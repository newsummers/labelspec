from __future__ import annotations

from typing import List, Tuple

from .domain import AnnotationDecision, Route, VerificationDecision


def route_annotation(
    annotation: AnnotationDecision,
    verifier: VerificationDecision,
    threshold: float,
) -> Tuple[Route, List[str]]:
    reasons: List[str] = []
    if annotation.spec_gap:
        return Route.spec_gap, [annotation.missing_rule_reason or "现有标准无法覆盖或消解该 Case"]
    if annotation.ambiguous:
        return Route.ambiguous, ["现有规则同时支持多个候选标签"]
    if not annotation.label or not annotation.checks.uniquely_decidable:
        return Route.spec_gap, [annotation.missing_rule_reason or "规则不足以唯一决定标签"]

    hard_failures = []
    if not verifier.rules_exist or verifier.unsupported_rules:
        hard_failures.append("Annotator 引用了不存在或不适用的 Rule")
    if verifier.omitted_boundary_rules:
        hard_failures.append("遗漏适用的 Boundary Rule")
    if verifier.omitted_priority_rules:
        hard_failures.append("遗漏适用的 Priority Rule")
    if verifier.exclude_triggered:
        hard_failures.append("最终标签触发了 Exclude")
    if verifier.verdict == "REJECT" or not verifier.label_supported:
        hard_failures.append("Verifier 不支持最终标签")
    if hard_failures:
        return Route.review, hard_failures

    effective_confidence = min(annotation.confidence, verifier.confidence)
    if verifier.verdict != "PASS":
        reasons.append("Verifier 结论不稳定")
    if effective_confidence < threshold:
        reasons.append(f"有效置信度 {effective_confidence:.2f} 低于阈值 {threshold:.2f}")
    checks = annotation.checks
    if not all(
        [
            checks.definition_matched,
            checks.excludes_checked,
            checks.alternatives_checked,
            checks.boundaries_checked,
            checks.priorities_checked,
            checks.uniquely_decidable,
        ]
    ):
        reasons.append("Rule 完整性检查未全部通过")
    if reasons:
        return Route.review, reasons
    return Route.auto_accept, ["规则充分、Annotator 与 Verifier 一致且置信度达标"]
