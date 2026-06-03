"""Style-aware topology renderer — validates LLM-filled StyleInstances against
their StyleSchema, then produces Mermaid diagrams and structured view graphs.

Replaces the monolithic rule-based TopologyGenerator for the primary code path.
The old generator is retained as a fallback in the orchestrator.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from app.knowledge.style_schemas import get_schema
from app.models.schemas import (
    ComposeStyleInstances,
    ConnectionDef,
    LayerConnectionRule,
    LayerSpec,
    StyleInstance,
    StyleSchema,
)


# ───────────────── dataclasses for internal graph representation ─────────────────


@dataclass(frozen=True)
class RenderNode:
    id: str
    name: str
    layer: str
    style_id: str = ""


@dataclass(frozen=True)
class RenderEdge:
    source: str
    target: str
    label: str = ""
    kind: str = "sync"
    style_id: str = ""


# ───────────────── validation ─────────────────


class SchemaValidationError(Exception):
    """Raised when a StyleInstance violates its StyleSchema constraints."""


class StyleTopologyRenderer:
    """Schema-driven topology renderer.

    Usage:
        renderer = StyleTopologyRenderer()
        schema = get_schema("monolithic_layered")
        instance = StyleInstance(style_id="monolithic_layered", components=[...], connections=[...])
        mermaid, graphs = renderer.render(schema, instance)
    """

    def render(
        self,
        schema: StyleSchema,
        instance: StyleInstance,
        notes: list[str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Produce Mermaid string and structured graph for a single style instance."""
        notes = notes or []
        self._validate(instance, schema, notes)
        nodes, edges = self._build_graph(instance, schema, notes)
        mermaid = self._render_mermaid(nodes, edges, schema)
        structured = self._serialize_graph(nodes, edges)
        return mermaid, structured

    def render_views(
        self,
        schema: StyleSchema,
        instance: StyleInstance,
        notes: list[str] | None = None,
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]], list[str]]:
        """Produce multi-view diagrams and structured graphs."""
        notes = notes or []
        self._validate(instance, schema, notes)
        nodes, edges = self._build_graph(instance, schema, notes)

        node_map = {n.id: n for n in nodes}
        overview_nodes, overview_edges = self._aggregate_dense(nodes, edges)

        diagrams = {
            "总览图": self._render_mermaid(overview_nodes, overview_edges, schema),
            "完整图": self._render_mermaid(nodes, edges, schema),
            "业务链路图": self._render_mermaid(*self._project_view(nodes, edges, "business", node_map), schema),
            "数据流图": self._render_mermaid(*self._project_view(nodes, edges, "data", node_map), schema),
            "支撑设施图": self._render_mermaid(*self._project_view(nodes, edges, "support", node_map), schema),
        }
        graphs = {
            "总览图": self._serialize_graph(overview_nodes, overview_edges),
            "完整图": self._serialize_graph(nodes, edges),
            "业务链路图": self._serialize_graph(*self._project_view(nodes, edges, "business", node_map)),
            "数据流图": self._serialize_graph(*self._project_view(nodes, edges, "data", node_map)),
            "支撑设施图": self._serialize_graph(*self._project_view(nodes, edges, "support", node_map)),
        }
        return diagrams, graphs, notes

    def render_composed(
        self,
        composed: ComposeStyleInstances,
        notes: list[str] | None = None,
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]], list[str]]:
        """Render a composed architecture with primary + supporting styles."""
        notes = notes or []
        all_nodes: list[RenderNode] = []
        all_edges: list[RenderEdge] = []

        prim_schema = get_schema(composed.primary.style_id)
        if prim_schema:
            self._validate(composed.primary, prim_schema, notes)
            n, e = self._build_graph(composed.primary, prim_schema, notes)
            all_nodes.extend(n)
            all_edges.extend(e)

        for supp in composed.supporting:
            supp_schema = get_schema(supp.style_id)
            if supp_schema:
                self._validate(supp, supp_schema, notes)
                n, e = self._build_graph(supp, supp_schema, notes)
                # prefix node ids to avoid collisions
                for node in n:
                    all_nodes.append(RenderNode(
                        id=f"{supp.style_id}_{node.id}",
                        name=node.name,
                        layer=f"[{supp.style_id}] {node.layer}",
                        style_id=supp.style_id,
                    ))
                for edge in e:
                    all_edges.append(RenderEdge(
                        source=f"{supp.style_id}_{edge.source}",
                        target=f"{supp.style_id}_{edge.target}",
                        label=edge.label,
                        kind=edge.kind,
                        style_id=supp.style_id,
                    ))

        primary_schema = prim_schema or self._fallback_schema()
        diagrams = {
            "总览图": self._render_mermaid(all_nodes, all_edges, primary_schema),
            "完整图": self._render_mermaid(all_nodes, all_edges, primary_schema),
        }
        graphs = {
            "总览图": self._serialize_graph(all_nodes, all_edges),
            "完整图": self._serialize_graph(all_nodes, all_edges),
        }
        return diagrams, graphs, notes

    # ────────────── validation ──────────────────────────────────

    def _validate(self, instance: StyleInstance, schema: StyleSchema, notes: list[str]) -> None:
        layer_map = {layer.layer_id: layer for layer in schema.layers}
        components_by_layer: dict[str, list[str]] = {}
        for comp in instance.components:
            components_by_layer.setdefault(comp.layer_id, []).append(comp.name)

        # mandatory layers
        for layer in schema.layers:
            count = len(components_by_layer.get(layer.layer_id, []))
            if layer.mandatory and count < layer.min_components:
                raise SchemaValidationError(
                    f"风格「{schema.style_name}」要求层「{layer.label}」至少 {layer.min_components} 个组件，"
                    f"实际 {count} 个。"
                )
            if layer.singleton and count > 1:
                raise SchemaValidationError(
                    f"风格「{schema.style_name}」的层「{layer.label}」为单例，最多 1 个组件，"
                    f"实际 {count} 个。"
                )
            if layer.max_components and count > layer.max_components:
                notes.append(f"风格约束提醒：{layer.label} 超过建议组件数 {layer.max_components}")

        # connection rules
        comp_layer_map = {comp.name: comp.layer_id for comp in instance.components}
        for conn in instance.connections:
            src_layer = comp_layer_map.get(conn.source)
            tgt_layer = comp_layer_map.get(conn.target)
            if not src_layer or not tgt_layer:
                continue
            rule = self._find_connection_rule(schema, src_layer, tgt_layer)
            if rule is None or (not rule.allow_skip and src_layer != tgt_layer):
                notes.append(
                    f"风格约束检查：{conn.source}({src_layer}) → {conn.target}({tgt_layer}) "
                    f"未经层连接规则声明"
                )

    @staticmethod
    def _find_connection_rule(
        schema: StyleSchema,
        source_layer: str,
        target_layer: str,
    ) -> LayerConnectionRule | None:
        for rule in schema.layer_connections:
            if rule.source_layer == source_layer and rule.target_layer == target_layer:
                return rule
            if rule.bidirectional and rule.source_layer == target_layer and rule.target_layer == source_layer:
                return rule
        return None

    # ────────────── graph construction ──────────────────────────

    def _build_graph(
        self,
        instance: StyleInstance,
        schema: StyleSchema,
        notes: list[str],
    ) -> tuple[list[RenderNode], list[RenderEdge]]:
        nodes: dict[str, RenderNode] = {}
        edges: list[RenderEdge] = []

        for comp in instance.components:
            node_id = self._safe_node_id(comp.name)
            layer_label = self._layer_label(schema, comp.layer_id)
            nodes[node_id] = RenderNode(node_id, comp.name, layer_label)

        for conn in instance.connections:
            src_id = self._safe_node_id(conn.source)
            tgt_id = self._safe_node_id(conn.target)
            if src_id in nodes and tgt_id in nodes:
                edges.append(RenderEdge(src_id, tgt_id, conn.label, conn.kind))

        if not edges:
            notes.append("LLM 未提供组件间连接，仅展示组件分组")

        return list(nodes.values()), edges

    @staticmethod
    def _layer_label(schema: StyleSchema, layer_id: str) -> str:
        for layer in schema.layers:
            if layer.layer_id == layer_id:
                return layer.label
        return layer_id

    # ────────────── Mermaid rendering ───────────────────────────

    def _render_mermaid(
        self,
        nodes: list[RenderNode],
        edges: list[RenderEdge],
        schema: StyleSchema,
    ) -> str:
        if not nodes:
            return f"flowchart {schema.layout_direction}\n  empty[暂无节点]"

        layer_order = self._ordered_layers(nodes)
        lines = [f"flowchart {schema.layout_direction}"]
        node_map = {n.id: n for n in nodes}

        # layer subgraphs
        for layer in layer_order:
            layer_nodes = [n for n in nodes if n.layer == layer]
            if not layer_nodes:
                continue
            safe_layer = self._safe_label(layer)
            lines.append(f"  subgraph {safe_layer}[{layer}]")
            for node in layer_nodes:
                lines.append(f"    {node.id}[{self._escape(node.name)}]")
            lines.append("  end")

        # edges
        seen = set()
        for edge in edges:
            if edge.source not in node_map or edge.target not in node_map:
                continue
            key = (edge.source, edge.target, edge.label)
            if key in seen:
                continue
            seen.add(key)
            arrow = self._arrow(edge.kind)
            if edge.label:
                lines.append(f"  {edge.source} {arrow}|{self._escape(edge.label)}| {edge.target}")
            else:
                lines.append(f"  {edge.source} {arrow} {edge.target}")

        return "\n".join(lines)

    # ────────────── structured graph serialization ───────────────

    def _serialize_graph(
        self,
        nodes: list[RenderNode],
        edges: list[RenderEdge],
    ) -> dict[str, Any]:
        node_map = {n.id: n for n in nodes}
        layer_order = self._ordered_layers(nodes)
        return {
            "nodes": [
                {"id": n.id, "label": n.name, "layer": n.layer, "style_id": n.style_id}
                for n in nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "label": e.label,
                    "kind": e.kind,
                    "style_id": e.style_id,
                    "category": self._edge_category(e, node_map),
                }
                for e in edges
                if e.source in node_map and e.target in node_map
            ],
            "layers": layer_order,
        }

    # ────────────── view projection ─────────────────────────────

    def _project_view(
        self,
        nodes: list[RenderNode],
        edges: list[RenderEdge],
        view: str,
        node_map: dict[str, RenderNode],
    ) -> tuple[list[RenderNode], list[RenderEdge]]:
        selected_edges: list[RenderEdge] = []
        for edge in edges:
            cat = self._edge_category(edge, node_map)
            if view == "business" and cat in {"sync", "event"}:
                selected_edges.append(edge)
            elif view == "data" and cat == "data":
                selected_edges.append(edge)
            elif view == "support" and cat == "support":
                selected_edges.append(edge)

        selected_ids = {e.source for e in selected_edges} | {e.target for e in selected_edges}
        if view == "data":
            selected_ids.update(n.id for n in nodes if "数据" in n.layer or "存储" in n.layer or "库" in n.layer)
        elif view == "support":
            selected_ids.update(n.id for n in nodes if "治理" in n.layer or "基础" in n.layer or "监控" in n.layer)

        selected_nodes = [n for n in nodes if n.id in selected_ids] if selected_ids else nodes
        selected_edges = selected_edges if selected_edges else edges
        return selected_nodes, selected_edges

    # ────────────── dense edge aggregation ──────────────────────

    def _aggregate_dense(
        self,
        nodes: list[RenderNode],
        edges: list[RenderEdge],
    ) -> tuple[list[RenderNode], list[RenderEdge]]:
        node_map = {n.id: n for n in nodes}
        aggregate_nodes: dict[str, RenderNode] = dict(node_map)
        aggregate_edges: list[RenderEdge] = []
        consumed: set[int] = set()

        for hub_id, hub in node_map.items():
            grouped_in: dict[str, list[tuple[int, RenderEdge]]] = {}
            grouped_out: dict[str, list[tuple[int, RenderEdge]]] = {}
            for idx, edge in enumerate(edges):
                if edge.target == hub_id and edge.source in node_map:
                    grouped_in.setdefault(node_map[edge.source].layer, []).append((idx, edge))
                if edge.source == hub_id and edge.target in node_map:
                    grouped_out.setdefault(node_map[edge.target].layer, []).append((idx, edge))
            for layer, group in grouped_in.items():
                if len(group) < 3:
                    continue
                agg_id = self._agg_id(hub_id, layer, "in")
                aggregate_nodes[agg_id] = RenderNode(agg_id, f"{layer}组件组", layer)
                primary_label = group[0][1].label
                aggregate_edges.append(RenderEdge(agg_id, hub_id, f"{primary_label} 等{len(group)}条", group[0][1].kind))
                consumed.update(idx for idx, _ in group)
            for layer, group in grouped_out.items():
                if len(group) < 3:
                    continue
                agg_id = self._agg_id(hub_id, layer, "out")
                aggregate_nodes[agg_id] = RenderNode(agg_id, f"{layer}组件组", layer)
                primary_label = group[0][1].label
                aggregate_edges.append(RenderEdge(hub_id, agg_id, f"{primary_label} 等{len(group)}条", group[0][1].kind))
                consumed.update(idx for idx, _ in group)

        for idx, edge in enumerate(edges):
            if idx not in consumed:
                aggregate_edges.append(edge)

        reachable = {e.source for e in aggregate_edges} | {e.target for e in aggregate_edges}
        overview_nodes = [n for n in aggregate_nodes.values() if n.id in reachable]
        return overview_nodes or nodes, aggregate_edges

    # ────────────── helpers ─────────────────────────────────────

    @staticmethod
    def _ordered_layers(nodes: list[RenderNode]) -> list[str]:
        seen: list[str] = []
        for n in nodes:
            if n.layer not in seen:
                seen.append(n.layer)
        return seen

    @staticmethod
    def _safe_node_id(name: str) -> str:
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
        return f"n_{digest}"

    @staticmethod
    def _safe_label(value: str) -> str:
        return "layer_" + str(abs(hash(value)))

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace('"', "'").replace("\n", " ")

    @staticmethod
    def _arrow(kind: str) -> str:
        if kind in {"event"}:
            return "-.->"
        if kind in {"data"}:
            return "==>"
        if kind in {"support", "responsibility"}:
            return "~~~>"
        return "-->"

    @staticmethod
    def _edge_category(edge: RenderEdge, node_map: dict[str, RenderNode]) -> str:
        if edge.kind == "event":
            return "event"
        src = node_map.get(edge.source)
        tgt = node_map.get(edge.target)
        if src and tgt:
            if "数据" in (src.layer + tgt.layer) or "存储" in (src.layer + tgt.layer) or "库" in (src.layer + tgt.layer):
                return "data"
            if "治理" in (src.layer + tgt.layer) or "基础" in (src.layer + tgt.layer):
                return "support"
        return "sync"

    @staticmethod
    def _agg_id(hub_id: str, layer: str, direction: str) -> str:
        digest = hashlib.sha1(f"{hub_id}:{layer}:{direction}".encode("utf-8")).hexdigest()[:8]
        return f"agg_{digest}"

    @staticmethod
    def _fallback_schema() -> StyleSchema:
        return StyleSchema(
            style_id="generic",
            style_name="通用",
            layers=[],
            layer_connections=[],
            topology_template="flowchart TD\n  %%LAYER:default%%\n  %%EDGES%%",
            layout_direction="TD",
        )
