#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from xrd.fullprof import run_fullprof_case


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AutoXRD FullProf example benchmark")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("fullprof_cases.json"))
    parser.add_argument("--examples", type=Path, default=Path.home() / ".local/share/autoxrd/fullprof/Examples")
    parser.add_argument("--fp2k", type=Path, default=Path(os.environ.get("AUTOXRD_FULLPROF_BIN", ".venv/bin/fp2k")))
    parser.add_argument("--results", type=Path, default=Path(__file__).with_name("results") / "fullprof")
    args = parser.parse_args()

    cases = json.loads(args.manifest.read_text(encoding="utf-8"))
    results = []
    for spec in cases:
        metric = run_fullprof_case(
            args.fp2k.resolve(), args.examples.expanduser(), args.results, spec["case"], spec["data"]
        )
        record = {**spec, **metric.to_dict()}
        results.append(record)
        status = "PASS" if metric.success else "FAIL"
        print(f"{status:4} {metric.case:14} {metric.runtime_seconds:7.2f}s")

    summary = {
        "case_count": len(results),
        "success_count": sum(bool(item["success"]) for item in results),
        "convergence_count": sum(bool(item["converged"]) for item in results),
        "cases": results,
    }
    args.results.mkdir(parents=True, exist_ok=True)
    (args.results / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "cases"}, indent=2))


if __name__ == "__main__":
    main()
