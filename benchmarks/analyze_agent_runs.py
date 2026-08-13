#!/usr/bin/env python3
"""Export paper-ready performance/compute tables and plots from Agent runs."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


NUMERIC_FIELDS = ("score", "total_tokens", "elapsed_seconds", "agent_step_count")


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def token_total(record: dict[str, Any]) -> int | None:
    totals = record.get("token_totals")
    if isinstance(totals, dict):
        return totals.get("total_tokens")
    usage = record.get("usage")
    if isinstance(usage, dict) and usage:
        return sum(int(item.get("input_tokens", 0)) + int(item.get("output_tokens", 0))
                   for item in usage.values())
    return None


def load_run(run: Path) -> list[dict[str, Any]]:
    report_path = run / "final-report.json"
    if not report_path.exists():
        report_path = run / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    model = report.get("run", {}).get("model", run.name)
    scores = {item["id"]: item for item in report.get("per_case", [])}
    rows = []
    for path in sorted((run / "records").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        score = scores.get(record["id"], {})
        rows.append({
            "model": model,
            "case_id": record["id"],
            "difficulty": record.get("difficulty", score.get("difficulty")),
            "family": record.get("family", score.get("family")),
            "status": record.get("status"),
            "termination_reason": record.get("termination_reason"),
            "attempt": record.get("attempt", 1),
            "score": score.get("score"),
            "points": score.get("points"),
            "total_tokens": token_total(record),
            "input_tokens": record.get("token_totals", {}).get("input_tokens"),
            "output_tokens": record.get("token_totals", {}).get("output_tokens"),
            "elapsed_seconds": record.get("elapsed_seconds"),
            "api_duration_seconds": record.get("api_duration_seconds"),
            "tool_duration_seconds": record.get("tool_duration_seconds"),
            "model_turn_count": record.get("model_turn_count"),
            "tool_calls_requested": record.get("tool_calls_requested",
                                                record.get("tool_call_count")),
            "tool_calls_executed": record.get("tool_calls_executed",
                                               record.get("tool_call_count")),
            "agent_step_count": record.get("agent_step_count"),
            "api_attempt_count": record.get("api_attempt_count"),
            "api_retry_count": record.get("api_retry_count"),
            "token_reporting_complete": record.get("token_reporting_complete"),
        })
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["model"], "overall", "overall")].append(row)
        groups[(row["model"], "difficulty", str(row["difficulty"]))].append(row)
        groups[(row["model"], "family", str(row["family"]))].append(row)
    result = []
    for (model, group_type, group), items in sorted(groups.items()):
        scored = [item for item in items if isinstance(item["score"], (int, float))]
        result.append({
            "model": model, "group_type": group_type, "group": group, "tasks": len(items),
            "performance_percent": 100 * mean(item["score"] for item in scored) if scored else None,
            "ok_rate_percent": 100 * mean(item["status"] == "ok" for item in items),
            "mean_tokens": mean(item["total_tokens"] for item in items
                                if item["total_tokens"] is not None) if any(
                                    item["total_tokens"] is not None for item in items) else None,
            "mean_seconds": mean(item["elapsed_seconds"] for item in items
                                 if item["elapsed_seconds"] is not None),
            "mean_steps": mean(item["agent_step_count"] for item in items
                               if item["agent_step_count"] is not None) if any(
                                   item["agent_step_count"] is not None for item in items) else None,
            "total_tokens": sum(item["total_tokens"] or 0 for item in items),
            "total_seconds": sum(item["elapsed_seconds"] or 0 for item in items),
        })
    return result


def correlations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    from scipy.stats import pearsonr, spearmanr

    output: dict[str, Any] = {}
    for model in sorted({row["model"] for row in rows}):
        output[model] = {}
        selected = [row for row in rows if row["model"] == model]
        for predictor in ("total_tokens", "elapsed_seconds", "agent_step_count"):
            pairs = [(row[predictor], row["score"]) for row in selected
                     if isinstance(row[predictor], (int, float))
                     and isinstance(row["score"], (int, float))]
            if len(pairs) < 3 or len({x for x, _ in pairs}) < 2 or len({y for _, y in pairs}) < 2:
                output[model][predictor] = {"n": len(pairs), "pearson": None, "spearman": None}
                continue
            xs, ys = zip(*pairs)
            output[model][predictor] = {
                "n": len(pairs), "pearson": float(pearsonr(xs, ys).statistic),
                "spearman": float(spearmanr(xs, ys).statistic),
            }
    return output


def plots(summary: list[dict[str, Any]], output: Path) -> None:
    import matplotlib.pyplot as plt

    overall = [row for row in summary if row["group_type"] == "overall"]
    for x_field, label, log_scale in (
        ("mean_tokens", "Mean tokens per task", True),
        ("mean_seconds", "Mean wall time per task (s)", False),
        ("mean_steps", "Mean agent steps per task", False),
    ):
        points = [row for row in overall if isinstance(row[x_field], (int, float))
                  and isinstance(row["performance_percent"], (int, float))]
        if not points:
            continue
        figure, axis = plt.subplots(figsize=(7.2, 4.8))
        axis.scatter([row[x_field] for row in points],
                     [row["performance_percent"] for row in points], s=45)
        for row in points:
            axis.annotate(row["model"], (row[x_field], row["performance_percent"]),
                          xytext=(4, 4), textcoords="offset points", fontsize=8)
        if log_scale and all(row[x_field] > 0 for row in points):
            axis.set_xscale("log")
        axis.set_xlabel(label)
        axis.set_ylabel("Benchmark performance (%)")
        axis.grid(alpha=0.25)
        figure.tight_layout()
        figure.savefig(output / f"performance_vs_{x_field.removeprefix('mean_')}.png", dpi=180)
        plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = [row for run in args.runs for row in load_run(run)]
    summary = summarize(rows)
    write_csv(args.output / "task_metrics.csv", rows)
    write_csv(args.output / "model_summary.csv", summary)
    atomic_json(args.output / "correlations.json", correlations(rows))
    if not args.no_plots:
        plots(summary, args.output)
    print(json.dumps({"runs": len(args.runs), "tasks": len(rows), "output": str(args.output)}))


if __name__ == "__main__":
    main()
