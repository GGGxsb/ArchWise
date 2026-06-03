"""Structured topology schemas for the 6 architecture styles.

Each schema declares:
- layers: mandatory/optional role-groups the style expects
- layer_connections: which layers may connect and with what semantics
- topology_template: Mermaid skeleton with %%LAYER%% and %%EDGES%% markers
- prompt_hints: extra guidance injected into the LLM extraction prompt
"""

from __future__ import annotations

from functools import lru_cache

from app.models.schemas import (
    LayerConnectionRule,
    LayerSpec,
    StyleSchema,
)

# ───────────────── helpers ─────────────────


def _schema(
    style_id: str,
    style_name: str,
    layers: list[LayerSpec],
    layer_connections: list[LayerConnectionRule],
    topology_template: str,
    layout_direction: str = "TD",
    prompt_hints: str = "",
) -> StyleSchema:
    return StyleSchema(
        style_id=style_id,
        style_name=style_name,
        layers=layers,
        layer_connections=layer_connections,
        topology_template=topology_template,
        layout_direction=layout_direction,
        prompt_hints=prompt_hints,
    )


# ───────────────── 6 style schemas ─────────────────

SCHEMAS: list[StyleSchema] = [
    # ── 1. 单体分层 ─────────────────────────────────────────────────
    _schema(
        style_id="monolithic_layered",
        style_name="单体分层架构",
        layers=[
            LayerSpec(layer_id="presentation", label="表现层", description="用户界面、控制器、API 入口", mandatory=True, min_components=1),
            LayerSpec(layer_id="business", label="业务层", description="核心业务逻辑、服务", mandatory=True, min_components=1),
            LayerSpec(layer_id="data", label="数据层", description="数据库、缓存、持久化存储", mandatory=True, min_components=1),
            LayerSpec(layer_id="governance", label="治理层", description="监控、审计、配置中心", mandatory=False, min_components=0),
        ],
        layer_connections=[
            LayerConnectionRule(source_layer="presentation", target_layer="business", kind="sync", label="调用", allow_skip=False),
            LayerConnectionRule(source_layer="business", target_layer="data", kind="data", label="读写", allow_skip=False),
            LayerConnectionRule(source_layer="business", target_layer="governance", kind="support", label="治理", allow_skip=True),
            LayerConnectionRule(source_layer="presentation", target_layer="data", kind="sync", label="禁止", allow_skip=False),
        ],
        topology_template=(
            "flowchart TD\n"
            "  subgraph pres[表现层]\n"
            "    %%LAYER:presentation%%\n"
            "  end\n"
            "  subgraph biz[业务层]\n"
            "    %%LAYER:business%%\n"
            "  end\n"
            "  subgraph dat[数据层]\n"
            "    %%LAYER:data%%\n"
            "  end\n"
            "  %%EDGES%%"
        ),
        prompt_hints=(
            "单一部署单元，内部严格分层：表现层只能调用业务层，业务层只能调用数据层。"
            "表现层组件（Controller/API）不能直连数据库。所有业务模块共享同一个数据库。"
            "组件数量控制在合理范围，体现单体架构的简洁性。"
        ),
    ),
    # ── 2. 微服务 ───────────────────────────────────────────────────
    _schema(
        style_id="microservices",
        style_name="微服务架构",
        layers=[
            LayerSpec(layer_id="gateway", label="API 网关", description="统一入口、路由、限流", mandatory=True, singleton=True, min_components=1),
            LayerSpec(layer_id="services", label="业务服务", description="独立部署的微服务", mandatory=True, min_components=2),
            LayerSpec(layer_id="service_dbs", label="服务数据库", description="每个微服务独占的数据存储", mandatory=True, min_components=1),
            LayerSpec(layer_id="infrastructure", label="基础设施", description="服务注册、配置、监控、消息队列", mandatory=False, min_components=0),
        ],
        layer_connections=[
            LayerConnectionRule(source_layer="gateway", target_layer="services", kind="sync", label="API 路由"),
            LayerConnectionRule(source_layer="services", target_layer="service_dbs", kind="data", label="读写"),
            LayerConnectionRule(source_layer="services", target_layer="services", kind="sync", label="服务调用", bidirectional=True),
            LayerConnectionRule(source_layer="services", target_layer="infrastructure", kind="support", label="依赖"),
        ],
        topology_template=(
            "flowchart LR\n"
            "  %%LAYER:gateway%%\n"
            "  subgraph services[业务服务集群]\n"
            "    %%LAYER:services%%\n"
            "  end\n"
            "  subgraph dbs[数据存储]\n"
            "    %%LAYER:service_dbs%%\n"
            "  end\n"
            "  %%EDGES%%"
        ),
        prompt_hints=(
            "网关负责统一路由到各业务服务。每个微服务独占自己的数据库，不共享数据库。"
            "服务之间通过 API 或消息队列通信。区分核心业务服务和基础设施服务。"
        ),
    ),
    # ── 3. 事件驱动 ─────────────────────────────────────────────────
    _schema(
        style_id="event_driven",
        style_name="事件驱动架构",
        layers=[
            LayerSpec(layer_id="producers", label="事件生产者", description="产生事件的业务组件", mandatory=True, min_components=1),
            LayerSpec(layer_id="event_bus", label="事件总线", description="消息队列、事件路由", mandatory=True, singleton=True, min_components=1),
            LayerSpec(layer_id="consumers", label="事件消费者", description="订阅事件并处理的组件", mandatory=True, min_components=1),
            LayerSpec(layer_id="event_store", label="事件存储", description="持久化事件日志", mandatory=False, min_components=0),
        ],
        layer_connections=[
            LayerConnectionRule(source_layer="producers", target_layer="event_bus", kind="event", label="发布事件"),
            LayerConnectionRule(source_layer="event_bus", target_layer="consumers", kind="event", label="订阅"),
            LayerConnectionRule(source_layer="event_bus", target_layer="event_store", kind="data", label="持久化"),
            LayerConnectionRule(source_layer="consumers", target_layer="producers", kind="event", label="反馈事件", bidirectional=True),
        ],
        topology_template=(
            "flowchart LR\n"
            "  subgraph prod[生产者]\n"
            "    %%LAYER:producers%%\n"
            "  end\n"
            "  %%LAYER:event_bus%%\n"
            "  subgraph cons[消费者]\n"
            "    %%LAYER:consumers%%\n"
            "  end\n"
            "  %%EDGES%%"
        ),
        layout_direction="LR",
        prompt_hints=(
            "核心是事件总线连接生产者和消费者。每个消费者负责独立的业务逻辑。"
            "生产者只发布事件，不关心谁消费。"
        ),
    ),
    # ── 4. CQRS ─────────────────────────────────────────────────────
    _schema(
        style_id="cqrs",
        style_name="CQRS 架构",
        layers=[
            LayerSpec(layer_id="command_side", label="命令端", description="写入操作入口", mandatory=True, min_components=1),
            LayerSpec(layer_id="event_store", label="事件存储", description="事件溯源日志", mandatory=False, min_components=0),
            LayerSpec(layer_id="projector", label="投影器", description="事件→读模型转换", mandatory=True, min_components=1),
            LayerSpec(layer_id="read_side", label="查询端", description="读模型和查询入口", mandatory=True, min_components=1),
            LayerSpec(layer_id="read_store", label="读存储", description="优化查询的读数据库", mandatory=True, min_components=1),
        ],
        layer_connections=[
            LayerConnectionRule(source_layer="command_side", target_layer="event_store", kind="data", label="写入"),
            LayerConnectionRule(source_layer="event_store", target_layer="projector", kind="event", label="投影"),
            LayerConnectionRule(source_layer="projector", target_layer="read_store", kind="data", label="更新"),
            LayerConnectionRule(source_layer="read_side", target_layer="read_store", kind="data", label="查询"),
            LayerConnectionRule(source_layer="command_side", target_layer="projector", kind="event", label="直接投影"),
        ],
        topology_template=(
            "flowchart LR\n"
            "  subgraph write[写路径]\n"
            "    %%LAYER:command_side%%\n"
            "    %%LAYER:event_store%%\n"
            "  end\n"
            "  %%LAYER:projector%%\n"
            "  subgraph read[读路径]\n"
            "    %%LAYER:read_side%%\n"
            "    %%LAYER:read_store%%\n"
            "  end\n"
            "  %%EDGES%%"
        ),
        prompt_hints=(
            "写端和读端物理分离。写操作走命令模型→事件存储→投影器。"
            "读操作走查询模型→读数据库。投影器负责将事件转换为读优化模型。"
        ),
    ),
    # ── 5. 管道-过滤器 ──────────────────────────────────────────────
    _schema(
        style_id="pipe_filter",
        style_name="管道-过滤器架构",
        layers=[
            LayerSpec(layer_id="source", label="数据源", description="数据入口", mandatory=True, min_components=1),
            LayerSpec(layer_id="filters", label="过滤器", description="数据处理节点", mandatory=True, min_components=2),
            LayerSpec(layer_id="sink", label="数据出口", description="最终输出或存储", mandatory=True, min_components=1),
        ],
        layer_connections=[
            LayerConnectionRule(source_layer="source", target_layer="filters", kind="sync", label="流入"),
            LayerConnectionRule(source_layer="filters", target_layer="filters", kind="sync", label="管道"),
            LayerConnectionRule(source_layer="filters", target_layer="sink", kind="sync", label="输出"),
        ],
        topology_template=(
            "flowchart LR\n"
            "  %%LAYER:source%%\n"
            "  %%LAYER:filters%%\n"
            "  %%LAYER:sink%%\n"
            "  %%EDGES%%"
        ),
        layout_direction="LR",
        prompt_hints=(
            "数据从左到右流经过滤器管道。每个过滤器完成一个独立的处理步骤。"
            "过滤器之间通过管道连接，数据格式需统一。"
        ),
    ),
    # ── 6. 六边形架构 ────────────────────────────────────────────────
    _schema(
        style_id="hexagonal",
        style_name="六边形架构 (Ports & Adapters)",
        layers=[
            LayerSpec(layer_id="inbound_adapters", label="入站适配器", description="HTTP、消息队列、CLI 等输入入口", mandatory=True, min_components=1),
            LayerSpec(layer_id="inbound_ports", label="输入端口", description="领域服务接口定义", mandatory=True, min_components=1),
            LayerSpec(layer_id="domain", label="领域核心", description="纯领域模型、业务规则", mandatory=True, singleton=True, min_components=1),
            LayerSpec(layer_id="outbound_ports", label="输出端口", description="仓储接口、外部服务接口", mandatory=True, min_components=1),
            LayerSpec(layer_id="outbound_adapters", label="出站适配器", description="数据库实现、消息队列、外部 API 调用", mandatory=True, min_components=1),
        ],
        layer_connections=[
            LayerConnectionRule(source_layer="inbound_adapters", target_layer="inbound_ports", kind="sync", label="调用"),
            LayerConnectionRule(source_layer="inbound_ports", target_layer="domain", kind="sync", label="触发"),
            LayerConnectionRule(source_layer="domain", target_layer="outbound_ports", kind="sync", label="依赖"),
            LayerConnectionRule(source_layer="outbound_ports", target_layer="outbound_adapters", kind="sync", label="实现"),
        ],
        topology_template=(
            "flowchart TD\n"
            "  subgraph inbound[入站侧]\n"
            "    %%LAYER:inbound_adapters%%\n"
            "    %%LAYER:inbound_ports%%\n"
            "  end\n"
            "  %%LAYER:domain%%\n"
            "  subgraph outbound[出站侧]\n"
            "    %%LAYER:outbound_ports%%\n"
            "    %%LAYER:outbound_adapters%%\n"
            "  end\n"
            "  %%EDGES%%"
        ),
        prompt_hints=(
            "领域核心独立于任何框架和外部依赖。输入端口定义领域能力契约，输出端口定义数据访问契约。"
            "适配器层才包含 HTTP 服务器、数据库驱动等具体实现。"
        ),
    ),
]


# ───────────────── accessor ─────────────────


@lru_cache(maxsize=1)
def load_all_schemas() -> list[StyleSchema]:
    return list(SCHEMAS)


def get_schema(style_id: str) -> StyleSchema | None:
    for schema in SCHEMAS:
        if schema.style_id == style_id:
            return schema
    return None


def get_schema_names() -> dict[str, str]:
    return {s.style_id: s.style_name for s in SCHEMAS}
