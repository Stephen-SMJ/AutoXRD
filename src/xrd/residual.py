"""Deterministic morphology features for observed-calculated XRD residuals."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResidualRegion:
    start_2theta: float
    end_2theta: float
    apex_2theta: float
    signed_area: float
    max_abs_z: float


@dataclass(frozen=True)
class ResidualFeatures:
    point_count: int
    rwp: float
    robust_sigma: float
    normalized_absolute_residual: float
    lag1_autocorrelation: float
    low_angle_signed_bias: float
    high_angle_signed_bias: float
    structured_region_fraction: float
    unexplained_peak_ratio: float
    regions: tuple[ResidualRegion, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _median_absolute_deviation(values: list[float]) -> float:
    center = statistics.median(values)
    return statistics.median(abs(value - center) for value in values)


def _local_maxima(values: list[float], threshold: float) -> list[int]:
    return [index for index in range(1, len(values) - 1)
            if values[index] > threshold and values[index] >= values[index - 1]
            and values[index] > values[index + 1]]


def analyze_residual(two_theta: list[float], observed: list[float], calculated: list[float],
                     sigma: list[float] | None = None, z_threshold: float = 5.0) -> ResidualFeatures:
    size = len(two_theta)
    if size < 5 or len(observed) != size or len(calculated) != size:
        raise ValueError("two_theta, observed, and calculated need equal length >= 5")
    if sigma is not None and len(sigma) != size:
        raise ValueError("sigma must have the same length as the pattern")
    if any(not math.isfinite(value) for series in (two_theta, observed, calculated)
           for value in series):
        raise ValueError("residual input contains non-finite values")
    if any(right <= left for left, right in zip(two_theta, two_theta[1:])):
        raise ValueError("two_theta must be strictly increasing")

    residual = [obs - calc for obs, calc in zip(observed, calculated)]
    centered = [value - statistics.median(residual) for value in residual]
    robust_sigma = _median_absolute_deviation(centered) / 0.67448975
    if robust_sigma <= 1e-12:
        robust_sigma = math.sqrt(sum(value * value for value in centered) / size) or 1.0
    z_scores = [value / robust_sigma for value in centered]

    weights = [1.0 / max(value * value, 1e-12) for value in sigma] if sigma else [1.0] * size
    numerator = sum(weight * value * value for weight, value in zip(weights, residual))
    denominator = sum(weight * value * value for weight, value in zip(weights, observed))
    rwp = 100.0 * math.sqrt(numerator / denominator) if denominator > 0 else math.inf
    intensity_scale = max(sum(abs(value) for value in observed), 1e-12)
    normalized_absolute = sum(abs(value) for value in residual) / intensity_scale

    lag_numerator = sum(left * right for left, right in zip(centered, centered[1:]))
    lag_denominator = sum(value * value for value in centered)
    lag1 = lag_numerator / lag_denominator if lag_denominator else 0.0
    split = max(1, size // 3)
    scale = max(statistics.median(abs(value) for value in observed), robust_sigma, 1e-12)
    low_bias = statistics.mean(residual[:split]) / scale
    high_bias = statistics.mean(residual[-split:]) / scale

    mask = [abs(value) >= z_threshold for value in z_scores]
    regions: list[ResidualRegion] = []
    index = 0
    while index < size:
        if not mask[index]:
            index += 1
            continue
        start = index
        while index + 1 < size and mask[index + 1]:
            index += 1
        end = index
        apex = max(range(start, end + 1), key=lambda item: abs(z_scores[item]))
        regions.append(ResidualRegion(
            two_theta[start], two_theta[end], two_theta[apex],
            sum(residual[start:end + 1]), abs(z_scores[apex]),
        ))
        index += 1

    baseline = statistics.median(observed)
    observed_threshold = baseline + max(6 * robust_sigma, 0.05 * (max(observed) - baseline))
    calculated_threshold = statistics.median(calculated) + max(
        3 * robust_sigma, 0.025 * (max(calculated) - statistics.median(calculated)))
    observed_peaks = _local_maxima(observed, observed_threshold)
    calculated_peaks = _local_maxima(calculated, calculated_threshold)
    median_step = statistics.median(right - left for left, right in zip(two_theta, two_theta[1:]))
    tolerance = max(0.08, 3 * median_step)
    unexplained = sum(not any(abs(two_theta[peak] - two_theta[other]) <= tolerance
                              for other in calculated_peaks) for peak in observed_peaks)
    unexplained_ratio = unexplained / len(observed_peaks) if observed_peaks else 0.0

    warnings: list[str] = []
    if not observed_peaks:
        warnings.append("no_observed_peaks_detected")
    if abs(lag1) > 0.5:
        warnings.append("strongly_structured_residual")
    if unexplained_ratio > 0.2:
        warnings.append("many_unexplained_peaks")
    return ResidualFeatures(
        size, rwp, robust_sigma, normalized_absolute, lag1, low_bias, high_bias,
        sum(mask) / size, unexplained_ratio, tuple(regions), tuple(warnings),
    )


def read_residual_table(path: Path) -> tuple[list[float], list[float], list[float], list[float] | None]:
    columns: list[list[float]] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "!", ";")):
            continue
        try:
            row = [float(value) for value in line.replace(",", " ").split()]
        except ValueError:
            continue
        if len(row) >= 3:
            columns.append(row)
    if not columns:
        raise ValueError("no numeric rows with at least three columns")
    sigma = [row[3] for row in columns] if all(len(row) >= 4 for row in columns) else None
    return ([row[0] for row in columns], [row[1] for row in columns],
            [row[2] for row in columns], sigma)


def read_fullprof_prf(path: Path) -> tuple[list[float], list[float], list[float], None]:
    """Read the observed/calculated arrays in FullProf's packed legacy PRF format."""
    lines = path.read_text(encoding="latin-1", errors="replace").splitlines()
    if len(lines) < 6:
        raise ValueError("FullProf PRF is too short")
    scan = lines[2].split()
    pattern = lines[3].split()
    if len(scan) < 3 or len(pattern) < 2:
        raise ValueError("FullProf PRF header is incomplete")
    try:
        theta_max, theta_min, step = (float(scan[0]), float(scan[1]), float(scan[2]))
        point_count = int(pattern[1])
    except ValueError as exc:
        raise ValueError("FullProf PRF header contains invalid scan metadata") from exc
    if point_count < 5 or not (math.isfinite(theta_min) and math.isfinite(theta_max)
                               and math.isfinite(step) and step > 0):
        raise ValueError("FullProf PRF has invalid scan bounds or point count")
    packed: list[float] = []
    for line in lines[5:]:
        for token in line.split():
            try:
                packed.append(float(token))
            except ValueError:
                break
    if len(packed) < 2 * point_count:
        raise ValueError("FullProf PRF does not contain complete observed/calculated arrays")
    observed = packed[:point_count]
    calculated = packed[point_count:2 * point_count]
    two_theta = [theta_min + index * step for index in range(point_count)]
    expected_max = two_theta[-1]
    if abs(expected_max - theta_max) > max(step * 2, 1e-3):
        raise ValueError("FullProf PRF scan metadata is internally inconsistent")
    return two_theta, observed, calculated, None


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract deterministic XRD residual features")
    parser.add_argument("table", type=Path,
                        help="FullProf PRF or 2theta observed calculated [sigma] table")
    parser.add_argument("--z-threshold", type=float, default=5.0)
    args = parser.parse_args()
    values = (read_fullprof_prf(args.table) if args.table.suffix.lower() == ".prf"
              else read_residual_table(args.table))
    result = analyze_residual(*values, z_threshold=args.z_threshold)
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
