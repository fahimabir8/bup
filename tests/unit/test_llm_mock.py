"""Unit tests for the mock LLM interpreter."""

from __future__ import annotations

import asyncio

from app.llm.base import InterpretationContext
from app.llm.mock import MockInterpreter


def _ctx(notes):
    return InterpretationContext(
        scenario_id="TEST",
        operator_notes=notes,
        battery_capacity_kwh=200.0,
        peak_demand_kwh=200.0,
        peak_solar_kwh=150.0,
        peak_tariff_bdt_per_kwh=28.0,
        initial_battery_energy_kwh=80.0,
        base_minimum_energy_kwh=20.0,
    )


def test_mock_handles_solar_reduction() -> None:
    interp = MockInterpreter()
    res = asyncio.run(
        interp.interpret(
            _ctx(
                [
                    "Panel maintenance from 1 PM to 3 PM means only 20% of normal solar should be counted."
                ]
            )
        )
    )
    item = res.envelope.directive_interpretation[0]
    assert item.directive_type == "solar_reduction"
    assert item.applies is True
    assert item.structured_adjustment == {"hours": [13, 14], "factor": 0.2}


def test_mock_handles_distractor() -> None:
    interp = MockInterpreter()
    res = asyncio.run(
        interp.interpret(
            _ctx(["The cafeteria menu has changed next week."])
        )
    )
    item = res.envelope.directive_interpretation[0]
    assert item.directive_type == "no_op"
    assert item.applies is False
    assert item.structured_adjustment is None


def test_mock_handles_reserve_50_percent() -> None:
    interp = MockInterpreter()
    res = asyncio.run(
        interp.interpret(
            _ctx(
                [
                    "Keep at least 50% of the battery capacity stored in the battery from 6 PM until 9 PM for emergency operations."
                ]
            )
        )
    )
    item = res.envelope.directive_interpretation[0]
    assert item.directive_type == "minimum_battery_reserve"
    assert item.structured_adjustment["minimum_energy_kwh"] == 100.0


def test_mock_handles_multiple_notes() -> None:
    interp = MockInterpreter()
    notes = [
        "Panel washing from 1 PM to 3 PM will leave 20% of normal solar.",
        "The cafeteria menu has changed next week.",
        "Grid intake must stay at or below 100 kWh from 6 PM to 9 PM.",
    ]
    res = asyncio.run(interp.interpret(_ctx(notes)))
    items = res.envelope.directive_interpretation
    assert [i.note_index for i in items] == [0, 1, 2]
    types = [i.directive_type for i in items]
    assert types == ["solar_reduction", "no_op", "max_grid_window"]


def test_mock_handles_80_percent_reduction() -> None:
    interp = MockInterpreter()
    res = asyncio.run(
        interp.interpret(
            _ctx(
                [
                    "Expect an 80% reduction in rooftop solar between 11 AM and 2 PM because of inverter work."
                ]
            )
        )
    )
    item = res.envelope.directive_interpretation[0]
    assert item.directive_type == "solar_reduction"
    assert item.structured_adjustment["hours"] == [11, 12, 13]
    assert abs(item.structured_adjustment["factor"] - 0.2) < 1e-6


def test_mock_handles_no_charge_window() -> None:
    interp = MockInterpreter()
    res = asyncio.run(
        interp.interpret(
            _ctx(
                [
                    "Battery charging is disabled from 11 AM until 1 PM while technicians inspect the charger."
                ]
            )
        )
    )
    item = res.envelope.directive_interpretation[0]
    assert item.directive_type == "no_charge_window"
    assert item.structured_adjustment["hours"] == [11, 12]


def test_mock_handles_no_discharge_window() -> None:
    interp = MockInterpreter()
    res = asyncio.run(
        interp.interpret(
            _ctx(
                [
                    "Do not discharge the battery from 5 PM until 7 PM during relay testing."
                ]
            )
        )
    )
    item = res.envelope.directive_interpretation[0]
    assert item.directive_type == "no_discharge_window"
    assert item.structured_adjustment["hours"] == [17, 18]