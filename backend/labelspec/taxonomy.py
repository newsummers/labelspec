from __future__ import annotations

import copy
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .domain import CompiledStandard, DefinitionRule, LabelDefinition


def numeric_id(prefix: str, value: int) -> str:
    return f"{prefix}{value:03d}"


def next_numeric_id(values: Iterable[str], prefix: str) -> str:
    numbers = [
        int(value[len(prefix) :])
        for value in values
        if re.fullmatch(rf"{re.escape(prefix)}\d{{3,}}", value)
    ]
    return numeric_id(prefix, max(numbers, default=0) + 1)


def label_index(standard: CompiledStandard) -> Dict[str, LabelDefinition]:
    return {label.label_id: label for label in standard.labels.labels}


def children_index(standard: CompiledStandard) -> Dict[Optional[str], List[LabelDefinition]]:
    children: Dict[Optional[str], List[LabelDefinition]] = defaultdict(list)
    for label in standard.labels.labels:
        children[label.parent_id].append(label)
    return children


def leaf_ids(standard: CompiledStandard) -> Set[str]:
    parents = {label.parent_id for label in standard.labels.labels if label.parent_id}
    return {label.label_id for label in standard.labels.labels if label.label_id not in parents}


def ancestors(standard: CompiledStandard, label_id: str, include_self: bool = True) -> List[str]:
    by_id = label_index(standard)
    chain: List[str] = []
    current = label_id if include_self else by_id[label_id].parent_id
    seen: Set[str] = set()
    while current:
        if current in seen or current not in by_id:
            break
        seen.add(current)
        chain.append(current)
        current = by_id[current].parent_id
    return list(reversed(chain))


def descendants(standard: CompiledStandard, label_id: str, leaves_only: bool = False) -> Set[str]:
    children = children_index(standard)
    result: Set[str] = set()
    pending = [label_id]
    leaves = leaf_ids(standard)
    visited: Set[str] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        if not leaves_only or current in leaves:
            result.add(current)
        pending.extend(child.label_id for child in children.get(current, []))
    return result


def label_path(standard: CompiledStandard, label_id: str) -> str:
    by_id = label_index(standard)
    return "/".join(by_id[item].name for item in ancestors(standard, label_id))


def path_index(standard: CompiledStandard) -> Dict[str, str]:
    return {label_path(standard, label.label_id): label.label_id for label in standard.labels.labels}


def leaf_catalog(standard: CompiledStandard) -> List[Tuple[str, LabelDefinition]]:
    leaves = leaf_ids(standard)
    return [
        (label_path(standard, label.label_id), label)
        for label in standard.labels.labels
        if label.label_id in leaves
    ]


def effective_definitions(
    standard: CompiledStandard, candidate_label_ids: Sequence[str]
) -> List[DefinitionRule]:
    wanted: Set[str] = set()
    for label_id in candidate_label_ids:
        wanted.update(ancestors(standard, label_id))
    by_label = {rule.label_id: rule for rule in standard.definition_rules}
    return [
        by_label[label.label_id]
        for label in standard.labels.labels
        if label.label_id in wanted and label.label_id in by_label
    ]


def _legacy_paths(payload: Dict[str, Any]) -> List[Tuple[str, ...]]:
    paths: List[Tuple[str, ...]] = []
    for label in payload.get("labels", {}).get("labels", []):
        parts = tuple(part.strip() for part in str(label.get("name", "")).split("/") if part.strip())
        for depth in range(1, len(parts) + 1):
            path = parts[:depth]
            if path and path not in paths:
                paths.append(path)
    return paths


def upgrade_compiled_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Convert immutable v0.1 snapshots to the v0.2 tree shape on read/migration."""
    payload = copy.deepcopy(raw)
    # v0.2 initially exposed the same examples twice. Preserve old snapshots
    # while normalizing the public schema to Include (positive) and Exclude
    # (negative).
    for rule in payload.get("definition_rules", []):
        if rule.get("positive_examples"):
            rule["include"] = list(dict.fromkeys([
                *rule.get("include", []), *rule.get("positive_examples", [])
            ]))
        if rule.get("negative_examples"):
            rule["exclude"] = list(dict.fromkeys([
                *rule.get("exclude", []), *rule.get("negative_examples", [])
            ]))
        rule.pop("positive_examples", None)
        rule.pop("negative_examples", None)
    if payload.get("schema_version") == "0.2":
        return payload

    paths = _legacy_paths(payload)
    path_ids = {path: numeric_id("L", index) for index, path in enumerate(paths, start=1)}
    old_labels = {
        str(label.get("name", "")): label
        for label in payload.get("labels", {}).get("labels", [])
    }
    old_definitions = {
        str(rule.get("label", "")): rule
        for rule in payload.get("definition_rules", [])
    }
    used_definition_ids = {
        str(rule.get("rule_id")) for rule in payload.get("definition_rules", [])
    }
    next_definition = max(
        [int(value[1:]) for value in used_definition_ids if re.fullmatch(r"D\d{3,}", value)],
        default=0,
    ) + 1
    labels: List[Dict[str, Any]] = []
    definitions: List[Dict[str, Any]] = []
    for path in paths:
        full_path = "/".join(path)
        legacy_label = old_labels.get(full_path, {})
        labels.append(
            {
                "label_id": path_ids[path],
                "name": path[-1],
                "description": legacy_label.get("description") or f"{path[-1]}分类范围",
                "parent_id": path_ids.get(path[:-1]),
                "source_refs": [],
            }
        )
        legacy_rule = old_definitions.get(full_path)
        if legacy_rule:
            rule = {key: value for key, value in legacy_rule.items() if key != "label"}
            rule["label_id"] = path_ids[path]
            rule.setdefault("source_refs", [])
        else:
            child_names = [candidate[-1] for candidate in paths if len(candidate) == len(path) + 1 and candidate[:-1] == path]
            rule = {
                "rule_id": numeric_id("D", next_definition),
                "label_id": path_ids[path],
                "definition": legacy_label.get("description") or f"{path[-1]}分类范围",
                "include": child_names,
                "exclude": [],
                "source_refs": [],
            }
            next_definition += 1
        definitions.append(rule)

    boundaries = []
    for legacy in payload.get("decision_rules", {}).get("boundary_rules", []):
        label_ids = []
        for name in legacy.get("labels", []):
            path = tuple(part.strip() for part in str(name).split("/") if part.strip())
            if path in path_ids:
                label_ids.append(path_ids[path])
        boundaries.append(
            {
                "rule_id": legacy.get("rule_id"),
                "label_ids": label_ids,
                "scope_label_id": None,
                "condition": legacy.get("condition", ""),
                "decision": legacy.get("decision", ""),
                "source_refs": [],
            }
        )
    priorities = [
        {
            **rule,
            "scope_label_id": None,
            "source_refs": [],
        }
        for rule in payload.get("decision_rules", {}).get("priority_rules", [])
    ]
    return {
        "schema_version": "0.2",
        "name": payload.get("name", "Imported Standard"),
        "labels": {"labels": labels},
        "definition_rules": definitions,
        "decision_rules": {
            "boundary_rules": boundaries,
            "priority_rules": priorities,
        },
        "conflicts": [],
    }


def parse_compiled_standard(raw: Dict[str, Any]) -> CompiledStandard:
    return CompiledStandard.model_validate(upgrade_compiled_payload(raw))
