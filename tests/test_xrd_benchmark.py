import json
from pathlib import Path

import pytest

from xrd.benchmark import (
    EXPECTED_COUNTS,
    build_cases,
    load_suite,
    materialize_data,
    score_predictions,
    write_baseline,
    write_suite,
)


def test_benchmark_has_exactly_100_unique_cases() -> None:
    cases, oracle = build_cases()
    assert len(cases) == len(oracle) == 100
    assert len({case["id"] for case in cases}) == 100
    assert {family: sum(case["family"] == family for case in cases)
            for family in EXPECTED_COUNTS} == EXPECTED_COUNTS


def test_write_load_and_materialize_controlled_patterns(tmp_path: Path) -> None:
    write_suite(tmp_path)
    cases, oracle = load_suite(tmp_path)
    status = materialize_data(tmp_path, dara_source=tmp_path / "missing")
    assert len(cases) == len(oracle) == 100
    assert status["residual"]["ready"] == 40
    paths = [tmp_path / case["input"]["pattern"] for case in cases
             if case["family"] == "residual_diagnosis"]
    assert all(path.stat().st_size > 1000 for path in paths)


def test_oracle_submission_scores_one(tmp_path: Path) -> None:
    write_suite(tmp_path)
    cases, oracle = load_suite(tmp_path)
    predictions = tmp_path / "oracle-predictions.jsonl"
    predictions.write_text("".join(json.dumps({"id": case["id"], "answer": oracle[case["id"]]}) + "\n"
                                   for case in cases), encoding="utf-8")
    report = score_predictions(tmp_path, predictions)
    assert report["macro_score"] == pytest.approx(1.0)
    assert report["macro_score_bootstrap_95ci"] == pytest.approx([1.0, 1.0])
    assert report["micro_score"] == pytest.approx(1.0)
    assert report["by_split"] == pytest.approx({"controlled": 1.0, "experimental": 1.0})
    assert report["missing"] == 0


def test_baseline_is_complete_and_scores_below_oracle(tmp_path: Path) -> None:
    write_suite(tmp_path)
    baseline = tmp_path / "baseline.jsonl"
    write_baseline(tmp_path, baseline)
    report = score_predictions(tmp_path, baseline)
    assert report["submitted"] == 100
    assert 0.0 < report["macro_score"] < 0.8


def test_missing_answers_score_zero_and_duplicate_ids_fail(tmp_path: Path) -> None:
    write_suite(tmp_path)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert score_predictions(tmp_path, empty)["micro_score"] == 0.0
    duplicate = tmp_path / "duplicate.jsonl"
    row = json.dumps({"id": "contract-001", "answer": {}}) + "\n"
    duplicate.write_text(row + row, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate prediction ids"):
        score_predictions(tmp_path, duplicate)
