from __future__ import annotations

import csv
import io
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import get_settings
from .domain import CompiledStandard, ModelSettings
from .miner import SpecGapMiner
from .provider import MissingApiKeyError, ProviderError, QianfanProvider
from .service import LabelSpecService
from .store import Store
from .validator import validate_standard
from .yaml_io import standard_to_yaml_files

app_settings = get_settings()
logging.basicConfig(level=app_settings.labelspec_log_level)
store = Store(app_settings.database_path)
provider = QianfanProvider(app_settings)
service = LabelSpecService(store, provider)
miner = SpecGapMiner(provider, store)


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.initialize()
    yield


app = FastAPI(
    title="LabelSpec API",
    version="0.1.0",
    description="Compile business standards into executable labeling rules.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CompileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    source_markdown: str = Field(min_length=20)


class RunRequest(BaseModel):
    dataset_id: str
    standard_id: str


class ReviewRequest(BaseModel):
    human_label: str = Field(min_length=1)
    note: str = ""


class RuleRevisionRequest(BaseModel):
    rule_id: str
    new_rule: Dict[str, Any]
    reason: str = Field(min_length=2)
    related_case_ids: List[str] = Field(default_factory=list)
    suggestion_id: Optional[str] = None


class ImpactRunRequest(BaseModel):
    source_run_id: str
    target_standard_id: str
    rule_id: str
    labels: List[str] = Field(default_factory=list)


def _handle_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MissingApiKeyError):
        return HTTPException(status_code=412, detail=str(exc))
    if isinstance(exc, ProviderError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc).strip("'"))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "version": "0.1.0",
        "provider": "qianfan",
        "api_key_configured": provider.configured,
        "database": str(app_settings.database_path),
    }


@app.get("/api/settings")
def get_model_settings() -> Dict[str, Any]:
    return {"models": store.get_settings().model_dump(), "api_key_configured": provider.configured}


@app.put("/api/settings")
def put_model_settings(payload: ModelSettings) -> Dict[str, Any]:
    return {"models": store.save_settings(payload).model_dump(), "api_key_configured": provider.configured}


@app.get("/api/models")
async def models() -> Dict[str, Any]:
    try:
        return {"data": await provider.list_models()}
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.get("/api/demo")
def demo_content() -> Dict[str, str]:
    demo_dir = Path(__file__).parent / "demo"
    template = Path(__file__).parent / "templates" / "standard-template.md"
    return {
        "standard_markdown": (demo_dir / "standard.md").read_text(encoding="utf-8"),
        "dataset_csv": (demo_dir / "data.csv").read_text(encoding="utf-8"),
        "standard_template": template.read_text(encoding="utf-8"),
    }


@app.post("/api/demo/dataset")
def create_demo_dataset() -> Dict[str, Any]:
    path = Path(__file__).parent / "demo" / "data.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        items = list(csv.DictReader(stream))
    return store.create_dataset("金融与汽车演示数据", path.name, items)


@app.post("/api/standards/compile")
async def compile_endpoint(payload: CompileRequest) -> Dict[str, Any]:
    try:
        return await service.compile(payload.name, payload.source_markdown)
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.get("/api/standards")
def standards() -> List[Dict[str, Any]]:
    return store.list_standards()


@app.get("/api/standards/{standard_id}")
def standard_detail(standard_id: str) -> Dict[str, Any]:
    try:
        standard = store.get_standard(standard_id)
        compiled = CompiledStandard.model_validate(standard["compiled"])
        return {
            **standard,
            "validation": validate_standard(compiled).model_dump(),
            "files": standard_to_yaml_files(compiled),
            "rule_stats": store.rule_stats(standard_id),
        }
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.post("/api/standards/{standard_id}/activate")
def activate_standard(standard_id: str) -> Dict[str, Any]:
    try:
        standard = store.get_standard(standard_id)
        report = validate_standard(CompiledStandard.model_validate(standard["compiled"]))
        if not report.valid:
            raise ValueError("Standard 校验未通过，不能激活")
        return store.activate_standard(standard_id)
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.post("/api/standards/{standard_id}/revise")
def revise_standard(standard_id: str, payload: RuleRevisionRequest) -> Dict[str, Any]:
    try:
        result = service.revise_rule(
            standard_id,
            payload.rule_id,
            payload.new_rule,
            payload.reason,
            payload.related_case_ids,
        )
        if payload.suggestion_id:
            store.update_suggestion_status(payload.suggestion_id, "accepted")
        return result
    except Exception as exc:
        raise _handle_error(exc) from exc


def _parse_upload(filename: str, content: bytes) -> List[Dict[str, Any]]:
    text = content.decode("utf-8-sig")
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return list(csv.DictReader(io.StringIO(text)))
    if suffix in {".jsonl", ".ndjson"}:
        rows = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL 第 {line_number} 行无效: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL 第 {line_number} 行必须是对象")
            rows.append(value)
        return rows
    raise ValueError("仅支持 .csv、.jsonl 或 .ndjson 文件")


@app.post("/api/datasets")
async def upload_dataset(
    file: UploadFile = File(...), name: Optional[str] = Form(default=None)
) -> Dict[str, Any]:
    try:
        content = await file.read()
        items = _parse_upload(file.filename or "", content)
        return store.create_dataset(name or Path(file.filename or "dataset").stem, file.filename, items)
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.get("/api/datasets")
def datasets() -> List[Dict[str, Any]]:
    return store.list_datasets()


@app.get("/api/datasets/{dataset_id}/items")
def dataset_items(dataset_id: str) -> List[Dict[str, Any]]:
    try:
        store.get_dataset(dataset_id)
        return store.list_items(dataset_id)
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.post("/api/runs")
def create_run(payload: RunRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    try:
        standard = store.get_standard(payload.standard_id)
        if standard["status"] != "active":
            raise ValueError("只能使用已激活的 Standard 运行标注")
        store.get_dataset(payload.dataset_id)
        run = store.create_run(payload.dataset_id, payload.standard_id)
        background_tasks.add_task(service.process_run, run["id"])
        return run
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.get("/api/runs")
def runs() -> List[Dict[str, Any]]:
    return store.list_runs()


@app.post("/api/runs/{run_id}/retry")
def retry_run(run_id: str, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    try:
        run = store.get_run(run_id)
        if run["status"] != "failed":
            raise ValueError("只能继续失败的运行")
        store.update_run(run_id, status="queued", error=None, completed_at=None)
        background_tasks.add_task(service.process_run, run_id)
        return store.get_run(run_id)
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> Dict[str, Any]:
    try:
        return {
            "run": store.get_run(run_id),
            "metrics": store.run_metrics(run_id),
            "annotations": store.list_annotations(run_id),
        }
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.get("/api/runs/{run_id}/export")
def export_run(run_id: str, format: str = "jsonl", gold_only: bool = False) -> Response:
    try:
        annotations = store.list_annotations(run_id)
        if gold_only:
            annotations = [
                item for item in annotations
                if item["route"] == "AUTO_ACCEPT" or item.get("human_label")
            ]
        rows = [
            {
                "id": item["item_id"],
                "text": item["text"],
                "label": item.get("human_label") or item.get("label"),
                "route": item["route"],
                "rules_used": item["rules_used"],
                "evidence": item["evidence"],
                "confidence": item["confidence"],
                "gold_label": item.get("gold_label"),
            }
            for item in annotations
        ]
        suffix = "gold" if gold_only else "all"
        if format == "jsonl":
            content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else "")
            return Response(
                content=content,
                media_type="application/x-ndjson",
                headers={"Content-Disposition": f'attachment; filename="labelspec-{suffix}.jsonl"'},
            )
        if format == "csv":
            stream = io.StringIO()
            fields = ["id", "text", "label", "route", "rules_used", "evidence", "confidence", "gold_label"]
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({**row, "rules_used": "|".join(row["rules_used"])})
            return Response(
                content="\ufeff" + stream.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="labelspec-{suffix}.csv"'},
            )
        raise ValueError("format 仅支持 csv 或 jsonl")
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.post("/api/annotations/{annotation_id}/review")
def review(annotation_id: str, payload: ReviewRequest) -> Dict[str, Any]:
    try:
        return store.review_annotation(annotation_id, payload.human_label, payload.note)
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.post("/api/runs/{run_id}/mine")
async def mine_run(run_id: str) -> Dict[str, Any]:
    try:
        run = store.get_run(run_id)
        if run["status"] != "completed":
            raise ValueError("只能分析已完成的运行")
        return {"suggestions": await miner.mine(run_id)}
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.get("/api/suggestions")
def suggestions(run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    return store.list_suggestions(run_id)


@app.patch("/api/suggestions/{suggestion_id}")
def update_suggestion(suggestion_id: str, status: str) -> Dict[str, Any]:
    try:
        return store.update_suggestion_status(suggestion_id, status)
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.post("/api/impact-runs")
def impact_run(payload: ImpactRunRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    try:
        run = service.create_impact_run(
            payload.source_run_id,
            payload.target_standard_id,
            payload.rule_id,
            payload.labels,
        )
        background_tasks.add_task(service.process_run, run["id"])
        return run
    except Exception as exc:
        raise _handle_error(exc) from exc


@app.get("/api/compare")
def compare_runs(left_run_id: str, right_run_id: str) -> Dict[str, Any]:
    try:
        return {
            "left": {"run": store.get_run(left_run_id), "metrics": store.run_metrics(left_run_id)},
            "right": {"run": store.get_run(right_run_id), "metrics": store.run_metrics(right_run_id)},
        }
    except Exception as exc:
        raise _handle_error(exc) from exc


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (frontend_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="web")
