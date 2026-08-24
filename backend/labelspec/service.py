from __future__ import annotations

import copy
import json
import logging
import time
from contextlib import asynccontextmanager, nullcontext
from typing import Any, Dict, List, Optional, Tuple

from .annotator import annotate
from .compiler import CompilerSource, compile_sources
from .disclosure import DisclosureEngine
from .domain import (
    AnnotationDecision,
    AnnotationResult,
    CompiledStandard,
    DecisionStatus,
    DisclosureTrace,
)
from .documents import ParsedDocument, parse_standard_document
from .provider import QianfanProvider
from .router import route_annotation
from .store import Store, utc_now
from .taxonomy import descendants, label_path, parse_compiled_standard, upgrade_compiled_payload
from .validator import validate_standard
from .yaml_io import standard_to_yaml_files

logger = logging.getLogger(__name__)


class LabelSpecService:
    def __init__(self, store: Store, provider: QianfanProvider):
        self.store = store
        self.provider = provider
        self.disclosure = DisclosureEngine(provider, store)
        set_observer = getattr(provider, "set_call_observer", None)
        if set_observer:
            set_observer(self.record_model_call)

    async def record_model_call(self, record: Dict[str, Any]) -> None:
        """Persist provider metrics and mirror completion into the live trace."""
        run_id = record.get("run_id")
        if not run_id:
            return
        saved = self.store.save_model_call(record)
        usage = {
            key: saved.get(key)
            for key in (
                "input_tokens", "output_tokens", "total_tokens",
                "cached_input_tokens", "reasoning_tokens",
            )
        }
        await self._emit_event(
            run_id=run_id,
            item_id=record.get("item_id"),
            stage=record.get("stage", "UNKNOWN"),
            event_type="MODEL_CALL_COMPLETED",
            status=record.get("status", "success"),
            message=(
                f"{record.get('operation', 'model')} "
                f"{'完成' if record.get('status') == 'success' else '失败'}"
            ),
            duration_ms=record.get("duration_ms"),
            model_role=record.get("model_role"),
            model_id=record.get("model_id"),
            metadata={
                "attempt": record.get("attempt", 1),
                "model_call_id": saved.get("id"),
                "operation": record.get("operation"),
                "request_id": record.get("request_id"),
                "usage": usage,
                "error": record.get("error"),
            },
        )

    async def _emit_event(
        self,
        run_id: str,
        item_id: Optional[str],
        stage: str,
        event_type: str,
        status: str,
        message: str,
        duration_ms: Optional[float] = None,
        model_role: Optional[str] = None,
        model_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        event = self.store.save_annotation_event(
            run_id=run_id,
            item_id=item_id,
            stage=stage,
            event_type=event_type,
            status=status,
            message=message,
            duration_ms=duration_ms,
            model_role=model_role,
            model_id=model_id,
            metadata=metadata,
        )
        if event_type in {"STAGE_STARTED", "MODEL_CALL_COMPLETED"}:
            self.store.update_run(
                run_id,
                current_item_id=item_id,
                current_stage=stage,
            )
        return event

    def _provider_context(self, **values: Any):
        context = getattr(self.provider, "telemetry_context", None)
        return context(**values) if context else nullcontext()

    @asynccontextmanager
    async def _trace_stage(
        self,
        run_id: str,
        item_id: str,
        stage: str,
        message: str,
        model_role: Optional[str] = None,
        model_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        started = time.perf_counter()
        await self._emit_event(
            run_id, item_id, stage, "STAGE_STARTED", "running", message,
            model_role=model_role, model_id=model_id, metadata=metadata,
        )
        try:
            with self._provider_context(
                run_id=run_id,
                item_id=item_id,
                stage=stage,
                model_role=model_role,
            ):
                yield
        except Exception as exc:
            await self._emit_event(
                run_id, item_id, stage, "STAGE_FAILED", "error", str(exc),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                model_role=model_role, model_id=model_id,
            )
            raise
        else:
            await self._emit_event(
                run_id, item_id, stage, "STAGE_COMPLETED", "success", message,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                model_role=model_role, model_id=model_id, metadata=metadata,
            )

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
                await self._emit_event(
                    run_id, item["id"], "QUERY", "STAGE_STARTED", "running",
                    f"开始处理第 {index}/{len(items)} 条 query",
                    metadata={"index": index, "total": len(items)},
                )
                async with self._trace_stage(
                    run_id, item["id"], "DISCLOSURE", "候选召回开始",
                    model_role="annotator", model_id=settings.annotator_model,
                ):
                    trace = await self.disclosure.disclose(
                        text=item["text"],
                        item_id=item["id"],
                        standard=standard,
                        model=settings.annotator_model,
                        embedding_model=settings.embedding_model,
                    )
                async with self._trace_stage(
                    run_id, item["id"], "ANNOTATOR", "Annotator 开始决策",
                    model_role="annotator", model_id=settings.annotator_model,
                ):
                    try:
                        decision = await annotate(
                            self.provider, settings.annotator_model, item["text"], trace
                        )
                    except Exception as exc:
                        decision = self._fallback_decision(trace, f"Annotator 输出无法解析：{exc}")
                # Legacy models may still request historical context. New
                # annotators express this as needs_review and do not retry.
                if decision.status == DecisionStatus.needs_context:
                    historical_cases = await self.disclosure.retrieve_history(
                        item["text"], item["id"], trace.candidates,
                        settings.embedding_model,
                    )
                    if historical_cases:
                        trace.historical_cases = historical_cases
                        try:
                            decision = await annotate(
                                self.provider, settings.annotator_model, item["text"], trace
                            )
                        except Exception as exc:
                            decision = self._fallback_decision(trace, f"历史 Case 重试输出无法解析：{exc}")
                try:
                    decision = AnnotationDecision.model_validate(decision.model_dump())
                except Exception as exc:
                    decision = self._fallback_decision(trace, f"Annotator 输出不符合结构：{exc}")
                if decision.status != DecisionStatus.labeled:
                    decision = decision.model_copy(update={
                        "status": DecisionStatus.labeled,
                        "needs_review": True,
                        "review_reason_codes": list(dict.fromkeys([
                            *decision.review_reason_codes, decision.status.value
                        ])),
                        "reason": (
                            decision.reason
                            + f"（模型标记为 {decision.status.value}，因此需要人工确认。）"
                        ),
                    })
                async with self._trace_stage(
                    run_id, item["id"], "ANNOTATOR_VALIDATE", "校验 Annotator 输出一致性",
                    model_role="annotator", model_id=settings.annotator_model,
                ):
                    decision = await self._ensure_valid_decision(
                        settings.annotator_model, item["text"], trace, decision
                    )
                known_rule_ids = {
                    rule.rule_id
                    for chain in trace.definitions
                    for rule in chain.chain
                } | {
                    rule.rule_id for rule in [*trace.boundaries, *trace.global_priority_rules]
                }
                unsupported = sorted(set(decision.rules_used) - known_rule_ids)
                if unsupported:
                    decision = decision.model_copy(update={
                        "decision_rules_referenced": [
                            rule_id for rule_id in decision.decision_rules_referenced
                            if rule_id in known_rule_ids
                        ],
                        "needs_review": True,
                        "review_reason_codes": list(dict.fromkeys([
                            *decision.review_reason_codes, "INVALID_RULE_REFERENCE"
                        ])),
                        "reason": (
                            f"模型引用了未披露的规则 {', '.join(unsupported)}，"
                            "标签仍然来自合法候选，但需要人工确认。"
                        ),
                        "status": DecisionStatus.labeled,
                    })
                selected_chain = next(
                    (chain for chain in trace.definitions if chain.leaf_path == decision.label),
                    None,
                )
                if selected_chain is None:
                    # This should only be reachable after a malformed model
                    # response. _ensure_valid_decision chooses the first legal
                    # candidate, but keep a final guard before persistence.
                    selected_chain = trace.definitions[0] if trace.definitions else None
                    if selected_chain is None:
                        raise ValueError("Disclosure 未返回任何合法叶子标签")
                    decision = decision.model_copy(update={
                        "status": DecisionStatus.labeled,
                        "label": selected_chain.leaf_path,
                        "leaf_rule_used": selected_chain.chain[-1].rule_id,
                        "needs_review": True,
                        "review_reason_codes": list(dict.fromkeys([
                            *decision.review_reason_codes, "INVALID_LABEL"
                        ])),
                        "reason": "模型标签不在合法候选范围内，系统选择第一个合法候选，需人工确认。",
                        "confidence": 0.0,
                    })
                definition_rules = [
                    rule.rule_id for rule in selected_chain.chain
                ]
                rules_used = list(
                    dict.fromkeys([*definition_rules, *decision.decision_rules_referenced])
                )
                if decision.needs_review or decision.confidence < settings.auto_accept_threshold:
                    decision = self._attach_review_evidence(
                        decision,
                        selected_chain,
                        trace,
                        low_confidence=decision.confidence < settings.auto_accept_threshold,
                    )
                async with self._trace_stage(
                    run_id, item["id"], "ROUTER", "根据标签合法性和审核信号路由",
                ):
                    route, reasons = route_annotation(
                        decision, threshold=settings.auto_accept_threshold
                    )
                result = AnnotationResult(
                    item_id=item["id"],
                    text=item["text"],
                    label=decision.label,
                    candidates=trace.candidates,
                    rules_used=rules_used,
                    rule_reasons=decision.rule_reasons,
                    evidence=decision.evidence,
                    confidence=decision.confidence,
                    route=route,
                    route_reasons=reasons,
                    decision=decision,
                    disclosure=trace,
                )
                async with self._trace_stage(
                    run_id, item["id"], "PERSIST", "保存 query 标注结果",
                ):
                    self.store.save_annotation(run_id, result.model_dump(mode="json"))
                self.store.update_run(run_id, processed=index)
                await self._emit_event(
                    run_id, item["id"], "QUERY", "STAGE_COMPLETED", "success",
                    f"第 {index}/{len(items)} 条 query 处理完成",
                    metadata={"index": index, "total": len(items), "route": route.value},
                )
            await self._emit_event(
                run_id, None, "RUN", "STAGE_COMPLETED", "success", "标注运行完成",
                metadata={"processed": len(items), "total": len(items)},
            )
            self.store.update_run(
                run_id, status="completed", processed=len(items),
                current_item_id=None, current_stage="COMPLETED",
                completed_at=utc_now(),
            )
        except Exception as exc:
            logger.exception("Annotation run %s failed", run_id)
            await self._emit_event(
                run_id, None, "RUN", "STAGE_FAILED", "error", str(exc),
            )
            self.store.update_run(
                run_id, status="failed", current_stage="FAILED",
                error=str(exc), completed_at=utc_now(),
            )

    async def _ensure_valid_decision(
        self,
        model: str,
        text: str,
        trace: DisclosureTrace,
        decision: AnnotationDecision,
        max_attempts: int = 3,
    ) -> AnnotationDecision:
        errors = self._decision_errors(trace, decision)
        for attempt in range(1, max_attempts):
            if not errors:
                return decision
            logger.warning(
                "Annotator 第 %d 次输出不一致：%s，重试",
                attempt,
                "；".join(errors),
            )
            valid_options = {
                chain.leaf_path: {
                    "leaf_rule_used": chain.chain[-1].rule_id if chain.chain else None,
                }
                for chain in trace.definitions
            }
            correction = (
                "上一次输出存在以下问题："
                + "；".join(errors)
                + "。请重新输出。合法标签及对应 Definition Rule 如下：\n"
                + json.dumps(valid_options, ensure_ascii=False)
            )
            try:
                decision = await annotate(
                    self.provider, model, text, trace, correction=correction
                )
            except Exception as exc:
                decision = self._fallback_decision(trace, f"Annotator 重试输出无法解析：{exc}")
                errors = self._decision_errors(trace, decision)
                break
            errors = self._decision_errors(trace, decision)
        if not errors:
            return decision
        logger.warning(
            "Annotator 连续 %d 次输出不一致：%s，选择合法候选并转 REVIEW",
            max_attempts,
            "；".join(errors),
        )
        if not trace.definitions:
            raise ValueError("Disclosure 未返回任何合法叶子标签")
        fallback = trace.definitions[0]
        return decision.model_copy(
            update={
                "status": DecisionStatus.labeled,
                "label": fallback.leaf_path,
                "leaf_rule_used": fallback.chain[-1].rule_id,
                "decision_rules_referenced": [],
                "rule_reasons": {},
                "confidence": 0.0,
                "needs_review": True,
                "review_reason_codes": list(dict.fromkeys([
                    *decision.review_reason_codes, "INVALID_ANNOTATOR_OUTPUT"
                ])),
                "reason": (
                    f"{decision.reason.strip()} "
                    f"模型连续 {max_attempts} 次输出不符合标签约束（{'；'.join(errors)}），"
                    f"系统选择合法候选“{fallback.leaf_path}”，需要人工确认。"
                ),
            }
        )

    @staticmethod
    def _fallback_decision(trace: DisclosureTrace, message: str) -> AnnotationDecision:
        if not trace.definitions:
            raise ValueError("Disclosure 未返回任何合法叶子标签")
        fallback = trace.definitions[0]
        return AnnotationDecision.model_construct(
            status=DecisionStatus.labeled,
            label=fallback.leaf_path,
            leaf_rule_used=fallback.chain[-1].rule_id,
            decision_rules_referenced=[],
            rule_reasons={},
            evidence="系统从候选叶子中选择了合法标签，原始模型输出无法解析。",
            reason=f"{message}；系统选择合法候选“{fallback.leaf_path}”，需要人工确认。",
            confidence=0.0,
            needs_review=True,
            review_reason_codes=["INVALID_ANNOTATOR_OUTPUT"],
            evidence_items=[],
        )

    @staticmethod
    def _attach_review_evidence(
        decision: AnnotationDecision,
        selected_chain: Any,
        trace: DisclosureTrace,
        low_confidence: bool = False,
    ) -> AnnotationDecision:
        items = list(decision.evidence_items)
        seen = {(item.get("type"), item.get("rule_id")) for item in items if isinstance(item, dict)}
        for rule in selected_chain.chain:
            key = ("definition", rule.rule_id)
            if key not in seen:
                items.append({
                    "type": "definition",
                    "rule_id": rule.rule_id,
                    "rule_text": rule.definition,
                    "explanation": f"候选标签路径中的第 {rule.rule_id} 层定义",
                })
        referenced = set(decision.decision_rules_referenced)
        for rule in [*trace.boundaries, *trace.global_priority_rules]:
            if rule.rule_id not in referenced:
                continue
            kind = "boundary" if rule in trace.boundaries else "priority"
            key = (kind, rule.rule_id)
            if key in seen:
                continue
            text = getattr(rule, "condition", None) or getattr(rule, "principle", "")
            if getattr(rule, "decision", None):
                text = f"{text}；结论：{rule.decision}"
            items.append({
                "type": kind,
                "rule_id": rule.rule_id,
                "rule_text": text,
                "explanation": decision.rule_reasons.get(rule.rule_id, "该规则参与当前结论"),
            })
        rule_text = "；".join(
            f"{item.get('rule_id')}: {item.get('rule_text')}"
            for item in items if item.get("rule_id")
        )
        reason = decision.reason.strip()
        if decision.evidence.strip() not in reason:
            reason += f" 原文证据：“{decision.evidence.strip()}”。"
        if rule_text and rule_text not in reason:
            reason += f" 规则依据：{rule_text}。"
        codes = list(decision.review_reason_codes)
        if low_confidence and "LOW_CONFIDENCE" not in codes:
            codes.append("LOW_CONFIDENCE")
        return decision.model_copy(update={
            "needs_review": True,
            "review_reason_codes": codes,
            "evidence_items": items,
            "reason": reason,
            "status": DecisionStatus.labeled,
        })

    @staticmethod
    def _decision_errors(
        trace: DisclosureTrace, decision: AnnotationDecision
    ) -> List[str]:
        errors: List[str] = []
        chains_by_path = {chain.leaf_path: chain for chain in trace.definitions}
        known_decision_rules = {
            rule.rule_id for rule in [*trace.boundaries, *trace.global_priority_rules]
        }

        if not decision.label:
            errors.append("标注结果必须提供 label")
        chain = chains_by_path.get(decision.label)
        if chain is None:
            errors.append(f"label {decision.label!r} 不在候选叶子范围内")
        else:
            expected_leaf_rule = chain.chain[-1].rule_id if chain.chain else None
            if decision.leaf_rule_used != expected_leaf_rule:
                errors.append(
                    f"label {decision.label!r} 必须使用叶子 Rule {expected_leaf_rule!r}"
                )

        invalid_decision_rules = sorted(
            set(decision.decision_rules_referenced) - known_decision_rules
        )
        if invalid_decision_rules:
            errors.append(
                "decision_rules_referenced 包含未披露 Rule: "
                + ", ".join(invalid_decision_rules)
            )
        missing_reasons = [
            rule_id
            for rule_id in decision.decision_rules_referenced
            if not decision.rule_reasons.get(rule_id, "").strip()
        ]
        if missing_reasons:
            errors.append("rule_reasons 缺少说明: " + ", ".join(missing_reasons))
        return errors

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

    def apply_rule_patch(self, patch_id: str) -> Dict[str, Any]:
        """Apply an approved Add/Update/Delete patch as a new immutable version."""
        patch = self.store.get_rule_patch(patch_id)
        if patch["status"] != "approved":
            raise ValueError("Rule Patch 必须先经过人工批准，才能生成新 Standard")
        current = self.store.get_standard(patch["standard_id"])
        compiled = copy.deepcopy(current["compiled"])
        operations = patch["payload"].get("operations", [])
        if not operations:
            raise ValueError("Rule Patch 没有可应用的 operations")
        affected: set[str] = set()
        changes: List[Tuple[str, Optional[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]] = []
        for operation in operations:
            action = operation.get("action")
            rule_type = operation.get("rule_type")
            if rule_type not in {"definition", "boundary", "priority"}:
                raise ValueError(f"不支持的 Rule 类型: {rule_type}")
            collection = (
                compiled["definition_rules"]
                if rule_type == "definition"
                else compiled["decision_rules"][f"{rule_type}_rules"]
            )
            rule_id = operation.get("rule_id") or operation.get("after", {}).get("rule_id")
            before = next((item for item in collection if item.get("rule_id") == rule_id), None)
            before_snapshot = copy.deepcopy(before)
            if before is not None:
                _, labels_before = self._find_rule(compiled, rule_id)
            else:
                labels_before = []
            if action == "add":
                after = copy.deepcopy(operation.get("after"))
                if not isinstance(after, dict) or not after.get("rule_id"):
                    raise ValueError("新增 Rule 必须提供完整 after 和 rule_id")
                if any(item.get("rule_id") == after["rule_id"] for item in collection):
                    raise ValueError(f"Rule ID 已存在: {after['rule_id']}")
                collection.append(after)
                rule_id = after["rule_id"]
            elif action == "update":
                after = copy.deepcopy(operation.get("after"))
                if before is None or not isinstance(after, dict):
                    raise ValueError(f"更新 Rule 不存在或缺少 after: {rule_id}")
                if after.get("rule_id") != rule_id:
                    raise ValueError("更新后的 Rule 必须保留原 rule_id")
                before.clear()
                before.update(after)
            elif action == "delete":
                if before is None:
                    raise ValueError(f"删除 Rule 不存在: {rule_id}")
                collection.remove(before)
                after = None
            else:
                raise ValueError(f"不支持的 Patch 操作: {action}")
            _, labels = self._find_rule(compiled, rule_id) if action != "delete" else (None, labels_before)
            affected.update(labels)
            changes.append((rule_id, operation.get("before") or before_snapshot, copy.deepcopy(after), labels))

        patch_report = validate_standard(CompiledStandard.model_validate(compiled))
        if not patch_report.valid:
            raise ValueError("Rule Patch 应用后 Standard 校验未通过，不能生效")
        result = self.create_manual_version(
            patch["standard_id"],
            compiled,
            patch["payload"].get("reason", "基于人工反馈应用 Rule Patch"),
        )
        saved = result["standard"]
        for rule_id, before, after, _ in changes:
            self.store.record_rule_change(
                patch["standard_id"], saved["id"], rule_id,
                before or {}, after or {},
                patch["payload"].get("reason", "基于人工反馈应用 Rule Patch"),
                patch["related_feedback_ids"],
            )
        self.store.update_rule_patch_status(patch_id, "applied", saved["id"])
        return {**result, "affected_labels": sorted(affected), "patch": self.store.get_rule_patch(patch_id)}

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
