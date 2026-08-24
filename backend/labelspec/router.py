from __future__ import annotations

from typing import List, Optional, Tuple

from .domain import AnnotationDecision, Route, RouteReason, VerificationDecision


def _reason(code: str, source: str, message: str) -> RouteReason:
    return RouteReason(code=code, source=source, message=message)


def route_annotation(
    annotation: AnnotationDecision,
    verifier: Optional[VerificationDecision] = None,
    threshold: float = 0.85,
) -> Tuple[Route, List[RouteReason]]:
    """Route a labeled decision using deterministic signals only.

    ``verifier`` remains an optional argument for callers that still use the
    old API, but it is deliberately ignored by new runs.
    """
    reasons: List[RouteReason] = []
    # Compatibility for callers of the removed Verifier API. Production
    # annotation runs do not pass a verifier payload.
    if verifier is not None:
        blocking = [issue for issue in verifier.issues if issue.severity == "BLOCKING"]
        if blocking:
            return Route.review, [
                _reason(
                    issue.code,
                    "VERIFIER",
                    f"{issue.rule_id}: {issue.message}" if issue.rule_id else issue.message,
                )
                for issue in blocking
            ]
    if annotation.status.value in {"AMBIGUOUS", "SPEC_GAP", "NEEDS_CONTEXT"}:
        return Route.review, [
            _reason(annotation.status.value, "ANNOTATOR", annotation.reason)
        ]
    if not annotation.label or not annotation.leaf_rule_used:
        return Route.review, [
            _reason("INVALID_LABEL", "ROUTER", "标注结果没有提供合法标签，必须人工审核")
        ]

    for code in annotation.review_reason_codes:
        reasons.append(_reason(code, "ANNOTATOR", annotation.reason))
    if annotation.needs_review:
        if not reasons:
            reasons.append(_reason("ANNOTATOR_REVIEW", "ANNOTATOR", annotation.reason))
        return Route.review, reasons

    if annotation.confidence < threshold:
        return Route.review, [
            _reason(
                "LOW_CONFIDENCE",
                "ROUTER",
                f"Annotator 置信度 {annotation.confidence:.2f} 低于自动通过阈值 {threshold:.2f}；{annotation.reason}",
            )
        ]

    return Route.auto_accept, [
        _reason(
            "AUTO_ACCEPT",
            "ROUTER",
            "标签属于当前 Standard 的合法叶子，原文证据和规则依据完整，置信度达到自动通过阈值",
        )
    ]
