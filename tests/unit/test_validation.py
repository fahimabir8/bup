"""Unit tests for the canonical replay validator."""

from __future__ import annotations

from app.config import NumericalConfig
from app.schemas.directives import (
    BatteryActionEnum,
    DirectiveInterpretationItem,
    DirectiveTypeEnum,
)
from app.schemas.request import BatteryInput, HourlyInput
from app.schemas.response import HourlyPlanItem
from app.validation.replay import (
    recalculate_totals,
    replay_plan,
)


def _hours() -> list[HourlyInput]:
    return [
        HourlyInput(
            hour=h,
            demand_kwh=100.0,
            solar_kwh=80.0 if 6 <= h <= 18 else 0.0,
            tariff_bdt_per_kwh=10.0,
        )
        for h in range(24)
    ]


def _battery() -> BatteryInput:
    return BatteryInput(
        capacity_kwh=200.0,
        initial_energy_kwh=80.0,
        minimum_energy_kwh=20.0,
        max_charge_kwh_per_hour=50.0,
        max_discharge_kwh_per_hour=50.0,
    )


def _plan_idle() -> list[HourlyPlanItem]:
    return [
        HourlyPlanItem(
            hour=h,
            grid_kwh=100.0,
            solar_used_kwh=0.0,
            battery_action=BatteryActionEnum.IDLE,
            battery_kwh=0.0,
            battery_energy_after_kwh=80.0,
        )
        for h in range(24)
    ]


def test_replay_passes_idle_schedule() -> None:
    res = replay_plan(
        _plan_idle(), _hours(), _battery(), [], NumericalConfig()
    )
    assert res.valid, res.errors


def test_replay_detects_simultaneous_charge_discharge() -> None:
    """A truly invalid plan (imbalanced energy) must fail replay.

    Note: the postprocess layer selects a single dominant action so a
    plan with conflicting (charge_kwh, discharge_kwh) cannot reach the
    replay validator unchanged. We instead test that an inconsistent
    energy balance is correctly detected.
    """
    plan = _plan_idle()
    bad = HourlyPlanItem(
        hour=0,
        grid_kwh=40.0,  # too low to balance demand=100 with no solar/discharge
        solar_used_kwh=0.0,
        battery_action=BatteryActionEnum.CHARGE,
        battery_kwh=10.0,
        battery_energy_after_kwh=90.0,
    )
    plan[0] = bad
    res = replay_plan(plan, _hours(), _battery(), [], NumericalConfig())
    assert not res.valid
    assert any("balance" in e for e in res.errors)


def test_replay_detects_final_neutrality_violation() -> None:
    plan = _plan_idle()
    # Replace last hour so final energy mismatches.
    last = HourlyPlanItem(
        hour=23,
        grid_kwh=100.0,
        solar_used_kwh=0.0,
        battery_action=BatteryActionEnum.IDLE,
        battery_kwh=0.0,
        battery_energy_after_kwh=50.0,  # initial is 80
    )
    plan[-1] = last
    res = replay_plan(plan, _hours(), _battery(), [], NumericalConfig())
    assert not res.valid
    assert any("end-of-day" in e for e in res.errors)


def test_replay_detects_energy_balance_violation() -> None:
    plan = _plan_idle()
    plan[5] = HourlyPlanItem(
        hour=5,
        grid_kwh=200.0,  # too high
        solar_used_kwh=0.0,
        battery_action=BatteryActionEnum.IDLE,
        battery_kwh=0.0,
        battery_energy_after_kwh=80.0,
    )
    res = replay_plan(plan, _hours(), _battery(), [], NumericalConfig())
    assert not res.valid


def test_replay_detects_solar_exceeds_effective_solar() -> None:
    plan = _plan_idle()
    plan[12] = HourlyPlanItem(
        hour=12,
        grid_kwh=0.0,
        solar_used_kwh=200.0,  # exceeds effective 80
        battery_action=BatteryActionEnum.IDLE,
        battery_kwh=0.0,
        battery_energy_after_kwh=80.0,
    )
    res = replay_plan(plan, _hours(), _battery(), [], NumericalConfig())
    assert not res.valid


def test_replay_detects_directive_violations() -> None:
    plan = _plan_idle()
    plan[5] = HourlyPlanItem(
        hour=5,
        grid_kwh=100.0,
        solar_used_kwh=0.0,
        battery_action=BatteryActionEnum.CHARGE,
        battery_kwh=10.0,
        battery_energy_after_kwh=90.0,
    )
    interpretations = [
        DirectiveInterpretationItem(
            note_index=0,
            applies=True,
            directive_type=DirectiveTypeEnum.NO_CHARGE_WINDOW,
            structured_adjustment={"hours": [5, 6]},
            explanation="x",
        )
    ]
    res = replay_plan(
        plan, _hours(), _battery(), interpretations, NumericalConfig()
    )
    assert not res.valid
    assert any("no_charge_window" in e for e in res.errors)


def test_replay_detects_grid_cap_violation() -> None:
    plan = _plan_idle()
    interpretations = [
        DirectiveInterpretationItem(
            note_index=0,
            applies=True,
            directive_type=DirectiveTypeEnum.MAX_GRID_WINDOW,
            structured_adjustment={"hours": [5, 6], "max_grid_kwh": 50.0},
            explanation="x",
        )
    ]
    res = replay_plan(
        plan, _hours(), _battery(), interpretations, NumericalConfig()
    )
    assert not res.valid
    assert any("cap" in e for e in res.errors)


def test_recalculate_totals() -> None:
    plan = _plan_idle()
    plan[0] = HourlyPlanItem(
        hour=0,
        grid_kwh=80.0,
        solar_used_kwh=20.0,
        battery_action=BatteryActionEnum.IDLE,
        battery_kwh=0.0,
        battery_energy_after_kwh=80.0,
    )
    total_grid, total_cost, peak_grid = recalculate_totals(plan, _hours())
    assert total_grid == 23 * 100.0 + 80.0  # 23 idle (100) + first hour 80
    assert total_cost == total_grid * 10.0
    assert peak_grid == 100.0