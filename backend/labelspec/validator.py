from __future__ import annotations

from collections import Counter
from typing import List, Optional, Set, Tuple

from .domain import CompiledStandard, ValidationIssue, ValidationReport
from .taxonomy import descendants, label_path, leaf_ids


def validate_standard(standard: CompiledStandard) -> ValidationReport:
    issues: List[ValidationIssue] = []
    label_ids = {item.label_id for item in standard.labels.labels}
    labels_by_id = {item.label_id: item for item in standard.labels.labels}
    definition_labels = {rule.label_id for rule in standard.definition_rules}

    sibling_names: Counter[Tuple[Optional[str], str]] = Counter(
        (label.parent_id, label.name) for label in standard.labels.labels
    )
    for (parent_id, name), count in sibling_names.items():
        if count > 1:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_SIBLING_NAME",
                    message=f"同一父节点下存在重复标签名称 {name}",
                    path=parent_id or "root",
                )
            )

    for label in standard.labels.labels:
        if label.parent_id and label.parent_id not in label_ids:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_PARENT",
                    message=f"标签 {label.name} 的父节点 {label.parent_id} 不存在",
                    path=label.label_id,
                )
            )
        if label.parent_id == label.label_id:
            issues.append(
                ValidationIssue(
                    code="LABEL_CYCLE",
                    message=f"标签 {label.name} 不能以自身作为父节点",
                    path=label.label_id,
                )
            )

    for label in standard.labels.labels:
        seen: Set[str] = set()
        current = label.label_id
        while current in labels_by_id:
            if current in seen:
                issues.append(
                    ValidationIssue(
                        code="LABEL_CYCLE",
                        message=f"标签层级存在环: {label.name}",
                        path=label.label_id,
                    )
                )
                break
            seen.add(current)
            current = labels_by_id[current].parent_id or ""

    leaves = leaf_ids(standard)
    if len(leaves) < 2:
        issues.append(
            ValidationIssue(
                code="TOO_FEW_LEAVES",
                message="单标签分类标准至少需要两个叶子标签",
                path="labels",
            )
        )

    duplicate_definition_labels = [
        label for label, count in Counter(rule.label_id for rule in standard.definition_rules).items()
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

    for label in sorted(label_ids - definition_labels):
        issues.append(
            ValidationIssue(
                code="MISSING_DEFINITION",
                message=f"标签 {label_path(standard, label)} 缺少 Definition Rule",
                path=label,
            )
        )
    for label in sorted(definition_labels - label_ids):
        issues.append(
            ValidationIssue(
                code="UNKNOWN_LABEL",
                message=f"Definition Rule 引用了不存在的标签 {label}",
                path=label,
            )
        )
    for rule in standard.definition_rules:
        if not rule.include:
            issues.append(
                ValidationIssue(
                    code="WEAK_DEFINITION",
                    message=f"{rule.rule_id} 没有 Include（正例），建议人工检查",
                    path=rule.rule_id,
                    severity="warning",
                )
            )
    for rule in standard.decision_rules.boundary_rules:
        unknown = sorted(set(rule.label_ids) - label_ids)
        if unknown:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_BOUNDARY_LABEL",
                    message=f"{rule.rule_id} 引用了不存在的标签: {', '.join(unknown)}",
                    path=rule.rule_id,
                )
            )

        known_refs = [label_id for label_id in rule.label_ids if label_id in label_ids]
        for index, left in enumerate(known_refs):
            left_tree = descendants(standard, left)
            for right in known_refs[index + 1 :]:
                if right in left_tree or left in descendants(standard, right):
                    issues.append(
                        ValidationIssue(
                            code="OVERLAPPING_BOUNDARY_LABELS",
                            message=f"{rule.rule_id} 不能同时比较祖先和其后代标签",
                            path=rule.rule_id,
                        )
                    )
        if rule.scope_label_id and rule.scope_label_id not in label_ids:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_RULE_SCOPE",
                    message=f"{rule.rule_id} 的作用域标签不存在",
                    path=rule.rule_id,
                )
            )
        elif rule.scope_label_id:
            scope_nodes = descendants(standard, rule.scope_label_id)
            outside = [label_id for label_id in known_refs if label_id not in scope_nodes]
            if outside:
                issues.append(
                    ValidationIssue(
                        code="BOUNDARY_OUTSIDE_SCOPE",
                        message=f"{rule.rule_id} 引用了作用域之外的标签: {', '.join(outside)}",
                        path=rule.rule_id,
                    )
                )

    for rule in standard.decision_rules.priority_rules:
        if rule.scope_label_id and rule.scope_label_id not in label_ids:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_RULE_SCOPE",
                    message=f"{rule.rule_id} 的作用域标签不存在",
                    path=rule.rule_id,
                )
            )

    for conflict in standard.conflicts:
        if not conflict.resolved:
            issues.append(
                ValidationIssue(
                    code="SOURCE_CONFLICT",
                    message=conflict.message,
                    path=conflict.entity_key,
                )
            )

    return ValidationReport(valid=not any(i.severity == "error" for i in issues), issues=issues)
