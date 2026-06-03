"""Agent 3: Generate the final architecture evaluation report.

Responsibilities:
- Call LLM for natural-language report generation
- Validate report completeness (required sections present)
- Fallback to template-based report when LLM is unavailable
- Format final Markdown via ReportFormatter
"""

from __future__ import annotations

import re

from app.models.schemas import ArchitectureStyle, CandidateEvaluation, ExtractedFeatures
from app.services.llm_client import LLMClient
from app.services.report_formatter import ReportFormatter


class EvaluationGeneratorAgent:
    """Generates and validates the final evaluation report."""

    REQUIRED_SECTIONS = [
        ("推荐理由", r"推荐理由|适配理由|为何推荐|为什么推荐"),
        ("风险提示", r"风险|注意事项|潜在问题|隐患"),
        ("落地建议", r"落地建议|实施建议|部署建议|实践建议|后续建议"),
    ]

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    async def generate(
        self,
        requirement: str,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
        styles: dict[str, ArchitectureStyle],
    ) -> str:
        """Generate a complete evaluation report, with LLM and fallback paths."""
        llm_report = await self.llm_client.generate_report(requirement, features, candidates)

        analysis: str
        if llm_report:
            missing = self._check_completeness(llm_report)
            if missing:
                supplements = self._build_supplements(missing, features, candidates)
                analysis = llm_report + "\n\n" + supplements
            else:
                analysis = llm_report
        else:
            analysis = self._fallback_analysis(features, candidates)

        return ReportFormatter.build_markdown(requirement, features, candidates, styles, analysis)

    def _check_completeness(self, report: str) -> list[str]:
        """Return list of missing section names."""
        missing: list[str] = []
        for name, pattern in self.REQUIRED_SECTIONS:
            if not re.search(pattern, report):
                missing.append(name)
        return missing

    @staticmethod
    def _build_supplements(
        missing: list[str],
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
    ) -> str:
        """Build supplemental content for missing sections."""
        parts: list[str] = []
        winner = candidates[0]

        if "推荐理由" in missing:
            parts.append(
                "### 推荐理由（补充）\n\n"
                f"首选架构 **{winner.name}**（{winner.score} 分）。\n\n"
                + (
                    "\n".join(f"- {reason}" for reason in winner.matched_reasons)
                    if winner.matched_reasons
                    else f"- 基于 {len(features.business_capabilities)} 项业务能力和 "
                         f"数据流类型 {features.data_flow} 的综合评估"
                )
            )

        if "风险提示" in missing:
            parts.append(
                "### 风险提示（补充）\n\n"
                + (
                    "\n".join(f"- {risk}" for risk in winner.risks)
                    if winner.risks
                    else "- 当前评估未识别到显著风险，建议在详细设计阶段进一步验证。"
                )
            )

        if "落地建议" in missing:
            runner_up = candidates[1] if len(candidates) > 1 else None
            advice = [
                f"1. 以 **{winner.name}** 为核心架构启动原型开发，验证关键技术假设。",
                "2. 关注数据一致性边界，明确各模块的职责和接口契约。",
                "3. 建立架构决策记录（ADR），记录选型依据和备选方案。",
            ]
            if runner_up:
                advice.append(
                    f"4. 将 **{runner_up.name}** 作为备选方案保留，"
                    f"若 {winner.name} 在原型阶段暴露不可接受的缺陷，可快速切换。"
                )
            if features.constraints.get("requires_future_extension"):
                advice.append(
                    "5. 在设计阶段预留扩展点（接口抽象、配置化），"
                    "为后续业务增长保留架构演进空间。"
                )
            parts.append("### 落地建议（补充）\n\n" + "\n".join(advice))

        return "\n\n".join(parts)

    @staticmethod
    def _fallback_analysis(
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
    ) -> str:
        """Generate a complete analysis when LLM is unavailable."""
        winner = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None

        lines = [
            "> 注意：以下内容由本地 Agent 模板生成，LLM 评估报告不可用。建议配置 DeepSeek API Key 以获得更详细的分析。",
            "",
            "### 推荐理由",
            "",
            f"首选架构 **{winner.name}**（{winner.score} 分），基于以下特征匹配：",
            "",
        ]

        for reason in winner.matched_reasons:
            lines.append(f"- {reason}")

        lines.extend([
            "",
            f"业务领域 {features.domain}，包含 {len(features.business_capabilities)} 项业务能力，"
            f"数据流类型为 {features.data_flow}。",
            "",
        ])

        if runner_up:
            lines.append(
                f"备选方案 **{runner_up.name}**（{runner_up.score} 分），"
                f"可作为对比参考或组合候选。"
            )
            lines.append("")

        lines.extend([
            "### 风险提示",
            "",
        ])

        if winner.risks:
            for risk in winner.risks:
                lines.append(f"- {risk}")
        else:
            lines.append("- 本地分析未识别到显著架构风险，建议在实际开发中持续关注。")

        lines.extend([
            "",
            "### 落地建议",
            "",
            f"1. 以 {winner.name} 为核心基线启动原型开发。",
            "2. 建立架构决策记录（ADR），记录选型依据。",
            "3. 在详细设计阶段验证架构假设，必要时调整。",
        ])

        return "\n".join(lines)
