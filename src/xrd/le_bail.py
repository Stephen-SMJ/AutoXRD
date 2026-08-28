"""Validated first-run workflow for FullProf Le Bail profile matching."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from .fullprof import FullProfMetrics, run_fullprof_template
from .pcr import parse_pcr, validate_le_bail_initialization


def default_fullprof_executable() -> Path:
    for name in ("AUTOXRD_FULLPROF_BIN", "FULLPROF_BIN"):
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser()
    discovered = shutil.which("fp2k")
    if discovered:
        return Path(discovered)
    return Path("~/.local/share/autoxrd/fullprof/fp2k").expanduser()


def initialize_le_bail(executable: Path, template: Path, pattern: Path,
                       results_dir: Path, case: str = "le_bail_000",
                       timeout: float = 120.0) -> FullProfMetrics:
    document = parse_pcr(template)
    failures = validate_le_bail_initialization(document)
    if failures:
        raise ValueError("invalid Le Bail initialization template: " + "; ".join(failures))
    metrics = run_fullprof_template(executable, template, pattern, results_dir, case, timeout)
    run_dir = results_dir / case
    generated_hkl = sorted(run_dir.glob(f"{case}*.hkl"))
    if not generated_hkl:
        metrics.success = False
        metrics.warnings.append("le_bail_hkl_missing")
    result = metrics.to_dict()
    result["workflow"] = "le_bail_initialization"
    result["initialization_validated"] = True
    result["generated_hkl"] = [str(path) for path in generated_hkl]
    (run_dir / "le_bail.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a validated FullProf Le Bail initialization")
    parser.add_argument("template", type=Path)
    parser.add_argument("pattern", type=Path)
    parser.add_argument("results", type=Path)
    parser.add_argument("--case", default="le_bail_000")
    parser.add_argument("--fp2k", type=Path, default=default_fullprof_executable())
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    metrics = initialize_le_bail(args.fp2k.resolve(), args.template.resolve(),
                                 args.pattern.resolve(), args.results.resolve(),
                                 args.case, args.timeout)
    print(json.dumps(metrics.to_dict(), indent=2))


if __name__ == "__main__":
    main()
