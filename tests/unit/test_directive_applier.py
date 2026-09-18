"""Unit tests for the directive applier (effective scenario builder)."""

from __future__ import annotations

import pytest

from app.directives.applier import (
    apply_directives,
    detect_infeasible_preconditions,
)
from app.schemas.directives import (
    DirectiveTypeEnum,
    ValidatedDirective,
    ValidatedDirectiveSet,
)
from app.schemas.request import BatteryInput, HourlyInput


def _hours() -> list[HourlyInput]:
    return [
        HourlyInput(
            hour=h,
            demand_kwh=100.0,
            solar_kwh=80.0 if 6 <= h <= 18 else 0.0,
            tariff_bdt_per_kwh=10.0 + (h % 4),
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


def test_apply_solar_reduction() -> None:
    battery = _battery()
    eff = apply_directives(
        _hours(),
        battery,
        ValidatedDirectiveSet(
            directives=[
                ValidatedDirective(
                    note_index=0,
                    directive_type=DirectiveTypeEnum.SOLAR_REDUCTION,
                    applies=True,
                    adjustment={"hours": [12, 13], "factor": 0.5},
                )
            ]
        ),
    )
    assert eff.effective_solar_kwh[12] == 80.0 * 0.5
    assert eff.effective_solar_kwh[13] == 80.0 * 0.5
    assert eff.effective_solar_kwh[11] == 80.0  # unchanged


def test_apply_minimum_battery_reserve_takes_max() -> None:
    battery = _battery()
    eff = apply_directives(
        _hours(),
        battery,
        ValidatedDirectiveSet(
            directives=[
                ValidatedDirective(
                    note_index=0,
                    directive_type=DirectiveTypeEnum.MINIMUM_BATTERY_RESERVE,
                    applies=True,
                    adjustment={"hours": [18, 19], "minimum_energy_kwh": 120.0},
                )
            ]
        ),
    )
    assert eff.active_minimum_reserve_kwh[18] == 120.0
    assert eff.active_minimum_reserve_kwh[19] == 120.0
    assert eff.active_minimum_reserve_kwh[17] == 20.0  # base minimum


def test_apply_no_charge_window_zeroes_charge() -> None:
    battery = _battery()
    eff = apply_directives(
        _hours(),
        battery,
        ValidatedDirectiveSet(
            directives=[
                ValidatedDirective(
                    note_index=0,
                    directive_type=DirectiveTypeEnum.NO_CHARGE_WINDOW,
                    applies=True,
                    adjustment={"hours": [2, 3]},
                )
            ]
        ),
    )
    assert eff.max_charge_kwh_per_hour[2] == 0.0
    assert eff.max_charge_kwh_per_hour[3] == 0.0
    assert eff.max_discharge_kwh_per_hour[2] == 50.0


def test_apply_no_discharge_window_zeroes_discharge() -> None:
    battery = _battery()
    eff = apply_directives(
        _hours(),
        battery,
        ValidatedDirectiveSet(
            directives=[
                ValidatedDirective(
                    note_index=0,
                    directive_type=DirectiveTypeEnum.NO_DISCHARGE_WINDOW,
                    applies=True,
                    adjustment={"hours": [18, 19]},
                )
            ]
        ),
    )
    assert eff.max_discharge_kwh_per_hour[18] == 0.0
    assert eff.max_discharge_kwh_per_hour[19] == 0.0
    assert eff.max_charge_kwh_per_hour[18] == 50.0


def test_apply_grid_cap_takes_min() -> None:
    battery = _battery()
    eff = apply_directives(
        _hours(),
        battery,
        ValidatedDirectiveSet(
            directives=[
                ValidatedDirective(
                    note_index=0,
                    directive_type=DirectiveTypeEnum.MAX_GRID_WINDOW,
                    applies=True,
                    adjustment={"hours": [17, 18], "max_grid_kwh": 90.0},
                )
            ]
        ),
    )
    assert eff.grid_caps_kwh[17] == 90.0
    assert eff.grid_caps_kwh[18] == 90.0


def test_apply_reserve_above_capacity_raises() -> None:
    battery = _battery()
    with pytest.raises(ValueError):
        apply_directives(
            _hours(),
            battery,
            ValidatedDirectiveSet(
                directives=[
                    ValidatedDirective(
                        note_index=0,
                        directive_type=DirectiveTypeEnum.MINIMUM_BATTERY_RESERVE,
                        applies=True,
                        adjustment={
                            "hours": [18],
                            "minimum_energy_kwh": 999.0,
                        },
                    )
                ]
            ),
        )


def test_apply_no_op_ignored() -> None:
    battery = _battery()
    eff = apply_directives(
        _hours(),
        battery,
        ValidatedDirectiveSet(
            directives=[
                ValidatedDirective(
                    note_index=0,
                    directive_type=DirectiveTypeEnum.NO_OP,
                    applies=False,
                    adjustment={},
                )
            ]
        ),
    )
    # No change to effective solar or other fields.
    for h in range(24):
        expected = 80.0 if 6 <= h <= 18 else 0.0
        assert eff.effective_solar_kwh[h] == expected
        assert eff.active_minimum_reserve_kwh[h] == 20.0


def test_detect_infeasible_preconditions_init_below_minimum() -> None:
    battery = BatteryInput(
        capacity_kwh=200.0,
        initial_energy_kwh=10.0,  # below minimum
        minimum_energy_kwh=50.0,
        max_charge_kwh_per_hour=50.0,
        max_discharge_kwh_per_hour=50.0,
    )
    eff = apply_directives(_hours(), battery, ValidatedDirectiveSet())
    errors = detect_infeasible_preconditions(_hours(), battery, eff)
    assert any("initial battery" in e for e in errors)