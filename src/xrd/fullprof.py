from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


_CONVENTIONAL_RE = re.compile(
    r"Conventional Rietveld Rp,Rwp,Re and Chi2:\s*"
    r"([\d.Ee+-]+)\s+([\d.Ee+-]+)\s+([\d.Ee+-]+)\s+([\d.Ee+-]+)"
)
_BRAGG_RE = re.compile(
    r"Bragg R-factor:\s*([\d.Ee+-]+)"
    r"(?:[^\n]*?Fract\(%\):\s*([\d.Ee+-]+))?"
)
_GLOBAL_CHI_RE = re.compile(r"Global user-weigthed Chi2 \(Bragg contrib\.\):\s*([\d.Ee+-]+)")
_SAFE_CASE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class PatternMetric:
    rp: float
    rwp: float
    rexp: float
    chi2: float


@dataclass(frozen=True)
class PhaseMetric:
    bragg_r: float
    fraction_percent: float | None = None


@dataclass
class FullProfMetrics:
    case: str
    success: bool
    returncode: int
    runtime_seconds: float
    converged: bool = False
    patterns: list[PatternMetric] = field(default_factory=list)
    final_pattern: PatternMetric | None = None
    phases: list[PhaseMetric] = field(default_factory=list)
    global_chi2: float | None = None
    warnings: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _finite(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite FullProf metric: {value}")
    return number


def parse_fullprof_output(case: str, workdir: Path, returncode: int, runtime: float) -> FullProfMetrics:
    output_path = workdir / f"{case}.out"
    log_path = workdir / f"{case}.log"
    text = output_path.read_text(encoding="latin-1", errors="replace") if output_path.exists() else ""
    log_text = log_path.read_text(encoding="latin-1", errors="replace") if log_path.exists() else ""

    conventional = [
        PatternMetric(*(_finite(value) for value in match.groups()))
        for match in _CONVENTIONAL_RE.finditer(text)
    ]
    # FullProf repeats the final block near the end. Preserve one metric per unique pattern.
    patterns: list[PatternMetric] = []
    for metric in conventional:
        if metric not in patterns:
            patterns.append(metric)

    phases: list[PhaseMetric] = []
    for match in _BRAGG_RE.finditer(text):
        metric = PhaseMetric(
            bragg_r=_finite(match.group(1)),
            fraction_percent=_finite(match.group(2)) if match.group(2) else None,
        )
        if metric not in phases:
            phases.append(metric)

    global_values = [_finite(match.group(1)) for match in _GLOBAL_CHI_RE.finditer(text)]
    combined = f"{text}\n{log_text}".lower()
    warnings = []
    for needle, label in (
        ("singular matrix", "singular_matrix"),
        ("negative intensity", "negative_intensity"),
        ("refinement diverged", "divergence_reported"),
        ("nan", "non_finite_value_reported"),
    ):
        if needle in combined:
            warnings.append(label)

    artifacts = {
        suffix: str(workdir / f"{case}.{suffix}")
        for suffix in ("pcr", "new", "out", "sum", "prf", "log", "hkl")
        if (workdir / f"{case}.{suffix}").exists()
    }
    converged = "convergence reached" in combined
    return FullProfMetrics(
        case=case,
        success=returncode == 0 and output_path.exists() and bool(patterns) and not warnings,
        returncode=returncode,
        runtime_seconds=runtime,
        converged=converged,
        patterns=patterns,
        final_pattern=patterns[-1] if patterns else None,
        phases=phases,
        global_chi2=global_values[-1] if global_values else None,
        warnings=warnings,
        artifacts=artifacts,
    )


def run_fullprof_case(
    executable: Path,
    source_dir: Path,
    results_dir: Path,
    case: str,
    data_code: str,
    timeout: float = 120.0,
) -> FullProfMetrics:
    workdir = results_dir / case
    workdir.mkdir(parents=True, exist_ok=True)
    for source in source_dir.iterdir():
        if source.is_file():
            shutil.copy2(source, workdir / source.name)

    started = time.monotonic()
    try:
        completed = subprocess.run(
            [str(executable), case, data_code, case],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        returncode = completed.returncode
        (workdir / "runner.stdout").write_text(completed.stdout, encoding="utf-8")
        (workdir / "runner.stderr").write_text(completed.stderr, encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        (workdir / "runner.stderr").write_text(str(exc), encoding="utf-8")

    metrics = parse_fullprof_output(case, workdir, returncode, time.monotonic() - started)
    (workdir / "metrics.json").write_text(json.dumps(metrics.to_dict(), indent=2), encoding="utf-8")
    return metrics


def run_fullprof_template(
    executable: Path,
    template: Path,
    pattern: Path,
    results_dir: Path,
    case: str,
    timeout: float = 120.0,
    auxiliary_files: dict[str, Path] | None = None,
) -> FullProfMetrics:
    """Run a specific PCR and pattern without copying an entire example directory."""
    if not _SAFE_CASE_RE.fullmatch(case) or case in {".", ".."}:
        raise ValueError("case must be a safe filename of at most 128 characters")
    if not template.is_file() or not pattern.is_file():
        raise FileNotFoundError("FullProf template and pattern must be regular files")
    workdir = results_dir / case
    if workdir.exists() and any(workdir.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty run directory: {workdir}")
    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, workdir / f"{case}.pcr")
    shutil.copy2(pattern, workdir / f"{case}.dat")
    for name, source in (auxiliary_files or {}).items():
        if Path(name).name != name or name in {".", ".."}:
            raise ValueError(f"unsafe auxiliary filename: {name}")
        if not source.is_file():
            raise FileNotFoundError(f"FullProf auxiliary file does not exist: {source}")
        shutil.copy2(source, workdir / name)

    started = time.monotonic()
    try:
        completed = subprocess.run(
            [str(executable), case, case, case], cwd=workdir, capture_output=True,
            text=True, timeout=timeout, errors="replace",
        )
        returncode = completed.returncode
        (workdir / "runner.stdout").write_text(completed.stdout, encoding="utf-8")
        (workdir / "runner.stderr").write_text(completed.stderr, encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        (workdir / "runner.stderr").write_text(str(exc), encoding="utf-8")

    metrics = parse_fullprof_output(case, workdir, returncode, time.monotonic() - started)
    (workdir / "metrics.json").write_text(json.dumps(metrics.to_dict(), indent=2), encoding="utf-8")
    return metrics
