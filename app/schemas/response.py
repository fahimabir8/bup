"""Response schema for /optimize-energy."""

from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.directives import (
    BatteryActionEnum,
    DirectiveInterpretationItem,
)


class HourlyPlanItem(BaseModel):
    """One hour of the optimised energy schedule."""

    model_config = ConfigDict(extra="forbid")

    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0)
    solar_used_kwh: float = Field(..., ge=0)
    battery_action: BatteryActionEnum
    battery_kwh: float = Field(..., ge=0)
    battery_energy_after_kwh: float = Field(..., ge=0)


class OptimizeEnergyResponse(BaseModel):
    """Top-level response payload."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    directive_interpretation: List[DirectiveInterpretationItem]
    hourly_plan: List[HourlyPlanItem]
    total_grid_kwh: float = Field(..., ge=0)
    total_cost_bdt: float = Field(..., ge=0)
    peak_grid_kwh: float = Field(..., ge=0)
    plan_summary: str


__all__ = ["HourlyPlanItem", "OptimizeEnergyResponse"]


# Re-export enum for backwards compatibility
__all__ += ["BatteryActionEnum"]
