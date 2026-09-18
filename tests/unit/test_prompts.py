"""Unit tests for the LLM prompt templates."""

from __future__ import annotations

from app.llm.prompts import SYSTEM_PROMPT, build_user_payload


def test_system_prompt_lists_six_directives() -> None:
    assert "solar_reduction" in SYSTEM_PROMPT
    assert "minimum_battery_reserve" in SYSTEM_PROMPT
    assert "no_charge_window" in SYSTEM_PROMPT
    assert "no_discharge_window" in SYSTEM_PROMPT
    assert "max_grid_window" in SYSTEM_PROMPT
    assert "no_op" in SYSTEM_PROMPT


def test_system_prompt_explains_time_semantics() -> None:
    assert "start-inclusive" in SYSTEM_PROMPT or "inclusive" in SYSTEM_PROMPT
    assert "1 PM to 3 PM" in SYSTEM_PROMPT
    assert "13, 14" in SYSTEM_PROMPT


def test_system_prompt_explains_factor_semantics() -> None:
    assert "factor" in SYSTEM_PROMPT
    assert "reduction" in SYSTEM_PROMPT.lower()


def test_build_user_payload_serialises_json() -> None:
    notes = ["Note A", "Note B"]
    body = build_user_payload(
        notes,
        {
            "scenario_id": "S-1",
            "battery_capacity_kwh": 100.0,
            "initial_battery_energy_kwh": 50.0,
            "base_minimum_energy_kwh": 10.0,
            "peak_demand_kwh": 200.0,
            "peak_solar_kwh": 150.0,
            "peak_tariff_bdt_per_kwh": 25.0,
        },
    )
    assert '"Note A"' in body
    assert "S-1" in body
    assert "100.0" in body