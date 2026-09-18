from pydantic import BaseModel, Field
from typing import Literal
from typing_extensions import Annotated
from .directives import (
    DirectiveType,
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    MaxGridWindowAdjustment,
)


class HourlyPlanEntry(BaseModel):
    hour: Annotated[int, Field(ge=0, le=23)]
    grid_kwh: Annotated[float, Field(ge=0)]
    solar_used_kwh: Annotated[float, Field(ge=0)]
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: Annotated[float, Field(ge=0)]
    battery_energy_after_kwh: Annotated[float, Field(ge=0)]


class DirectiveInterpretationResponse(BaseModel):
    note_index: int
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: (
        SolarReductionAdjustment
        | MinimumBatteryReserveAdjustment
        | NoChargeWindowAdjustment
        | NoDischargeWindowAdjustment
        | MaxGridWindowAdjustment
        | None
    ) = None
    explanation: str


class OptimizeEnergyResponse(BaseModel):
    scenario_id: str
    directive_interpretation: list[DirectiveInterpretationResponse]
    hourly_plan: Annotated[list[HourlyPlanEntry], Field(min_length=24, max_length=24)]
    total_grid_kwh: Annotated[float, Field(ge=0)]
    total_cost_bdt: Annotated[float, Field(ge=0)]
    peak_grid_kwh: Annotated[float, Field(ge=0)]
    plan_summary: str
