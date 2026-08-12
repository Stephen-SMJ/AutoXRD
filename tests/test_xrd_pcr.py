from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from xrd.pcr import (
    compile_action,
    compile_spec,
    parse_pcr_text,
    validate_le_bail_initialization,
    validate_mvp_document,
)
from xrd.schemas import (
    ActionKind,
    Evidence,
    FalsifiablePrediction,
    RefinementAction,
    RefinementStage,
)


RIETVELD_PCR = """COMM Minimal guarded test
!Job Npr Nph Nba Nex Nsc Nor Dum Iwg Ilo Ias Res Ste Nre Cry Uni Cor Opt Aut
 0 5 1 0 0 0 0 1 0 0 1 0 0 0 0 0 0 0 0
! 0 !Number of refined parameters
 3 !Number of refined parameters
!  Zero    Code    SyCos    Code   SySin    Code  Lambda     Code MORE
 0.01 11.0 0 0 0 0 0 0 0
! Background coefficients/codes for Pattern# 1
 10 2 0 0 0 0
 21 31 0 0 0 0
! Data for PHASE number: 1
Phase A
!Nat Dis Ang Pr1 Pr2 Pr3 Jbt Irf Isy Str Furth ATZ Nvk Npr More
 1 0 0 0 0 1 0 0 0 0 0 100 0 5 0
P m -3 m
!Atom Typ X Y Z Biso Occ In Fin N_t Spc /Codes
A A 0 0 0 1 1 0 0 0 0
 0 0 0 0 0
! Scale Shape1 Bov Str1 Str2 Str3 Strain-Model
 1 0 0 0 0 0 0
 0 0 0 0 0 0
! U V W X Y GauSiz LorSiz Size-Model
 0.01 0 0.01 0 0 0 0 0
 0 0 0 0 0 0 0
! a b c alpha beta gamma #Cell Info
 5 5 5 90 90 90
 0 0 0 0 0 0
! Pref1 Pref2 Asy1 Asy2 Asy3 Asy4
 0 0 0 0 0 0
 0 0 0 0 0 0
"""


LE_BAIL_PCR = RIETVELD_PCR.replace(
    " 3 !Number of refined parameters", " 0 !Number of refined parameters"
).replace(
    " 0.01 11.0 0 0 0 0 0 0 0", " 0.01 0 0 0 0 0 0 0 0"
).replace(
    " 21 31 0 0 0 0", " 0 0 0 0 0 0"
).replace(
    " 1 0 0 0 0 1 0 0 0 0 0 100 0 5 0",
    " 0 0 0 0 0 1 2 0 0 0 0 0 0 5 0",
).replace(
    "!Atom Typ X Y Z Biso Occ In Fin N_t Spc /Codes\nA A 0 0 0 1 1 0 0 0 0\n 0 0 0 0 0\n",
    "",
)


def action(kind: ActionKind, parameter: str) -> RefinementAction:
    return RefinementAction(
        kind=kind,
        stage=RefinementStage.PROFILE_MATCH,
        parameters=(parameter,),
        rationale="A deterministic feature supports this bounded intervention.",
        evidence=(Evidence("test_feature", 1.0, "residual.json", ">0.5"),),
        predictions=(FalsifiablePrediction("residual_score", "decrease", 0.01),),
    )


def test_parser_catalogues_supported_parameter_blocks():
    document = parse_pcr_text(RIETVELD_PCR)
    assert validate_mvp_document(document) == ()
    assert document.declared_parameters == 3
    assert document.slot_map()["global.zero"].group == 1
    assert document.slot_map()["background.b1"].group == 3
    assert "phase.1.atom.A.biso" in document.slot_map()


def test_le_bail_initialization_requires_official_first_run_controls():
    assert validate_le_bail_initialization(parse_pcr_text(LE_BAIL_PCR)) == ()
    failures = validate_le_bail_initialization(parse_pcr_text(RIETVELD_PCR))
    assert "le_bail_initialization_requires_maxs_0" in failures
    assert "phase_1_le_bail_requires_jbt_2" in failures


def test_compile_freezes_template_and_preserves_shared_cell_constraint():
    source = RIETVELD_PCR.replace(" 0 0 0 0 0 0\n! Pref1", " 41 41 41 0 0 0\n! Pref1")
    source = source.replace(" 3 !Number", " 4 !Number")
    document = parse_pcr_text(source)
    compiled, report = compile_action(
        document, action(ActionKind.REFINE_LATTICE, "phase.1.cell.a"),
        ("phase.1.cell.a",),
    )
    result = parse_pcr_text(compiled)
    assert result.declared_parameters == 1
    assert result.slot_map()["phase.1.cell.a"].code == 11
    assert result.slot_map()["phase.1.cell.b"].code == 11
    assert result.slot_map()["phase.1.cell.c"].code == 11
    assert result.slot_map()["global.zero"].code == 0
    assert result.aut == 0
    assert report["constraint_expanded"] == ["phase.1.cell.b", "phase.1.cell.c"]


def test_compile_rejects_selector_outside_action_family():
    with pytest.raises(ValueError, match="selector_not_allowed"):
        compile_action(
            parse_pcr_text(RIETVELD_PCR),
            action(ActionKind.REFINE_ZERO, "phase.1.cell.a"),
            ("phase.1.cell.a",),
        )


def test_validator_rejects_uncatalogued_active_codeword():
    broken = RIETVELD_PCR.replace(" 3 !Number", " 4 !Number")
    assert "uncatalogued_or_inconsistent_active_codeword" in validate_mvp_document(
        parse_pcr_text(broken)
    )


def test_compile_spec_checks_template_hash_and_writes_provenance(tmp_path: Path):
    template = tmp_path / "source.pcr"
    output = tmp_path / "compiled.pcr"
    spec_path = tmp_path / "spec.json"
    template.write_text(RIETVELD_PCR, encoding="latin-1")
    typed_action = replace(
        action(ActionKind.REFINE_BACKGROUND, "background.b0"),
        parameters=("background.b0", "background.b1"),
    )
    spec = {
        "template": str(template),
        "template_sha256": hashlib.sha256(template.read_bytes()).hexdigest(),
        "output": str(output),
        "action": asdict(typed_action),
        "selectors": ["background.b0", "background.b1"],
    }
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    report = compile_spec(spec_path)
    assert output.exists()
    assert output.with_suffix(".compile.json").exists()
    assert report.refined_groups == 2

    spec["template_sha256"] = "0" * 64
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        compile_spec(spec_path)


def test_compiler_rejects_unbounded_structure_actions():
    structural = RefinementAction(
        ActionKind.REFINE_BISO, RefinementStage.STRUCTURE, ("phase.1.atom.A.biso",),
        "A structural test requires numerical limits not implemented by this compiler.",
        (Evidence("site_residual", 1.0, "residual.json", ">0.5"),),
        (FalsifiablePrediction("residual_score", "decrease", 0.01),),
        bounds={"phase.1.atom.A.biso": (0.0, 5.0)},
    )
    with pytest.raises(ValueError, match="action_not_supported_by_pcr_compiler"):
        compile_action(parse_pcr_text(RIETVELD_PCR), structural, structural.parameters)


def test_le_bail_compiler_rejects_scale_refinement():
    scale = action(ActionKind.REFINE_SCALE, "phase.1.scale")
    with pytest.raises(ValueError, match="constant_scale"):
        compile_action(parse_pcr_text(LE_BAIL_PCR), scale, scale.parameters)


def test_compiler_rejects_stale_fullprof_limit_records():
    limited = RIETVELD_PCR + "! Limits for selected parameters:\n 1 -0.1 0.1 0 0 zero\n"
    failures = validate_mvp_document(parse_pcr_text(limited))
    assert "existing_parameter_limits_require_remapping_support" in failures
