from .factories import standard
from labelspec.validator import validate_standard


def test_valid_standard_passes() -> None:
    report = validate_standard(standard())
    assert report.valid
    assert report.issues == []


def test_missing_definition_is_reported() -> None:
    value = standard()
    value.definition_rules.pop()
    report = validate_standard(value)
    assert not report.valid
    assert any(issue.code == "MISSING_DEFINITION" for issue in report.issues)


def test_duplicate_definition_is_reported() -> None:
    value = standard()
    duplicate = value.definition_rules[0].model_copy(update={"rule_id": "D003"})
    value.definition_rules.append(duplicate)
    report = validate_standard(value)
    assert not report.valid
    assert any(issue.code == "DUPLICATE_DEFINITION" for issue in report.issues)
