from xrd.structure import audit_structure


def valid_structure():
    return {
        "lattice": {"a": 5, "b": 5, "c": 5, "alpha": 90, "beta": 90, "gamma": 90},
        "minimum_distance": 2.1,
        "sites": [
            {"label": "Na1", "occupancy": 1, "fractional_coordinates": [0, 0, 0]},
            {"label": "Cl1", "occupancy": 1, "fractional_coordinates": [0.5, 0.5, 0.5]},
        ],
    }


def test_structure_audit_accepts_basic_valid_model():
    report = audit_structure(valid_structure())
    assert report["accepted"]
    assert report["site_count"] == 2
    assert len(report["structure_fingerprint"]) == 64


def test_structure_audit_rejects_overlap_and_occupancy():
    data = valid_structure()
    data["minimum_distance"] = 0.2
    data["sites"][0]["occupancy"] = 1.2
    report = audit_structure(data)
    assert not report["accepted"]
    assert "severe_atomic_overlap" in report["hard_failures"]
    assert "invalid_occupancy:Na1" in report["hard_failures"]
