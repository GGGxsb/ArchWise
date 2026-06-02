import asyncio

from app.models.schemas import ExtractedFeatures
from app.services.knowledge_normalizer import KnowledgeNormalizer


class FakeSemanticClient:
    def __init__(self, adjudication=None):
        self.adjudication = adjudication
        self.adjudication_calls = []

    async def embed_texts(self, texts):
        vectors = []
        for text in texts:
            name = self._node_name(text)
            if name in {"支付模块", "支付服务", "支付能力", "支付结算"}:
                vectors.append([1.0, 0.0, 0.0])
            elif name in {"订单模块", "订单服务", "订单数据库", "订单库"}:
                vectors.append([0.0, 1.0, 0.0])
            elif name == "互动服务":
                vectors.append([1.0, 0.0, 0.0])
            elif name == "评论服务":
                vectors.append([0.8, 0.6, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors

    @staticmethod
    def _node_name(text):
        for line in text.splitlines():
            if line.startswith("节点名称:"):
                return line.split(":", 1)[1].strip()
        return text

    async def adjudicate_semantic_merge(self, requirement, candidate_node, top_matches):
        self.adjudication_calls.append((candidate_node, top_matches))
        return self.adjudication


class NoEmbeddingClient(FakeSemanticClient):
    async def embed_texts(self, texts):
        return None


def features() -> ExtractedFeatures:
    return ExtractedFeatures(
        domain="电商交易",
        keywords=["支付", "订单"],
        business_capabilities=["支付结算", "订单管理"],
        architecture_drivers=[],
        topology_expectations={"must_have_components": [], "must_have_relations": [], "quality_infrastructure": []},
        quality_attributes={
            "concurrency": 0.8,
            "realtime": 0.4,
            "reliability": 0.8,
            "scalability": 0.8,
            "data_intensity": 0.5,
            "ai_reasoning": 0,
        },
        constraints={},
        data_flow="transactional",
        ambiguity_notes=[],
    )


def test_normalize_patch_merges_high_confidence_semantic_matches():
    normalizer = KnowledgeNormalizer(FakeSemanticClient())
    patch = {
        "capabilities": [
            {"name": "支付结算", "components": ["支付模块", "订单模块"], "stores": ["订单数据库"]},
        ],
        "components": ["支付模块"],
        "stores": ["订单数据库"],
        "edges": [{"source": "订单模块", "target": "支付模块", "label": "支付", "kind": "sync"}],
    }
    existing = {
        "BusinessCapability": [
            {
                "label": "BusinessCapability",
                "name": "支付结算",
                "context": {"capabilities": ["支付结算"], "components": ["支付服务"], "stores": ["支付库"]},
            }
        ],
        "ArchitectureComponent": [
            {
                "label": "ArchitectureComponent",
                "name": "支付服务",
                "context": {"capabilities": ["支付结算"], "neighbors": ["订单模块"]},
            },
            {
                "label": "ArchitectureComponent",
                "name": "订单服务",
                "context": {"capabilities": ["支付结算"], "neighbors": ["支付模块"]},
            },
        ],
        "DataStore": [
            {
                "label": "DataStore",
                "name": "订单库",
                "context": {"capabilities": ["支付结算"], "components": ["支付模块", "订单模块"]},
            }
        ],
    }

    result = asyncio.run(normalizer.normalize_patch(patch, existing, "电商支付订单系统", features()))

    trial = result["trial_patch"]
    assert trial["capabilities"][0]["name"] == "支付结算"
    assert trial["capabilities"][0]["components"] == ["支付服务", "订单服务"]
    assert trial["capabilities"][0]["stores"] == ["订单库"]
    assert trial["components"] == ["支付服务"]
    assert trial["stores"] == ["订单库"]
    assert trial["edges"][0]["source"] == "订单服务"
    assert trial["edges"][0]["target"] == "支付服务"
    assert any(item["action"] == "merged" and item["original"] == "支付模块" for item in result["report"])


def test_uncertain_match_uses_llm_adjudication_and_excludes_temporary_from_write_patch():
    client = FakeSemanticClient(
        {
            "decision": "temporary",
            "canonical": "互动服务",
            "confidence": 0.78,
            "reason": "互动和评论语义接近但职责边界不清",
        }
    )
    normalizer = KnowledgeNormalizer(client)
    patch = {
        "capabilities": [{"name": "互动行为", "components": ["评论服务"], "stores": []}],
        "components": ["评论服务"],
        "stores": [],
        "edges": [],
    }
    existing = {
        "BusinessCapability": [],
        "ArchitectureComponent": [
            {
                "label": "ArchitectureComponent",
                "name": "互动服务",
                "context": {"capabilities": ["互动行为"], "neighbors": ["内容服务"]},
            }
        ],
        "DataStore": [],
    }

    result = asyncio.run(normalizer.normalize_patch(patch, existing, "社交平台评论互动", features()))

    assert client.adjudication_calls
    assert result["trial_patch"]["components"] == ["评论服务"]
    assert result["write_patch"]["components"] == []
    assert {"label": "ArchitectureComponent", "name": "评论服务"} in result["temporary_items"]
    assert any(item["action"] == "temporary" for item in result["report"])


def test_no_embedding_marks_nodes_temporary_without_string_fallback():
    normalizer = KnowledgeNormalizer(NoEmbeddingClient())
    patch = {
        "capabilities": [{"name": "支付能力", "components": ["支付模块"], "stores": []}],
        "components": ["支付模块"],
        "stores": [],
        "edges": [],
    }
    existing = {
        "BusinessCapability": [{"label": "BusinessCapability", "name": "支付结算", "context": {}}],
        "ArchitectureComponent": [{"label": "ArchitectureComponent", "name": "支付服务", "context": {}}],
        "DataStore": [],
    }

    result = asyncio.run(normalizer.normalize_patch(patch, existing, "支付系统", features()))

    assert result["semantic_available"] is False
    assert result["trial_patch"]["components"] == ["支付模块"]
    assert result["write_patch"]["components"] == []
    assert not any(item["canonical"] == "支付服务" for item in result["report"])


def test_detect_duplicates_uses_embedding_by_label_only():
    normalizer = KnowledgeNormalizer(FakeSemanticClient())
    findings = asyncio.run(
        normalizer.detect_duplicates(
            {
                "BusinessCapability": [
                    {"label": "BusinessCapability", "name": "支付能力", "context": {"capabilities": ["支付结算"]}},
                    {"label": "BusinessCapability", "name": "支付结算", "context": {"capabilities": ["支付结算"]}},
                ],
                "ArchitectureComponent": [
                    {"label": "ArchitectureComponent", "name": "支付服务", "context": {"capabilities": ["支付结算"]}},
                    {"label": "ArchitectureComponent", "name": "支付模块", "context": {"capabilities": ["支付结算"]}},
                ],
                "DataStore": [
                    {"label": "DataStore", "name": "订单库", "context": {"capabilities": ["订单管理"]}},
                    {"label": "DataStore", "name": "订单数据库", "context": {"capabilities": ["订单管理"]}},
                ],
            }
        )
    )

    assert any(item["label"] == "ArchitectureComponent" and {"支付服务", "支付模块"} == {item["left"], item["right"]} for item in findings)
    assert any(item["label"] == "DataStore" and {"订单库", "订单数据库"} == {item["left"], item["right"]} for item in findings)
    assert not any(item["left"] == "支付结算" and item["right"] == "支付服务" for item in findings)
