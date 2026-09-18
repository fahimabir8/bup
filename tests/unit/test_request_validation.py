"""Unit tests for request validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.request import (
    BatteryInput,
    HourlyInput,
    OptimizeEnergyRequest,
    validate_request_payload,
)


def _good_hours() -> list[dict]:
    return [
        {
            "hour": h,
            "demand_kwh": 100.0,
            "solar_kwh": 50.0,
            "tariff_bdt_per_kwh": 10.0,
        }
        for h in range(24)
    ]


def _good_battery() -> dict:
    return {
        "capacity_kwh": 200.0,
        "initial_energy_kwh": 80.0,
        "minimum_energy_kwh": 20.0,
        "max_charge_kwh_per_hour": 50.0,
        "max_discharge_kwh_per_hour": 50.0,
    }


def test_valid_request_passes() -> None:
    req = validate_request_payload(
        {
            "scenario_id": "TEST-1",
            "operator_notes": ["hello"],
            "hours": _good_hours(),
            "battery": _good_battery(),
        }
    )
    assert isinstance(req, OptimizeEnergyRequest)
    assert req.scenario_id == "TEST-1"
    assert len(req.hours) == 24


def test_hours_must_have_24_entries() -> None:
    payload = {
        "scenario_id": "TEST-2",
        "operator_notes": ["note"],
        "hours": _good_hours()[:23],
        "battery": _good_battery(),
    }
    with pytest.raises(ValidationError):
        validate_request_payload(payload)


def test_hours_must_cover_full_range() -> None:
    hours = _good_hours()
    hours[5] = hours[5].copy()
    hours[5]["hour"] = 24  # out-of-range value
    with pytest.raises(ValidationError):
        validate_request_payload(
            {
                "scenario_id": "TEST-3",
                "operator_notes": ["note"],
                "hours": hours,
                "battery": _good_battery(),
            }
        )


def test_duplicate_hour_rejected() -> None:
    hours = _good_hours()
    hours[1]["hour"] = 0  # duplicate
    with pytest.raises(ValidationError):
        validate_request_payload(
            {
                "scenario_id": "TEST-4",
                "operator_notes": ["note"],
                "hours": hours,
                "battery": _good_battery(),
            }
        )


def test_operator_notes_count_limit() -> None:
    payload = {
        "scenario_id": "TEST-5",
        "operator_notes": ["a", "b", "c", "d"],
        "hours": _good_hours(),
        "battery": _good_battery(),
    }
    with pytest.raises(ValidationError):
        validate_request_payload(payload)


def test_negative_demand_rejected() -> None:
    hours = _good_hours()
    hours[0]["demand_kwh"] = -1.0
    with pytest.raises(ValidationError):
        validate_request_payload(
            {
                "scenario_id": "TEST-6",
                "operator_notes": ["note"],
                "hours": hours,
                "battery": _good_battery(),
            }
        )


def test_battery_capacity_must_be_positive() -> None:
    battery = _good_battery()
    battery["capacity_kwh"] = 0.0
    with pytest.raises(ValidationError):
        validate_request_payload(
            {
                "scenario_id": "TEST-7",
                "operator_notes": ["note"],
                "hours": _good_hours(),
                "battery": battery,
            }
        )


def test_operator_notes_stripped() -> None:
    req = validate_request_payload(
        {
            "scenario_id": "TEST-8",
            "operator_notes": ["  trimmed  "],
            "hours": _good_hours(),
            "battery": _good_battery(),
        }
    )
    assert req.operator_notes[0] == "trimmed"


def test_extra_fields_rejected() -> None:
    battery = _good_battery()
    battery["mystery"] = 5.0
    with pytest.raises(ValidationError):
        BatteryInput.model_validate(battery)


def test_hour_out_of_range() -> None:
    with pytest.raises(ValidationError):
        HourlyInput(hour=24, demand_kwh=1, solar_kwh=0, tariff_bdt_per_kwh=1)


def test_blank_operator_note_rejected() -> None:
    payload = {
        "scenario_id": "TEST-9",
        "operator_notes": ["   "],
        "hours": _good_hours(),
        "battery": _good_battery(),
    }
    with pytest.raises(ValidationError):
        validate_request_payload(payload)
