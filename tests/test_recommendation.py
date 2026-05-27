from fastapi.testclient import TestClient

from app.main import app
from app.services.recommendation_service import RecommendationService


client = TestClient(app)


def test_recommend_im_returns_at_least_three_candidates():
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


def test_neo4j_status_endpoint_is_available():
    response = client.get("/api/knowledge/neo4j/status")
    assert response.status_code == 200
    payload = response.json()
    assert "configured" in payload


def test_service_generates_matrix_and_trace():
    import asyncio

    service = RecommendationService()
    result = asyncio.run(service.recommend("日志 ETL 清洗、转换和报表分析平台，需要流水线处理", top_k=3))
    assert result.comparison_matrix
    assert result.trace
    assert result.final_recommendation.name in {"管道-过滤器架构", "微服务架构", "Serverless 架构"}
    assert any("HybridReasoningOrchestrator" in item for item in result.trace)
    assert any("规则引擎" in item for item in result.trace)
    assert any("知识图谱" in item for item in result.trace)
