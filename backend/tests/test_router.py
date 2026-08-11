from labelspec.domain import AnnotationDecision, RuleChecks, Route, VerificationDecision
from labelspec.router import route_annotation


def annotation(**overrides):
    data = {
        "label": "金融/贷款",
        "rules_used": ["D001", "B001", "P001"],
        "rule_reasons": {},
        "evidence": "询问贷款利率",
        "confidence": 0.94,
        "ambiguous": False,
        "spec_gap": False,
        "needs_history": False,
        "checks": RuleChecks(
            definition_matched=True,
            excludes_checked=True,
            alternatives_checked=True,
            boundaries_checked=True,
            priorities_checked=True,
            uniquely_decidable=True,
        ),
    }
    data.update(overrides)
    return AnnotationDecision.model_validate(data)


def verifier(**overrides):
    data = {
        "label_supported": True,
        "rules_exist": True,
        "definition_satisfied": True,
        "exclude_triggered": False,
        "omitted_boundary_rules": [],
        "omitted_priority_rules": [],
        "unsupported_rules": [],
        "confidence": 0.91,
        "verdict": "PASS",
        "explanation": "规则支持",
    }
    data.update(overrides)
    return VerificationDecision.model_validate(data)


def test_auto_accept_requires_two_confident_decisions() -> None:
    route, _ = route_annotation(annotation(), verifier(), 0.85)
    assert route == Route.auto_accept


def test_spec_gap_is_never_force_labeled() -> None:
    route, _ = route_annotation(
        annotation(spec_gap=True, missing_rule_reason="没有规定金融方案"), verifier(), 0.85
    )
    assert route == Route.spec_gap


def test_omitted_boundary_routes_to_review() -> None:
    route, reasons = route_annotation(annotation(), verifier(omitted_boundary_rules=["B001"]), 0.85)
    assert route == Route.review
    assert "Boundary" in reasons[0]

