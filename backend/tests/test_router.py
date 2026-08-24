import pytest
from pydantic import ValidationError

from labelspec.domain import AnnotationDecision, Route, VerificationDecision
from labelspec.router import route_annotation


def annotation(**overrides):
    data = {
        "status": "LABELED",
        "label": "金融/贷款",
        "leaf_rule_used": "D001",
        "decision_rules_referenced": [],
        "rule_reasons": {},
        "evidence": "贷款利率",
        "reason": "文本直接询问贷款利率，符合贷款定义。",
        "confidence": 0.94,
    }
    data.update(overrides)
    return AnnotationDecision.model_validate(data)


def verifier(**overrides):
    data = {
        "outcome": "PASS",
        "issues": [],
        "summary": "未发现阻塞问题",
    }
    data.update(overrides)
    return VerificationDecision.model_validate(data)


def test_auto_accept_requires_supported_confident_decision() -> None:
    route, reasons = route_annotation(annotation(), verifier(), 0.85)

    assert route == Route.auto_accept
    assert reasons[0].code == "AUTO_ACCEPT"


def test_spec_gap_is_never_force_labeled() -> None:
    route, reasons = route_annotation(
        annotation(
            status="SPEC_GAP",
            label=None,
            leaf_rule_used=None,
            reason="现有标准没有规定金融方案",
        ),
        verifier(outcome="SKIPPED", summary="无需核验"),
        0.85,
    )

    assert route == Route.review
    assert reasons[0].message == "现有标准没有规定金融方案"


def test_blocking_verifier_issue_routes_to_review_with_specific_reason() -> None:
    route, reasons = route_annotation(
        annotation(),
        verifier(
            outcome="REVIEW",
            issues=[
                {
                    "code": "MISSED_DECISION_RULE",
                    "severity": "BLOCKING",
                    "rule_id": "B001",
                    "message": "该边界规则会改变最终标签",
                }
            ],
        ),
        0.85,
    )

    assert route == Route.review
    assert reasons[0].code == "MISSED_DECISION_RULE"
    assert reasons[0].message == "B001: 该边界规则会改变最终标签"


def test_warning_does_not_block_auto_accept() -> None:
    route, _ = route_annotation(
        annotation(),
        verifier(
            issues=[
                {
                    "code": "OTHER",
                    "severity": "WARNING",
                    "message": "可以补充更详细的解释",
                }
            ]
        ),
        0.85,
    )

    assert route == Route.auto_accept


def test_needs_context_routes_to_review_without_verifier() -> None:
    route, reasons = route_annotation(
        annotation(
            status="NEEDS_CONTEXT",
            label=None,
            leaf_rule_used=None,
            reason="需要历史人工 Case 判断",
        ),
        verifier(outcome="SKIPPED", summary="无需核验"),
        0.85,
    )

    assert route == Route.review
    assert reasons[0].code == "NEEDS_CONTEXT"


def test_low_confidence_reason_contains_value_and_threshold() -> None:
    route, reasons = route_annotation(annotation(confidence=0.71), verifier(), 0.85)

    assert route == Route.review
    assert reasons[0].code == "LOW_CONFIDENCE"
    assert "0.71" in reasons[0].message
    assert "0.85" in reasons[0].message


def test_pass_cannot_hide_blocking_issue() -> None:
    with pytest.raises(ValidationError, match="PASS 不能包含 BLOCKING issue"):
        verifier(
            issues=[
                {
                    "code": "EXCLUDE_HIT",
                    "severity": "BLOCKING",
                    "message": "命中排除条件",
                }
            ]
        )
