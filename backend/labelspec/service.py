from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional, Tuple

from .annotator import annotate
from .compiler import compile_standard
from .disclosure import DisclosureEngine
from .domain import AnnotationResult, CompiledStandard
from .provider import QianfanProvider
from .router import route_annotation
from .store import Store, utc_now
from .validator import validate_standard
from .verifier import verify
from .yaml_io import standard_to_yaml_files

logger = logging.getLogger(__name__)


class LabelSpecService:
    def __init__(self, store: Store, provider: QianfanProvider):
        self.store = store
        self.provider = provider
        self.disclosure = DisclosureEngine(provider, store)

    async def compile(self, name: str, source_markdown: str) -> Dict[str, Any]:
        settings = self.store.get_settings()
        standard = await compile_standard(
            self.provider, settings.compiler_model, name, source_markdown
        )
        report = validate_standard(standard)
        saved = self.store.create_standard(source_markdown, standard, status="draft")
        return {
            "standard": saved,
            "validation": report.model_dump(),
            "files": standard_to_yaml_files(standard),
        }

    async def process_run(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        standard = CompiledStandard.model_validate(
            self.store.get_standard(run["standard_id"])["compiled"]
        )
        report = validate_standard(standard)
        if not report.valid:
            self.store.update_run(run_id, status="failed", error="当前 Standard 校验未通过")
            return
        settings = self.store.get_settings()
        items = self.store.list_items(run["dataset_id"], run.get("scope_item_ids"))
        completed_item_ids = {
            annotation["item_id"] for annotation in self.store.list_annotations(run_id)
        }
        pending_items = [item for item in items if item["id"] not in completed_item_ids]
        completed_count = len(completed_item_ids)
        self.store.update_run(
            run_id,
            status="running",
            processed=completed_count,
            error=None,
            completed_at=None,
        )
        try:
            for index, item in enumerate(pending_items, start=completed_count + 1):
                trace = await self.disclosure.disclose(
                    text=item["text"],
                    item_id=item["id"],
                    standard=standard,
                    model=settings.annotator_model,
                    embedding_model=settings.embedding_model,
                )
                decision = await annotate(
                    self.provider, settings.annotator_model, item["text"], trace
                )
                if decision.needs_history:
                    trace.historical_cases = await self.disclosure.retrieve_history(
                        item["text"], item["id"], settings.embedding_model
                    )
                    decision = await annotate(
                        self.provider, settings.annotator_model, item["text"], trace
                    )
                verification = await verify(
                    self.provider, settings.verifier_model, item["text"], trace, decision
                )
                known_rule_ids = {
                    rule.rule_id for rule in [
                        *trace.definitions,
                        *trace.boundaries,
                        *trace.global_priority_rules,
                    ]
                }
                unsupported = sorted(set(decision.rules_used) - known_rule_ids)
                verification.unsupported_rules = sorted(
                    set(verification.unsupported_rules).union(unsupported)
                )
                verification.rules_exist = not verification.unsupported_rules
                used = set(decision.rules_used)
                verification.omitted_boundary_rules = sorted(
                    set(verification.omitted_boundary_rules).union(
                        rule.rule_id for rule in trace.boundaries if rule.rule_id not in used
                    )
                )
                verification.omitted_priority_rules = sorted(
                    set(verification.omitted_priority_rules).union(
                        rule.rule_id
                        for rule in trace.global_priority_rules
                        if rule.rule_id not in used
                    )
                )
                route, reasons = route_annotation(
                    decision, verification, settings.auto_accept_threshold
                )
                result = AnnotationResult(
                    item_id=item["id"],
                    text=item["text"],
                    label=decision.label,
                    candidates=trace.candidates,
                    rules_used=decision.rules_used,
                    rule_reasons=decision.rule_reasons,
                    evidence=decision.evidence,
                    confidence=min(decision.confidence, verification.confidence),
                    route=route,
                    route_reasons=reasons,
                    disclosure=trace,
                    verifier=verification,
                )
                self.store.save_annotation(run_id, result.model_dump(mode="json"))
                self.store.update_run(run_id, processed=index)
            self.store.update_run(run_id, status="completed", completed_at=utc_now())
        except Exception as exc:
            logger.exception("Annotation run %s failed", run_id)
            self.store.update_run(run_id, status="failed", error=str(exc), completed_at=utc_now())

    def revise_rule(
        self,
        standard_id: str,
        rule_id: str,
        new_rule: Dict[str, Any],
        reason: str,
        related_case_ids: List[str],
    ) -> Dict[str, Any]:
        current = self.store.get_standard(standard_id)
        compiled = copy.deepcopy(current["compiled"])
        target, labels = self._find_rule(compiled, rule_id)
        if new_rule.get("rule_id") != rule_id:
            raise ValueError("修改后的 Rule 必须保留原 rule_id")
        before = copy.deepcopy(target)
        target.clear()
        target.update(new_rule)
        revised = CompiledStandard.model_validate(compiled)
        report = validate_standard(revised)
        if not report.valid:
            raise ValueError("Rule 修改导致 Standard 校验失败: " + "; ".join(i.message for i in report.issues))
        source = current["source_markdown"] + (
            f"\n\n<!-- LabelSpec revision: {rule_id} -->\n"
            f"## Rule revision {rule_id}\n\nReason: {reason}\n"
        )
        saved = self.store.create_standard(
            source_markdown=source,
            standard=revised,
            status="draft",
            parent_id=standard_id,
            change_summary=f"{rule_id}: {reason}",
        )
        activated = self.store.activate_standard(saved["id"])
        self.store.record_rule_change(
            standard_id,
            activated["id"],
            rule_id,
            before,
            new_rule,
            reason,
            related_case_ids,
        )
        return {"standard": activated, "affected_labels": labels, "validation": report.model_dump()}

    @staticmethod
    def _find_rule(compiled: Dict[str, Any], rule_id: str) -> Tuple[Dict[str, Any], List[str]]:
        for rule in compiled["definition_rules"]:
            if rule["rule_id"] == rule_id:
                return rule, [rule["label"]]
        for rule in compiled["decision_rules"]["boundary_rules"]:
            if rule["rule_id"] == rule_id:
                return rule, list(rule["labels"])
        for rule in compiled["decision_rules"]["priority_rules"]:
            if rule["rule_id"] == rule_id:
                return rule, []
        raise KeyError(f"Rule {rule_id} 不存在")

    def create_impact_run(
        self,
        source_run_id: str,
        target_standard_id: str,
        rule_id: str,
        labels: List[str],
    ) -> Dict[str, Any]:
        source = self.store.get_run(source_run_id)
        item_ids = self.store.affected_item_ids(source_run_id, rule_id, labels)
        return self.store.create_run(
            dataset_id=source["dataset_id"],
            standard_id=target_standard_id,
            scope_item_ids=item_ids,
            parent_run_id=source_run_id,
        )
