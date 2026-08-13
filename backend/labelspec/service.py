from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional, Tuple

from .annotator import annotate
from .compiler import CompilerSource, compile_sources
from .disclosure import DisclosureEngine
from .domain import AnnotationResult, CompiledStandard
from .documents import ParsedDocument, parse_standard_document
from .provider import QianfanProvider
from .router import route_annotation
from .store import Store, utc_now
from .taxonomy import descendants, label_path, parse_compiled_standard, upgrade_compiled_payload
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
        document = parse_standard_document(
            "standard.md", "text/markdown", source_markdown.encode("utf-8")
        )
        return await self.compile_documents(name, [document])

    async def compile_documents(
        self,
        name: str,
        documents: List[ParsedDocument],
        base_standard_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        settings = self.store.get_settings()
        base_row = self.store.get_standard(base_standard_id) if base_standard_id else None
        base = parse_compiled_standard(base_row["compiled"]) if base_row else None
        if base_row and base_row["name"] != name:
            raise ValueError("补充文档时标准名称必须与原版本一致")

        stored_documents = [
            self.store.create_source_document(
                document.filename,
                document.media_type,
                document.raw_content,
                document.extracted_text,
                document.metadata,
            )
            for document in documents
        ]
        role_by_document_id = {
            stored["id"]: source.role for stored, source in zip(stored_documents, documents)
        }
        sources = [
            CompilerSource(
                document_id=document["id"],
                filename=document["filename"],
                text=document["extracted_text"],
                role=role_by_document_id[document["id"]],
            )
            for document in stored_documents
        ]
        standard = await compile_sources(
            self.provider, settings.compiler_model, name, sources, base=base
        )
        report = validate_standard(standard)
        previous_source_ids = [source["id"] for source in base_row.get("sources", [])] if base_row else []
        source_ids = list(dict.fromkeys([*previous_source_ids, *[item["id"] for item in stored_documents]]))
        previous_roles = {
            source["id"]: source.get("role", "auto")
            for source in (base_row or {}).get("sources", [])
        }
        source_roles = [role_by_document_id.get(source_id, previous_roles.get(source_id, "auto")) for source_id in source_ids]
        source_texts = []
        for source_id in source_ids:
            source = self.store.get_source_document(source_id)
            source_texts.append(f"# Source: {source['filename']}\n\n{source['extracted_text']}")
        changes = self._diff_standard(base, standard) if base else [
            {
                "operation": "add",
                "entity_type": "standard",
                "entity_id": None,
                "before": None,
                "after": standard.model_dump(mode="json"),
            }
        ]
        for document in stored_documents:
            if document["id"] not in previous_source_ids:
                changes.append(
                    {
                        "operation": "add",
                        "entity_type": "document",
                        "entity_id": document["id"],
                        "before": None,
                        "after": {"filename": document["filename"], "sha256": document["sha256"]},
                    }
                )
        saved = self.store.create_standard(
            "\n\n---\n\n".join(source_texts),
            standard,
            status="draft",
            parent_id=base_standard_id,
            family_id=base_row["family_id"] if base_row else None,
            source_document_ids=source_ids,
            source_document_roles=source_roles,
            changes=changes,
            change_summary="补充标准文档" if base_row else "从标准文档编译",
            origin="document_import",
        )
        return {
            "standard": saved,
            "validation": report.model_dump(mode="json"),
            "files": standard_to_yaml_files(standard),
        }

    async def process_run(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        standard = parse_compiled_standard(
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

    @staticmethod
    def _entity_maps(standard: CompiledStandard) -> Dict[str, Dict[str, Dict[str, Any]]]:
        return {
            "label": {item.label_id: item.model_dump(mode="json") for item in standard.labels.labels},
            "definition": {item.rule_id: item.model_dump(mode="json") for item in standard.definition_rules},
            "boundary": {
                item.rule_id: item.model_dump(mode="json")
                for item in standard.decision_rules.boundary_rules
            },
            "priority": {
                item.rule_id: item.model_dump(mode="json")
                for item in standard.decision_rules.priority_rules
            },
        }

    @classmethod
    def _diff_standard(
        cls, before: Optional[CompiledStandard], after: CompiledStandard
    ) -> List[Dict[str, Any]]:
        if not before:
            return []
        changes: List[Dict[str, Any]] = []
        before_maps = cls._entity_maps(before)
        after_maps = cls._entity_maps(after)
        for entity_type in ("label", "definition", "boundary", "priority"):
            old = before_maps[entity_type]
            new = after_maps[entity_type]
            for entity_id in sorted(old.keys() - new.keys()):
                changes.append({
                    "operation": "delete", "entity_type": entity_type,
                    "entity_id": entity_id, "before": old[entity_id], "after": None,
                })
            for entity_id in sorted(new.keys() - old.keys()):
                changes.append({
                    "operation": "add", "entity_type": entity_type,
                    "entity_id": entity_id, "before": None, "after": new[entity_id],
                })
            for entity_id in sorted(old.keys() & new.keys()):
                if old[entity_id] == new[entity_id]:
                    continue
                operation = "update"
                if entity_type == "label" and old[entity_id].get("parent_id") != new[entity_id].get("parent_id"):
                    operation = "move"
                changes.append({
                    "operation": operation, "entity_type": entity_type,
                    "entity_id": entity_id, "before": old[entity_id], "after": new[entity_id],
                })
        return changes

    def create_manual_version(
        self,
        standard_id: str,
        compiled: Dict[str, Any],
        reason: str,
        resolve_conflicts: bool = False,
    ) -> Dict[str, Any]:
        current = self.store.get_standard(standard_id)
        before = parse_compiled_standard(current["compiled"])
        payload = upgrade_compiled_payload(copy.deepcopy(compiled))
        payload["name"] = current["name"]
        payload["schema_version"] = "0.2"
        payload["conflicts"] = (
            []
            if resolve_conflicts
            else [conflict.model_dump(mode="json") for conflict in before.conflicts]
        )
        revised = CompiledStandard.model_validate(payload)
        report = validate_standard(revised)
        changes = self._diff_standard(before, revised)
        if resolve_conflicts and before.conflicts:
            changes.append(
                {
                    "operation": "update",
                    "entity_type": "conflicts",
                    "entity_id": None,
                    "before": [item.model_dump(mode="json") for item in before.conflicts],
                    "after": [],
                }
            )
        if not changes:
            raise ValueError("标准内容没有变化")
        saved = self.store.create_standard(
            current["source_markdown"], revised, status="draft", parent_id=standard_id,
            family_id=current["family_id"],
            source_document_ids=[source["id"] for source in current.get("sources", [])],
            source_document_roles=[source.get("role", "auto") for source in current.get("sources", [])],
            changes=changes, change_summary=reason.strip() or "手动编辑标准", origin="manual",
        )
        return {
            "standard": saved,
            "validation": report.model_dump(mode="json"),
            "files": standard_to_yaml_files(revised),
        }

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
        result = self.create_manual_version(standard_id, compiled, reason)
        saved = result["standard"]
        self.store.record_rule_change(
            standard_id,
            saved["id"],
            rule_id,
            before,
            new_rule,
            reason,
            related_case_ids,
        )
        return {"standard": saved, "affected_labels": labels, "validation": result["validation"]}

    @staticmethod
    def _find_rule(compiled: Dict[str, Any], rule_id: str) -> Tuple[Dict[str, Any], List[str]]:
        for rule in compiled["definition_rules"]:
            if rule["rule_id"] == rule_id:
                standard = parse_compiled_standard(compiled)
                affected = descendants(standard, rule["label_id"], leaves_only=True)
                return rule, [label_path(standard, label_id) for label_id in sorted(affected)]
        for rule in compiled["decision_rules"]["boundary_rules"]:
            if rule["rule_id"] == rule_id:
                standard = parse_compiled_standard(compiled)
                affected = set()
                for label_id in rule["label_ids"]:
                    affected.update(descendants(standard, label_id, leaves_only=True))
                return rule, [label_path(standard, label_id) for label_id in sorted(affected)]
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
