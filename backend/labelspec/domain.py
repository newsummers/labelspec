from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Route(str, Enum):
    auto_accept = "AUTO_ACCEPT"
    review = "REVIEW"
    # Legacy values are kept only so historical rows can still be read. New
    # annotation runs never emit them.
    ambiguous = "AMBIGUOUS"
    spec_gap = "SPEC_GAP"


class RuleType(str, Enum):
    definition = "definition"
    boundary = "boundary"
    priority = "priority"


class DecisionStatus(str, Enum):
    labeled = "LABELED"
    ambiguous = "AMBIGUOUS"
    spec_gap = "SPEC_GAP"
    needs_context = "NEEDS_CONTEXT"


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
    miner_model: str = "ernie-4.5-turbo-128k"
    embedding_model: str = "Embedding-V1"
    auto_accept_threshold: float = Field(default=0.85, ge=0, le=1)
    spec_gap_min_cluster_size: int = Field(default=10, ge=2, le=10000)


class CandidateDecision(BaseModel):
    candidates: List[str] = Field(min_length=1, max_length=5)
    rationale: str


class AnnotationDecision(BaseModel):
    # status is retained for backwards-compatible reads. New writes always
    # use LABELED because every result must carry a legal label.
    status: DecisionStatus = DecisionStatus.labeled
    label: Optional[str] = None
    leaf_rule_used: Optional[str] = None
    decision_rules_referenced: List[str] = Field(default_factory=list)
    rule_reasons: Dict[str, str] = Field(default_factory=dict)
    evidence: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    needs_review: bool = False
    review_reason_codes: List[str] = Field(default_factory=list)
    evidence_items: List[Dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def status_matches_label(self) -> "AnnotationDecision":
        if self.status == DecisionStatus.labeled and (not self.label or not self.leaf_rule_used):
            raise ValueError("标注结果必须同时提供 label 与 leaf_rule_used")
        if self.needs_review and not self.reason.strip():
            raise ValueError("需要审核的标注必须提供可读的审核理由")
        return self

    @property
    def rules_used(self) -> List[str]:
        values = [
            *([self.leaf_rule_used] if self.leaf_rule_used else []),
            *self.decision_rules_referenced,
        ]
        return list(dict.fromkeys(values))


class VerificationIssue(BaseModel):
    code: Literal[
        "DEFINITION_MISMATCH",
        "EXCLUDE_HIT",
        "BETTER_CANDIDATE",
        "MISSED_DECISION_RULE",
        "UNGROUNDED_EVIDENCE",
        "INVALID_RULE_REFERENCE",
        "OTHER",
    ]
    severity: Literal["BLOCKING", "WARNING"] = "BLOCKING"
    rule_id: Optional[str] = None
    message: str = Field(min_length=1)


class VerificationDecision(BaseModel):
    outcome: Literal[
        "PASS", "REVIEW", "SKIPPED", "CONSENSUS", "MAJORITY",
        "ADJUDICATED", "MULTI_INTENT", "UNCLEAR_EXPRESSION", "SPEC_GAP", "INVALID",
    ] = "SKIPPED"
    issues: List[VerificationIssue] = Field(default_factory=list)
    summary: str = "未记录独立核验结果"
    diagnosis: Optional[Literal[
        "CONSENSUS", "MAJORITY", "MULTI_INTENT", "UNCLEAR_EXPRESSION", "SPEC_GAP", "INVALID"
    ]] = None
    label: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    needs_review: bool = False
    reason: str = ""
    inferred_intent: Optional[str] = None
    standard_feedback: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def outcome_matches_issues(self) -> "VerificationDecision":
        blocking = any(issue.severity == "BLOCKING" for issue in self.issues)
        if self.outcome == "PASS" and blocking:
            raise ValueError("PASS 不能包含 BLOCKING issue")
        if self.outcome == "REVIEW" and not blocking:
            raise ValueError("REVIEW 必须包含至少一个 BLOCKING issue")
        if self.outcome == "SKIPPED" and self.issues:
            raise ValueError("SKIPPED 不能包含 issue")
        if self.outcome in {"MULTI_INTENT", "UNCLEAR_EXPRESSION", "SPEC_GAP", "INVALID"}:
            self.needs_review = True
        return self


class RouteReason(BaseModel):
    code: str = Field(min_length=1)
    source: Literal["ANNOTATOR", "VERIFIER", "ROUTER"]
    message: str = Field(min_length=1)


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


class TraceReplica(BaseModel):
    replica_index: int = Field(ge=1)
    candidates: List[str] = Field(default_factory=list)
    decision: AnnotationDecision
    disclosure: DisclosureTrace


class AnnotationResult(BaseModel):
    item_id: str
    text: str
    label: str = Field(min_length=1)
    labels: List[str] = Field(default_factory=list)
    candidates: List[str]
    rules_used: List[str]
    rule_reasons: Dict[str, str]
    evidence: str
    confidence: float
    route: Route
    route_reasons: List[RouteReason]
    decision: AnnotationDecision
    disclosure: DisclosureTrace
    # Legacy verifier payload is optional; it is no longer produced by the
    # annotation pipeline.
    verifier: Optional[VerificationDecision] = None
    replicas: List[TraceReplica] = Field(default_factory=list)


class MinerSuggestion(BaseModel):
    title: str
    labels: List[str]
    rules: List[str]
    typical_cases: List[str]
    problem: str
    target_rule_id: Optional[str] = None
    proposed_change: str
    operations: List[Dict[str, Any]] = Field(min_length=1)
