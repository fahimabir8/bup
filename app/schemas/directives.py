"""Domain models for directives and effective scenarios.

This module is the *canonical* typed representation of the directive
ontology. The LLM returns free-form dictionaries, but every value that
reaches the optimizer MUST pass through these typed models.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DirectiveTypeEnum(str, Enum):
    """The only supported directive types."""

    SOLAR_REDUCTION = "solar_reduction"
    MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
    NO_CHARGE_WINDOW = "no_charge_window"
    NO_DISCHARGE_WINDOW = "no_discharge_window"
    MAX_GRID_WINDOW = "max_grid_window"
    NO_OP = "no_op"


class BatteryActionEnum(str, Enum):
    """Battery action label exposed in the API."""

    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"


class DirectiveInterpretationItem(BaseModel):
    """One directive interpretation entry, as exposed in the response."""

    model_config = ConfigDict(extra="forbid")

    note_index: int = Field(..., ge=0)
    applies: bool
    directive_type: DirectiveTypeEnum
    structured_adjustment: Optional[Dict[str, Any]] = None
    explanation: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Per-directive structured adjustment schemas
# ---------------------------------------------------------------------------


class SolarReductionAdjustment(BaseModel):
    hours: List[int]
    factor: float

    @field_validator("hours")
    @classmethod
    def _check_hours(cls, value: List[int]) -> List[int]:
        if not value:
            raise ValueError("hours must be non-empty")
        if any(not isinstance(h, int) or h != int(h) for h in value):
            raise ValueError("hours must contain integer hours")
        if any(h < 0 or h > 23 for h in value):
            raise ValueError("hours must be in 0..23")
        if len(set(value)) != len(value):
            raise ValueError("hours must be unique")
        if value != sorted(value):
            raise ValueError("hours must be ascending")
        return value

    @field_validator("factor")
    @classmethod
    def _check_factor(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("factor must be in [0, 1]")
        return float(value)


class BatteryReserveAdjustment(BaseModel):
    hours: List[int]
    minimum_energy_kwh: float

    @field_validator("hours")
    @classmethod
    def _check_hours(cls, value: List[int]) -> List[int]:
        if not value:
            raise ValueError("hours must be non-empty")
        if any(not isinstance(h, int) for h in value):
            raise ValueError("hours must contain integer hours")
        if any(h < 0 or h > 23 for h in value):
            raise ValueError("hours must be in 0..23")
        if len(set(value)) != len(value):
            raise ValueError("hours must be unique")
        if value != sorted(value):
            raise ValueError("hours must be ascending")
        return value

    @field_validator("minimum_energy_kwh")
    @classmethod
    def _check_minimum(cls, value: float) -> float:
        if value < 0.0:
            raise ValueError("minimum_energy_kwh must be non-negative")
        return float(value)


class HoursOnlyAdjustment(BaseModel):
    hours: List[int]

    @field_validator("hours")
    @classmethod
    def _check_hours(cls, value: List[int]) -> List[int]:
        if not value:
            raise ValueError("hours must be non-empty")
        if any(not isinstance(h, int) for h in value):
            raise ValueError("hours must contain integer hours")
        if any(h < 0 or h > 23 for h in value):
            raise ValueError("hours must be in 0..23")
        if len(set(value)) != len(value):
            raise ValueError("hours must be unique")
        if value != sorted(value):
            raise ValueError("hours must be ascending")
        return value


class GridCapAdjustment(BaseModel):
    hours: List[int]
    max_grid_kwh: float

    @field_validator("hours")
    @classmethod
    def _check_hours(cls, value: List[int]) -> List[int]:
        if not value:
            raise ValueError("hours must be non-empty")
        if any(not isinstance(h, int) for h in value):
            raise ValueError("hours must contain integer hours")
        if any(h < 0 or h > 23 for h in value):
            raise ValueError("hours must be in 0..23")
        if len(set(value)) != len(value):
            raise ValueError("hours must be unique")
        if value != sorted(value):
            raise ValueError("hours must be ascending")
        return value

    @field_validator("max_grid_kwh")
    @classmethod
    def _check_max(cls, value: float) -> float:
        if value < 0.0:
            raise ValueError("max_grid_kwh must be non-negative")
        return float(value)


# ---------------------------------------------------------------------------
# Validated directive set
# ---------------------------------------------------------------------------


class ValidatedDirective(BaseModel):
    """A single, validated directive ready for the optimizer."""

    model_config = ConfigDict(extra="forbid")

    note_index: int = Field(..., ge=0)
    directive_type: DirectiveTypeEnum
    applies: bool
    adjustment: Dict[str, Any]


class ValidatedDirectiveSet(BaseModel):
    """The set of validated directives for one scenario."""

    model_config = ConfigDict(extra="forbid")

    directives: List[ValidatedDirective] = Field(default_factory=list)

    def by_type(self, dtype: DirectiveTypeEnum) -> List[ValidatedDirective]:
        return [d for d in self.directives if d.directive_type == dtype]


# ---------------------------------------------------------------------------
# Effective scenario (post-application view of the world)
# ---------------------------------------------------------------------------


class EffectiveScenario(BaseModel):
    """Deterministic, optimizer-facing view of the world."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    base_minimum_reserve: float = Field(..., ge=0)
    # Length 24 lists; hours must be ascending.
    effective_solar_kwh: List[float]
    active_minimum_reserve_kwh: List[float]
    max_charge_kwh_per_hour: List[float]
    max_discharge_kwh_per_hour: List[float]
    no_charge_hours: List[int]
    no_discharge_hours: List[int]
    grid_caps_kwh: List[float]
    solar_reduction_hours: List[int] = Field(default_factory=list)

    @field_validator("effective_solar_kwh", "active_minimum_reserve_kwh",
                     "max_charge_kwh_per_hour", "max_discharge_kwh_per_hour",
                     "grid_caps_kwh")
    @classmethod
    def _check_length_24(cls, value: List[float]) -> List[float]:
        if len(value) != 24:
            raise ValueError("list must have length 24")
        if any(v < 0 for v in value):
            raise ValueError("values must be non-negative")
        return [float(v) for v in value]

    @field_validator("no_charge_hours", "no_discharge_hours",
                     "solar_reduction_hours")
    @classmethod
    def _check_hour_lists(cls, value: List[int]) -> List[int]:
        if any(not isinstance(h, int) for h in value):
            raise ValueError("hours must be integers")
        if any(h < 0 or h > 23 for h in value):
            raise ValueError("hours must be in 0..23")
        if len(set(value)) != len(value):
            raise ValueError("hours must be unique")
        if value != sorted(value):
            raise ValueError("hours must be ascending")
        return list(value)


__all__ = [
    "DirectiveTypeEnum",
    "BatteryActionEnum",
    "DirectiveInterpretationItem",
    "SolarReductionAdjustment",
    "BatteryReserveAdjustment",
    "HoursOnlyAdjustment",
    "GridCapAdjustment",
    "ValidatedDirective",
    "ValidatedDirectiveSet",
    "EffectiveScenario",
]
