"""Deterministic construction and scoring for AutoXRD-Bench-100."""

from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .pattern import analyze_pattern, read_pattern, read_xrdml
from .schemas import (
    ActionKind,
    Evidence,
    FalsifiablePrediction,
    FitSnapshot,
    RefinementAction,
    RefinementStage,
)
from .trajectory import evaluate_transition, validate_action


BENCHMARK_ID = "autoxrd-bench-100-v1"
EXPECTED_COUNTS = {
    "action_contract": 10,
    "trajectory_gate": 20,
    "residual_diagnosis": 40,
    "iucr_qpa": 20,
    "dara_phase_identification": 10,
}

_ARTIFACTS = (
    ("zero_shift", "refine_zero"),
    ("background_curvature", "refine_background"),
    ("peak_broadening", "refine_profile"),
    ("low_angle_asymmetry", "refine_asymmetry"),
    ("impurity_peaks", "add_phase"),
    ("preferred_orientation", "refine_preferred_orientation"),
    ("limited_range", "request_broader_2theta_range"),
    ("high_noise", "reacquire_higher_counts"),
)

_IUCR_ROOT = "https://www.iucr.org/__data/iucr/powder/QARR/cpi"
_IUCR_QPA = {
    "1a": ({"corundum": 0.0115, "zincite": 0.0404, "fluorite": 0.9481}, "none"),
    "1b": ({"corundum": 0.9431, "zincite": 0.0136, "fluorite": 0.0433}, "none"),
    "1c": ({"corundum": 0.0504, "zincite": 0.9359, "fluorite": 0.0136}, "none"),
    "1d": ({"corundum": 0.1353, "zincite": 0.3289, "fluorite": 0.5358}, "none"),
    "1e": ({"corundum": 0.5512, "zincite": 0.1525, "fluorite": 0.2962}, "none"),
    "1f": ({"corundum": 0.2706, "zincite": 0.5522, "fluorite": 0.1772}, "none"),
    "1g": ({"corundum": 0.3137, "zincite": 0.3421, "fluorite": 0.3442}, "none"),
    "1h": ({"corundum": 0.3512, "zincite": 0.3019, "fluorite": 0.3469}, "none"),
    "2": (
        {"corundum": 0.2127, "zincite": 0.1994, "fluorite": 0.2253, "brucite": 0.3626},
        "preferred_orientation",
    ),
    "3": (
        {"corundum": 0.3079, "zincite": 0.1968, "fluorite": 0.2006, "glass": 0.2947},
        "amorphous_content",
    ),
    "4": ({"corundum": 0.5046, "magnetite": 0.1964, "zircon": 0.2990}, "microabsorption"),
}

_DARA_ROWS = (
    ("Bi2O3-Nb2O5", 500, ("Bi2O3", "Nb2O5", "unknown"), False),
    ("Bi2O3-2MoO3", 400, ("Bi2O3", "MoO3", "Bi2Mo3O12"), True),
    ("Bi2O3-V2O5", 400, ("Bi2O3", "V2O5", "VBiO4"), True),
    ("CaCO3-NH4H2PO4", 200, ("CaCO3", "unknown"), False),
    ("CoO-WO3", 900, ("CoWO4", "WO3"), True),
    ("CoO-ZnO", 1100, ("ZnO", "Co3O4"), True),
    ("Cr2O3-2MnO", 1100, ("MnCr2O4",), True),
    ("Cr2O3-2PbO", 500, ("CrPbO4", "Pb2CrO5", "unknown"), False),
    ("Cr2O3-2ZnO", 1100, ("ZnCr2O4", "ZnO"), True),
    ("Cr2O3-V2O5", 400, ("V2O5", "Cr2O3"), True),
)


def _snapshot(**updates: Any) -> FitSnapshot:
    values: dict[str, Any] = {
        "rwp": 12.0,
        "rexp": 6.0,
        "gof": 2.0,
        "residual_score": 0.30,
        "unexplained_peak_ratio": 0.10,
        "physical_violations": (),
        "parameter_count": 12,
        "max_abs_correlation": 0.70,
        "features": {},
    }
    values.update(updates)
    return FitSnapshot(**values)


def _action(
    kind: ActionKind = ActionKind.REFINE_BACKGROUND,
    stage: RefinementStage = RefinementStage.PROFILE_MATCH,
    parameters: tuple[str, ...] = ("b0", "b1"),
    bounds: dict[str, tuple[float, float]] | None = None,
) -> RefinementAction:
    return RefinementAction(
        kind=kind,
        stage=stage,
        parameters=parameters,
        rationale="Test the single mechanism supported by the supplied residual evidence.",
        evidence=(Evidence("residual_score", 0.30, "benchmark", ">0.2"),),
        predictions=(FalsifiablePrediction("residual_score", "decrease", 0.05),),
        bounds=bounds or {},
    )


def _action_contract_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    specs = (
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
    cases: list[dict[str, Any]] = []
    oracle: dict[str, Any] = {}
    for index, action in enumerate(specs, 1):
        case_id = f"contract-{index:03d}"
        failures = validate_action(action)
        cases.append({
            "id": case_id,
            "family": "action_contract",
            "split": "controlled",
            "question": "Is this typed refinement action scientifically admissible at the stated stage?",
            "input": {"action": asdict(action)},
            "response_schema": {"valid": "boolean", "violations": ["string"]},
        })
        oracle[case_id] = {"valid": not failures, "violations": list(failures)}
    return cases, oracle


def _trajectory_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    before = _snapshot()
    variants: list[tuple[FitSnapshot, RefinementAction]] = []
    variants.extend((_snapshot(rwp=11.0 - 0.1 * i, residual_score=0.20 - 0.01 * i), _action())
                    for i in range(5))
    variants.extend((_snapshot(rwp=11.8, residual_score=0.28 + 0.01 * i), _action())
                    for i in range(3))
    variants.extend((_snapshot(rwp=12.5 + 0.2 * i, residual_score=0.20), _action())
                    for i in range(3))
    variants.extend([
        (_snapshot(rwp=11.0, residual_score=0.20, physical_violations=("negative_biso",)), _action()),
        (_snapshot(rwp=10.8, residual_score=0.18, physical_violations=("occupancy_sum",)), _action()),
        (_snapshot(rwp=11.0, residual_score=0.20, max_abs_correlation=0.995), _action()),
        (_snapshot(rwp=11.0, residual_score=0.20, unexplained_peak_ratio=0.14), _action()),
        (_snapshot(rwp=11.0, residual_score=0.20),
         _action(ActionKind.REFINE_LATTICE, RefinementStage.STRUCTURE, ("cell_a",))),
        (_snapshot(rwp=11.0, residual_score=0.20),
         _action(ActionKind.REFINE_OCCUPANCY, RefinementStage.STRUCTURE, ("occupancy_Fe",))),
        (_snapshot(rwp=11.0, residual_score=0.20),
         _action(ActionKind.REFINE_ZERO, RefinementStage.INSTRUMENT, ("zero", "cell_a"))),
        (_snapshot(rwp=11.0, residual_score=0.20),
         _action(ActionKind.REFINE_BISO, RefinementStage.STRUCTURE,
                 ("biso_Fe", "occupancy_Fe"),
                 {"biso_Fe": (0.0, 5.0), "occupancy_Fe": (0.0, 1.0)})),
        (_snapshot(rwp=12.2, rexp=5.5, residual_score=0.20, parameter_count=30), _action()),
    ])
    assert len(variants) == 20
    cases: list[dict[str, Any]] = []
    oracle: dict[str, Any] = {}
    for index, (after, action) in enumerate(variants, 1):
        case_id = f"gate-{index:03d}"
        decision = evaluate_transition(before, after, action)
        cases.append({
            "id": case_id,
            "family": "trajectory_gate",
            "split": "controlled",
            "question": "Accept or reject this refinement edge using predictions, physical gates, and multi-objective utility.",
            "input": {"before": asdict(before), "after": asdict(after), "action": asdict(action)},
            "response_schema": {"accepted": "boolean", "reasons": ["string"]},
        })
        oracle[case_id] = {"accepted": decision.accepted, "reasons": list(decision.reasons)}
    return cases, oracle


def _residual_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    materials = ("CeO2", "LaB6", "rutile", "PbSO4", "Tb2BaCoO5")
    cases: list[dict[str, Any]] = []
    oracle: dict[str, Any] = {}
    for material_index, material in enumerate(materials, 1):
        for artifact_index, (diagnosis, action) in enumerate(_ARTIFACTS, 1):
            case_id = f"residual-{material_index:02d}-{artifact_index:02d}"
            cases.append({
                "id": case_id,
                "family": "residual_diagnosis",
                "split": "controlled",
                "question": "Identify the dominant single cause and choose the next action. Do not optimize a different mechanism.",
                "input": {
                    "pattern": f"data/residual/{case_id}.xye",
                    "columns": ["two_theta_deg", "observed", "calculated"],
                    "material": material,
                    "radiation": "Cu Kalpha1",
                    "wavelength_angstrom": 1.5406,
                    "single_cause_assumption": True,
                },
                "response_schema": {"diagnosis": "string", "action": "string"},
            })
            oracle[case_id] = {"diagnosis": diagnosis, "action": action}
    return cases, oracle


def _iucr_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    definitions: list[tuple[str, tuple[str, ...], dict[str, float] | None, str]] = []
    for sample, (fractions, artifact) in _IUCR_QPA.items():
        definitions.append((f"cpd-{sample}", tuple(fractions), fractions, artifact))
    definitions.extend([
        ("bauxite", ("quartz", "boehmite", "anatase", "goethite", "kaolinite", "gibbsite", "hematite"),
         {"quartz": .0516, "boehmite": .1493, "anatase": .0200, "goethite": .0998,
          "kaolinite": .0302, "gibbsite": .5490, "hematite": .1000}, "complex_mixture"),
        ("granodio", ("quartz", "feldspar", "albite", "biotite", "clinochlore", "hornblende", "zircon"), None, "natural_sample"),
        ("pharm1gr", ("mannitol", "sucrose", "dl-valine", "starch", "nizatidine"), None, "pharmaceutical_mixture"),
        ("pharm2gr", ("mannitol", "sucrose", "dl-valine", "starch", "nizatidine"), None, "pharmaceutical_mixture"),
        ("corundum", ("corundum",), None, "none"),
        ("fluorite", ("fluorite",), None, "none"),
        ("zincite", ("zincite",), None, "none"),
        ("brucite", ("brucite",), None, "preferred_orientation_reference"),
        ("magnetit", ("magnetite",), None, "microabsorption_reference"),
    ])
    assert len(definitions) == 20
    candidate_library = sorted({phase for _, phases, _, _ in definitions for phase in phases}
                               | {"calcite", "rutile", "spinel", "silicon"})
    cases: list[dict[str, Any]] = []
    oracle: dict[str, Any] = {}
    for index, (stem, phases, fractions, artifact) in enumerate(definitions, 1):
        case_id = f"iucr-{index:03d}"
        cases.append({
            "id": case_id,
            "family": "iucr_qpa",
            "split": "experimental",
            "question": "Report the phase set, quantitative weight fractions when identifiable, and dominant specimen artifact.",
            "input": {
                "pattern": f"data/iucr/{stem}.cpi",
                "source_url": f"{_IUCR_ROOT}/{stem}.cpi",
                "candidate_library": candidate_library,
                "instrument": "Cu Kalpha, Bragg-Brentano, graphite monochromator",
            },
            "response_schema": {
                "phases": ["string"], "weight_fractions": {"phase": "fraction_0_to_1"},
                "artifact": "string",
            },
        })
        answer: dict[str, Any] = {"phases": list(phases), "artifact": artifact}
        if fractions is not None:
            answer["weight_fractions"] = fractions
        oracle[case_id] = answer
    return cases, oracle


def _dara_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_phases = sorted({phase for _, _, phases, _ in _DARA_ROWS for phase in phases}
                        | {"TiO2", "Y2O3", "Fe2O3", "ZnWO4"})
    cases: list[dict[str, Any]] = []
    oracle: dict[str, Any] = {}
    for index, (reactants, temperature, phases, fully_indexed) in enumerate(_DARA_ROWS, 1):
        source_name = f"{reactants}_{temperature}C_60min.xrdml"
        case_id = f"dara-{index:03d}"
        cases.append({
            "id": case_id,
            "family": "dara_phase_identification",
            "split": "experimental",
            "question": "Return all supported product phases and whether the pattern is fully indexed; retain unknown when peaks remain unexplained.",
            "input": {
                "pattern": f"data/dara/{case_id}.xy",
                "source_pattern": source_name,
                "reactants": reactants,
                "temperature_c": temperature,
                "candidate_library": all_phases,
            },
            "response_schema": {"phases": ["string"], "fully_indexed": "boolean"},
        })
        oracle[case_id] = {"phases": list(phases), "fully_indexed": fully_indexed}
    return cases, oracle


def build_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    oracle: dict[str, Any] = {}
    for builder in (_action_contract_cases, _trajectory_cases, _residual_cases,
                    _iucr_cases, _dara_cases):
        new_cases, new_oracle = builder()
        cases.extend(new_cases)
        oracle.update(new_oracle)
    validate_suite(cases, oracle)
    return cases, oracle


def validate_suite(cases: list[dict[str, Any]], oracle: dict[str, Any]) -> dict[str, Any]:
    ids = [case.get("id") for case in cases]
    if len(cases) != 100:
        raise ValueError(f"benchmark must contain exactly 100 cases, found {len(cases)}")
    if len(set(ids)) != len(ids):
        raise ValueError("benchmark contains duplicate case ids")
    if set(ids) != set(oracle):
        raise ValueError("public cases and oracle ids differ")
    counts = Counter(case.get("family") for case in cases)
    if dict(counts) != EXPECTED_COUNTS:
        raise ValueError(f"unexpected family distribution: {dict(counts)}")
    return {"benchmark_id": BENCHMARK_ID, "case_count": len(cases), "families": dict(counts)}


def write_suite(root: Path) -> dict[str, Any]:
    cases, oracle = build_cases()
    root.mkdir(parents=True, exist_ok=True)
    cases_path = root / "cases.jsonl"
    cases_path.write_text("".join(json.dumps(case, sort_keys=True) + "\n" for case in cases),
                          encoding="utf-8")
    (root / "oracle.json").write_text(
        json.dumps({"benchmark_id": BENCHMARK_ID, "answers": oracle}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "benchmark_id": BENCHMARK_ID,
        "case_count": 100,
        "family_counts": EXPECTED_COUNTS,
        "splits": {"controlled": 70, "experimental": 30},
        "primary_metrics": ["macro_score", "physical_gate_error_rate", "diagnosis_accuracy"],
        "sources": {
            "controlled": "Generated deterministically by src/xrd/benchmark.py",
            "iucr_qarr": "https://www.iucr.org/__data/iucr/powder/QARR/data-kit.htm",
            "iucr_reference": "https://www.iucr.org/__data/iucr/powder/QARR/results.htm",
            "dara": "https://github.com/CederGroupHub/dara",
        },
        "oracle_policy": "Exact truth for controlled cases; published weighed/reference labels for experimental cases.",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                         encoding="utf-8")
    return validate_suite(cases, oracle)


def load_suite(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases = [json.loads(line) for line in (root / "cases.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    oracle_doc = json.loads((root / "oracle.json").read_text(encoding="utf-8"))
    oracle = oracle_doc["answers"]
    validate_suite(cases, oracle)
    return cases, oracle


def validate_data(root: Path) -> dict[str, Any]:
    """Require every file-backed case to exist and parse as a diffraction pattern."""
    cases, _ = load_suite(root)
    inline = 0
    parsed: dict[str, int] = Counter()
    point_counts: list[int] = []
    failures: list[str] = []
    for case in cases:
        relative = case["input"].get("pattern")
        if relative is None:
            inline += 1
            continue
        path = root / relative
        if not path.is_file():
            failures.append(f"{case['id']}:missing:{relative}")
            continue
        try:
            qc = analyze_pattern(read_pattern(path))
        except Exception as exc:
            failures.append(f"{case['id']}:invalid:{exc}")
            continue
        parsed[case["family"]] += 1
        point_counts.append(qc.point_count)
    if failures:
        preview = "; ".join(failures[:10])
        raise ValueError(f"benchmark data are not ready ({len(failures)} failures): {preview}")
    return {
        "benchmark_id": BENCHMARK_ID,
        "case_count": len(cases),
        "inline_cases": inline,
        "pattern_cases_ready": sum(parsed.values()),
        "pattern_cases_by_family": dict(parsed),
        "minimum_points": min(point_counts),
        "maximum_points": max(point_counts),
        "ready": inline + sum(parsed.values()) == len(cases),
    }


def _gaussian(x: float, center: float, sigma: float) -> float:
    return math.exp(-0.5 * ((x - center) / sigma) ** 2)


def _write_residual_pattern(path: Path, material_index: int, artifact_index: int) -> None:
    rng = random.Random(91000 + material_index * 100 + artifact_index)
    angles = [10.0 + 0.04 * index for index in range(2001)]
    peaks = [(16 + 6.7 * j + material_index * 0.73 + (j % 3) * 1.19,
              400 + 170 * ((j + material_index) % 5), 0.10 + 0.025 * ((j + 2) % 4))
             for j in range(10)]

    def profile(x: float, broaden: float = 1.0, shift: float = 0.0,
                orient: bool = False, asymmetry: bool = False) -> float:
        value = 80.0 + 0.35 * (x - 10.0)
        for j, (center, amplitude, sigma) in enumerate(peaks):
            scale = (1.8 if j in {1, 5, 8} else 0.65) if orient else 1.0
            moved = center + shift
            value += amplitude * scale * _gaussian(x, moved, sigma * broaden)
            if asymmetry and center < 40:
                value += 0.28 * amplitude * _gaussian(x, moved - 0.22, sigma * 2.4)
        return value

    rows: list[tuple[float, float, float]] = []
    for x in angles:
        calculated = profile(x)
        artifact = _ARTIFACTS[artifact_index - 1][0]
        if artifact == "zero_shift":
            observed = profile(x, shift=0.18)
        elif artifact == "background_curvature":
            observed = calculated + 0.12 * (x - 52.0) ** 2
        elif artifact == "peak_broadening":
            observed = profile(x, broaden=1.9)
        elif artifact == "low_angle_asymmetry":
            observed = profile(x, asymmetry=True)
        elif artifact == "impurity_peaks":
            observed = calculated + 520 * _gaussian(x, 27.31 + material_index * .13, .13)
            observed += 330 * _gaussian(x, 61.77 - material_index * .17, .16)
        elif artifact == "preferred_orientation":
            observed = profile(x, orient=True)
        elif artifact == "limited_range":
            if x < 27.0 or x > 58.0:
                continue
            observed = calculated
        else:
            observed = calculated + rng.gauss(0.0, 85.0)
        if artifact != "high_noise":
            observed += rng.gauss(0.0, 7.0)
        rows.append((x, max(0.0, observed), calculated))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii") as stream:
        stream.write("# two_theta_deg observed calculated\n")
        for row in rows:
            stream.write(f"{row[0]:.4f} {row[1]:.6f} {row[2]:.6f}\n")


def materialize_data(root: Path, dara_source: Path | None = None,
                     download_iucr: bool = False) -> dict[str, Any]:
    cases, _ = load_suite(root)
    statuses: dict[str, Any] = {"residual": {"ready": 0}, "dara": {"ready": 0, "missing": []},
                                "iucr": {"ready": 0, "failed": []}}
    for case in cases:
        if case["family"] == "residual_diagnosis":
            parts = case["id"].split("-")
            target = root / case["input"]["pattern"]
            _write_residual_pattern(target, int(parts[1]), int(parts[2]))
            statuses["residual"]["ready"] += 1

    if dara_source is None:
        dara_source = Path("benchmarks/data/dara/supplement/pairwise_reactions_patterns")
    for case in cases:
        if case["family"] != "dara_phase_identification":
            continue
        source = dara_source / case["input"]["source_pattern"]
        target = root / case["input"]["pattern"]
        if not source.is_file():
            statuses["dara"]["missing"].append(str(source))
            continue
        pattern = read_xrdml(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="ascii") as stream:
            stream.write("# two_theta_deg intensity\n")
            for angle, intensity in zip(pattern.two_theta, pattern.intensity):
                stream.write(f"{angle:.6f} {intensity:.6f}\n")
        statuses["dara"]["ready"] += 1

    if download_iucr:
        for case in cases:
            if case["family"] != "iucr_qpa":
                continue
            target = root / case["input"]["pattern"]
            target.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(case["input"]["source_url"],
                                             headers={"User-Agent": "AutoXRD-Bench/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response, target.open("wb") as out:
                    shutil.copyfileobj(response, out)
            except Exception as exc:  # Network mirrors fail independently of suite construction.
                target.unlink(missing_ok=True)
                statuses["iucr"]["failed"].append({"id": case["id"], "error": str(exc)})
            else:
                statuses["iucr"]["ready"] += 1
    else:
        statuses["iucr"]["ready"] = sum(
            (root / case["input"]["pattern"]).is_file() for case in cases
            if case["family"] == "iucr_qpa"
        )
    checksums: dict[str, str] = {}
    for path in sorted((root / "data").rglob("*")):
        if path.is_file() and path.name != "materialization.json":
            checksums[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {**statuses, "checksums": checksums}
    report_path = root / "data" / "materialization.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    statuses["checksum_count"] = len(checksums)
    statuses["report"] = str(report_path)
    return statuses


def _set_f1(expected: Iterable[str], predicted: Iterable[str]) -> float:
    if not isinstance(predicted, (list, tuple, set, frozenset)):
        return 0.0
    left = {_normalize_label(value) for value in expected}
    right = {_normalize_label(value) for value in predicted}
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    return 2.0 * overlap / (len(left) + len(right))


def _normalize_label(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    aliases = {"al2o3": "corundum", "caf2": "fluorite", "zno": "zincite",
               "fe3o4": "magnetite", "amorphous": "glass", "unknownphase": "unknown"}
    return aliases.get(text, text)


def _fraction_score(expected: dict[str, float], predicted: Any) -> tuple[float, float | None]:
    if not isinstance(predicted, dict):
        return 0.0, None
    numeric = [(key, value) for key, value in predicted.items() if isinstance(value, (int, float))]
    if len(numeric) != len(predicted) or any(not math.isfinite(value) or not 0 <= value <= 1
                                              for _, value in numeric):
        return 0.0, None
    normalized = {_normalize_label(key): float(value) for key, value in numeric}
    errors = [abs(value - normalized.get(_normalize_label(phase), 0.0))
              for phase, value in expected.items()]
    expected_names = {_normalize_label(phase) for phase in expected}
    errors.extend(abs(value) for phase, value in normalized.items() if phase not in expected_names)
    mae = sum(errors) / len(errors)
    return max(0.0, 1.0 - mae / 0.20), mae


def _score_one(family: str, expected: dict[str, Any], predicted: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    if family == "action_contract":
        exact = float(predicted.get("valid") is expected["valid"])
        f1 = _set_f1(expected["violations"], predicted.get("violations", []))
        return 0.5 * exact + 0.5 * f1, {"valid_exact": exact, "violation_f1": f1}
    if family == "trajectory_gate":
        exact = float(predicted.get("accepted") is expected["accepted"])
        f1 = _set_f1(expected["reasons"], predicted.get("reasons", []))
        return 0.5 * exact + 0.5 * f1, {"accept_exact": exact, "reason_f1": f1}
    if family == "residual_diagnosis":
        diagnosis = float(_normalize_label(predicted.get("diagnosis")) == _normalize_label(expected["diagnosis"]))
        action = float(_normalize_label(predicted.get("action")) == _normalize_label(expected["action"]))
        return 0.5 * diagnosis + 0.5 * action, {"diagnosis_exact": diagnosis, "action_exact": action}
    phase_f1 = _set_f1(expected["phases"], predicted.get("phases", []))
    if family == "dara_phase_identification":
        indexed = float(predicted.get("fully_indexed") is expected["fully_indexed"])
        return 0.8 * phase_f1 + 0.2 * indexed, {"phase_f1": phase_f1, "fully_indexed_exact": indexed}
    artifact = float(_normalize_label(predicted.get("artifact")) == _normalize_label(expected["artifact"]))
    if "weight_fractions" in expected:
        fraction, mae = _fraction_score(expected["weight_fractions"], predicted.get("weight_fractions"))
        return 0.45 * phase_f1 + 0.45 * fraction + 0.10 * artifact, {
            "phase_f1": phase_f1, "fraction_score": fraction, "fraction_mae": mae,
            "artifact_exact": artifact,
        }
    return 0.8 * phase_f1 + 0.2 * artifact, {"phase_f1": phase_f1, "artifact_exact": artifact}


def _stratified_bootstrap_macro(per_case: list[dict[str, Any]], iterations: int = 2000) -> list[float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for item in per_case:
        grouped[item["family"]].append(item["score"])
    rng = random.Random(20260812)
    estimates: list[float] = []
    for _ in range(iterations):
        family_means = []
        for scores in grouped.values():
            family_means.append(sum(rng.choice(scores) for _ in scores) / len(scores))
        estimates.append(sum(family_means) / len(family_means))
    estimates.sort()
    return [estimates[int(0.025 * iterations)], estimates[int(0.975 * iterations) - 1]]


def score_predictions(root: Path, predictions_path: Path) -> dict[str, Any]:
    cases, oracle = load_suite(root)
    predictions: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for line_number, line in enumerate(predictions_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        case_id = item.get("id")
        if case_id in predictions:
            duplicates.append(str(case_id))
        if not isinstance(item.get("answer"), dict):
            raise ValueError(f"line {line_number} must contain an answer object")
        predictions[str(case_id)] = item["answer"]
    if duplicates:
        raise ValueError("duplicate prediction ids: " + ", ".join(sorted(set(duplicates))))
    known_ids = {case["id"] for case in cases}
    unknown = sorted(set(predictions) - known_ids)
    if unknown:
        raise ValueError("unknown prediction ids: " + ", ".join(unknown))

    per_case: list[dict[str, Any]] = []
    family_scores: dict[str, list[float]] = defaultdict(list)
    for case in cases:
        case_id = case["id"]
        if case_id in predictions:
            score, components = _score_one(case["family"], oracle[case_id], predictions[case_id])
        else:
            score, components = 0.0, {}
        family_scores[case["family"]].append(score)
        per_case.append({"id": case_id, "family": case["family"], "split": case["split"], "score": score,
                         "components": components, "missing": case_id not in predictions})
    by_family = {family: sum(values) / len(values) for family, values in family_scores.items()}
    macro = sum(by_family.values()) / len(by_family)
    micro = sum(item["score"] for item in per_case) / len(per_case)
    gate_items = [item for item in per_case if item["family"] in {"action_contract", "trajectory_gate"}]
    physical_gate_error_rate = 1.0 - sum(item["score"] for item in gate_items) / len(gate_items)
    diagnosis = [item["components"].get("diagnosis_exact", 0.0) for item in per_case
                 if item["family"] == "residual_diagnosis"]
    split_scores = {
        split: sum(item["score"] for item in per_case if item["split"] == split)
        / sum(item["split"] == split for item in per_case)
        for split in {item["split"] for item in per_case}
    }
    return {
        "benchmark_id": BENCHMARK_ID,
        "submitted": len(predictions),
        "missing": 100 - len(predictions),
        "macro_score": macro,
        "macro_score_bootstrap_95ci": _stratified_bootstrap_macro(per_case),
        "micro_score": micro,
        "physical_gate_error_rate": physical_gate_error_rate,
        "diagnosis_accuracy": sum(diagnosis) / len(diagnosis),
        "by_split": split_scores,
        "by_family": by_family,
        "per_case": per_case,
    }


def write_baseline(root: Path, output: Path) -> None:
    cases, _ = load_suite(root)
    answers: list[dict[str, Any]] = []
    for case in cases:
        family = case["family"]
        if family == "action_contract":
            answer = {"valid": True, "violations": []}
        elif family == "trajectory_gate":
            answer = {"accepted": False, "reasons": ["no_multi_objective_utility_gain"]}
        elif family == "residual_diagnosis":
            answer = {"diagnosis": "background_curvature", "action": "refine_background"}
        elif family == "iucr_qpa":
            answer = {"phases": [], "weight_fractions": {}, "artifact": "none"}
        else:
            answer = {"phases": [], "fully_indexed": True}
        answers.append({"id": case["id"], "answer": answer})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in answers),
                      encoding="utf-8")
