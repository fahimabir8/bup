"""Canonical replay validator.

The replay validator independently reconstructs the validity of a
returned 24-hour schedule. It is the *single* source of truth for
schedule validity and is used by:

* the API service before returning the response
* the public sample validator
* the property-based test suite
* the benchmark script

Anything that needs to verify a schedule should call `replay_plan`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.config import NumericalConfig, get_settings
from app.schemas.directives import (
    BatteryActionEnum,
    DirectiveInterpretationItem,
    DirectiveTypeEnum,
)
from app.schemas.request import BatteryInput, HourlyInput
from app.schemas.response import HourlyPlanItem


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def _build_hour_index(
    hours: List[HourlyInput],
) -> dict[int, HourlyInput]:
    return {h.hour: h for h in hours}


def _validate_structure(
    plan: List[HourlyPlanItem],
    hours: List[HourlyInput],
    result: ValidationResult,
) -> None:
    if len(plan) != 24:
        result.add_error(
            f"hourly_plan must contain exactly 24 entries; got {len(plan)}"
        )
        return
    if len(hours) != 24:
        result.add_error(
            "scenario hours must contain exactly 24 entries"
        )
        return

    seen = set()
    for item in plan:
        if item.hour in seen:
            result.add_error(f"duplicate hour in plan: {item.hour}")
        seen.add(item.hour)
    if seen != set(range(24)):
        result.add_error(
            "hourly_plan must cover hours 0..23 exactly once"
        )


def _validate_nonnegativity(
    plan: List[HourlyPlanItem],
    result: ValidationResult,
) -> None:
    for item in plan:
        if item.grid_kwh < -1e-6:
            result.add_error(
                f"hour {item.hour}: grid_kwh must be non-negative "
                f"(got {item.grid_kwh})"
            )
        if item.solar_used_kwh < -1e-6:
            result.add_error(
                f"hour {item.hour}: solar_used_kwh must be non-negative "
                f"(got {item.solar_used_kwh})"
            )
        if item.battery_kwh < -1e-6:
            result.add_error(
                f"hour {item.hour}: battery_kwh must be non-negative "
                f"(got {item.battery_kwh})"
            )


def _validate_action(
    item: HourlyPlanItem,
    result: ValidationResult,
    tol: float,
) -> None:
    if item.battery_action not in (
        BatteryActionEnum.CHARGE,
        BatteryActionEnum.DISCHARGE,
        BatteryActionEnum.IDLE,
    ):
        result.add_error(
            f"hour {item.hour}: invalid battery_action {item.battery_action}"
        )
        return
    if item.battery_action == BatteryActionEnum.IDLE:
        if item.battery_kwh > tol:
            result.add_error(
                f"hour {item.hour}: idle hour must have battery_kwh == 0"
            )
    elif item.battery_action == BatteryActionEnum.CHARGE:
        if item.battery_kwh <= tol:
            result.add_error(
                f"hour {item.hour}: charge hour must have positive "
                "battery_kwh"
            )
    elif item.battery_action == BatteryActionEnum.DISCHARGE:
        if item.battery_kwh <= tol:
            result.add_error(
                f"hour {item.hour}: discharge hour must have positive "
                "battery_kwh"
            )


def replay_plan(
    plan: List[HourlyPlanItem],
    hours: List[HourlyInput],
    battery: BatteryInput,
    interpretations: List[DirectiveInterpretationItem],
    numerical: Optional[NumericalConfig] = None,
) -> ValidationResult:
    """Validate a returned 24-hour schedule against all hard constraints.

    Returns a `ValidationResult` with a `valid` flag plus lists of
    human-readable errors/warnings. The validator is independent of the
    LLM, the optimization engine, and the post-processing layer: it
    re-derives every constraint from the plan and the original inputs.
    """

    numerical = numerical or get_settings().numerical
    tol = numerical.abs_tolerance
    tiny = numerical.zero_tolerance
    result = ValidationResult(valid=True)
    _validate_structure(plan, hours, result)
    if not result.valid:
        return result
    hour_index = _build_hour_index(hours)

    # Pre-compute active directive adjustments for replay checks.
    solar_factors: dict[int, float] = {}
    min_reserves: dict[int, float] = {}
    no_charge: set[int] = set()
    no_discharge: set[int] = set()
    grid_caps: dict[int, float] = {}

    for interp in interpretations:
        if not interp.applies or interp.structured_adjustment is None:
            continue
        adj = interp.structured_adjustment
        hours_list = adj.get("hours", []) or []
        if interp.directive_type == DirectiveTypeEnum.SOLAR_REDUCTION:
            factor = float(adj.get("factor", 1.0))
            for h in hours_list:
                solar_factors[int(h)] = factor
        elif interp.directive_type == DirectiveTypeEnum.MINIMUM_BATTERY_RESERVE:
            min_reserve = float(adj.get("minimum_energy_kwh", battery.minimum_energy_kwh))
            for h in hours_list:
                min_reserves[int(h)] = max(
                    min_reserves.get(int(h), battery.minimum_energy_kwh),
                    min_reserve,
                )
        elif interp.directive_type == DirectiveTypeEnum.NO_CHARGE_WINDOW:
            for h in hours_list:
                no_charge.add(int(h))
        elif interp.directive_type == DirectiveTypeEnum.NO_DISCHARGE_WINDOW:
            for h in hours_list:
                no_discharge.add(int(h))
        elif interp.directive_type == DirectiveTypeEnum.MAX_GRID_WINDOW:
            cap = float(adj.get("max_grid_kwh", 0.0))
            for h in hours_list:
                grid_caps[int(h)] = min(
                    grid_caps.get(int(h), float("inf")),
                    cap,
                )

    # Walk hour-by-hour and check energy balance + battery transition +
    # directive-specific constraints.
    prev_energy = None
    for item in plan:
        h = item.hour
        h_in = hour_index[h]
        effective_solar = max(
            0.0, h_in.solar_kwh * solar_factors.get(h, 1.0)
        )
        demand = h_in.demand_kwh

        charge = (
            item.battery_kwh
            if item.battery_action == BatteryActionEnum.CHARGE
            else 0.0
        )
        discharge = (
            item.battery_kwh
            if item.battery_action == BatteryActionEnum.DISCHARGE
            else 0.0
        )

        # Energy balance
        balance = (
            item.grid_kwh
            + item.solar_used_kwh
            + discharge
            - demand
            - charge
        )
        if abs(balance) > tol:
            result.add_error(
                f"hour {h}: energy balance violated "
                f"(grid+sol+dch - demand - chg = {balance:.4f})"
            )

        # Solar usage bound
        if item.solar_used_kwh > effective_solar + tol:
            result.add_error(
                f"hour {h}: solar_used_kwh {item.solar_used_kwh:.4f} exceeds "
                f"effective_solar {effective_solar:.4f}"
            )

        # Action exclusivity: there should never be both charge and discharge.
        if charge > tol and discharge > tol:
            result.add_error(
                f"hour {h}: simultaneous charge ({charge:.4f}) and "
                f"discharge ({discharge:.4f})"
            )

        # Charge / discharge rate limits
        if charge > battery.max_charge_kwh_per_hour + tol:
            result.add_error(
                f"hour {h}: charge {charge:.4f} exceeds max "
                f"{battery.max_charge_kwh_per_hour:.4f}"
            )
        if discharge > battery.max_discharge_kwh_per_hour + tol:
            result.add_error(
                f"hour {h}: discharge {discharge:.4f} exceeds max "
                f"{battery.max_discharge_kwh_per_hour:.4f}"
            )

        # No-charge / no-discharge windows
        if h in no_charge and charge > tol:
            result.add_error(
                f"hour {h}: charging not allowed in no_charge_window "
                f"(observed {charge:.4f})"
            )
        if h in no_discharge and discharge > tol:
            result.add_error(
                f"hour {h}: discharging not allowed in no_discharge_window "
                f"(observed {discharge:.4f})"
            )

        # Grid cap
        cap = grid_caps.get(h)
        if cap is not None and item.grid_kwh > cap + tol:
            result.add_error(
                f"hour {h}: grid_kwh {item.grid_kwh:.4f} exceeds cap "
                f"{cap:.4f}"
            )

        # Battery bounds
        if item.battery_energy_after_kwh < battery.minimum_energy_kwh - tol:
            result.add_error(
                f"hour {h}: battery_energy_after_kwh "
                f"{item.battery_energy_after_kwh:.4f} below base minimum "
                f"{battery.minimum_energy_kwh:.4f}"
            )
        if item.battery_energy_after_kwh > battery.capacity_kwh + tol:
            result.add_error(
                f"hour {h}: battery_energy_after_kwh "
                f"{item.battery_energy_after_kwh:.4f} above capacity "
                f"{battery.capacity_kwh:.4f}"
            )
        directive_min = min_reserves.get(h)
        if (
            directive_min is not None
            and item.battery_energy_after_kwh < directive_min - tol
        ):
            result.add_error(
                f"hour {h}: battery_energy_after_kwh "
                f"{item.battery_energy_after_kwh:.4f} below directive "
                f"minimum {directive_min:.4f}"
            )

        # Battery transition
        if prev_energy is None:
            expected_prev = battery.initial_energy_kwh
        else:
            expected_prev = prev_energy
        expected_after = expected_prev + charge - discharge
        if abs(item.battery_energy_after_kwh - expected_after) > tol:
            result.add_error(
                f"hour {h}: battery transition mismatch "
                f"(expected {expected_after:.4f}, got "
                f"{item.battery_energy_after_kwh:.4f}; prev "
                f"{expected_prev:.4f}, chg {charge:.4f}, "
                f"dch {discharge:.4f})"
            )
        prev_energy = item.battery_energy_after_kwh

        # Battery action-specific non-negativity
        _validate_action(item, result, tol)

    # Final battery neutrality check
    final_energy = plan[-1].battery_energy_after_kwh
    if abs(final_energy - battery.initial_energy_kwh) > tol:
        result.add_error(
            f"end-of-day battery energy {final_energy:.4f} does not "
            f"equal initial {battery.initial_energy_kwh:.4f}"
        )

    # Non-negativity sweep (final pass)
    _validate_nonnegativity(plan, result)

    return result


def recalculate_totals(
    plan: List[HourlyPlanItem],
    hours: List[HourlyInput],
) -> tuple[float, float, float]:
    """Recompute (total_grid, total_cost, peak_grid) from the final plan."""

    hour_index = _build_hour_index(hours)
    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0
    for item in plan:
        total_grid += item.grid_kwh
        total_cost += item.grid_kwh * hour_index[item.hour].tariff_bdt_per_kwh
        if item.grid_kwh > peak_grid:
            peak_grid = item.grid_kwh
    return total_grid, total_cost, peak_grid


__all__ = [
    "ValidationResult",
    "replay_plan",
    "recalculate_totals",
]
