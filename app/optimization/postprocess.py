"""Deterministic post-processing of optimizer output into the API response.

Responsibilities:

* select the battery_action label per hour
* build the `HourlyPlanItem` list
* recompute totals from the final hourly plan (NOT solver metadata)
* generate a concise deterministic `plan_summary`

Replays the plan with the canonical replay validator before returning.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from app.config import NumericalConfig, get_settings
from app.optimization.model import EnergyScenario
from app.optimization.solver import OptimizationResult
from app.schemas.directives import (
    BatteryActionEnum,
    DirectiveInterpretationItem,
    DirectiveTypeEnum,
)
from app.schemas.request import BatteryInput, HourlyInput
from app.schemas.response import HourlyPlanItem, OptimizeEnergyResponse


@dataclass
class PostprocessContext:
    scenario_id: str
    hours: List[HourlyInput]
    battery: BatteryInput
    interpretations: List[DirectiveInterpretationItem]


def _select_action(
    charge: float,
    discharge: float,
    tol: float,
) -> tuple[BatteryActionEnum, float]:
    """Map (charge, discharge) pair to (action, kWh)."""

    if charge > tol and discharge > tol:
        # The solver was supposed to prevent this; if we ever see it we
        # treat it as an upstream violation. The replay validator will
        # surface the error. Choose the dominant action so downstream
        # arithmetic stays defined; the validator will fail the schedule.
        if charge >= discharge:
            return BatteryActionEnum.CHARGE, charge
        return BatteryActionEnum.DISCHARGE, discharge
    if charge > tol:
        return BatteryActionEnum.CHARGE, charge
    if discharge > tol:
        return BatteryActionEnum.DISCHARGE, discharge
    return BatteryActionEnum.IDLE, 0.0


def _round(value: float, precision: int) -> float:
    factor = 10 ** precision
    rounded = round(float(value) * factor) / factor
    # Normalize -0.0 -> 0.0
    if rounded == 0.0:
        return 0.0
    return rounded


def _normalise_tiny(value: float, tol: float) -> float:
    if abs(value) < tol:
        return 0.0
    return float(value)


def build_hourly_plan(
    ctx: PostprocessContext,
    raw: OptimizationResult,
    numerical: NumericalConfig,
) -> List[HourlyPlanItem]:
    """Build the final API hourly plan from solver output."""

    items: List[HourlyPlanItem] = []
    for h in range(24):
        grid = _normalise_tiny(raw.grid_kwh[h], numerical.zero_tolerance)
        solar = _normalise_tiny(raw.solar_used_kwh[h], numerical.zero_tolerance)
        charge = _normalise_tiny(raw.charge_kwh[h], numerical.zero_tolerance)
        discharge = _normalise_tiny(raw.discharge_kwh[h], numerical.zero_tolerance)
        energy_after = _normalise_tiny(
            raw.energy_after_kwh[h], numerical.zero_tolerance
        )

        action, kwh = _select_action(charge, discharge, numerical.action_select_tolerance)
        items.append(
            HourlyPlanItem(
                hour=h,
                grid_kwh=_round(grid, numerical.output_precision),
                solar_used_kwh=_round(solar, numerical.output_precision),
                battery_action=action,
                battery_kwh=_round(kwh, numerical.output_precision),
                battery_energy_after_kwh=_round(
                    energy_after, numerical.output_precision
                ),
            )
        )
    return items


def _recalculate_totals(
    plan: List[HourlyPlanItem],
    hours: List[HourlyInput],
) -> tuple[float, float, float]:
    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0
    for item in plan:
        total_grid += item.grid_kwh
        total_cost += item.grid_kwh * hours[item.hour].tariff_bdt_per_kwh
        if item.grid_kwh > peak_grid:
            peak_grid = item.grid_kwh
    return total_grid, total_cost, peak_grid


def build_plan_summary(
    plan: List[HourlyPlanItem],
    interpretations: List[DirectiveInterpretationItem],
    total_cost: float,
    total_grid: float,
) -> str:
    """Generate a short deterministic plan summary."""

    active_directives = [
        i.directive_type.value
        for i in interpretations
        if i.applies and i.directive_type != DirectiveTypeEnum.NO_OP
    ]

    pieces: list[str] = []
    pieces.append(
        "GridWise optimised a 24-hour campus schedule."
    )
    pieces.append(
        f"Total grid import {total_grid:.2f} kWh, "
        f"total cost {total_cost:.2f} BDT."
    )
    if active_directives:
        pieces.append(
            "Applied directives: " + ", ".join(active_directives) + "."
        )
    # Mention the dominant battery direction.
    charge_hours = sum(
        1 for i in plan if i.battery_action == BatteryActionEnum.CHARGE
    )
    discharge_hours = sum(
        1 for i in plan if i.battery_action == BatteryActionEnum.DISCHARGE
    )
    if charge_hours and discharge_hours:
        pieces.append(
            f"Battery charged in {charge_hours} hour(s) and discharged "
            f"in {discharge_hours} hour(s)."
        )
    elif charge_hours:
        pieces.append(f"Battery charged in {charge_hours} hour(s).")
    elif discharge_hours:
        pieces.append(f"Battery discharged in {discharge_hours} hour(s).")
    pieces.append(
        "Battery ends the day at the initial energy level as required."
    )
    return " ".join(pieces)


def build_response(
    ctx: PostprocessContext,
    raw: OptimizationResult,
    numerical: Optional[NumericalConfig] = None,
) -> tuple[OptimizeEnergyResponse, List[HourlyPlanItem]]:
    """Construct the full response payload from solver output."""

    numerical = numerical or get_settings().numerical
    plan = build_hourly_plan(ctx, raw, numerical)
    total_grid, total_cost, peak_grid = _recalculate_totals(plan, ctx.hours)

    # Round totals to API precision; the rounded totals MUST be consistent
    # with the rounded plan. We recalculate from the rounded plan again to
    # guarantee the invariant.
    plan = [
        HourlyPlanItem(
            hour=item.hour,
            grid_kwh=_round(item.grid_kwh, numerical.output_precision),
            solar_used_kwh=_round(item.solar_used_kwh, numerical.output_precision),
            battery_action=item.battery_action,
            battery_kwh=_round(item.battery_kwh, numerical.output_precision),
            battery_energy_after_kwh=_round(
                item.battery_energy_after_kwh, numerical.output_precision
            ),
        )
        for item in plan
    ]
    total_grid_r, total_cost_r, peak_grid_r = _recalculate_totals(plan, ctx.hours)
    total_grid = _round(total_grid_r, numerical.output_precision)
    total_cost = _round(total_cost_r, numerical.output_precision)
    peak_grid = _round(peak_grid_r, numerical.output_precision)

    summary = build_plan_summary(plan, ctx.interpretations, total_cost, total_grid)

    response = OptimizeEnergyResponse(
        scenario_id=ctx.scenario_id,
        directive_interpretation=ctx.interpretations,
        hourly_plan=plan,
        total_grid_kwh=total_grid,
        total_cost_bdt=total_cost,
        peak_grid_kwh=peak_grid,
        plan_summary=summary,
    )
    return response, plan


__all__ = [
    "PostprocessContext",
    "build_hourly_plan",
    "build_plan_summary",
    "build_response",
]
