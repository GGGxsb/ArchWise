from app.agents.requirement_parser import RequirementParserAgent
from app.models.schemas import CandidateEvaluation
from app.services.topology_generator import TopologyGenerator


def test_social_media_topology_contains_domain_capabilities():
    requirement = "开发社交媒体平台，用户发帖、点赞、评论、私信，高并发访问、内容推荐"
    features = RequirementParserAgent().parse(requirement)
    winner = CandidateEvaluation(
        style_id="microservices",
        name="微服务架构",
        score=95,
        matched_reasons=[],
        risks=[],
        quality_scores={"scalability": 0.9, "performance": 0.7, "reliability": 0.7, "realtime": 0.6},
    )

    mermaid, notes = TopologyGenerator().generate(requirement, features, winner)

    assert "Feed服务" in mermaid
    assert "关系服务" in mermaid
    assert "审核服务" in mermaid
    assert "特征库" in mermaid
    assert "事件总线" in mermaid
    assert "缓存集群" in mermaid
    assert "subgraph" in mermaid


def test_online_education_topology_contains_domain_capabilities():
    requirement = "开发在线教育平台，支持万人同时上课，直播流畅，录播回放，课后互动"
    features = RequirementParserAgent().parse(requirement)
    winner = CandidateEvaluation(
        style_id="microservices",
        name="微服务架构",
        score=96,
        matched_reasons=[],
        risks=[],
        quality_scores={"scalability": 0.9, "performance": 0.72, "reliability": 0.74, "realtime": 0.58},
    )

    mermaid, notes = TopologyGenerator().generate(requirement, features, winner)

    assert "课程服务" in mermaid
    assert "直播服务" in mermaid
    assert "直播网关" in mermaid
    assert "回放服务" in mermaid
    assert "互动服务" in mermaid
    assert "媒体服务" in mermaid
    assert "转码服务" in mermaid
    assert "对象存储" in mermaid
    assert "CDN" in mermaid
    assert "事件总线" in mermaid


def test_topology_uses_graph_knowledge_components():
    requirement = "开发旅游预订平台，酒店、机票、门票预订，高并发促销、订单管理、退款处理"
    features = RequirementParserAgent().parse(requirement)
    winner = CandidateEvaluation(
        style_id="microservices",
        name="微服务架构",
        score=94,
        matched_reasons=[],
        risks=[],
        quality_scores={"scalability": 0.9, "performance": 0.72, "reliability": 0.74, "realtime": 0.4},
    )
    graph_knowledge = {
        "components": ["商品服务", "订单服务", "支付服务", "库存服务", "退款服务", "促销服务"],
        "stores": ["商品库", "订单库", "支付库", "库存库"],
        "edges": [
            {"source": "订单服务", "target": "支付服务", "label": "支付", "kind": "sync"},
            {"source": "订单服务", "target": "库存服务", "label": "锁定库存", "kind": "sync"},
        ],
        "scenarios": ["旅游预订"],
        "capabilities": ["订单管理", "支付结算", "库存管理"],
    }

    mermaid, notes = TopologyGenerator().generate(requirement, features, winner, graph_knowledge=graph_knowledge)

    assert "商品服务" in mermaid
    assert "订单服务" in mermaid
    assert "支付服务" in mermaid
    assert "库存服务" in mermaid
    assert "退款服务" in mermaid
    assert "订单库" in mermaid
    assert "拓扑图谱增强" in " ".join(notes)


def test_topology_deduplicates_singleton_infrastructure_from_graph_knowledge():
    requirement = "开发一个跨平台的即时通讯系统，要求支持万人同时在线，需要保证消息的实时性和可靠性，后期可能需要快速扩展视频通话功能"
    features = RequirementParserAgent().parse(requirement)
    winner = CandidateEvaluation(
        style_id="event_driven",
        name="事件驱动架构",
        score=96,
        matched_reasons=[],
        risks=[],
        quality_scores={"scalability": 0.88, "performance": 0.82, "reliability": 0.76, "realtime": 0.86},
    )
    graph_knowledge = {
        "components": ["API网关", "负载均衡", "事件总线", "通知服务", "用户服务"],
        "stores": ["用户库", "对象存储"],
        "edges": [
            {"source": "负载均衡", "target": "API网关", "label": "路由", "kind": "sync"},
            {"source": "API网关", "target": "用户服务", "label": "API", "kind": "sync"},
            {"source": "事件总线", "target": "通知服务", "label": "订阅", "kind": "event"},
            {"source": "用户服务", "target": "用户库", "label": "读写", "kind": "sync"},
        ],
        "scenarios": ["即时通信"],
        "capabilities": ["用户体系", "通知提醒"],
    }

    mermaid, notes = TopologyGenerator().generate(requirement, features, winner, graph_knowledge=graph_knowledge)

    assert mermaid.count("[API网关]") == 1
    assert mermaid.count("[负载均衡]") == 1
    assert mermaid.count("[事件总线]") == 1
    assert mermaid.count("[用户服务]") == 1
    assert mermaid.count("[用户库]") == 1
    assert "kg_" not in mermaid


def test_graph_primary_topology_uses_rules_only_as_validator_and_fallback():
    requirement = "开发一个跨平台的即时通讯系统，要求支持万人同时在线，需要保证消息的实时性和可靠性，后期可能需要快速扩展视频通话功能"
    features = RequirementParserAgent().parse(requirement)
    winner = CandidateEvaluation(
        style_id="event_driven",
        name="事件驱动架构",
        score=96,
        matched_reasons=[],
        risks=[],
        quality_scores={"scalability": 0.88, "performance": 0.82, "reliability": 0.76, "realtime": 0.86},
    )
    graph_knowledge = {
        "components": ["用户服务", "消息服务", "状态服务", "信令服务", "媒体服务", "通知服务"],
        "stores": ["用户库", "消息库", "状态缓存", "对象存储"],
        "edges": [
            {"source": "消息服务", "target": "消息库", "label": "存储", "kind": "sync"},
            {"source": "消息服务", "target": "事件总线", "label": "消息事件", "kind": "event"},
            {"source": "状态服务", "target": "状态缓存", "label": "在线状态", "kind": "sync"},
            {"source": "信令服务", "target": "媒体服务", "label": "通话信令", "kind": "sync"},
            {"source": "媒体服务", "target": "对象存储", "label": "存储", "kind": "sync"},
        ],
        "scenarios": ["即时通信"],
        "capabilities": ["用户体系", "消息通信", "在线状态", "视频通话", "通知提醒"],
    }

    mermaid, notes = TopologyGenerator().generate(requirement, features, winner, graph_knowledge=graph_knowledge)

    assert "消息服务" in mermaid
    assert "状态服务" in mermaid
    assert "信令服务" in mermaid
    assert "媒体服务" in mermaid
    assert "事件总线" in mermaid
    assert "API网关" in mermaid
    assert "拓扑生成策略：Neo4j 图谱作为主知识源" in " ".join(notes)
    assert "评论服务" not in mermaid
    assert "Feed服务" not in mermaid
    assert "课程服务" not in mermaid


def test_topology_maps_composition_styles_to_responsible_components():
    requirement = "开发一个跨平台的即时通讯系统，要求支持万人同时在线，需要保证消息的实时性和可靠性，后期可能需要快速扩展视频通话功能"
    features = RequirementParserAgent().parse(requirement)
    winner = CandidateEvaluation(
        style_id="event_driven",
        name="事件驱动架构",
        score=96,
        matched_reasons=[],
        risks=[],
        quality_scores={"scalability": 0.88, "performance": 0.82, "reliability": 0.76, "realtime": 0.86},
    )
    graph_knowledge = {
        "components": ["用户服务", "消息服务", "状态服务", "信令服务", "媒体服务", "通知服务"],
        "stores": ["用户库", "消息库", "状态缓存", "对象存储"],
        "edges": [
            {"source": "消息服务", "target": "消息库", "label": "存储", "kind": "sync"},
            {"source": "消息服务", "target": "事件总线", "label": "消息事件", "kind": "event"},
            {"source": "状态服务", "target": "状态缓存", "label": "在线状态", "kind": "sync"},
            {"source": "信令服务", "target": "媒体服务", "label": "通话信令", "kind": "sync"},
            {"source": "媒体服务", "target": "对象存储", "label": "存储", "kind": "sync"},
        ],
        "scenarios": ["即时通信"],
        "capabilities": ["用户体系", "消息通信", "在线状态", "视频通话", "通知提醒"],
    }
    composition = {
        "composition_needed": True,
        "primary_style": "事件驱动架构",
        "supporting_styles": [
            {
                "style_id": "microservices",
                "style": "微服务架构",
                "role": "服务拆分与独立扩展",
                "apply_to": ["用户服务", "消息服务", "媒体服务", "通知服务"],
            },
            {
                "style_id": "cqrs",
                "style": "CQRS 架构",
                "role": "高频查询与读写分离",
                "apply_to": ["消息库", "状态缓存"],
            },
        ],
    }

    mermaid, notes = TopologyGenerator().generate(
        requirement,
        features,
        winner,
        graph_knowledge=graph_knowledge,
        composition_recommendation=composition,
    )

    assert "架构模式职责" in mermaid
    assert "事件驱动架构" in mermaid
    assert "微服务架构" in mermaid
    assert "CQRS 架构" in mermaid
    assert "style_primary -.->|负责| event_bus" in mermaid
    assert "style_support_1 -.->|负责| user" in mermaid
    assert "style_support_1 -.->|负责| message_service" in mermaid
    assert "style_support_2 -.->|负责| message_db" in mermaid
    assert "拓扑职责映射" in " ".join(notes)


def test_topology_does_not_add_composition_layer_when_not_needed():
    requirement = "开发企业内部 OA 系统，50 人使用，功能稳定，无需高并发，部署在公司服务器"
    features = RequirementParserAgent().parse(requirement)
    winner = CandidateEvaluation(
        style_id="layered",
        name="分层架构",
        score=92,
        matched_reasons=[],
        risks=[],
        quality_scores={"scalability": 0.45, "performance": 0.55, "reliability": 0.7, "realtime": 0.2},
    )
    composition = {
        "composition_needed": False,
        "primary_style": "分层架构",
        "supporting_styles": [],
    }

    mermaid, notes = TopologyGenerator().generate(
        requirement,
        features,
        winner,
        composition_recommendation=composition,
    )

    assert "架构模式职责" not in mermaid
    assert "style_primary" not in mermaid
