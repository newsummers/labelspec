from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Sequence

from .disclosure import DisclosureEngine
from .domain import MinerSuggestion
from .provider import QianfanProvider
from .store import Store
from .taxonomy import descendants, label_path, parse_compiled_standard


MINER_SYSTEM = """你是 LabelSpec Rule Evolution Miner。你会看到人工确认过的标注反馈和当前相关 Rule。
判断问题是 Definition、Boundary 还是 Priority Rule 不完整，并提出最小、可执行、不会随意扩大标签范围的修改。
只能生成供人工审核的 Rule Patch，不能直接修改 Standard。Patch 支持 add、update、delete，
每个 operation 必须包含 action、rule_type、rule_id（add 可从 after 读取）和完整 after（delete 除外）。
典型 Case 最多 8 条，target_rule_id 优先指向现有 Rule；只有确实缺少规则时才为 null。
输出严格符合 JSON Schema。"""


class SpecGapMiner:
    def __init__(self, provider: QianfanProvider, store: Store):
        self.provider = provider
        self.store = store

    async def mine(self, run_id: str) -> List[Dict[str, Any]]:
        settings = self.store.get_settings()
        run = self.store.get_run(run_id)
        standard = self.store.get_standard(run["standard_id"])["compiled"]
        feedback = self.store.list_feedback(run_id=run_id)
        failures = [
            {
                "item_id": item["item_id"],
                "text": item["text"],
                "route": "REVIEW",
                "evidence": item["evidence_snapshot"].get("evidence", ""),
                "route_reasons": [{"code": item["reason_code"], "message": item["note"]}],
                "rules_used": item["evidence_snapshot"].get("decision", {}).get("decision_rules_referenced", []),
                "candidates": [item["human_label"]],
                "model_label": item["model_label"],
                "human_label": item["human_label"],
                "feedback_id": item["id"],
            }
            for item in feedback
        ]
        if not failures:
            return []
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in failures:
            signature = (
                "|".join(sorted(item["candidates"]))
                + "::"
                + item["route_reasons"][0]["code"]
            )
            groups[signature].append(item)

        created: List[Dict[str, Any]] = []
        for signature, cases in groups.items():
            if len(cases) < settings.spec_gap_min_cluster_size:
                continue
            clusters = await self._semantic_clusters(cases, settings.embedding_model)
            for index, cluster in enumerate(clusters):
                if len(cluster) < settings.spec_gap_min_cluster_size:
                    continue
                candidates = sorted({label for case in cluster for label in case["candidates"]})
                rule_ids = sorted({rule_id for case in cluster for rule_id in case["rules_used"]})
                related_rules = self._related_rules(standard, candidates, rule_ids)
                payload = {
                    "labels": candidates,
                    "observed_rules": related_rules,
                    "feedback": [
                        {
                            "text": case["text"],
                            "model_label": case["model_label"],
                            "human_label": case["human_label"],
                            "evidence": case["evidence"],
                            "route_reasons": case["route_reasons"],
                            "feedback_id": case["feedback_id"],
                        }
                        for case in cluster[:30]
                    ],
                }
                suggestion = await self.provider.structured(
                    model=settings.miner_model,
                    system=MINER_SYSTEM,
                    user=json.dumps(payload, ensure_ascii=False),
                    response_model=MinerSuggestion,
                    temperature=0.15,
                )
                patch = self.store.save_rule_patch(
                    run["standard_id"],
                    suggestion.model_dump(mode="json"),
                    [case["feedback_id"] for case in cluster],
                    source_run_id=run_id,
                )
                suggestion_payload = suggestion.model_dump()
                suggestion_payload["patch_id"] = patch["id"]
                saved = self.store.save_suggestion(
                    run_id,
                    f"{signature}#{index}",
                    suggestion_payload,
                    [case["item_id"] for case in cluster],
                )
                saved["patch"] = patch
                created.append(saved)
        return created

    async def _semantic_clusters(
        self, cases: List[Dict[str, Any]], model: str
    ) -> List[List[Dict[str, Any]]]:
        item_ids = [case["item_id"] for case in cases]
        vectors = self.store.get_embeddings(item_ids, model)
        missing = [case for case in cases if case["item_id"] not in vectors]
        if missing:
            generated = await self.provider.embeddings(model, [case["text"] for case in missing])
            additions = {case["item_id"]: vector for case, vector in zip(missing, generated)}
            self.store.save_embeddings(additions, model)
            vectors.update(additions)

        # Connected components make the grouping deterministic and auditable.
        remaining = set(item_ids)
        components: List[List[str]] = []
        while remaining:
            seed = remaining.pop()
            component = {seed}
            frontier = [seed]
            while frontier:
                current = frontier.pop()
                neighbors = {
                    candidate for candidate in remaining
                    if DisclosureEngine._cosine(vectors[current], vectors[candidate]) >= 0.76
                }
                remaining.difference_update(neighbors)
                component.update(neighbors)
                frontier.extend(neighbors)
            components.append(sorted(component))
        by_id = {case["item_id"]: case for case in cases}
        return [[by_id[item_id] for item_id in component] for component in components]

    @staticmethod
    def _related_rules(
        standard: Dict[str, Any], labels: Sequence[str], rule_ids: Sequence[str]
    ) -> List[Dict[str, Any]]:
        label_set = set(labels)
        rule_set = set(rule_ids)
        compiled = parse_compiled_standard(standard)
        paths = {
            label.label_id: label_path(compiled, label.label_id)
            for label in compiled.labels.labels
        }
        definitions = [
            rule for rule in standard["definition_rules"]
            if paths.get(rule["label_id"]) in label_set or rule["rule_id"] in rule_set
        ]
        boundaries = [
            rule for rule in standard["decision_rules"]["boundary_rules"]
            if len([
                item for item in rule["label_ids"]
                if label_set.intersection(
                    paths.get(descendant, "")
                    for descendant in descendants(compiled, item, leaves_only=True)
                )
            ]) >= 2
            or rule["rule_id"] in rule_set
        ]
        priorities = standard["decision_rules"]["priority_rules"]
        return [*definitions, *boundaries, *priorities]
