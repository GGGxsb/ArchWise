from __future__ import annotations

from collections.abc import AsyncGenerator

from app.agents.architecture_matcher import ArchitectureMatcherAgent
from app.agents.evaluation_generator import EvaluationGeneratorAgent
from app.agents.requirement_parser import RequirementParserAgent
from app.knowledge.repository import KnowledgeRepository
from app.models.schemas import RecommendationResponse
from app.services.hybrid_orchestrator import HybridReasoningOrchestrator
from app.services.knowledge_graph import KnowledgeGraphService
from app.services.llm_client import LLMClient
from app.services.rule_engine import RuleEngine


class RecommendationService:
    def __init__(self, repository: KnowledgeRepository | None = None) -> None:
        self.repository = repository or KnowledgeRepository()
        self.parser = RequirementParserAgent()
        self.matcher = ArchitectureMatcherAgent()
        self.llm_client = LLMClient()
        self.evaluator = EvaluationGeneratorAgent(self.llm_client)
        self.rule_engine = RuleEngine()
        self.graph_service = KnowledgeGraphService()
        self.orchestrator = HybridReasoningOrchestrator(
            parser=self.parser,
            matcher=self.matcher,
            evaluator=self.evaluator,
            llm_client=self.llm_client,
            rule_engine=self.rule_engine,
            graph_service=self.graph_service,
        )

    async def recommend(self, requirement: str, top_k: int = 3) -> RecommendationResponse:
        styles = self.repository.list_styles()
        return await self.orchestrator.run(requirement, styles, top_k)

    async def recommend_stream(self, requirement: str, top_k: int = 3) -> AsyncGenerator[str, None]:
        styles = self.repository.list_styles()
        async for event in self.orchestrator.stream(requirement, styles, top_k):
            yield event

    @staticmethod
    def _matrix_row(candidate):
        scores = candidate.quality_scores
        return {
            "架构风格": candidate.name,
            "综合评分": candidate.score,
            "推荐定位": candidate.recommendation_role,
            "置信度": candidate.confidence,
            "扩展性": RecommendationService._stars(scores.get("scalability", 0)),
            "性能": RecommendationService._stars(scores.get("performance", 0)),
            "可靠性": RecommendationService._stars(scores.get("reliability", 0)),
            "可维护性": RecommendationService._stars(scores.get("modifiability", 0)),
            "实时性": RecommendationService._stars(scores.get("realtime", 0)),
            "复杂度友好度": RecommendationService._complexity_label(scores.get("complexity", 0)),
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
