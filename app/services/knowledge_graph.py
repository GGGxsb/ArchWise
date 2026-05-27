from __future__ import annotations

import os

from app.models.schemas import ArchitectureStyle, ExtractedFeatures
from app.services.neo4j_aura import Neo4jAuraService


QUALITY_TO_SCENARIO = {
    "concurrency": ["高并发", "即时通信", "高并发异步处理", "突发流量"],
    "realtime": ["实时消息", "即时通信", "交易通知", "IoT 事件流"],
    "reliability": ["金融业务", "订单交易", "审计系统"],
    "scalability": ["快速迭代产品", "复杂业务平台", "多团队协作", "弹性伸缩系统"],
    "data_intensity": ["数据处理", "ETL", "日志分析", "批处理流水线"],
    "ai_reasoning": ["AI 诊断", "专家系统", "多智能体推理"],
}


class KnowledgeGraphService:
    def __init__(self) -> None:
        self.neo4j = Neo4jAuraService()

    def build_graph(self, styles: list[ArchitectureStyle]) -> dict[str, list[dict[str, str]]]:
        if self.neo4j.configured:
            graph = self.neo4j.fetch_graph()
            if graph["nodes"]:
                return graph

        nodes: dict[str, dict[str, str]] = {}
        edges: list[dict[str, str]] = []

        for style in styles:
            style_node = f"style:{style.id}"
            nodes[style_node] = {"id": style_node, "label": style.name, "type": "architecture_style"}
            nodes[f"category:{style.category}"] = {"id": f"category:{style.category}", "label": style.category, "type": "category"}
            edges.append({"source": style_node, "target": f"category:{style.category}", "relation": "BELONGS_TO"})

            for scenario in style.suitable_for:
                scenario_node = f"scenario:{scenario}"
                nodes[scenario_node] = {"id": scenario_node, "label": scenario, "type": "scenario"}
                edges.append({"source": style_node, "target": scenario_node, "relation": "SUITABLE_FOR"})

            for quality, score in style.quality_scores.items():
                quality_node = f"quality:{quality}"
                nodes[quality_node] = {"id": quality_node, "label": quality, "type": "quality_attribute"}
                edges.append({"source": style_node, "target": quality_node, "relation": f"HAS_SCORE:{score}"})

        return {"nodes": list(nodes.values()), "edges": edges}

    def retrieve_styles(self, features: ExtractedFeatures, styles: list[ArchitectureStyle]) -> list[tuple[str, float, str]]:
        """Retrieve styles through graph-like Style-Scenario-Quality relations.

        The demo uses in-memory graph data. If Neo4j is configured later, this
        method is the seam to replace with Cypher queries while keeping the
        orchestrator unchanged.
        """
        matches: list[tuple[str, float, str]] = []
        active_quality = [
            quality for quality, value in features.quality_attributes.items()
            if value >= 0.6
        ]

        for style in styles:
            score = 0.0
            reasons: list[str] = []
            scenario_text = " ".join(style.suitable_for)
            keyword_text = " ".join(features.keywords)

            for quality in active_quality:
                architecture_quality = self._quality_name(quality)
                quality_score = style.quality_scores.get(architecture_quality, 0)
                if quality_score >= 0.68:
                    score += quality_score * 0.2
                    reasons.append(f"质量属性 {quality} 匹配")

                for scenario in QUALITY_TO_SCENARIO.get(quality, []):
                    if scenario in scenario_text:
                        score += 0.16
                        reasons.append(f"适用场景 {scenario} 匹配")

            for scenario in style.suitable_for:
                if scenario in keyword_text or scenario in features.domain:
                    score += 0.18
                    reasons.append(f"领域场景 {scenario} 匹配")

            if score > 0:
                matches.append((style.id, round(score, 3), "、".join(list(dict.fromkeys(reasons))[:3])))

        matches.sort(key=lambda item: item[1], reverse=True)
        return matches

    def neo4j_status(self) -> dict[str, object]:
        return self.neo4j.status()

    def sync_to_neo4j(self, styles: list[ArchitectureStyle]) -> dict[str, object]:
        style_result = self.neo4j.sync_styles(styles)
        topology_result = self.neo4j.sync_domain_topology()
        singleton_result = self.neo4j.sync_singleton_components()
        return {
            "ok": bool(style_result.get("ok") and topology_result.get("ok") and singleton_result.get("ok")),
            "styles": style_result,
            "domain_topology": topology_result,
            "singletons": singleton_result,
        }

    def retrieve_topology_knowledge(self, requirement: str, features: ExtractedFeatures) -> dict[str, object]:
        if self.neo4j.configured:
            result = self.neo4j.retrieve_topology_knowledge(
                requirement,
                features.keywords,
                features.quality_attributes,
            )
            if result.get("components") or result.get("stores"):
                return result
        return {"components": [], "stores": [], "edges": [], "scenarios": [], "capabilities": []}

    @staticmethod
    def _quality_name(feature_name: str) -> str:
        mapping = {
            "concurrency": "scalability",
            "realtime": "realtime",
            "reliability": "reliability",
            "scalability": "scalability",
            "data_intensity": "performance",
            "ai_reasoning": "modifiability",
        }
        return mapping.get(feature_name, feature_name)
