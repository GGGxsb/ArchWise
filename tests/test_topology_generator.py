from app.models.schemas import CandidateEvaluation, ExtractedFeatures
from app.services.topology_generator import TopologyGenerator


def features_for(
    domain: str,
    keywords: list[str],
    business_capabilities: list[str],
    quality_attributes: dict[str, float],
    data_flow: str,
    topology_expectations: dict | None = None,
) -> ExtractedFeatures:
    return ExtractedFeatures(
        domain=domain,
        keywords=keywords,
        business_capabilities=business_capabilities,
        architecture_drivers=[],
        topology_expectations=topology_expectations or {
            "must_have_components": [],
            "must_have_relations": [],
            "quality_infrastructure": [],
        },
        quality_attributes={
            "concurrency": quality_attributes.get("concurrency", 0),
            "realtime": quality_attributes.get("realtime", 0),
            "reliability": quality_attributes.get("reliability", 0),
            "scalability": quality_attributes.get("scalability", 0),
            "data_intensity": quality_attributes.get("data_intensity", 0),
            "ai_reasoning": quality_attributes.get("ai_reasoning", 0),
        },
        constraints={},
        data_flow=data_flow,
        ambiguity_notes=[],
    )


def candidate(style_id: str = "microservices", name: str = "微服务架构") -> CandidateEvaluation:
    return CandidateEvaluation(
        style_id=style_id,
        name=name,
        score=95,
        matched_reasons=[],
        risks=[],
        quality_scores={"scalability": 0.9, "performance": 0.8, "reliability": 0.8, "realtime": 0.6},
    )


def test_social_media_topology_contains_domain_capabilities():
    requirement = "开发社交媒体平台，用户发帖、点赞、评论、私信，高并发访问、内容推荐"
    features = features_for(
        "社交媒体",
        ["发帖", "点赞", "评论", "私信", "内容推荐", "高并发"],
        ["内容发布", "互动行为", "评论管理", "私信通信", "关注关系", "信息流", "内容推荐", "内容审核"],
        {"concurrency": 0.9, "realtime": 0.65, "scalability": 0.8, "reliability": 0.7},
        "event_stream",
    )

    mermaid, notes = TopologyGenerator().generate(requirement, features, candidate())

    assert "Feed服务" in mermaid
    assert "关系服务" in mermaid
    assert "审核服务" in mermaid
    assert "特征库" in mermaid
    assert "事件总线" in mermaid
    assert "缓存集群" in mermaid
    assert "subgraph" in mermaid


def test_online_education_topology_contains_domain_capabilities():
    requirement = "开发在线教育平台，支持万人同时上课，直播流畅，录播回放，课后互动"
    features = features_for(
        "在线教育",
        ["在线教育", "直播", "录播", "回放", "课后互动"],
        ["课程管理", "直播教学", "录播回放", "课堂互动", "作业考试", "通知提醒", "媒体处理"],
        {"concurrency": 0.85, "realtime": 0.9, "scalability": 0.8, "reliability": 0.72, "data_intensity": 0.55},
        "event_stream",
    )

    mermaid, notes = TopologyGenerator().generate(requirement, features, candidate())

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
    features = features_for(
        "旅游预订",
        ["旅游", "预订", "促销", "订单", "退款"],
        ["商品管理", "订单管理", "支付结算", "库存管理", "退款售后", "促销活动"],
        {"concurrency": 0.75, "scalability": 0.8, "reliability": 0.72},
        "transactional",
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

    mermaid, notes = TopologyGenerator().generate(requirement, features, candidate(), graph_knowledge=graph_knowledge)

    assert "商品服务" in mermaid
    assert "订单服务" in mermaid
    assert "支付服务" in mermaid
    assert "库存服务" in mermaid
    assert "退款服务" in mermaid
    assert "订单库" in mermaid
    assert "拓扑图谱增强" in " ".join(notes)


def test_topology_deduplicates_singleton_infrastructure_from_graph_knowledge():
    requirement = "开发一个跨平台的即时通讯系统，要求支持万人同时在线，需要保证消息的实时性和可靠性，后期可能需要快速扩展视频通话功能"
    features = features_for(
        "即时通信",
        ["即时通讯", "万人在线", "实时", "视频通话"],
        ["用户体系", "消息通信", "在线状态", "视频通话", "通知提醒"],
        {"concurrency": 0.95, "realtime": 0.95, "reliability": 0.8, "scalability": 0.85},
        "event_stream",
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

    mermaid, notes = TopologyGenerator().generate(
        requirement,
        features,
        candidate("event_driven", "事件驱动架构"),
        graph_knowledge=graph_knowledge,
    )

    assert mermaid.count("[API网关]") == 1
    assert mermaid.count("[负载均衡]") == 1
    assert mermaid.count("[事件总线]") == 1
    assert mermaid.count("[用户服务]") == 1
    assert mermaid.count("[用户库]") == 1
    assert "kg_" not in mermaid


def test_graph_primary_topology_uses_local_rules_only_as_topology_validator():
    requirement = "开发一个跨平台的即时通讯系统，要求支持万人同时在线，需要保证消息的实时性和可靠性，后期可能需要快速扩展视频通话功能"
    features = features_for(
        "即时通信",
        ["即时通讯", "万人在线", "实时", "视频通话"],
        ["用户体系", "消息通信", "在线状态", "视频通话", "通知提醒"],
        {"concurrency": 0.95, "realtime": 0.95, "reliability": 0.8, "scalability": 0.85},
        "event_stream",
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

    mermaid, notes = TopologyGenerator().generate(
        requirement,
        features,
        candidate("event_driven", "事件驱动架构"),
        graph_knowledge=graph_knowledge,
    )

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


def test_topology_keeps_composition_styles_out_of_system_diagram():
    requirement = "开发一个跨平台的即时通讯系统，要求支持万人同时在线，需要保证消息的实时性和可靠性，后期可能需要快速扩展视频通话功能"
    features = features_for(
        "即时通信",
        ["即时通讯", "万人在线", "实时", "视频通话"],
        ["用户体系", "消息通信", "在线状态", "视频通话", "通知提醒"],
        {"concurrency": 0.95, "realtime": 0.95, "reliability": 0.8, "scalability": 0.85},
        "event_stream",
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
        candidate("event_driven", "事件驱动架构"),
        graph_knowledge=graph_knowledge,
        composition_recommendation=composition,
    )

    assert "架构模式职责" not in mermaid
    assert "微服务架构" not in mermaid
    assert "CQRS 架构" not in mermaid
    assert "style_primary" not in mermaid
    assert "style_support" not in mermaid
    assert "消息服务" in mermaid
    assert "事件总线" in mermaid
    assert "拓扑生成约束" in " ".join(notes)


def test_topology_does_not_add_composition_layer_when_not_needed():
    requirement = "开发企业内部 OA 系统，50 人使用，功能稳定，无需高并发，部署在公司服务器"
    features = features_for(
        "企业管理",
        ["OA", "稳定", "低并发"],
        [],
        {"concurrency": 0.1, "realtime": 0.1, "reliability": 0.65, "scalability": 0.2},
        "request_response",
    )
    composition = {
        "composition_needed": False,
        "primary_style": "分层架构",
        "supporting_styles": [],
    }

    mermaid, notes = TopologyGenerator().generate(
        requirement,
        features,
        candidate("layered", "分层架构"),
        composition_recommendation=composition,
    )

    assert "架构模式职责" not in mermaid
    assert "style_primary" not in mermaid


def test_ecommerce_topology_repairs_missing_domain_components_without_graph_knowledge():
    requirement = (
        "我们要构建一个面向全国用户的电商平台，支持商品浏览、购物车、下单支付、订单管理与物流跟踪。"
        "大促期间有秒杀活动，瞬时并发可达每秒数万笔订单，要求系统具备高并发、弹性伸缩与高可用能力，"
        "订单与库存数据需保证最终一致性。团队希望按业务域拆分为多个微服务，支持独立部署与灰度发布。"
    )
    features = features_for(
        "电商交易",
        ["电商", "商品浏览", "购物车", "订单", "支付", "库存", "秒杀", "物流", "灰度发布"],
        ["商品浏览", "购物车", "订单管理", "支付结算", "库存管理", "库存一致性", "秒杀活动", "物流跟踪", "灰度发布"],
        {"concurrency": 0.95, "scalability": 0.9, "reliability": 0.85, "data_intensity": 0.65},
        "transactional",
    )

    mermaid, notes = TopologyGenerator().generate(requirement, features, candidate())

    assert "商品服务" in mermaid
    assert "购物车服务" in mermaid
    assert "订单服务" in mermaid
    assert "支付服务" in mermaid
    assert "库存服务" in mermaid
    assert "秒杀服务" in mermaid
    assert "物流服务" in mermaid
    assert "事件总线" in mermaid
    assert "缓存集群" in mermaid
    assert "服务注册" in mermaid
    assert "监控服务" in mermaid
    assert "订单服务" in mermaid and "支付服务" in mermaid
    assert "拓扑自检：电商核心能力覆盖率" in " ".join(notes)


def test_ecommerce_coverage_uses_business_capabilities_not_generic_components():
    requirement = (
        "我们要构建一个面向全国用户的电商平台，支持商品浏览、购物车、下单支付、订单管理与物流跟踪。"
        "大促期间有秒杀活动，瞬时并发可达每秒数万笔订单，要求系统具备高并发、弹性伸缩与高可用能力，"
        "订单与库存数据需保证最终一致性。团队希望按业务域拆分为多个微服务，支持独立部署与灰度发布。"
    )
    features = features_for(
        "电商交易",
        ["电商", "商品浏览", "购物车", "订单", "支付", "库存", "秒杀", "物流", "灰度发布"],
        ["商品浏览", "购物车", "订单管理", "支付结算", "库存管理", "库存一致性", "秒杀活动", "物流跟踪", "灰度发布"],
        {"concurrency": 0.95, "scalability": 0.9, "reliability": 0.85, "data_intensity": 0.65},
        "transactional",
    )
    coverage = TopologyGenerator().assess_coverage(requirement, features, {}, extra_capabilities=["消息处理"])

    assert "商品浏览" in coverage["expected_capabilities"]
    assert "购物车" in coverage["expected_capabilities"]
    assert "订单管理" in coverage["expected_capabilities"]
    assert "支付结算" in coverage["expected_capabilities"]
    assert "库存管理" in coverage["expected_capabilities"]
    assert "秒杀活动" in coverage["expected_capabilities"]
    assert "物流跟踪" in coverage["expected_capabilities"]
    assert "灰度发布" in coverage["expected_capabilities"]
    assert "消息处理" not in coverage["expected_capabilities"]
    assert "消息通信" not in coverage["expected_capabilities"]
    assert "交易处理" not in coverage["expected_capabilities"]
    assert "轨迹采集" not in coverage["expected_capabilities"]
    assert "内容发布" not in coverage["expected_capabilities"]
    assert "dimensions" in coverage


def test_ecommerce_graph_topology_repairs_partial_neo4j_result():
    requirement = "电商平台支持商品浏览、购物车、下单支付、库存最终一致性、物流跟踪和秒杀活动"
    features = features_for(
        "电商交易",
        ["电商", "商品浏览", "购物车", "订单", "支付", "库存", "秒杀", "物流"],
        ["商品浏览", "购物车", "订单管理", "支付结算", "库存管理", "库存一致性", "秒杀活动", "物流跟踪"],
        {"concurrency": 0.85, "scalability": 0.8, "reliability": 0.8},
        "transactional",
    )
    graph_knowledge = {
        "components": ["商品服务", "订单服务", "支付服务"],
        "stores": ["商品库", "订单库", "支付库"],
        "edges": [
            {"source": "订单服务", "target": "支付服务", "label": "支付", "kind": "sync"},
            {"source": "商品服务", "target": "商品库", "label": "读写", "kind": "sync"},
        ],
        "scenarios": ["电商交易"],
        "capabilities": ["商品浏览", "购物车", "订单管理", "支付结算", "库存管理", "秒杀活动", "物流跟踪"],
    }

    mermaid, notes = TopologyGenerator().generate(requirement, features, candidate(), graph_knowledge=graph_knowledge)

    assert "购物车服务" in mermaid
    assert "库存服务" in mermaid
    assert "秒杀服务" in mermaid
    assert "物流服务" in mermaid
    assert "购物车缓存" in mermaid
    assert "库存库" in mermaid
    assert "物流库" in mermaid
    assert "拓扑生成策略：Neo4j 图谱作为主知识源" in " ".join(notes)
    assert "拓扑自检：电商核心能力覆盖率" in " ".join(notes)
