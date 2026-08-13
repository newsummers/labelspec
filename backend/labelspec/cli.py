from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import List, Optional

import typer
import uvicorn
import yaml
from rich.console import Console
from rich.table import Table

from .api import _parse_upload
from .api import app as api_app
from .api import miner, provider, service, store
from .domain import ModelSettings
from .documents import parse_standard_document
from .taxonomy import parse_compiled_standard
from .validator import validate_standard
from .yaml_io import standard_to_yaml_files

app = typer.Typer(help="LabelSpec: executable standards for reliable labeling.", no_args_is_help=True)
console = Console()


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Start the LabelSpec API server."""
    uvicorn.run("labelspec.api:app", host=host, port=port, reload=reload)


@app.command("settings")
def settings_command(
    compiler_model: Optional[str] = None,
    annotator_model: Optional[str] = None,
    verifier_model: Optional[str] = None,
    miner_model: Optional[str] = None,
    embedding_model: Optional[str] = None,
    auto_accept_threshold: Optional[float] = None,
    spec_gap_min_cluster_size: Optional[int] = None,
) -> None:
    """Show or update model and routing settings."""
    store.initialize()
    current = store.get_settings().model_dump()
    updates = {
        "compiler_model": compiler_model,
        "annotator_model": annotator_model,
        "verifier_model": verifier_model,
        "miner_model": miner_model,
        "embedding_model": embedding_model,
        "auto_accept_threshold": auto_accept_threshold,
        "spec_gap_min_cluster_size": spec_gap_min_cluster_size,
    }
    current.update({key: value for key, value in updates.items() if value is not None})
    saved = store.save_settings(ModelSettings.model_validate(current))
    console.print_json(data=saved.model_dump())


@app.command("compile")
def compile_command(
    standard_files: List[Path] = typer.Argument(..., exists=True, readable=True),
    name: str = typer.Option(..., "--name", "-n"),
    output_dir: Optional[Path] = typer.Option(None, "--output", "-o"),
) -> None:
    """Compile a Markdown standard with the configured Qianfan model."""
    store.initialize()
    documents = [
        parse_standard_document(path.name, "application/octet-stream", path.read_bytes())
        for path in standard_files
    ]
    result = asyncio.run(service.compile_documents(name, documents))
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in result["files"].items():
            (output_dir / filename).write_text(content, encoding="utf-8")
    console.print(f"Draft v{result['standard']['version']} created: {result['standard']['id']}")
    console.print_json(data=result["validation"])


@app.command("validate")
def validate_command(
    labels_yaml: Path = typer.Option(..., exists=True),
    definitions_yaml: Path = typer.Option(..., exists=True),
    decisions_yaml: Path = typer.Option(..., exists=True),
    name: str = "Imported Standard",
) -> None:
    """Validate three compiled YAML files without calling a model."""
    standard = parse_compiled_standard(
        {
            "schema_version": "0.2",
            "name": name,
            "labels": yaml.safe_load(labels_yaml.read_text(encoding="utf-8")),
            "definition_rules": yaml.safe_load(definitions_yaml.read_text(encoding="utf-8")),
            "decision_rules": yaml.safe_load(decisions_yaml.read_text(encoding="utf-8")),
            "conflicts": [],
        }
    )
    report = validate_standard(standard)
    console.print_json(data=report.model_dump())
    if not report.valid:
        raise typer.Exit(1)


@app.command("activate")
def activate_command(standard_id: str) -> None:
    """Activate a validated Standard version."""
    store.initialize()
    standard = store.get_standard(standard_id)
    report = validate_standard(parse_compiled_standard(standard["compiled"]))
    if not report.valid:
        console.print_json(data=report.model_dump())
        raise typer.Exit(1)
    console.print_json(data=store.activate_standard(standard_id))


@app.command("export")
def export_command(standard_id: str, output_dir: Path = Path("./compiled-standard")) -> None:
    """Export a Standard snapshot as labels/definition/decision YAML files."""
    store.initialize()
    standard = parse_compiled_standard(store.get_standard(standard_id)["compiled"])
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in standard_to_yaml_files(standard).items():
        (output_dir / filename).write_text(content, encoding="utf-8")
    console.print(f"Exported to {output_dir.resolve()}")


@app.command("import-data")
def import_data_command(path: Path = typer.Argument(..., exists=True), name: Optional[str] = None) -> None:
    """Import CSV, XLSX, TXT, or JSONL data; every row receives an internal UUID."""
    store.initialize()
    try:
        items = _parse_upload(path.name, path.read_bytes())
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print_json(data=store.create_dataset(name or path.stem, path.name, items))


@app.command("annotate")
def annotate_command(dataset_id: str, standard_id: str) -> None:
    """Run progressive-disclosure annotation synchronously."""
    store.initialize()
    run = store.create_run(dataset_id, standard_id)
    asyncio.run(service.process_run(run["id"]))
    console.print_json(data={"run": store.get_run(run["id"]), "metrics": store.run_metrics(run["id"])})


@app.command("runs")
def runs_command() -> None:
    """List annotation runs."""
    store.initialize()
    table = Table("Run", "Dataset", "Standard", "Status", "Progress")
    for run in store.list_runs():
        table.add_row(
            run["id"], run["dataset_name"], f"{run['standard_name']} v{run['standard_version']}",
            run["status"], f"{run['processed']}/{run['total']}",
        )
    console.print(table)


@app.command("mine")
def mine_command(run_id: str) -> None:
    """Cluster repeated failures and generate Rule modification suggestions."""
    store.initialize()
    console.print_json(data=asyncio.run(miner.mine(run_id)))


@app.command("review")
def review_command(annotation_id: str, human_label: str, note: str = "") -> None:
    """Save a human-reviewed label for an annotation."""
    store.initialize()
    console.print_json(data=store.review_annotation(annotation_id, human_label, note))


@app.command("revise")
def revise_command(
    standard_id: str,
    rule_id: str,
    rule_json: Path = typer.Argument(..., exists=True, readable=True),
    reason: str = typer.Option(..., "--reason", "-r"),
) -> None:
    """Create and activate a new Standard version from a human-edited Rule JSON file."""
    store.initialize()
    new_rule = json.loads(rule_json.read_text(encoding="utf-8"))
    console.print_json(
        data=service.revise_rule(standard_id, rule_id, new_rule, reason, [])
    )


@app.command("impact-rerun")
def impact_rerun_command(
    source_run_id: str,
    target_standard_id: str,
    rule_id: str,
    labels: str = typer.Option("", help="Comma-separated labels affected by the Rule"),
) -> None:
    """Re-annotate only cases impacted by a Rule change."""
    store.initialize()
    run = service.create_impact_run(
        source_run_id,
        target_standard_id,
        rule_id,
        [label.strip() for label in labels.split(",") if label.strip()],
    )
    asyncio.run(service.process_run(run["id"]))
    console.print_json(data={"run": store.get_run(run["id"]), "metrics": store.run_metrics(run["id"])})


@app.command("export-results")
def export_results_command(
    run_id: str,
    output: Path,
    gold_only: bool = False,
) -> None:
    """Export annotation results as CSV or JSONL."""
    store.initialize()
    rows = store.list_annotations(run_id)
    if gold_only:
        rows = [row for row in rows if row["route"] == "AUTO_ACCEPT" or row.get("human_label")]
    values = [
        {
            "id": row["item_id"], "text": row["text"],
            "label": row.get("human_label") or row.get("label"), "route": row["route"],
            "rules_used": row["rules_used"], "evidence": row["evidence"],
            "confidence": row["confidence"], "gold_label": row.get("gold_label"),
        }
        for row in rows
    ]
    if output.suffix.lower() == ".jsonl":
        output.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in values) + "\n", encoding="utf-8")
    elif output.suffix.lower() == ".csv":
        with output.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values[0]) if values else ["id", "text", "label", "route", "rules_used", "evidence", "confidence", "gold_label"])
            writer.writeheader()
            for row in values:
                writer.writerow({**row, "rules_used": "|".join(row["rules_used"])})
    else:
        raise typer.BadParameter("Output suffix must be .csv or .jsonl")
    console.print(f"Exported {len(values)} rows to {output.resolve()}")


@app.command("demo-data")
def demo_data_command() -> None:
    """Import the built-in demonstration dataset (model calls still require an API Key)."""
    store.initialize()
    path = Path(__file__).parent / "demo" / "data.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        result = store.create_dataset(
            store.next_dataset_name("金融与汽车演示数据"), path.name, list(csv.DictReader(stream))
        )
    console.print_json(data=result)


if __name__ == "__main__":
    app()
