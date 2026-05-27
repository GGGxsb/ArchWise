from __future__ import annotations

from typing import Any

from app.models.schemas import CandidateEvaluation, ExtractedFeatures


class CompositionRecommender:
    """Rule-driven lightweight architecture composition recommender."""

    SIMPLE_DOMAINS = {"企业管理", "博客系统", "图书管理", "通用业务系统"}

    def recommend(
        self,
        requirement: str,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
    ) -> dict[str, Any]:
        winner = candidates[0]
        candidate_map = {item.style_id: item for item in candidates}
        needed, triggers, warnings = self._composition_need(features, candidates)

        if not needed:
            return {
                "composition_needed": False,
                "primary_style": winner.name,
                "supporting_styles": [],
                "reason": self._single_style_reason(features, winner),
                "triggers": triggers,
                "overengineering_warnings": warnings,
            }

        supporting = self._supporting_styles(requirement, features, winner, candidate_map)
        if not supporting:
            return {
                "composition_needed": False,
                "primary_style": winner.name,
                "supporting_styles": [],
                "reason": "候选架构中没有足够明确的辅助模式证据，建议先采用单一核心架构并保留演进空间。",
                "triggers": triggers,
                "overengineering_warnings": ["避免为了组合而引入额外治理和部署复杂度。"],
            }

        return {
            "composition_needed": True,
            "primary_style": winner.name,
            "supporting_styles": supporting[:3],
            "reason": self._composition_reason(features, winner, supporting),
            "triggers": triggers,
            "overengineering_warnings": warnings,
        }

    def _composition_need(
        self,
        features: ExtractedFeatures,
        candidates: list[CandidateEvaluation],
    ) -> tuple[bool, list[str], list[str]]:
        qualities = features.quality_attributes
        triggers: list[str] = []
        warnings: list[str] = []

        simple_scale = (
            qualities.get("concurrency", 0) < 0.4
            and qualities.get("realtime", 0) < 0.4
            and qualities.get("scalability", 0) < 0.5
            and qualities.get("data_intensity", 0) < 0.5
        )
        if simple_scale:
            warnings.append("需求规模和质量属性压力较低，组合架构可能带来过度设计。")

        if features.domain in self.SIMPLE_DOMAINS and simple_scale:
            warnings.append("业务场景偏管理或 CRUD，单一分层/MVC/单体风格通常更经济。")

        if len(candidates) >= 2 and candidates[0].score - candidates[1].score >= 12 and simple_scale:
            warnings.append("第一候选优势明显，缺少引入辅助架构模式的必要性。")

        if warnings:
            return False, triggers, warnings

        if qualities.get("concurrency", 0) >= 0.75 and qualities.get("realtime", 0) >= 0.65:
            triggers.append("高并发 + 实时性需求需要异步解耦和独立扩展协同。")
        if qualities.get("scalability", 0) >= 0.75:
            triggers.append("扩展性诉求明确，需要清晰模块边界和独立演进能力。")
        if qualities.get("data_intensity", 0) >= 0.65 or features.data_flow == "pipeline":
            triggers.append("数据处理链路较重，需要专项数据流或流水线模式支撑。")
        if features.data_flow == "transactional":
            triggers.append("事务/查询压力明显，可能需要读写分离或领域隔离补充。")
        if self._score_gap(candidates) < 6:
            triggers.append("前两名候选分差较小，存在组合使用价值。")

        return bool(triggers), triggers, warnings

    def _supporting_styles(
        self,
        requirement: str,
        features: ExtractedFeatures,
        winner: CandidateEvaluation,
        candidate_map: dict[str, CandidateEvaluation],
    ) -> list[dict[str, Any]]:
        text = requirement + " " + " ".join(features.keywords)
        supporting: list[dict[str, Any]] = []

        def add(style_id: str, role: str, apply_to: list[str], reason: str) -> None:
            item = candidate_map.get(style_id)
            if not item or item.style_id == winner.style_id:
                return
            supporting.append(
                {
                    "style_id": style_id,
                    "style": item.name,
                    "role": role,
                    "apply_to": apply_to,
                    "reason": reason,
                    "score": item.score,
                }
            )

        if winner.style_id == "event_driven":
            add(
                "microservices",
                "服务拆分与独立扩展",
                ["用户服务", "消息服务", "媒体服务", "通知服务"],
                "事件驱动负责异步解耦，微服务负责业务边界和独立部署。",
            )
        if features.data_flow == "event_stream" or "消息" in text or "通知" in text:
            add(
                "cqrs",
                "高频查询与读写分离",
                ["消息历史", "会话列表", "通知查询", "状态查询"],
                "事件流系统常存在写入事件和读取查询压力差异，CQRS 可用于局部读写优化。",
            )
        if any(keyword in text for keyword in ["视频", "图片", "转码", "录播", "大数据", "ETL", "日志"]):
            add(
                "pipe_filter",
                "媒体/数据流水线处理",
                ["转码任务", "文件处理", "日志清洗", "离线分析"],
                "媒体和数据处理适合拆分为可组合的处理阶段。",
            )
        if features.quality_attributes.get("scalability", 0) >= 0.75 and winner.style_id != "microservices":
            add(
                "microservices",
                "模块独立演进",
                ["核心业务服务", "扩展服务", "第三方集成"],
                "高扩展诉求需要独立部署和模块化治理能力。",
            )
        if any(keyword in text for keyword in ["突发", "峰值", "低运维", "图片生成", "任务"]):
            add(
                "serverless",
                "弹性任务处理",
                ["异步任务", "图片生成", "通知推送", "自动化处理"],
                "突发任务和轻运维场景可局部采用 Serverless 降低资源管理成本。",
            )

        deduped: dict[str, dict[str, Any]] = {}
        for item in supporting:
            deduped.setdefault(item["style_id"], item)
        return sorted(deduped.values(), key=lambda item: item["score"], reverse=True)

    @staticmethod
    def _score_gap(candidates: list[CandidateEvaluation]) -> float:
        if len(candidates) < 2:
            return 99
        return candidates[0].score - candidates[1].score

    @staticmethod
    def _single_style_reason(features: ExtractedFeatures, winner: CandidateEvaluation) -> str:
        return (
            f"{features.domain} 场景当前质量属性压力不高，"
            f"采用 {winner.name} 作为单一核心架构即可满足实现、维护和部署要求。"
        )

    @staticmethod
    def _composition_reason(
        features: ExtractedFeatures,
        winner: CandidateEvaluation,
        supporting: list[dict[str, Any]],
    ) -> str:
        styles = "、".join(item["style"] for item in supporting)
        return (
            f"{features.domain} 场景存在多维质量属性诉求，建议以 {winner.name} 为核心，"
            f"局部组合 {styles}，分别处理扩展、查询、异步或专项处理链路。"
        )
