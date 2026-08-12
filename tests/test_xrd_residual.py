from __future__ import annotations

import math

from pathlib import Path

from xrd.residual import analyze_residual, read_fullprof_prf


def gaussian(x: float, center: float, width: float, height: float) -> float:
    return height * math.exp(-0.5 * ((x - center) / width) ** 2)


def test_residual_features_detect_missing_peak_and_structure():
    angles = [10 + index * 0.02 for index in range(2000)]
    calculated = [10 + gaussian(x, 25, 0.12, 700) for x in angles]
    observed = [value + gaussian(x, 35, 0.14, 500) for x, value in zip(angles, calculated)]

    result = analyze_residual(angles, observed, calculated)

    assert result.unexplained_peak_ratio == 0.5
    assert result.structured_region_fraction > 0
    assert any(abs(region.apex_2theta - 35) < 0.1 for region in result.regions)
    assert "strongly_structured_residual" in result.warnings


def test_residual_features_accept_sigma_weighting():
    angles = [10 + index * 0.1 for index in range(100)]
    observed = [100 + (50 if index == 50 else 0) for index in range(100)]
    calculated = [100.0] * 100
    result = analyze_residual(angles, observed, calculated, sigma=[10.0] * 100)
    assert math.isfinite(result.rwp)


def test_residual_rejects_non_monotonic_axis():
    try:
        analyze_residual([1, 2, 2, 4, 5], [1] * 5, [1] * 5)
    except ValueError as error:
        assert "strictly increasing" in str(error)
    else:
        raise AssertionError("non-monotonic axis was accepted")


def test_read_packed_fullprof_prf(tmp_path: Path):
    path = tmp_path / "sample.prf"
    path.write_text(
        "COMM sample\n"
        "3111 1.0 0.0\n"
        "14.0 10.0 1.0 8 0\n"
        "1 5 1.5406 0 0 0 0\n"
        "0 0\n"
        "10 20 30 20 10\n"
        "9 18 29 18 9\n",
        encoding="latin-1",
    )
    two_theta, observed, calculated, sigma = read_fullprof_prf(path)
    assert two_theta == [10, 11, 12, 13, 14]
    assert observed == [10, 20, 30, 20, 10]
    assert calculated == [9, 18, 29, 18, 9]
    assert sigma is None
