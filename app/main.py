from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.knowledge.repository import KnowledgeRepository
from app.models.schemas import CaseRequest, KnowledgeStyleRequest, RequirementRequest, TopologyRequest
from app.services.exceptions import DeepSeekServiceError, RequirementParsingError
from app.services.knowledge_graph import KnowledgeGraphService
from app.services.recommendation_service import RecommendationService

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
repository = KnowledgeRepository()
service = RecommendationService(repository)
graph_service = KnowledgeGraphService()

app = FastAPI(
    title="ArchWise 软件体系结构风格智能助手",
    description="LLM + 知识图谱 + 多 Agent + 规则引擎的架构推荐演示系统",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/llm/status")
async def llm_status():
    return await service.llm_client.ping()


@app.post("/api/recommend")
async def recommend(payload: RequirementRequest):
    try:
        return await service.recommend(
            payload.requirement,
            payload.top_k,
            topology_options={
                "fast_mode": payload.topology_fast_mode,
                "llm_timeout_seconds": payload.topology_llm_timeout_seconds,
                "repair_max_rounds": payload.topology_repair_max_rounds,
            },
        )
    except (RequirementParsingError, DeepSeekServiceError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/recommend/stream")
async def recommend_stream(payload: RequirementRequest):
    return StreamingResponse(
        service.recommend_stream(
            payload.requirement,
            payload.top_k,
            topology_options={
                "fast_mode": payload.topology_fast_mode,
                "llm_timeout_seconds": payload.topology_llm_timeout_seconds,
                "repair_max_rounds": payload.topology_repair_max_rounds,
            },
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/topology/stream")
async def topology_stream(payload: TopologyRequest):
    return StreamingResponse(
        service.topology_stream(
            requirement=payload.requirement,
            features=payload.features,
            final_recommendation=payload.final_recommendation,
            composition_recommendation=payload.composition_recommendation,
            decision_trace=payload.decision_trace,
            topology_options={
                "fast_mode": payload.topology_fast_mode,
                "llm_timeout_seconds": payload.topology_llm_timeout_seconds,
                "repair_max_rounds": payload.topology_repair_max_rounds,
            },
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/styles")
async def styles():
    return repository.list_styles()


@app.get("/api/knowledge/graph")
async def graph():
    return graph_service.build_graph(repository.list_styles())


@app.get("/api/knowledge/neo4j/status")
async def neo4j_status():
    return graph_service.neo4j_status()


@app.post("/api/knowledge/neo4j/sync")
async def sync_neo4j():
    return graph_service.sync_to_neo4j(repository.list_styles())


@app.post("/api/knowledge/neo4j/rebuild-topology")
async def rebuild_neo4j_topology():
    return graph_service.rebuild_domain_topology()


@app.get("/api/knowledge/neo4j/duplicates")
async def neo4j_duplicate_like_nodes():
    return await graph_service.detect_duplicate_like_nodes()


@app.post("/api/knowledge/styles")
async def add_style(payload: KnowledgeStyleRequest):
    return repository.add_style(payload.style)


@app.get("/api/cases")
async def cases():
    return repository.list_cases()


@app.post("/api/knowledge/cases")
async def add_case(payload: CaseRequest):
    return repository.add_case(payload)
