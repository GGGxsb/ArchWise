from __future__ import annotations

from app.models.schemas import ArchitectureStyle, CandidateEvaluation, ExtractedFeatures
from app.services.llm_client import LLMClient
from app.services.report_formatter import ReportFormatter


class EvaluationGeneratorAgent:
    """Agent 3: generate final decision report with LLM assistance when available."""

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    async def generate(
        self,
        requirement: str,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
        styles: dict[str, ArchitectureStyle],
    ) -> str | None:
        llm_report = await self.llm_client.generate_report(requirement, features, candidates)
        if not llm_report:
            return None
        analysis = llm_report
        return ReportFormatter.build_markdown(requirement, features, candidates, styles, analysis)
