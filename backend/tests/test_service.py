from __future__ import annotations

from typing import Type

import pytest
from pydantic import BaseModel

from labelspec.disclosure import DisclosureEngine
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
                "label": "金融/贷款",
                "leaf_rule_used": "D002",
                "path_rules_referenced": ["D001"],
                "decision_rules_referenced": ["B001", "P001"],
                "rule_reasons": {
                    "D002": "符合贷款定义",
                    "D001": "符合金融上位定义",
                    "B001": "核心诉求是利率",
                    "P001": "最终诉求优先",
                },
                "evidence": "用户询问贷款利率",
                "confidence": 0.94,
                "ambiguous": False,
                "spec_gap": False,
                "needs_history": False,
                "checks": {
                    "definition_matched": True,
                    "excludes_checked": True,
                    "alternatives_checked": True,
                    "boundaries_checked": True,
                    "priorities_checked": True,
                    "uniquely_decidable": True,
                },
            },
            "VerificationDecision": {
                "label_supported": True,
                "rules_exist": True,
                "definition_satisfied": True,
                "exclude_triggered": False,
                "omitted_boundary_rules": [],
                "omitted_priority_rules": [],
                "unsupported_rules": [],
                "confidence": 0.92,
                "verdict": "PASS",
                "explanation": "规则与标签一致",
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
                return result.model_copy(update={"needs_history": True})
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


class VerifierRejectsRuleProvider(TestProvider):
    async def structured(self, model, system, user, response_model, temperature=0):
        result = await super().structured(model, system, user, response_model, temperature)
        if response_model.__name__ == "VerificationDecision":
            return result.model_copy(update={"rules_exist": False})
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
    assert annotations[0]["rules_used"] == ["D002", "D001", "B001", "P001"]
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
    assert annotation["rules_used"][0] == "D002"


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
    assert annotation["label"] is None
    assert annotation["rules_used"] == []
    assert annotation["route"] == "SPEC_GAP"


@pytest.mark.asyncio
async def test_service_preserves_verifier_rules_exist_failure(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset("cases", "cases.csv", [{"text": "贷款利率"}])
    run = store.create_run(dataset["id"], current["id"])

    await LabelSpecService(store, VerifierRejectsRuleProvider()).process_run(run["id"])

    annotation = store.list_annotations(run["id"])[0]
    assert annotation["verifier"]["rules_exist"] is False
    assert annotation["route"] == "REVIEW"


@pytest.mark.asyncio
async def test_disclosed_but_inapplicable_rules_are_not_mechanically_omitted(store) -> None:
    current = store.create_standard("source", standard(), status="active")
    dataset = store.create_dataset("cases", "cases.csv", [{"text": "普通贷款利率"}])
    run = store.create_run(dataset["id"], current["id"])

    await LabelSpecService(store, NoApplicableDecisionRulesProvider()).process_run(run["id"])

    annotation = store.list_annotations(run["id"])[0]
    assert annotation["verifier"]["omitted_boundary_rules"] == []
    assert annotation["verifier"]["omitted_priority_rules"] == []
    assert annotation["route"] == "AUTO_ACCEPT"
