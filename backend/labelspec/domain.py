from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Route(str, Enum):
    auto_accept = "AUTO_ACCEPT"
    review = "REVIEW"
    ambiguous = "AMBIGUOUS"
    spec_gap = "SPEC_GAP"


class RuleType(str, Enum):
    definition = "definition"
    boundary = "boundary"
    priority = "priority"


class SourceReference(BaseModel):
    document_id: str
    filename: str
    locator: str = ""


class LabelDefinition(BaseModel):
    label_id: str = Field(pattern=r"^L\d{3,}$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parent_id: Optional[str] = None
    source_refs: List[SourceReference] = Field(default_factory=list)


class LabelsDocument(BaseModel):
    labels: List[LabelDefinition] = Field(min_length=1)

    @field_validator("labels")
    @classmethod
    def label_ids_are_unique(cls, value: List[LabelDefinition]) -> List[LabelDefinition]:
        label_ids = [item.label_id for item in value]
        if len(label_ids) != len(set(label_ids)):
            raise ValueError("标签 ID 必须唯一")
        return value


class DefinitionRule(BaseModel):
    rule_id: str = Field(pattern=r"^D\d{3,}$")
    label_id: str = Field(pattern=r"^L\d{3,}$")
    definition: str = Field(min_length=1)
    include: List[str] = Field(default_factory=list)
    exclude: List[str] = Field(default_factory=list)
    source_refs: List[SourceReference] = Field(default_factory=list)


class BoundaryRule(BaseModel):
    rule_id: str = Field(pattern=r"^B\d{3,}$")
    label_ids: List[str] = Field(min_length=2)
    scope_label_id: Optional[str] = None
    condition: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    source_refs: List[SourceReference] = Field(default_factory=list)

    @field_validator("label_ids")
    @classmethod
    def boundary_labels_are_unique(cls, value: List[str]) -> List[str]:
        if len(value) != len(set(value)):
            raise ValueError("Boundary Rule 中不能重复引用同一标签")
        return value


class PriorityRule(BaseModel):
    rule_id: str = Field(pattern=r"^P\d{3,}$")
    principle: str = Field(min_length=1)
    scope_label_id: Optional[str] = None
    source_refs: List[SourceReference] = Field(default_factory=list)


class ConflictCandidate(BaseModel):
    rule_id: str = ""
    label_ids: List[str] = Field(default_factory=list)
    scope_label_id: Optional[str] = None
    condition: str = ""
    decision: str = ""
    source_refs: List[SourceReference] = Field(default_factory=list)


class DecisionRulesDocument(BaseModel):
    boundary_rules: List[BoundaryRule] = Field(default_factory=list)
    priority_rules: List[PriorityRule] = Field(default_factory=list)


class CompilationConflict(BaseModel):
    conflict_id: str
    kind: str
    entity_key: str
    message: str
    source_refs: List[SourceReference] = Field(default_factory=list)
    candidates: List[ConflictCandidate] = Field(default_factory=list)
    source_excerpts: List[Dict[str, str]] = Field(default_factory=list)
    resolved: bool = False


class CompiledStandard(BaseModel):
    schema_version: Literal["0.2"] = "0.2"
    name: str = Field(min_length=1)
    labels: LabelsDocument
    definition_rules: List[DefinitionRule]
    decision_rules: DecisionRulesDocument
    conflicts: List[CompilationConflict] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    code: str
    message: str
    path: str = ""
    severity: str = "error"


class ValidationReport(BaseModel):
    valid: bool
    issues: List[ValidationIssue] = Field(default_factory=list)


class ModelSettings(BaseModel):
    compiler_model: str = "ernie-4.5-turbo-128k"
    annotator_model: str = "ernie-4.5-turbo-128k"
    verifier_model: str = "ernie-4.5-turbo-128k"
    miner_model: str = "ernie-4.5-turbo-128k"
    embedding_model: str = "Embedding-V1"
    auto_accept_threshold: float = Field(default=0.85, ge=0, le=1)
    spec_gap_min_cluster_size: int = Field(default=10, ge=2, le=10000)


class CandidateDecision(BaseModel):
    candidates: List[str] = Field(min_length=1, max_length=5)
    rationale: str


class RuleChecks(BaseModel):
    definition_matched: bool
    excludes_checked: bool
    alternatives_checked: bool
    boundaries_checked: bool
    priorities_checked: bool
    uniquely_decidable: bool


class AnnotationDecision(BaseModel):
    label: Optional[str] = None
    leaf_rule_used: Optional[str] = None
    path_rules_referenced: List[str] = Field(default_factory=list)
    decision_rules_referenced: List[str] = Field(default_factory=list)
    rule_reasons: Dict[str, str] = Field(default_factory=dict)
    evidence: str
    confidence: float = Field(ge=0, le=1)
    ambiguous: bool = False
    spec_gap: bool = False
    needs_history: bool = False
    missing_rule_reason: Optional[str] = None
    checks: RuleChecks

    @property
    def rules_used(self) -> List[str]:
        values = [
            *([self.leaf_rule_used] if self.leaf_rule_used else []),
            *self.path_rules_referenced,
            *self.decision_rules_referenced,
        ]
        return list(dict.fromkeys(values))


class VerificationDecision(BaseModel):
    label_supported: bool
    rules_exist: bool
    definition_satisfied: bool
    exclude_triggered: bool
    omitted_boundary_rules: List[str] = Field(default_factory=list)
    omitted_priority_rules: List[str] = Field(default_factory=list)
    unsupported_rules: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    verdict: Literal["PASS", "UNCERTAIN", "REJECT"]
    explanation: str


class DefinitionChain(BaseModel):
    leaf_label_id: str
    leaf_path: str
    chain: List[DefinitionRule]


class DisclosureTrace(BaseModel):
    label_map: List[LabelDefinition]
    global_priority_rules: List[PriorityRule]
    candidates: List[str]
    definitions: List[DefinitionChain]
    boundaries: List[BoundaryRule]
    historical_cases: List[Dict[str, Any]] = Field(default_factory=list)


class AnnotationResult(BaseModel):
    item_id: str
    text: str
    label: Optional[str]
    candidates: List[str]
    rules_used: List[str]
    rule_reasons: Dict[str, str]
    evidence: str
    confidence: float
    route: Route
    route_reasons: List[str]
    disclosure: DisclosureTrace
    verifier: VerificationDecision


class MinerSuggestion(BaseModel):
    title: str
    labels: List[str]
    rules: List[str]
    typical_cases: List[str]
    problem: str
    target_rule_id: Optional[str] = None
    proposed_change: str
