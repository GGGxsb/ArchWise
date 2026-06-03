# ArchWise | 基于 DeepSeek LLM + 多 Agent 的软件体系结构风格智能助手

ArchWise 是一个面向软件架构设计场景的智能推荐系统，能够根据用户自然语言需求自动完成需求理解、架构风格推荐、多维度对比分析、决策溯源和定制架构拓扑图生成。

## 项目背景

在软件系统设计早期，开发者需要根据业务规模、并发压力、实时性、可靠性、扩展性、数据流特征和部署约束选择合适的软件体系结构风格。传统方式依赖人工经验，容易出现判断主观、依据不清晰、候选方案对比不足等问题。

ArchWise 将"自然语言需求"转化为"结构化架构决策"，通过 LLM 语义理解 + 三 Agent 协作流水线，提供可解释、可追溯、可视化的架构推荐结果。

适用场景包括：

- 软件体系结构课程作业
- 架构风格选型辅助
- 需求到架构映射演示
- 多架构方案对比分析
- 架构设计早期原型验证

## 主要功能

- **需求理解**：RequirementParserAgent 从自然语言需求中提取业务领域、关键词、业务能力、质量属性、数据流和部署约束，内建一致性和内部矛盾检测。
- **架构推荐**：ArchitectureMatcherAgent 结合 LLM 语义评分和本地特征校验，从 6 种架构风格中推荐最优方案。对简单系统主动预警过度设计。
- **多维度对比**：从性能、扩展性、可靠性、可维护性、实时性、复杂度 6 个维度生成对比矩阵。
- **评估报告**：EvaluationGeneratorAgent 生成含推荐理由、风险提示和落地建议的 Markdown 报告，LLM 不可用时自动切换本地模板兜底。
- **组合推荐**：判断是否需要组合架构，说明主架构和辅助架构各自负责的部分。
- **定制拓扑图**：LLM 根据 StyleSchema 生成 Mermaid 架构拓扑图，展示组件关系、层归属和架构模式职责映射。
- **决策溯源**：展示需求特征、评分证据、Agent 校验结果等全链路推理过程。
- **流式输出**：报告和拓扑图支持 Server-Sent Events 流式生成。

## 技术栈

| 维度 | 技术 |
| --- | --- |
| 后端 | Python、FastAPI、Pydantic |
| 前端 | HTML、CSS、JavaScript (vanilla) |
| 可视化 | Mermaid.js |
| 大语言模型 | DeepSeek API (OpenAI-compatible) |
| 推理机制 | 三 Agent 协作管道 (非平级、链式) |
| 数据交互 | REST API、Server-Sent Events |
| 配置管理 | python-dotenv |
| 测试 | pytest |

## 系统架构

```
用户输入自然语言需求
        │
        ▼
┌─────────────────────────┐
│  RequirementParserAgent │  ← LLM 调用 #1
│  需求解析 + 一致性校验    │
└───────────┬─────────────┘
            ▼ ExtractedFeatures
┌─────────────────────────┐
│  ArchitectureMatcherAgent│  ← LLM 调用 #2
│  LLM 评分 + 后置校验     │     本地一致性校验
└───────────┬─────────────┘
            ▼ 候选排序
┌─────────────────────────┐
│  EvaluationGeneratorAgent│  ← LLM 调用 #3
│  报告生成 + 模板兜底      │
└───────────┬─────────────┘
            ▼ Markdown 报告 + 拓扑图
        RecommendationResponse
```

详见 [架构设计文档](docs/架构设计文档.md) 和 [架构设计专题讲解](docs/架构设计专题讲解.md)。

## 支持的架构风格

| # | 架构 | 定位 |
|---|------|------|
| 1 | 单体分层架构 | 默认选择，90% 简单系统的答案 |
| 2 | 微服务架构 | 多团队、高扩展、独立部署 |
| 3 | 事件驱动架构 | 异步解耦、高吞吐、实时通知 |
| 4 | CQRS 架构 | 读写分离、审计溯源 |
| 5 | 管道-过滤器架构 | 数据流处理、ETL |
| 6 | 六边形架构 | 领域复杂、长期演进、可测试性 |

## 环境依赖与前置条件

- Python 3.11 或更高版本
- DeepSeek API Key（可选；未配置时系统使用本地模板兜底）

主要 Python 依赖：

- fastapi、uvicorn
- pydantic
- httpx
- jinja2
- python-dotenv
- pytest

## 快速部署与运行

### 1. 拉取项目

```bash
git clone <your-repository-url>
cd ArchWise
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```env
LLM_API_KEY=你的 DeepSeek API Key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
LLM_TIMEOUT_SECONDS=12
```

### 4. 启动服务

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 5. 访问系统

- Web 页面：http://127.0.0.1:8000
- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health
- LLM 状态：http://127.0.0.1:8000/api/llm/status

## 项目目录结构

```text
ArchWise/
  app/
    agents/
      requirement_parser.py    # Agent 1: 需求解析 + 一致性校验 + 兜底
      architecture_matcher.py  # Agent 2: LLM 评分 + 本地后置校验
      evaluation_generator.py  # Agent 3: 报告生成 + 模板兜底
    knowledge/
      styles.py                # 6 种架构风格定义
      style_schemas.py         # 6 种拓扑 Schema (层/连接/模板)
      repository.py            # 知识库 CRUD
    models/
      schemas.py               # Pydantic 数据模型
    services/
      llm_client.py            # OpenAI-compatible LLM 客户端
      hybrid_orchestrator.py   # 三 Agent 链式编排器
      recommendation_service.py # 推荐服务入口
      composition_recommender.py # 组合架构推荐
      report_formatter.py      # Markdown 报告格式化
      style_topology_renderer.py # 拓扑图 Mermaid 渲染
      knowledge_graph.py       # 内存图构建器 (前端可视化)
    static/                    # CSS + JS
    templates/                 # Jinja2 页面模板
    main.py                    # FastAPI 入口
  docs/
    需求规格说明书.md           # 含 AI 系统特有需求分析
    架构设计文档.md             # Agent 协作 + LLM 集成方案
    架构设计专题讲解.md         # 设计哲学与关键决策
  tests/
  requirements.txt
  .env.example
  README.md
```

## 设计原则

- **架构倾向而非架构规则**：Prompt 编码通用原则（"简单架构能做就不用复杂架构"），不做硬编码阈值判断
- **LLM 主判断 + 后置校验**：LLM 独立评分；本地 Agent 在显著矛盾时标记，不前置干预
- **串行管道而非平级投票**：架构推荐是序列决策，三个 Agent 各负责一个阶段
- **LLM 不可用时降级运行**：需求解析用正则兜底，报告用本地模板生成，功能不中断

详见 [架构设计专题讲解](docs/架构设计专题讲解.md)。

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/recommend | 同步推荐（返回完整 JSON） |
| POST | /api/recommend/stream | 流式推荐（SSE） |
| POST | /api/topology/stream | 流式拓扑生成（SSE） |
| GET | /api/styles | 获取 6 种架构风格 |
| GET | /api/knowledge/graph | 获取风格关系图谱数据 |
| GET | /api/llm/status | LLM 连接状态 |

## 后续优化方向

- LLM 结果缓存，降低重复请求成本
- 案例 embedding 相似度检索
- 人工反馈写入案例库
- 多 LLM 交叉验证（如 Qwen 做一致性检查）
- 报告和拓扑图导出 PDF/Markdown

## 开源协议

本项目用于课程作业和学习交流。
