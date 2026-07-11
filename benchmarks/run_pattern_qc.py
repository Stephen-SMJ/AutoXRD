#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import statistics
import zipfile
from collections import Counter
from pathlib import Path

from xrd.pattern import analyze_pattern, read_json_pattern, read_pattern


def summarize(records: list[dict[str, object]], corpus: str) -> dict[str, object]:
    warnings = Counter(item for record in records for item in record["warnings"])
    return {
        "corpus": corpus,
        "pattern_count": len(records),
        "parse_success_rate": 1.0,
        "median_point_count": statistics.median(record["point_count"] for record in records),
        "median_step": statistics.median(record["median_step"] for record in records),
        "median_peak_count": statistics.median(record["detected_peak_count"] for record in records),
        "warning_counts": dict(warnings),
    }


def opxrd_sample(archive: Path, limit: int) -> list[dict[str, object]]:
    records = []
    with zipfile.ZipFile(archive) as bundle:
        names = sorted(name for name in bundle.namelist() if name.endswith(".json"))
        stride = max(1, len(names) // limit)
        for name in names[::stride][:limit]:
            with bundle.open(name) as stream:
                pattern = read_json_pattern(json.load(io.TextIOWrapper(stream, encoding="utf-8")))
            records.append({"source": name, **analyze_pattern(pattern).to_dict()})
    return records


def xrdml_corpus(directory: Path) -> list[dict[str, object]]:
    return [
        {"source": str(path), **analyze_pattern(read_pattern(path)).to_dict()}
        for path in sorted(directory.rglob("*.xrdml"))
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="QC benchmark for experimental XRD corpora")
    parser.add_argument("--opxrd", type=Path, default=Path("benchmarks/data/opxrd/opxrd.zip"))
    parser.add_argument("--opxrd-limit", type=int, default=500)
    parser.add_argument("--dara", type=Path, default=Path("benchmarks/data/dara/supplement"))
    parser.add_argument("--results", type=Path, default=Path("benchmarks/results/pattern_qc"))
    args = parser.parse_args()
    args.results.mkdir(parents=True, exist_ok=True)

    corpora = {
        "opxrd": opxrd_sample(args.opxrd, args.opxrd_limit),
        "dara": xrdml_corpus(args.dara),
    }
    summary = {name: summarize(records, name) for name, records in corpora.items()}
    for name, records in corpora.items():
        (args.results / f"{name}.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    (args.results / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
