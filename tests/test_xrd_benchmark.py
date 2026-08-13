import json
from pathlib import Path

import pytest

from xrd.benchmark_v2 import (
    EXPECTED_DIFFICULTIES,
    EXPECTED_FAMILIES,
    _utility,
    build_cases,
    load_suite,
    materialize_data,
    score_predictions,
    validate_data,
    write_baseline,
    write_suite,
)


def _oracle_answer(case, expected):
    if case["difficulty"] == "easy":
        return {"selected_options": expected["selected_options"]}
    if case["difficulty"] == "medium":
        return {"conclusion": expected["reference_answer"], "key_metrics": {},
                "diagnosis": expected["required_facts"][0], "recommended_action": "reference"}
    if case["family"] == "hard_metric_recovery":
        return {"diagnosed_mechanisms": expected["mechanisms"],
                "parameter_estimates": expected["parameters"],
                "recovery_plan": ["isolate each mechanism"], "report": expected["reference_answer"]}
    if case["family"] == "hard_qpa":
        return {"phases": expected["phases"], "weight_fractions": expected["weight_fractions"],
                "artifact": expected["artifact"], "uncertainty": {}, "report": expected["reference_answer"]}
    return {"phases": expected["phases"], "fully_indexed": expected["fully_indexed"],
            "confidence": {}, "verification_sequence": ["Rietveld verification"],
            "report": expected["reference_answer"]}


def _perfect_judgments(cases, path: Path):
    rows = []
    for case in cases:
        if case["difficulty"] == "easy":
            continue
        for repeat in range(3):
            rows.append({"id": case["id"], "repeat": repeat, "judgment": {
                "scientific_correctness": 4, "evidence_grounding": 4,
                "action_quality": 4, "completeness": 4, "fatal_error": False,
                "critique": "Reference answer.",
            }})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_benchmark_has_tiered_100_case_distribution_and_distractors():
    cases, oracle = build_cases()
    assert len(cases) == len(oracle) == 100
    assert {difficulty: sum(c["difficulty"] == difficulty for c in cases)
            for difficulty in EXPECTED_DIFFICULTIES} == EXPECTED_DIFFICULTIES
    assert {family: sum(c["family"] == family for c in cases)
            for family in EXPECTED_FAMILIES} == EXPECTED_FAMILIES
    for case in (case for case in cases if case["difficulty"] == "easy"):
        assert len(case["input"]["options"]) - len(oracle[case["id"]]["selected_options"]) >= 4


def test_write_load_and_materialize_controlled_patterns(tmp_path: Path):
    write_suite(tmp_path)
    cases, oracle = load_suite(tmp_path)
    status = materialize_data(tmp_path, dara_source=tmp_path / "missing")
    assert len(cases) == len(oracle) == 100
    assert status["residual_ready"] == 40
    assert status["hard_recovery_ready"] == 10
    assert len(list((tmp_path / "data/hard_recovery").glob("*.xye"))) == 10


def test_data_validation_rejects_missing_experimental_patterns(tmp_path: Path):
    write_suite(tmp_path)
    materialize_data(tmp_path, dara_source=tmp_path / "missing")
    with pytest.raises(ValueError, match="data are not ready"):
        validate_data(tmp_path)


def test_oracle_and_perfect_judgments_score_100(tmp_path: Path):
    write_suite(tmp_path)
    cases, oracle = load_suite(tmp_path)
    predictions = tmp_path / "oracle.jsonl"
    predictions.write_text("".join(json.dumps({"id": case["id"],
                                                "answer": _oracle_answer(case, oracle[case["id"]])}) + "\n"
                                   for case in cases), encoding="utf-8")
    judgments = tmp_path / "judgments.jsonl"
    _perfect_judgments(cases, judgments)
    report = score_predictions(tmp_path, predictions, judgments)
    assert report["overall_score_percent"] == pytest.approx(100.0)
    assert report["by_difficulty_percent"] == pytest.approx(
        {"easy": 100.0, "medium": 100.0, "hard": 100.0})
    assert report["provisional"] is False


def test_missing_judgments_are_not_silently_renormalized(tmp_path: Path):
    write_suite(tmp_path)
    baseline = tmp_path / "baseline.jsonl"
    write_baseline(tmp_path, baseline)
    report = score_predictions(tmp_path, baseline)
    assert report["submitted"] == 100
    assert report["provisional"] is True
    assert report["by_difficulty_percent"]["medium"] == 0.0
    assert report["overall_score_percent"] < 30.0


def test_relative_utility_is_frozen_and_clipped():
    assert _utility(1.0, 0.0, 1.0, True) == 1.0
    assert _utility(0.0, 0.0, 1.0, True) == 0.0
    assert _utility(0.0, 0.25, 0.0, False) == 1.0
    assert _utility(0.25, 0.25, 0.0, False) == 0.0
    assert _utility(2.0, 0.0, 1.0, True) == 1.0


def test_duplicate_and_unknown_predictions_fail(tmp_path: Path):
    write_suite(tmp_path)
    duplicate = tmp_path / "duplicate.jsonl"
    row = json.dumps({"id": "easy-action-001", "answer": {}}) + "\n"
    duplicate.write_text(row + row, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate prediction id"):
        score_predictions(tmp_path, duplicate)
