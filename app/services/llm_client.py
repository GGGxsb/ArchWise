from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import urlparse

import httpx

from app.models.schemas import CandidateEvaluation, ExtractedFeatures


class LLMClient:
    """OpenAI-compatible LLM adapter. DeepSeek, Qwen compatible gateways can use it."""

    def __init__(self) -> None:
        self.api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = (os.getenv("LLM_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.model = os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS") or os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "12"))
        self.chat_url = self._build_chat_url(self.base_url)
        self.last_error: str | None = None

    async def generate_report(
        self,
        requirement: str,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
    ) -> str | None:
        if not self.api_key:
            return None

        prompt = self._build_prompt(requirement, features, candidates)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是软件体系结构评审专家，输出简洁、可追溯、适合课程作业展示的中文报告。"},
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0.2,
            "stream": False,
        }
        try:
            return await self._chat(payload)
        except Exception:
            return None

    async def stream_report(
        self,
        requirement: str,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
    ) -> AsyncGenerator[str, None]:
        if not self.api_key:
            return

        prompt = self._build_prompt(requirement, features, candidates)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是软件体系结构评审专家，输出简洁、可追溯、适合课程作业展示的中文报告。"},
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0.2,
            "stream": True,
        }
        async for chunk in self._stream_chat(payload):
            yield chunk

    async def generate_topology(
        self,
        requirement: str,
        features: ExtractedFeatures,
        winner: CandidateEvaluation,
    ) -> str | None:
        if not self.api_key:
            return None

        prompt = (
            "请根据本次软件需求和最终推荐架构，生成一张定制化 Mermaid 架构拓扑图。\n"
            "只返回 Mermaid 源码，不要 Markdown 代码块，不要解释。\n"
            "要求：\n"
            "1. 使用 flowchart LR 或 flowchart TD。\n"
            "2. 节点必须体现本需求中的业务模块、数据存储、消息/事件通道、外部客户端或第三方服务。\n"
            "3. 节点文字使用中文，控制在 2-8 个字。\n"
            "4. 不要使用括号、引号、emoji 或特殊符号，避免 Mermaid 渲染失败。\n\n"
            f"需求：{requirement}\n"
            f"抽取特征：{features.model_dump_json()}\n"
            f"最终推荐：{winner.model_dump()}\n"
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是软件架构图生成 Agent，只输出合法 Mermaid flowchart 源码。"},
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0.2,
            "stream": False,
            "max_tokens": 1000,
        }
        content = await self._chat(payload)
        if not content:
            return None
        return self._sanitize_mermaid(content)

    async def extract_capabilities(
        self,
        requirement: str,
        features: ExtractedFeatures,
    ) -> list[str]:
        if not self.api_key:
            return []

        prompt = (
            "请从软件需求中提取架构拓扑所需的业务能力模块，只返回 JSON，不要 Markdown。\n"
            "格式：{\"capabilities\":[\"能力1\",\"能力2\"]}\n"
            "能力名称使用 2-6 个中文字符，优先返回业务能力，不要返回抽象质量属性。\n"
            "例如社交媒体应包含 Feed、关系、内容、互动、评论、私信、推荐、审核。\n\n"
            f"需求：{requirement}\n"
            f"特征：{features.model_dump_json()}\n"
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是架构能力识别 Agent，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0.1,
            "stream": False,
            "response_format": {"type": "json_object"},
            "max_tokens": 800,
        }
        content = await self._chat(payload)
        if not content:
            return []
        try:
            data = self._extract_json(content)
            capabilities = data.get("capabilities", [])
            return [str(item).strip() for item in capabilities if str(item).strip()]
        except Exception:
            return []

    async def extract_features(
        self,
        requirement: str,
        rule_features: ExtractedFeatures,
    ) -> ExtractedFeatures | None:
        if not self.api_key:
            return None

        prompt = (
            "请从软件需求中抽取体系结构推荐所需特征，并只返回 JSON，不要 Markdown。\n"
            "JSON 字段必须为：domain, keywords, quality_attributes, constraints, data_flow, ambiguity_notes。\n"
            "quality_attributes 必须包含 concurrency, realtime, reliability, scalability, data_intensity, ai_reasoning，值为 0 到 1。\n"
            "data_flow 只能是 event_stream, pipeline, transactional, request_response 之一。\n"
            "constraints 至少包含 scale_mentions, deployment, requires_high_availability, requires_future_extension。\n\n"
            "示例 JSON：\n"
            "{\"domain\":\"即时通信\",\"keywords\":[\"实时\"],\"quality_attributes\":{\"concurrency\":0.8,\"realtime\":1,\"reliability\":0.7,\"scalability\":0.8,\"data_intensity\":0.2,\"ai_reasoning\":0},\"constraints\":{\"scale_mentions\":[\"万人\"],\"deployment\":[\"跨平台\"],\"requires_high_availability\":true,\"requires_future_extension\":true},\"data_flow\":\"event_stream\",\"ambiguity_notes\":[\"未说明部署环境\"]}\n\n"
            f"原始需求：{requirement}\n"
            f"本地规则初步结果：{rule_features.model_dump_json()}\n"
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是软件架构需求分析 Agent，擅长把模糊中文需求转为结构化架构特征。"},
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0.1,
            "stream": False,
            "response_format": {"type": "json_object"},
            "max_tokens": 1200,
        }
        content = await self._chat(payload)
        if not content:
            return None
        try:
            return ExtractedFeatures(**self._extract_json(content))
        except Exception:
            return None

    async def review_candidates(
        self,
        requirement: str,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
    ) -> list[str]:
        if not self.api_key:
            return []

        prompt = (
            "请作为架构评审 Agent，复核候选架构排序是否合理。只返回 3 条以内中文短句，指出补充理由或风险，不要改分。\n\n"
            f"需求：{requirement}\n"
            f"特征：{features.model_dump_json()}\n"
            f"候选：{[item.model_dump() for item in candidates]}\n"
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是谨慎的软件体系结构评审专家，输出简洁可追溯的复核意见。"},
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0.2,
            "stream": False,
        }
        content = await self._chat(payload)
        if not content:
            return []
        return [line.strip("- 1234567890.、") for line in content.splitlines() if line.strip()][:3]

    async def propose_topology_knowledge_patch(
        self,
        requirement: str,
        features: ExtractedFeatures,
        coverage: dict[str, Any],
        graph_knowledge: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not self.api_key:
            return None

        prompt = (
            "你是软件架构知识图谱补全 Agent。当前系统要生成架构拓扑图，但 Neo4j 知识覆盖率不足。\n"
            "请根据用户需求、已抽取特征、已有图谱知识和缺失组件，补全领域能力、架构组件、数据存储和依赖关系。\n"
            "只返回 JSON，不要 Markdown，不要解释。\n\n"
            "JSON 格式必须为：\n"
            "{\n"
            "  \"capabilities\": [{\"name\":\"能力名\", \"components\":[\"组件名\"], \"stores\":[\"存储名\"]}],\n"
            "  \"components\": [\"组件名\"],\n"
            "  \"stores\": [\"存储名\"],\n"
            "  \"edges\": [{\"source\":\"源组件\", \"target\":\"目标组件\", \"label\":\"关系\", \"kind\":\"sync|event\"}],\n"
            "  \"reason\": \"一句话说明补全依据\"\n"
            "}\n\n"
            "约束：\n"
            "1. 组件名称使用中文，2 到 8 个字。\n"
            "2. 只补充和本需求直接相关的组件，避免泛化过度。\n"
            "3. 高并发/秒杀场景必须考虑缓存、消息队列或事件总线。\n"
            "4. 最终一致性场景必须考虑事件关系或异步消息关系。\n"
            "5. 支付/订单/库存/物流等业务能力需要体现服务和数据存储。\n\n"
            f"用户需求：{requirement}\n"
            f"需求特征：{features.model_dump_json()}\n"
            f"覆盖率评估：{json.dumps(coverage, ensure_ascii=False)}\n"
            f"已有图谱知识：{json.dumps(graph_knowledge, ensure_ascii=False)}\n"
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是谨慎的软件架构知识图谱补全 Agent，只输出可解析 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0.1,
            "stream": False,
            "response_format": {"type": "json_object"},
            "max_tokens": 1400,
        }
        content = await self._chat(payload)
        if not content:
            return None
        try:
            data = self._extract_json(content)
            return self._sanitize_topology_patch(data)
        except Exception:
            return None

    @staticmethod
    def _build_prompt(requirement: str, features: ExtractedFeatures, candidates: list[CandidateEvaluation]) -> str:
        return (
            "请基于以下需求分析和候选架构，只生成“适配理由补充”部分的 Markdown 内容。\n"
            "严格要求：\n"
            "1. 不要输出标题，不要输出完整报告。\n"
            "2. 不要输出对比表格，表格由系统生成。\n"
            "3. 输出 3 到 5 条要点，每条使用 '- ' 开头。\n"
            "4. 每条要点必须包含加粗关键词，例如 **高并发**。\n"
            "5. 聚焦需求特征、候选差异、最终推荐可信度、主要风险和落地关注点。\n\n"
            f"原始需求：{requirement}\n"
            f"抽取特征：{features.model_dump_json()}\n"
            f"候选架构：{[item.model_dump() for item in candidates]}\n"
        )

    @staticmethod
    def _sanitize_topology_patch(data: dict[str, Any]) -> dict[str, Any]:
        def clean_list(items) -> list[str]:
            if not isinstance(items, list):
                return []
            return [str(item).strip() for item in items if str(item).strip()][:16]

        capabilities = []
        for item in data.get("capabilities", []):
            if isinstance(item, dict):
                name = str(item.get("name", "")).strip()
                if name:
                    capabilities.append(
                        {
                            "name": name,
                            "components": clean_list(item.get("components", [])),
                            "stores": clean_list(item.get("stores", [])),
                        }
                    )
            elif str(item).strip():
                capabilities.append({"name": str(item).strip(), "components": [], "stores": []})

        edges = []
        for item in data.get("edges", []):
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "")).strip()
            target = str(item.get("target", "")).strip()
            if not source or not target:
                continue
            kind = str(item.get("kind", "sync")).strip()
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "label": str(item.get("label", "依赖")).strip() or "依赖",
                    "kind": "event" if kind == "event" else "sync",
                }
            )

        return {
            "capabilities": capabilities[:12],
            "components": clean_list(data.get("components", [])),
            "stores": clean_list(data.get("stores", [])),
            "edges": edges[:24],
            "reason": str(data.get("reason", "")).strip()[:160],
        }

    async def _chat(self, payload: dict[str, Any]) -> str | None:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            self.last_error = None
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.chat_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            self.last_error = str(exc)
            return None

    async def _stream_chat(self, payload: dict[str, Any]) -> AsyncGenerator[str, None]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            self.last_error = None
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", self.chat_url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line.removeprefix("data:").strip()
                        if data == "[DONE]":
                            break
                        try:
                            payload = json.loads(data)
                            delta = payload["choices"][0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                yield content
                        except Exception:
                            continue
        except Exception as exc:
            self.last_error = str(exc)

    async def ping(self) -> dict[str, Any]:
        if not self.api_key:
            return {"configured": False, "ok": False, "model": self.model, "base_url": self.base_url}

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a health check endpoint. Reply with ok."},
                {"role": "user", "content": "ping"},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": 8,
            "stream": False,
        }
        content = await self._chat(payload)
        return {
            "configured": True,
            "ok": bool(content),
            "model": self.model,
            "base_url": self.base_url,
            "chat_url": self.chat_url,
            "error": None if content else self.last_error,
        }

    @staticmethod
    def _build_chat_url(base_url: str) -> str:
        parsed = urlparse(base_url)
        path = parsed.path.rstrip("/")
        if path.endswith("/chat/completions"):
            return base_url
        if path.endswith("/v1"):
            return f"{base_url}/chat/completions"
        return f"{base_url}/chat/completions"

    @staticmethod
    def _extract_json(content: str) -> dict[str, Any]:
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.S)
        if fenced:
            content = fenced.group(1)
        else:
            start = content.find("{")
            end = content.rfind("}")
            content = content[start : end + 1] if start >= 0 and end >= start else content
        return json.loads(content)

    @staticmethod
    def _sanitize_mermaid(content: str) -> str:
        fenced = re.search(r"```(?:mermaid)?\s*(.*?)\s*```", content, flags=re.S)
        if fenced:
            content = fenced.group(1)
        lines = [line.rstrip() for line in content.strip().splitlines() if line.strip()]
        if not lines:
            return ""
        if not lines[0].startswith("flowchart"):
            lines.insert(0, "flowchart LR")
        return "\n".join(lines)
