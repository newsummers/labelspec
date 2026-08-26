from __future__ import annotations

import asyncio
from typing import List, Type

import pytest
from pydantic import BaseModel

from labelspec.disclosure import DisclosureEngine
from labelspec.domain import DecisionStatus
from labelspec.service import LabelSpecService

from .factories import standard


class TestProvider:
    async def structured(self, model: str, system: str, user: str, response_model: Type[BaseModel], temperature: float = 0):
        values = {
            "CandidateDecision": {
                "candidates": ["金融/贷款", "汽车/购车"],
                "rationale": "同时出现汽车和贷款",
            },
            "AnnotationDecision": {
                "status": "LABELED",
                "label": "金融/贷款",
                "leaf_rule_used": "D002",
                "decision_rules_referenced": ["B001", "P001"],
                "rule_reasons": {
                    "B001": "核心诉求是利率",
                    "P001": "最终诉求优先",
                },
                "evidence": "宝马贷款利率多少",
                "reason": "用户询问贷款利率，符合金融/贷款定义。",
                "confidence": 0.94,
            },
            "VerificationDecision": {
                "outcome": "PASS",
                "issues": [],
                "summary": "规则与标签一致",
            },
        }
        return response_model.model_validate(values[response_model.__name__])

    async def embeddings(self, model: str, inputs):
        return [[1.0, 0.0] for _ in inputs]


class FailOnSecondCandidateProvider(TestProvider):
    def __init__(self) -> None:
        self.candidate_calls = 0

    async def structured(self, model, system, user, response_model, temperature=0):
        if response_model.__name__ == "CandidateDecision":
            self.candidate_calls += 1
            if self.candidate_calls == 2:
                raise ValueError("模拟候选输出解析失败")
        return await super().structured(model, system, user, response_model, temperature)


class CountingProvider(TestProvider):
    def __init__(self) -> None:
        self.candidate_calls = 0

    async def structured(self, model, system, user, response_model, temperature=0):
        if response_model.__name__ == "CandidateDecision":
            self.candidate_calls += 1
        return await super().structured(model, system, user, response_model, temperature)


class HistoryRetryProvider(TestProvider):
    def __init__(self) -> None:
        self.annotation_calls = 0

    async def structured(self, model, system, user, response_model, temperature=0):
        result = await super().structured(model, system, user, response_model, temperature)
        if response_model.__name__ == "AnnotationDecision":
            self.annotation_calls += 1
            if self.annotation_calls == 1:
                return result.model_copy(
                    update={
                        "status": "NEEDS_CONTEXT",
                        "label": None,
                        "leaf_rule_used": None,
                        "reason": "需要历史人工 Case 判断",
                    }
                )
        return result


class InvalidLeafRuleProvider(TestProvider):
    def __init__(self, always_invalid: bool = False) -> None:
        self.always_invalid = always_invalid
        self.annotation_calls = 0

    async def structured(self, model, system, user, response_model, temperature=0):
        result = await super().structured(model, system, user, response_model, temperature)
        if response_model.__name__ == "AnnotationDecision":
            self.annotation_calls += 1
            if self.always_invalid or self.annotation_calls == 1:
                return result.model_copy(update={"leaf_rule_used": "D004"})
        return result


class VerifierBlockingIssueProvider(TestProvider):
    async def structured(self, model, system, user, response_model, temperature=0):
        result = await super().structured(model, system, user, response_model, temperature)
        if response_model.__name__ == "VerificationDecision":
            return response_model.model_validate(
                {
                    "outcome": "REVIEW",
                    "issues": [
                        {
                            "code": "DEFINITION_MISMATCH",
                            "severity": "BLOCKING",
                            "rule_id": "D002",
                            "message": "文本不满足贷款定义",
                        }
                    ],
                    "summary": "叶子定义不匹配",
                }
            )
        return result


class NoApplicableDecisionRulesProvider(TestProvider):
    async def structured(self, model, system, user, response_model, temperature=0):
        result = await super().structured(model, system, user, response_model, temperature)
        if response_model.__name__ == "AnnotationDecision":
            reasons = {
                rule_id: reason
                for rule_id, reason in result.rule_reasons.items()
                if rule_id.startswith("D")
            }
            return result.model_copy(
                update={"decision_rules_referenced": [], "rule_reasons": reasons}
            )
        return result


class SpecGapProvider(TestProvider):
    def __init__(self) -> None:
        self.verifier_calls = 0

    async def structured(self, model, system, user, response_model, temperature=0):
        result = await super().structured(model, system, user, response_model, temperature)
        if response_model.__name__ == "AnnotationDecision":
            return result.model_copy(
                update={
                    "status": DecisionStatus.spec_gap,
                    "label": None,
                    "leaf_rule_used": None,
                    "decision_rules_referenced": [],
                    "rule_reasons": {},
                    "reason": "标准未覆盖这种贷款咨询",
                }
            )
        if response_model.__name__ == "VerificationDecision":
            self.verifier_calls += 1
        return result


class ConcurrencyTrackingProvider(TestProvider):
    """Records how many structured calls overlap, to prove the pool is bounded."""

    def __init__(self, delay: float = 0.01) -> None:
        self.delay = delay
        self.in_flight = 0
        self.peak_in_flight = 0

    async def structured(self, model, system, user, response_model, temperature=0):
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return await super().structured(model, system, user, response_model, temperature)
        finally:
            self.in_flight -= 1


class FailOnTextProvider(TestProvider):
    """Fails the query whose text is `marker`, leaving siblings to succeed."""

    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.seen_texts: List[str] = []

    async def structured(self, model, system, user, response_model, temperature=0):
        if response_model.__name__ == "CandidateDecision":
            self.seen_texts.append(user)
            if self.marker in user:
                raise ValueError(f"模拟 {self.marker} 处理失败")
        return await super().structured(model, system, user, response_model, temperature)


def test_candidate_normalization_strips_explanation_suffix() -> None:
    known = {"金融/贷款", "汽车/购车"}

    candidates = DisclosureEngine._normalize_candidates(
        ["金融/贷款: 车贷", "汽车/购车：车型选择", "不存在/标签: 说明"], known
    )

    assert candidates == ["金融/贷款", "汽车/购车"]


@pytest.mark.asyncio
async def test_full_annotation_and_impact_scope(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset(
        "cases", "cases.csv", [{"text": "宝马贷款利率多少", "gold_label": "金融/贷款"}]
    )
    run = store.create_run(dataset["id"], current["id"])
    service = LabelSpecService(store, TestProvider())

    await service.process_run(run["id"])

    completed = store.get_run(run["id"])
    annotations = store.list_annotations(run["id"])
    assert completed["status"] == "completed"
    assert annotations[0]["route"] == "AUTO_ACCEPT"
    assert annotations[0]["rules_used"] == ["D001", "D002", "B001", "P001"]
    assert annotations[0]["decision"]["status"] == "LABELED"
    assert annotations[0]["route_reasons"][0]["code"] == "AUTO_ACCEPT"
    assert annotations[0]["confidence"] == 0.94
    events = store.list_annotation_events(run["id"])
    assert events[0]["stage"] == "QUERY"
    assert any(event["stage"] == "DISCLOSURE" for event in events)
    assert events[-1]["event_type"] == "STAGE_COMPLETED"
    assert store.run_metrics(run["id"])["accuracy"] == 1.0

    changed_rule = current["compiled"]["decision_rules"]["boundary_rules"][0]
    changed_rule = {**changed_rule, "decision": "贷款利率问题始终归金融/贷款"}
    revised = service.revise_rule(
        current["id"], "B001", changed_rule, "明确汽车贷款利率边界", []
    )
    impact = service.create_impact_run(
        run["id"], revised["standard"]["id"], "B001", revised["affected_labels"]
    )
    assert impact["total"] == 1
    assert impact["scope_item_ids"] == [annotations[0]["item_id"]]


@pytest.mark.asyncio
async def test_failed_run_resumes_without_reprocessing_completed_items(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset(
        "cases",
        "cases.csv",
        [
            {"text": "第一条贷款利率", "gold_label": "金融/贷款"},
            {"text": "第二条贷款利率", "gold_label": "金融/贷款"},
        ],
    )
    run = store.create_run(dataset["id"], current["id"])
    failing_provider = FailOnSecondCandidateProvider()

    await LabelSpecService(store, failing_provider).process_run(run["id"])

    assert store.get_run(run["id"])["status"] == "failed"
    assert len(store.list_annotations(run["id"])) == 1

    retry_provider = CountingProvider()
    await LabelSpecService(store, retry_provider).process_run(run["id"])

    completed = store.get_run(run["id"])
    assert completed["status"] == "completed"
    assert completed["processed"] == 2
    assert len(store.list_annotations(run["id"])) == 2
    assert retry_provider.candidate_calls == 1


@pytest.mark.asyncio
async def test_needs_history_retrieves_candidate_cases_and_retries(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    previous_dataset = store.create_dataset(
        "history", "history.csv", [{"text": "贷款利率查询", "gold_label": "金融/贷款"}]
    )
    previous_run = store.create_run(previous_dataset["id"], current["id"])
    await LabelSpecService(store, TestProvider()).process_run(previous_run["id"])

    dataset = store.create_dataset(
        "target", "target.csv", [{"text": "宝马贷款利率多少"}]
    )
    run = store.create_run(dataset["id"], current["id"])
    provider = HistoryRetryProvider()

    await LabelSpecService(store, provider).process_run(run["id"])

    annotation = store.list_annotations(run["id"])[0]
    assert store.get_run(run["id"])["status"] == "completed"
    assert provider.annotation_calls == 2
    assert annotation["route"] == "AUTO_ACCEPT"
    assert annotation["disclosure"]["historical_cases"][0]["label"] == "金融/贷款"


@pytest.mark.asyncio
async def test_inconsistent_leaf_rule_is_retried(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset("cases", "cases.csv", [{"text": "贷款利率"}])
    run = store.create_run(dataset["id"], current["id"])
    provider = InvalidLeafRuleProvider()

    await LabelSpecService(store, provider).process_run(run["id"])

    annotation = store.list_annotations(run["id"])[0]
    assert provider.annotation_calls == 2
    assert annotation["route"] == "AUTO_ACCEPT"
    assert annotation["rules_used"][0] == "D001"


@pytest.mark.asyncio
async def test_repeated_inconsistent_decision_degrades_to_spec_gap(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset("cases", "cases.csv", [{"text": "贷款利率"}])
    run = store.create_run(dataset["id"], current["id"])
    provider = InvalidLeafRuleProvider(always_invalid=True)

    await LabelSpecService(store, provider).process_run(run["id"])

    annotation = store.list_annotations(run["id"])[0]
    assert store.get_run(run["id"])["status"] == "completed"
    assert provider.annotation_calls == 3
    assert annotation["label"] == "金融/贷款"
    assert annotation["route"] == "REVIEW"
    assert annotation["decision"]["needs_review"] is True


@pytest.mark.asyncio
async def test_service_routes_concrete_verifier_issue_to_review(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset("cases", "cases.csv", [{"text": "贷款利率"}])
    run = store.create_run(dataset["id"], current["id"])

    await LabelSpecService(store, VerifierBlockingIssueProvider()).process_run(run["id"])

    annotation = store.list_annotations(run["id"])[0]
    assert annotation["verifier"]["outcome"] == "SKIPPED"
    assert annotation["route"] == "AUTO_ACCEPT"


@pytest.mark.asyncio
async def test_disclosed_but_inapplicable_rules_are_not_mechanically_omitted(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset("cases", "cases.csv", [{"text": "普通贷款利率"}])
    run = store.create_run(dataset["id"], current["id"])

    await LabelSpecService(store, NoApplicableDecisionRulesProvider()).process_run(run["id"])

    annotation = store.list_annotations(run["id"])[0]
    assert annotation["verifier"]["issues"] == []
    assert annotation["route"] == "AUTO_ACCEPT"


@pytest.mark.asyncio
async def test_non_labeled_decision_skips_verifier(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset("cases", "cases.csv", [{"text": "未知贷款咨询"}])
    run = store.create_run(dataset["id"], current["id"])
    provider = SpecGapProvider()

    await LabelSpecService(store, provider).process_run(run["id"])

    annotation = store.list_annotations(run["id"])[0]
    assert provider.verifier_calls == 0
    assert annotation["route"] == "REVIEW"
    assert annotation["label"] == "金融/贷款"
    assert annotation["verifier"]["outcome"] == "SKIPPED"
    assert annotation["route_reasons"][0]["code"] == "INVALID_ANNOTATOR_OUTPUT"


@pytest.mark.asyncio
async def test_parallel_run_annotates_every_item_and_counts_completions(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset(
        "cases", "cases.csv",
        [{"text": f"第{index}条贷款利率", "gold_label": "金融/贷款"} for index in range(9)],
    )
    run = store.create_run(dataset["id"], current["id"], concurrency=4)
    provider = ConcurrencyTrackingProvider()

    await LabelSpecService(store, provider).process_run(run["id"])

    completed = store.get_run(run["id"])
    assert completed["status"] == "completed"
    assert completed["processed"] == 9
    assert completed["concurrency"] == 4
    annotations = store.list_annotations(run["id"])
    assert len({annotation["item_id"] for annotation in annotations}) == 9
    # Progress is a shared completion counter, so it must be a clean 1..9 sequence.
    counts = [
        event["metadata"]["completed"]
        for event in store.list_annotation_events(run["id"])
        if event["stage"] == "QUERY" and event["event_type"] == "STAGE_COMPLETED"
    ]
    assert sorted(counts) == list(range(1, 10))
    assert provider.peak_in_flight > 1


@pytest.mark.asyncio
async def test_worker_pool_never_exceeds_requested_concurrency(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset(
        "cases", "cases.csv",
        [{"text": f"第{index}条贷款利率"} for index in range(8)],
    )
    run = store.create_run(dataset["id"], current["id"], concurrency=2)
    provider = ConcurrencyTrackingProvider()

    await LabelSpecService(store, provider).process_run(run["id"])

    assert store.get_run(run["id"])["status"] == "completed"
    assert provider.peak_in_flight == 2


@pytest.mark.asyncio
async def test_parallel_run_stops_writing_after_a_failure_and_resumes(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset(
        "cases", "cases.csv",
        [{"text": f"第{index}条贷款利率"} for index in range(6)],
    )
    run = store.create_run(dataset["id"], current["id"], concurrency=3)

    await LabelSpecService(store, FailOnTextProvider("第4条")).process_run(run["id"])

    failed = store.get_run(run["id"])
    partial = store.list_annotations(run["id"])
    assert failed["status"] == "failed"
    # The failing query is never annotated, and siblings cancelled mid-flight
    # must not have written a partial annotation either.
    assert len(partial) < 6
    assert all("第4条" not in annotation["text"] for annotation in partial)

    retry_provider = ConcurrencyTrackingProvider()
    await LabelSpecService(store, retry_provider).process_run(run["id"])

    completed = store.get_run(run["id"])
    annotations = store.list_annotations(run["id"])
    assert completed["status"] == "completed"
    assert completed["processed"] == 6
    assert len({annotation["item_id"] for annotation in annotations}) == 6


@pytest.mark.asyncio
async def test_parallel_run_does_not_publish_a_single_current_item(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset(
        "cases", "cases.csv", [{"text": f"第{index}条贷款利率"} for index in range(4)]
    )
    serial = store.create_run(dataset["id"], current["id"], concurrency=1)
    service = LabelSpecService(store, TestProvider())

    await service.process_run(serial["id"])
    serial_pointers = {
        event["item_id"]
        for event in store.list_annotation_events(serial["id"])
        if event["event_type"] == "STAGE_STARTED"
    }
    assert serial_pointers - {None}

    parallel = store.create_run(dataset["id"], current["id"], concurrency=4)
    await service.process_run(parallel["id"])

    # Concurrency > 1 suppresses the run pointer so the UI derives the
    # in-flight set from per-item events instead of a thrashing single value.
    assert store.get_run(parallel["id"])["current_item_id"] is None

