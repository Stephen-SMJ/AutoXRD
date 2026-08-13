"""Construction and scoring for the tiered AutoXRD-Bench-100 v2 suite."""

from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from .benchmark import _DARA_ROWS, _IUCR_QPA, _IUCR_ROOT, _action, _snapshot, _write_residual_pattern
from .pattern import analyze_pattern, read_pattern, read_xrdml
from .residual import analyze_residual, read_residual_table
from .schemas import ActionKind, RefinementStage
from .trajectory import evaluate_transition, validate_action


BENCHMARK_ID = "autoxrd-bench-100-v2"
EXPECTED_DIFFICULTIES = {"easy": 30, "medium": 40, "hard": 30}
EXPECTED_FAMILIES = {
    "easy_action_reasoning": 10,
    "easy_gate_reasoning": 10,
    "easy_residual_reasoning": 10,
    "medium_residual_report": 20,
    "medium_trajectory_report": 10,
    "medium_experimental_report": 10,
    "hard_metric_recovery": 10,
    "hard_qpa": 10,
    "hard_phase_identification": 10,
}

ARTIFACTS = (
    ("zero_shift", "refine_zero"),
    ("background_curvature", "refine_background"),
    ("peak_broadening", "refine_profile"),
    ("low_angle_asymmetry", "refine_asymmetry"),
    ("impurity_peaks", "add_phase"),
    ("preferred_orientation", "refine_preferred_orientation"),
    ("limited_range", "request_broader_2theta_range"),
    ("high_noise", "reacquire_higher_counts"),
)


@lru_cache(maxsize=40)
def _residual_metric_truth(material_index: int, artifact_index: int) -> dict[str, float | int]:
    """Run the deterministic analyzer on the generated pattern to create numeric Judge anchors."""
    with tempfile.TemporaryDirectory(prefix="autoxrd-truth-") as directory:
        path = Path(directory) / "pattern.xye"
        _write_residual_pattern(path, material_index, artifact_index)
        features = analyze_residual(*read_residual_table(path))
    return {
        "point_count": features.point_count,
        "rwp": round(features.rwp, 8),
        "normalized_absolute_residual": round(features.normalized_absolute_residual, 8),
        "lag1_autocorrelation": round(features.lag1_autocorrelation, 8),
        "low_angle_signed_bias": round(features.low_angle_signed_bias, 8),
        "high_angle_signed_bias": round(features.high_angle_signed_bias, 8),
        "structured_region_fraction": round(features.structured_region_fraction, 8),
        "unexplained_peak_ratio": round(features.unexplained_peak_ratio, 8),
    }


def _case(case_id: str, difficulty: str, family: str, split: str, question: str,
          input_data: dict[str, Any], response_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": case_id,
        "difficulty": difficulty,
        "family": family,
        "split": split,
        "question": question,
        "input": input_data,
        "response_schema": response_schema,
    }


def _easy_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    oracle: dict[str, Any] = {}
    actions = (
        _action(),
        _action(ActionKind.REFINE_ZERO, RefinementStage.INSTRUMENT, ("zero",)),
        _action(ActionKind.REFINE_LATTICE, RefinementStage.STRUCTURE, ("cell_a",)),
        _action(ActionKind.REFINE_OCCUPANCY, RefinementStage.STRUCTURE, ("occupancy_Fe",)),
        _action(ActionKind.REFINE_OCCUPANCY, RefinementStage.STRUCTURE, ("occupancy_Fe",),
                {"occupancy_Fe": (0.0, 1.0)}),
        _action(ActionKind.REFINE_BISO, RefinementStage.STRUCTURE, ("biso_Fe", "occupancy_Fe"),
                {"biso_Fe": (0.0, 5.0), "occupancy_Fe": (0.0, 1.0)}),
        _action(ActionKind.REFINE_ZERO, RefinementStage.INSTRUMENT, ("zero", "cell_a")),
        _action(ActionKind.ADD_PHASE, RefinementStage.PROFILE_MATCH, ("phase_2",)),
        _action(ActionKind.REFINE_SIZE_STRAIN, RefinementStage.MICROSTRUCTURE,
                ("size", "strain"), {"size": (1.0, 10000.0), "strain": (0.0, 0.1)}),
        _action(ActionKind.REFINE_ORIENTATION, RefinementStage.INSTRUMENT, ("march_dollase",),
                {"march_dollase": (0.2, 5.0)}),
    )
    action_options = [
        {"id": "A", "text": "The action contract is admissible."},
        {"id": "B", "text": "The action contract must be rejected."},
        {"id": "C", "text": "The action is not allowed at this refinement stage."},
        {"id": "D", "text": "A high-risk parameter is missing explicit bounds."},
        {"id": "E", "text": "The parameter list mixes unrelated mechanisms."},
        {"id": "F", "text": "The action is automatically valid because evidence is present."},
        {"id": "G", "text": "All structure parameters should be released together."},
        {"id": "H", "text": "Bounds may be omitted for every occupancy refinement."},
        {"id": "I", "text": "The action must remain isolated from unrelated refinement mechanisms."},
    ]
    violation_to_option = {
        "action_not_allowed_in_stage": "C",
        "high_risk_action_requires_bounds": "D",
        "parameters_span_multiple_mechanisms": "E",
    }
    for index, action in enumerate(actions, 1):
        failures = list(validate_action(action))
        selected = (["A"] if not failures else ["B"]) + [
            violation_to_option[item] for item in failures if item in violation_to_option
        ] + ["I"]
        case_id = f"easy-action-{index:03d}"
        cases.append(_case(
            case_id, "easy", "easy_action_reasoning", "controlled",
            "Select every scientifically correct statement about this proposed refinement action.",
            {"action": asdict(action), "options": action_options, "selection_rule": "select_all_that_apply"},
            {"selected_options": ["option_id"]},
        ))
        oracle[case_id] = {"selected_options": selected, "explanation": failures or ["valid_contract"]}
        oracle[case_id]["ground_truth_source"] = "deterministic typed-action validator"

    before = _snapshot()
    after_variants = [
        _snapshot(rwp=10.8, residual_score=0.18),
        _snapshot(rwp=11.2, residual_score=0.22),
        _snapshot(rwp=11.8, residual_score=0.28),
        _snapshot(rwp=12.6, residual_score=0.20),
        _snapshot(rwp=10.9, residual_score=0.19, physical_violations=("negative_biso",)),
        _snapshot(rwp=10.7, residual_score=0.17, max_abs_correlation=0.997),
        _snapshot(rwp=11.0, residual_score=0.20, unexplained_peak_ratio=0.15),
        _snapshot(rwp=12.2, residual_score=0.19, parameter_count=30),
        _snapshot(rwp=10.5, residual_score=0.15),
        _snapshot(rwp=11.9, residual_score=0.24),
    ]
    gate_options = [
        {"id": "A", "text": "Accept the transition."},
        {"id": "B", "text": "Reject the transition."},
        {"id": "C", "text": "The declared residual prediction is satisfied."},
        {"id": "D", "text": "The declared residual prediction is not satisfied."},
        {"id": "E", "text": "A hard physical violation blocks acceptance."},
        {"id": "F", "text": "Excessive parameter correlation blocks acceptance."},
        {"id": "G", "text": "Lower Rwp alone guarantees acceptance."},
        {"id": "H", "text": "A failed falsifiable prediction can be ignored."},
    ]
    for index, after in enumerate(after_variants, 1):
        action = _action()
        decision = evaluate_transition(before, after, action)
        selected = ["A" if decision.accepted else "B"]
        selected.append("D" if "falsifiable_prediction_not_satisfied" in decision.reasons else "C")
        if "physical_violation" in " ".join(decision.reasons):
            selected.append("E")
        if "correlation" in " ".join(decision.reasons):
            selected.append("F")
        case_id = f"easy-gate-{index:03d}"
        cases.append(_case(
            case_id, "easy", "easy_gate_reasoning", "controlled",
            "Select every correct conclusion about whether this trajectory edge should be accepted.",
            {"before": asdict(before), "after": asdict(after), "action": asdict(action),
             "options": gate_options, "selection_rule": "select_all_that_apply"},
            {"selected_options": ["option_id"]},
        ))
        oracle[case_id] = {"selected_options": selected, "reference_decision": asdict(decision)}
        oracle[case_id]["ground_truth_source"] = "deterministic physical trajectory gate"

    diagnosis_options = [
        {"id": chr(65 + i), "text": f"Dominant mechanism: {mechanism}."}
        for i, (mechanism, _) in enumerate(ARTIFACTS)
    ] + [
        {"id": chr(73 + i), "text": f"Supported next action: {action}."}
        for i, (_, action) in enumerate(ARTIFACTS)
    ] + [
        {"id": "Q", "text": "Release occupancies and displacement parameters simultaneously."},
        {"id": "R", "text": "Accept the fit solely because several peaks are visible."},
    ]
    easy_pairs = [(1 + (index - 1) % 5, index) for index in range(1, 9)] + [(4, 1), (5, 8)]
    for index, (material_index, artifact_index) in enumerate(easy_pairs, 1):
        mechanism, action = ARTIFACTS[artifact_index - 1]
        case_id = f"easy-residual-{index:03d}"
        cases.append(_case(
            case_id, "easy", "easy_residual_reasoning", "controlled",
            "Select all options supported by the observed-minus-calculated residual. Incorrect extra selections count as errors.",
            {"pattern": f"data/residual/residual-{material_index:02d}-{artifact_index:02d}.xye",
             "columns": ["two_theta_deg", "observed", "calculated"],
             "options": diagnosis_options, "selection_rule": "select_all_that_apply"},
            {"selected_options": ["option_id"]},
        ))
        oracle[case_id] = {"selected_options": [chr(64 + artifact_index), chr(72 + artifact_index)],
                           "diagnosis": mechanism, "action": action,
                           "ground_truth_source": "deterministic single-defect generator"}
    return cases, oracle


def _medium_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    oracle: dict[str, Any] = {}
    easy_pairs = {(1 + (index - 1) % 5, index) for index in range(1, 9)} | {(4, 1), (5, 8)}
    residual_pairs = [(material, artifact) for material in range(1, 6) for artifact in range(1, 9)
                      if (material, artifact) not in easy_pairs][:20]
    for index, (material_index, artifact_index) in enumerate(residual_pairs, 1):
        mechanism, action = ARTIFACTS[artifact_index - 1]
        case_id = f"medium-residual-{index:03d}"
        cases.append(_case(
            case_id, "medium", "medium_residual_report", "controlled",
            "Write a concise scientific diagnosis. State the dominant residual mechanism, cite the key computed metrics or morphology, recommend the next action, and explain one tempting but wrong action.",
            {"pattern": f"data/residual/residual-{material_index:02d}-{artifact_index:02d}.xye",
             "columns": ["two_theta_deg", "observed", "calculated"],
             "material": ("CeO2", "LaB6", "rutile", "PbSO4", "Tb2BaCoO5")[material_index - 1]},
            {"conclusion": "string", "diagnosis": "string", "recommended_action": "string",
             "key_metrics": {"metric_name": "number"}, "rejected_alternative": "string"},
        ))
        oracle[case_id] = {
            "reference_answer": f"The dominant mechanism is {mechanism}; the next isolated action is {action}.",
            "required_facts": [mechanism, action, "uses observed-minus-calculated evidence"],
            "forbidden_claims": ["release all parameters", "Rwp alone proves correctness"],
            "reference_metrics": _residual_metric_truth(material_index, artifact_index),
            "ground_truth_source": "deterministic generator followed by xrd.residual.analyze_residual",
            "judge_rubric": "Score diagnosis, metric-grounded evidence, action appropriateness, and rejection of a wrong mechanism.",
        }

    before = _snapshot()
    variants = [
        _snapshot(rwp=10.8, residual_score=0.18),
        _snapshot(rwp=11.8, residual_score=0.28),
        _snapshot(rwp=12.8, residual_score=0.20),
        _snapshot(rwp=10.7, residual_score=0.17, physical_violations=("negative_biso",)),
        _snapshot(rwp=10.9, residual_score=0.19, max_abs_correlation=0.997),
        _snapshot(rwp=11.0, residual_score=0.20, unexplained_peak_ratio=0.16),
        _snapshot(rwp=12.1, residual_score=0.19, parameter_count=32),
        _snapshot(rwp=10.4, residual_score=0.14),
        _snapshot(rwp=11.5, residual_score=0.23),
        _snapshot(rwp=10.6, residual_score=0.17, physical_violations=("occupancy_sum",)),
    ]
    for index, after in enumerate(variants, 1):
        action = _action()
        decision = evaluate_transition(before, after, action)
        case_id = f"medium-trajectory-{index:03d}"
        cases.append(_case(
            case_id, "medium", "medium_trajectory_report", "controlled",
            "Give an evidence-based accept/reject conclusion for this trajectory edge. Discuss prediction satisfaction, fit change, complexity, physical validity, and the next controlled experiment.",
            {"before": asdict(before), "after": asdict(after), "action": asdict(action)},
            {"conclusion": "string", "accepted": "boolean", "key_metrics": {"metric_name": "number"},
             "physical_assessment": "string", "next_experiment": "string"},
        ))
        oracle[case_id] = {
            "reference_answer": f"The edge is {'accepted' if decision.accepted else 'rejected'} for: "
                                + (", ".join(decision.reasons) or "all hard gates and predictions pass"),
            "required_facts": [f"accepted={decision.accepted}", *decision.reasons],
            "forbidden_claims": ["lower Rwp overrides physical violations"],
            "ground_truth_source": "deterministic physical trajectory gate",
            "judge_rubric": "Score decision correctness, numerical evidence, physics, and a falsifiable next step.",
        }

    experimental = [
        ("cpd-4", tuple(_IUCR_QPA["4"][0]), "microabsorption"),
        ("bauxite", ("quartz", "boehmite", "anatase", "goethite", "kaolinite", "gibbsite", "hematite"), "complex_mixture"),
        ("granodio", ("quartz", "feldspar", "albite", "biotite", "clinochlore", "hornblende", "zircon"), "natural_sample"),
        ("pharm1gr", ("mannitol", "sucrose", "dl-valine", "starch", "nizatidine"), "pharmaceutical_mixture"),
        ("pharm2gr", ("mannitol", "sucrose", "dl-valine", "starch", "nizatidine"), "pharmaceutical_mixture"),
        ("corundum", ("corundum",), "none"),
        ("fluorite", ("fluorite",), "none"),
        ("zincite", ("zincite",), "none"),
        ("brucite", ("brucite",), "preferred_orientation_reference"),
        ("magnetit", ("magnetite",), "microabsorption_reference"),
    ]
    all_experimental_phases = sorted({phase for _, phases, _ in experimental for phase in phases}
                                     | {"calcite", "rutile", "spinel", "silicon"})
    for index, (stem, phases, artifact) in enumerate(experimental, 1):
        case_id = f"medium-experimental-{index:03d}"
        input_data = {"pattern": f"data/iucr/{stem}.cpi", "instrument": "Cu Kalpha Bragg-Brentano",
                      "candidate_phases": all_experimental_phases}
        reference = f"Supported phases are {', '.join(phases)}; the reference artifact is {artifact}."
        facts = [*phases, artifact]
        cases.append(_case(
            case_id, "medium", "medium_experimental_report", "experimental",
            "Provide a defensible phase-analysis conclusion, identify ambiguity or specimen effects, cite key pattern evidence, and state what refinement or measurement would test the conclusion.",
            input_data,
            {"conclusion": "string", "supported_phases": ["string"], "key_metrics": {"metric_name": "number"},
             "uncertainty": "string", "verification_step": "string"},
        ))
        oracle[case_id] = {
            "reference_answer": reference,
            "required_facts": facts,
            "forbidden_claims": ["all candidate phases are present", "absence of unexplained peaks without analysis"],
            "ground_truth_source": "IUCr CPD quantitative phase-analysis round robin reference",
            "judge_rubric": "Score phase conclusion, quantitative evidence, calibrated uncertainty, and verification design.",
        }
    return cases, oracle


def _hard_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    oracle: dict[str, Any] = {}
    for index in range(1, 11):
        if index <= 5:
            mechanisms = ["zero_shift", "background_curvature"]
            parameters = {"zero_shift_deg": 0.075 + 0.025 * index,
                          "background_quadratic": 0.045 + 0.012 * index}
            baseline = {"zero_shift_deg": 0.0, "background_quadratic": 0.0}
            normalizers = {"zero_shift_deg": 0.20, "background_quadratic": 0.12}
        else:
            j = index - 5
            mechanisms = ["peak_broadening", "impurity_peaks"]
            parameters = {"broadening_factor": 1.25 + 0.12 * j,
                          "impurity_peak_1_deg": 25.3 + 0.37 * j,
                          "impurity_peak_2_deg": 60.8 - 0.29 * j}
            baseline = {"broadening_factor": 1.0, "impurity_peak_1_deg": 40.0,
                        "impurity_peak_2_deg": 40.0}
            normalizers = {"broadening_factor": 1.0, "impurity_peak_1_deg": 20.0,
                           "impurity_peak_2_deg": 20.0}
        case_id = f"hard-recovery-{index:03d}"
        cases.append(_case(
            case_id, "hard", "hard_metric_recovery", "controlled",
            "Analyze the mixed-defect residual, identify every supported mechanism, estimate the physical correction parameters, and justify a staged recovery plan. Do not fit an arbitrary curve to the observations.",
            {"pattern": f"data/hard_recovery/{case_id}.xye",
             "columns": ["two_theta_deg", "observed", "calculated"],
             "allowed_parameters": list(parameters), "call_budget": 20},
            {"diagnosed_mechanisms": ["string"], "parameter_estimates": {"parameter": "number"},
             "recovery_plan": ["string"], "report": "string"},
        ))
        oracle[case_id] = {
            "mechanisms": mechanisms, "parameters": parameters, "baseline_parameters": baseline,
            "parameter_normalizers": normalizers,
            "reference_answer": f"Recover {', '.join(mechanisms)} in separate stages and estimate {parameters}.",
            "ground_truth_source": "deterministic mixed-defect generator parameters",
            "judge_rubric": "Judge mechanism-aware staging, physical reasoning, uncertainty, and resistance to overfitting; numerical accuracy is scored separately.",
        }

    qpa_samples = list(_IUCR_QPA.items())[:10]
    all_qpa_phases = sorted({phase for _, (fractions, _) in qpa_samples for phase in fractions}
                            | {"quartz", "calcite", "rutile", "spinel", "silicon"})
    for index, (sample, (fractions, artifact)) in enumerate(qpa_samples, 1):
        case_id = f"hard-qpa-{index:03d}"
        cases.append(_case(
            case_id, "hard", "hard_qpa", "experimental",
            "Perform quantitative phase analysis from the pattern. Return only supported phases, normalized weight fractions, the dominant artifact, uncertainty, and a scientific report.",
            {"pattern": f"data/iucr/cpd-{sample}.cpi", "candidate_phases": all_qpa_phases,
             "instrument": "Cu Kalpha, Bragg-Brentano, graphite monochromator", "fraction_sum": 1.0},
            {"phases": ["string"], "weight_fractions": {"phase": "fraction_0_to_1"},
             "artifact": "string", "uncertainty": {"phase": "standard_uncertainty"}, "report": "string"},
        ))
        oracle[case_id] = {
            "phases": list(fractions), "weight_fractions": fractions, "artifact": artifact,
            "reference_answer": f"Published weighed fractions are {fractions}; artifact={artifact}.",
            "ground_truth_source": "IUCr CPD quantitative phase-analysis round robin weighed sample",
            "metric_baselines": {"phase_f1": 0.0, "fraction_mae": 0.25, "fraction_rmse": 0.30},
            "judge_rubric": "Judge interpretation, uncertainty calibration, artifact awareness, and whether claims match the quantitative result.",
        }

    all_dara_phases = sorted({phase for row in _DARA_ROWS for phase in row[2]}
                             | {"TiO2", "Y2O3", "Fe2O3", "ZnWO4"})
    for index, (reactants, temperature, phases, fully_indexed) in enumerate(_DARA_ROWS, 1):
        case_id = f"hard-phase-{index:03d}"
        cases.append(_case(
            case_id, "hard", "hard_phase_identification", "experimental",
            "Identify all supported phases under the candidate library, preserve unknown when warranted, quantify confidence, and propose a Rietveld verification sequence.",
            {"pattern": f"data/dara/dara-{index:03d}.xy", "reactants": reactants,
             "temperature_c": temperature, "candidate_phases": all_dara_phases},
            {"phases": ["string"], "fully_indexed": "boolean", "confidence": {"phase": "0_to_1"},
             "verification_sequence": ["string"], "report": "string"},
        ))
        oracle[case_id] = {
            "phases": list(phases), "fully_indexed": fully_indexed,
            "reference_answer": f"Reference phases are {phases}; fully_indexed={fully_indexed}.",
            "ground_truth_source": "Dara benchmark manual Rietveld/indexing reference",
            "metric_baselines": {"phase_f1": 0.0},
            "judge_rubric": "Judge phase reasoning, unknown handling, confidence calibration, and the verification sequence.",
        }
    return cases, oracle


def build_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    oracle: dict[str, Any] = {}
    for builder in (_easy_cases, _medium_cases, _hard_cases):
        new_cases, new_oracle = builder()
        cases.extend(new_cases)
        oracle.update(new_oracle)
    validate_suite(cases, oracle)
    return cases, oracle


def validate_suite(cases: list[dict[str, Any]], oracle: dict[str, Any]) -> dict[str, Any]:
    ids = [case.get("id") for case in cases]
    if len(cases) != 100 or len(set(ids)) != 100 or set(ids) != set(oracle):
        raise ValueError("benchmark must contain exactly 100 unique public/oracle pairs")
    difficulties = Counter(case.get("difficulty") for case in cases)
    families = Counter(case.get("family") for case in cases)
    if dict(difficulties) != EXPECTED_DIFFICULTIES:
        raise ValueError(f"unexpected difficulty distribution: {dict(difficulties)}")
    if dict(families) != EXPECTED_FAMILIES:
        raise ValueError(f"unexpected family distribution: {dict(families)}")
    for case in cases:
        if case["difficulty"] == "easy":
            options = case["input"].get("options", [])
            correct = oracle[case["id"]].get("selected_options", [])
            if len(options) < 5 or len(options) - len(correct) < 4:
                raise ValueError(f"{case['id']} needs at least four distractors")
    return {"benchmark_id": BENCHMARK_ID, "case_count": 100,
            "difficulties": dict(difficulties), "families": dict(families)}


def write_suite(root: Path) -> dict[str, Any]:
    cases, oracle = build_cases()
    root.mkdir(parents=True, exist_ok=True)
    (root / "cases.jsonl").write_text(
        "".join(json.dumps(case, sort_keys=True) + "\n" for case in cases), encoding="utf-8")
    (root / "oracle.json").write_text(
        json.dumps({"benchmark_id": BENCHMARK_ID, "answers": oracle}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    manifest = {
        "benchmark_id": BENCHMARK_ID,
        "case_count": 100,
        "difficulty_counts": EXPECTED_DIFFICULTIES,
        "family_counts": EXPECTED_FAMILIES,
        "overall_weights": {"easy": 0.30, "medium": 0.40, "hard": 0.30},
        "judge_policy": {"repeats": 3, "aggregation": "median per dimension",
                         "medium_weight": 1.0, "hard_explanation_weight": "0.20-0.25"},
        "hard_normalization": {
            "higher_is_better": "clip((metric-baseline)/(oracle-baseline),0,1)",
            "lower_is_better": "clip((baseline-metric)/(baseline-oracle),0,1)",
            "policy": "oracle and baseline are frozen; never normalize against participating models",
        },
        "sources": {
            "controlled": "Deterministic AutoXRD v2 generators",
            "iucr_qarr_data": "https://www.iucr.org/__data/iucr/powder/QARR/data-kit.htm",
            "iucr_qarr_results": "https://www.iucr.org/__data/iucr/powder/QARR/results.htm",
            "dara": "https://github.com/CederGroupHub/dara",
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                         encoding="utf-8")
    return validate_suite(cases, oracle)


def load_suite(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases = [json.loads(line) for line in (root / "cases.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    oracle = json.loads((root / "oracle.json").read_text(encoding="utf-8"))["answers"]
    validate_suite(cases, oracle)
    return cases, oracle


def _base_profile(x: float, material_index: int, broaden: float = 1.0, shift: float = 0.0) -> float:
    value = 80.0 + 0.35 * (x - 10.0)
    for j in range(10):
        center = 16 + 6.7 * j + material_index * 0.73 + (j % 3) * 1.19
        amplitude = 400 + 170 * ((j + material_index) % 5)
        sigma = (0.10 + 0.025 * ((j + 2) % 4)) * broaden
        value += amplitude * math.exp(-0.5 * ((x - (center + shift)) / sigma) ** 2)
    return value


def _write_hard_recovery(path: Path, index: int, truth: dict[str, float]) -> None:
    rng = random.Random(84000 + index)
    rows = []
    for point in range(2001):
        x = 10.0 + 0.04 * point
        calculated = _base_profile(x, 1 + (index - 1) % 5)
        if index <= 5:
            observed = _base_profile(x, 1 + (index - 1) % 5, shift=truth["zero_shift_deg"])
            observed += truth["background_quadratic"] * (x - 52.0) ** 2
        else:
            observed = _base_profile(x, 1 + (index - 1) % 5,
                                     broaden=truth["broadening_factor"])
            observed += 500 * math.exp(-0.5 * ((x - truth["impurity_peak_1_deg"]) / 0.13) ** 2)
            observed += 360 * math.exp(-0.5 * ((x - truth["impurity_peak_2_deg"]) / 0.16) ** 2)
        observed += rng.gauss(0.0, 6.0)
        rows.append((x, max(0.0, observed), calculated))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii") as stream:
        stream.write("# two_theta_deg observed calculated\n")
        for row in rows:
            stream.write(f"{row[0]:.4f} {row[1]:.6f} {row[2]:.6f}\n")


def materialize_data(root: Path, dara_source: Path | None = None,
                     download_iucr: bool = False) -> dict[str, Any]:
    del download_iucr  # The pinned downloader remains the supported IUCr acquisition path.
    cases, oracle = load_suite(root)
    for material in range(1, 6):
        for artifact in range(1, 9):
            _write_residual_pattern(root / f"data/residual/residual-{material:02d}-{artifact:02d}.xye",
                                    material, artifact)
    for index in range(1, 11):
        case_id = f"hard-recovery-{index:03d}"
        _write_hard_recovery(root / f"data/hard_recovery/{case_id}.xye", index,
                             oracle[case_id]["parameters"])
    if dara_source is None:
        dara_source = Path("benchmarks/data/dara/supplement/pairwise_reactions_patterns")
    dara_ready = 0
    for index, row in enumerate(_DARA_ROWS, 1):
        target = root / f"data/dara/dara-{index:03d}.xy"
        source = dara_source / f"{row[0]}_{row[1]}C_60min.xrdml"
        if source.is_file():
            pattern = read_xrdml(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# two_theta_deg intensity\n" + "".join(
                f"{x:.6f} {y:.6f}\n" for x, y in zip(pattern.two_theta, pattern.intensity)),
                encoding="ascii")
        dara_ready += int(target.is_file())
    status = {"residual_ready": 40, "hard_recovery_ready": 10, "dara_ready": dara_ready,
              "iucr_ready": sum((root / f"data/iucr/cpd-{sample}.cpi").is_file()
                                for sample in list(_IUCR_QPA)[:10])}
    required = sorted({case["input"].get("pattern") for case in cases
                       if case["input"].get("pattern")})
    status["checksums"] = {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in required if (root / relative).is_file()
    }
    report = root / "data/materialization.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return status


def validate_data(root: Path) -> dict[str, Any]:
    cases, _ = load_suite(root)
    paths = sorted({case["input"].get("pattern") for case in cases if case["input"].get("pattern")})
    failures = []
    for relative in paths:
        try:
            analyze_pattern(read_pattern(root / relative))
        except Exception as exc:
            failures.append(f"{relative}: {exc}")
    if failures:
        raise ValueError(f"benchmark data are not ready ({len(failures)} failures): {'; '.join(failures[:5])}")
    return {"benchmark_id": BENCHMARK_ID, "unique_pattern_count": len(paths), "ready": True}


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    return {"al2o3": "corundum", "caf2": "fluorite", "zno": "zincite",
            "amorphous": "glass", "unknownphase": "unknown"}.get(text, text)


def _set_f1(expected: Iterable[str], predicted: Any) -> float:
    if not isinstance(predicted, list):
        return 0.0
    left, right = {_norm(x) for x in expected}, {_norm(x) for x in predicted}
    return 1.0 if not left and not right else (2 * len(left & right) / (len(left) + len(right))
                                                if left and right else 0.0)


def _fraction_errors(expected: dict[str, float], predicted: Any) -> tuple[float, float]:
    if not isinstance(predicted, dict) or any(not isinstance(v, (int, float)) or not math.isfinite(v)
                                              or v < 0 or v > 1 for v in predicted.values()):
        return 1.0, 1.0
    p = {_norm(k): float(v) for k, v in predicted.items()}
    keys = {_norm(k) for k in expected} | set(p)
    errors = [p.get(k, 0.0) - next((v for name, v in expected.items() if _norm(name) == k), 0.0)
              for k in keys]
    return sum(abs(e) for e in errors) / len(errors), math.sqrt(sum(e * e for e in errors) / len(errors))


def _utility(metric: float, baseline: float, oracle: float, higher: bool) -> float:
    denominator = (oracle - baseline) if higher else (baseline - oracle)
    numerator = (metric - baseline) if higher else (baseline - metric)
    return max(0.0, min(1.0, numerator / denominator)) if denominator > 0 else float(metric == oracle)


def _judge_score(case_id: str, judgments: dict[str, list[dict[str, Any]]]) -> tuple[float, dict[str, Any]]:
    rows = judgments.get(case_id, [])
    if not rows:
        return 0.0, {"judge_missing": True}
    dimensions = ("scientific_correctness", "evidence_grounding", "action_quality", "completeness")
    values = {name: median([max(0, min(4, float(row.get(name, 0)))) for row in rows])
              for name in dimensions}
    fatal = median([float(bool(row.get("fatal_error", False))) for row in rows]) >= 0.5
    score = sum(values.values()) / (4 * len(values))
    if fatal:
        score = min(score, 0.25)
    return score, {"judge_dimensions": values, "judge_repeats": len(rows), "judge_fatal": fatal}


def _load_judgments(path: Path | None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if path is None:
        return grouped
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            grouped[row["id"]].append(row["judgment"])
    return grouped


def _score_case(case: dict[str, Any], expected: dict[str, Any], predicted: dict[str, Any],
                judgments: dict[str, list[dict[str, Any]]]) -> tuple[float, dict[str, Any]]:
    difficulty = case["difficulty"]
    if difficulty == "easy":
        expected_set = set(expected["selected_options"])
        predicted_set = set(predicted.get("selected_options", [])) if isinstance(predicted.get("selected_options"), list) else set()
        exact = float(expected_set == predicted_set)
        return exact, {"exact_option_set": exact, "option_f1": _set_f1(expected_set, list(predicted_set))}
    judge, judge_components = _judge_score(case["id"], judgments)
    if difficulty == "medium":
        return judge, judge_components
    family = case["family"]
    if family == "hard_metric_recovery":
        f1 = _set_f1(expected["mechanisms"], predicted.get("diagnosed_mechanisms"))
        estimates = predicted.get("parameter_estimates", {})
        if not isinstance(estimates, dict):
            estimates = {}
        numeric = {
            name: estimates.get(name, expected["baseline_parameters"][name])
            for name in expected["parameters"]
        }
        if any(not isinstance(value, (int, float)) or not math.isfinite(value)
               for value in numeric.values()):
            mae = rmse = 1.0
        else:
            normalized_errors = [
                (float(numeric[name]) - truth) / expected["parameter_normalizers"][name]
                for name, truth in expected["parameters"].items()
            ]
            mae = sum(abs(x) for x in normalized_errors) / len(normalized_errors)
            rmse = math.sqrt(sum(x * x for x in normalized_errors) / len(normalized_errors))
        base_errors = [(expected["baseline_parameters"][name] - truth) / expected["parameter_normalizers"][name]
                       for name, truth in expected["parameters"].items()]
        base_mae = sum(abs(x) for x in base_errors) / len(base_errors)
        base_rmse = math.sqrt(sum(x * x for x in base_errors) / len(base_errors))
        mae_u, rmse_u = _utility(mae, base_mae, 0.0, False), _utility(rmse, base_rmse, 0.0, False)
        score = 0.30 * f1 + 0.25 * mae_u + 0.20 * rmse_u + 0.25 * judge
        return score, {"mechanism_f1": f1, "normalized_parameter_mae": mae,
                       "normalized_parameter_rmse": rmse, "mae_utility": mae_u,
                       "rmse_utility": rmse_u, **judge_components}
    phase_f1 = _set_f1(expected["phases"], predicted.get("phases"))
    if family == "hard_qpa":
        mae, rmse = _fraction_errors(expected["weight_fractions"], predicted.get("weight_fractions"))
        mae_u = _utility(mae, expected["metric_baselines"]["fraction_mae"], 0.0, False)
        rmse_u = _utility(rmse, expected["metric_baselines"]["fraction_rmse"], 0.0, False)
        artifact = float(_norm(predicted.get("artifact")) == _norm(expected["artifact"]))
        score = 0.25 * phase_f1 + 0.25 * mae_u + 0.15 * rmse_u + 0.15 * artifact + 0.20 * judge
        return score, {"phase_f1": phase_f1, "fraction_mae": mae, "fraction_rmse": rmse,
                       "fraction_mae_utility": mae_u, "fraction_rmse_utility": rmse_u,
                       "artifact_exact": artifact, **judge_components}
    indexed = float(predicted.get("fully_indexed") is expected["fully_indexed"])
    unknown = float(("unknown" in {_norm(x) for x in predicted.get("phases", [])})
                    == ("unknown" in {_norm(x) for x in expected["phases"]}))
    score = 0.45 * phase_f1 + 0.15 * indexed + 0.15 * unknown + 0.25 * judge
    return score, {"phase_f1": phase_f1, "fully_indexed_exact": indexed,
                   "unknown_handling": unknown, **judge_components}


def score_predictions(root: Path, predictions_path: Path,
                      judgments_path: Path | None = None) -> dict[str, Any]:
    cases, oracle = load_suite(root)
    predictions: dict[str, dict[str, Any]] = {}
    for line in predictions_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["id"] in predictions:
            raise ValueError(f"duplicate prediction id: {row['id']}")
        predictions[row["id"]] = row.get("answer", {})
    unknown = set(predictions) - {case["id"] for case in cases}
    if unknown:
        raise ValueError(f"unknown prediction ids: {sorted(unknown)[:5]}")
    judgments = _load_judgments(judgments_path)
    per_case = []
    for case in cases:
        answer = predictions.get(case["id"], {})
        score, components = _score_case(case, oracle[case["id"]], answer, judgments)
        per_case.append({"id": case["id"], "difficulty": case["difficulty"],
                         "family": case["family"], "split": case["split"], "score": score,
                         "points": score, "components": components, "missing": case["id"] not in predictions})
    by_difficulty = {difficulty: sum(x["score"] for x in per_case if x["difficulty"] == difficulty)
                     / EXPECTED_DIFFICULTIES[difficulty] for difficulty in EXPECTED_DIFFICULTIES}
    by_family = {family: sum(x["score"] for x in per_case if x["family"] == family) / count
                 for family, count in EXPECTED_FAMILIES.items()}
    overall = sum(x["score"] for x in per_case)  # 100 cases, one point each.
    judged_ids = {case_id for case_id, rows in judgments.items() if rows}
    required_judgments = sum(case["difficulty"] != "easy" for case in cases)
    def component_mean(family: str, name: str) -> float | None:
        values = [x["components"][name] for x in per_case
                  if x["family"] == family and name in x["components"]]
        return sum(values) / len(values) if values else None
    aggregate_metrics = {
        "hard_qpa_phase_f1": component_mean("hard_qpa", "phase_f1"),
        "hard_qpa_fraction_mae": component_mean("hard_qpa", "fraction_mae"),
        "hard_qpa_fraction_rmse": component_mean("hard_qpa", "fraction_rmse"),
        "hard_phase_identification_f1": component_mean("hard_phase_identification", "phase_f1"),
        "hard_recovery_mechanism_f1": component_mean("hard_metric_recovery", "mechanism_f1"),
        "hard_recovery_normalized_parameter_mae": component_mean(
            "hard_metric_recovery", "normalized_parameter_mae"),
        "hard_recovery_normalized_parameter_rmse": component_mean(
            "hard_metric_recovery", "normalized_parameter_rmse"),
    }
    return {
        "benchmark_id": BENCHMARK_ID,
        "overall_score_percent": overall,
        "by_difficulty_percent": {key: 100 * value for key, value in by_difficulty.items()},
        "by_family_percent": {key: 100 * value for key, value in by_family.items()},
        "submitted": len(predictions), "missing": 100 - len(predictions),
        "judged_cases": len(judged_ids & {case["id"] for case in cases}),
        "required_judged_cases": required_judgments,
        "provisional": len(judged_ids) < required_judgments,
        "aggregate_metrics": aggregate_metrics,
        "per_case": per_case,
    }


def write_baseline(root: Path, output: Path) -> None:
    cases, oracle = load_suite(root)
    rows = []
    for case in cases:
        if case["difficulty"] == "easy":
            answer = {"selected_options": [case["input"]["options"][0]["id"]]}
        elif case["difficulty"] == "medium":
            answer = {"conclusion": "Insufficient evidence.", "key_metrics": {}}
        elif case["family"] == "hard_metric_recovery":
            expected = oracle[case["id"]]
            answer = {"diagnosed_mechanisms": [], "parameter_estimates": expected["baseline_parameters"],
                      "recovery_plan": [], "report": "No analysis."}
        elif case["family"] == "hard_qpa":
            answer = {"phases": [], "weight_fractions": {}, "artifact": "none", "report": "No analysis."}
        else:
            answer = {"phases": [], "fully_indexed": True, "report": "No analysis."}
        rows.append({"id": case["id"], "answer": answer})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
