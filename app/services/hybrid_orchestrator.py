from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.agents.architecture_matcher import ArchitectureMatcherAgent
from app.agents.evaluation_generator import EvaluationGeneratorAgent
from app.agents.requirement_parser import RequirementParserAgent
from app.knowledge.style_schemas import get_schema
from app.models.schemas import (
    ArchitectureStyle,
    CandidateEvaluation,
    ExtractedFeatures,
    RecommendationResponse,
    StyleInstance,
)
from app.services.composition_recommender import CompositionRecommender
from app.services.exceptions import DeepSeekServiceError, RequirementParsingError
from app.services.llm_client import LLMClient
from app.services.report_formatter import ReportFormatter
from app.services.style_topology_renderer import StyleTopologyRenderer


@dataclass
class ReasoningContext:
    requirement: str
    top_k: int
    styles: list[ArchitectureStyle]
    style_map: dict[str, ArchitectureStyle]
    trace: list[str]
    decision_trace: dict[str, Any]
    composition_recommendation: dict[str, Any]


class HybridReasoningOrchestrator:
    """LangChain-style chain orchestration for LLM + agent reasoning."""

    def __init__(
        self,
        matcher: ArchitectureMatcherAgent,
        evaluator: EvaluationGeneratorAgent,
        requirement_parser: RequirementParserAgent,
        llm_client: LLMClient,
    ) -> None:
        self.matcher = matcher
        self.evaluator = evaluator
        self.requirement_parser = requirement_parser
        self.llm_client = llm_client
        self.style_renderer = StyleTopologyRenderer()
        self.composition_recommender = CompositionRecommender()

    async def run(
        self,
        requirement: str,
        styles: list[ArchitectureStyle],
        top_k: int,
        topology_options: dict | None = None,
    ) -> RecommendationResponse:
        ctx = self._context(requirement, styles, top_k, topology_options)
        features, graph_matches = await self._analyze(ctx)
        candidates, composition, review_notes = await self._match_with_deepseek(ctx, features, top_k)

        report = await self.evaluator.generate(requirement, features, candidates, ctx.style_map)
        ctx.trace.append("评估生成 Agent 完成报告生成")

        matrix = [self._matrix_row(item) for item in candidates]
        ctx.decision_trace = self._build_decision_trace(
            features=features,
            graph_matches=graph_matches,
            candidates=candidates,
            review_notes=review_notes,
            composition=composition,
        )
        ctx.composition_recommendation = composition
        ctx.trace.append("架构组合推荐由 DeepSeek 架构匹配 Agent 生成")
        topology_payload = await self._build_topologies(ctx, features, candidates)

        return RecommendationResponse(
            requirement=requirement,
            features=features,
            candidates=candidates,
            final_recommendation=candidates[0],
            report=report,
            comparison_matrix=matrix,
            topology_diagrams=topology_payload["diagrams"],
            topology_graphs=topology_payload["graphs"],
            trace=ctx.trace,
            decision_trace=ctx.decision_trace,
            composition_recommendation=composition,
        )

    async def stream(
        self,
        requirement: str,
        styles: list[ArchitectureStyle],
        top_k: int,
        topology_options: dict | None = None,
    ) -> AsyncGenerator[str, None]:
        ctx = self._context(requirement, styles, top_k, topology_options)
        try:
            features, graph_matches = await self._analyze(ctx)
        except RequirementParsingError as exc:
            yield self._sse(
                "error",
                {
                    "message": str(exc),
                    "trace": ctx.trace,
                },
            )
            yield self._sse("done", {"ok": False})
            return

        yield self._sse(
            "features",
            {
                "requirement": requirement,
                "features": features.model_dump(),
                "trace": ctx.trace,
            },
        )

        try:
            candidates, composition, review_notes = await self._match_with_deepseek(ctx, features, top_k)
        except DeepSeekServiceError as exc:
            yield self._sse(
                "error",
                {
                    "message": str(exc),
                    "trace": ctx.trace,
                },
            )
            yield self._sse("done", {"ok": False})
            return

        matrix = [self._matrix_row(item) for item in candidates]
        ctx.decision_trace = self._build_decision_trace(
            features=features,
            graph_matches=graph_matches,
            candidates=candidates,
            review_notes=review_notes,
            composition=composition,
        )
        ctx.composition_recommendation = composition
        ctx.trace.append("架构组合推荐由 DeepSeek 架构匹配 Agent 生成")
        yield self._sse(
            "recommendation",
            {
                "requirement": requirement,
                "features": features.model_dump(),
                "candidates": [item.model_dump() for item in candidates],
                "final_recommendation": candidates[0].model_dump(),
                "comparison_matrix": matrix,
                "trace": ctx.trace,
                "decision_trace": ctx.decision_trace,
                "composition_recommendation": composition,
            },
        )

        yield self._sse("report_delta", {"delta": ReportFormatter.build_report_prefix(requirement, features, candidates)})

        streamed = False
        report_buffer: list[str] = []
        last_report_flush = time.perf_counter()
        async for token in self.llm_client.stream_report(requirement, features, candidates):
            streamed = True
            report_buffer.append(token)
            buffered_text = "".join(report_buffer)
            should_flush = len(buffered_text) >= 120 or time.perf_counter() - last_report_flush >= 0.18
            if should_flush:
                yield self._sse("report_delta", {"delta": buffered_text})
                report_buffer = []
                last_report_flush = time.perf_counter()

        if report_buffer:
            yield self._sse("report_delta", {"delta": "".join(report_buffer)})

        if not streamed:
            message = self.llm_client.last_error or "DeepSeek 未返回流式报告内容。"
            ctx.trace.append(f"评估生成 Agent 终止：{message}")
            yield self._sse(
                "error",
                {
                    "message": f"评估报告生成失败：{message}",
                    "trace": ctx.trace,
                },
            )
            yield self._sse("done", {"ok": False})
            return

        yield self._sse("report_delta", {"delta": ReportFormatter.build_report_suffix(candidates[0], ctx.style_map)})
        yield self._sse("report_delta", {"delta": ReportFormatter.build_report_footer(candidates[0])})
        yield self._sse("done", {"ok": True})

    async def stream_topology(
        self,
        requirement: str,
        styles: list[ArchitectureStyle],
        features: ExtractedFeatures,
        final_recommendation: CandidateEvaluation,
        composition_recommendation: dict[str, Any] | None = None,
        decision_trace: dict[str, Any] | None = None,
        topology_options: dict | None = None,
    ) -> AsyncGenerator[str, None]:
        ctx = self._context(requirement, styles, 1, topology_options)
        ctx.trace.append("拓扑生成流启动：复用推荐流已解析的需求特征和最终推荐架构")
        ctx.composition_recommendation = composition_recommendation or {}
        ctx.decision_trace = decision_trace or {}
        candidates = [final_recommendation]
        topology_task = asyncio.create_task(self._build_topologies(ctx, features, candidates))
        while not topology_task.done():
            yield self._sse(
                "heartbeat",
                {
                    "message": "架构图生成中：正在检索 Neo4j、检查覆盖率并生成 Mermaid 拓扑",
                    "trace": ctx.trace,
                    "decision_trace": ctx.decision_trace,
                },
            )
            await asyncio.sleep(2)
        topology_payload = await self._resolve_topology_task(topology_task, ctx, features, candidates)
        yield self._sse(
            "topology",
            {
                "topology_diagrams": topology_payload["diagrams"],
                "topology_graphs": topology_payload["graphs"],
                "trace": ctx.trace,
                "decision_trace": ctx.decision_trace,
            },
        )
        yield self._sse("done", {"ok": True})

    async def _build_topologies(
        self,
        ctx: ReasoningContext,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
    ) -> dict[str, Any]:
        """Generate topology diagrams via LLM-driven StyleSchema rendering."""
        winner = candidates[0]
        style_schema = get_schema(winner.style_id)

        if not style_schema or not self.llm_client.api_key:
            ctx.trace.append("拓扑生成跳过：缺少 StyleSchema 或 LLM API Key")
            return {"diagrams": {}, "graphs": {}}

        try:
            return await self._build_style_topologies(ctx, features, winner, style_schema)
        except Exception as exc:
            ctx.trace.append(f"拓扑生成失败：{exc}")
            return {"diagrams": {}, "graphs": {}}

    async def _build_style_topologies(
        self,
        ctx: ReasoningContext,
        features: ExtractedFeatures,
        winner: CandidateEvaluation,
        schema,
    ) -> dict[str, Any]:
        """LLM → StyleInstance → StyleRenderer → Mermaid."""
        ctx.trace.append(f"风格驱动拓扑：使用「{schema.style_name}」Schema 引导 LLM 输出结构化组件和连接")

        instance = await self.llm_client.extract_style_instance(
            ctx.requirement, features, schema,
            composition_mode=ctx.composition_recommendation.get("composition_needed", False),
        )
        if not instance:
            raise RuntimeError("LLM 未返回有效的 StyleInstance")

        ctx.trace.append(f"LLM 填充 StyleInstance 完成：{len(instance.components)} 组件，{len(instance.connections)} 连接")

        diagrams, graphs, render_notes = self.style_renderer.render_views(schema, instance, notes=[])
        ctx.trace.extend(render_notes)

        ctx.decision_trace["topology_evidence"] = {
            "method": "style_schema",
            "style_id": schema.style_id,
            "style_name": schema.style_name,
            "component_count": len(instance.components),
            "connection_count": len(instance.connections),
            "notes": render_notes,
        }

        return {
            "diagrams": {f"{winner.name}{name}": diagram for name, diagram in diagrams.items()},
            "graphs": {f"{winner.name}{name}": graph for name, graph in graphs.items()},
        }

    async def _analyze(self, ctx: ReasoningContext):
        ctx.trace.append("需求解析 Agent 接收自然语言需求")
        try:
            features = await self.requirement_parser.parse(ctx.requirement)
        except ValueError as exc:
            ctx.trace.append(f"需求解析 Agent 输入校验失败：{exc}")
            raise RequirementParsingError(str(exc)) from exc

        consistency_issues = [
            note for note in features.ambiguity_notes
            if "一致性" in note or "矛盾" in note or "不匹配" in note or "复核" in note
        ]
        if consistency_issues:
            ctx.trace.append(
                f"需求解析 Agent 一致性校验发现 {len(consistency_issues)} 个问题："
                + "；".join(consistency_issues[:3])
            )
        ctx.trace.append("需求解析 Agent 完成结构化特征提取与校验")
        ctx.trace.append("知识图谱用于后续拓扑知识检索、ReAct 补全和 Neo4j 写入")
        return features, []

    async def _match_with_deepseek(
        self,
        ctx: ReasoningContext,
        features: ExtractedFeatures,
        top_k: int,
    ) -> tuple[list[CandidateEvaluation], dict[str, Any], list[str]]:
        ctx.trace.append("架构匹配 Agent 调用 DeepSeek 生成候选架构、评分和组合建议")
        styles = [style.model_dump() for style in ctx.styles]
        result = await self.llm_client.recommend_architectures(ctx.requirement, features, styles, top_k)
        if not result:
            message = self.llm_client.last_error or "DeepSeek 未返回可用候选架构 JSON。"
            ctx.trace.append(f"架构匹配 Agent 终止：{message}")
            raise DeepSeekServiceError(f"架构匹配失败：{message}")
        candidates, composition_payload = result
        review_notes = list(composition_payload.pop("review_notes", []))

        # ── Agent 后置校验：架构匹配 Agent 对比本地评分，检测过度设计 ──
        candidates, consistency_notes = self.matcher.validate_llm_results(
            features, candidates, ctx.styles
        )
        if consistency_notes:
            ctx.trace.append(
                f"架构匹配 Agent 一致性校验发现 {len(consistency_notes)} 个关注点"
            )
            ctx.trace.extend(consistency_notes)

        ctx.trace.append("DeepSeek 架构匹配 + Agent 校验完成候选架构排序")
        if review_notes:
            ctx.trace.extend(f"DeepSeek 架构匹配说明：{note}" for note in review_notes)
        return candidates[:top_k], composition_payload, review_notes

    def _normalize_llm_features(self, requirement: str, features: ExtractedFeatures) -> ExtractedFeatures:
        normalized_expectations = self._normalize_topology_expectations(features.topology_expectations)
        quality_attributes = {
            key: round(max(0.0, min(1.0, float(value))), 2)
            for key, value in features.quality_attributes.items()
        }
        for key in ["concurrency", "realtime", "reliability", "scalability", "data_intensity", "ai_reasoning"]:
            quality_attributes.setdefault(key, 0.0)
        return features.model_copy(
            update={
                "keywords": self._dedupe(features.keywords),
                "business_capabilities": self._dedupe(features.business_capabilities),
                "architecture_drivers": self._dedupe(features.architecture_drivers),
                "topology_expectations": normalized_expectations,
                "quality_attributes": quality_attributes,
                "ambiguity_notes": self._dedupe(features.ambiguity_notes),
            }
        )

    @staticmethod
    def _normalize_topology_expectations(expectations: dict[str, Any] | None) -> dict[str, Any]:
        expectations = expectations or {}
        normalized: dict[str, Any] = {}
        for key in ["must_have_components", "must_have_relations", "quality_infrastructure"]:
            value = expectations.get(key, [])
            if isinstance(value, list):
                normalized[key] = [str(item).strip() for item in value if str(item).strip()]
            elif value:
                normalized[key] = [str(value).strip()]
            else:
                normalized[key] = []
        component_specs = []
        for item in expectations.get("component_specs", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            component_specs.append(
                {
                    "name": name,
                    "type": str(item.get("type", "service")).strip() or "service",
                    "layer": str(item.get("layer", "business")).strip() or "business",
                    "owned_by": str(item.get("owned_by", "")).strip(),
                }
            )
        relation_specs = []
        for item in expectations.get("relation_specs", []):
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "")).strip()
            target = str(item.get("target", "")).strip()
            if not source or not target:
                continue
            relation_specs.append(
                {
                    "source": source,
                    "target": target,
                    "label": str(item.get("label", "依赖")).strip() or "依赖",
                    "kind": str(item.get("kind", "sync")).strip() or "sync",
                }
            )
        normalized["component_specs"] = component_specs
        normalized["relation_specs"] = relation_specs
        return normalized

    @staticmethod
    def _dedupe(items: list[Any]) -> list[Any]:
        return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))

    @classmethod
    def _context(
        cls,
        requirement: str,
        styles: list[ArchitectureStyle],
        top_k: int,
        topology_options: dict | None = None,
    ) -> ReasoningContext:
        return ReasoningContext(
            requirement=requirement,
            top_k=top_k,
            styles=styles,
            style_map={style.id: style for style in styles},
            trace=["HybridReasoningOrchestrator 启动链式编排"],
            decision_trace={},
            composition_recommendation={},
        )

    @staticmethod
    def _build_decision_trace(
        features,
        graph_matches,
        candidates,
        review_notes,
        composition,
    ) -> dict[str, Any]:
        winner = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None
        score_gap = round(winner.score - runner_up.score, 1) if runner_up else None
        return {
            "requirement_features": {
                "domain": features.domain,
                "data_flow": features.data_flow,
                "keywords": features.keywords,
                "business_capabilities": features.business_capabilities,
                "architecture_drivers": features.architecture_drivers,
                "topology_expectations": features.topology_expectations,
                "quality_attributes": features.quality_attributes,
                "constraints": features.constraints,
                "ambiguity_notes": features.ambiguity_notes,
            },
            "rule_evidence": {
                "enabled": False,
                "reasons": ["本地规则引擎已停用，推荐决策由 DeepSeek 架构匹配 Agent 生成。"],
                "fired_rule_ids": [],
                "preferred_style_ids": [],
                "rejected_style_ids": [],
            },
            "graph_evidence": [
                {"style_id": style_id, "score": score, "reason": reason}
                for style_id, score, reason in graph_matches[:8]
            ],
            "score_evidence": [
                {
                    "style_id": item.style_id,
                    "name": item.name,
                    "score": item.score,
                    "raw_score": item.raw_score,
                    "role": item.recommendation_role,
                    "confidence": item.confidence,
                    "matched_reasons": item.matched_reasons,
                    "deductions": item.deductions,
                    "risks": item.risks,
                }
                for item in candidates
            ],
            "llm_review": review_notes,
            "composition_evidence": composition,
            "final_reason": (
                f"{winner.name} 得分 {winner.score}/100，定位为{winner.recommendation_role}。"
                + (f"相对 {runner_up.name} 领先 {score_gap} 分。" if runner_up else "")
            ),
        }

    @staticmethod
    def _matrix_row(candidate):
        scores = candidate.quality_scores
        return {
            "架构风格": candidate.name,
            "综合评分": candidate.score,
            "推荐定位": candidate.recommendation_role,
            "置信度": candidate.confidence,
            "扩展性": HybridReasoningOrchestrator._stars(scores.get("scalability", 0)),
            "性能": HybridReasoningOrchestrator._stars(scores.get("performance", 0)),
            "可靠性": HybridReasoningOrchestrator._stars(scores.get("reliability", 0)),
            "可维护性": HybridReasoningOrchestrator._stars(scores.get("modifiability", 0)),
            "实时性": HybridReasoningOrchestrator._stars(scores.get("realtime", 0)),
            "复杂度友好度": HybridReasoningOrchestrator._complexity_label(scores.get("complexity", 0)),
            "扣分原因": "；".join(candidate.deductions) if candidate.deductions else "无明显扣分",
        }

    @staticmethod
    def _stars(value: float) -> str:
        count = max(1, min(5, round(value * 5)))
        return "★" * count + "☆" * (5 - count)

    @staticmethod
    def _complexity_label(value: float) -> str:
        if value >= 0.75:
            return "较低"
        if value >= 0.5:
            return "中等"
        return "较高"

    @staticmethod
    def _sse(event: str, data: object) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
