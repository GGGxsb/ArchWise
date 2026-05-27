from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.models.schemas import CandidateEvaluation, ExtractedFeatures


@dataclass(frozen=True)
class RuleDecision:
    preferred_style_ids: list[str]
    rejected_style_ids: list[str]
    reasons: list[str]
    fired_rule_ids: list[str]


class RuleEngine:
    """Configurable lightweight rule engine for hard constraints and LLM guardrails."""

    def __init__(self, rules_file: Path | None = None) -> None:
        self.rules_file = rules_file or Path("data/rules.json")
        self.rules = self._load_rules()

    def evaluate(self, features: ExtractedFeatures) -> RuleDecision:
        preferred: list[str] = []
        rejected: list[str] = []
        reasons: list[str] = []
        fired: list[str] = []

        for rule in self.rules:
            if not self._matches(rule, features):
                continue
            fired.append(rule["id"])
            preferred.extend(rule.get("prefer", []))
            rejected.extend(rule.get("reject", []))
            reasons.append(f"{rule['id']}：{rule['reason']}")

        return RuleDecision(
            preferred_style_ids=list(dict.fromkeys(preferred)),
            rejected_style_ids=list(dict.fromkeys(rejected)),
            reasons=reasons,
            fired_rule_ids=fired,
        )

    def validate_candidates(
        self,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
        decision: RuleDecision,
    ) -> tuple[list[CandidateEvaluation], list[str]]:
        notes: list[str] = []
        filtered = list(candidates)
        rejected = [item for item in filtered if item.style_id in decision.rejected_style_ids]
        if rejected:
            notes.append(f"规则引擎硬约束校验：{', '.join(item.name for item in rejected)} 被降权并标记为不推荐。")
            for item in rejected:
                item.score = max(45, round(item.score - 12, 1))
                item.risks.append("规则引擎硬约束认为该风格不适合作为优先方案")
                item.deductions.append("触发规则引擎硬约束降权")

        if features.quality_attributes.get("realtime", 0) >= 0.7 and filtered[0].quality_scores.get("realtime", 0) < 0.55:
            notes.append("规则引擎二次校验：最高候选实时性不足，优先选择实时性更强的候选。")
            filtered[0].deductions.append("规则二次校验发现实时性不足")
            filtered[0].score = max(55, round(filtered[0].score - 5, 1))
            filtered.sort(key=lambda item: (item.quality_scores.get("realtime", 0), item.score), reverse=True)

        if features.quality_attributes.get("concurrency", 0) >= 0.7 and filtered[0].quality_scores.get("scalability", 0) < 0.6:
            notes.append("规则引擎二次校验：最高候选扩展性不足，重新按扩展性排序。")
            filtered[0].deductions.append("规则二次校验发现扩展性不足")
            filtered[0].score = max(55, round(filtered[0].score - 5, 1))
            filtered.sort(key=lambda item: (item.quality_scores.get("scalability", 0), item.score), reverse=True)

        self._refresh_roles(filtered)
        return filtered, notes

    @staticmethod
    def _refresh_roles(candidates: list[CandidateEvaluation]) -> None:
        if not candidates:
            return
        candidates.sort(key=lambda item: item.score, reverse=True)
        if len(candidates) == 1:
            candidates[0].recommendation_role = "核心推荐"
            candidates[0].confidence = "高"
            return

        gap = candidates[0].score - candidates[1].score
        for index, item in enumerate(candidates):
            has_hard_constraint = any("硬约束" in deduction or "排除" in deduction for deduction in item.deductions)
            unique_deductions = list(dict.fromkeys(item.deductions))
            if has_hard_constraint:
                hard_items = [deduction for deduction in unique_deductions if "硬约束" in deduction or "排除" in deduction]
                other_items = [deduction for deduction in unique_deductions if deduction not in hard_items]
                item.deductions = (hard_items + other_items)[:4]
            else:
                item.deductions = unique_deductions[:4]
            if index == 0:
                item.recommendation_role = "核心推荐" if gap >= 3 else "核心推荐/组合候选"
                item.confidence = "高" if gap >= 8 else "中高" if gap >= 3 else "中"
            elif index == 1:
                item.recommendation_role = "备选方案" if gap >= 3 else "组合备选"
                item.confidence = "中高" if item.score >= 85 else "中"
            elif has_hard_constraint:
                item.recommendation_role = "不推荐"
                item.confidence = "低"
            else:
                item.recommendation_role = "专项补充"
                item.confidence = "中" if item.score >= 78 else "中低"

    def _matches(self, rule: dict, features: ExtractedFeatures) -> bool:
        if rule.get("data_flow") and rule["data_flow"] != features.data_flow:
            return False

        for key, threshold in rule.get("conditions", {}).items():
            if features.quality_attributes.get(key, 0) < threshold:
                return False

        for key, maximum in rule.get("max_conditions", {}).items():
            if features.quality_attributes.get(key, 0) > maximum:
                return False

        return True

    def _load_rules(self) -> list[dict]:
        if not self.rules_file.exists():
            return []
        return json.loads(self.rules_file.read_text(encoding="utf-8"))
