from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence

from .domain import (
    CandidateDecision,
    CompiledStandard,
    DisclosureTrace,
)
from .provider import QianfanProvider
from .store import Store


CANDIDATE_SYSTEM = """你是单标签文本分类的候选召回器。你会看到完整标签空间和全部全局 Priority Rule。
此阶段不做最终分类，只选出所有合理候选标签（通常 1-3 个，最多 5 个）。
不得返回标签目录之外的标签。存在跨行业实体时，不要只按实体行业召回，要考虑用户最终诉求。
candidates 数组中的每一项只能逐字复制标签目录中的完整标签名，不得添加冒号、解释、子类或任何其他文字；解释只能放在 rationale。
输出严格遵循 JSON Schema。"""


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
        include_history: bool = False,
    ) -> DisclosureTrace:
        labels = standard.labels.labels
        priorities = standard.decision_rules.priority_rules
        label_map = "\n".join(f"- {label.name}: {label.description}" for label in labels)
        priority_map = "\n".join(f"- {rule.rule_id}: {rule.principle}" for rule in priorities) or "（无）"
        candidate_prompt = f"待分类文本：{text}\n\n完整标签目录：\n{label_map}\n\n全局 Priority Rules：\n{priority_map}"
        candidate = await self.provider.structured(
            model=model,
            system=CANDIDATE_SYSTEM,
            user=candidate_prompt,
            response_model=CandidateDecision,
            temperature=0.05,
        )
        known = {label.name for label in labels}
        candidates = self._normalize_candidates(candidate.candidates, known)
        if not candidates:
            candidate = await self.provider.structured(
                model=model,
                system=CANDIDATE_SYSTEM,
                user=(
                    candidate_prompt
                    + "\n\n上一次返回的候选均不在标签目录中。重新选择，candidates 每项只能从以下字符串中原样取值：\n"
                    + str(sorted(known))
                ),
                response_model=CandidateDecision,
                temperature=0,
            )
            candidates = self._normalize_candidates(candidate.candidates, known)
        if not candidates:
            raise ValueError("候选模型未返回任何合法标签")

        definitions = [rule for rule in standard.definition_rules if rule.label in candidates]
        candidate_set = set(candidates)
        boundaries = [
            rule
            for rule in standard.decision_rules.boundary_rules
            if len(candidate_set.intersection(rule.labels)) >= 2
        ]
        history: List[Dict[str, Any]] = []
        if include_history:
            history = await self.retrieve_history(text, item_id, embedding_model)
        return DisclosureTrace(
            label_map=labels,
            global_priority_rules=priorities,
            candidates=candidates,
            definitions=definitions,
            boundaries=boundaries,
            historical_cases=history,
        )

    @staticmethod
    def _normalize_candidates(values: Sequence[str], known: set) -> List[str]:
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

    async def retrieve_history(
        self, text: str, item_id: str, embedding_model: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        cases = self.store.historical_cases(exclude_item_id=item_id)
        if not cases:
            return []
        cached = self.store.get_embeddings([case["id"] for case in cases], embedding_model)
        missing = [case for case in cases if case["id"] not in cached]
        if missing:
            vectors = await self.provider.embeddings(embedding_model, [case["text"] for case in missing])
            new_values = {case["id"]: vector for case, vector in zip(missing, vectors)}
            self.store.save_embeddings(new_values, embedding_model)
            cached.update(new_values)
        query_vector = (await self.provider.embeddings(embedding_model, [text]))[0]
        ranked = sorted(
            cases,
            key=lambda case: self._cosine(query_vector, cached[case["id"]]),
            reverse=True,
        )[:limit]
        return [
            {
                "item_id": case["id"],
                "text": case["text"],
                "label": case["label"],
                "similarity": round(self._cosine(query_vector, cached[case["id"]]), 4),
                "note": case.get("review_note"),
            }
            for case in ranked
        ]

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0
