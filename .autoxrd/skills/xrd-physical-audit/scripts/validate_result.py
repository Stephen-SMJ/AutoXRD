#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def values(mapping: Any) -> list[float]:
    if isinstance(mapping, dict):
        return [float(value) for value in mapping.values()]
    if isinstance(mapping, list):
        return [float(value) for value in mapping]
    return []


def validate(data: dict[str, Any]) -> dict[str, Any]:
    hard: list[str] = []
    soft: list[str] = []
    metrics = data.get("metrics", data)
    for name in ("Rp", "Rwp", "Rexp", "GoF"):
        if name in metrics and not math.isfinite(float(metrics[name])):
            hard.append(f"non_finite_{name}")
    for occupancy in values(data.get("occupancies")):
        if occupancy < 0 or occupancy > 1:
            hard.append("occupancy_outside_0_1")
    for displacement in values(data.get("Biso")):
        if displacement <= 0:
            hard.append("non_positive_Biso")
        elif displacement > 20:
            soft.append("extreme_Biso_requires_justification")
    for fraction in values(data.get("phase_fractions")):
        if fraction < 0:
            hard.append("negative_phase_fraction")
    for cell_value in values(data.get("cell")):
        if cell_value <= 0:
            hard.append("non_positive_cell_parameter")
    if data.get("singular_matrix"):
        hard.append("singular_matrix")
    if data.get("diverged"):
        hard.append("refinement_diverged")
    max_correlation = data.get("max_abs_correlation")
    if max_correlation is not None and abs(float(max_correlation)) > 0.95:
        soft.append("severe_parameter_correlation")
    return {
        "accepted": not hard,
        "hard_failures": sorted(set(hard)),
        "warnings": sorted(set(soft)),
        "requires_domain_review": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Boundary checks for parsed refinement results")
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    data = json.loads(args.result.read_text(encoding="utf-8"))
    print(json.dumps(validate(data), indent=2))


if __name__ == "__main__":
    main()
