"""Top-level response validator.

Calls the canonical replay validator and recomputes totals. Returns a
structured result that the API layer can use to decide whether the
optimization succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.schemas.directives import DirectiveInterpretationItem
from app.schemas.request import BatteryInput, HourlyInput
from app.schemas.response import HourlyPlanItem
from app.validation.replay import (
    ValidationResult,
    recalculate_totals,
    replay_plan,
)


@dataclass
class ResponseValidationReport:
    valid: bool
    errors: List[str]
    warnings: List[str]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float

    @property
    def is_ok(self) -> bool:
        return self.valid


def validate_response(
    plan: List[HourlyPlanItem],
    hours: List[HourlyInput],
    battery: BatteryInput,
    interpretations: List[DirectiveInterpretationItem],
) -> ResponseValidationReport:
    """Validate the candidate API response end-to-end."""

    replay = replay_plan(plan, hours, battery, interpretations)
    total_grid, total_cost, peak_grid = recalculate_totals(plan, hours)

    return ResponseValidationReport(
        valid=replay.valid,
        errors=list(replay.errors),
        warnings=list(replay.warnings),
        total_grid_kwh=total_grid,
        total_cost_bdt=total_cost,
        peak_grid_kwh=peak_grid,
    )


__all__ = ["ResponseValidationReport", "validate_response"]
