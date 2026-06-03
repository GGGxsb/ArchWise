from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ────────────────────────────── Request / Feature Models ──────────────────────────────


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


# ────────────────────────────── Domain Models ──────────────────────────────


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
    schema_id: str = Field(default="", description="Maps to StyleSchema.style_id; empty when schema is not yet defined")


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


# ────────────────────────────── Style Schema Models ──────────────────────────────
# Each architecture style defines a structural template (StyleSchema) that
# describes mandatory/optional layers, connection rules between layers, and
# a canonical Mermaid skeleton.  The LLM fills a StyleInstance by assigning
# domain-specific components to layers and declaring connections.  The
# StyleTopologyRenderer then validates the instance against the schema and
# produces the final Mermaid diagram.


class LayerSpec(BaseModel):
    """One layer (or role-group) inside an architecture style schema."""
    layer_id: str = Field(..., description="Identifier: presentation, business, data, event_bus, gateway, etc.")
    label: str = Field(..., description="Human-readable layer name shown in the diagram.")
    description: str = Field(default="", description="What this layer is responsible for.")
    mandatory: bool = Field(default=True, description="Must the LLM provide at least one component in this layer?")
    min_components: int = Field(default=1, ge=0, description="Minimum number of components the LLM must supply.")
    max_components: int | None = Field(default=None, description="Optional cap on components in this layer.")
    singleton: bool = Field(default=False, description="Layer accepts exactly one component (e.g. a single Event Bus).")
    allow_multiple_instances: bool = Field(default=True, description="Can this layer appear more than once in composition mode?")


class LayerConnectionRule(BaseModel):
    """Declares which layers may connect, in which direction, and with what semantics."""
    source_layer: str = Field(..., description="layer_id of the source.")
    target_layer: str = Field(..., description="layer_id of the target.")
    kind: str = Field(default="sync", description="Edge kind: sync, event, data, responsibility.")
    label: str = Field(default="依赖", description="Default edge label.")
    bidirectional: bool = Field(default=False)
    allow_skip: bool = Field(default=True, description="Can an edge skip intermediate layers?")


class StyleSchema(BaseModel):
    """Complete structural template for one architecture style."""
    style_id: str = Field(..., description="Matches ArchitectureStyle.id.")
    style_name: str = Field(default="", description="Human-readable name for prompt context.")
    layers: list[LayerSpec] = Field(..., min_length=1, description="Ordered layers/role-groups.")
    layer_connections: list[LayerConnectionRule] = Field(default_factory=list, description="Allowed inter-layer connections.")
    topology_template: str = Field(default="", description="Mermaid skeleton with %%PLACEHOLDER%% markers.")
    layout_direction: str = Field(default="TD", description="Mermaid flowchart direction: TD, LR, RL, BT.")
    prompt_hints: str = Field(default="", description="Extra guidance injected into the LLM extraction prompt.")


class ComponentDef(BaseModel):
    """One concrete component inside a StyleInstance, assigned by the LLM."""
    name: str = Field(..., description="Component display name, 2-8 Chinese characters preferred.")
    layer_id: str = Field(..., description="Which layer this component belongs to.")
    component_type: str = Field(default="service", description="service, data_store, gateway, event_bus, cache, external, infrastructure.")


class ConnectionDef(BaseModel):
    """One concrete connection between components inside a StyleInstance."""
    source: str = Field(..., description="Source component name (must match a ComponentDef.name).")
    target: str = Field(..., description="Target component name.")
    kind: str = Field(default="sync", description="sync, event, data.")
    label: str = Field(default="", description="Short edge label.")


class StyleInstance(BaseModel):
    """LLM-filled instantiation of a StyleSchema for a concrete requirement."""
    style_id: str = Field(..., description="Which StyleSchema this instantiates.")
    components: list[ComponentDef] = Field(..., min_length=1, description="All components with layer assignments.")
    connections: list[ConnectionDef] = Field(default_factory=list, description="Component-level connections.")
    notes: str = Field(default="", description="LLM commentary on design decisions.")


class ComposeStyleInstances(BaseModel):
    """Container for a primary style instance plus optional supporting style instances."""
    primary: StyleInstance
    supporting: list[StyleInstance] = Field(default_factory=list)
    composition_notes: str = Field(default="")
