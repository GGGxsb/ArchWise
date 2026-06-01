from __future__ import annotations

import os
import json
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.models.schemas import ArchitectureStyle


class Neo4jAuraService:
    """Optional Neo4j AuraDB adapter.

    The app keeps working without this dependency/configuration. When AuraDB is
    configured, this adapter can sync the architecture knowledge graph and read
    graph data back from the cloud database.
    """

    def __init__(self) -> None:
        self.uri = os.getenv("NEO4J_URI", "")
        self.user = os.getenv("NEO4J_USER", "neo4j")
        self.password = os.getenv("NEO4J_PASSWORD", "")
        self.database = os.getenv("NEO4J_DATABASE", "neo4j")

    @property
    def configured(self) -> bool:
        return bool(self.uri and self.user and self.password)

    def status(self) -> dict[str, Any]:
        base = {
            "configured": self.configured,
            "uri": self.uri,
            "database": self.database,
            "mode": "auradb" if self.configured else "optional",
        }
        if not self.configured:
            return base
        try:
            with self._driver() as driver:
                driver.verify_connectivity()
            return {**base, "ok": True, "error": None}
        except Exception as exc:
            return {**base, "ok": False, "error": str(exc)}

    def sync_styles(self, styles: Iterable[ArchitectureStyle]) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Neo4j AuraDB is not configured."}

        styles = list(styles)
        with self._driver() as driver:
            with driver.session(database=self.database) as session:
                self._create_constraints(session)
                for style in styles:
                    session.execute_write(self._merge_style, style)
        return {"ok": True, "styles_synced": len(styles)}

    def sync_domain_topology(self, knowledge_file: Path | None = None) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Neo4j AuraDB is not configured."}

        knowledge_file = knowledge_file or Path("data/domain_topology.json")
        data = json.loads(knowledge_file.read_text(encoding="utf-8"))
        with self._driver() as driver:
            with driver.session(database=self.database) as session:
                self._create_constraints(session)
                session.execute_write(self._merge_domain_topology, data)
        return {
            "ok": True,
            "scenarios_synced": len(data.get("scenarios", [])),
            "capabilities_synced": len(data.get("capabilities", {})),
        }

    def sync_singleton_components(self, knowledge_file: Path | None = None) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Neo4j AuraDB is not configured."}

        knowledge_file = knowledge_file or Path("data/domain_topology.json")
        data = json.loads(knowledge_file.read_text(encoding="utf-8"))
        singletons = list(dict.fromkeys(data.get("singleton_components", [])))
        if not singletons:
            return {"ok": True, "singletons_synced": 0}

        query = """
        UNWIND $singletons AS name
        OPTIONAL MATCH (component:ArchitectureComponent {name: name})
        FOREACH (_ IN CASE WHEN component IS NULL THEN [] ELSE [1] END |
          SET component.singleton = true
        )
        WITH name
        OPTIONAL MATCH (store:DataStore {name: name})
        FOREACH (_ IN CASE WHEN store IS NULL THEN [] ELSE [1] END |
          SET store.singleton = true
        )
        """
        with self._driver() as driver:
            with driver.session(database=self.database) as session:
                session.run(query, singletons=singletons).consume()

        return {"ok": True, "singletons_synced": len(singletons)}

    def merge_topology_patch(self, requirement: str, keywords: list[str], patch: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Neo4j AuraDB is not configured."}

        scenario_ids = self._match_domain_scenarios(requirement, keywords)
        if not scenario_ids:
            scenario_ids = ["llm_learned"]
        scenario_name = patch.get("scenario_name") or "LLM 补全场景"
        try:
            with self._driver() as driver:
                with driver.session(database=self.database) as session:
                    self._create_constraints(session)
                    session.execute_write(self._merge_topology_patch, scenario_ids, scenario_name, patch)
            return {
                "ok": True,
                "scenario_ids": scenario_ids,
                "capabilities": len(patch.get("capabilities", [])),
                "components": len(patch.get("components", [])),
                "stores": len(patch.get("stores", [])),
                "edges": len(patch.get("edges", [])),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def retrieve_topology_knowledge(self, requirement: str, keywords: list[str], qualities: dict[str, float]) -> dict[str, Any]:
        if not self.configured:
            return {"components": [], "stores": [], "edges": [], "scenarios": [], "capabilities": []}

        scenario_ids = self._match_domain_scenarios(requirement, keywords)
        active_qualities = [name for name, value in qualities.items() if value >= 0.6]
        scenario_query = """
        MATCH (scenario:DomainScenario)
        WHERE scenario.id IN $scenario_ids
        OPTIONAL MATCH (scenario)-[:REQUIRES]->(cap:BusinessCapability)
        OPTIONAL MATCH (cap)-[:IMPLEMENTED_BY]->(component:ArchitectureComponent)
        OPTIONAL MATCH (component)-[:STORES_IN]->(store:DataStore)
        RETURN collect(DISTINCT scenario.name) AS scenarios,
               collect(DISTINCT cap.name) AS capabilities,
               collect(DISTINCT component.name) AS components,
               collect(DISTINCT store.name) AS stores
        """
        quality_query = """
        MATCH (q:QualityAttribute)-[:REQUIRES_COMPONENT]->(component:ArchitectureComponent)
        WHERE q.name IN $active_qualities
        RETURN collect(DISTINCT component.name) AS components
        """
        edge_query = """
        MATCH (a:ArchitectureComponent)-[r:DEPENDS_ON]->(b:ArchitectureComponent)
        WHERE a.name IN $components AND b.name IN $targets
        RETURN collect(DISTINCT {source: a.name, target: b.name, label: coalesce(r.label, "依赖"), kind: coalesce(r.kind, "sync")}) AS edges
        """
        try:
            with self._driver() as driver:
                with driver.session(database=self.database) as session:
                    scenario_record = session.run(scenario_query, scenario_ids=scenario_ids).single()
                    if not scenario_record:
                        return {"components": [], "stores": [], "edges": [], "scenarios": [], "capabilities": []}
                    quality_record = session.run(quality_query, active_qualities=active_qualities).single()
                    components = self._dedupe(
                        list(scenario_record["components"] or []) + list((quality_record or {}).get("components", []) or [])
                    )
                    stores = self._dedupe(list(scenario_record["stores"] or []))
                    edge_record = session.run(edge_query, components=components, targets=components + stores).single()
                    return {
                        "components": [item for item in components if item],
                        "stores": [item for item in stores if item],
                        "edges": [item for item in (edge_record["edges"] if edge_record else []) if item["source"] and item["target"]],
                        "scenarios": [item for item in scenario_record["scenarios"] if item],
                        "capabilities": [item for item in scenario_record["capabilities"] if item],
                    }
        except Exception:
            return {"components": [], "stores": [], "edges": [], "scenarios": [], "capabilities": []}

    @staticmethod
    def _match_domain_scenarios(requirement: str, keywords: list[str]) -> list[str]:
        text = requirement + " " + " ".join(keywords)
        rules = {
            "instant_messaging": ["即时通讯", "即时通信", "聊天", "消息", "万人在线", "同时在线", "视频通话", "长连接"],
            "social_media": ["社交", "发帖", "点赞", "评论", "私信", "内容推荐"],
            "online_education": ["在线教育", "上课", "课程", "直播", "录播", "回放", "课后互动"],
            "ecommerce": ["电商", "下单", "支付", "促销", "订单", "退款", "库存"],
            "iot": ["物联网", "设备", "传感器", "采集", "远程控制", "告警"],
            "big_data": ["大数据", "TB", "实时计算", "离线分析", "数据可视化", "批量处理", "ETL"],
            "finance_payment": ["金融", "支付", "交易", "对账", "清算", "安全"],
            "game_backend": ["游戏", "玩家", "实时对战", "道具交易", "社交互动"],
            "healthcare": ["医院", "挂号", "患者", "科室", "医生"],
            "logistics": ["物流", "快递", "轨迹", "位置", "异常告警"],
            "short_video": ["短视频", "视频", "转码", "播放", "推荐算法"],
            "smart_city": ["智慧城市", "摄像头", "传感器", "实时监控", "应急指挥"],
            "blog": ["博客", "文章", "分类"],
            "supply_chain": ["供应链", "多企业", "订单跟踪", "库存管理"],
            "exam": ["在线考试", "考试", "防作弊", "自动阅卷", "成绩统计"],
            "industrial_control": ["工业", "生产线", "设备数据", "故障预警", "远程维护"],
            "library": ["图书", "借阅", "归还"],
            "travel_booking": ["旅游", "酒店", "机票", "门票", "预订"],
            "ai_image": ["AI 绘画", "提示词", "生成图片", "图片存储"],
        }
        return [
            scenario_id for scenario_id, scenario_keywords in rules.items()
            if any(keyword in text for keyword in scenario_keywords)
        ]

    @staticmethod
    def _dedupe(items: list[Any]) -> list[Any]:
        return list(dict.fromkeys(item for item in items if item))

    def fetch_graph(self) -> dict[str, list[dict[str, str]]]:
        if not self.configured:
            return {"nodes": [], "edges": []}

        query = """
        MATCH (s:ArchitectureStyle)
        OPTIONAL MATCH (s)-[r]->(n)
        RETURN s, collect({rel: type(r), node: n, value: r.value}) AS links
        """
        nodes: dict[str, dict[str, str]] = {}
        edges: list[dict[str, str]] = []
        with self._driver() as driver:
            with driver.session(database=self.database) as session:
                for record in session.run(query):
                    style = record["s"]
                    style_id = f"style:{style['id']}"
                    nodes[style_id] = {"id": style_id, "label": style["name"], "type": "architecture_style"}
                    for link in record["links"]:
                        node = link["node"]
                        relation = link["rel"]
                        if node is None or relation is None:
                            continue
                        node_id = self._node_id(node)
                        nodes[node_id] = {
                            "id": node_id,
                            "label": node.get("name", node.get("category", node_id)),
                            "type": next(iter(node.labels)).lower(),
                        }
                        rel_label = relation if link["value"] is None else f"{relation}:{link['value']}"
                        edges.append({"source": style_id, "target": node_id, "relation": rel_label})
        return {"nodes": list(nodes.values()), "edges": edges}

    @contextmanager
    def _driver(self):
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RuntimeError("Please install neo4j driver: pip install -r requirements.txt") from exc

        driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        try:
            yield driver
        finally:
            driver.close()

    @staticmethod
    def _create_constraints(session) -> None:
        constraints = [
            "CREATE CONSTRAINT architecture_style_id IF NOT EXISTS FOR (n:ArchitectureStyle) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT quality_name IF NOT EXISTS FOR (n:QualityAttribute) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT scenario_name IF NOT EXISTS FOR (n:Scenario) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT category_name IF NOT EXISTS FOR (n:Category) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT domain_scenario_id IF NOT EXISTS FOR (n:DomainScenario) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT capability_name IF NOT EXISTS FOR (n:BusinessCapability) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT component_name IF NOT EXISTS FOR (n:ArchitectureComponent) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT datastore_name IF NOT EXISTS FOR (n:DataStore) REQUIRE n.name IS UNIQUE",
        ]
        for statement in constraints:
            session.run(statement)

    @staticmethod
    def _merge_style(tx, style: ArchitectureStyle) -> None:
        tx.run(
            """
            MERGE (s:ArchitectureStyle {id: $id})
            SET s.name = $name,
                s.category = $category,
                s.description = $description
            MERGE (c:Category {name: $category})
            MERGE (s)-[:BELONGS_TO]->(c)
            """,
            id=style.id,
            name=style.name,
            category=style.category,
            description=style.description,
        )
        for scenario in style.suitable_for:
            tx.run(
                """
                MATCH (s:ArchitectureStyle {id: $id})
                MERGE (sc:Scenario {name: $scenario})
                MERGE (s)-[:SUITABLE_FOR]->(sc)
                """,
                id=style.id,
                scenario=scenario,
            )
        for quality, score in style.quality_scores.items():
            tx.run(
                """
                MATCH (s:ArchitectureStyle {id: $id})
                MERGE (q:QualityAttribute {name: $quality})
                MERGE (s)-[r:HAS_SCORE]->(q)
                SET r.value = $score
                """,
                id=style.id,
                quality=quality,
                score=score,
            )

    @staticmethod
    def _merge_domain_topology(tx, data: dict[str, Any]) -> None:
        capabilities = data.get("capabilities", {})
        component_layers = data.get("component_layers", {})
        singleton_components = set(data.get("singleton_components", []))

        for scenario in data.get("scenarios", []):
            tx.run(
                """
                MERGE (s:DomainScenario {id: $id})
                SET s.name = $name, s.keywords = $keywords
                """,
                id=scenario["id"],
                name=scenario["name"],
                keywords=scenario.get("keywords", []),
            )
            for capability_name in scenario.get("capabilities", []):
                tx.run(
                    """
                    MATCH (s:DomainScenario {id: $scenario_id})
                    MERGE (c:BusinessCapability {name: $capability})
                    MERGE (s)-[:REQUIRES]->(c)
                    """,
                    scenario_id=scenario["id"],
                    capability=capability_name,
                )

        for capability_name, spec in capabilities.items():
            tx.run("MERGE (:BusinessCapability {name: $name})", name=capability_name)
            for component_name in spec.get("components", []):
                tx.run(
                    """
                    MATCH (c:BusinessCapability {name: $capability})
                    MERGE (component:ArchitectureComponent {name: $component})
                    SET component.layer = $layer,
                        component.singleton = $singleton
                    MERGE (c)-[:IMPLEMENTED_BY]->(component)
                    """,
                    capability=capability_name,
                    component=component_name,
                    layer=component_layers.get(component_name, "业务服务层"),
                    singleton=component_name in singleton_components,
                )
            for store_name in spec.get("stores", []):
                tx.run(
                    """
                    MATCH (c:BusinessCapability {name: $capability})
                    MERGE (store:DataStore {name: $store})
                    SET store.singleton = $singleton
                    MERGE (c)-[:USES_STORE]->(store)
                    WITH c, store
                    MATCH (component:ArchitectureComponent)<-[:IMPLEMENTED_BY]-(c)
                    MERGE (component)-[:STORES_IN]->(store)
                    """,
                    capability=capability_name,
                    store=store_name,
                    singleton=store_name in singleton_components,
                )

        for quality, components in data.get("quality_components", {}).items():
            tx.run("MERGE (:QualityAttribute {name: $name})", name=quality)
            for component_name in components:
                tx.run(
                    """
                    MATCH (q:QualityAttribute {name: $quality})
                    MERGE (component:ArchitectureComponent {name: $component})
                    SET component.layer = $layer,
                        component.singleton = $singleton
                    MERGE (q)-[:REQUIRES_COMPONENT]->(component)
                    """,
                    quality=quality,
                    component=component_name,
                    layer=component_layers.get(component_name, "业务服务层"),
                    singleton=component_name in singleton_components,
                )

        for source, target, label in data.get("dependencies", []):
            if source.startswith("*") or target.startswith("*"):
                continue
            tx.run(
                """
                MERGE (a:ArchitectureComponent {name: $source})
                SET a.layer = $source_layer,
                    a.singleton = $source_singleton
                MERGE (b:ArchitectureComponent {name: $target})
                SET b.layer = $target_layer,
                    b.singleton = $target_singleton
                MERGE (a)-[r:DEPENDS_ON]->(b)
                SET r.label = $label, r.kind = $kind
                """,
                source=source,
                target=target,
                label=label,
                kind="event" if "事件" in label or "通知" in label else "sync",
                source_layer=component_layers.get(source, "业务服务层"),
                target_layer=component_layers.get(target, "业务服务层"),
                source_singleton=source in singleton_components,
                target_singleton=target in singleton_components,
            )

    @staticmethod
    def _merge_topology_patch(tx, scenario_ids: list[str], scenario_name: str, patch: dict[str, Any]) -> None:
        for scenario_id in scenario_ids:
            tx.run(
                """
                MERGE (s:DomainScenario {id: $id})
                SET s.name = coalesce(s.name, $name)
                """,
                id=scenario_id,
                name=scenario_name,
            )

        component_names = set(patch.get("components", []))
        store_names = set(patch.get("stores", []))
        for capability in patch.get("capabilities", []):
            if not isinstance(capability, dict) or not capability.get("name"):
                continue
            capability_name = capability["name"]
            component_names.update(capability.get("components", []))
            store_names.update(capability.get("stores", []))
            tx.run("MERGE (:BusinessCapability {name: $name})", name=capability_name)
            for scenario_id in scenario_ids:
                tx.run(
                    """
                    MATCH (s:DomainScenario {id: $scenario_id})
                    MATCH (c:BusinessCapability {name: $capability})
                    MERGE (s)-[:REQUIRES]->(c)
                    """,
                    scenario_id=scenario_id,
                    capability=capability_name,
                )
            for component_name in capability.get("components", []):
                tx.run(
                    """
                    MATCH (c:BusinessCapability {name: $capability})
                    MERGE (component:ArchitectureComponent {name: $component})
                    MERGE (c)-[:IMPLEMENTED_BY]->(component)
                    """,
                    capability=capability_name,
                    component=component_name,
                )
            for store_name in capability.get("stores", []):
                tx.run(
                    """
                    MATCH (c:BusinessCapability {name: $capability})
                    MERGE (store:DataStore {name: $store})
                    MERGE (c)-[:USES_STORE]->(store)
                    WITH c, store
                    MATCH (component:ArchitectureComponent)<-[:IMPLEMENTED_BY]-(c)
                    MERGE (component)-[:STORES_IN]->(store)
                    """,
                    capability=capability_name,
                    store=store_name,
                )

        for component_name in component_names:
            tx.run("MERGE (:ArchitectureComponent {name: $name})", name=component_name)
        for store_name in store_names:
            tx.run("MERGE (:DataStore {name: $name})", name=store_name)

        for edge in patch.get("edges", []):
            source = edge.get("source")
            target = edge.get("target")
            if not source or not target:
                continue
            tx.run(
                """
                MERGE (a:ArchitectureComponent {name: $source})
                MERGE (b:ArchitectureComponent {name: $target})
                MERGE (a)-[r:DEPENDS_ON]->(b)
                SET r.label = $label, r.kind = $kind
                """,
                source=source,
                target=target,
                label=edge.get("label", "依赖"),
                kind=edge.get("kind", "sync"),
            )

    @staticmethod
    def _node_id(node) -> str:
        labels = list(node.labels)
        label = labels[0] if labels else "Node"
        key = node.get("id") or node.get("name") or node.get("category") or str(node.element_id)
        return f"{label.lower()}:{key}"
