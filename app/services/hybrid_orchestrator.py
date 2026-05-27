from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.agents.architecture_matcher import ArchitectureMatcherAgent
from app.agents.evaluation_generator import EvaluationGeneratorAgent
from app.agents.requirement_parser import RequirementParserAgent
from app.models.schemas import ArchitectureStyle, RecommendationResponse
from app.services.composition_recommender import CompositionRecommender
from app.services.knowledge_graph import KnowledgeGraphService
from app.services.llm_client import LLMClient
from app.services.report_formatter import ReportFormatter
from app.services.rule_engine import RuleEngine
from app.services.topology_generator import TopologyGenerator


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
    """LangChain-style chain orchestration for rules + LLM + knowledge graph reasoning."""

    def __init__(
        self,
        parser: RequirementParserAgent,
        matcher: ArchitectureMatcherAgent,
        evaluator: EvaluationGeneratorAgent,
        llm_client: LLMClient,
        rule_engine: RuleEngine,
        graph_service: KnowledgeGraphService,
    ) -> None:
        self.parser = parser
        self.matcher = matcher
        self.evaluator = evaluator
        self.llm_client = llm_client
        self.rule_engine = rule_engine
        self.graph_service = graph_service
        self.topology_generator = TopologyGenerator()
        self.composition_recommender = CompositionRecommender()

    async def run(self, requirement: str, styles: list[ArchitectureStyle], top_k: int) -> RecommendationResponse:
        ctx = self._context(requirement, styles, top_k)
        features, rule_decision, graph_style_ids, graph_matches = await self._analyze(ctx)
        candidates = self.matcher.match(
            features,
            ctx.styles,
            top_k=max(top_k + 3, 6),
            preferred_style_ids=rule_decision.preferred_style_ids + graph_style_ids,
            rejected_style_ids=rule_decision.rejected_style_ids,
        )
        ctx.trace.append("架构匹配 Agent 基于规则引擎和知识图谱检索结果完成候选初筛")

        candidates, guard_notes = self.rule_engine.validate_candidates(features, candidates, rule_decision)
        ctx.trace.extend(guard_notes)
        candidates = candidates[:top_k]

        review_notes = await self.llm_client.review_candidates(requirement, features, candidates)
        ctx.trace.extend(f"DeepSeek/LLM 候选复核：{note}" for note in review_notes)

        candidates, guard_notes = self.rule_engine.validate_candidates(features, candidates, rule_decision)
        ctx.trace.extend(guard_notes)

        report = await self.evaluator.generate(requirement, features, candidates, ctx.style_map)
        ctx.trace.append("评估生成 Agent 完成 DeepSeek/模板协同报告生成")

        matrix = [self._matrix_row(item) for item in candidates]
        composition = self.composition_recommender.recommend(requirement, features, candidates)
        ctx.decision_trace = self._build_decision_trace(
            features=features,
            rule_decision=rule_decision,
            graph_matches=graph_matches,
            candidates=candidates,
            review_notes=review_notes,
            composition=composition,
        )
        ctx.composition_recommendation = composition
        ctx.trace.append("组合推荐模块完成主架构与辅助模式判断")
        topology_diagrams = await self._build_topologies(ctx, features, candidates)

        return RecommendationResponse(
            requirement=requirement,
            features=features,
            candidates=candidates,
            final_recommendation=candidates[0],
            report=report,
            comparison_matrix=matrix,
            topology_diagrams=topology_diagrams,
            trace=ctx.trace,
            decision_trace=ctx.decision_trace,
            composition_recommendation=composition,
        )

    async def stream(self, requirement: str, styles: list[ArchitectureStyle], top_k: int) -> AsyncGenerator[str, None]:
        ctx = self._context(requirement, styles, top_k)
        features, rule_decision, graph_style_ids, graph_matches = await self._analyze(ctx)
        candidates = self.matcher.match(
            features,
            ctx.styles,
            top_k=max(top_k + 3, 6),
            preferred_style_ids=rule_decision.preferred_style_ids + graph_style_ids,
            rejected_style_ids=rule_decision.rejected_style_ids,
        )
        ctx.trace.append("架构匹配 Agent 基于规则引擎和知识图谱检索结果完成候选初筛")
        candidates, guard_notes = self.rule_engine.validate_candidates(features, candidates, rule_decision)
        ctx.trace.extend(guard_notes)
        candidates = candidates[:top_k]

        review_notes = await self.llm_client.review_candidates(requirement, features, candidates)
        ctx.trace.extend(f"DeepSeek/LLM 候选复核：{note}" for note in review_notes)
        candidates, guard_notes = self.rule_engine.validate_candidates(features, candidates, rule_decision)
        ctx.trace.extend(guard_notes)

        matrix = [self._matrix_row(item) for item in candidates]
        composition = self.composition_recommender.recommend(requirement, features, candidates)
        ctx.decision_trace = self._build_decision_trace(
            features=features,
            rule_decision=rule_decision,
            graph_matches=graph_matches,
            candidates=candidates,
            review_notes=review_notes,
            composition=composition,
        )
        ctx.composition_recommendation = composition
        ctx.trace.append("组合推荐模块完成主架构与辅助模式判断")
        topology_task: asyncio.Task[dict[str, str]] | None = asyncio.create_task(
            self._build_topologies(ctx, features, candidates)
        )
        yield self._sse(
            "initial",
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
        async for token in self.llm_client.stream_report(requirement, features, candidates):
            streamed = True
            yield self._sse("report_delta", {"delta": token})
            if topology_task and topology_task.done():
                topology_diagrams = await self._resolve_topology_task(topology_task, ctx, candidates)
                yield self._sse("topology", {"topology_diagrams": topology_diagrams, "trace": ctx.trace, "decision_trace": ctx.decision_trace})
                topology_task = None

        if not streamed:
            fallback = self.evaluator._fallback_analysis(features, candidates)
            yield self._sse("report_delta", {"delta": fallback})

        yield self._sse("report_delta", {"delta": ReportFormatter.build_report_suffix(candidates[0], ctx.style_map)})

        if topology_task is not None:
            topology_diagrams = await self._resolve_topology_task(topology_task, ctx, candidates)
            yield self._sse("topology", {"topology_diagrams": topology_diagrams, "trace": ctx.trace, "decision_trace": ctx.decision_trace})

        yield self._sse("report_delta", {"delta": ReportFormatter.build_report_footer(candidates[0])})
        yield self._sse("done", {"ok": True})

    async def _resolve_topology_task(
        self,
        topology_task: asyncio.Task[dict[str, str]],
        ctx: ReasoningContext,
        candidates: list[CandidateEvaluation],
    ) -> dict[str, str]:
        try:
            return await topology_task
        except Exception as exc:
            ctx.trace.append(f"拓扑生成任务异常，使用基础架构图兜底：{exc}")
            fallback = ctx.style_map[candidates[0].style_id].topology
            return {f"{candidates[0].name}基础拓扑": fallback}

    async def _build_topologies(
        self,
        ctx: ReasoningContext,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
    ) -> dict[str, str]:
        llm_capabilities = await self.llm_client.extract_capabilities(ctx.requirement, features)
        graph_knowledge = self.graph_service.retrieve_topology_knowledge(ctx.requirement, features)
        mermaid, notes = self.topology_generator.generate(
            ctx.requirement,
            features,
            candidates[0],
            extra_capabilities=llm_capabilities,
            graph_knowledge=graph_knowledge,
            composition_recommendation=ctx.composition_recommendation,
        )
        if llm_capabilities:
            ctx.trace.append("DeepSeek/LLM 补充拓扑业务能力：" + "、".join(llm_capabilities[:8]))
        if graph_knowledge.get("scenarios"):
            ctx.trace.append("Neo4j 拓扑知识命中场景：" + "、".join(graph_knowledge["scenarios"][:5]))
        if graph_knowledge.get("capabilities"):
            ctx.trace.append("Neo4j 拓扑知识命中能力：" + "、".join(graph_knowledge["capabilities"][:8]))
        ctx.decision_trace["topology_evidence"] = {
            "scenarios": graph_knowledge.get("scenarios", []),
            "capabilities": graph_knowledge.get("capabilities", []),
            "components": graph_knowledge.get("components", []),
            "stores": graph_knowledge.get("stores", []),
            "notes": notes,
        }
        ctx.trace.extend(notes)
        ctx.trace.append("拓扑生成器基于领域能力和规则校验生成确定性 Mermaid 拓扑")
        return {f"{candidates[0].name}定制拓扑": mermaid}

    async def _analyze(self, ctx: ReasoningContext):
        ctx.trace.append("需求解析 Agent 接收自然语言需求")
        features = self.parser.parse(ctx.requirement)
        ctx.trace.append(f"规则解析得到领域={features.domain}，数据流={features.data_flow}")

        llm_features = await self.llm_client.extract_features(ctx.requirement, features)
        if llm_features:
            features = llm_features
            ctx.trace.append("DeepSeek/LLM 对需求特征完成二次语义增强")
        else:
            ctx.trace.append("DeepSeek/LLM 未配置或不可用，使用本地规则特征作为稳定兜底")

        rule_decision = self.rule_engine.evaluate(features)
        if rule_decision.fired_rule_ids:
            ctx.trace.append(f"规则引擎命中规则：{', '.join(rule_decision.fired_rule_ids)}")
            ctx.trace.extend(rule_decision.reasons)
        else:
            ctx.trace.append("规则引擎未命中特定硬规则，进入通用评分流程")

        graph_matches = self.graph_service.retrieve_styles(features, ctx.styles)
        graph_style_ids = [style_id for style_id, _score, _reason in graph_matches]
        if graph_matches:
            ctx.trace.append("知识图谱检索命中：" + "；".join(f"{style_id}({reason})" for style_id, _score, reason in graph_matches[:5]))
        else:
            ctx.trace.append("知识图谱未检索到强匹配，使用全量架构知识库")

        return features, rule_decision, graph_style_ids, graph_matches

    @staticmethod
    def _context(requirement: str, styles: list[ArchitectureStyle], top_k: int) -> ReasoningContext:
        return ReasoningContext(
            requirement=requirement,
            top_k=top_k,
            styles=styles,
            style_map={style.id: style for style in styles},
            trace=["HybridReasoningOrchestrator 启动 LangChain 风格链式编排"],
            decision_trace={},
            composition_recommendation={},
        )

    @staticmethod
    def _build_decision_trace(
        features,
        rule_decision,
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
                "quality_attributes": features.quality_attributes,
                "constraints": features.constraints,
                "ambiguity_notes": features.ambiguity_notes,
            },
            "rule_evidence": {
                "fired_rule_ids": rule_decision.fired_rule_ids,
                "reasons": rule_decision.reasons,
                "preferred_style_ids": rule_decision.preferred_style_ids,
                "rejected_style_ids": rule_decision.rejected_style_ids,
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
