#!/usr/bin/env python3
"""Run a reproducible two-node FullProf profile-matching smoke workflow."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from xrd.fullprof import run_fullprof_template
from xrd.le_bail import initialize_le_bail
from xrd.pcr import compile_action, parse_pcr
from xrd.residual import analyze_residual, read_fullprof_prf
from xrd.schemas import (
    ActionKind, Evidence, FalsifiablePrediction, FitSnapshot, RefinementAction, RefinementStage,
)
from xrd.trajectory import evaluate_transition


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    examples = Path.home() / ".local/share/autoxrd/fullprof/Examples"
    parser.add_argument("--template", type=Path, default=examples / "tbba.pcr")
    parser.add_argument("--pattern", type=Path, default=examples / "tbbaco.dat")
    parser.add_argument("--fp2k", type=Path,
                        default=Path(os.environ.get("AUTOXRD_FULLPROF_BIN", ".venv/bin/fp2k")))
    parser.add_argument("--results", type=Path,
                        default=Path(__file__).with_name("results") / "le_bail_workflow")
    args = parser.parse_args()
    if args.results.exists() and any(args.results.iterdir()):
        raise FileExistsError(f"results directory must be new or empty: {args.results}")

    initial = initialize_le_bail(
        args.fp2k.resolve(), args.template.expanduser().resolve(), args.pattern.expanduser().resolve(),
        args.results, "le_bail_000",
    )
    initial_dir = args.results / "le_bail_000"
    updated_pcr = initial_dir / "le_bail_000.new"
    generated_hkl = sorted(initial_dir.glob("le_bail_000*.hkl"))
    if not updated_pcr.is_file() or not generated_hkl:
        raise RuntimeError("Le Bail initialization did not generate the next PCR and HKL files")
    document = parse_pcr(updated_pcr)
    initial_residual = analyze_residual(*read_fullprof_prf(initial_dir / "le_bail_000.prf"))
    action = RefinementAction(
        kind=ActionKind.REFINE_BACKGROUND,
        stage=RefinementStage.PROFILE_MATCH,
        parameters=("background.b0", "background.b1"),
        rationale="Test low-order background terms after the zero-parameter Le Bail initialization.",
        evidence=(Evidence("absolute_low_angle_bias", abs(initial_residual.low_angle_signed_bias),
                           "le_bail_000/le_bail_000.prf", ">0.005"),),
        predictions=(FalsifiablePrediction("absolute_low_angle_bias", "decrease", 0.002),),
        parent_run_id="le_bail_000",
    )
    compiled, compilation = compile_action(
        document, action, ("background.b0", "background.b1"),
    )
    staging = args.results / "compiled"
    staging.mkdir(parents=True, exist_ok=False)
    compiled_path = staging / "le_bail_001.pcr"
    compiled_path.write_text(compiled, encoding="latin-1")
    (staging / "action.json").write_text(json.dumps(asdict(action), indent=2), encoding="utf-8")
    (staging / "compilation.json").write_text(json.dumps(compilation, indent=2), encoding="utf-8")

    auxiliary_files = {
        path.name.replace("le_bail_000", "le_bail_001", 1): path for path in generated_hkl
    }
    refined = run_fullprof_template(
        args.fp2k.resolve(), compiled_path, args.pattern.expanduser().resolve(), args.results,
        "le_bail_001", auxiliary_files=auxiliary_files,
    )
    refined_dir = args.results / "le_bail_001"
    refined_residual = analyze_residual(*read_fullprof_prf(refined_dir / "le_bail_001.prf"))
    if initial.final_pattern is None or refined.final_pattern is None:
        raise RuntimeError("FullProf returned no final pattern metrics")
    before = FitSnapshot(
        rwp=initial.final_pattern.rwp, rexp=initial.final_pattern.rexp,
        gof=initial.final_pattern.rwp / initial.final_pattern.rexp,
        residual_score=initial_residual.normalized_absolute_residual,
        unexplained_peak_ratio=initial_residual.unexplained_peak_ratio,
        parameter_count=0,
        features={"absolute_low_angle_bias": abs(initial_residual.low_angle_signed_bias)},
    )
    after = FitSnapshot(
        rwp=refined.final_pattern.rwp, rexp=refined.final_pattern.rexp,
        gof=refined.final_pattern.rwp / refined.final_pattern.rexp,
        residual_score=refined_residual.normalized_absolute_residual,
        unexplained_peak_ratio=refined_residual.unexplained_peak_ratio,
        parameter_count=compilation["refined_groups"],
        features={"absolute_low_angle_bias": abs(refined_residual.low_angle_signed_bias)},
    )
    decision = evaluate_transition(before, after, action)
    summary = {
        "initial": initial.to_dict(),
        "initial_residual": initial_residual.to_dict(),
        "background_action": refined.to_dict(),
        "background_action_residual": refined_residual.to_dict(),
        "gate_decision": asdict(decision),
        "rwp_change": ((refined.final_pattern.rwp - initial.final_pattern.rwp)
                       if initial.final_pattern and refined.final_pattern else None),
        "note": "The action is accepted only if the mechanism prediction and total utility pass.",
    }
    (args.results / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({
        "initial_success": initial.success,
        "initial_rwp": initial.final_pattern.rwp if initial.final_pattern else None,
        "refined_success": refined.success,
        "refined_rwp": refined.final_pattern.rwp if refined.final_pattern else None,
        "rwp_change": summary["rwp_change"],
        "mechanism_supported": decision.mechanism_supported,
        "accepted": decision.accepted,
        "reasons": decision.reasons,
    }, indent=2))


if __name__ == "__main__":
    main()
