"""Unit tests for the MILP solver."""

from __future__ import annotations

import math

import pytest

from app.directives.applier import apply_directives
from app.optimization.model import EnergyScenario
from app.optimization.solver import (
    InfeasibleScenarioError,
    solve,
)
from app.schemas.directives import (
    DirectiveTypeEnum,
    ValidatedDirectiveSet,
)
from app.schemas.request import BatteryInput, HourlyInput


def _hours(demand=100.0, solar_pattern=None):
    out = []
    for h in range(24):
        s = solar_pattern(h) if solar_pattern else (
            100.0 if 6 <= h <= 18 else 0.0
        )
        out.append(
            HourlyInput(
                hour=h,
                demand_kwh=float(demand),
                solar_kwh=float(s),
                tariff_bdt_per_kwh=10.0 + (h % 4),
            )
        )
    return out


def _battery(cap=200.0, init=80.0, rate=50.0, min_e=20.0):
    return BatteryInput(
        capacity_kwh=cap,
        initial_energy_kwh=init,
        minimum_energy_kwh=min_e,
        max_charge_kwh_per_hour=rate,
        max_discharge_kwh_per_hour=rate,
    )


def _scenario(battery=None, hours=None, validated=None):
    battery = battery or _battery()
    hours = hours or _hours()
    validated = validated or ValidatedDirectiveSet()
    eff = apply_directives(hours, battery, validated)
    return EnergyScenario.build("TEST", hours, battery, eff)


def test_solver_returns_24_hours() -> None:
    res = solve(_scenario())
    assert len(res.grid_kwh) == 24
    assert len(res.solar_used_kwh) == 24
    assert len(res.charge_kwh) == 24
    assert len(res.discharge_kwh) == 24
    assert len(res.energy_after_kwh) == 24


def test_solver_action_exclusivity() -> None:
    res = solve(_scenario())
    for h in range(24):
        assert not (
            res.charge_kwh[h] > 1e-4 and res.discharge_kwh[h] > 1e-4
        ), f"hour {h}"


def test_solver_no_simultaneous_charge_discharge_with_directed_limits() -> None:
    # Battery initially full; demand forces discharge in some hour.
    battery = _battery(init=200.0)
    hours = _hours(demand=300.0)
    res = solve(_scenario(battery=battery, hours=hours))
    for h in range(24):
        assert not (
            res.charge_kwh[h] > 1e-3 and res.discharge_kwh[h] > 1e-3
        )


def test_solver_final_neutrality() -> None:
    res = solve(_scenario())
    assert abs(res.energy_after_kwh[-1] - 80.0) < 1e-3


def test_solver_solar_cap() -> None:
    validated = ValidatedDirectiveSet(
        directives=[
            # factor applied by applier
        ]
    )
    res = solve(_scenario())
    for h in range(24):
        assert res.solar_used_kwh[h] >= 0 - 1e-6
        assert res.solar_used_kwh[h] <= (
            _hours()[h].solar_kwh + 1e-3
        )


def test_solver_charge_rate_limit() -> None:
    battery = _battery(rate=10.0)
    res = solve(_scenario(battery=battery))
    for h in range(24):
        assert res.charge_kwh[h] <= 10.0 + 1e-3
        assert res.discharge_kwh[h] <= 10.0 + 1e-3


def test_solver_totals_match_hours() -> None:
    hours = _hours()
    res = solve(_scenario(hours=hours))
    expected_cost = sum(
        res.grid_kwh[h] * hours[h].tariff_bdt_per_kwh for h in range(24)
    )
    assert math.isclose(res.total_cost_bdt, expected_cost, rel_tol=1e-6)


def test_solver_with_no_charge_directive() -> None:
    from app.schemas.directives import ValidatedDirective
    vd = ValidatedDirective(
        note_index=0,
        directive_type=DirectiveTypeEnum.NO_CHARGE_WINDOW,
        applies=True,
        adjustment={"hours": [2, 3, 4]},
    )
    validated = ValidatedDirectiveSet(directives=[vd])
    res = solve(_scenario(validated=validated))
    for h in [2, 3, 4]:
        assert res.charge_kwh[h] <= 1e-4


def test_solver_with_grid_cap_directive() -> None:
    from app.schemas.directives import ValidatedDirective
    vd = ValidatedDirective(
        note_index=0,
        directive_type=DirectiveTypeEnum.MAX_GRID_WINDOW,
        applies=True,
        adjustment={"hours": [17, 18], "max_grid_kwh": 50.0},
    )
    validated = ValidatedDirectiveSet(directives=[vd])
    res = solve(_scenario(validated=validated))
    for h in [17, 18]:
        assert res.grid_kwh[h] <= 50.0 + 1e-3


def test_solver_min_reserve_directive() -> None:
    from app.schemas.directives import ValidatedDirective
    vd = ValidatedDirective(
        note_index=0,
        directive_type=DirectiveTypeEnum.MINIMUM_BATTERY_RESERVE,
        applies=True,
        adjustment={"hours": [18, 19, 20], "minimum_energy_kwh": 150.0},
    )
    validated = ValidatedDirectiveSet(directives=[vd])
    res = solve(_scenario(validated=validated))
    for h in [18, 19, 20]:
        assert res.energy_after_kwh[h] >= 150.0 - 1e-3


def test_solver_with_solar_reduction_directive() -> None:
    from app.schemas.directives import ValidatedDirective
    vd = ValidatedDirective(
        note_index=0,
        directive_type=DirectiveTypeEnum.SOLAR_REDUCTION,
        applies=True,
        adjustment={"hours": [12, 13], "factor": 0.5},
    )
    validated = ValidatedDirectiveSet(directives=[vd])
    res = solve(_scenario(validated=validated))
    assert res.solar_used_kwh[12] <= 50.0 + 1e-3
    assert res.solar_used_kwh[13] <= 50.0 + 1e-3


def test_solver_infeasible_raises() -> None:
    # Demand > grid+capped+battery rate can supply.
    battery = _battery(rate=10.0, cap=20.0, init=10.0)
    hours = _hours(demand=500.0)
    scenario = _scenario(battery=battery, hours=hours)
    with pytest.raises(InfeasibleScenarioError):
        solve(scenario)