"""Hypothesis-based property tests.

For every randomly generated feasible scenario we assert the canonical
replay invariants hold. These tests catch optimization bugs that
hand-curated unit tests might miss.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from app.config import get_settings
from app.directives.applier import apply_directives
from app.optimization.model import EnergyScenario
from app.optimization.solver import solve
from app.schemas.directives import (
    DirectiveTypeEnum,
    ValidatedDirective,
    ValidatedDirectiveSet,
)
from app.schemas.request import BatteryInput, HourlyInput
from app.services.optimize_service import OptimizeService


def _run_async(coro):
    """Helper to drive async coroutines without pytest-asyncio."""

    return asyncio.run(coro)


# --- Strategies -------------------------------------------------------------

demand_st = st.floats(min_value=20.0, max_value=400.0, allow_nan=False)
solar_st = st.floats(min_value=0.0, max_value=300.0, allow_nan=False)
tariff_st = st.floats(min_value=4.0, max_value=32.0, allow_nan=False)
capacity_st = st.floats(min_value=100.0, max_value=500.0, allow_nan=False)
rate_st = st.floats(min_value=20.0, max_value=100.0, allow_nan=False)
note_st = st.sampled_from(
    [
        "Panel washing from 1 PM to 3 PM will leave 20% of normal solar.",
        "The battery charger will be isolated from 2 AM until 5 AM for electrical maintenance.",
        "The cafeteria menu has changed next week.",
        "",
    ]
)
note_count_st = st.integers(min_value=1, max_value=3)


def _hour_inputs(demand_value=100.0, solar_value=80.0, tariff_value=10.0):
    return [
        HourlyInput(
            hour=h,
            demand_kwh=float(demand_value),
            solar_kwh=float(solar_value if 6 <= h <= 18 else 0.0),
            tariff_bdt_per_kwh=float(tariff_value + (h % 4)),
        )
        for h in range(24)
    ]


def _hour_inputs_kw(demand=100.0, solar=80.0, tariff=10.0):
    return _hour_inputs(demand_value=demand, solar_value=solar, tariff_value=tariff)


def _battery_inputs(
    cap=200.0, init=80.0, min_e=20.0, rate=50.0
):
    return BatteryInput(
        capacity_kwh=float(cap),
        initial_energy_kwh=float(init),
        minimum_energy_kwh=float(min_e),
        max_charge_kwh_per_hour=float(rate),
        max_discharge_kwh_per_hour=float(rate),
    )


# --- Property tests ---------------------------------------------------------


@given(
    demand=demand_st,
    solar=solar_st,
    tariff=tariff_st,
    cap=capacity_st,
    rate=rate_st,
)
@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
)
def test_solver_satisfies_hard_constraints(
    demand: float, solar: float, tariff: float, cap: float, rate: float
) -> None:
    hours = _hour_inputs(demand, solar, tariff)
    # Initial energy is mid-range so we exercise both charge and discharge.
    init = cap * 0.5
    battery = _battery_inputs(cap=cap, init=init, min_e=cap * 0.1, rate=rate)
    eff = apply_directives(hours, battery, ValidatedDirectiveSet())
    scenario = EnergyScenario.build("PROP", hours, battery, eff)
    result = solve(scenario)
    # Energy balance per hour.
    for h in range(24):
        d = hours[h].demand_kwh
        balance = (
            result.grid_kwh[h]
            + result.solar_used_kwh[h]
            + result.discharge_kwh[h]
            - d
            - result.charge_kwh[h]
        )
        assert abs(balance) < 1e-3, (
            f"hour {h}: balance={balance}"
        )
        # Action exclusivity.
        assert not (
            result.charge_kwh[h] > 1e-4 and result.discharge_kwh[h] > 1e-4
        ), f"hour {h}: simultaneous charge/discharge"
    # End-of-day neutrality.
    assert abs(result.energy_after_kwh[-1] - init) < 1e-3


@given(cap=capacity_st, rate=rate_st, demand=demand_st)
@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
)
def test_solver_battery_bounds(cap: float, rate: float, demand: float) -> None:
    hours = _hour_inputs_kw(demand=demand, solar=80.0, tariff=10.0)
    battery = _battery_inputs(cap=cap, init=cap * 0.5, min_e=cap * 0.1, rate=rate)
    eff = apply_directives(hours, battery, ValidatedDirectiveSet())
    scenario = EnergyScenario.build("PROP", hours, battery, eff)
    result = solve(scenario)
    for e in result.energy_after_kwh:
        assert e >= battery.minimum_energy_kwh - 1e-3
        assert e <= battery.capacity_kwh + 1e-3
    for c in result.charge_kwh:
        assert c <= battery.max_charge_kwh_per_hour + 1e-3
    for d in result.discharge_kwh:
        assert d <= battery.max_discharge_kwh_per_hour + 1e-3


def test_property_full_pipeline() -> None:
    """Run the entire pipeline with the mock LLM for random scenarios."""

    settings = get_settings()
    service = OptimizeService.with_mock(settings)

    # Use a fixed set of scenarios for predictability.
    scenarios = [
        "The cafeteria menu has changed next week.",
        "Panel washing from 1 PM to 3 PM will leave 20% of normal solar.",
        "Battery must hold at least 80 kWh from 6 PM to 9 PM.",
    ]
    hours = _hour_inputs_kw(demand=120.0, solar=80.0, tariff=10.0)
    battery = _battery_inputs()
    from app.schemas.request import OptimizeEnergyRequest

    for i, notes in enumerate(scenarios):
        req = OptimizeEnergyRequest(
            scenario_id=f"PROP-{i}",
            operator_notes=[notes],
            hours=hours,
            battery=battery,
        )
        response = _run_async(service.optimize(req))
        assert len(response.hourly_plan) == 24
        # Energy balance
        for item in response.hourly_plan:
            c = item.battery_kwh if item.battery_action.value == "charge" else 0.0
            d = (
                item.battery_kwh
                if item.battery_action.value == "discharge"
                else 0.0
            )
            balance = (
                item.grid_kwh
                + item.solar_used_kwh
                + d
                - hours[item.hour].demand_kwh
                - c
            )
            assert abs(balance) < 1e-2, (
                f"hour {item.hour}: balance={balance}"
            )
        # Final neutrality
        last = response.hourly_plan[-1].battery_energy_after_kwh
        assert abs(last - battery.initial_energy_kwh) < 1e-2


# Required because the optimize() call is async; pytest-asyncio is not a
# dependency so we drive it via asyncio.run inside individual tests.
@pytest.fixture(scope="module", autouse=True)
def _ensure_sync_runtime():
    """Make sure no async fixtures interfere."""

    yield
