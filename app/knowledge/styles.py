"""Six well-differentiated architecture styles for the ArchWise recommender.

Merged from the original 12:
- monolithic + layered + MVC → monolithic_layered (单体分层)
- Clean Architecture merged into hexagonal (both domain-centric, hexagonal more widely used)
- SOA removed (legacy enterprise pattern, rarely greenfield)
- Blackboard removed (extremely niche AI diagnostic systems)
- Serverless removed (deployment/infrastructure choice, not a software architecture pattern)
"""

from __future__ import annotations

from app.models.schemas import ArchitectureStyle


def load_default_styles() -> list[ArchitectureStyle]:
    return [ArchitectureStyle(**item) for item in DEFAULT_STYLES]


DEFAULT_STYLES = [
    # ── 1. 单体分层 ──────────────────────────────────────────────────────
    {
        "id": "monolithic_layered",
        "name": "单体分层架构",
        "category": "baseline",
        "description": "单一部署单元，内部按表现层、业务层、数据层分层组织，结构清晰，适合绝大多数中小型业务系统。",
        "suitable_for": ["企业后台", "信息管理系统", "中小型 Web 应用", "MVP", "课程原型"],
        "quality_scores": {"scalability": 0.48, "performance": 0.60, "reliability": 0.64, "modifiability": 0.66, "complexity": 0.88, "realtime": 0.34},
        "strengths": ["结构清晰", "开发门槛低", "部署简单", "本地调试方便", "团队易于分工"],
        "weaknesses": ["横向扩展能力有限", "规模增长后维护困难", "不适合多团队独立交付", "技术栈演进成本随体量增长"],
        "topology": "flowchart LR\n  UI[表现层] --> Service[业务层]\n  Service --> Repo[数据访问层]\n  Repo --> DB[(数据库)]",
        "rules": {"prefer": ["管理", "后台", "CRUD", "表单", "权限", "MVP", "简单", "原型", "小型", "单团队"], "avoid": ["万人", "高并发", "实时流", "多团队", "独立部署", "弹性伸缩"]},
        "schema_id": "monolithic_layered",
    },
    # ── 2. 微服务 ────────────────────────────────────────────────────────
    {
        "id": "microservices",
        "name": "微服务架构",
        "category": "distributed",
        "description": "按业务能力拆分为独立部署的服务，通过 API 网关通信，适合多团队协作、弹性伸缩的复杂系统。",
        "suitable_for": ["复杂业务平台", "快速迭代产品", "多团队协作", "弹性伸缩系统"],
        "quality_scores": {"scalability": 0.90, "performance": 0.68, "reliability": 0.74, "modifiability": 0.86, "complexity": 0.38, "realtime": 0.58},
        "strengths": ["服务独立部署", "扩展性强", "便于技术异构", "故障隔离能力较好"],
        "weaknesses": ["分布式治理复杂", "链路追踪和运维要求高", "数据一致性设计成本高", "团队能力要求高"],
        "topology": "flowchart LR\n  Client[客户端] --> Gateway[API Gateway]\n  Gateway --> Svc1[业务服务 A]\n  Gateway --> Svc2[业务服务 B]\n  Svc1 --> DB1[(独立数据库)]\n  Svc2 --> DB2[(独立数据库)]",
        "rules": {"prefer": ["扩展", "多团队", "独立部署", "复杂业务", "弹性", "云原生", "高可用"], "avoid": ["简单", "MVP", "单团队", "小型系统"]},
        "schema_id": "microservices",
    },
    # ── 3. 事件驱动 ──────────────────────────────────────────────────────
    {
        "id": "event_driven",
        "name": "事件驱动架构",
        "category": "distributed",
        "description": "以事件生产、事件总线和消费者为核心，适合异步解耦、高并发和实时通知场景。",
        "suitable_for": ["即时通信", "交易通知", "IoT 事件流", "高并发异步处理"],
        "quality_scores": {"scalability": 0.88, "performance": 0.82, "reliability": 0.76, "modifiability": 0.80, "complexity": 0.45, "realtime": 0.86},
        "strengths": ["高吞吐量", "模块解耦", "便于异步削峰", "适合实时消息与通知"],
        "weaknesses": ["事件一致性难度高", "调试和链路追踪复杂", "事件模型需要规范治理", "不适合强事务同步场景"],
        "topology": "flowchart LR\n  Producer[事件生产者] --> Bus[(事件总线)]\n  Bus --> C1[消费者 A]\n  Bus --> C2[消费者 B]\n  Bus --> C3[消费者 C]",
        "rules": {"prefer": ["实时", "消息", "事件", "异步", "高并发", "通知", "削峰", "IoT"], "avoid": ["强事务", "同步审批", "简单 CRUD"]},
        "schema_id": "event_driven",
    },
    # ── 4. CQRS ──────────────────────────────────────────────────────────
    {
        "id": "cqrs",
        "name": "CQRS 架构",
        "category": "data-consistency",
        "description": "读写模型分离，适合读写压力差异大、审计和事件溯源要求明显的系统。",
        "suitable_for": ["高读写压力系统", "订单交易", "审计系统", "复杂查询平台"],
        "quality_scores": {"scalability": 0.82, "performance": 0.78, "reliability": 0.70, "modifiability": 0.68, "complexity": 0.36, "realtime": 0.62},
        "strengths": ["读写独立优化", "适合复杂查询", "可结合事件溯源", "提升高读场景性能"],
        "weaknesses": ["最终一致性复杂", "模型同步成本高", "开发和测试成本较高", "不适合简单 CRUD"],
        "topology": "flowchart LR\n  Client[客户端] --> Command[命令模型]\n  Client --> Query[查询模型]\n  Command --> EventStore[(事件存储)]\n  EventStore --> Projector[投影器]\n  Projector --> ReadDB[(读库)]",
        "rules": {"prefer": ["读多写少", "审计", "事件溯源", "复杂查询", "订单", "交易"], "avoid": ["简单 CRUD", "小型系统", "单体"]},
        "schema_id": "cqrs",
    },
    # ── 5. 管道-过滤器 ───────────────────────────────────────────────────
    {
        "id": "pipe_filter",
        "name": "管道-过滤器架构",
        "category": "dataflow",
        "description": "将数据处理拆为可组合的串行或并行过滤器，适合 ETL、数据清洗和流水线处理。",
        "suitable_for": ["数据处理", "ETL", "日志分析", "批处理流水线", "媒体转码"],
        "quality_scores": {"scalability": 0.70, "performance": 0.72, "reliability": 0.62, "modifiability": 0.78, "complexity": 0.65, "realtime": 0.48},
        "strengths": ["处理步骤清晰", "组件可复用", "易于并行化", "适合数据流编排"],
        "weaknesses": ["全局错误处理复杂", "不适合强交互业务", "中间数据格式需统一"],
        "topology": "flowchart LR\n  Source[数据源] --> F1[清洗过滤器]\n  F1 --> F2[转换过滤器]\n  F2 --> F3[分析过滤器]\n  F3 --> Sink[输出]",
        "rules": {"prefer": ["数据流", "ETL", "清洗", "流水线", "批处理", "日志", "转码"], "avoid": ["复杂交互", "强事务", "同步请求"]},
        "schema_id": "pipe_filter",
    },
    # ── 6. 六边形架构 ────────────────────────────────────────────────────
    {
        "id": "hexagonal",
        "name": "六边形架构 (Ports & Adapters)",
        "category": "domain-centric",
        "description": "将领域核心通过端口与外部适配器隔离，适合长期演进、测试要求高、业务规则复杂的系统。",
        "suitable_for": ["领域模型复杂系统", "金融业务", "长期维护核心系统", "多端适配系统"],
        "quality_scores": {"scalability": 0.62, "performance": 0.60, "reliability": 0.75, "modifiability": 0.88, "complexity": 0.50, "realtime": 0.42},
        "strengths": ["核心业务独立", "可测试性强", "外部依赖可替换", "适合领域驱动设计", "框架无关"],
        "weaknesses": ["抽象层较多", "初期设计成本高", "对团队建模能力有要求", "小项目可能过重"],
        "topology": "flowchart LR\n  Web[Web 适配器] --> Port[输入端口]\n  Port --> Domain[领域核心]\n  Domain --> OutPort[输出端口]\n  OutPort --> DB[(数据库适配器)]\n  OutPort --> MQ[消息适配器]",
        "rules": {"prefer": ["领域", "长期演进", "测试", "多端", "业务规则", "核心系统", "金融"], "avoid": ["极简", "一次性脚本", "短期原型", "简单 CRUD"]},
        "schema_id": "hexagonal",
    },
]
