from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from xrd.schemas import (
    ActionKind,
    Evidence,
    FalsifiablePrediction,
    FitSnapshot,
    RefinementAction,
    RefinementStage,
)
from xrd.trajectory import TrajectoryStore, evaluate_transition, validate_action


def zero_action() -> RefinementAction:
    return RefinementAction(
        kind=ActionKind.REFINE_ZERO,
        stage=RefinementStage.INSTRUMENT,
        parameters=("zero_shift",),
        rationale="Observed peaks have a nearly constant position offset.",
        evidence=(Evidence("absolute_position_bias", 0.12, "run_001/residual.json", ">0.05"),),
        predictions=(FalsifiablePrediction("absolute_position_bias", "decrease", 0.05),),
        bounds={"zero_shift": (-0.25, 0.25)},
    )


def snapshot(**changes) -> FitSnapshot:
    base = FitSnapshot(
        rwp=12.0, rexp=5.0, gof=2.4, residual_score=0.20,
        unexplained_peak_ratio=0.10, parameter_count=8,
        features={"absolute_position_bias": 0.12},
    )
    return replace(base, **changes)


def test_evidence_gate_accepts_supported_intervention():
    decision = evaluate_transition(
        snapshot(),
        snapshot(rwp=10.5, gof=2.1, residual_score=0.14,
                 features={"absolute_position_bias": 0.03}),
        zero_action(),
    )
    assert decision.accepted
    assert decision.mechanism_supported


def test_lower_rwp_does_not_override_failed_mechanism_or_physics():
    decision = evaluate_transition(
        snapshot(),
        snapshot(rwp=8.0, residual_score=0.12,
                 physical_violations=("negative_biso",),
                 features={"absolute_position_bias": 0.11}),
        zero_action(),
    )
    assert not decision.accepted
    assert not decision.mechanism_supported
    assert "falsifiable_prediction_not_satisfied" in decision.reasons
    assert any(reason.startswith("new_physical_violation") for reason in decision.reasons)


def test_invalid_parameter_coupling_is_rejected():
    action = replace(zero_action(), parameters=("zero_shift", "lattice_a"))
    assert "zero_and_cell_or_wavelength_cannot_be_released_together" in validate_action(action)


def test_high_risk_action_requires_bounds():
    action = RefinementAction(
        ActionKind.REFINE_OCCUPANCY, RefinementStage.STRUCTURE, ("occupancy_Fe",),
        "Intensity evidence supports an occupancy test.",
        (Evidence("family_intensity_bias", 0.2, "residual.json", ">0.1"),),
        (FalsifiablePrediction("residual_score", "decrease", 0.01),),
    )
    assert "high_risk_action_requires_bounds" in validate_action(action)


def test_trajectory_hash_chain_detects_tampering(tmp_path: Path):
    store = TrajectoryStore(tmp_path)
    artifact = tmp_path / "result.prf"
    artifact.write_text("original result", encoding="utf-8")
    before = snapshot()
    after = snapshot(rwp=10.5, residual_score=0.14,
                     features={"absolute_position_bias": 0.03})
    decision = evaluate_transition(before, after, zero_action())
    store.append("run_001", zero_action(), before, after, decision,
                 artifacts={"prf": "result.prf"})
    assert store.verify() == ()

    artifact.write_text("altered result", encoding="utf-8")
    assert "run_001:artifact_hash_mismatch:prf" in store.verify()
    artifact.write_text("original result", encoding="utf-8")

    manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    manifest["runs"][0]["after"]["rwp"] = 1.0
    store.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert "run_001:content_hash_mismatch" in store.verify()
    assert "run_001:record_manifest_mismatch" in store.verify()


def test_trajectory_rejects_unsafe_run_id(tmp_path: Path):
    store = TrajectoryStore(tmp_path)
    before = snapshot()
    after = snapshot(rwp=10.5, residual_score=0.14,
                     features={"absolute_position_bias": 0.03})
    decision = evaluate_transition(before, after, zero_action())
    with pytest.raises(ValueError, match="safe filename"):
        store.append("../outside", zero_action(), before, after, decision)


def test_action_requires_evidence_and_prediction():
    with pytest.raises(ValueError, match="evidence"):
        RefinementAction(
            ActionKind.REFINE_SCALE, RefinementStage.INSTRUMENT, ("scale",), "test", (),
            (FalsifiablePrediction("rwp", "decrease"),),
        )
