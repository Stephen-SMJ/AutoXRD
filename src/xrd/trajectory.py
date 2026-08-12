"""Evidence-gated state transitions and append-only trajectory storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .schemas import (
    ActionKind,
    FitSnapshot,
    GateDecision,
    RefinementAction,
    RefinementStage,
    content_hash,
)


_ALLOWED_STAGES: dict[ActionKind, frozenset[RefinementStage]] = {
    ActionKind.REFINE_SCALE: frozenset({RefinementStage.PROFILE_MATCH, RefinementStage.INSTRUMENT}),
    ActionKind.REFINE_ZERO: frozenset({RefinementStage.PROFILE_MATCH, RefinementStage.INSTRUMENT}),
    ActionKind.REFINE_BACKGROUND: frozenset({RefinementStage.PROFILE_MATCH, RefinementStage.INSTRUMENT}),
    ActionKind.REFINE_LATTICE: frozenset({RefinementStage.PROFILE_MATCH, RefinementStage.INSTRUMENT}),
    ActionKind.REFINE_PROFILE: frozenset({RefinementStage.PROFILE_MATCH, RefinementStage.INSTRUMENT}),
    ActionKind.REFINE_ASYMMETRY: frozenset({RefinementStage.PROFILE_MATCH, RefinementStage.INSTRUMENT}),
    ActionKind.REFINE_POSITIONS: frozenset({RefinementStage.STRUCTURE}),
    ActionKind.REFINE_BISO: frozenset({RefinementStage.STRUCTURE}),
    ActionKind.REFINE_OCCUPANCY: frozenset({RefinementStage.STRUCTURE}),
    ActionKind.REFINE_ORIENTATION: frozenset({RefinementStage.STRUCTURE, RefinementStage.MICROSTRUCTURE}),
    ActionKind.REFINE_SIZE_STRAIN: frozenset({RefinementStage.MICROSTRUCTURE}),
    ActionKind.FREEZE_PARAMETER: frozenset(set(RefinementStage) - {RefinementStage.QC}),
    ActionKind.ADD_PHASE: frozenset({RefinementStage.PROFILE_MATCH, RefinementStage.STRUCTURE}),
    ActionKind.REMOVE_PHASE: frozenset({RefinementStage.PROFILE_MATCH, RefinementStage.STRUCTURE}),
    ActionKind.EXCLUDE_REGION: frozenset({RefinementStage.PROFILE_MATCH, RefinementStage.INSTRUMENT}),
    ActionKind.SWITCH_PROFILE: frozenset({RefinementStage.PROFILE_MATCH, RefinementStage.INSTRUMENT}),
}

_HIGH_RISK_ACTIONS = {
    ActionKind.REFINE_POSITIONS,
    ActionKind.REFINE_BISO,
    ActionKind.REFINE_OCCUPANCY,
    ActionKind.REFINE_ORIENTATION,
    ActionKind.REFINE_SIZE_STRAIN,
}

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_action(action: RefinementAction) -> tuple[str, ...]:
    failures: list[str] = []
    if action.stage not in _ALLOWED_STAGES[action.kind]:
        failures.append("action_not_allowed_in_stage")
    if action.kind in _HIGH_RISK_ACTIONS and not action.bounds:
        failures.append("high_risk_action_requires_bounds")
    normalized = {parameter.lower() for parameter in action.parameters}
    if any("occup" in item for item in normalized) and any("biso" in item for item in normalized):
        failures.append("occupancy_and_biso_cannot_be_released_together")
    if any("zero" in item for item in normalized) and any(
        token in item for item in normalized for token in ("cell", "lattice", "wavelength")
    ):
        failures.append("zero_and_cell_or_wavelength_cannot_be_released_together")
    return tuple(sorted(set(failures)))


def _metric(snapshot: FitSnapshot, name: str) -> float | None:
    aliases = {
        "rwp": snapshot.rwp,
        "gof": snapshot.gof,
        "residual_score": snapshot.residual_score,
        "unexplained_peak_ratio": snapshot.unexplained_peak_ratio,
        "parameter_count": float(snapshot.parameter_count),
    }
    return aliases.get(name.lower(), snapshot.features.get(name))


def _prediction_result(before: FitSnapshot, after: FitSnapshot, metric: str,
                       direction: str, minimum_change: float) -> bool:
    old = _metric(before, metric)
    new = _metric(after, metric)
    if old is None or new is None:
        return False
    change = new - old
    return change >= minimum_change if direction == "increase" else -change >= minimum_change


def scientific_utility(snapshot: FitSnapshot) -> float:
    """A scale-stable utility for ordering, never a substitute for hard gates."""
    fit = snapshot.rwp / max(snapshot.rexp, 1e-9)
    complexity = 0.002 * snapshot.parameter_count
    correlation = max(0.0, (snapshot.max_abs_correlation or 0.0) - 0.90) * 10
    return -(fit + 2.0 * snapshot.residual_score + 3.0 * snapshot.unexplained_peak_ratio
             + complexity + correlation + 10.0 * len(snapshot.physical_violations))


def evaluate_transition(before: FitSnapshot, after: FitSnapshot,
                        action: RefinementAction) -> GateDecision:
    reasons = list(validate_action(action))
    satisfied: list[str] = []
    failed: list[str] = []
    for prediction in action.predictions:
        label = f"{prediction.metric}:{prediction.direction}:{prediction.minimum_change:g}"
        if _prediction_result(before, after, prediction.metric, prediction.direction,
                              prediction.minimum_change):
            satisfied.append(label)
        else:
            failed.append(label)

    new_violations = sorted(set(after.physical_violations) - set(before.physical_violations))
    if new_violations:
        reasons.append("new_physical_violation:" + ",".join(new_violations))
    if after.rwp > before.rwp * 1.02:
        reasons.append("rwp_regressed_beyond_budget")
    if after.unexplained_peak_ratio > before.unexplained_peak_ratio + 0.02:
        reasons.append("unexplained_peaks_regressed_beyond_budget")
    if after.max_abs_correlation is not None and after.max_abs_correlation > 0.98:
        reasons.append("severe_parameter_correlation")

    mechanism_supported = bool(satisfied) and not failed
    if not mechanism_supported:
        reasons.append("falsifiable_prediction_not_satisfied")
    utility_delta = scientific_utility(after) - scientific_utility(before)
    if utility_delta <= 0:
        reasons.append("no_multi_objective_utility_gain")
    accepted = not reasons
    return GateDecision(
        accepted=accepted,
        mechanism_supported=mechanism_supported,
        reasons=tuple(sorted(set(reasons))),
        satisfied_predictions=tuple(satisfied),
        failed_predictions=tuple(failed),
        utility_delta=utility_delta,
    )


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(data, indent=2, sort_keys=True))
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TrajectoryStore:
    """Append-only run ledger with a hash chain over scientific decisions."""

    def __init__(self, root: Path):
        self.root = root
        self.manifest_path = root / "trajectory.json"

    def load(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {"schema_version": 1, "head_hash": None, "runs": []}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def append(self, run_id: str, action: RefinementAction, before: FitSnapshot,
               after: FitSnapshot, decision: GateDecision,
               artifacts: dict[str, str] | None = None) -> dict[str, Any]:
        if not _RUN_ID_RE.fullmatch(run_id) or run_id in {".", ".."}:
            raise ValueError("run id must be a safe filename of at most 128 characters")
        manifest = self.load()
        if any(run["run_id"] == run_id for run in manifest["runs"]):
            raise ValueError(f"duplicate run id: {run_id}")
        parent_hash = manifest["head_hash"]
        artifact_paths = artifacts or {}
        artifact_hashes: dict[str, str] = {}
        for name, raw_path in artifact_paths.items():
            path = Path(raw_path)
            if not path.is_absolute():
                path = self.root / path
            if path.is_file():
                artifact_hashes[name] = _file_hash(path)
        payload = {
            "run_id": run_id,
            "parent_hash": parent_hash,
            "action": asdict(action),
            "before": asdict(before),
            "after": asdict(after),
            "decision": asdict(decision),
            "artifacts": artifact_paths,
            "artifact_hashes": artifact_hashes,
        }
        payload["run_hash"] = content_hash(payload)
        run_dir = self.root / "runs" / run_id
        _atomic_json(run_dir / "record.json", payload)
        manifest["runs"].append(payload)
        manifest["head_hash"] = payload["run_hash"]
        _atomic_json(self.manifest_path, manifest)
        return payload

    def verify(self) -> tuple[str, ...]:
        manifest = self.load()
        failures: list[str] = []
        parent_hash = None
        for run in manifest["runs"]:
            run_id = run.get("run_id")
            recorded_hash = run.get("run_hash")
            payload = {key: value for key, value in run.items() if key != "run_hash"}
            if run.get("parent_hash") != parent_hash:
                failures.append(f"{run_id}:broken_parent_hash")
            if recorded_hash != content_hash(payload):
                failures.append(f"{run_id}:content_hash_mismatch")
            record_path = self.root / "runs" / str(run_id) / "record.json"
            if not record_path.is_file():
                failures.append(f"{run_id}:record_missing")
            else:
                try:
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    failures.append(f"{run_id}:record_unreadable")
                else:
                    if record != run:
                        failures.append(f"{run_id}:record_manifest_mismatch")
            for name, expected_hash in run.get("artifact_hashes", {}).items():
                path = Path(run.get("artifacts", {}).get(name, ""))
                if not path.is_absolute():
                    path = self.root / path
                if not path.is_file():
                    failures.append(f"{run_id}:artifact_missing:{name}")
                elif _file_hash(path) != expected_hash:
                    failures.append(f"{run_id}:artifact_hash_mismatch:{name}")
            parent_hash = recorded_hash
        if manifest.get("head_hash") != parent_hash:
            failures.append("manifest_head_mismatch")
        return tuple(failures)


def action_from_dict(data: dict[str, Any]) -> RefinementAction:
    from .schemas import Evidence, FalsifiablePrediction

    return RefinementAction(
        kind=ActionKind(data["kind"]),
        stage=RefinementStage(data["stage"]),
        parameters=tuple(data["parameters"]),
        rationale=data["rationale"],
        evidence=tuple(Evidence(**item) for item in data["evidence"]),
        predictions=tuple(FalsifiablePrediction(**item) for item in data["predictions"]),
        bounds={key: tuple(value) for key, value in data.get("bounds", {}).items()},
        parent_run_id=data.get("parent_run_id"),
    )


def snapshot_from_dict(data: dict[str, Any]) -> FitSnapshot:
    return FitSnapshot(
        rwp=float(data["rwp"]), rexp=float(data["rexp"]), gof=float(data["gof"]),
        residual_score=float(data["residual_score"]),
        unexplained_peak_ratio=float(data["unexplained_peak_ratio"]),
        physical_violations=tuple(data.get("physical_violations", ())),
        parameter_count=int(data.get("parameter_count", 0)),
        max_abs_correlation=(float(data["max_abs_correlation"])
                             if data.get("max_abs_correlation") is not None else None),
        features={key: float(value) for key, value in data.get("features", {}).items()},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate or verify an AutoXRD trajectory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate_parser = subparsers.add_parser("evaluate", help="gate a proposed transition")
    evaluate_parser.add_argument("spec", type=Path)
    verify_parser = subparsers.add_parser("verify", help="verify an append-only trajectory")
    verify_parser.add_argument("trajectory", type=Path)
    args = parser.parse_args()
    if args.command == "evaluate":
        data = json.loads(args.spec.read_text(encoding="utf-8"))
        decision = evaluate_transition(
            snapshot_from_dict(data["before"]), snapshot_from_dict(data["after"]),
            action_from_dict(data["action"]),
        )
        print(json.dumps(asdict(decision), indent=2))
    else:
        failures = TrajectoryStore(args.trajectory).verify()
        print(json.dumps({"valid": not failures, "failures": failures}, indent=2))


if __name__ == "__main__":
    main()
