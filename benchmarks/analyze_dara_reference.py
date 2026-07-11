#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def truth_rate(series: pd.Series) -> float:
    normalized = series.astype(str).str.strip().str.lower()
    return float(normalized.isin({"1", "1.0", "y", "yes", "true"}).mean())


def main() -> None:
    root = Path("benchmarks/data/dara/supplement")
    pairwise = root / "pairwise_reactions-benchmark_summary_102125.xlsx"
    precursor = root / "precursor_mixture-benchmark_summary_102125.xlsx"
    manual = root / "pairwise_reactions_manual_rietveld_summary.xlsx"

    result: dict[str, object] = {"source": "Dara paper supplementary dataset"}
    result["pairwise_fully_indexed_rate"] = {
        name.lower(): truth_rate(pd.read_excel(pairwise, sheet_name=name)["Fully indexed?"])
        for name in ("Human", "Dara", "Jade")
    }
    result["precursor_correct_rate"] = {
        name.lower(): truth_rate(pd.read_excel(precursor, sheet_name=name)["Correct?"])
        for name in ("Dara", "Jade")
    }
    notes = pd.read_excel(manual, sheet_name="Notes on fits")
    result["manual_rietveld"] = {
        "case_count": int(len(notes)),
        "median_rwp": float(notes["Rwp"].median()),
        "median_rexp": float(notes["Rexp"].median()),
        "median_gof": float(notes["GOF"].median()),
        "rwp_range": [float(notes["Rwp"].min()), float(notes["Rwp"].max())],
    }
    output = Path("benchmarks/results/dara_reference.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
