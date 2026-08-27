from __future__ import annotations

from typing import Type

import pytest
from pydantic import BaseModel

from labelspec.compiler import CompilerSource, _parse_markdown_units, compile_sources
from labelspec.domain import CompilationConflict
from labelspec.service import LabelSpecService
from labelspec.taxonomy import leaf_catalog, parse_compiled_standard

from .factories import standard


def test_structured_markdown_parser_owns_paths_and_examples() -> None:
    source = CompilerSource(
        "doc-1",
        "standard.md",
        """# 测试\n\n## L1\n\n### 信息获取\n\n**定义：** 获取已有信息。\n\n**正例：** 查天气；查价格\n\n**反例：** 写文章\n\n### 科学常数\n\n**所属 L1：** 信息获取\n**所属 L2：** 事实与数据\n**所属 L3：** 客观事实\n\n**定义：** 查询固定科学常数。\n\n**正例：** 光速是多少；圆周率是多少\n\n**反例：** 为什么光速是极限。\n""",
    )
    parsed = _parse_markdown_units(source)
    assert parsed is not None
    labels = parsed[0].fragment.labels
    constant = next(item for item in labels if item.path[-1] == "科学常数")
    assert constant.path == ["信息获取", "事实与数据", "客观事实", "科学常数"]
    assert constant.include == ["光速是多少", "圆周率是多少"]
    assert constant.exclude == ["为什么光速是极限。"]


@pytest.mark.asyncio
async def test_structured_markdown_compile_does_not_call_model() -> None:
    class NoCallProvider:
        async def structured(self, *args, **kwargs):
            raise AssertionError("structured Markdown should not call the extraction model")

    source = CompilerSource(
        "doc-1",
        "standard.md",
        """# 测试\n## L1\n### A\n**定义：** A范围。\n**正例：** a\n**反例：** b\n### B\n**定义：** B范围。\n**正例：** b\n**反例：** a\n""",
    )
    compiled = await compile_sources(NoCallProvider(), "model", "测试", [source])
    assert len(compiled.labels.labels) == 2
    assert len(compiled.definition_rules) == 2
    assert not compiled.conflicts


class FragmentProvider:
    async def structured(
        self,
        model: str,
        system: str,
        user: str,
        response_model: Type[BaseModel],
        temperature: float = 0,
    ) -> BaseModel:
        if "one.md" in user:
            payload = {
                "labels": [
                    {"path": ["金融"], "description": "金融范围", "definition": "金融服务"},
                    {"path": ["金融", "贷款"], "description": "贷款", "definition": "借贷服务", "include": ["利率"]},
                ]
            }
        else:
            payload = {
                "labels": [
                    {"path": ["金融"], "description": "金融业务范围", "definition": "金融类业务"},
                    {"path": ["汽车"], "description": "汽车范围", "definition": "汽车服务"},
                    {"path": ["汽车", "购车"], "description": "购车", "definition": "车辆购买", "include": ["车型"]},
                ]
            }
        return response_model.model_validate(payload)


@pytest.mark.asyncio
async def test_multi_source_compile_builds_tree_and_reports_conflicts() -> None:
    compiled = await compile_sources(
        FragmentProvider(),
        "test-model",
        "层级标准",
        [
            CompilerSource("doc-1", "one.md", "first"),
            CompilerSource("doc-2", "two.md", "second"),
        ],
    )
    assert [path for path, _ in leaf_catalog(compiled)] == ["金融/贷款", "汽车/购车"]
    assert any(conflict.kind == "definition" for conflict in compiled.conflicts)
    loan = next(rule for rule in compiled.definition_rules if rule.definition == "借贷服务")
    assert loan.source_refs[0].document_id == "doc-1"


@pytest.mark.asyncio
async def test_boundary_conflict_contains_both_rule_candidates() -> None:
    class Provider:
        async def structured(self, model, system, user, response_model, temperature=0):
            condition = "新条件" if "来源文件：next" in user else "旧条件"
            return response_model.model_validate({
                "labels": [
                    {"path": ["A"], "description": "A", "definition": "A"},
                    {"path": ["B"], "description": "B", "definition": "B"},
                ],
                "boundary_rules": [{"label_paths": [["A"], ["B"]], "condition": condition, "decision": "B"}],
            })

    base = await compile_sources(Provider(), "model", "测试", [CompilerSource("base", "base", "x")])
    conflict = await compile_sources(Provider(), "model", "测试", [CompilerSource("next", "next", "x")], base=base)
    assert conflict.conflicts
    assert len(conflict.conflicts[0].candidates) == 2


@pytest.mark.asyncio
async def test_boundary_source_cannot_create_definition_conflicts() -> None:
    class BoundaryProvider:
        async def structured(self, model, system, user, response_model, temperature=0):
            if "混淆边界" in user:
                return response_model.model_validate({
                    "labels": [{"path": ["金融"], "description": "错误定义", "definition": "错误定义"}],
                    "boundary_rules": [{
                        "label_paths": [["金融", "贷款"], ["汽车", "购车"]],
                        "condition": "同时出现", "decision": "按核心诉求",
                    }],
                })
            return response_model.model_validate({
                "labels": [
                    {"path": ["金融"], "description": "金融", "definition": "金融范围"},
                    {"path": ["金融", "贷款"], "description": "贷款", "definition": "贷款范围"},
                    {"path": ["汽车"], "description": "汽车", "definition": "汽车范围"},
                    {"path": ["汽车", "购车"], "description": "购车", "definition": "购车范围"},
                ]
            })

    compiled = await compile_sources(
        BoundaryProvider(), "model", "测试", [
            CompilerSource("definition", "分类标准.txt", "定义", role="definition"),
            CompilerSource("boundary", "混淆边界规则.txt", "边界", role="boundary"),
        ]
    )
    assert not [item for item in compiled.conflicts if item.kind in {"definition", "description"}]
    assert len(compiled.decision_rules.boundary_rules) == 1


def test_manual_edit_creates_draft_version_and_change_log(store) -> None:
    first = store.create_standard("source", standard(), status="active")
    service = LabelSpecService(store, FragmentProvider())
    payload = first["compiled"]
    payload["labels"]["labels"][1]["description"] = "个人及企业贷款"

    result = service.create_manual_version(first["id"], payload, "扩展贷款描述")

    second = result["standard"]
    assert second["version"] == 2
    assert second["status"] == "draft"
    assert second["family_id"] == first["family_id"]
    changes = store.list_standard_changes(second["id"])
    assert any(
        change["operation"] == "update"
        and change["entity_type"] == "label"
        and change["entity_id"] == "L002"
        for change in changes
    )


def test_rule_patch_creates_successor_without_overwriting_parent(store) -> None:
    first = store.create_standard("source", standard(), status="active")
    patch = store.save_rule_patch(
        first["id"],
        {
            "reason": "补充贷款展期定义",
            "operations": [{
                "action": "update",
                "rule_type": "definition",
                "rule_id": "D002",
                "after": {
                    **first["compiled"]["definition_rules"][1],
                    "definition": "借款、利率、额度、还款、展期等贷款诉求",
                },
            }],
        },
        [],
    )
    store.update_rule_patch_status(patch["id"], "approved")
    service = LabelSpecService(store, FragmentProvider())
    result = service.apply_rule_patch(patch["id"])

    second = result["standard"]
    assert second["version"] == first["version"] + 1
    assert second["parent_id"] == first["id"]
    assert second["status"] == "draft"
    assert store.get_standard(first["id"])["status"] == "active"
    assert store.get_standard(first["id"])["compiled"]["definition_rules"][1]["definition"] != second["compiled"]["definition_rules"][1]["definition"]


def test_manual_edit_keeps_conflicts_until_explicitly_resolved(store) -> None:
    value = standard()
    value.conflicts = [
        CompilationConflict(
            conflict_id="C001",
            kind="definition",
            entity_key="金融/贷款",
            message="两个来源的贷款定义不一致",
            source_refs=[],
            resolved=False,
        )
    ]
    first = store.create_standard("source", value, status="draft")
    service = LabelSpecService(store, FragmentProvider())
    payload = first["compiled"]
    payload["labels"]["labels"][1]["description"] = "人工确认后的贷款描述"

    retained = service.create_manual_version(first["id"], payload, "先修改描述")
    resolved = service.create_manual_version(
        first["id"],
        store.get_standard(first["id"])["compiled"],
        "确认并解决来源冲突",
        resolve_conflicts=True,
    )

    assert not retained["validation"]["valid"]
    assert retained["standard"]["compiled"]["conflicts"]
    assert resolved["validation"]["valid"]
    assert resolved["standard"]["compiled"]["conflicts"] == []


def test_v01_payload_is_upgraded_to_variable_depth_leaves() -> None:
    compiled = parse_compiled_standard(
        {
            "name": "legacy",
            "labels": {"labels": [
                {"name": "A/A1", "description": "A1"},
                {"name": "A/A2/A21", "description": "A21"},
                {"name": "B", "description": "B"},
            ]},
            "definition_rules": [
                {"rule_id": "D001", "label": "A/A1", "definition": "A1", "include": ["a1"]},
                {"rule_id": "D002", "label": "A/A2/A21", "definition": "A21", "include": ["a21"]},
                {"rule_id": "D003", "label": "B", "definition": "B", "include": ["b"]},
            ],
            "decision_rules": {"boundary_rules": [], "priority_rules": []},
        }
    )
    assert [path for path, _ in leaf_catalog(compiled)] == ["A/A1", "A/A2/A21", "B"]


def test_legacy_positive_negative_examples_are_normalized() -> None:
    compiled = parse_compiled_standard(
        {
            "schema_version": "0.2",
            "name": "legacy-v02",
            "labels": {"labels": [{"label_id": "L001", "name": "A", "description": "A"}]},
            "definition_rules": [{
                "rule_id": "D001", "label_id": "L001", "definition": "A",
                "include": ["已有正例"], "exclude": ["已有反例"],
                "positive_examples": ["旧正例", "已有正例"],
                "negative_examples": ["旧反例", "已有反例"],
            }],
            "decision_rules": {"boundary_rules": [], "priority_rules": []},
        }
    )
    rule = compiled.definition_rules[0]
    assert rule.include == ["已有正例", "旧正例"]
    assert rule.exclude == ["已有反例", "旧反例"]
