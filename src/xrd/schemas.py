"""Typed contracts for auditable powder-XRD refinement workflows."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RefinementStage(str, Enum):
    QC = "qc"
    PROFILE_MATCH = "profile_match"
    INSTRUMENT = "instrument"
    STRUCTURE = "structure"
    MICROSTRUCTURE = "microstructure"
    FINAL_AUDIT = "final_audit"


class ActionKind(str, Enum):
    REFINE_SCALE = "refine_scale"
    REFINE_ZERO = "refine_zero"
    REFINE_BACKGROUND = "refine_background"
    REFINE_LATTICE = "refine_lattice"
    REFINE_PROFILE = "refine_profile"
    REFINE_ASYMMETRY = "refine_asymmetry"
    REFINE_POSITIONS = "refine_atomic_positions"
    REFINE_BISO = "refine_biso"
    REFINE_OCCUPANCY = "refine_occupancy"
    REFINE_ORIENTATION = "refine_preferred_orientation"
    REFINE_SIZE_STRAIN = "refine_size_strain"
    FREEZE_PARAMETER = "freeze_unstable_parameter"
    ADD_PHASE = "add_phase"
    REMOVE_PHASE = "remove_phase"
    EXCLUDE_REGION = "exclude_region"
    SWITCH_PROFILE = "switch_profile_function"


@dataclass(frozen=True)
class Evidence:
    feature: str
    value: float | str | bool
    source: str
    threshold: str


@dataclass(frozen=True)
class FalsifiablePrediction:
    metric: str
    direction: str
    minimum_change: float = 0.0

    def __post_init__(self) -> None:
        if self.direction not in {"increase", "decrease"}:
            raise ValueError("prediction direction must be increase or decrease")
        if self.minimum_change < 0 or not math.isfinite(self.minimum_change):
            raise ValueError("minimum_change must be finite and non-negative")


@dataclass(frozen=True)
class RefinementAction:
    kind: ActionKind
    stage: RefinementStage
    parameters: tuple[str, ...]
    rationale: str
    evidence: tuple[Evidence, ...]
    predictions: tuple[FalsifiablePrediction, ...]
    bounds: dict[str, tuple[float, float]] = field(default_factory=dict)
    parent_run_id: str | None = None

    def __post_init__(self) -> None:
        if not self.parameters:
            raise ValueError("a refinement action must name at least one parameter")
        if not self.rationale.strip():
            raise ValueError("a refinement action must include a rationale")
        if not self.evidence:
            raise ValueError("a refinement action must cite machine-readable evidence")
        if not self.predictions:
            raise ValueError("a refinement action must make a falsifiable prediction")
        for name, (lower, upper) in self.bounds.items():
            if not name or not (math.isfinite(lower) and math.isfinite(upper) and lower < upper):
                raise ValueError(f"invalid bound for {name!r}")


@dataclass(frozen=True)
class FitSnapshot:
    rwp: float
    rexp: float
    gof: float
    residual_score: float
    unexplained_peak_ratio: float
    physical_violations: tuple[str, ...] = ()
    parameter_count: int = 0
    max_abs_correlation: float | None = None
    features: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        numeric = (self.rwp, self.rexp, self.gof, self.residual_score,
                   self.unexplained_peak_ratio)
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("fit snapshot contains a non-finite metric")
        if not 0 <= self.unexplained_peak_ratio <= 1:
            raise ValueError("unexplained_peak_ratio must be in [0, 1]")
        if self.parameter_count < 0:
            raise ValueError("parameter_count cannot be negative")


@dataclass(frozen=True)
class GateDecision:
    accepted: bool
    mechanism_supported: bool
    reasons: tuple[str, ...]
    satisfied_predictions: tuple[str, ...]
    failed_predictions: tuple[str, ...]
    utility_delta: float


def canonical_json(value: Any) -> str:
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
