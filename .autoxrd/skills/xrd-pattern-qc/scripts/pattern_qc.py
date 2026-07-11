#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path


def median_absolute_deviation(values: list[float]) -> float:
    center = statistics.median(values)
    return statistics.median(abs(value - center) for value in values)


def read_pattern(path: Path) -> tuple[list[float], list[float], int]:
    angles: list[float] = []
    intensities: list[float] = []
    skipped = 0
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "!", ";")):
            continue
        fields = line.replace(",", " ").split()
        if len(fields) < 2:
            skipped += 1
            continue
        try:
            angle, intensity = float(fields[0]), float(fields[1])
        except ValueError:
            skipped += 1
            continue
        if math.isfinite(angle) and math.isfinite(intensity):
            angles.append(angle)
            intensities.append(intensity)
        else:
            skipped += 1
    if len(angles) < 3:
        raise ValueError("pattern must contain at least three numeric rows")
    return angles, intensities, skipped


def analyze(path: Path) -> dict[str, object]:
    angles, intensities, skipped = read_pattern(path)
    steps = [right - left for left, right in zip(angles, angles[1:])]
    positive_steps = [step for step in steps if step > 0]
    median_step = statistics.median(positive_steps) if positive_steps else 0.0
    step_mad = median_absolute_deviation(positive_steps) if positive_steps else 0.0

    differences = [right - left for left, right in zip(intensities, intensities[1:])]
    noise = median_absolute_deviation(differences) / 0.6745 / math.sqrt(2)
    baseline = statistics.median(intensities)
    threshold = baseline + max(6 * noise, 0.05 * (max(intensities) - baseline))
    peaks = [
        angles[index]
        for index in range(1, len(angles) - 1)
        if intensities[index] > threshold
        and intensities[index] >= intensities[index - 1]
        and intensities[index] > intensities[index + 1]
    ]

    warnings: list[str] = []
    if any(step <= 0 for step in steps):
        warnings.append("two_theta_not_strictly_increasing")
    if median_step and step_mad / median_step > 0.05:
        warnings.append("irregular_step_size")
    if any(value < 0 for value in intensities):
        warnings.append("negative_intensity_present")
    if len(angles) < 500:
        warnings.append("low_point_count")
    if skipped:
        warnings.append("non_numeric_rows_skipped")
    if not peaks:
        warnings.append("no_peaks_detected_by_conservative_rule")

    return {
        "source": str(path.resolve()),
        "point_count": len(angles),
        "skipped_rows": skipped,
        "scan_range_2theta": [angles[0], angles[-1]],
        "median_step_2theta": median_step,
        "step_mad_2theta": step_mad,
        "intensity_range": [min(intensities), max(intensities)],
        "robust_noise": noise,
        "detected_peak_count": len(peaks),
        "detected_peaks_2theta": peaks[:100],
        "radiation": "unknown",
        "wavelength": None,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Conservative QC for two-column powder XRD data")
    parser.add_argument("pattern", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.pattern), indent=2))


if __name__ == "__main__":
    main()
