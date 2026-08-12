"""Conservative FullProf PCR cataloguing and typed codeword compilation.

The compiler edits only refinement code fields discovered through FullProf's
comment anchors. It does not generate arbitrary PCR syntax or infer symmetry.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .schemas import ActionKind, RefinementAction
from .trajectory import action_from_dict, validate_action


_PHASE_RE = re.compile(r"Data for PHASE number:\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class CodeSlot:
    key: str
    value: float
    code: float
    code_line: int
    code_column: int

    @property
    def group(self) -> int | None:
        return int(abs(self.code) // 10) if abs(self.code) >= 10 else None


@dataclass(frozen=True)
class PhaseControl:
    phase: int
    line: int
    nat: int
    jbt: int
    irf: int
    isy: int


@dataclass
class PCRDocument:
    lines: list[str]
    slots: list[CodeSlot]
    phases: list[PhaseControl]
    declared_parameters: int
    declared_parameters_line: int
    job: int
    pattern_count: int
    declared_phase_count: int
    aut: int
    job_line: int
    has_parameter_limits: bool
    warnings: list[str] = field(default_factory=list)

    def slot_map(self) -> dict[str, CodeSlot]:
        return {slot.key: slot for slot in self.slots}


@dataclass(frozen=True)
class CompilationReport:
    input_sha256: str
    output_sha256: str
    action_kind: str
    requested_selectors: tuple[str, ...]
    directly_selected: tuple[str, ...]
    constraint_expanded: tuple[str, ...]
    refined_groups: int
    output_path: str
    warnings: tuple[str, ...]


_ACTION_PREFIXES: dict[ActionKind, tuple[str, ...]] = {
    ActionKind.REFINE_SCALE: ("phase.*.scale",),
    ActionKind.REFINE_ZERO: ("global.zero",),
    ActionKind.REFINE_BACKGROUND: ("background.*",),
    ActionKind.REFINE_LATTICE: ("phase.*.cell.*",),
    ActionKind.REFINE_PROFILE: (
        "phase.*.shape1", "phase.*.profile.*", "phase.*.lambda2_profile.*",
    ),
    ActionKind.REFINE_ASYMMETRY: ("phase.*.asymmetry.*",),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _numeric_tokens(line: str) -> list[float]:
    content = line.split("!", 1)[0].split("#", 1)[0]
    values: list[float] = []
    for token in content.split():
        try:
            values.append(float(token))
        except ValueError:
            break
    return values


def _next_numeric(lines: list[str], start: int, minimum: int = 1) -> int:
    for index in range(start, len(lines)):
        values = _numeric_tokens(lines[index])
        if len(values) >= minimum:
            return index
    raise ValueError(f"PCR ended before a numeric line after line {start + 1}")


def _next_data(lines: list[str], start: int) -> int:
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if stripped and not stripped.startswith("!"):
            return index
    raise ValueError(f"PCR ended before a data line after line {start + 1}")


def _find_anchor(lines: list[str], needle: str) -> int:
    normalized_needle = re.sub(r"\s+", " ", needle.lower()).strip()
    for index, line in enumerate(lines):
        normalized_line = re.sub(r"\s+", " ", line.lower()).strip()
        if normalized_needle in normalized_line:
            return index
    raise ValueError(f"required PCR anchor not found: {needle}")


def _add_pair(slots: list[CodeSlot], lines: list[str], prefix: str, names: tuple[str, ...],
              anchor: int, value_offset: int = 1) -> None:
    value_line = _next_numeric(lines, anchor + value_offset, len(names))
    code_line = _next_numeric(lines, value_line + 1, len(names))
    values = _numeric_tokens(lines[value_line])
    codes = _numeric_tokens(lines[code_line])
    for column, name in enumerate(names):
        slots.append(CodeSlot(f"{prefix}.{name}", values[column], codes[column], code_line, column))


def parse_pcr_text(text: str) -> PCRDocument:
    lines = text.splitlines()
    if not lines:
        raise ValueError("PCR is empty")
    job_anchor = _find_anchor(lines, "!Job Npr Nph")
    job_line = _next_numeric(lines, job_anchor + 1, 19)
    job_values = _numeric_tokens(lines[job_line])
    job, nph, aut = int(job_values[0]), int(job_values[2]), int(job_values[18])
    maxs_anchor = _find_anchor(lines, "Number of refined parameters")
    maxs_line = _next_numeric(lines, maxs_anchor, 1)
    maxs = int(_numeric_tokens(lines[maxs_line])[0])

    slots: list[CodeSlot] = []
    zero_anchor = _find_anchor(lines, "!  Zero")
    zero_line = _next_numeric(lines, zero_anchor + 1, 8)
    zero_values = _numeric_tokens(lines[zero_line])
    for name, value_column, code_column in (
        ("zero", 0, 1), ("sycos", 2, 3), ("sysin", 4, 5), ("wavelength_offset", 6, 7),
    ):
        slots.append(CodeSlot(f"global.{name}", zero_values[value_column],
                              zero_values[code_column], zero_line, code_column))

    background_anchor = _find_anchor(lines, "Background coefficients/codes")
    background_values_line = _next_numeric(lines, background_anchor + 1)
    background_codes_line = _next_numeric(lines, background_values_line + 1)
    background_values = _numeric_tokens(lines[background_values_line])
    background_codes = _numeric_tokens(lines[background_codes_line])
    if len(background_values) != len(background_codes):
        raise ValueError("background value/code counts differ")
    for column, (value, code) in enumerate(zip(background_values, background_codes)):
        slots.append(CodeSlot(f"background.b{column}", value, code,
                              background_codes_line, column))

    phases: list[PhaseControl] = []
    current_phase: int | None = None
    pending_nat: tuple[int, int] | None = None
    for index, line in enumerate(lines):
        phase_match = _PHASE_RE.search(line)
        if phase_match:
            current_phase = int(phase_match.group(1))
            continue
        if current_phase is None:
            if "Microabsorption coefficients" in line:
                pair_line = _next_numeric(lines, index + 1, 6)
                pairs = _numeric_tokens(lines[pair_line])
                for column, name in enumerate(("p0", "cp", "tau")):
                    slots.append(CodeSlot(f"microabsorption.{name}", pairs[column * 2],
                                          pairs[column * 2 + 1], pair_line, column * 2 + 1))
            continue
        lowered = line.lower()
        if line.lstrip().startswith("!Nat "):
            control_line = _next_numeric(lines, index + 1, 15)
            controls = _numeric_tokens(lines[control_line])
            phase = PhaseControl(current_phase, control_line, int(controls[0]), int(controls[6]),
                                 int(controls[7]), int(controls[8]))
            phases.append(phase)
            pending_nat = (phase.nat, control_line)
        elif line.lstrip().startswith("!Atom"):
            if pending_nat is None:
                raise ValueError(f"atom block at line {index + 1} has no phase control")
            nat, _ = pending_nat
            cursor = index + 1
            for _ in range(nat):
                value_line = _next_data(lines, cursor)
                raw = lines[value_line].split("#", 1)[0].split()
                if len(raw) < 7:
                    raise ValueError(f"invalid atom value line {value_line + 1}")
                label = raw[0]
                code_line = _next_numeric(lines, value_line + 1, 5)
                values = [float(value) for value in raw[2:7]]
                codes = _numeric_tokens(lines[code_line])
                for column, name in enumerate(("x", "y", "z", "biso", "occupancy")):
                    slots.append(CodeSlot(
                        f"phase.{current_phase}.atom.{label}.{name}", values[column],
                        codes[column], code_line, column,
                    ))
                cursor = code_line + 1
        elif "Scale" in line and "Shape1" in line and line.lstrip().startswith("!"):
            _add_pair(slots, lines, f"phase.{current_phase}",
                      ("scale", "shape1", "bov", "strain.str1", "strain.str2", "strain.str3"), index)
        elif re.search(r"!\s+U\s+V\s+W\s+X\s+Y", line, re.IGNORECASE):
            _add_pair(slots, lines, f"phase.{current_phase}.profile",
                      ("u", "v", "w", "x", "y", "gausiz", "lorsiz"), index)
        elif "#Cell Info" in line or re.search(r"!\s+a\s+b\s+c\s+alpha", line, re.IGNORECASE):
            _add_pair(slots, lines, f"phase.{current_phase}.cell",
                      ("a", "b", "c", "alpha", "beta", "gamma"), index)
        elif "Pref1" in line and "Asy1" in line:
            value_line = _next_numeric(lines, index + 1, 6)
            count = min(len(_numeric_tokens(lines[value_line])), 8)
            names = ("orientation.pref1", "orientation.pref2", "asymmetry.asy1",
                     "asymmetry.asy2", "asymmetry.asy3", "asymmetry.asy4",
                     "profile.sl", "profile.dl")[:count]
            _add_pair(slots, lines, f"phase.{current_phase}", names, index)
        elif "Additional U,V,W parameters for Lambda2" in line:
            _add_pair(slots, lines, f"phase.{current_phase}.lambda2_profile",
                      ("u", "v", "w"), index)

    warnings: list[str] = []
    if len(phases) != nph:
        warnings.append("declared_phase_count_mismatch")
    duplicate_keys = sorted({slot.key for slot in slots if sum(other.key == slot.key for other in slots) > 1})
    if duplicate_keys:
        raise ValueError("duplicate PCR parameter keys: " + ", ".join(duplicate_keys))
    pattern_numbers = {
        int(match.group(1)) for line in lines
        for match in re.finditer(r"Patt#\s*(\d+)", line, re.IGNORECASE)
    }
    return PCRDocument(
        lines=lines, slots=slots, phases=phases, declared_parameters=maxs,
        declared_parameters_line=maxs_line, job=job,
        pattern_count=max(pattern_numbers, default=1),
        declared_phase_count=nph, aut=aut, job_line=job_line, warnings=warnings,
        has_parameter_limits=any(
            "limits for selected parameters" in line.lower() for line in lines
        ),
    )


def parse_pcr(path: Path) -> PCRDocument:
    return parse_pcr_text(path.read_text(encoding="latin-1", errors="replace"))


def validate_mvp_document(document: PCRDocument) -> tuple[str, ...]:
    failures = list(document.warnings)
    if document.job != 0:
        failures.append("mvp_requires_constant_wavelength_xrd_job_0")
    if document.declared_phase_count not in {1, 2}:
        failures.append("mvp_supports_one_or_two_phases")
    if document.pattern_count != 1:
        failures.append("mvp_requires_single_pattern")
    if any(phase.jbt not in {0, 2} for phase in document.phases):
        failures.append("unsupported_phase_model_for_mvp")
    if any(phase.isy != 0 for phase in document.phases):
        failures.append("mvp_requires_space_group_generated_symmetry")
    if document.has_parameter_limits:
        failures.append("existing_parameter_limits_require_remapping_support")
    if document.declared_parameters:
        catalogued_groups = {slot.group for slot in document.slots if slot.group is not None}
        expected_groups = set(range(1, document.declared_parameters + 1))
        if catalogued_groups != expected_groups:
            failures.append("uncatalogued_or_inconsistent_active_codeword")
    return tuple(sorted(set(failures)))


def validate_le_bail_initialization(document: PCRDocument) -> tuple[str, ...]:
    failures = list(validate_mvp_document(document))
    if document.declared_parameters != 0:
        failures.append("le_bail_initialization_requires_maxs_0")
    if document.aut != 0:
        failures.append("le_bail_initialization_requires_aut_0")
    for phase in document.phases:
        if phase.nat != 0:
            failures.append(f"phase_{phase.phase}_le_bail_requires_nat_0")
        if phase.jbt != 2:
            failures.append(f"phase_{phase.phase}_le_bail_requires_jbt_2")
        if phase.irf != 0:
            failures.append(f"phase_{phase.phase}_le_bail_first_run_requires_irf_0")
    return tuple(sorted(set(failures)))


def _selector_allowed(kind: ActionKind, selector: str) -> bool:
    return any(fnmatch.fnmatchcase(selector, pattern) for pattern in _ACTION_PREFIXES.get(kind, ()))


def _format_code(value: float) -> str:
    return f"{value:.2f}"


def compile_action(document: PCRDocument, action: RefinementAction,
                   selectors: tuple[str, ...]) -> tuple[str, dict[str, Any]]:
    failures = list(validate_mvp_document(document)) + list(validate_action(action))
    if action.kind not in _ACTION_PREFIXES:
        failures.append("action_not_supported_by_pcr_compiler")
    if not selectors:
        failures.append("at_least_one_parameter_selector_is_required")
    for selector in selectors:
        if not _selector_allowed(action.kind, selector):
            failures.append(f"selector_not_allowed_for_action:{selector}")
    if set(selectors) != set(action.parameters):
        failures.append("selectors_must_equal_typed_action_parameters")
    if action.kind == ActionKind.REFINE_SCALE and any(phase.jbt == 2 for phase in document.phases):
        failures.append("le_bail_jbt_2_requires_constant_scale")
    if failures:
        raise ValueError("; ".join(sorted(set(failures))))

    directly_selected: set[str] = set()
    for selector in selectors:
        matches = {slot.key for slot in document.slots if fnmatch.fnmatchcase(slot.key, selector)}
        if not matches:
            raise ValueError(f"selector matched no catalogued parameter: {selector}")
        directly_selected.update(matches)

    selected = set(directly_selected)
    original_groups = {slot.group for slot in document.slots
                       if slot.key in directly_selected and slot.group is not None}
    selected.update(slot.key for slot in document.slots if slot.group in original_groups)
    slot_by_key = document.slot_map()
    crossed = sorted(key for key in selected if not _selector_allowed(action.kind, key))
    if crossed:
        raise ValueError("constraint crosses typed action boundary: " + ", ".join(crossed))

    groups: list[list[str]] = []
    handled: set[str] = set()
    for key in sorted(selected):
        if key in handled:
            continue
        group = slot_by_key[key].group
        members = sorted(item for item in selected if slot_by_key[item].group == group) if group else [key]
        groups.append(members)
        handled.update(members)

    tokens_by_line: dict[int, list[str]] = {}
    for slot in document.slots:
        tokens_by_line.setdefault(slot.code_line, document.lines[slot.code_line].split())
        tokens_by_line[slot.code_line][slot.code_column] = _format_code(0.0)
    for group_number, keys in enumerate(groups, start=1):
        for key in keys:
            slot = slot_by_key[key]
            multiplier = abs(slot.code) - (slot.group or 0) * 10 if slot.group else 1.0
            if multiplier <= 0 or multiplier >= 10:
                multiplier = 1.0
            sign = -1.0 if slot.code < 0 else 1.0
            code = sign * (group_number * 10 + multiplier)
            tokens_by_line[slot.code_line][slot.code_column] = _format_code(code)

    output_lines = list(document.lines)
    for line_number, tokens in tokens_by_line.items():
        output_lines[line_number] = "  " + "  ".join(tokens)
    maxs_tokens = output_lines[document.declared_parameters_line].split()
    maxs_tokens[0] = str(len(groups))
    output_lines[document.declared_parameters_line] = "       " + "  ".join(maxs_tokens)
    job_tokens = output_lines[document.job_line].split()
    job_tokens[18] = "0"
    output_lines[document.job_line] = "   " + "   ".join(job_tokens)
    output = "\n".join(output_lines) + "\n"
    warnings = list(document.warnings)
    if document.aut != 0:
        warnings.append("automatic_codeword_assignment_disabled")
    metadata = {
        "directly_selected": sorted(directly_selected),
        "constraint_expanded": sorted(selected - directly_selected),
        "refined_groups": len(groups),
        "warnings": warnings,
    }
    return output, metadata


def compile_spec(spec_path: Path) -> CompilationReport:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    template = Path(spec["template"]).expanduser().resolve()
    output_path = Path(spec["output"]).expanduser().resolve()
    if template == output_path:
        raise ValueError("compiler refuses to overwrite the source PCR template")
    input_bytes = template.read_bytes()
    expected_hash = spec.get("template_sha256")
    actual_hash = _sha256(input_bytes)
    if expected_hash and expected_hash != actual_hash:
        raise ValueError("template SHA-256 does not match the compilation spec")
    document = parse_pcr_text(input_bytes.decode("latin-1", errors="replace"))
    action = action_from_dict(spec["action"])
    selectors = tuple(spec.get("selectors", action.parameters))
    compiled, metadata = compile_action(document, action, selectors)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(compiled, encoding="latin-1", newline="\n")
    report = CompilationReport(
        input_sha256=actual_hash,
        output_sha256=_sha256(compiled.encode("latin-1")),
        action_kind=action.kind.value,
        requested_selectors=selectors,
        directly_selected=tuple(metadata["directly_selected"]),
        constraint_expanded=tuple(metadata["constraint_expanded"]),
        refined_groups=metadata["refined_groups"],
        output_path=str(output_path),
        warnings=tuple(metadata["warnings"]),
    )
    report_path = output_path.with_suffix(".compile.json")
    report_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    return report


def inspect_document(path: Path) -> dict[str, Any]:
    document = parse_pcr(path)
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path.read_bytes()),
        "job": document.job,
        "declared_phase_count": document.declared_phase_count,
        "declared_parameters": document.declared_parameters,
        "aut": document.aut,
        "has_parameter_limits": document.has_parameter_limits,
        "phases": [asdict(phase) for phase in document.phases],
        "catalogued_parameter_count": len(document.slots),
        "parameters": [asdict(slot) for slot in document.slots],
        "mvp_failures": validate_mvp_document(document),
        "le_bail_initialization_failures": validate_le_bail_initialization(document),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or compile a guarded FullProf PCR")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("pcr", type=Path)
    validate_parser = subparsers.add_parser("validate-le-bail")
    validate_parser.add_argument("pcr", type=Path)
    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("spec", type=Path)
    args = parser.parse_args()
    if args.command == "inspect":
        result = inspect_document(args.pcr)
    elif args.command == "validate-le-bail":
        failures = validate_le_bail_initialization(parse_pcr(args.pcr))
        result = {"valid": not failures, "failures": failures}
    else:
        result = asdict(compile_spec(args.spec))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
