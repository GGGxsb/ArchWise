from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import urlparse

import httpx

from app.models.schemas import (
    CandidateEvaluation,
    ComponentDef,
    ConnectionDef,
    ExtractedFeatures,
    StyleInstance,
    StyleSchema,
)

_DEFAULT_TIMEOUT = object()


class LLMClient:
    """OpenAI-compatible LLM adapter. DeepSeek, Qwen compatible gateways can use it."""

    def __init__(self) -> None:
        self.api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = (os.getenv("LLM_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.model = os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS") or os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "12"))
        self.chat_url = self._build_chat_url(self.base_url)
        self.embedding_api_key = os.getenv("EMBEDDING_API_KEY") or self.api_key
        self.embedding_base_url = (os.getenv("EMBEDDING_BASE_URL") or "").rstrip("/")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "")
        self.embedding_url = self._build_embedding_url(self.embedding_base_url) if self.embedding_base_url else ""
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

    async def recommend_architectures(
        self,
        requirement: str,
        features: ExtractedFeatures,
        styles: list[dict[str, Any]],
        top_k: int,
    ) -> tuple[list[CandidateEvaluation], dict[str, Any]] | None:
        if not self.api_key:
            self.last_error = "DeepSeek API Key 未配置，无法进行架构匹配。"
            return None

        candidate_count = max(3, min(top_k, 6))
        style_payload = [
            {
                "id": style.get("id"),
                "name": style.get("name"),
                "category": style.get("category"),
                "description": style.get("description"),
                "suitable_for": style.get("suitable_for", []),
                "quality_scores": style.get("quality_scores", {}),
            }
            for style in styles
        ]
        prompt = (
            "你是架构匹配 Agent。请完全基于用户需求、结构化特征和候选架构知识库，推荐候选体系结构风格。\n"
            "只返回 JSON，不要 Markdown，不要解释。\n\n"
            "输出 JSON Schema：\n"
            "{\n"
            "  \"candidates\": [\n"
            "    {\n"
            "      \"style_id\": \"必须来自候选架构 id\",\n"
            "      \"name\": \"架构中文名\",\n"
            "      \"score\": 0到100,\n"
            "      \"raw_score\": 0到100,\n"
            "      \"recommendation_role\": \"核心推荐|备选方案|专项补充|不推荐\",\n"
            "      \"confidence\": \"高|中高|中|中低|低\",\n"
            "      \"matched_reasons\": [\"理由\"],\n"
            "      \"risks\": [\"风险\"],\n"
            "      \"deductions\": [\"扣分原因\"],\n"
            "      \"quality_scores\": {\"scalability\":0到1,\"performance\":0到1,\"reliability\":0到1,\"modifiability\":0到1,\"complexity\":0到1,\"realtime\":0到1}\n"
            "    }\n"
            "  ],\n"
            "  \"composition_recommendation\": {\n"
            "    \"composition_needed\": true或false,\n"
            "    \"primary_style\": \"主架构\",\n"
            "    \"supporting_styles\": [{\"style_id\":\"id\",\"style\":\"名称\",\"role\":\"职责\",\"apply_to\":[\"组件或能力\"],\"reason\":\"原因\",\"score\":0到100}],\n"
            "    \"reason\": \"组合或不组合原因\",\n"
            "    \"triggers\": [\"触发依据\"],\n"
            "    \"overengineering_warnings\": [\"过度设计提醒\"]\n"
            "  },\n"
            "  \"review_notes\": [\"候选排序复核意见\"]\n"
            "}\n\n"
            "约束：\n"
            f"1. candidates 必须返回 {candidate_count} 个。\n"
            "2. style_id 必须来自候选架构知识库，不能编造。\n"
            "3. 简单架构能实现的需求就不应考虑复杂架构。分层、MVC、单体等方案能胜任时，不应为了「架构看起来先进」而引入微服务、事件驱动、CQRS 等重型方案。优先选择能满足需求的最简架构。\n"
            "4. 每个推荐方案必须深度评估技术债和长期维护成本：引入的复杂度代价、团队规模匹配度、数据一致性代价、部署与调试成本。\n"
            "5. 只有在高并发、强实时、多团队独立交付、或最终一致性等硬需求明确存在时，才可以推荐微服务、事件驱动或 CQRS。\n"
            "6. score 必须拉开合理差距，不要所有架构都给 100。\n\n"
            f"用户需求：{requirement}\n"
            f"结构化特征：{features.model_dump_json()}\n"
            f"候选架构知识库：{json.dumps(style_payload, ensure_ascii=False)}\n"
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是软件体系结构风格匹配 Agent，只输出可解析 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0.1,
            "stream": False,
            "response_format": {"type": "json_object"},
            "max_tokens": 3200,
        }
        content = await self._chat(payload)
        if not content:
            if not self.last_error:
                self.last_error = "DeepSeek 架构匹配返回空内容，请稍后重试或检查模型是否支持 JSON 输出。"
            return None
        try:
            data = self._extract_json(content)
            return self._sanitize_architecture_recommendation(data, styles, candidate_count)
        except Exception as exc:
            self.last_error = f"DeepSeek 架构匹配 JSON 校验失败：{exc}"
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

    async def extract_features(
        self,
        requirement: str,
    ) -> ExtractedFeatures | None:
        if not self.api_key:
            self.last_error = "DeepSeek API Key 未配置，无法进行需求解析。"
            return None

        content = await self._request_feature_extraction(requirement, strict=False)
        features = self._parse_extracted_features(requirement, content)
        if features:
            return features

        content = await self._request_feature_extraction(requirement, strict=True)
        return self._parse_extracted_features(requirement, content)

    async def _request_feature_extraction(self, requirement: str, strict: bool = False) -> str | None:
        strict_rules = (
            "严格补充要求：\n"
            "1. 必须从用户需求中按业务动作拆出 4 到 8 个业务能力，例如录入、查询、选择、下单、审核、核验、扣费、统计、提醒等。\n"
            "2. topology_expectations.component_specs 必须覆盖每个业务能力对应的服务组件和数据存储，并为每个组件明确 type、layer、owned_by。\n"
            "3. topology_expectations.relation_specs 必须体现主要业务链路，例如录入->库存、服务->数据存储、事件发布/订阅等。\n"
            "4. 不能只返回订单服务、库存服务这类过少组件；对租借、领用、预约、审批、归还、扣费、统计等普通业务系统也要完整拆分。\n\n"
            if strict
            else ""
        )
        prompt = (
            "请作为主需求解析器，从软件需求中抽取体系结构推荐所需结构化特征，并只返回 JSON，不要 Markdown。\n"
            "重要：下面 input.requirement 字段就是原始需求，必须逐字读取并围绕它抽取领域、关键词、业务能力和质量属性。\n"
            "如果 input.requirement 非空，不允许把需求判定为空，也不允许返回空的 business_capabilities。\n"
            "JSON 字段必须为：domain, keywords, business_capabilities, architecture_drivers, topology_expectations, quality_attributes, constraints, data_flow, ambiguity_notes。\n"
            "business_capabilities 必须是具体业务能力，不要写“业务处理”“数据处理”等泛化词；应覆盖用户、商家、管理员等角色的关键业务动作。\n"
            "architecture_drivers 表示影响架构选型的驱动因素，例如高并发、弹性伸缩、最终一致性、灰度发布。\n"
            "topology_expectations 必须包含 must_have_components, must_have_relations, quality_infrastructure, component_specs, relation_specs。\n"
            "component_specs 数组项格式：{\"name\":\"组件名\",\"type\":\"service|data_store|gateway|infrastructure|event_bus|cache|external\",\"layer\":\"access|business|data|event|governance\",\"owned_by\":\"所属服务名或空字符串\"}。\n"
            "relation_specs 数组项格式：{\"source\":\"源组件\",\"target\":\"目标组件\",\"label\":\"关系说明\",\"kind\":\"sync|event|data\"}。\n"
            "数据库、台账、记录、缓存等数据存储必须由 DeepSeek 在 component_specs 中标注为 type=data_store/layer=data，并通过 relation_specs 连接到所属业务服务，不能连接到 API 网关。\n"
            "quality_attributes 必须包含 concurrency, realtime, reliability, scalability, data_intensity, ai_reasoning，值为 0 到 1。\n"
            "data_flow 只能是 event_stream, pipeline, transactional, request_response 之一。\n"
            "constraints 至少包含 scale_mentions, deployment, requires_high_availability, requires_future_extension。\n\n"
            f"{strict_rules}"
            "示例 JSON：\n"
            "{\"domain\":\"电商交易\",\"keywords\":[\"秒杀\",\"支付\",\"库存\"],\"business_capabilities\":[\"商品浏览\",\"购物车\",\"订单管理\",\"支付结算\",\"库存一致性\",\"秒杀活动\",\"物流跟踪\"],\"architecture_drivers\":[\"高并发\",\"弹性伸缩\",\"最终一致性\",\"灰度发布\"],\"topology_expectations\":{\"must_have_components\":[\"订单服务\",\"订单数据库\",\"支付服务\",\"支付数据库\",\"库存服务\",\"库存数据库\",\"秒杀服务\",\"消息队列\"],\"must_have_relations\":[\"订单服务->支付服务\",\"订单服务->库存服务\",\"订单服务->订单数据库\",\"支付服务->支付数据库\",\"库存服务->库存数据库\",\"秒杀服务->消息队列\"],\"quality_infrastructure\":[\"负载均衡\",\"缓存集群\",\"监控服务\"],\"component_specs\":[{\"name\":\"订单服务\",\"type\":\"service\",\"layer\":\"business\",\"owned_by\":\"\"},{\"name\":\"订单数据库\",\"type\":\"data_store\",\"layer\":\"data\",\"owned_by\":\"订单服务\"},{\"name\":\"支付服务\",\"type\":\"service\",\"layer\":\"business\",\"owned_by\":\"\"},{\"name\":\"支付数据库\",\"type\":\"data_store\",\"layer\":\"data\",\"owned_by\":\"支付服务\"},{\"name\":\"库存服务\",\"type\":\"service\",\"layer\":\"business\",\"owned_by\":\"\"},{\"name\":\"库存数据库\",\"type\":\"data_store\",\"layer\":\"data\",\"owned_by\":\"库存服务\"},{\"name\":\"秒杀服务\",\"type\":\"service\",\"layer\":\"business\",\"owned_by\":\"\"},{\"name\":\"消息队列\",\"type\":\"event_bus\",\"layer\":\"event\",\"owned_by\":\"\"}],\"relation_specs\":[{\"source\":\"订单服务\",\"target\":\"支付服务\",\"label\":\"支付\",\"kind\":\"sync\"},{\"source\":\"订单服务\",\"target\":\"订单数据库\",\"label\":\"读写\",\"kind\":\"data\"},{\"source\":\"支付服务\",\"target\":\"支付数据库\",\"label\":\"读写\",\"kind\":\"data\"},{\"source\":\"库存服务\",\"target\":\"库存数据库\",\"label\":\"读写\",\"kind\":\"data\"},{\"source\":\"秒杀服务\",\"target\":\"消息队列\",\"label\":\"发布事件\",\"kind\":\"event\"}]},\"quality_attributes\":{\"concurrency\":0.95,\"realtime\":0.4,\"reliability\":0.85,\"scalability\":0.9,\"data_intensity\":0.65,\"ai_reasoning\":0},\"constraints\":{\"scale_mentions\":[\"每秒数万笔订单\"],\"deployment\":[\"微服务\",\"独立部署\",\"灰度发布\"],\"requires_high_availability\":true,\"requires_future_extension\":true},\"data_flow\":\"transactional\",\"ambiguity_notes\":[]}\n\n"
            "待解析输入：\n"
            f"{json.dumps({'requirement': requirement}, ensure_ascii=False)}\n"
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
            "max_tokens": 1800 if strict else 1200,
        }
        return await self._chat(payload)

    def _parse_extracted_features(self, requirement: str, content: str | None) -> ExtractedFeatures | None:
        if not content:
            return None
        try:
            data = self._extract_json(content)
            features = ExtractedFeatures(**data)
            features = self._normalize_topology_expectations(features)
            if not self._features_consistent_with_requirement(requirement, features):
                self.last_error = "DeepSeek 需求解析结果与输入不一致：输入需求非空，但模型返回了空需求或未提取到有效业务特征。"
                return None
            return features
        except Exception as exc:
            self.last_error = f"DeepSeek 需求解析 JSON 校验失败：{exc}"
            return None

    # ── Style-aware topology extraction ──────────────────────────

    async def extract_style_instance(
        self,
        requirement: str,
        features: ExtractedFeatures,
        schema: StyleSchema,
        composition_mode: bool = False,
    ) -> StyleInstance | None:
        """Ask the LLM to fill a StyleInstance by mapping domain components to
        the layers declared in *schema*, with connections obeying the style's
        connection rules.

        Returns None when the LLM is unavailable or returns unparseable JSON.
        """
        if not self.api_key:
            return None

        layers_desc = "\n".join(
            f"  - {layer.layer_id}（{layer.label}）：{layer.description}"
            f"{' [单例，只能有1个组件]' if layer.singleton else ''}"
            f"{'，至少' + str(layer.min_components) + '个组件' if layer.min_components > 1 else ''}"
            for layer in schema.layers
        )
        connection_desc = "\n".join(
            f"  - {rule.source_layer} → {rule.target_layer}（{rule.kind}）：{rule.label}"
            + (" [禁止跨层]" if not rule.allow_skip else "")
            for rule in schema.layer_connections[:12]
        )

        prompt = (
            f"你是架构拓扑实例化 Agent。当前推荐的架构风格是「{schema.style_name}」。\n"
            "请根据用户需求，将具体业务组件填充到该风格的层结构中，并定义组件间连接。\n"
            "只返回 JSON，不要 Markdown，不要解释。\n\n"
            f"风格结构说明：\n{layers_desc}\n\n"
            f"连接规则：\n{connection_desc}\n\n"
            f"风格约束提示：{schema.prompt_hints}\n\n"
            "JSON Schema：\n"
            "{\n"
            '  "style_id": "风格ID",\n'
            '  "components": [\n'
            '    {"name": "组件中文名", "layer_id": "所属层ID", "component_type": "service|data_store|gateway|event_bus|cache|external|infrastructure"}\n'
            "  ],\n"
            '  "connections": [\n'
            '    {"source": "源组件名", "target": "目标组件名", "kind": "sync|event|data", "label": "关系说明"}\n'
            "  ],\n"
            '  "notes": "一句话设计说明"\n'
            "}\n\n"
            "严格要求：\n"
            "1. 组件名使用 2-8 个中文字符，必须体现具体业务职能。\n"
            "2. 每个 mandatory 层至少有一个组件，单例层不超过一个。\n"
            "3. 连接必须遵守上面的连接规则，不要违反禁止跨层的约束。\n"
            "4. 数据存储（数据库、缓存、台账等）必须标注 component_type=data_store。\n"
            "5. 不要编造不在需求中的组件，但可以补充必要的基础设施组件。\n\n"
            f"用户需求：{requirement}\n"
            f"结构化特征：{features.model_dump_json()}\n"
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": f"你是「{schema.style_name}」拓扑实例化 Agent，只输出可解析 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0.1,
            "stream": False,
            "response_format": {"type": "json_object"},
            "max_tokens": 2000 if composition_mode else 1600,
        }
        content = await self._chat(payload)
        if not content:
            return None
        try:
            data = self._extract_json(content)
            return self._parse_style_instance(data, schema.style_id)
        except Exception as exc:
            self.last_error = f"StyleInstance JSON 解析失败：{exc}"
            return None

    @staticmethod
    def _parse_style_instance(data: dict[str, Any], expected_style_id: str) -> StyleInstance:
        components: list[ComponentDef] = []
        for item in data.get("components", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            components.append(ComponentDef(
                name=name,
                layer_id=str(item.get("layer_id", "")).strip(),
                component_type=str(item.get("component_type", "service")).strip() or "service",
            ))

        connections: list[ConnectionDef] = []
        for item in data.get("connections", []):
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "")).strip()
            target = str(item.get("target", "")).strip()
            if not source or not target:
                continue
            kind = str(item.get("kind", "sync")).strip()
            connections.append(ConnectionDef(
                source=source,
                target=target,
                kind=kind if kind in {"sync", "event", "data"} else "sync",
                label=str(item.get("label", "")).strip(),
            ))

        return StyleInstance(
            style_id=data.get("style_id", expected_style_id),
            components=components,
            connections=connections,
            notes=str(data.get("notes", "")).strip(),
        )

    async def propose_topology_knowledge_patch(
        self,
        requirement: str,
        features: ExtractedFeatures,
        coverage: dict[str, Any],
        graph_knowledge: dict[str, Any],
        request_timeout: float | None | object = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any] | None:
        if not self.api_key:
            return None

        prompt = (
            "你是软件架构知识图谱补全 Agent。当前系统要生成架构拓扑图，但 Neo4j 知识覆盖率不足。\n"
            "请根据用户需求、已抽取特征、已有图谱知识和多维覆盖率缺口，补全领域能力、架构组件、数据存储和依赖关系。\n"
            "只返回 JSON，不要 Markdown，不要解释。\n\n"
            "JSON 格式必须为：\n"
            "{\n"
            "  \"scenario_id\": \"领域场景英文或拼音标识\",\n"
            "  \"scenario_name\": \"领域场景中文名\",\n"
            "  \"capabilities\": [\n"
            "    {\"name\":\"能力名\", \"components\":[\"组件名\"], \"stores\":[\"存储名\"], "
            "\"edges\":[{\"source\":\"源组件\", \"target\":\"目标组件或存储\", \"label\":\"关系\", \"kind\":\"sync|event\"}]}\n"
            "  ],\n"
            "  \"components\": [\"组件名\"],\n"
            "  \"stores\": [\"存储名\"],\n"
            "  \"edges\": [{\"source\":\"源组件\", \"target\":\"目标组件\", \"label\":\"关系\", \"kind\":\"sync|event\"}],\n"
            "  \"reason\": \"一句话说明补全依据\"\n"
            "}\n\n"
            "约束：\n"
            "1. 组件名称使用中文，2 到 8 个字。\n"
            "2. 只补充和本需求直接相关的组件，避免泛化过度。\n"
            "3. scenario_id 必须代表当前需求场景，不要复用无关场景；无法归入已有领域时生成新的稳定标识。\n"
            "4. 每个 capability 必须按业务能力独立成组，组内给出该能力自己的组件、存储和关键边。\n"
            "5. 高并发/秒杀场景必须考虑缓存、消息队列或事件总线。\n"
            "6. 最终一致性场景必须考虑事件关系或异步消息关系。\n"
            "7. 支付/订单/库存/物流等业务能力需要体现服务和数据存储。\n\n"
            "强约束：\n"
            "1. coverage.missing_capabilities 中的每一个业务能力都必须在 capabilities 数组中逐项出现，"
            "不要合并成“消息处理”“业务处理”“数据处理”等泛化能力名。\n\n"
            "2. coverage.missing_components 中的组件应尽量出现在 components、capabilities.components 或 stores 中。\n"
            "3. coverage.missing_relations 中使用“源->目标”格式的关系，应尽量在 edges 中用完全相同的 source 和 target 补齐。\n"
            "4. coverage.missing_quality_infrastructure 中的高并发、高可用、可扩展基础设施应显式补齐。\n\n"
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
        content = await self._chat(payload, request_timeout=request_timeout)
        if not content:
            return None
        try:
            data = self._extract_json(content)
            return self._sanitize_topology_patch(data)
        except Exception:
            return None

    async def review_topology_coverage_gap(
        self,
        requirement: str,
        features: ExtractedFeatures,
        graph_knowledge: dict[str, Any],
        request_timeout: float | None | object = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any] | None:
        if not self.api_key:
            return None

        prompt = (
            "你是架构拓扑完整性复核 Agent。请对照原始需求和当前拓扑知识，找出当前架构图漏掉的业务能力、组件、数据存储和关系。\n"
            "只返回 JSON，不要 Markdown，不要解释。\n\n"
            "判断原则：\n"
            "1. 必须覆盖原始需求中的每个关键业务动作，例如录入、选择日期、下单、归还、核验、扣费、统计、提醒、审核等。\n"
            "2. 如果当前 graph_knowledge 已覆盖某能力，不要重复补。\n"
            "3. 只补与当前需求直接相关的内容，不要泛化成无关平台能力。\n\n"
            "JSON 格式与知识补丁一致：\n"
            "{\n"
            "  \"scenario_id\":\"场景标识\",\n"
            "  \"scenario_name\":\"场景名称\",\n"
            "  \"capabilities\":[{\"name\":\"能力名\",\"components\":[\"组件\"],\"stores\":[\"存储\"],\"edges\":[{\"source\":\"源\",\"target\":\"目标\",\"label\":\"关系\",\"kind\":\"sync|event\"}]}],\n"
            "  \"components\":[\"组件\"],\n"
            "  \"stores\":[\"存储\"],\n"
            "  \"edges\":[{\"source\":\"源\",\"target\":\"目标\",\"label\":\"关系\",\"kind\":\"sync|event\"}],\n"
            "  \"reason\":\"一句话说明\"\n"
            "}\n"
            "如果没有缺口，返回空数组字段。\n\n"
            f"原始需求：{requirement}\n"
            f"结构化特征：{features.model_dump_json()}\n"
            f"当前拓扑知识：{json.dumps(graph_knowledge, ensure_ascii=False)}\n"
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是谨慎的软件架构拓扑复核 Agent，只输出可解析 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0.1,
            "stream": False,
            "response_format": {"type": "json_object"},
            "max_tokens": 1400,
        }
        content = await self._chat(payload, request_timeout=request_timeout)
        if not content:
            return None
        try:
            return self._sanitize_topology_patch(self._extract_json(content))
        except Exception:
            return None

    async def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        """Generate embeddings through an OpenAI-compatible embedding endpoint.

        DeepSeek chat endpoints do not guarantee embedding support, so the
        embedding service is configured independently. If it is not configured,
        callers should avoid permanent semantic merge decisions instead of
        falling back to string rules.
        """
        if not texts:
            return []
        if not (self.embedding_api_key and self.embedding_url and self.embedding_model):
            self.last_error = "Embedding 服务未配置，无法进行语义近义节点召回。"
            return None

        headers = {"Authorization": f"Bearer {self.embedding_api_key}", "Content-Type": "application/json"}
        # Qwen text-embedding-v4 supports at most 10 input strings per request.
        batches = [texts[index : index + 10] for index in range(0, len(texts), 10)]
        vectors: list[list[float]] = []
        try:
            self.last_error = None
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for batch in batches:
                    payload = {"model": self.embedding_model, "input": batch}
                    response = await client.post(self.embedding_url, headers=headers, json=payload)
                    if response.status_code >= 400:
                        self.last_error = f"Embedding 服务调用失败：HTTP {response.status_code}，{response.text[:500]}"
                        return None
                    data = response.json()
                    rows = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
                    batch_vectors = [item.get("embedding") for item in rows]
                    if len(batch_vectors) != len(batch) or any(not isinstance(vector, list) for vector in batch_vectors):
                        self.last_error = "Embedding 服务返回结构不符合 OpenAI-compatible 格式。"
                        return None
                    vectors.extend(batch_vectors)
            return vectors
        except Exception as exc:
            self.last_error = str(exc)
            return None

    async def adjudicate_semantic_merge(
        self,
        requirement: str,
        candidate_node: dict[str, Any],
        top_matches: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not self.api_key:
            return None

        prompt = (
            "你是软件架构知识图谱节点消歧 Agent。请判断 LLM 新生成的节点是否应与 Neo4j 中已有节点合并。\n"
            "只返回 JSON，不要 Markdown，不要解释。\n\n"
            "判断原则：\n"
            "1. 只比较同一种节点类型，不能跨类型合并。\n"
            "2. 名称不同但业务语义、职责、上下游关系一致时可以 merge。\n"
            "3. 语义接近但无法确认是否同一职责时返回 temporary，表示仅本次临时使用，不写入 Neo4j。\n"
            "4. 明确是不同能力、组件或存储时返回 create。\n\n"
            "JSON 格式：\n"
            "{\"decision\":\"merge|create|temporary\",\"canonical\":\"已有节点名或新节点名\",\"confidence\":0.0,\"reason\":\"一句话理由\"}\n\n"
            f"用户需求：{requirement}\n"
            f"新节点：{json.dumps(candidate_node, ensure_ascii=False)}\n"
            f"Neo4j Top-K 候选：{json.dumps(top_matches, ensure_ascii=False)}\n"
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是谨慎的软件架构知识图谱节点消歧 Agent，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0.05,
            "stream": False,
            "response_format": {"type": "json_object"},
            "max_tokens": 500,
        }
        content = await self._chat(payload)
        if not content:
            return None
        try:
            data = self._extract_json(content)
            decision = str(data.get("decision", "")).strip().lower()
            if decision not in {"merge", "create", "temporary"}:
                return None
            confidence = float(data.get("confidence", 0))
            return {
                "decision": decision,
                "canonical": str(data.get("canonical", "")).strip(),
                "confidence": max(0.0, min(1.0, confidence)),
                "reason": str(data.get("reason", "")).strip()[:160],
            }
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

        flattened_edges = []
        capabilities = []
        for item in data.get("capabilities", []):
            if isinstance(item, dict):
                name = str(item.get("name", "")).strip()
                if name:
                    capability_edges = []
                    for edge in item.get("edges", []):
                        if not isinstance(edge, dict):
                            continue
                        source = str(edge.get("source", "")).strip()
                        target = str(edge.get("target", "")).strip()
                        if not source or not target:
                            continue
                        kind = str(edge.get("kind", "sync")).strip()
                        clean_edge = {
                            "source": source,
                            "target": target,
                            "label": str(edge.get("label", "依赖")).strip() or "依赖",
                            "kind": "event" if kind == "event" else "sync",
                            "capability": name,
                        }
                        capability_edges.append(clean_edge)
                        flattened_edges.append(clean_edge)
                    capabilities.append(
                        {
                            "name": name,
                            "components": clean_list(item.get("components", [])),
                            "stores": clean_list(item.get("stores", [])),
                            "edges": capability_edges[:12],
                        }
                    )
            elif str(item).strip():
                capabilities.append({"name": str(item).strip(), "components": [], "stores": []})

        edges = []
        for item in list(data.get("edges", [])) + flattened_edges:
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
                    "capability": str(item.get("capability", "")).strip(),
                }
            )

        return {
            "scenario_id": str(data.get("scenario_id", "")).strip(),
            "scenario_name": str(data.get("scenario_name", "")).strip(),
            "capabilities": capabilities[:12],
            "components": clean_list(data.get("components", [])),
            "stores": clean_list(data.get("stores", [])),
            "edges": edges[:24],
            "reason": str(data.get("reason", "")).strip()[:160],
        }

    @staticmethod
    def _sanitize_architecture_recommendation(
        data: dict[str, Any],
        styles: list[dict[str, Any]],
        top_k: int,
    ) -> tuple[list[CandidateEvaluation], dict[str, Any]]:
        style_map = {str(style.get("id", "")).strip(): style for style in styles}
        candidates: list[CandidateEvaluation] = []
        limit = max(3, min(top_k, 12))
        seen: set[str] = set()
        for item in data.get("candidates", []):
            if not isinstance(item, dict):
                continue
            style_id = str(item.get("style_id", "")).strip()
            if style_id not in style_map or style_id in seen:
                continue
            seen.add(style_id)
            style = style_map[style_id]
            quality_scores = item.get("quality_scores")
            if not isinstance(quality_scores, dict):
                quality_scores = style.get("quality_scores", {})
            score = LLMClient._clamp_score(item.get("score", 0))
            raw_score = LLMClient._clamp_score(item.get("raw_score", score))
            candidates.append(
                CandidateEvaluation(
                    style_id=style_id,
                    name=str(item.get("name") or style.get("name") or style_id),
                    score=score,
                    raw_score=raw_score,
                    recommendation_role=LLMClient._clean_choice(
                        item.get("recommendation_role"),
                        {"核心推荐", "备选方案", "专项补充", "不推荐", "核心推荐/组合候选", "组合备选"},
                        "备选方案" if candidates else "核心推荐",
                    ),
                    confidence=LLMClient._clean_choice(
                        item.get("confidence"),
                        {"高", "中高", "中", "中低", "低"},
                        "中",
                    ),
                    matched_reasons=LLMClient._clean_text_list(item.get("matched_reasons", []), 5),
                    risks=LLMClient._clean_text_list(item.get("risks", []), 4),
                    deductions=LLMClient._clean_text_list(item.get("deductions", []), 4),
                    quality_scores={
                        key: max(0.0, min(1.0, float(quality_scores.get(key, 0))))
                        for key in ["scalability", "performance", "reliability", "modifiability", "complexity", "realtime"]
                    },
                )
            )
            if len(candidates) >= limit:
                break
        if len(candidates) < 3:
            raise ValueError("候选架构少于 3 个或 style_id 不在知识库中")
        candidates.sort(key=lambda item: item.score, reverse=True)
        candidates[0].recommendation_role = "核心推荐"
        composition = data.get("composition_recommendation", {})
        if not isinstance(composition, dict):
            composition = {}
        composition = {
            "composition_needed": bool(composition.get("composition_needed", False)),
            "primary_style": str(composition.get("primary_style") or candidates[0].name),
            "supporting_styles": [
                item for item in composition.get("supporting_styles", [])
                if isinstance(item, dict)
            ][:3],
            "reason": str(composition.get("reason", "")).strip(),
            "triggers": LLMClient._clean_text_list(composition.get("triggers", []), 6),
            "overengineering_warnings": LLMClient._clean_text_list(composition.get("overengineering_warnings", []), 6),
        }
        review_notes = LLMClient._clean_text_list(data.get("review_notes", []), 5)
        return candidates, {**composition, "review_notes": review_notes}

    @staticmethod
    def _clamp_score(value: Any) -> float:
        return round(max(0.0, min(100.0, float(value))), 1)

    @staticmethod
    def _clean_choice(value: Any, allowed: set[str], default: str) -> str:
        clean = str(value or "").strip()
        return clean if clean in allowed else default

    @staticmethod
    def _clean_text_list(items: Any, limit: int) -> list[str]:
        if not isinstance(items, list):
            return []
        return [str(item).strip() for item in items if str(item).strip()][:limit]

    @staticmethod
    def _features_consistent_with_requirement(requirement: str, features: ExtractedFeatures) -> bool:
        if not requirement.strip():
            return True
        empty_notes = any("原始需求为空" in str(note) for note in features.ambiguity_notes)
        empty_result = (
            features.domain.strip() in {"", "未知"}
            and not features.keywords
            and not features.business_capabilities
            and not features.architecture_drivers
        )
        return not (empty_notes or empty_result)

    @staticmethod
    def _normalize_topology_expectations(features: ExtractedFeatures) -> ExtractedFeatures:
        expectations = features.topology_expectations or {}
        components = [
            str(item).strip()
            for item in expectations.get("must_have_components", [])
            if str(item).strip()
        ]
        relations = [
            str(item).strip()
            for item in expectations.get("must_have_relations", [])
            if str(item).strip()
        ]
        quality_infrastructure = [
            str(item).strip()
            for item in expectations.get("quality_infrastructure", [])
            if str(item).strip()
        ]
        component_specs = LLMClient._sanitize_component_specs(expectations.get("component_specs", []))
        relation_specs = LLMClient._sanitize_relation_specs(expectations.get("relation_specs", []))
        for item in component_specs:
            if item["name"] not in components:
                components.append(item["name"])
        for item in relation_specs:
            relation = f"{item['source']}->{item['target']}"
            if relation not in relations:
                relations.append(relation)

        normalized = {
            "must_have_components": list(dict.fromkeys(components))[:24],
            "must_have_relations": list(dict.fromkeys(relations))[:24],
            "quality_infrastructure": list(dict.fromkeys(quality_infrastructure))[:12],
            "component_specs": component_specs[:32],
            "relation_specs": relation_specs[:40],
        }
        return features.model_copy(update={"topology_expectations": normalized})

    @staticmethod
    def _sanitize_component_specs(items: Any) -> list[dict[str, str]]:
        if not isinstance(items, list):
            return []
        allowed_types = {"service", "data_store", "gateway", "infrastructure", "event_bus", "cache", "external"}
        allowed_layers = {"access", "business", "data", "event", "governance"}
        result: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            component_type = str(item.get("type", "service")).strip()
            layer = str(item.get("layer", "business")).strip()
            result.append(
                {
                    "name": name,
                    "type": component_type if component_type in allowed_types else "service",
                    "layer": layer if layer in allowed_layers else "business",
                    "owned_by": str(item.get("owned_by", "")).strip(),
                }
            )
        return result

    @staticmethod
    def _sanitize_relation_specs(items: Any) -> list[dict[str, str]]:
        if not isinstance(items, list):
            return []
        result: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "")).strip()
            target = str(item.get("target", "")).strip()
            if not source or not target:
                continue
            kind = str(item.get("kind", "sync")).strip()
            result.append(
                {
                    "source": source,
                    "target": target,
                    "label": str(item.get("label", "依赖")).strip() or "依赖",
                    "kind": kind if kind in {"sync", "event", "data"} else "sync",
                }
            )
        return result

    async def _chat(
        self,
        payload: dict[str, Any],
        request_timeout: float | None | object = _DEFAULT_TIMEOUT,
    ) -> str | None:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        timeout = self.timeout if request_timeout is _DEFAULT_TIMEOUT else request_timeout
        try:
            self.last_error = None
            async with httpx.AsyncClient(timeout=timeout) as client:
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
    def _build_embedding_url(base_url: str) -> str:
        parsed = urlparse(base_url)
        path = parsed.path.rstrip("/")
        if path.endswith("/embeddings"):
            return base_url
        if path.endswith("/v1"):
            return f"{base_url}/embeddings"
        return f"{base_url}/embeddings"

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
