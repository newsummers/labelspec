import pytest

from labelspec.store import DatasetDeleteError, StandardDeleteError

from .factories import standard


def test_dataset_assigns_unique_internal_ids(store) -> None:
    dataset = store.create_dataset(
        "test", "test.csv", [{"text": "第一条"}, {"id": "source-1", "text": "第二条"}]
    )
    items = store.list_items(dataset["id"])
    assert len(items) == 2
    assert len({item["id"] for item in items}) == 2
    by_text = {item["text"]: item for item in items}
    assert by_text["第一条"]["source_id"] is None
    assert by_text["第二条"]["source_id"] == "source-1"


def test_dataset_can_be_deleted_before_annotation(store) -> None:
    dataset = store.create_dataset("test", "test.csv", [{"text": "一条数据"}])
    result = store.delete_dataset(dataset["id"])
    assert result["deleted_items"] == 1
    with pytest.raises(KeyError):
        store.get_dataset(dataset["id"])


def test_dataset_names_are_unique(store) -> None:
    store.create_dataset("同名数据", "one.csv", [{"text": "第一条"}])
    with pytest.raises(ValueError, match="已存在"):
        store.create_dataset("同名数据", "two.csv", [{"text": "第二条"}])


def test_dataset_delete_is_blocked_after_annotation_run(store) -> None:
    dataset = store.create_dataset("test", "test.csv", [{"text": "一条数据"}])
    saved = store.create_standard("source", standard(), status="archived")
    store.create_run(dataset["id"], saved["id"])
    with pytest.raises(DatasetDeleteError, match="标注运行"):
        store.delete_dataset(dataset["id"])


def test_standard_versions_are_immutable_snapshots(store) -> None:
    first = store.create_standard("source", standard(), status="draft")
    second = store.create_standard("source v2", standard(), parent_id=first["id"])
    assert first["version"] == 1
    assert second["version"] == 2
    assert second["parent_id"] == first["id"]


def test_delete_draft_standard_cleans_history_sources_and_empty_family(store) -> None:
    source = store.create_source_document("rules.md", "text/markdown", b"rules", "rules", {})
    saved = store.create_standard(
        "source", standard(), source_document_ids=[source["id"]],
        changes=[{"operation": "add", "entity_type": "standard", "after": {"name": "source"}}],
    )
    result = store.delete_standard(saved["id"])
    assert result["deleted_changes"] == 1
    assert result["deleted_source_documents"] == 1
    assert result["deleted_family"] is True
    with pytest.raises(KeyError):
        store.get_standard(saved["id"])
    with pytest.raises(KeyError):
        store.get_source_document(source["id"])


def test_delete_active_standard_is_blocked(store) -> None:
    saved = store.create_standard("source", standard(), status="active")
    with pytest.raises(StandardDeleteError, match="已激活"):
        store.delete_standard(saved["id"])


def test_delete_parent_with_child_is_blocked(store) -> None:
    parent = store.create_standard("source", standard())
    store.create_standard("source", standard(), parent_id=parent["id"])
    with pytest.raises(StandardDeleteError, match="父版本引用"):
        store.delete_standard(parent["id"])


def test_delete_standard_used_by_run_is_blocked(store) -> None:
    saved = store.create_standard("source", standard(), status="archived")
    dataset = store.create_dataset("data", "data.csv", [{"text": "一条数据"}])
    store.create_run(dataset["id"], saved["id"])
    with pytest.raises(StandardDeleteError, match="标注运行"):
        store.delete_standard(saved["id"])


def test_shared_source_is_retained_when_deleting_one_version(store) -> None:
    source = store.create_source_document("rules.md", "text/markdown", b"rules", "rules", {})
    first = store.create_standard("source", standard(), source_document_ids=[source["id"]])
    second = store.create_standard("source", standard(), source_document_ids=[source["id"]], parent_id=first["id"])
    result = store.delete_standard(second["id"])
    assert result["deleted_source_documents"] == 0
    assert store.get_source_document(source["id"])["id"] == source["id"]


def test_standard_source_roles_are_persisted(store) -> None:
    first = store.create_source_document("taxonomy.md", "text/markdown", b"taxonomy", "taxonomy", {})
    second = store.create_source_document("boundary.md", "text/markdown", b"boundary", "boundary", {})
    saved = store.create_standard(
        "source", standard(), source_document_ids=[first["id"], second["id"]],
        source_document_roles=["definition", "boundary"],
    )
    assert [item["role"] for item in saved["sources"]] == ["definition", "boundary"]


def test_legacy_annotation_payload_is_normalized_on_read(store) -> None:
    saved = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset("cases", "cases.csv", [{"text": "贷款利率"}])
    item = store.list_items(dataset["id"])[0]
    run = store.create_run(dataset["id"], saved["id"])

    annotation = store.save_annotation(
        run["id"],
        {
            "item_id": item["id"],
            "label": "金融/贷款",
            "candidates": ["金融/贷款"],
            "rules_used": ["D002"],
            "rule_reasons": {"D002": "符合贷款定义"},
            "evidence": "贷款利率",
            "confidence": 0.9,
            "route": "AUTO_ACCEPT",
            "route_reasons": ["历史自动通过"],
            "disclosure": {},
            "verifier": {
                "verdict": "PASS",
                "explanation": "历史核验通过",
                "confidence": 0.88,
            },
        },
    )

    assert annotation["route_reasons"] == [
        {"code": "LEGACY", "source": "ROUTER", "message": "历史自动通过"}
    ]
    assert annotation["verifier"]["outcome"] == "PASS"
    assert annotation["decision"]["status"] == "LABELED"
    assert annotation["decision"]["leaf_rule_used"] == "D002"


def test_trace_events_and_model_calls_are_persisted(store) -> None:
    saved = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset("trace-cases", "cases.csv", [{"text": "贷款利率"}])
    run = store.create_run(dataset["id"], saved["id"])

    started = store.save_annotation_event(
        run["id"], "item-1", "ANNOTATOR", "STAGE_STARTED", "running", "开始决策",
        model_role="annotator", model_id="test-model",
    )
    completed = store.save_annotation_event(
        run["id"], "item-1", "ANNOTATOR", "STAGE_COMPLETED", "success", "完成决策",
        duration_ms=123.4, model_role="annotator", model_id="test-model",
    )
    call = store.save_model_call(
        {
            "run_id": run["id"],
            "item_id": "item-1",
            "stage": "ANNOTATOR",
            "operation": "AnnotationDecision",
            "attempt": 1,
            "model_role": "annotator",
            "model_id": "test-model",
            "duration_ms": 123.4,
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "cached_input_tokens": 8,
            "status": "success",
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }
    )

    events = store.list_annotation_events(run["id"])
    calls = store.list_model_calls(run["id"], "item-1")
    assert [event["sequence"] for event in events] == [started["sequence"], completed["sequence"]]
    assert events[1]["duration_ms"] == 123.4
    assert calls[0]["total_tokens"] == 120
    assert calls[0]["usage"]["prompt_tokens"] == 100
    assert call["id"] == calls[0]["id"]
