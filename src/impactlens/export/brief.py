"""Impact exports. Output is deterministic for the same stored records (no wall-clock fields).

Exports include provenance (source, URL, timestamps, content hash, evidence, snapshot id,
model/prompt/schema/scoring/rules versions, event-study config) and exclude secrets,
raw LLM responses and full position lists beyond the affected positions.
"""

from __future__ import annotations

import csv
import io
import json

from impactlens import DISCLAIMER

EXPORT_VERSION = "export-v1"
CSV_COLUMNS = [
    "impact_id",
    "news_id",
    "snapshot_id",
    "scoring_version",
    "ticker",
    "security_id",
    "relationship_type",
    "direction",
    "counted",
    "position_weight",
    "exposure_magnitude",
    "relationship_weight",
    "severity_value",
    "confidence",
    "relevance_weight",
    "signed_component",
    "absolute_component",
    "position_priority",
    "position_level",
    "path",
]


def build_export_record(impact: dict, analysis: dict, news: dict, studies: list[dict]) -> dict:
    out = analysis["analysis"] or {}
    return {
        "export_version": EXPORT_VERSION,
        "disclaimer": DISCLAIMER,
        "impact": {
            "impact_id": impact["impact_id"],
            "snapshot_id": impact["snapshot_id"],
            "portfolio_id": impact["result"]["portfolio_id"],
            "snapshot_as_of": impact["result"]["snapshot_as_of"],
            "scoring_version": impact["scoring_version"],
            "rules_version": impact["rules_version"],
            "signed_score": impact["signed_score"],
            "absolute_priority": impact["absolute_priority"],
            "impact_level": impact["impact_level"],
            "net_direction": impact["result"]["net_direction"],
            "semantics": impact["result"]["semantics"],
            "computed_at": impact["computed_at"],
            "components": impact["result"]["components"],
            "excluded": impact["result"]["excluded"],
            "scoring_config": impact["result"]["config"],
        },
        "event": {
            "analysis_id": analysis["analysis_id"],
            "status": analysis["status"],
            "event_type": analysis["event_type"],
            "event_summary": analysis["event_summary"],
            "direction": analysis["direction"],
            "severity": analysis["severity"],
            "confidence": analysis["confidence"],
            "time_horizon": analysis["time_horizon"],
            "uncertainties": out.get("uncertainties", []),
            "versions": {
                k: analysis[k] for k in ("schema_version", "prompt_version", "model_provider", "model_name")
            },
        },
        "source": {
            "news_id": news["news_id"],
            "title": news["title"],
            "source_name": news["source_name"],
            "source_url": news["source_url"],
            "canonical_url": news["canonical_url"],
            "published_at": news["published_at"],
            "published_at_quality": news["published_at_quality"],
            "retrieved_at": news["retrieved_at"],
            "content_hash": news["content_hash"],
        },
        "evidence": [c for c in impact["explanation"]["citations"]],
        "historical": [
            {
                "security_id": s["security_id"],
                "benchmark": s["benchmark_symbol"],
                "config_version": s["config_version"],
                "as_of": s["as_of"],
                "alignment": s["result"]["alignment"],
                "windows": s["result"]["windows"],
                "config": s["result"]["config"],
                "interpretation": s["result"]["interpretation"],
            }
            for s in studies
        ],
    }


def to_json(record: dict) -> str:
    return json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def to_csv(record: dict) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    imp = record["impact"]
    for comp in imp["components"]:
        writer.writerow(
            {
                "impact_id": imp["impact_id"],
                "news_id": record["source"]["news_id"],
                "snapshot_id": imp["snapshot_id"],
                "scoring_version": imp["scoring_version"],
                **comp,
            }
        )
    return buf.getvalue()


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.2f}%"


def to_markdown(record: dict) -> str:
    src, ev, imp = record["source"], record["event"], record["impact"]
    lines = [
        f"# ImpactLens Research Brief — {src['title']}",
        "",
        f"> {record['disclaimer']}",
        "",
        "## 1. Observed facts (from the source)",
        "",
        f"- **Source:** {src['source_name']}" + (f" — <{src['source_url']}>" if src["source_url"] else ""),
        f"- **Published:** {src['published_at'] or 'unknown'} (timestamp quality: `{src['published_at_quality']}`)",
        f"- **Retrieved:** {src['retrieved_at']}",
        f"- **Content hash:** `{src['content_hash']}`",
        "",
        "**Evidence quoted from the article:**",
        "",
    ]
    lines += [f"- [E{c['evidence_id']}] “{c['quote']}”" for c in record["evidence"]] or ["- (none)"]
    lines += [
        "",
        "**Model-extracted event (schema-validated, evidence-grounded):**",
        "",
        f"- Event type: `{ev['event_type']}`; direction: `{ev['direction']}`; severity: `{ev['severity']}`; "
        f"confidence: {ev['confidence']:.2f}; horizon: `{ev['time_horizon']}`",
        f"- Summary: {ev['event_summary']}",
        f"- Versions: model `{ev['versions']['model_provider']}/{ev['versions']['model_name']}`, prompt "
        f"`{ev['versions']['prompt_version']}`, schema `{ev['versions']['schema_version']}`",
        "",
        "## 2. Computed impact priority (deterministic code)",
        "",
        f"- **Impact level:** {imp['impact_level']} — absolute priority {imp['absolute_priority']:.2f}/100, "
        f"signed score {imp['signed_score']:+.2f}, net direction `{imp['net_direction']}`",
        f"- Portfolio snapshot `{imp['snapshot_id']}` (as of {imp['snapshot_as_of']}); scoring "
        f"`{imp['scoring_version']}`, exposure rules `{imp['rules_version']}`",
        f"- {imp['semantics']}",
        "",
        "| Ticker | Path | Direction | Weight | Magnitude | Rel. wt | Severity | Conf. | Relevance | Component | Counted |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for c in imp["components"]:
        lines.append(
            f"| {c['ticker']} | {c['relationship_type']}: {c['path']} | {c['direction']} | "
            f"{c['position_weight'] * 100:.2f}% | {c['exposure_magnitude']:.4f} | {c['relationship_weight']:.2f} | "
            f"{c['severity_value']:.2f} | {c['confidence']:.2f} | {c['relevance_weight']:.4f} | "
            f"{c['signed_component']:+.6f} | {'yes' if c['counted'] else 'no'} |"
        )
    if not imp["components"]:
        lines.append("| — | no exposure matched | | | | | | | | | |")
    lines += ["", "## 3. Historical association (not causal)", ""]
    if not record["historical"]:
        lines.append("No event study has been run for this news item.")
    for study in record["historical"]:
        al = study["alignment"]
        lines.append(
            f"- **{study['security_id']}** vs `{study['benchmark']}` — anchor {al['anchor_date']} "
            f"({al['session']}, policy {al['policy']}), data as of {study['as_of']}, config `{study['config_version']}`"
        )
        for w in study["windows"]:
            lines.append(
                f"  - window [{w['window'][0]},+{w['window'][1]}]: {w['status']}; security "
                f"{_fmt_pct(w['security_return'])}, benchmark {_fmt_pct(w['benchmark_return'])}, abnormal "
                f"{_fmt_pct(w['abnormal_return'])}"
            )
        lines.append(f"  - {study['interpretation']}")
    lines += ["", f"_Export format `{record['export_version']}`._", ""]
    return "\n".join(lines)
