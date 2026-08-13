from __future__ import annotations

import json
import math
import statistics
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Pattern:
    two_theta: list[float]
    intensity: list[float]
    wavelength: float | None = None
    radiation: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PatternQC:
    point_count: int
    scan_min: float
    scan_max: float
    median_step: float
    step_relative_mad: float
    robust_noise: float
    dynamic_range: float
    detected_peak_count: int
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mad(values: list[float]) -> float:
    center = statistics.median(values)
    return statistics.median(abs(value - center) for value in values)


def read_json_pattern(data: dict[str, Any]) -> Pattern:
    angles = data.get("two_theta_values") or data.get("two_theta")
    intensities = data.get("intensity_values") or data.get("intensities") or data.get("intensity")
    if not isinstance(angles, list) or not isinstance(intensities, list):
        raise ValueError("JSON pattern lacks angle or intensity arrays")
    label = data.get("label")
    label_data = json.loads(label) if isinstance(label, str) else (label or {})
    xray_info = label_data.get("xray_info") if isinstance(label_data, dict) else None
    xray_data = json.loads(xray_info) if isinstance(xray_info, str) else (xray_info or {})
    wavelength = xray_data.get("primary_wavelength")
    return Pattern(
        [float(value) for value in angles],
        [float(value) for value in intensities],
        float(wavelength) if wavelength is not None else None,
        metadata={"label": label_data, "source_metadata": data.get("metadata")},
    )


def read_xrdml(path: Path) -> Pattern:
    root = ET.parse(path).getroot()
    namespace = root.tag.partition("}")[0].lstrip("{")
    prefix = f"{{{namespace}}}" if namespace else ""
    counts_node = root.find(f".//{prefix}counts")
    if counts_node is None:
        counts_node = root.find(f".//{prefix}intensities")
    if counts_node is None or not counts_node.text:
        raise ValueError("XRDML file contains no counts")
    counts = [float(value) for value in counts_node.text.split()]
    positions = [
        node for node in root.findall(f".//{prefix}positions") if node.attrib.get("axis") == "2Theta"
    ]
    if not positions:
        raise ValueError("XRDML file contains no 2Theta positions")
    start = float(positions[0].findtext(f"{prefix}startPosition"))
    end = float(positions[0].findtext(f"{prefix}endPosition"))
    step = (end - start) / (len(counts) - 1)
    angles = [start + index * step for index in range(len(counts))]
    wavelength_text = root.findtext(f".//{prefix}kAlpha1")
    anode = root.findtext(f".//{prefix}anodeMaterial") or "unknown"
    return Pattern(
        angles,
        counts,
        float(wavelength_text) if wavelength_text else None,
        radiation=anode,
        metadata={"format": "xrdml"},
    )


def read_text_pattern(path: Path) -> Pattern:
    angles: list[float] = []
    intensities: list[float] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = raw_line.strip().replace(",", " ").split()
        if len(fields) < 2 or raw_line.lstrip().startswith(("#", "!", ";")):
            continue
        try:
            angle, intensity = float(fields[0]), float(fields[1])
        except ValueError:
            continue
        if math.isfinite(angle) and math.isfinite(intensity):
            angles.append(angle)
            intensities.append(intensity)
    return Pattern(angles, intensities)


def read_cpi(path: Path) -> Pattern:
    """Read the historical Sietronics CPI column format used by IUCr QARR."""
    lines = path.read_text(encoding="ascii", errors="replace").splitlines()
    if len(lines) < 11 or lines[0].strip().upper() != "SIETRONICS XRD SCAN":
        raise ValueError("CPI file lacks the Sietronics scan header")
    try:
        start = float(lines[1].strip())
        end = float(lines[2].strip())
        step = float(lines[3].strip())
        wavelength = float(lines[5].strip())
        marker = next(index for index, line in enumerate(lines) if line.strip().upper() == "SCANDATA")
        intensities = [float(token) for line in lines[marker + 1:] for token in line.split()]
    except (StopIteration, ValueError) as exc:
        raise ValueError("CPI file contains an invalid scan header or intensity value") from exc
    expected = int(round((end - start) / step)) + 1
    if step <= 0 or expected < 3 or len(intensities) != expected:
        raise ValueError(
            f"CPI scan length mismatch: header expects {expected}, found {len(intensities)}"
        )
    angles = [start + index * step for index in range(expected)]
    return Pattern(
        angles,
        intensities,
        wavelength=wavelength,
        radiation=lines[4].strip() or "unknown",
        metadata={"format": "sietronics_cpi", "sample": lines[8].strip()},
    )


def read_pattern(path: Path) -> Pattern:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return read_json_pattern(json.loads(path.read_text(encoding="utf-8")))
    if suffix == ".xrdml":
        return read_xrdml(path)
    if suffix == ".cpi":
        return read_cpi(path)
    return read_text_pattern(path)


def analyze_pattern(pattern: Pattern) -> PatternQC:
    if len(pattern.two_theta) != len(pattern.intensity) or len(pattern.two_theta) < 3:
        raise ValueError("pattern needs equal angle/intensity arrays with at least three points")
    steps = [right - left for left, right in zip(pattern.two_theta, pattern.two_theta[1:])]
    positive_steps = [value for value in steps if value > 0]
    median_step = statistics.median(positive_steps) if positive_steps else 0.0
    relative_mad = _mad(positive_steps) / median_step if median_step else math.inf
    differences = [right - left for left, right in zip(pattern.intensity, pattern.intensity[1:])]
    noise = _mad(differences) / 0.6745 / math.sqrt(2)
    baseline = statistics.median(pattern.intensity)
    dynamic_range = max(pattern.intensity) - min(pattern.intensity)
    threshold = baseline + max(6 * noise, 0.05 * (max(pattern.intensity) - baseline))
    peaks = sum(
        pattern.intensity[index] > threshold
        and pattern.intensity[index] >= pattern.intensity[index - 1]
        and pattern.intensity[index] > pattern.intensity[index + 1]
        for index in range(1, len(pattern.intensity) - 1)
    )
    warnings = []
    if any(value <= 0 for value in steps):
        warnings.append("two_theta_not_strictly_increasing")
    if relative_mad > 0.05:
        warnings.append("irregular_step_size")
    if any(value < 0 for value in pattern.intensity):
        warnings.append("negative_intensity_present")
    if len(pattern.two_theta) < 500:
        warnings.append("low_point_count")
    if peaks == 0:
        warnings.append("no_peaks_detected_by_conservative_rule")
    if pattern.wavelength is None:
        warnings.append("wavelength_missing")
    return PatternQC(
        len(pattern.two_theta), pattern.two_theta[0], pattern.two_theta[-1], median_step,
        relative_mad, noise, dynamic_range, peaks, warnings,
    )
