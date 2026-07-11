from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from features.skills import clear_skills, discover_skills, get_skill


ROOT = Path(__file__).parents[1]


def test_project_xrd_skills_are_discoverable():
    clear_skills()
    loaded = discover_skills(str(ROOT))

    names = {skill.name for skill in loaded}
    assert {
        "xrd-pattern-qc",
        "fullprof-staged-refinement",
        "xrd-residual-diagnosis",
        "xrd-physical-audit",
    } <= names
    prompt = get_skill("xrd-pattern-qc").get_prompt("scan.xy")
    assert "scan.xy" in prompt
    assert "AUTOXRD_SKILL_DIR" not in prompt


def test_pattern_qc_script_emits_pattern_state(tmp_path: Path):
    pattern = tmp_path / "scan.xy"
    rows = [f"{10 + index * 0.02:.2f} {100 + (1000 if index == 25 else 0)}" for index in range(60)]
    pattern.write_text("\n".join(rows), encoding="utf-8")
    script = ROOT / ".autoxrd/skills/xrd-pattern-qc/scripts/pattern_qc.py"

    result = subprocess.run(
        [sys.executable, str(script), str(pattern)],
        check=True,
        capture_output=True,
        text=True,
    )
    state = json.loads(result.stdout)

    assert state["point_count"] == 60
    assert state["detected_peak_count"] == 1
    assert state["radiation"] == "unknown"


def test_physical_validator_rejects_hard_violations(tmp_path: Path):
    script = ROOT / ".autoxrd/skills/xrd-physical-audit/scripts/validate_result.py"
    spec = importlib.util.spec_from_file_location("validate_result", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    report = module.validate(
        {"metrics": {"Rwp": 3.2}, "occupancies": {"A": 1.4}, "phase_fractions": [0.8, -0.1]}
    )

    assert report["accepted"] is False
    assert "occupancy_outside_0_1" in report["hard_failures"]
    assert "negative_phase_fraction" in report["hard_failures"]
