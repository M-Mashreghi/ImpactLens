"""Offline evaluation harness for the analysis pipeline (no network, reproducible).

Each JSONL row: ``{"id", "title", "text", "model_output", "gold": {"event_type", "direction",
"uncertain", "issuers"}}``. The recorded ``model_output`` runs through the same schema →
evidence → resolution path as production; the report compares against gold labels.

Usage: ``python -m impactlens.intelligence.eval [dataset.jsonl] [--samples-dir DIR]``
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from impactlens.entities.models import Security
from impactlens.entities.resolver import SecurityResolver
from impactlens.intelligence.entity_pipeline import resolve_entities
from impactlens.intelligence.evidence import validate_evidence
from impactlens.intelligence.schema import AnalysisOutput
from impactlens.intelligence.taxonomy import SCHEMA_VERSION

DEFAULT_DATASET = Path("data/samples/eval/labeled_v1.jsonl")
EVAL_VERSION = "eval-v1"


def evaluate_rows(rows: list[dict], resolver: SecurityResolver) -> dict:
    per_item = []
    tp = fp = fn = 0
    type_hits = dir_hits = routing_hits = schema_failures = 0
    for row in rows:
        gold = row["gold"]
        try:
            output = AnalysisOutput.model_validate(row["model_output"])
        except ValidationError:
            schema_failures += 1
            per_item.append({"id": row["id"], "schema_valid": False, "predicted_uncertain": True})
            routing_hits += int(gold["uncertain"])
            fn += len(gold["issuers"])
            continue
        text = f"{row['title']}\n\n{row['text']}"
        report = validate_evidence(output, text)
        resolution = resolve_entities(output, resolver, set(report.supported_entities))
        uncertain = (
            output.is_uncertain
            or not report.passed
            or not resolution.impact_entities
            or output.direction.value == "uncertain"
        )
        predicted = set() if uncertain else {e.issuer_id for e in resolution.impact_entities if e.issuer_id}
        expected = set(gold["issuers"])
        tp += len(predicted & expected)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
        type_hits += int(output.event_type.value == gold["event_type"])
        dir_hits += int(output.direction.value == gold["direction"])
        routing_hits += int(uncertain == gold["uncertain"])
        per_item.append(
            {
                "id": row["id"],
                "schema_valid": True,
                "event_type": output.event_type.value,
                "event_type_correct": output.event_type.value == gold["event_type"],
                "direction_correct": output.direction.value == gold["direction"],
                "predicted_uncertain": uncertain,
                "gold_uncertain": gold["uncertain"],
                "evidence_passed": report.passed,
                "predicted_issuers": sorted(predicted),
                "gold_issuers": sorted(expected),
            }
        )
    n = len(rows)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
    return {
        "eval_version": EVAL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "n": n,
        "schema_failures": schema_failures,
        "event_type_accuracy": round(type_hits / n, 6) if n else None,
        "direction_accuracy": round(dir_hits / n, 6) if n else None,
        "uncertain_routing_accuracy": round(routing_hits / n, 6) if n else None,
        "entity_precision": round(precision, 6) if precision is not None else None,
        "entity_recall": round(recall, 6) if recall is not None else None,
        "entity_f1": round(f1, 6) if f1 is not None else None,
        "items": per_item,
    }


def load_resolver(samples_dir: Path) -> SecurityResolver:
    rows = json.loads((samples_dir / "securities.json").read_text("utf-8"))
    return SecurityResolver(Security.model_validate(r) for r in rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ImpactLens offline analysis evaluation")
    parser.add_argument("dataset", nargs="?", default=str(DEFAULT_DATASET))
    parser.add_argument("--samples-dir", default="data/samples")
    args = parser.parse_args(argv)
    rows = [json.loads(line) for line in Path(args.dataset).read_text("utf-8").splitlines() if line.strip()]
    report = evaluate_rows(rows, load_resolver(Path(args.samples_dir)))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
