"""In-memory graph builder for frontend architecture visualization.

Neo4j has been removed — the primary topology path uses LLM-driven StyleSchema
rendering and does not require an external graph database. This module retains
a lightweight build_graph() for the frontend knowledge-graph overview tab.
"""

from __future__ import annotations

from app.models.schemas import ArchitectureStyle


class KnowledgeGraphService:
    """Builds a graph representation of architecture styles for visualization."""

    @staticmethod
    def build_graph(styles: list[ArchitectureStyle]) -> dict[str, list[dict[str, str]]]:
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
