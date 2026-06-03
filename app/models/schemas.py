from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RequirementRequest(BaseModel):
    requirement: str = Field(..., min_length=5, description="用户自然语言需求")
    top_k: int = Field(default=12, ge=3, le=12, description="候选架构数量")
    topology_fast_mode: bool | None = Field(default=None, description="是否启用本次拓扑快速模式")
    topology_llm_timeout_seconds: float | None = Field(default=None, description="本次拓扑 LLM 调用超时时间；0 表示无上限")
    topology_repair_max_rounds: int | None = Field(default=None, ge=0, le=3, description="本次拓扑 ReAct 补全轮数")


class TopologyRequest(BaseModel):
    requirement: str = Field(..., min_length=5, description="用户自然语言需求")
    features: "ExtractedFeatures"
    final_recommendation: "CandidateEvaluation"
    composition_recommendation: dict[str, Any] = Field(default_factory=dict)
    decision_trace: dict[str, Any] = Field(default_factory=dict)
    topology_fast_mode: bool | None = Field(default=None, description="是否启用本次拓扑快速模式")
    topology_llm_timeout_seconds: float | None = Field(default=None, description="本次拓扑 LLM 调用超时时间；0 表示无上限")
    topology_repair_max_rounds: int | None = Field(default=None, ge=0, le=3, description="本次拓扑 ReAct 补全轮数")


class ExtractedFeatures(BaseModel):
    domain: str
    keywords: list[str]
    business_capabilities: list[str] = Field(default_factory=list)
    architecture_drivers: list[str] = Field(default_factory=list)
    topology_expectations: dict[str, Any] = Field(default_factory=dict)
    quality_attributes: dict[str, float]
    constraints: dict[str, Any]
    data_flow: str
    ambiguity_notes: list[str]


class ArchitectureStyle(BaseModel):
    id: str
    name: str
    category: str
    description: str
    suitable_for: list[str]
    quality_scores: dict[str, float]
    strengths: list[str]
    weaknesses: list[str]
    topology: str
    rules: dict[str, list[str]]


class CandidateEvaluation(BaseModel):
    style_id: str
    name: str
    score: float
    raw_score: float = 0.0
    recommendation_role: str = "对比候选"
    confidence: str = "中"
    matched_reasons: list[str]
    risks: list[str]
    deductions: list[str] = Field(default_factory=list)
    quality_scores: dict[str, float]


class RecommendationResponse(BaseModel):
    requirement: str
    features: ExtractedFeatures
    candidates: list[CandidateEvaluation]
    final_recommendation: CandidateEvaluation
    report: str
    comparison_matrix: list[dict[str, Any]]
    topology_diagrams: dict[str, str]
    topology_graphs: dict[str, Any] = Field(default_factory=dict)
    trace: list[str]
    decision_trace: dict[str, Any] = Field(default_factory=dict)
    composition_recommendation: dict[str, Any] = Field(default_factory=dict)


class KnowledgeStyleRequest(BaseModel):
    style: ArchitectureStyle


class CaseRequest(BaseModel):
    title: str
    requirement: str
    expected_styles: list[str]
    notes: str = ""
