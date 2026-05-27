from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.models.schemas import CandidateEvaluation, ExtractedFeatures


@dataclass(frozen=True)
class TopologyNode:
    id: str
    name: str
    layer: str


@dataclass(frozen=True)
class TopologyEdge:
    source: str
    target: str
    label: str = ""
    kind: str = "sync"


class TopologyGenerator:
    """Deterministic topology generator based on capabilities and rules."""

    CANONICAL_COMPONENT_IDS = {
        "客户端": "client",
        "CDN": "cdn",
        "负载均衡": "lb",
        "API网关": "gateway",
        "直播网关": "live_gateway",
        "设备网关": "device_gateway",
        "视频网关": "video_gateway",
        "用户服务": "user",
        "用户库": "user_db",
        "课程服务": "course",
        "课程库": "course_db",
        "直播服务": "live",
        "回放服务": "replay",
        "回放库": "replay_db",
        "作业服务": "homework",
        "作业库": "homework_db",
        "考试服务": "exam",
        "考试库": "exam_db",
        "关系服务": "relation",
        "关系图谱": "graph_db",
        "内容服务": "content",
        "内容库": "content_db",
        "搜索索引": "search",
        "互动服务": "interaction",
        "互动库": "interaction_db",
        "评论服务": "comment",
        "私信服务": "message",
        "消息库": "message_db",
        "Feed服务": "feed",
        "Feed缓存": "feed_cache",
        "推荐服务": "recommend",
        "特征库": "feature_store",
        "审核服务": "moderation",
        "通知服务": "notify",
        "消息服务": "message_service",
        "状态服务": "status_service",
        "状态缓存": "status_cache",
        "信令服务": "signaling_service",
        "缓存集群": "cache",
        "消息队列": "event_bus",
        "事件总线": "event_bus",
        "媒体服务": "media",
        "转码服务": "transcode",
        "对象存储": "object_store",
        "AI服务": "ai",
        "服务注册": "service_registry",
        "监控服务": "monitoring",
        "审计服务": "audit",
    }

    SINGLETON_COMPONENTS = {
        "客户端", "CDN", "负载均衡", "API网关", "直播网关", "设备网关", "视频网关",
        "事件总线", "消息队列", "任务队列", "数据管道", "缓存集群", "对象存储",
        "搜索索引", "特征库", "模型库", "服务注册", "监控服务", "审计服务",
    }

    SOCIAL_KEYWORDS = ["社交", "发帖", "点赞", "评论", "私信", "内容推荐", "关注", "粉丝"]
    EDUCATION_KEYWORDS = ["在线教育", "上课", "课程", "直播", "录播", "回放", "课后互动", "作业", "考试", "课堂"]
    MEDIA_KEYWORDS = ["视频", "图片", "短视频", "转码", "直播", "录播"]
    COMMERCE_KEYWORDS = ["订单", "支付", "退款", "库存", "促销", "下单"]
    IOT_KEYWORDS = ["设备", "传感器", "采集", "告警", "远程控制"]
    AI_KEYWORDS = ["AI", "智能", "推荐算法", "生成", "大模型"]

    def generate(
        self,
        requirement: str,
        features: ExtractedFeatures,
        winner: CandidateEvaluation,
        extra_capabilities: list[str] | None = None,
        graph_knowledge: dict | None = None,
        composition_recommendation: dict | None = None,
    ) -> tuple[str, list[str]]:
        graph_knowledge = graph_knowledge or {}
        composition_recommendation = composition_recommendation or {}
        graph_primary = self._has_graph_knowledge(graph_knowledge)
        if graph_primary:
            capabilities = list(graph_knowledge.get("capabilities", []))
        else:
            capabilities = self.extract_capabilities(requirement, features)
        capabilities.extend(extra_capabilities or [])
        capabilities = list(dict.fromkeys(capabilities))
        nodes, edges, notes = self._build_graph(capabilities, features, winner, graph_knowledge, composition_recommendation)
        return self._render_mermaid(nodes, edges), notes

    def extract_capabilities(self, requirement: str, features: ExtractedFeatures) -> list[str]:
        text = requirement + " " + " ".join(features.keywords) + " " + features.domain
        capabilities: list[str] = []

        if any(keyword in text for keyword in self.SOCIAL_KEYWORDS):
            capabilities.extend(["社交", "用户", "内容", "互动", "评论", "私信", "Feed", "关系", "推荐", "审核"])
        if any(keyword in text for keyword in self.EDUCATION_KEYWORDS):
            capabilities.extend(["教育", "用户", "课程", "直播", "录播", "互动", "作业", "考试", "通知", "媒体", "CDN"])
        if any(keyword in text for keyword in self.MEDIA_KEYWORDS):
            capabilities.extend(["媒体", "对象存储", "转码", "CDN"])
        if any(keyword in text for keyword in self.COMMERCE_KEYWORDS):
            capabilities.extend(["订单", "支付", "库存", "对账"])
        if any(keyword in text for keyword in self.IOT_KEYWORDS):
            capabilities.extend(["设备", "采集", "告警", "控制"])
        if any(keyword in text for keyword in self.AI_KEYWORDS) or features.quality_attributes.get("ai_reasoning", 0) >= 0.6:
            capabilities.extend(["AI", "特征", "模型"])

        if features.quality_attributes.get("concurrency", 0) >= 0.65:
            capabilities.extend(["负载均衡", "缓存", "消息队列"])
        if features.quality_attributes.get("realtime", 0) >= 0.65 or features.data_flow == "event_stream":
            capabilities.extend(["事件总线", "通知"])
        if features.quality_attributes.get("data_intensity", 0) >= 0.6 or features.data_flow == "pipeline":
            capabilities.extend(["数据管道", "分析"])
        if not capabilities:
            capabilities.extend(["用户", "业务", "数据库"])

        return list(dict.fromkeys(capabilities))

    def _build_graph(
        self,
        capabilities: list[str],
        features: ExtractedFeatures,
        winner: CandidateEvaluation,
        graph_knowledge: dict,
        composition_recommendation: dict,
    ) -> tuple[list[TopologyNode], list[TopologyEdge], list[str]]:
        nodes: dict[str, TopologyNode] = {}
        edges: list[TopologyEdge] = []
        notes: list[str] = []
        graph_primary = self._has_graph_knowledge(graph_knowledge)

        def add(node_id: str, name: str, layer: str) -> None:
            canonical_id = self._canonical_node_id(node_id, name)
            if self._is_singleton(name) and canonical_id in nodes:
                notes.append(f"拓扑规则去重：{name} 作为全局单例合并展示")
                return
            nodes[canonical_id] = TopologyNode(canonical_id, name, layer)

        def link(source: str, target: str, label: str = "", kind: str = "sync") -> None:
            canonical_source = self._canonical_node_id(source)
            canonical_target = self._canonical_node_id(target)
            if canonical_source in nodes and canonical_target in nodes:
                edges.append(TopologyEdge(canonical_source, canonical_target, label, kind))

        self._ensure_base_infrastructure(features, add, notes, graph_primary)
        if graph_primary:
            notes.append("拓扑生成策略：Neo4j 图谱作为主知识源，本地规则仅执行校验、补齐和去重")
            self._apply_graph_knowledge(graph_knowledge, nodes, edges, add, link, notes)
            self._ensure_quality_infrastructure(features, add, notes)
        else:
            notes.append("拓扑生成策略：Neo4j 未命中，启用本地规则兜底生成基础拓扑")
            self._add_local_capability_nodes(capabilities, add)

        self._connect_common(nodes, edges, link)
        if graph_primary:
            self._connect_graph_services(nodes, edges, link, notes)
        else:
            self._validate_social(capabilities, nodes, add, link, notes)
            self._validate_education(capabilities, nodes, add, link, notes)
        nodes, edges = self._dedupe_graph(nodes, edges, notes)
        self._apply_composition_responsibilities(nodes, edges, winner, composition_recommendation, notes)

        return list(nodes.values()), edges, notes

    def _apply_composition_responsibilities(
        self,
        nodes: dict[str, TopologyNode],
        edges: list[TopologyEdge],
        winner: CandidateEvaluation,
        composition: dict,
        notes: list[str],
    ) -> None:
        if not composition.get("composition_needed"):
            return

        style_specs = [
            {
                "style_id": winner.style_id,
                "style": composition.get("primary_style") or winner.name,
                "role": self._primary_style_role(winner.style_id),
                "apply_to": self._primary_apply_targets(winner.style_id, nodes),
                "node_id": "style_primary",
            }
        ]
        for index, item in enumerate(composition.get("supporting_styles", []), start=1):
            style_specs.append(
                {
                    "style_id": item.get("style_id", f"support_{index}"),
                    "style": item.get("style", "辅助架构模式"),
                    "role": item.get("role", "局部能力增强"),
                    "apply_to": item.get("apply_to", []),
                    "node_id": f"style_support_{index}",
                }
            )

        added = 0
        for spec in style_specs:
            targets = self._resolve_responsibility_targets(spec["style_id"], spec["apply_to"], nodes)
            if not targets:
                continue
            node_id = spec["node_id"]
            label = f"{spec['style']}<br/>{spec['role']}"
            nodes[node_id] = TopologyNode(node_id, label, "架构模式职责")
            for target in targets[:6]:
                edges.append(TopologyEdge(node_id, target, "负责", "responsibility"))
            added += 1

        if added:
            notes.append("拓扑职责映射：已把组合推荐中的架构模式与其负责的组件显性关联")

    def _resolve_responsibility_targets(
        self,
        style_id: str,
        apply_to: list[str],
        nodes: dict[str, TopologyNode],
    ) -> list[str]:
        resolved: list[str] = []

        def add_target(node_id: str) -> None:
            if node_id in nodes and node_id not in resolved:
                resolved.append(node_id)

        for item in apply_to:
            exact_id = self._component_id(item)
            add_target(exact_id)
            for node_id, node in nodes.items():
                if node.layer == "架构模式职责":
                    continue
                if item in node.name or node.name in item:
                    add_target(node_id)

        if style_id == "event_driven":
            for node_id in ["event_bus", "message_service", "message", "notify", "live", "interaction", "transcode"]:
                add_target(node_id)
        elif style_id == "microservices":
            for node_id, node in nodes.items():
                if node.layer == "业务服务层":
                    add_target(node_id)
        elif style_id == "cqrs":
            for node_id in ["message_db", "status_cache", "feed_cache", "search", "cache", "feature_store"]:
                add_target(node_id)
        elif style_id == "pipe_filter":
            for node_id in ["transcode", "object_store", "media", "replay"]:
                add_target(node_id)
        elif style_id == "serverless":
            for node_id in ["notify", "transcode", "ai"]:
                add_target(node_id)

        return resolved

    @staticmethod
    def _primary_style_role(style_id: str) -> str:
        roles = {
            "event_driven": "核心：异步解耦与事件分发",
            "microservices": "核心：服务边界与独立部署",
            "layered": "核心：分层治理与职责隔离",
            "cqrs": "核心：读写分离与查询优化",
            "pipe_filter": "核心：流水线处理",
        }
        return roles.get(style_id, "核心：主导整体结构")

    def _primary_apply_targets(self, style_id: str, nodes: dict[str, TopologyNode]) -> list[str]:
        if style_id == "event_driven":
            return ["事件总线", "消息服务", "通知服务", "转码服务"]
        if style_id == "microservices":
            return [node.name for node in nodes.values() if node.layer == "业务服务层"][:8]
        if style_id == "cqrs":
            return ["消息库", "状态缓存", "搜索索引", "缓存集群"]
        if style_id == "pipe_filter":
            return ["转码服务", "对象存储", "数据管道"]
        return [node.name for node in nodes.values() if node.layer in {"业务服务层", "异步事件层"}][:6]

    def _add_local_capability_nodes(self, capabilities, add) -> None:
        if "CDN" in capabilities:
            add("cdn", "CDN", "接入层")
        if "负载均衡" in capabilities:
            add("lb", "负载均衡", "接入层")
        if "用户" in capabilities:
            add("user", "用户服务", "业务服务层")
            add("user_db", "用户库", "数据层")
        if "课程" in capabilities:
            add("course", "课程服务", "业务服务层")
            add("course_db", "课程库", "数据层")
        if "直播" in capabilities:
            add("live", "直播服务", "业务服务层")
            add("live_gateway", "直播网关", "接入层")
        if "录播" in capabilities:
            add("replay", "回放服务", "业务服务层")
            add("replay_db", "回放库", "数据层")
        if "作业" in capabilities:
            add("homework", "作业服务", "业务服务层")
            add("homework_db", "作业库", "数据层")
        if "考试" in capabilities:
            add("exam", "考试服务", "业务服务层")
            add("exam_db", "考试库", "数据层")
        if "关系" in capabilities:
            add("relation", "关系服务", "业务服务层")
            add("graph_db", "关系图谱", "数据层")
        if "内容" in capabilities:
            add("content", "内容服务", "业务服务层")
            add("content_db", "内容库", "数据层")
            add("search", "搜索索引", "数据层")
        if "互动" in capabilities:
            add("interaction", "互动服务", "业务服务层")
            add("interaction_db", "互动库", "数据层")
        if "评论" in capabilities:
            add("comment", "评论服务", "业务服务层")
        if "私信" in capabilities:
            add("message", "私信服务", "业务服务层")
            add("message_db", "消息库", "数据层")
        if "Feed" in capabilities:
            add("feed", "Feed服务", "业务服务层")
            add("feed_cache", "Feed缓存", "数据层")
        if "推荐" in capabilities:
            add("recommend", "推荐服务", "业务服务层")
            add("feature_store", "特征库", "数据层")
        if "审核" in capabilities:
            add("moderation", "审核服务", "治理层")
        if "通知" in capabilities:
            add("notify", "通知服务", "业务服务层")
        if "缓存" in capabilities:
            add("cache", "缓存集群", "数据层")
        if "消息队列" in capabilities or "事件总线" in capabilities:
            add("event_bus", "事件总线", "异步事件层")
        if "媒体" in capabilities:
            add("media", "媒体服务", "业务服务层")
        if "转码" in capabilities:
            add("transcode", "转码服务", "异步事件层")
        if "对象存储" in capabilities:
            add("object_store", "对象存储", "数据层")
        if "AI" in capabilities:
            add("ai", "AI服务", "业务服务层")

    def _apply_graph_knowledge(self, graph_knowledge, nodes, edges, add, link, notes) -> None:
        components = graph_knowledge.get("components", [])
        stores = graph_knowledge.get("stores", [])
        graph_edges = graph_knowledge.get("edges", [])
        if not components and not stores:
            return

        notes.append("拓扑图谱增强：已从 Neo4j 检索领域能力、组件和依赖关系")
        for component in components:
            node_id = self._component_id(component)
            add(node_id, component, self._component_layer(component))
        for store in stores:
            node_id = self._component_id(store)
            add(node_id, store, "数据层")
        for edge in graph_edges:
            source = self._component_id(edge["source"])
            target = self._component_id(edge["target"])
            label = edge.get("label", "依赖")
            kind = edge.get("kind", "sync")
            link(source, target, label, kind)

    def _ensure_base_infrastructure(self, features: ExtractedFeatures, add, notes: list[str], graph_primary: bool) -> None:
        add("client", "客户端", "接入层")
        add("gateway", "API网关", "接入层")
        if graph_primary:
            notes.append("拓扑校验补齐：接入入口统一为客户端和 API 网关")

        if features.quality_attributes.get("concurrency", 0) >= 0.65:
            add("lb", "负载均衡", "接入层")
            if graph_primary:
                notes.append("拓扑校验补齐：高并发需求需要负载均衡")

        if features.data_flow == "event_stream" or features.quality_attributes.get("realtime", 0) >= 0.65:
            add("event_bus", "事件总线", "异步事件层")
            if graph_primary:
                notes.append("拓扑校验补齐：事件流或实时需求需要事件总线")

    def _ensure_quality_infrastructure(self, features: ExtractedFeatures, add, notes: list[str]) -> None:
        qualities = features.quality_attributes
        if qualities.get("concurrency", 0) >= 0.65:
            add("cache", "缓存集群", "数据层")
            notes.append("拓扑校验补齐：高并发场景补充缓存集群")
        if qualities.get("reliability", 0) >= 0.65:
            add("monitoring", "监控服务", "治理层")
            add("audit", "审计服务", "治理层")
            notes.append("拓扑校验补齐：可靠性需求补充监控与审计")
        if qualities.get("scalability", 0) >= 0.65:
            add("service_registry", "服务注册", "治理层")
            notes.append("拓扑校验补齐：扩展性需求补充服务注册")

    def _connect_graph_services(
        self,
        nodes: dict[str, TopologyNode],
        edges: list[TopologyEdge],
        link,
        notes: list[str],
    ) -> None:
        service_nodes = [
            node_id for node_id, node in nodes.items()
            if node.layer == "业务服务层" and node_id not in {"gateway"}
        ]
        for service in service_nodes:
            if not self._has_edge(edges, "gateway", service):
                link("gateway", service, "API")

        event_sources = [
            node_id for node_id, node in nodes.items()
            if node.layer == "业务服务层" and node_id not in {"notify"}
        ]
        if "event_bus" in nodes:
            for source in event_sources:
                if source in {"gateway"}:
                    continue
                if not self._has_edge(edges, source, "event_bus") and self._should_emit_event(source):
                    link(source, "event_bus", "事件", "event")
            for target in ["notify", "monitoring", "audit"]:
                if target in nodes and not self._has_edge(edges, "event_bus", target):
                    link("event_bus", target, "订阅", "event")

        if "cache" in nodes:
            for service in service_nodes[:4]:
                if not self._has_edge(edges, "cache", service):
                    link("cache", service, "热点")

        notes.append("拓扑校验完成：已补齐服务入口、事件订阅、缓存热点和边合法性")

    def _connect_common(self, nodes: dict[str, TopologyNode], edges: list[TopologyEdge], link) -> None:
        if "cdn" in nodes:
            link("client", "cdn", "访问")
            if "lb" in nodes:
                link("cdn", "lb", "转发")
            else:
                link("cdn", "gateway", "转发")
        elif "lb" in nodes:
            link("client", "lb", "访问")
        else:
            link("client", "gateway", "访问")

        if "lb" in nodes:
            link("lb", "gateway", "路由")

        for service in [
            "user", "relation", "content", "interaction", "comment", "message", "feed",
            "recommend", "media", "ai", "course", "live", "replay", "homework", "exam",
        ]:
            link("gateway", service, "API")
        link("live_gateway", "live", "推流")

        pairs = [
            ("user", "user_db", "读写"),
            ("course", "course_db", "课程"),
            ("relation", "graph_db", "关系"),
            ("content", "content_db", "内容"),
            ("content", "search", "索引"),
            ("interaction", "interaction_db", "互动"),
            ("comment", "content_db", "评论"),
            ("message", "message_db", "消息"),
            ("feed", "feed_cache", "动态"),
            ("recommend", "feature_store", "特征"),
            ("media", "object_store", "文件"),
            ("replay", "replay_db", "回放"),
            ("homework", "homework_db", "作业"),
            ("exam", "exam_db", "考试"),
        ]
        for source, target, label in pairs:
            link(source, target, label)

        for source in ["content", "interaction", "comment", "message", "relation", "media", "live", "course", "homework", "exam"]:
            link(source, "event_bus", "事件", "event")

        for target in ["feed", "recommend", "notify", "moderation", "transcode", "replay"]:
            link("event_bus", target, "订阅", "event")

        link("recommend", "feed", "排序")
        link("relation", "feed", "关注")
        link("cache", "feed", "加速")
        link("cache", "content", "热点")
        link("transcode", "object_store", "存储")
        link("live", "media", "音视频")
        link("media", "replay", "回放")
        link("cache", "live", "热点")
        link("cdn", "live_gateway", "分发")

    def _validate_social(self, capabilities, nodes, add, link, notes) -> None:
        if "社交" not in capabilities:
            return
        required = {
            "feed": ("Feed服务", "业务服务层"),
            "relation": ("关系服务", "业务服务层"),
            "moderation": ("审核服务", "治理层"),
            "feature_store": ("特征库", "数据层"),
            "event_bus": ("事件总线", "异步事件层"),
        }
        for node_id, (name, layer) in required.items():
            if node_id not in nodes:
                add(node_id, name, layer)
                notes.append(f"拓扑规则补全：社交媒体场景需要{name}")
        link("content", "event_bus", "发布", "event")
        link("interaction", "event_bus", "行为", "event")
        link("event_bus", "feed", "更新", "event")
        link("event_bus", "recommend", "训练", "event")
        link("moderation", "content", "审核")

    def _validate_education(self, capabilities, nodes, add, link, notes) -> None:
        if "教育" not in capabilities:
            return
        required = {
            "course": ("课程服务", "业务服务层"),
            "live": ("直播服务", "业务服务层"),
            "live_gateway": ("直播网关", "接入层"),
            "replay": ("回放服务", "业务服务层"),
            "interaction": ("互动服务", "业务服务层"),
            "media": ("媒体服务", "业务服务层"),
            "object_store": ("对象存储", "数据层"),
            "event_bus": ("事件总线", "异步事件层"),
            "cache": ("缓存集群", "数据层"),
            "cdn": ("CDN", "接入层"),
        }
        for node_id, (name, layer) in required.items():
            if node_id not in nodes:
                add(node_id, name, layer)
                notes.append(f"拓扑规则补全：在线教育场景需要{name}")

        if "录播" in capabilities and "transcode" not in nodes:
            add("transcode", "转码服务", "异步事件层")
            notes.append("拓扑规则补全：录播回放需要转码服务")
        if "课后互动" in capabilities and "notify" not in nodes:
            add("notify", "通知服务", "业务服务层")

        link("client", "cdn", "访问")
        link("cdn", "live_gateway", "直播分发")
        link("live_gateway", "live", "推流")
        link("gateway", "course", "课程")
        link("gateway", "interaction", "互动")
        link("live", "event_bus", "课堂事件", "event")
        link("interaction", "event_bus", "互动事件", "event")
        link("event_bus", "replay", "生成回放", "event")
        link("event_bus", "notify", "课后通知", "event")
        link("live", "media", "音视频")
        link("media", "object_store", "存储")
        link("transcode", "object_store", "录播")
        link("replay", "object_store", "读取")
        link("cache", "live", "热点加速")

    def _render_mermaid(self, nodes: list[TopologyNode], edges: list[TopologyEdge]) -> str:
        layer_names = ["架构模式职责", "接入层", "业务服务层", "异步事件层", "治理层", "数据层"]
        lines = ["flowchart TD"]
        node_map = {node.id: node for node in nodes}

        for layer in layer_names:
            layer_nodes = [node for node in nodes if node.layer == layer]
            if not layer_nodes:
                continue
            lines.append(f"  subgraph {self._safe_id(layer)}[{layer}]")
            for node in layer_nodes:
                lines.append(f"    {node.id}{self._node_label(node.name)}")
            lines.append("  end")

        seen_edges = set()
        for edge in edges:
            if edge.source not in node_map or edge.target not in node_map:
                continue
            key = (edge.source, edge.target, edge.label)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            arrow = "-.->" if edge.kind in {"event", "responsibility"} else "-->"
            if edge.label:
                lines.append(f"  {edge.source} {arrow}|{self._escape_label(edge.label)}| {edge.target}")
            else:
                lines.append(f"  {edge.source} {arrow} {edge.target}")

        return "\n".join(lines)

    def _dedupe_graph(
        self,
        nodes: dict[str, TopologyNode],
        edges: list[TopologyEdge],
        notes: list[str],
    ) -> tuple[dict[str, TopologyNode], list[TopologyEdge]]:
        canonical_by_name: dict[str, str] = {}
        aliases: dict[str, str] = {}
        deduped_nodes: dict[str, TopologyNode] = {}

        for node_id, node in nodes.items():
            canonical_id = self._canonical_node_id(node_id, node.name)
            if self._is_singleton(node.name) and node.name in canonical_by_name:
                aliases[node_id] = canonical_by_name[node.name]
                notes.append(f"拓扑规则去重：{node.name} 作为全局单例合并展示")
                continue
            if canonical_id in deduped_nodes:
                aliases[node_id] = canonical_id
                if deduped_nodes[canonical_id].name == node.name:
                    notes.append(f"拓扑规则去重：合并重复节点 {node.name}")
                continue
            canonical_by_name[node.name] = canonical_id
            aliases[node_id] = canonical_id
            deduped_nodes[canonical_id] = TopologyNode(canonical_id, node.name, node.layer)

        deduped_edges: list[TopologyEdge] = []
        seen_edges: set[tuple[str, str, str, str]] = set()
        for edge in edges:
            source = aliases.get(edge.source, self._canonical_node_id(edge.source))
            target = aliases.get(edge.target, self._canonical_node_id(edge.target))
            if source == target or source not in deduped_nodes or target not in deduped_nodes:
                continue
            key = (source, target, edge.label, edge.kind)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            deduped_edges.append(TopologyEdge(source, target, edge.label, edge.kind))

        return deduped_nodes, deduped_edges

    @staticmethod
    def _has_graph_knowledge(graph_knowledge: dict) -> bool:
        return bool(
            graph_knowledge.get("components")
            or graph_knowledge.get("stores")
            or graph_knowledge.get("edges")
        )

    @staticmethod
    def _has_edge(edges: list[TopologyEdge], source: str, target: str) -> bool:
        return any(edge.source == source and edge.target == target for edge in edges)

    @staticmethod
    def _should_emit_event(node_id: str) -> bool:
        return node_id not in {"user", "course"}

    @classmethod
    def _canonical_node_id(cls, node_id: str, name: str | None = None) -> str:
        if name and name in cls.CANONICAL_COMPONENT_IDS:
            return cls.CANONICAL_COMPONENT_IDS[name]
        return node_id

    @staticmethod
    def _safe_id(value: str) -> str:
        return "layer_" + str(abs(hash(value)))

    @staticmethod
    def _escape_label(value: str) -> str:
        return value.replace('"', "'")

    @classmethod
    def _node_label(cls, value: str) -> str:
        escaped = cls._escape_label(value)
        if any(token in escaped for token in ["<", ">", "|", "\n"]):
            return f'["{escaped}"]'
        return f"[{escaped}]"

    @classmethod
    def _component_id(cls, name: str) -> str:
        if name in cls.CANONICAL_COMPONENT_IDS:
            return cls.CANONICAL_COMPONENT_IDS[name]
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
        return f"kg_{digest}"

    @classmethod
    def _is_singleton(cls, name: str) -> bool:
        return name in cls.SINGLETON_COMPONENTS or name in cls.CANONICAL_COMPONENT_IDS

    @staticmethod
    def _component_layer(name: str) -> str:
        if name in ["CDN", "负载均衡", "API网关", "直播网关", "设备网关", "视频网关"]:
            return "接入层"
        if name in ["消息队列", "事件总线", "任务队列", "数据管道", "实时计算", "离线分析", "转码服务"]:
            return "异步事件层"
        if name in ["审核服务", "审计服务", "风控服务", "防作弊服务", "监控服务"]:
            return "治理层"
        return "业务服务层"
