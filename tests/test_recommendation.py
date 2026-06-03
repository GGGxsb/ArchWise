import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import ExtractedFeatures
from app.services.exceptions import RequirementParsingError
from app.services.recommendation_service import RecommendationService


client = TestClient(app)


def llm_features(
    domain: str = "即时通信",
    data_flow: str = "event_stream",
    keywords: list[str] | None = None,
    business_capabilities: list[str] | None = None,
    quality_attributes: dict[str, float] | None = None,
) -> ExtractedFeatures:
    quality_attributes = quality_attributes or {
        "concurrency": 0.95,
        "realtime": 0.9,
        "reliability": 0.82,
        "scalability": 0.85,
        "data_intensity": 0.45,
        "ai_reasoning": 0.0,
    }
    return ExtractedFeatures(
        domain=domain,
        keywords=keywords or ["即时通讯", "万人在线", "实时", "可靠", "扩展"],
        business_capabilities=business_capabilities or ["用户体系", "消息通信", "在线状态", "通知提醒", "视频通话"],
        architecture_drivers=["高并发", "实时性", "高可用", "弹性伸缩"],
        topology_expectations={
            "must_have_components": ["消息服务", "状态服务", "事件总线"],
            "must_have_relations": ["消息服务->事件总线"],
            "quality_infrastructure": ["负载均衡", "缓存集群", "监控服务"],
        },
        quality_attributes=quality_attributes,
        constraints={
            "scale_mentions": ["万人在线"],
            "deployment": ["跨平台"],
            "requires_high_availability": True,
            "requires_future_extension": True,
        },
        data_flow=data_flow,
        ambiguity_notes=[],
    )


def patch_llm(monkeypatch, features: ExtractedFeatures | None = None) -> None:
    async def fake_extract_features(self, requirement):
        return features or llm_features()

    async def fake_review_candidates(self, requirement, extracted_features, candidates):
        return ["DeepSeek 复核候选排序合理"]

    async def fake_generate_report(self, requirement, extracted_features, candidates):
        return "- **高并发** 场景需要异步削峰和服务拆分。"

    async def fake_stream_report(self, requirement, extracted_features, candidates):
        yield "- **高并发** 场景需要异步削峰和服务拆分。"

    async def fake_extract_capabilities(self, requirement, extracted_features):
        return []

    async def fake_propose_patch(self, requirement, extracted_features, coverage, graph_knowledge):
        return None

    monkeypatch.setattr("app.services.llm_client.LLMClient.extract_features", fake_extract_features)
    monkeypatch.setattr("app.services.llm_client.LLMClient.review_candidates", fake_review_candidates)
    monkeypatch.setattr("app.services.llm_client.LLMClient.generate_report", fake_generate_report)
    monkeypatch.setattr("app.services.llm_client.LLMClient.stream_report", fake_stream_report)
    monkeypatch.setattr("app.services.llm_client.LLMClient.extract_capabilities", fake_extract_capabilities)
    monkeypatch.setattr("app.services.llm_client.LLMClient.propose_topology_knowledge_patch", fake_propose_patch)


def test_recommend_im_returns_at_least_three_candidates(monkeypatch):
    patch_llm(monkeypatch)
    response = client.post(
        "/api/recommend",
        json={
            "requirement": "开发一个跨平台即时通讯系统，支持万人同时在线，消息实时可靠，后续扩展视频通话",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["candidates"]) == 3
    assert payload["final_recommendation"]["name"] in {"事件驱动架构", "微服务架构", "CQRS 架构"}
    assert payload["features"]["data_flow"] == "event_stream"
    assert "本地规则提取硬信号" not in " ".join(payload["trace"])


def test_recommend_returns_prompt_when_deepseek_parse_unavailable(monkeypatch):
    async def fake_extract_features(self, requirement):
        self.last_error = "DeepSeek API Key 未配置，无法进行需求解析。"
        return None

    monkeypatch.setattr("app.services.llm_client.LLMClient.extract_features", fake_extract_features)

    response = client.post(
        "/api/recommend",
        json={"requirement": "开发一个在线教育平台，支持直播和录播", "top_k": 3},
    )

    assert response.status_code == 503
    assert "需求解析失败" in response.json()["detail"]
    assert "DeepSeek API Key 未配置" in response.json()["detail"]


def test_styles_include_required_knowledge_base_size():
    response = client.get("/api/styles")
    assert response.status_code == 200
    assert len(response.json()) >= 10


def test_knowledge_graph_has_nodes_and_edges():
    response = client.get("/api/knowledge/graph")
    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes"]
    assert payload["edges"]




def test_service_generates_matrix_and_trace(monkeypatch):
    patch_llm(
        monkeypatch,
        llm_features(
            "数据分析",
            "pipeline",
            keywords=["日志", "ETL", "清洗", "转换", "报表", "分析", "流水线"],
            business_capabilities=["数据采集", "数据管道", "离线分析", "数据可视化", "任务调度"],
            quality_attributes={
                "concurrency": 0.35,
                "realtime": 0.2,
                "reliability": 0.65,
                "scalability": 0.7,
                "data_intensity": 0.95,
                "ai_reasoning": 0.0,
            },
        ),
    )

    service = RecommendationService()
    result = asyncio.run(service.recommend("日志 ETL 清洗、转换和报表分析平台，需要流水线处理", top_k=3))

    assert result.comparison_matrix
    assert result.trace
    assert result.final_recommendation.name in {"管道-过滤器架构", "微服务架构", "Serverless 架构"}
    assert any("HybridReasoningOrchestrator" in item for item in result.trace)
    assert any("DeepSeek 主解析" in item for item in result.trace)
    assert any("知识图谱" in item for item in result.trace)
    assert not any("本地规则提取硬信号" in item for item in result.trace)


def test_service_raises_when_deepseek_parse_unavailable(monkeypatch):
    async def fake_extract_features(self, requirement):
        self.last_error = "DeepSeek 返回 JSON 不符合 Schema。"
        return None

    monkeypatch.setattr("app.services.llm_client.LLMClient.extract_features", fake_extract_features)

    service = RecommendationService()
    try:
        asyncio.run(service.recommend("开发一个系统", top_k=3))
    except RequirementParsingError as exc:
        assert "需求解析失败" in str(exc)
    else:
        raise AssertionError("Expected RequirementParsingError")
