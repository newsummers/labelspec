from __future__ import annotations

from collections import Counter
from typing import List

from .domain import CompiledStandard, ValidationIssue, ValidationReport


def validate_standard(standard: CompiledStandard) -> ValidationReport:
    issues: List[ValidationIssue] = []
    label_names = {item.name for item in standard.labels.labels}
    definition_labels = {rule.label for rule in standard.definition_rules}

    duplicate_definition_labels = [
        label for label, count in Counter(rule.label for rule in standard.definition_rules).items()
        if count > 1
    ]
    for label in duplicate_definition_labels:
        issues.append(
            ValidationIssue(
                code="DUPLICATE_DEFINITION",
                message=f"标签 {label} 存在多个 Definition Rule",
                path=label,
            )
        )

    all_rules = list(standard.definition_rules)
    all_rules.extend(standard.decision_rules.boundary_rules)
    all_rules.extend(standard.decision_rules.priority_rules)
    duplicate_ids = [rule_id for rule_id, count in Counter(r.rule_id for r in all_rules).items() if count > 1]
    for rule_id in duplicate_ids:
        issues.append(ValidationIssue(code="DUPLICATE_RULE_ID", message=f"Rule ID {rule_id} 重复", path=rule_id))

    for label in sorted(label_names - definition_labels):
        issues.append(
            ValidationIssue(
                code="MISSING_DEFINITION",
                message=f"标签 {label} 缺少 Definition Rule",
                path=label,
            )
        )
    for label in sorted(definition_labels - label_names):
        issues.append(
            ValidationIssue(
                code="UNKNOWN_LABEL",
                message=f"Definition Rule 引用了不存在的标签 {label}",
                path=label,
            )
        )
    for rule in standard.definition_rules:
        if not rule.include and not rule.positive_examples:
            issues.append(
                ValidationIssue(
                    code="WEAK_DEFINITION",
                    message=f"{rule.rule_id} 至少需要 include 或 positive_examples",
                    path=rule.rule_id,
                )
            )
    for rule in standard.decision_rules.boundary_rules:
        unknown = sorted(set(rule.labels) - label_names)
        if unknown:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_BOUNDARY_LABEL",
                    message=f"{rule.rule_id} 引用了不存在的标签: {', '.join(unknown)}",
                    path=rule.rule_id,
                )
            )

    return ValidationReport(valid=not any(i.severity == "error" for i in issues), issues=issues)
