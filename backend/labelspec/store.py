from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from .domain import CompiledStandard, ModelSettings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: Optional[str], default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS standards (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('draft', 'active', 'archived')),
                    source_markdown TEXT NOT NULL,
                    compiled_json TEXT NOT NULL,
                    parent_id TEXT REFERENCES standards(id),
                    change_summary TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(name, version)
                );

                CREATE TABLE IF NOT EXISTS rule_changes (
                    id TEXT PRIMARY KEY,
                    from_standard_id TEXT NOT NULL REFERENCES standards(id),
                    to_standard_id TEXT NOT NULL REFERENCES standards(id),
                    rule_id TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    related_case_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    filename TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS data_items (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                    source_id TEXT,
                    text TEXT NOT NULL,
                    gold_label TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_data_items_dataset ON data_items(dataset_id);

                CREATE TABLE IF NOT EXISTS annotation_runs (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL REFERENCES datasets(id),
                    standard_id TEXT NOT NULL REFERENCES standards(id),
                    parent_run_id TEXT REFERENCES annotation_runs(id),
                    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'completed', 'failed')),
                    total INTEGER NOT NULL DEFAULT 0,
                    processed INTEGER NOT NULL DEFAULT 0,
                    scope_item_ids_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS annotations (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES annotation_runs(id) ON DELETE CASCADE,
                    item_id TEXT NOT NULL REFERENCES data_items(id),
                    label TEXT,
                    candidates_json TEXT NOT NULL,
                    rules_used_json TEXT NOT NULL,
                    rule_reasons_json TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    route TEXT NOT NULL,
                    route_reasons_json TEXT NOT NULL,
                    disclosure_json TEXT NOT NULL,
                    verifier_json TEXT NOT NULL,
                    human_label TEXT,
                    review_note TEXT,
                    reviewed_at TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, item_id)
                );

                CREATE INDEX IF NOT EXISTS idx_annotations_run ON annotations(run_id);
                CREATE INDEX IF NOT EXISTS idx_annotations_route ON annotations(route);

                CREATE TABLE IF NOT EXISTS suggestions (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES annotation_runs(id),
                    signature TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    case_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('open', 'accepted', 'dismissed')),
                    created_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestions_signature
                ON suggestions(run_id, signature);

                CREATE TABLE IF NOT EXISTS case_embeddings (
                    item_id TEXT NOT NULL REFERENCES data_items(id) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(item_id, model)
                );
                """
            )
            existing = db.execute("SELECT id FROM settings WHERE id = 1").fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO settings(id, value_json, updated_at) VALUES (1, ?, ?)",
                    (_json(ModelSettings().model_dump()), utc_now()),
                )

    def get_settings(self) -> ModelSettings:
        with self.connect() as db:
            row = db.execute("SELECT value_json FROM settings WHERE id = 1").fetchone()
        return ModelSettings.model_validate(_loads(row["value_json"]))

    def save_settings(self, settings: ModelSettings) -> ModelSettings:
        with self.connect() as db:
            db.execute(
                "UPDATE settings SET value_json = ?, updated_at = ? WHERE id = 1",
                (_json(settings.model_dump()), utc_now()),
            )
        return settings

    def create_standard(
        self,
        source_markdown: str,
        standard: CompiledStandard,
        status: str = "draft",
        parent_id: Optional[str] = None,
        change_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        standard_id = str(uuid.uuid4())
        with self.connect() as db:
            row = db.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM standards WHERE name = ?",
                (standard.name,),
            ).fetchone()
            version = int(row["version"]) + 1
            db.execute(
                """INSERT INTO standards
                   (id, name, version, status, source_markdown, compiled_json, parent_id, change_summary, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    standard_id,
                    standard.name,
                    version,
                    status,
                    source_markdown,
                    _json(standard.model_dump()),
                    parent_id,
                    change_summary,
                    utc_now(),
                ),
            )
        return self.get_standard(standard_id)

    def activate_standard(self, standard_id: str) -> Dict[str, Any]:
        standard = self.get_standard(standard_id)
        with self.connect() as db:
            db.execute(
                "UPDATE standards SET status = 'archived' WHERE name = ? AND status = 'active'",
                (standard["name"],),
            )
            db.execute("UPDATE standards SET status = 'active' WHERE id = ?", (standard_id,))
        return self.get_standard(standard_id)

    def list_standards(self) -> List[Dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM standards ORDER BY created_at DESC"
            ).fetchall()
        return [self._standard_row(row, include_source=False) for row in rows]

    def get_standard(self, standard_id: str) -> Dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM standards WHERE id = ?", (standard_id,)).fetchone()
        if not row:
            raise KeyError(f"Standard {standard_id} 不存在")
        return self._standard_row(row, include_source=True)

    def _standard_row(self, row: sqlite3.Row, include_source: bool) -> Dict[str, Any]:
        compiled = _loads(row["compiled_json"], {})
        result = {
            "id": row["id"],
            "name": row["name"],
            "version": row["version"],
            "status": row["status"],
            "parent_id": row["parent_id"],
            "change_summary": row["change_summary"],
            "created_at": row["created_at"],
            "compiled": compiled,
            "counts": {
                "labels": len(compiled.get("labels", {}).get("labels", [])),
                "definitions": len(compiled.get("definition_rules", [])),
                "boundaries": len(compiled.get("decision_rules", {}).get("boundary_rules", [])),
                "priorities": len(compiled.get("decision_rules", {}).get("priority_rules", [])),
            },
        }
        if include_source:
            result["source_markdown"] = row["source_markdown"]
        return result

    def create_dataset(
        self, name: str, filename: Optional[str], items: Iterable[Dict[str, Any]]
    ) -> Dict[str, Any]:
        dataset_id = str(uuid.uuid4())
        now = utc_now()
        normalized = []
        seen_ids = set()
        for raw in items:
            item_id = str(uuid.uuid4())
            source_id = str(raw.get("id") or "").strip() or None
            text = str(raw.get("text") or "").strip()
            if not text:
                continue
            if source_id and source_id in seen_ids:
                source_id = None
            if source_id:
                seen_ids.add(source_id)
            gold = str(raw.get("gold_label") or "").strip() or None
            metadata = {key: value for key, value in raw.items() if key not in {"id", "text", "gold_label"}}
            normalized.append((item_id, dataset_id, source_id, text, gold, _json(metadata), now))
        if not normalized:
            raise ValueError("数据集中没有有效的 text")
        with self.connect() as db:
            db.execute(
                "INSERT INTO datasets(id, name, filename, created_at) VALUES (?, ?, ?, ?)",
                (dataset_id, name, filename, now),
            )
            db.executemany(
                """INSERT INTO data_items
                   (id, dataset_id, source_id, text, gold_label, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                normalized,
            )
        return self.get_dataset(dataset_id)

    def list_datasets(self) -> List[Dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT d.*, COUNT(i.id) AS item_count
                   FROM datasets d LEFT JOIN data_items i ON i.dataset_id = d.id
                   GROUP BY d.id ORDER BY d.created_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def get_dataset(self, dataset_id: str) -> Dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                """SELECT d.*, COUNT(i.id) AS item_count
                   FROM datasets d LEFT JOIN data_items i ON i.dataset_id = d.id
                   WHERE d.id = ? GROUP BY d.id""",
                (dataset_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"Dataset {dataset_id} 不存在")
        return dict(row)

    def list_items(self, dataset_id: str, ids: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM data_items WHERE dataset_id = ?"
        params: List[Any] = [dataset_id]
        if ids is not None:
            if not ids:
                return []
            sql += f" AND id IN ({','.join('?' for _ in ids)})"
            params.extend(ids)
        sql += " ORDER BY created_at, id"
        with self.connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [
            {
                **dict(row),
                "metadata": _loads(row["metadata_json"], {}),
            }
            for row in rows
        ]

    def create_run(
        self,
        dataset_id: str,
        standard_id: str,
        scope_item_ids: Optional[List[str]] = None,
        parent_run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        total = len(scope_item_ids) if scope_item_ids is not None else self.get_dataset(dataset_id)["item_count"]
        with self.connect() as db:
            db.execute(
                """INSERT INTO annotation_runs
                   (id, dataset_id, standard_id, parent_run_id, status, total, processed,
                    scope_item_ids_json, created_at)
                   VALUES (?, ?, ?, ?, 'queued', ?, 0, ?, ?)""",
                (run_id, dataset_id, standard_id, parent_run_id, total, _json(scope_item_ids) if scope_item_ids is not None else None, utc_now()),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> Dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                """SELECT r.*, d.name AS dataset_name, s.name AS standard_name, s.version AS standard_version
                   FROM annotation_runs r
                   JOIN datasets d ON d.id = r.dataset_id
                   JOIN standards s ON s.id = r.standard_id
                   WHERE r.id = ?""",
                (run_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"Run {run_id} 不存在")
        result = dict(row)
        result["scope_item_ids"] = _loads(row["scope_item_ids_json"])
        return result

    def list_runs(self) -> List[Dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT r.*, d.name AS dataset_name, s.name AS standard_name, s.version AS standard_version
                   FROM annotation_runs r
                   JOIN datasets d ON d.id = r.dataset_id
                   JOIN standards s ON s.id = r.standard_id
                   ORDER BY r.created_at DESC"""
            ).fetchall()
        return [{**dict(row), "scope_item_ids": _loads(row["scope_item_ids_json"])} for row in rows]

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {"status", "processed", "error", "completed_at"}
        data = {key: value for key, value in fields.items() if key in allowed}
        if not data:
            return
        assignments = ", ".join(f"{key} = ?" for key in data)
        with self.connect() as db:
            db.execute(f"UPDATE annotation_runs SET {assignments} WHERE id = ?", [*data.values(), run_id])

    def save_annotation(self, run_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        annotation_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute(
                """INSERT OR REPLACE INTO annotations
                   (id, run_id, item_id, label, candidates_json, rules_used_json,
                    rule_reasons_json, evidence, confidence, route, route_reasons_json,
                    disclosure_json, verifier_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    annotation_id,
                    run_id,
                    result["item_id"],
                    result.get("label"),
                    _json(result.get("candidates", [])),
                    _json(result.get("rules_used", [])),
                    _json(result.get("rule_reasons", {})),
                    result.get("evidence", ""),
                    result.get("confidence", 0),
                    result["route"],
                    _json(result.get("route_reasons", [])),
                    _json(result.get("disclosure", {})),
                    _json(result.get("verifier", {})),
                    utc_now(),
                ),
            )
        return self.get_annotation(annotation_id)

    def get_annotation(self, annotation_id: str) -> Dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                """SELECT a.*, i.text, i.gold_label FROM annotations a
                   JOIN data_items i ON i.id = a.item_id WHERE a.id = ?""",
                (annotation_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"Annotation {annotation_id} 不存在")
        return self._annotation_row(row)

    def list_annotations(self, run_id: str, route: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = """SELECT a.*, i.text, i.gold_label FROM annotations a
                 JOIN data_items i ON i.id = a.item_id WHERE a.run_id = ?"""
        params: List[Any] = [run_id]
        if route:
            sql += " AND a.route = ?"
            params.append(route)
        sql += " ORDER BY a.created_at"
        with self.connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [self._annotation_row(row) for row in rows]

    def _annotation_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        for column in ("candidates_json", "rules_used_json", "rule_reasons_json", "route_reasons_json", "disclosure_json", "verifier_json"):
            result[column[:-5]] = _loads(row[column], [] if column.endswith("s_json") else {})
        return result

    def review_annotation(self, annotation_id: str, human_label: str, note: str) -> Dict[str, Any]:
        with self.connect() as db:
            db.execute(
                "UPDATE annotations SET human_label = ?, review_note = ?, reviewed_at = ? WHERE id = ?",
                (human_label, note, utc_now(), annotation_id),
            )
        return self.get_annotation(annotation_id)

    def historical_cases(self, exclude_item_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT i.id, i.text, COALESCE(a.human_label, i.gold_label, a.label) AS label,
                          a.route, a.review_note
                   FROM annotations a JOIN data_items i ON i.id = a.item_id
                   WHERE i.id != ? AND (a.human_label IS NOT NULL OR i.gold_label IS NOT NULL)
                   ORDER BY COALESCE(a.reviewed_at, a.created_at) DESC LIMIT ?""",
                (exclude_item_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_embeddings(self, item_ids: Sequence[str], model: str) -> Dict[str, List[float]]:
        if not item_ids:
            return {}
        with self.connect() as db:
            rows = db.execute(
                f"SELECT item_id, vector_json FROM case_embeddings WHERE model = ? AND item_id IN ({','.join('?' for _ in item_ids)})",
                [model, *item_ids],
            ).fetchall()
        return {row["item_id"]: _loads(row["vector_json"], []) for row in rows}

    def save_embeddings(self, values: Dict[str, List[float]], model: str) -> None:
        with self.connect() as db:
            db.executemany(
                """INSERT OR REPLACE INTO case_embeddings(item_id, model, vector_json, created_at)
                   VALUES (?, ?, ?, ?)""",
                [(item_id, model, _json(vector), utc_now()) for item_id, vector in values.items()],
            )

    def save_suggestion(self, run_id: str, signature: str, payload: Dict[str, Any], case_ids: List[str]) -> Dict[str, Any]:
        with self.connect() as db:
            existing = db.execute(
                "SELECT id FROM suggestions WHERE run_id = ? AND signature = ?",
                (run_id, signature),
            ).fetchone()
        if existing:
            return self.get_suggestion(existing["id"])
        suggestion_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute(
                """INSERT INTO suggestions(id, run_id, signature, payload_json, case_ids_json, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'open', ?)""",
                (suggestion_id, run_id, signature, _json(payload), _json(case_ids), utc_now()),
            )
        return self.get_suggestion(suggestion_id)

    def get_suggestion(self, suggestion_id: str) -> Dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
        if not row:
            raise KeyError(f"Suggestion {suggestion_id} 不存在")
        result = dict(row)
        result["payload"] = _loads(row["payload_json"], {})
        result["case_ids"] = _loads(row["case_ids_json"], [])
        return result

    def list_suggestions(self, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM suggestions"
        params: List[Any] = []
        if run_id:
            sql += " WHERE run_id = ?"
            params.append(run_id)
        sql += " ORDER BY created_at DESC"
        with self.connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [
            {**dict(row), "payload": _loads(row["payload_json"], {}), "case_ids": _loads(row["case_ids_json"], [])}
            for row in rows
        ]

    def update_suggestion_status(self, suggestion_id: str, status: str) -> Dict[str, Any]:
        if status not in {"open", "accepted", "dismissed"}:
            raise ValueError("无效的建议状态")
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE suggestions SET status = ? WHERE id = ?", (status, suggestion_id)
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Suggestion {suggestion_id} 不存在")
        return self.get_suggestion(suggestion_id)

    def record_rule_change(
        self,
        from_standard_id: str,
        to_standard_id: str,
        rule_id: str,
        before: Dict[str, Any],
        after: Dict[str, Any],
        reason: str,
        related_case_ids: List[str],
    ) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO rule_changes
                   (id, from_standard_id, to_standard_id, rule_id, before_json, after_json,
                    reason, related_case_ids_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), from_standard_id, to_standard_id, rule_id,
                    _json(before), _json(after), reason, _json(related_case_ids), utc_now(),
                ),
            )

    def affected_item_ids(self, run_id: str, rule_id: str, labels: List[str]) -> List[str]:
        annotations = self.list_annotations(run_id)
        affected = []
        label_set = set(labels)
        for annotation in annotations:
            if rule_id in annotation["rules_used"] or label_set.intersection(annotation["candidates"]):
                affected.append(annotation["item_id"])
        return sorted(set(affected))

    def run_metrics(self, run_id: str) -> Dict[str, Any]:
        annotations = self.list_annotations(run_id)
        total = len(annotations)
        routes: Dict[str, int] = {}
        correct = 0
        comparable = 0
        conflict = 0
        for item in annotations:
            routes[item["route"]] = routes.get(item["route"], 0) + 1
            truth = item.get("human_label") or item.get("gold_label")
            if truth:
                comparable += 1
                correct += int(item.get("label") == truth)
            conflict += int(item["route"] in {"AMBIGUOUS", "SPEC_GAP"})
        ratio = lambda count: round(count / total, 4) if total else 0
        return {
            "total": total,
            "routes": routes,
            "accuracy": round(correct / comparable, 4) if comparable else None,
            "accuracy_sample_size": comparable,
            "auto_accept_rate": ratio(routes.get("AUTO_ACCEPT", 0)),
            "review_rate": ratio(routes.get("REVIEW", 0)),
            "rule_conflict_rate": ratio(conflict),
        }

    def rule_stats(self, standard_id: str) -> List[Dict[str, Any]]:
        standard = self.get_standard(standard_id)["compiled"]
        descriptors: Dict[str, Dict[str, Any]] = {}
        for rule in standard["definition_rules"]:
            descriptors[rule["rule_id"]] = {"type": "definition", "labels": [rule["label"]]}
        for rule in standard["decision_rules"]["boundary_rules"]:
            descriptors[rule["rule_id"]] = {"type": "boundary", "labels": rule["labels"]}
        for rule in standard["decision_rules"]["priority_rules"]:
            descriptors[rule["rule_id"]] = {"type": "priority", "labels": []}
        stats = {
            rule_id: {"rule_id": rule_id, **value, "uses": 0, "conflicts": 0, "overrides": 0, "modifications": 0}
            for rule_id, value in descriptors.items()
        }
        with self.connect() as db:
            rows = db.execute(
                """SELECT a.rules_used_json, a.route, a.label, a.human_label
                   FROM annotations a JOIN annotation_runs r ON r.id = a.run_id
                   WHERE r.standard_id = ?""",
                (standard_id,),
            ).fetchall()
            changes = db.execute(
                """SELECT rule_id, COUNT(*) AS count FROM rule_changes
                   WHERE from_standard_id = ? OR to_standard_id = ? GROUP BY rule_id""",
                (standard_id, standard_id),
            ).fetchall()
        for row in rows:
            for rule_id in _loads(row["rules_used_json"], []):
                if rule_id not in stats:
                    continue
                stats[rule_id]["uses"] += 1
                stats[rule_id]["conflicts"] += int(row["route"] in {"AMBIGUOUS", "SPEC_GAP"})
                stats[rule_id]["overrides"] += int(
                    bool(row["human_label"]) and row["human_label"] != row["label"]
                )
        for row in changes:
            if row["rule_id"] in stats:
                stats[row["rule_id"]]["modifications"] = row["count"]
        return list(stats.values())
