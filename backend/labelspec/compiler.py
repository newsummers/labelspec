from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field, field_validator

from .domain import (
    BoundaryRule,
    CompilationConflict,
    ConflictCandidate,
    CompiledStandard,
    DecisionRulesDocument,
    DefinitionRule,
    LabelDefinition,
    LabelsDocument,
    PriorityRule,
    SourceReference,
)
from .provider import QianfanProvider
from .taxonomy import label_path, numeric_id


COMPILER_SYSTEM = """你是 LabelSpec 分层标准抽取器。请从当前来源片段抽取事实，不要补写来源中没有的业务政策。

必须遵循：
1. 标签使用 path 表示完整层级，例如 ["金融", "贷款", "房贷"]。
2. 每个层级节点都必须单独输出一条 label；父节点写公共范围，子节点只写相对父节点新增的限定。
3. 同一个 path 只能出现一次。没有子节点的标签才是最终可分类标签。
4. 每个节点都要有 description、definition；include 是正例，exclude 是反例，原文没有时可以为空。
5. Boundary 可比较叶子或整个子树，label_paths 必须引用抽取出的路径；scope_path 是规则作用域，没有则为 null。
6. Priority 可以是全局规则，也可以通过 scope_path 限定到一个子树。
7. source_locator 填写原文标题、页码、Sheet 或表格位置，无法确定时填写当前片段位置。
8. 只抽取当前来源明确支持的内容。多个来源的合并和冲突判断由后续程序完成。
9. 只支持单标签文本分类，输出必须严格符合 JSON Schema。
"""


class ExtractedLabel(BaseModel):
    path: List[str] = Field(min_length=1)
    description: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    include: List[str] = Field(default_factory=list)
    exclude: List[str] = Field(default_factory=list)
    source_locator: str = ""

    @field_validator("path")
    @classmethod
    def clean_path(cls, value: List[str]) -> List[str]:
        cleaned = [part.strip() for part in value if part.strip()]
        if not cleaned:
            raise ValueError("标签路径不能为空")
        return cleaned


class ExtractedBoundary(BaseModel):
    label_paths: List[List[str]] = Field(min_length=2)
    scope_path: Optional[List[str]] = None
    condition: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    source_locator: str = ""


class ExtractedPriority(BaseModel):
    principle: str = Field(min_length=1)
    scope_path: Optional[List[str]] = None
    source_locator: str = ""


class ExtractedFragment(BaseModel):
    labels: List[ExtractedLabel] = Field(default_factory=list)
    boundary_rules: List[ExtractedBoundary] = Field(default_factory=list)
    priority_rules: List[ExtractedPriority] = Field(default_factory=list)


@dataclass(frozen=True)
class CompilerSource:
    document_id: str
    filename: str
    text: str
    role: str = "auto"


@dataclass(frozen=True)
class ExtractedSourceFragment:
    source: CompilerSource
    locator: str
    fragment: ExtractedFragment


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _merge_unique(left: List[str], right: Iterable[str]) -> List[str]:
    seen = {_normalized(value) for value in left}
    for value in right:
        if _normalized(value) not in seen:
            left.append(value)
            seen.add(_normalized(value))
    return left


def _source_ref(source: CompilerSource, locator: str) -> SourceReference:
    return SourceReference(
        document_id=source.document_id,
        filename=source.filename,
        locator=locator,
    )


def _split_examples(value: str) -> List[str]:
    value = re.sub(r"\([^)]*归[^)]*\)", "", value)
    return [item.strip(" \t-；;，,") for item in re.split(r"[；;\n]+", value) if item.strip(" \t-；;，,")]


def _field_value(lines: Sequence[str], field_names: Sequence[str]) -> str:
    pattern = re.compile(r"^\*\*(?:" + "|".join(field_names) + r")：?\*\*\s*(.*)$")
    for line in lines:
        value = pattern.match(line.strip())
        if value:
            return value.group(1).strip()
        for name in field_names:
            value = re.match(rf"^(?:-\s*)?{re.escape(name)}：?\s*(.*)$", line.strip(), re.I)
            if value:
                return value.group(1).strip()
    return ""


def _definition_summary(definition: str) -> str:
    definition = re.sub(r"\s+", " ", definition).strip()
    if not definition:
        return "分类范围"
    first = re.split(r"(?<=[。！？.!?])", definition, maxsplit=1)[0].strip()
    return first[:180] if first else definition[:180]


def _parse_markdown_units(source: CompilerSource) -> Optional[List[ExtractedSourceFragment]]:
    """Parse the repository's explicit L1/L2/L3/L4 Markdown format.

    A structured document has one heading per category and explicit 所属/定义
    fields. In that case the program owns taxonomy paths and the model is not
    allowed to invent duplicate labels.
    """
    lines = source.text.splitlines()
    heading_re = re.compile(r"^(#{3,6})\s+(.+?)\s*$")
    headings = [(index, len(mark.group(1)), mark.group(2).strip()) for index, line in enumerate(lines) if (mark := heading_re.match(line))]
    if len(headings) < 2:
        return None
    units: List[ExtractedLabel] = []
    for position, (start, level, title) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        block = lines[start + 1 : end]
        l1 = _field_value(block, ["所属 L1", "所属L1"])
        l2 = _field_value(block, ["所属 L2", "所属L2"])
        l3 = _field_value(block, ["所属 L3", "所属L3"])
        l4 = _field_value(block, ["所属 L4", "所属L4"])
        if l4:
            path = [l1, l2, l3, l4, title]
        elif l3:
            path = [l1, l2, l3, title]
        elif l2:
            path = [l1, l2, title]
        elif l1:
            path = [l1, title]
        elif "L1" in title or "L2" in title or "L3" in title or "L4" in title:
            continue
        else:
            # The first section uses headings as root labels and has no 所属 field.
            path = [title] if position == 0 or any("L1" in lines[i] for i in range(start) if lines[i].startswith("##")) else []
        path = [part.strip() for part in path if part.strip()]
        definition = _field_value(block, ["定义", "Definition"])
        if not path or not definition:
            continue
        include = _split_examples(_field_value(block, ["正例", "Include", "包含"]))
        exclude = _split_examples(_field_value(block, ["反例", "Exclude", "排除"]))
        locator = f"{source.filename}, 第 {start + 1} 行, {title}"
        units.append(
            ExtractedLabel(
                path=path,
                description=_definition_summary(definition),
                definition=definition,
                include=include,
                exclude=exclude,
                source_locator=locator,
            )
        )
    if len(units) < 2 or len(units) < len(headings) * 0.5:
        return None
    return [ExtractedSourceFragment(source=source, locator="结构化 Markdown", fragment=ExtractedFragment(labels=units))]


def _split_text(text: str, max_chars: int = 24000) -> List[Tuple[str, str]]:
    if len(text) <= max_chars:
        return [("全文", text)]
    chunks: List[str] = []
    current: List[str] = []
    current_size = 0
    for line in text.splitlines():
        line_size = len(line) + 1
        if current and current_size + line_size > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_size = 0
        if line_size > max_chars:
            for start in range(0, len(line), max_chars):
                piece = line[start : start + max_chars]
                if current:
                    chunks.append("\n".join(current))
                    current = []
                    current_size = 0
                chunks.append(piece)
            continue
        current.append(line)
        current_size += line_size
    if current:
        chunks.append("\n".join(current))
    return [(f"片段 {index}/{len(chunks)}", chunk) for index, chunk in enumerate(chunks, start=1)]


async def _extract_sources(
    provider: QianfanProvider, model: str, sources: Sequence[CompilerSource]
) -> List[ExtractedSourceFragment]:
    semaphore = asyncio.Semaphore(4)

    async def extract(source: CompilerSource, locator: str, text: str) -> ExtractedSourceFragment:
        async with semaphore:
            role_instruction = {
                "boundary": "本来源是混淆边界规则文档。只抽取 boundary_rules；labels、definition、include、exclude 必须为空。文档中出现的标签路径只能作为引用。",
                "priority": "本来源是优先级规则文档。只抽取 priority_rules；labels、definition、include、exclude、boundary_rules 必须为空。",
                "definition": "本来源是分类定义文档。只抽取 labels 及其 definition、include、exclude；不要从本来源生成 boundary_rules 或 priority_rules。",
            }.get(source.role, "本来源角色自动识别，按文档内容抽取适用的标签和规则。")
            fragment = await provider.structured(
                model=model,
                system=f"{COMPILER_SYSTEM}\n\n{role_instruction}",
                user=f"来源文件：{source.filename}\n位置：{locator}\n角色：{source.role}\n\n---\n{text}\n---",
                response_model=ExtractedFragment,
                temperature=0.05,
            )
            if source.role == "boundary":
                fragment = fragment.model_copy(update={"labels": [], "priority_rules": []})
            elif source.role == "priority":
                fragment = fragment.model_copy(update={"labels": [], "boundary_rules": []})
            elif source.role == "definition":
                fragment = fragment.model_copy(update={"boundary_rules": [], "priority_rules": []})
            return ExtractedSourceFragment(source=source, locator=locator, fragment=fragment)

    structured: List[ExtractedSourceFragment] = []
    calls = []
    for source in sources:
        parsed = _parse_markdown_units(source) if source.role in {"auto", "definition"} and source.filename.lower().endswith(".md") else None
        if parsed:
            if source.role == "definition":
                parsed = [item for item in parsed]
            structured.extend(parsed)
        else:
            calls.extend(
                extract(source, locator, text)
                for locator, text in _split_text(source.text)
            )
    if not calls:
        return structured
    extracted = list(await asyncio.gather(*calls))
    return [*structured, *extracted]


def _next_rule_number(rules: Iterable[object], prefix: str) -> int:
    values = []
    for rule in rules:
        rule_id = getattr(rule, "rule_id", "")
        if re.fullmatch(rf"{prefix}\d{{3,}}", rule_id):
            values.append(int(rule_id[1:]))
    return max(values, default=0) + 1


def _merge_fragments(
    name: str,
    fragments: Sequence[ExtractedSourceFragment],
    base: Optional[CompiledStandard],
) -> CompiledStandard:
    nodes: Dict[Tuple[str, ...], Dict[str, object]] = {}
    conflicts: List[CompilationConflict] = []

    def add_conflict(
        kind: str,
        key: str,
        message: str,
        refs: List[SourceReference],
        candidates: Optional[List[ConflictCandidate]] = None,
    ) -> None:
        unique_refs = {
            (ref.document_id, ref.filename, ref.locator): ref for ref in refs
        }
        conflicts.append(
            CompilationConflict(
                conflict_id=f"C{len(conflicts) + 1:03d}",
                kind=kind,
                entity_key=key,
                message=message,
                source_refs=list(unique_refs.values()),
                candidates=candidates or [],
            )
        )

    if base:
        definitions = {rule.label_id: rule for rule in base.definition_rules}
        for label in base.labels.labels:
            path = tuple(label_path(base, label.label_id).split("/"))
            rule = definitions[label.label_id]
            nodes[path] = {
                "label_id": label.label_id,
                "rule_id": rule.rule_id,
                "description": label.description,
                "definition": rule.definition,
                "include": list(rule.include),
                "exclude": list(rule.exclude),
                "label_refs": list(label.source_refs),
                "rule_refs": list(rule.source_refs),
                "from_base": True,
            }

    for extracted in fragments:
        for label in extracted.fragment.labels:
            path = tuple(label.path)
            locator = label.source_locator or extracted.locator
            ref = _source_ref(extracted.source, locator)
            existing = nodes.get(path)
            if not existing:
                nodes[path] = {
                    "label_id": None,
                    "rule_id": None,
                    "description": label.description,
                    "definition": label.definition,
                    "include": list(label.include),
                    "exclude": list(label.exclude),
                    "label_refs": [ref],
                    "rule_refs": [ref],
                    "from_base": False,
                }
                continue
            refs = [*existing["rule_refs"], ref]  # type: ignore[list-item]
            source_ids = {item.document_id for item in refs}  # type: ignore[union-attr]
            if len(source_ids) > 1 and _normalized(str(existing["definition"])) != _normalized(label.definition):
                add_conflict(
                    "definition",
                    "/".join(path),
                    f"多个来源对 {'/'.join(path)} 的 Definition 描述不一致，请人工确认",
                    refs,
                )
            if len(source_ids) > 1 and _normalized(str(existing["description"])) != _normalized(label.description):
                add_conflict(
                    "description",
                    "/".join(path),
                    f"多个来源对 {'/'.join(path)} 的简述不一致，请人工确认",
                    refs,
                )
            for field in ("include", "exclude"):
                _merge_unique(existing[field], getattr(label, field))  # type: ignore[arg-type]
            include_values = {_normalized(value) for value in existing["include"]}  # type: ignore[union-attr]
            exclude_values = {_normalized(value) for value in existing["exclude"]}  # type: ignore[union-attr]
            overlap = sorted(include_values & exclude_values)
            if overlap:
                add_conflict(
                    "include_exclude_overlap",
                    "/".join(path),
                    f"{ '/'.join(path) } 的 Include 与 Exclude 存在相同示例，请人工确认",
                    refs,
                )
            existing["label_refs"] = [*existing["label_refs"], ref]  # type: ignore[list-item]
            existing["rule_refs"] = refs

    for path in list(nodes):
        for depth in range(1, len(path)):
            parent = path[:depth]
            if parent in nodes:
                continue
            child_ref = list(nodes[path]["rule_refs"])[0]  # type: ignore[arg-type]
            nodes[parent] = {
                "label_id": None,
                "rule_id": None,
                "description": f"{parent[-1]}分类范围",
                "definition": f"涵盖 {parent[-1]} 下的业务类别",
                "include": [path[depth]],
                "exclude": [],
                "label_refs": [child_ref],
                "rule_refs": [child_ref],
                "from_base": False,
            }
            add_conflict(
                "missing_parent_definition",
                "/".join(parent),
                f"来源使用了层级 {'/'.join(path)}，但没有给父节点 {'/'.join(parent)} 独立定义",
                [child_ref],
            )

    ordered_paths = sorted(nodes, key=lambda path: (len(path), list(nodes).index(path)))
    used_label_numbers = [
        int(str(node["label_id"])[1:])
        for node in nodes.values()
        if re.fullmatch(r"L\d{3,}", str(node["label_id"]))
    ]
    next_label = max(used_label_numbers, default=0) + 1
    path_ids: Dict[Tuple[str, ...], str] = {}
    for path in ordered_paths:
        value = nodes[path]["label_id"]
        if not value:
            value = numeric_id("L", next_label)
            next_label += 1
        path_ids[path] = str(value)

    base_definitions = base.definition_rules if base else []
    next_definition = _next_rule_number(base_definitions, "D")
    labels: List[LabelDefinition] = []
    definitions_out: List[DefinitionRule] = []
    for path in ordered_paths:
        node = nodes[path]
        label_id = path_ids[path]
        rule_id = node["rule_id"]
        if not rule_id:
            rule_id = numeric_id("D", next_definition)
            next_definition += 1
        labels.append(
            LabelDefinition(
                label_id=label_id,
                name=path[-1],
                description=str(node["description"]),
                parent_id=path_ids.get(path[:-1]),
                source_refs=node["label_refs"],
            )
        )
        definitions_out.append(
            DefinitionRule(
                rule_id=str(rule_id),
                label_id=label_id,
                definition=str(node["definition"]),
                include=node["include"],
                exclude=node["exclude"],
                source_refs=node["rule_refs"],
            )
        )

    boundaries: List[BoundaryRule] = list(base.decision_rules.boundary_rules) if base else []
    boundary_keys = {
        (tuple(sorted(rule.label_ids)), rule.scope_label_id): rule for rule in boundaries
    }
    next_boundary = _next_rule_number(boundaries, "B")
    priorities: List[PriorityRule] = list(base.decision_rules.priority_rules) if base else []
    next_priority = _next_rule_number(priorities, "P")

    for extracted in fragments:
        for rule in extracted.fragment.boundary_rules:
            paths = [tuple(part.strip() for part in path if part.strip()) for path in rule.label_paths]
            if any(path not in path_ids for path in paths):
                add_conflict(
                    "unknown_boundary_label",
                    " | ".join("/".join(path) for path in paths),
                    "Boundary Rule 引用了当前标签树中不存在的路径",
                    [_source_ref(extracted.source, rule.source_locator or extracted.locator)],
                )
                continue
            scope_path = tuple(rule.scope_path or [])
            ref = _source_ref(extracted.source, rule.source_locator or extracted.locator)
            if scope_path and scope_path not in path_ids:
                add_conflict(
                    "unknown_boundary_scope",
                    "/".join(scope_path),
                    "Boundary Rule 的作用域不在当前标签树中",
                    [ref],
                )
                continue
            scope_id = path_ids.get(scope_path) if scope_path else None
            ids = [path_ids[path] for path in paths]
            key = (tuple(sorted(ids)), scope_id)
            existing = boundary_keys.get(key)
            if existing:
                if (
                    _normalized(existing.condition) != _normalized(rule.condition)
                    or _normalized(existing.decision) != _normalized(rule.decision)
                ):
                    add_conflict(
                        "boundary",
                        " | ".join("/".join(path) for path in paths),
                        "多个来源对同一组标签的 Boundary Rule 不一致，请人工确认",
                        [*existing.source_refs, ref],
                        candidates=[
                            ConflictCandidate(
                                rule_id=existing.rule_id,
                                label_ids=list(existing.label_ids),
                                scope_label_id=existing.scope_label_id,
                                condition=existing.condition,
                                decision=existing.decision,
                                source_refs=list(existing.source_refs),
                            ),
                            ConflictCandidate(
                                label_ids=ids,
                                scope_label_id=scope_id,
                                condition=rule.condition,
                                decision=rule.decision,
                                source_refs=[ref],
                            ),
                        ],
                    )
                continue
            value = BoundaryRule(
                rule_id=numeric_id("B", next_boundary),
                label_ids=ids,
                scope_label_id=scope_id,
                condition=rule.condition,
                decision=rule.decision,
                source_refs=[ref],
            )
            next_boundary += 1
            boundaries.append(value)
            boundary_keys[key] = value

        for rule in extracted.fragment.priority_rules:
            scope_path = tuple(rule.scope_path or [])
            if scope_path and scope_path not in path_ids:
                add_conflict(
                    "unknown_priority_scope",
                    "/".join(scope_path),
                    "Priority Rule 的作用域不在当前标签树中",
                    [_source_ref(extracted.source, rule.source_locator or extracted.locator)],
                )
                continue
            scope_id = path_ids.get(scope_path) if scope_path else None
            if any(
                existing.scope_label_id == scope_id
                and _normalized(existing.principle) == _normalized(rule.principle)
                for existing in priorities
            ):
                continue
            priorities.append(
                PriorityRule(
                    rule_id=numeric_id("P", next_priority),
                    principle=rule.principle,
                    scope_label_id=scope_id,
                    source_refs=[_source_ref(extracted.source, rule.source_locator or extracted.locator)],
                )
            )
            next_priority += 1

    return CompiledStandard(
        name=name,
        labels=LabelsDocument(labels=labels),
        definition_rules=definitions_out,
        decision_rules=DecisionRulesDocument(
            boundary_rules=boundaries,
            priority_rules=priorities,
        ),
        conflicts=conflicts,
    )


async def compile_sources(
    provider: QianfanProvider,
    model: str,
    name: str,
    sources: Sequence[CompilerSource],
    base: Optional[CompiledStandard] = None,
) -> CompiledStandard:
    if not sources:
        raise ValueError("至少需要一份标准文档")
    fragments = await _extract_sources(provider, model, sources)
    return _merge_fragments(name, fragments, base)


async def compile_standard(
    provider: QianfanProvider, model: str, name: str, source_markdown: str
) -> CompiledStandard:
    return await compile_sources(
        provider,
        model,
        name,
        [CompilerSource(document_id="inline", filename="standard.md", text=source_markdown.strip())],
    )
