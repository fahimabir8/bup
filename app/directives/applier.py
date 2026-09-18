"""Deterministic application of validated directives.

Given a `ValidatedDirectiveSet` and the original scenario inputs, build
the `EffectiveScenario` that the optimizer will consume. This layer
has zero dependency on the LLM or on text.
"""

from __future__ import annotations

import math
from typing import List

from app.schemas.directives import (
    DirectiveTypeEnum,
    EffectiveScenario,
    ValidatedDirectiveSet,
)
from app.schemas.request import BatteryInput, HourlyInput


def apply_directives(
    request_hours: List[HourlyInput],
    battery: BatteryInput,
    validated: ValidatedDirectiveSet,
    capacity_kwh: float | None = None,
) -> EffectiveScenario:
    """Convert a validated set of directives into an EffectiveScenario.

    Parameters
    ----------
    request_hours:
        24-hour input horizon, ascending by `hour`.
    battery:
        Battery configuration from the request.
    validated:
        Output of `validate_directive_interpretation`.
    capacity_kwh:
        Optional override for battery capacity (defaults to the request).
        Useful for tests that feed a deliberately tight directive.
    """

    if len(request_hours) != 24:
        raise ValueError("request_hours must contain 24 entries")

    capacity = capacity_kwh if capacity_kwh is not None else battery.capacity_kwh
    base_minimum = battery.minimum_energy_kwh

    # Defaults
    effective_solar = [float(h.solar_kwh) for h in request_hours]
    active_minimum = [float(base_minimum) for _ in range(24)]
    max_charge = [float(battery.max_charge_kwh_per_hour) for _ in range(24)]
    max_discharge = [
        float(battery.max_discharge_kwh_per_hour) for _ in range(24)
    ]
    no_charge: set[int] = set()
    no_discharge: set[int] = set()
    grid_caps = [math.inf for _ in range(24)]
    solar_reduction_hours: list[int] = []

    for d in validated.directives:
        if not d.applies or d.directive_type == DirectiveTypeEnum.NO_OP:
            continue

        adj = d.adjustment
        hours = adj.get("hours", [])
        dtype = d.directive_type

        if dtype == DirectiveTypeEnum.SOLAR_REDUCTION:
            factor = float(adj["factor"])
            for h in hours:
                effective_solar[h] = float(request_hours[h].solar_kwh) * factor
                solar_reduction_hours.append(h)
        elif dtype == DirectiveTypeEnum.MINIMUM_BATTERY_RESERVE:
            min_kwh = float(adj["minimum_energy_kwh"])
            for h in hours:
                active_minimum[h] = max(active_minimum[h], min_kwh)
        elif dtype == DirectiveTypeEnum.NO_CHARGE_WINDOW:
            for h in hours:
                no_charge.add(int(h))
        elif dtype == DirectiveTypeEnum.NO_DISCHARGE_WINDOW:
            for h in hours:
                no_discharge.add(int(h))
        elif dtype == DirectiveTypeEnum.MAX_GRID_WINDOW:
            cap = float(adj["max_grid_kwh"])
            for h in hours:
                grid_caps[h] = min(grid_caps[h], cap)

    # Apply no-charge / no-discharge rate limits and resolve inf grid caps.
    for h in range(24):
        if h in no_charge:
            max_charge[h] = 0.0
        if h in no_discharge:
            max_discharge[h] = 0.0

        # If cap is +inf, use a very large finite sentinel so the optimizer
        # stays within solver tolerances.
        if math.isinf(grid_caps[h]):
            grid_caps[h] = 1e6

        # Round tiny values to zero to avoid solver noise.
        if grid_caps[h] < 1e-9:
            grid_caps[h] = 0.0
        if effective_solar[h] < 1e-9:
            effective_solar[h] = 0.0

    scenario = EffectiveScenario(
        base_minimum_reserve=base_minimum,
        effective_solar_kwh=effective_solar,
        active_minimum_reserve_kwh=active_minimum,
        max_charge_kwh_per_hour=max_charge,
        max_discharge_kwh_per_hour=max_discharge,
        no_charge_hours=sorted(no_charge),
        no_discharge_hours=sorted(no_discharge),
        grid_caps_kwh=grid_caps,
        solar_reduction_hours=sorted(set(solar_reduction_hours)),
    )

    # Sanity check: reserves never exceed capacity.
    for h, r in enumerate(scenario.active_minimum_reserve_kwh):
        if r > capacity + 1e-6:
            raise ValueError(
                f"minimum_battery_reserve for hour {h} ({r}) "
                f"exceeds battery capacity ({capacity})"
            )

    return scenario


def detect_infeasible_preconditions(
    request_hours: List[HourlyInput],
    battery: BatteryInput,
    effective: EffectiveScenario,
) -> list[str]:
    """Best-effort deterministic conflict detection.

    Returns a list of safe human-readable error messages. The optimizer
    is the final source of truth for infeasibility. We deliberately do
    NOT reject scenarios where the grid cap is below demand, because
    solar and battery discharge can cover the difference.
    """

    errors: list[str] = []

    # Reserves above capacity are a hard constraint and we can detect them
    # without invoking the solver.
    for h, r in enumerate(effective.active_minimum_reserve_kwh):
        if r > battery.capacity_kwh + 1e-6:
            errors.append(
                f"hour {h}: minimum reserve {r:.2f} kWh exceeds "
                f"battery capacity {battery.capacity_kwh:.2f} kWh"
            )

    # Initial battery below base reserve.
    if battery.initial_energy_kwh < battery.minimum_energy_kwh - 1e-6:
        errors.append(
            "initial battery energy is below the configured minimum reserve"
        )

    # Directives that forbid both charge and discharge for the same hour
    # when the battery cannot stay exactly at its previous state across the
    # whole window. The optimizer can usually satisfy this by idling, but
    # if the battery starts below minimum we surface a clear error.
    overlaps = set(effective.no_charge_hours) & set(effective.no_discharge_hours)
    if overlaps and battery.initial_energy_kwh < battery.minimum_energy_kwh - 1e-6:
        errors.append(
            "both no_charge_window and no_discharge_window intersect while "
            "initial battery is below minimum reserve"
        )

    return errors


__all__ = [
    "apply_directives",
    "detect_infeasible_preconditions",
]
