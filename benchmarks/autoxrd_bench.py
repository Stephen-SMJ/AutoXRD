#!/usr/bin/env python3
"""Build, materialize, validate, and score AutoXRD-Bench-100."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xrd.benchmark import (
    load_suite,
    materialize_data,
    score_predictions,
    validate_suite,
    write_baseline,
    write_suite,
)


DEFAULT_ROOT = Path(__file__).with_name("autoxrd_bench_100")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("build", help="write the deterministic public cases and oracle")
    subparsers.add_parser("validate", help="validate ids, schemas, and family counts")
    materialize = subparsers.add_parser("materialize", help="generate local pattern artifacts")
    materialize.add_argument("--dara-source", type=Path)
    materialize.add_argument("--download-iucr", action="store_true")
    score = subparsers.add_parser("score", help="score a JSONL submission")
    score.add_argument("predictions", type=Path)
    score.add_argument("--output", type=Path)
    baseline = subparsers.add_parser("baseline", help="write a format and scoring smoke baseline")
    baseline.add_argument("output", type=Path)
    args = parser.parse_args()

    if args.command == "build":
        result = write_suite(args.root)
    elif args.command == "validate":
        cases, oracle = load_suite(args.root)
        result = validate_suite(cases, oracle)
    elif args.command == "materialize":
        result = materialize_data(args.root, args.dara_source, args.download_iucr)
    elif args.command == "baseline":
        write_baseline(args.root, args.output)
        result = {"output": str(args.output), "records": 100}
    else:
        result = score_predictions(args.root, args.predictions)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = {key: value for key, value in result.items() if key != "per_case"}
            result["detail_output"] = str(args.output)
        else:
            result = {key: value for key, value in result.items() if key != "per_case"}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
