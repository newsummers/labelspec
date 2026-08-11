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


def test_standard_versions_are_immutable_snapshots(store) -> None:
    first = store.create_standard("source", standard(), status="draft")
    second = store.create_standard("source v2", standard(), parent_id=first["id"])
    assert first["version"] == 1
    assert second["version"] == 2
    assert second["parent_id"] == first["id"]
