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
    ) -> str:
        llm_report = await self.llm_client.generate_report(requirement, features, candidates)
        analysis = llm_report or self._fallback_analysis(features, candidates)
        return ReportFormatter.build_markdown(requirement, features, candidates, styles, analysis)

    def _fallback_report(
        self,
        requirement: str,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
        styles: dict[str, ArchitectureStyle],
    ) -> str:
        winner = candidates[0]
        style = styles[winner.style_id]
        alternatives = "、".join(item.name for item in candidates[1:])
        reasons = "\n".join(f"- {reason}" for reason in winner.matched_reasons)
        strengths = "\n".join(f"- {item}" for item in style.strengths[:4])
        weaknesses = "\n".join(f"- {item}" for item in style.weaknesses[:3])
        risks = "\n".join(f"- {risk}" for risk in winner.risks) if winner.risks else "- 暂无明显硬性冲突，建议在详细设计阶段继续校验非功能指标。"

        return (
            f"最终推荐：{winner.name}（评分 {winner.score}/100）。\n\n"
            f"需求领域识别为：{features.domain}，主要数据流类型为：{features.data_flow}。\n"
            f"候选备选方案：{alternatives}。\n\n"
            "推荐理由：\n"
            f"{reasons}\n\n"
            "优点：\n"
            f"{strengths}\n\n"
            "缺点与风险：\n"
            f"{weaknesses}\n"
            f"{risks}\n\n"
            "落地建议：优先建立清晰的服务边界、统一观测日志与接口契约；对高风险质量属性使用规则引擎持续校验，并把新项目案例写入知识库形成知识进化闭环。"
        )

    def _fallback_analysis(
        self,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
    ) -> str:
        winner = candidates[0]
        risks = "\n".join(f"- 风险：{risk}" for risk in winner.risks[:2])
        if not risks:
            risks = "- 风险：需要在详细设计阶段继续验证性能、可靠性和部署复杂度。"
        return (
            f"- **综合判断**：{winner.name} 与 {features.domain} 场景的关键质量属性匹配度最高，适合作为本次方案的主架构风格。\n"
            f"{risks}"
        )
