from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.agents.architecture_matcher import ArchitectureMatcherAgent
from app.agents.evaluation_generator import EvaluationGeneratorAgent
from app.models.schemas import ArchitectureStyle, CandidateEvaluation, ExtractedFeatures, RecommendationResponse
from app.services.composition_recommender import CompositionRecommender
from app.services.exceptions import DeepSeekServiceError, RequirementParsingError
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
    topology_fast_mode: bool
    topology_llm_timeout_seconds: float
    topology_repair_max_rounds: int


class HybridReasoningOrchestrator:
    """LangChain-style chain orchestration for rules + LLM + knowledge graph reasoning."""

    TOPOLOGY_COVERAGE_THRESHOLD = 0.75
    TOPOLOGY_REPAIR_MAX_ROUNDS = int(os.getenv("TOPOLOGY_REPAIR_MAX_ROUNDS", "1"))
    TOPOLOGY_LLM_TIMEOUT_SECONDS = float(os.getenv("TOPOLOGY_LLM_TIMEOUT_SECONDS", "12"))
    TOPOLOGY_FAST_MODE = os.getenv("TOPOLOGY_FAST_MODE", "true").lower() not in {"0", "false", "no", "off"}

    def __init__(
        self,
        matcher: ArchitectureMatcherAgent,
        evaluator: EvaluationGeneratorAgent,
        llm_client: LLMClient,
        rule_engine: RuleEngine,
        graph_service: KnowledgeGraphService,
    ) -> None:
        self.matcher = matcher
        self.evaluator = evaluator
        self.llm_client = llm_client
        self.rule_engine = rule_engine
        self.graph_service = graph_service
        self.topology_generator = TopologyGenerator()
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
        if not report:
            message = self.llm_client.last_error or "DeepSeek 未返回可用评估报告。"
            ctx.trace.append(f"评估生成 Agent 终止：{message}")
            raise DeepSeekServiceError(f"评估报告生成失败：{message}")
        ctx.trace.append("评估生成 Agent 完成 DeepSeek 报告生成")

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

    async def _resolve_topology_task(
        self,
        topology_task: asyncio.Task[dict[str, Any]],
        ctx: ReasoningContext,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
    ) -> dict[str, Any]:
        try:
            return await topology_task
        except Exception as exc:
            ctx.trace.append(f"拓扑生成任务异常，使用结构化基础拓扑兜底：{exc}")
            topology_diagrams, topology_graphs, notes = self.topology_generator.generate_graph_views(
                ctx.requirement,
                features,
                candidates[0],
                extra_capabilities=[],
                graph_knowledge={},
                composition_recommendation=ctx.composition_recommendation,
            )
            ctx.trace.extend(notes)
            return {
                "diagrams": {f"{candidates[0].name}{name}": diagram for name, diagram in topology_diagrams.items()},
                "graphs": {f"{candidates[0].name}{name}": graph for name, graph in topology_graphs.items()},
            }

    async def _build_topologies(
        self,
        ctx: ReasoningContext,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
        topology_prep_task: asyncio.Task[tuple[dict[str, Any], list[dict[str, Any]], list[str]]] | None = None,
    ) -> dict[str, Any]:
        if topology_prep_task is None:
            graph_knowledge, repair_trace, topology_capabilities = await self._prepare_topology_knowledge(ctx, features)
        else:
            graph_knowledge, repair_trace, topology_capabilities = await topology_prep_task
        topology_diagrams, topology_graphs, notes = self.topology_generator.generate_graph_views(
            ctx.requirement,
            features,
            candidates[0],
            extra_capabilities=topology_capabilities,
            graph_knowledge=graph_knowledge,
            composition_recommendation=ctx.composition_recommendation,
        )
        if topology_capabilities:
            ctx.trace.append("DeepSeek 主解析拓扑业务能力：" + "、".join(topology_capabilities[:8]))
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
            "react_repair": repair_trace,
        }
        ctx.trace.extend(notes)
        ctx.trace.append("拓扑生成器基于领域能力和规则校验生成结构化可交互拓扑")
        return {
            "diagrams": {f"{candidates[0].name}{name}": diagram for name, diagram in topology_diagrams.items()},
            "graphs": {f"{candidates[0].name}{name}": graph for name, graph in topology_graphs.items()},
        }

    async def _prepare_topology_knowledge(
        self,
        ctx: ReasoningContext,
        features: ExtractedFeatures,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        started = time.perf_counter()
        topology_capabilities = [
            str(item).strip()
            for item in features.business_capabilities
            if str(item).strip()
        ]
        retrieve_started = time.perf_counter()
        graph_knowledge = await asyncio.to_thread(
            self.graph_service.retrieve_topology_knowledge,
            ctx.requirement,
            features,
        )
        ctx.trace.append(f"拓扑耗时：Neo4j 知识检索 {time.perf_counter() - retrieve_started:.1f}s")
        repair_started = time.perf_counter()
        graph_knowledge, repair_trace = await self._repair_topology_knowledge(
            ctx,
            features,
            graph_knowledge,
            topology_capabilities,
        )
        ctx.trace.append(f"拓扑耗时：LLM 补全与语义规范化 {time.perf_counter() - repair_started:.1f}s")
        ctx.trace.append(f"拓扑耗时：知识准备总计 {time.perf_counter() - started:.1f}s")
        return graph_knowledge, repair_trace, topology_capabilities

    async def _repair_topology_knowledge(
        self,
        ctx: ReasoningContext,
        features: ExtractedFeatures,
        graph_knowledge: dict,
        llm_capabilities: list[str],
    ) -> tuple[dict, list[dict[str, Any]]]:
        repair_trace: list[dict[str, Any]] = []
        current_graph = graph_knowledge

        gap_started = time.perf_counter()
        try:
            gap_patch = await asyncio.wait_for(
                self.llm_client.review_topology_coverage_gap(ctx.requirement, features, current_graph),
                timeout=ctx.topology_llm_timeout_seconds,
            )
        except TimeoutError:
            gap_patch = None
            repair_trace.append(
                {
                    "round": 0,
                    "action": "llm_gap_review_timeout",
                    "message": f"拓扑完整性复核超过 {ctx.topology_llm_timeout_seconds:.0f}s，已跳过以保证响应速度。",
                }
            )
        ctx.trace.append(f"拓扑耗时：DeepSeek 漏项复核 {time.perf_counter() - gap_started:.1f}s")
        if gap_patch and self._patch_has_write_items(gap_patch):
            before_coverage = self.topology_generator.assess_coverage(
                ctx.requirement,
                features,
                current_graph,
                extra_capabilities=llm_capabilities,
            )
            normalize_started = time.perf_counter()
            normalization = await self.graph_service.normalize_topology_patch(
                gap_patch,
                ctx.requirement,
                features,
                current_graph,
                before_coverage,
            )
            ctx.trace.append(f"拓扑耗时：漏项补丁 embedding 规范化 {time.perf_counter() - normalize_started:.1f}s")
            trial_patch = normalization.get("trial_patch", gap_patch)
            write_patch = normalization.get("write_patch", trial_patch)
            current_graph = self.topology_generator.merge_knowledge_patch(current_graph, trial_patch)
            after_coverage = self.topology_generator.assess_coverage(
                ctx.requirement,
                features,
                current_graph,
                extra_capabilities=llm_capabilities,
            )
            if ctx.topology_fast_mode:
                neo4j_result = {
                    "ok": False,
                    "skipped": True,
                    "reason": "拓扑快速模式：补丁已用于本次架构图，跳过同步写入 Neo4j。",
                }
            elif self._patch_has_write_items(write_patch):
                neo4j_result = await asyncio.to_thread(
                    self.graph_service.merge_topology_patch,
                    ctx.requirement,
                    features,
                    write_patch,
                )
            else:
                neo4j_result = {
                    "ok": False,
                    "skipped": True,
                    "reason": "语义规范化后没有达到永久写入条件的节点或关系。",
                }
            repair_trace.append(
                {
                    "round": 0,
                    "action": "llm_gap_review_merged",
                    "raw_patch": gap_patch,
                    "trial_patch": trial_patch,
                    "write_patch": write_patch,
                    "normalization": normalization.get("report", []),
                    "temporary_items": normalization.get("temporary_items", []),
                    "semantic_available": normalization.get("semantic_available", False),
                    "neo4j": neo4j_result,
                    "coverage_before": before_coverage,
                    "coverage_after": after_coverage,
                }
            )
            gap_components = list(trial_patch.get("components", [])) + list(trial_patch.get("stores", []))
            ctx.trace.append(
                "拓扑完整性复核：DeepSeek 对照原始需求补充漏项 "
                + ("、".join(gap_components[:8]) if gap_components else "见能力映射")
            )

        for round_index in range(1, ctx.topology_repair_max_rounds + 1):
            coverage = self.topology_generator.assess_coverage(
                ctx.requirement,
                features,
                current_graph,
                extra_capabilities=llm_capabilities,
            )
            repair_trace.append(
                {
                    "round": round_index,
                    "action": "coverage_check",
                    "coverage": coverage,
                }
            )
            missing_items = self._coverage_missing_items(coverage)
            if not self._coverage_requires_repair(coverage):
                break

            patch_started = time.perf_counter()
            try:
                patch = await asyncio.wait_for(
                    self.llm_client.propose_topology_knowledge_patch(
                        ctx.requirement,
                        features,
                        coverage,
                        current_graph,
                    ),
                    timeout=ctx.topology_llm_timeout_seconds,
                )
            except TimeoutError:
                patch = None
                repair_trace.append(
                    {
                        "round": round_index,
                        "action": "llm_patch_timeout",
                        "message": f"DeepSeek ReAct 补全超过 {ctx.topology_llm_timeout_seconds:.0f}s，已跳过以保证响应速度。",
                    }
                )
                break
            ctx.trace.append(f"拓扑耗时：第 {round_index} 轮 DeepSeek ReAct 补全 {time.perf_counter() - patch_started:.1f}s")
            if not patch:
                repair_trace.append(
                    {
                        "round": round_index,
                        "action": "llm_patch_unavailable",
                        "message": "DeepSeek 补全不可用或返回格式不合法，本次不写入 Neo4j。",
                    }
                )
                break
            raw_patch = patch
            normalize_started = time.perf_counter()
            normalization = await self.graph_service.normalize_topology_patch(
                raw_patch,
                ctx.requirement,
                features,
                current_graph,
                coverage,
            )
            ctx.trace.append(f"拓扑耗时：第 {round_index} 轮 embedding 规范化 {time.perf_counter() - normalize_started:.1f}s")
            trial_patch = normalization.get("trial_patch", raw_patch)
            write_patch = normalization.get("write_patch", trial_patch)
            normalization_report = normalization.get("report", [])
            patch_capability_names = {
                str(item.get("name", "")).strip()
                for item in trial_patch.get("capabilities", [])
                if isinstance(item, dict)
            }
            patch_names = set(trial_patch.get("components", [])) | set(trial_patch.get("stores", []))
            patch_relations = {
                f"{edge.get('source')}->{edge.get('target')}"
                for edge in trial_patch.get("edges", [])
                if isinstance(edge, dict) and edge.get("source") and edge.get("target")
            }
            if not (
                patch_capability_names & set(coverage.get("missing_capabilities", []))
                or patch_names & set(coverage.get("missing_components", []))
                or patch_names & set(coverage.get("missing_quality_infrastructure", []))
                or patch_relations & set(coverage.get("missing_relations", []))
            ):
                repair_trace.append(
                    {
                        "round": round_index,
                        "action": "llm_patch_rejected",
                        "message": "DeepSeek 补丁未覆盖缺失能力、组件或关系，已拒绝泛化补全。",
                        "missing_capabilities": coverage.get("missing_capabilities", []),
                        "missing_components": coverage.get("missing_components", []),
                        "missing_relations": coverage.get("missing_relations", []),
                        "raw_patch": raw_patch,
                        "trial_patch": trial_patch,
                        "write_patch": write_patch,
                        "normalization": normalization_report,
                    }
                )
                break

            missing_capabilities = [item for item in coverage.get("missing_capabilities", []) if item]
            if missing_capabilities:
                covered_caps = {
                    item
                    for item in patch_capability_names
                    if item in missing_capabilities
                }
                if len(covered_caps) < len(set(missing_capabilities)):
                    repair_trace.append(
                        {
                            "round": round_index,
                            "action": "llm_patch_rejected",
                            "message": "DeepSeek 补丁没有把缺失能力按能力组逐项补齐，已拒绝。",
                            "missing_capabilities": missing_capabilities,
                            "trial_patch": trial_patch,
                            "write_patch": write_patch,
                            "normalization": normalization_report,
                        }
                    )
                    break

            trial_graph = self.topology_generator.merge_knowledge_patch(current_graph, trial_patch)
            refreshed_coverage = self.topology_generator.assess_coverage(
                ctx.requirement,
                features,
                trial_graph,
                extra_capabilities=llm_capabilities,
            )
            if refreshed_coverage["score"] <= coverage["score"]:
                repair_trace.append(
                    {
                        "round": round_index,
                        "action": "llm_patch_rejected",
                        "message": "DeepSeek 补丁试合并后未提升多维覆盖率，未写入 Neo4j。",
                        "coverage_after": refreshed_coverage,
                        "raw_patch": raw_patch,
                        "trial_patch": trial_patch,
                        "write_patch": write_patch,
                        "normalization": normalization_report,
                    }
                )
                break

            current_graph = trial_graph
            if ctx.topology_fast_mode:
                neo4j_result = {
                    "ok": False,
                    "skipped": True,
                    "reason": "拓扑快速模式：补丁已用于本次架构图，跳过同步写入 Neo4j。",
                }
            elif self._patch_has_write_items(write_patch):
                neo4j_result = await asyncio.to_thread(
                    self.graph_service.merge_topology_patch,
                    ctx.requirement,
                    features,
                    write_patch,
                )
            else:
                neo4j_result = {
                    "ok": False,
                    "skipped": True,
                    "reason": "语义规范化后没有达到永久写入条件的节点或关系。",
                }
            repair_trace.append(
                {
                    "round": round_index,
                    "action": "llm_patch_merged",
                    "raw_patch": raw_patch,
                    "trial_patch": trial_patch,
                    "write_patch": write_patch,
                    "normalization": normalization_report,
                    "temporary_items": normalization.get("temporary_items", []),
                    "semantic_available": normalization.get("semantic_available", False),
                    "neo4j": neo4j_result,
                    "coverage_after": refreshed_coverage,
                }
            )
            merged_names = [
                f"{item['original']}->{item['canonical']}"
                for item in normalization_report
                if item.get("action") == "merged"
            ]
            if merged_names:
                ctx.trace.append("拓扑知识规范化：同类型近义节点合并 " + "、".join(merged_names[:6]))
            ctx.trace.append(
                "拓扑 ReAct 补全：覆盖率 "
                f"{coverage['score']} -> {refreshed_coverage['score']}，"
                f"补充组件 {', '.join(trial_patch.get('components', [])[:6]) or '见能力映射'}"
            )
            temporary_items = normalization.get("temporary_items", [])
            if temporary_items:
                ctx.trace.append(f"语义规范化：{len(temporary_items)} 个不确定节点仅用于本次拓扑，未写入 Neo4j")
            if refreshed_coverage["score"] >= self.TOPOLOGY_COVERAGE_THRESHOLD:
                break

        return current_graph, repair_trace

    async def _analyze(self, ctx: ReasoningContext):
        ctx.trace.append("需求解析 Agent 接收自然语言需求")
        features = await self.llm_client.extract_features(ctx.requirement)
        if not features:
            message = self.llm_client.last_error or "DeepSeek 未配置、调用失败或返回 JSON 不符合结构化需求 Schema。"
            ctx.trace.append(f"需求解析 Agent 终止：{message}")
            raise RequirementParsingError(f"需求解析失败：{message}")
        features = self._normalize_llm_features(ctx.requirement, features)
        ctx.trace.append("DeepSeek 主解析完成结构化需求特征，并通过 Pydantic Schema 校验")

        ctx.trace.append("本地规则引擎已停用：需求理解结果完全来自 DeepSeek，Python 仅做 Schema 校验")
        ctx.trace.append("知识图谱不参与候选架构打分，仅用于后续拓扑知识检索、ReAct 补全和 Neo4j 写入")
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
        ctx.trace.append("DeepSeek 架构匹配 Agent 完成候选架构排序")
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
        return normalized

    @staticmethod
    def _drivers_from_features(features: ExtractedFeatures) -> list[str]:
        mapping = {
            "concurrency": "高并发",
            "realtime": "实时性",
            "reliability": "高可用",
            "scalability": "弹性伸缩",
            "data_intensity": "数据密集",
            "ai_reasoning": "AI 推理",
        }
        drivers = [label for key, label in mapping.items() if features.quality_attributes.get(key, 0) >= 0.65]
        if features.data_flow == "event_stream":
            drivers.append("事件流")
        if features.data_flow == "pipeline":
            drivers.append("数据管道")
        if features.data_flow == "transactional":
            drivers.append("事务处理")
        return drivers

    @staticmethod
    def _coverage_missing_items(coverage: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        for key in [
            "missing_capabilities",
            "missing_components",
            "missing_relations",
            "missing_quality_infrastructure",
        ]:
            missing.extend(coverage.get(key, []))
        return missing

    @classmethod
    def _coverage_requires_repair(cls, coverage: dict[str, Any]) -> bool:
        business_missing = bool(
            coverage.get("missing_capabilities")
            or coverage.get("missing_components")
            or coverage.get("missing_relations")
        )
        quality_missing = bool(coverage.get("missing_quality_infrastructure"))
        if business_missing:
            return True
        if quality_missing and coverage.get("score", 0) < cls.TOPOLOGY_COVERAGE_THRESHOLD:
            return True
        return False

    @staticmethod
    def _patch_has_write_items(patch: dict[str, Any]) -> bool:
        return bool(
            patch.get("capabilities")
            or patch.get("components")
            or patch.get("stores")
            or patch.get("edges")
        )

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
        topology_options = topology_options or {}
        fast_mode = topology_options.get("fast_mode")
        timeout = topology_options.get("llm_timeout_seconds")
        rounds = topology_options.get("repair_max_rounds")
        return ReasoningContext(
            requirement=requirement,
            top_k=top_k,
            styles=styles,
            style_map={style.id: style for style in styles},
            trace=[
                "HybridReasoningOrchestrator 启动 LangChain 风格链式编排",
                "拓扑生成配置："
                f"{'快速模式' if (cls.TOPOLOGY_FAST_MODE if fast_mode is None else bool(fast_mode)) else '精细模式'}，"
                f"LLM 超时 {float(timeout if timeout is not None else cls.TOPOLOGY_LLM_TIMEOUT_SECONDS):.0f}s，"
                f"补全轮数 {int(rounds if rounds is not None else cls.TOPOLOGY_REPAIR_MAX_ROUNDS)}",
            ],
            decision_trace={},
            composition_recommendation={},
            topology_fast_mode=cls.TOPOLOGY_FAST_MODE if fast_mode is None else bool(fast_mode),
            topology_llm_timeout_seconds=max(
                3.0,
                min(60.0, float(timeout if timeout is not None else cls.TOPOLOGY_LLM_TIMEOUT_SECONDS)),
            ),
            topology_repair_max_rounds=max(
                0,
                min(3, int(rounds if rounds is not None else cls.TOPOLOGY_REPAIR_MAX_ROUNDS)),
            ),
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
