"""Conservative structure checks with optional pymatgen CIF support."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


def audit_structure(data: dict[str, Any]) -> dict[str, Any]:
    hard: list[str] = []
    warnings: list[str] = []
    lattice = data.get("lattice", {})
    for name in ("a", "b", "c"):
        value = lattice.get(name)
        if value is None or not math.isfinite(float(value)) or float(value) <= 0:
            hard.append(f"invalid_lattice_{name}")
    for name in ("alpha", "beta", "gamma"):
        value = lattice.get(name)
        if value is None or not math.isfinite(float(value)) or not 0 < float(value) < 180:
            hard.append(f"invalid_lattice_{name}")
    sites = data.get("sites", [])
    if not sites:
        hard.append("no_atomic_sites")
    labels: set[str] = set()
    for index, site in enumerate(sites):
        label = str(site.get("label", ""))
        if not label:
            warnings.append(f"site_{index}_missing_label")
        elif label in labels:
            warnings.append(f"duplicate_site_label:{label}")
        labels.add(label)
        occupancy = site.get("occupancy", 1.0)
        if not math.isfinite(float(occupancy)) or not 0 <= float(occupancy) <= 1:
            hard.append(f"invalid_occupancy:{label or index}")
        coordinates = site.get("fractional_coordinates", ())
        if len(coordinates) != 3 or any(not math.isfinite(float(value)) for value in coordinates):
            hard.append(f"invalid_fractional_coordinates:{label or index}")
    minimum_distance = data.get("minimum_distance")
    if minimum_distance is not None and float(minimum_distance) < 0.5:
        hard.append("severe_atomic_overlap")
    elif minimum_distance is not None and float(minimum_distance) < 0.8:
        warnings.append("short_interatomic_distance_requires_review")
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "accepted": not hard,
        "hard_failures": sorted(set(hard)),
        "warnings": sorted(set(warnings)),
        "site_count": len(sites),
        "structure_fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def cif_to_structure_dict(path: Path) -> dict[str, Any]:
    try:
        from pymatgen.core import Structure
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    except ImportError as exc:
        raise RuntimeError("CIF auditing requires the optional xrd dependencies") from exc
    structure = Structure.from_file(path)
    distances = structure.distance_matrix
    positive_distances = [float(value) for row in distances for value in row if value > 1e-8]
    analyzer = SpacegroupAnalyzer(structure, symprec=0.01)
    sites: list[dict[str, Any]] = []
    for index, site in enumerate(structure):
        occupancy = sum(float(amount) for amount in site.species.values())
        source_label = site.label or f"site_{index}"
        sites.append({
            # pymatgen expands symmetry-equivalent positions. Preserve the CIF label as
            # provenance while assigning a unique identifier to each expanded site.
            "label": f"{source_label}_{index}",
            "source_label": source_label,
            "species": {str(element): float(amount) for element, amount in site.species.items()},
            "occupancy": occupancy,
            "fractional_coordinates": [float(value) for value in site.frac_coords],
        })
    return {
        "source": str(path.resolve()),
        "formula": structure.composition.reduced_formula,
        "space_group": analyzer.get_space_group_symbol(),
        "space_group_number": analyzer.get_space_group_number(),
        "lattice": {
            "a": structure.lattice.a, "b": structure.lattice.b, "c": structure.lattice.c,
            "alpha": structure.lattice.alpha, "beta": structure.lattice.beta,
            "gamma": structure.lattice.gamma,
        },
        "density": structure.density,
        "minimum_distance": min(positive_distances) if positive_distances else None,
        "sites": sites,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a candidate CIF before refinement")
    parser.add_argument("cif", type=Path)
    args = parser.parse_args()
    data = cif_to_structure_dict(args.cif)
    print(json.dumps({"structure": data, "audit": audit_structure(data)}, indent=2))


if __name__ == "__main__":
    main()
