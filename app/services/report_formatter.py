from __future__ import annotations

import re

from app.models.schemas import ArchitectureStyle, CandidateEvaluation, ExtractedFeatures


class ReportFormatter:
    @staticmethod
    def build_markdown(
        requirement: str,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
        styles: dict[str, ArchitectureStyle],
        analysis: str,
    ) -> str:
        winner = candidates[0]
        backup = candidates[1] if len(candidates) > 1 else None
        style = styles[winner.style_id]
        analysis = ReportFormatter.clean_markdown(analysis)

        return (
            f"# 架构推荐评估报告\n\n"
            f"## 需求理解\n\n"
            f"{ReportFormatter._feature_summary(features)}\n\n"
            f"## 候选架构对比\n\n"
            f"{ReportFormatter.build_markdown_matrix(candidates)}\n\n"
            f"## 最终推荐\n\n"
            f"{ReportFormatter._recommendation_line(winner, backup)}\n\n"
            f"{ReportFormatter._decision_summary(candidates)}\n\n"
            f"## 适配理由\n\n"
            f"{ReportFormatter._reference_reasons(winner, analysis)}\n\n"
            f"{analysis}\n\n"
            f"## 优势与收益\n\n"
            f"{ReportFormatter._bullet_list(style.strengths[:4])}\n\n"
            f"## 风险与约束\n\n"
            f"{ReportFormatter._risk_list(winner, style)}\n\n"
            f"## 落地建议\n\n"
            f"- 以 **{winner.name}** 作为核心架构风格，优先设计关键模块边界和数据流路径。\n"
            f"- 对高风险质量属性建立压测、监控、链路追踪和故障恢复验证。\n"
            f"- 将本次推荐结果、扣分原因和后续验证结论沉淀到知识图谱，形成案例学习闭环。\n"
        )

    @staticmethod
    def build_report_prefix(requirement: str, features: ExtractedFeatures, candidates: list[CandidateEvaluation]) -> str:
        winner = candidates[0]
        backup = candidates[1] if len(candidates) > 1 else None
        return (
            f"# 架构推荐评估报告\n\n"
            f"## 需求理解\n\n"
            f"{ReportFormatter._feature_summary(features)}\n\n"
            f"## 候选架构对比\n\n"
            f"{ReportFormatter.build_markdown_matrix(candidates)}\n\n"
            f"## 最终推荐\n\n"
            f"{ReportFormatter._recommendation_line(winner, backup)}\n\n"
            f"{ReportFormatter._decision_summary(candidates)}\n\n"
            f"## 适配理由\n\n"
            f"{ReportFormatter._reference_reasons(winner, '')}\n\n"
        )

    @staticmethod
    def build_report_suffix(winner: CandidateEvaluation, styles: dict[str, ArchitectureStyle]) -> str:
        style = styles[winner.style_id]
        return (
            f"\n\n## 优势与收益\n\n"
            f"{ReportFormatter._bullet_list(style.strengths[:4])}\n\n"
            f"## 风险与约束\n\n"
            f"{ReportFormatter._risk_list(winner, style)}\n\n"
        )

    @staticmethod
    def build_report_footer(winner: CandidateEvaluation) -> str:
        return (
            f"\n\n## 落地建议\n\n"
            f"- 以 **{winner.name}** 作为核心架构风格，优先设计关键模块边界和数据流路径。\n"
            f"- 对高风险质量属性建立压测、监控、链路追踪和故障恢复验证。\n"
            f"- 将本次推荐结果、扣分原因和后续验证结论沉淀到知识图谱，形成案例学习闭环。\n"
        )

    @staticmethod
    def build_markdown_matrix(candidates: list[CandidateEvaluation]) -> str:
        rows = [
            "| 架构风格 | 综合评分 | 定位 | 置信度 | 扩展性 | 性能 | 可靠性 | 实时性 | 复杂度 | 扣分原因 |",
            "| --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for item in candidates:
            scores = item.quality_scores
            deductions = "；".join(item.deductions[:2]) if item.deductions else "无明显扣分"
            rows.append(
                "| "
                f"{item.name} | "
                f"**{item.score}/100** | "
                f"{item.recommendation_role} | "
                f"{item.confidence} | "
                f"{ReportFormatter._stars(scores.get('scalability', 0))} | "
                f"{ReportFormatter._stars(scores.get('performance', 0))} | "
                f"{ReportFormatter._stars(scores.get('reliability', 0))} | "
                f"{ReportFormatter._stars(scores.get('realtime', 0))} | "
                f"{ReportFormatter._complexity_label(scores.get('complexity', 0))} | "
                f"{deductions} |"
            )
        return "\n".join(rows)

    @staticmethod
    def clean_markdown(content: str) -> str:
        content = re.sub(r"```(?:markdown)?\s*|\s*```", "", content.strip())
        content = re.sub(r"^# .*$", "", content, flags=re.M)
        content = re.sub(r"^##\s*(推荐理由|优点|缺点.*|落地建议|需求理解|候选架构对比|最终推荐|适配理由|优势.*|风险.*).*$", "", content, flags=re.M)
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip() or "- 当前候选架构与需求特征匹配度较高，建议结合团队能力和部署环境进一步细化。"

    @staticmethod
    def _feature_summary(features: ExtractedFeatures) -> str:
        qualities = features.quality_attributes
        rows = [
            f"- **关键词**：{'、'.join(features.keywords) if features.keywords else '暂无'}",
            f"- **并发需求**：{ReportFormatter._level(qualities.get('concurrency', 0))}",
            f"- **实时性**：{ReportFormatter._level(qualities.get('realtime', 0))}",
            f"- **可靠性**：{ReportFormatter._level(qualities.get('reliability', 0))}",
            f"- **扩展性**：{ReportFormatter._level(qualities.get('scalability', 0))}",
            f"- **部署约束**：{'、'.join(features.constraints.get('deployment', [])) or '未明确'}",
        ]
        if features.ambiguity_notes:
            rows.append(f"- **模糊点**：{'；'.join(features.ambiguity_notes)}")
        return "\n".join(rows)

    @staticmethod
    def _bullet_list(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items)

    @staticmethod
    def _recommendation_line(winner: CandidateEvaluation, backup: CandidateEvaluation | None) -> str:
        if backup:
            return f"**推荐架构：{winner.name}（{winner.recommendation_role}，{winner.score}/100）、{backup.name}（{backup.recommendation_role}，{backup.score}/100）**"
        return f"**推荐架构：{winner.name}（{winner.recommendation_role}，{winner.score}/100）**"

    @staticmethod
    def _reference_reasons(winner: CandidateEvaluation, analysis: str) -> str:
        reasons = list(winner.matched_reasons[:3])
        llm_lines = [
            line.lstrip("- ").strip()
            for line in ReportFormatter.clean_markdown(analysis).splitlines()
            if line.strip().startswith("- ")
        ]
        for line in llm_lines:
            if line and line not in reasons:
                reasons.append(line)
        if not reasons:
            reasons = ["该架构与需求中的关键质量属性匹配度最高。"]
        return "\n".join(f"- {reason}" for reason in reasons[:3])

    @staticmethod
    def _check_list(items: list[str], mark: str) -> str:
        return "\n".join(f"{mark} {item}" for item in items)

    @staticmethod
    def _weakness_list(winner: CandidateEvaluation, style: ArchitectureStyle) -> str:
        items = list(style.weaknesses[:3])
        for deduction in winner.deductions:
            if deduction not in items:
                items.append(deduction)
        return ReportFormatter._check_list(items[:5], "×")

    @staticmethod
    def _risk_list(winner: CandidateEvaluation, style: ArchitectureStyle) -> str:
        items = list(style.weaknesses[:3])
        for risk in winner.risks:
            if risk not in items:
                items.append(risk)
        for deduction in winner.deductions:
            if deduction not in items:
                items.append(deduction)
        if not items:
            items.append("暂无明显硬性冲突，建议在详细设计阶段继续校验非功能指标。")
        return ReportFormatter._bullet_list(items[:6])

    @staticmethod
    def _decision_summary(candidates: list[CandidateEvaluation]) -> str:
        if not candidates:
            return "- 决策摘要：暂无候选架构。"
        if len(candidates) == 1:
            return f"- 决策摘要：{candidates[0].name} 为唯一候选，置信度为 {candidates[0].confidence}。"
        gap = round(candidates[0].score - candidates[1].score, 1)
        if gap < 3:
            return f"- 决策摘要：前两名分差 {gap} 分，建议采用 **{candidates[0].name}** 为主、结合 **{candidates[1].name}** 的局部能力。"
        return f"- 决策摘要：{candidates[0].name} 领先备选方案 {gap} 分，推荐置信度为 {candidates[0].confidence}。"

    @staticmethod
    def _stars(value: float) -> str:
        count = max(1, min(5, round(value * 5)))
        return "★" * count + "☆" * (5 - count)

    @staticmethod
    def _level(value: float) -> str:
        if value >= 0.75:
            return "高"
        if value >= 0.4:
            return "中"
        return "低"

    @staticmethod
    def _complexity_label(value: float) -> str:
        if value >= 0.75:
            return "较低"
        if value >= 0.5:
            return "中等"
        return "较高"
