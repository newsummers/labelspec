from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence

from .domain import CandidateDecision, CompiledStandard, DisclosureTrace
from .provider import QianfanProvider
from .store import Store
from .taxonomy import (
    children_index,
    descendants,
    effective_definitions,
    label_index,
    label_path,
    leaf_ids,
    path_index,
)


CANDIDATE_SYSTEM = """你是分层单标签分类的候选召回器。你会看到当前层级可选节点及其局部定义。
选择 1 到 5 个最可能的候选路径，不做最终裁决；有歧义时保留多个分支，不得返回目录之外的路径。
返回简短召回理由。"""


class DisclosureEngine:
    def __init__(self, provider: QianfanProvider, store: Store):
        self.provider = provider
        self.store = store

    async def disclose(
        self,
        text: str,
        item_id: str,
        standard: CompiledStandard,
        model: str,
        embedding_model: str,
        top_k_history: int = 3,
    ) -> DisclosureTrace:
        candidate_paths, _ = await self._recall_candidates(
            text, standard, model
        )
        paths = path_index(standard)
        candidate_ids = [paths[path] for path in candidate_paths if path in paths]
        definitions = effective_definitions(standard, candidate_ids)
        boundaries = [
            rule
            for rule in standard.decision_rules.boundary_rules
            if self._boundary_relevant(standard, rule.label_ids, candidate_ids, rule.scope_label_id)
        ]
        priorities = [
            rule
            for rule in standard.decision_rules.priority_rules
            if not rule.scope_label_id
            or any(
                candidate in descendants(standard, rule.scope_label_id, leaves_only=True)
                for candidate in candidate_ids
            )
        ]
        historical_cases = await self._retrieve_history(
            text, item_id, candidate_paths, embedding_model, top_k_history
        )
        by_id = label_index(standard)
        return DisclosureTrace(
            label_map=[by_id[rule.label_id] for rule in definitions],
            global_priority_rules=priorities,
            candidates=candidate_paths,
            definitions=definitions,
            boundaries=boundaries,
            historical_cases=historical_cases,
        )

    async def _recall_candidates(
        self, text: str, standard: CompiledStandard, model: str
    ) -> tuple[List[str], str]:
        by_id = label_index(standard)
        definitions = {rule.label_id: rule for rule in standard.definition_rules}
        children = children_index(standard)
        leaves = leaf_ids(standard)
        selected = [label.label_id for label in children.get(None, [])]
        rationale_parts: List[str] = []
        max_rounds = max((len(label_path(standard, label_id).split("/")) for label_id in leaves), default=1)

        for _ in range(max_rounds):
            options: List[str] = []
            for label_id in selected:
                if label_id in leaves:
                    options.append(label_id)
                else:
                    options.extend(child.label_id for child in children.get(label_id, []))
            options = list(dict.fromkeys(options))
            if not options:
                break
            if len(options) == 1:
                selected = options
                continue
            catalog = [
                {
                    "path": label_path(standard, label_id),
                    "description": by_id[label_id].description,
                    "definition": definitions[label_id].definition if label_id in definitions else "",
                }
                for label_id in options
            ]
            relevant_priorities = [
                rule.model_dump(mode="json")
                for rule in standard.decision_rules.priority_rules
                if not rule.scope_label_id
                or any(
                    option in descendants(standard, rule.scope_label_id)
                    for option in options
                )
            ]
            decision = await self.provider.structured(
                model=model,
                system=CANDIDATE_SYSTEM,
                user=f"标签节点：{catalog}\n\n相关 Priority：{relevant_priorities}\n\n待分类文本：{text}",
                response_model=CandidateDecision,
                temperature=0.0,
            )
            option_paths = {label_path(standard, label_id): label_id for label_id in options}
            normalized = self._normalize_candidates(decision.candidates, set(option_paths))
            chosen = [option_paths[path] for path in normalized]
            selected = list(dict.fromkeys(chosen))[:5] or options[:5]
            rationale_parts.append(decision.rationale)
            if all(label_id in leaves for label_id in selected):
                break

        final_ids: List[str] = []
        for label_id in selected:
            if label_id in leaves:
                final_ids.append(label_id)
            else:
                final_ids.extend(sorted(descendants(standard, label_id, leaves_only=True)))
        final_ids = list(dict.fromkeys(final_ids))[:5]
        if not final_ids:
            final_ids = [
                label.label_id
                for label in standard.labels.labels
                if label.label_id in leaves
            ][:5]
        return [label_path(standard, label_id) for label_id in final_ids], "；".join(rationale_parts)

    @staticmethod
    def _normalize_candidates(values: Sequence[str], known: set[str]) -> List[str]:
        normalized: List[str] = []
        for value in values:
            candidate = value.strip()
            if candidate in known:
                normalized.append(candidate)
                continue
            for separator in (":", "："):
                prefix = candidate.split(separator, 1)[0].strip()
                if prefix in known:
                    normalized.append(prefix)
                    break
        return list(dict.fromkeys(normalized))

    @staticmethod
    def _boundary_relevant(
        standard: CompiledStandard,
        referenced_ids: List[str],
        candidate_ids: List[str],
        scope_label_id: str | None,
    ) -> bool:
        if scope_label_id:
            scope_leaves = descendants(standard, scope_label_id, leaves_only=True)
            candidates = [item for item in candidate_ids if item in scope_leaves]
        else:
            candidates = candidate_ids
        matched_groups = 0
        for referenced in referenced_ids:
            covered = descendants(standard, referenced, leaves_only=True)
            if any(candidate in covered for candidate in candidates):
                matched_groups += 1
        return matched_groups >= 2

    async def _retrieve_history(
        self,
        text: str,
        item_id: str,
        candidates: List[str],
        embedding_model: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        cases = [
            case
            for case in self.store.historical_cases(exclude_item_id=item_id)
            if case.get("label") in candidates
        ]
        if not cases:
            return []
        query_vector = (await self.provider.embeddings(embedding_model, [text]))[0]
        cached = self.store.get_embeddings([case["id"] for case in cases], embedding_model)
        missing = [case for case in cases if case["id"] not in cached]
        if missing:
            vectors = await self.provider.embeddings(embedding_model, [case["text"] for case in missing])
            additions = {case["id"]: vector for case, vector in zip(missing, vectors)}
            self.store.save_embeddings(additions, embedding_model)
            cached.update(additions)
        ranked = sorted(
            cases,
            key=lambda case: self._cosine(query_vector, cached[case["id"]]),
            reverse=True,
        )[:top_k]
        return [
            {
                "text": case["text"],
                "label": case["label"],
                "similarity": round(self._cosine(query_vector, cached[case["id"]]), 4),
            }
            for case in ranked
        ]

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0
