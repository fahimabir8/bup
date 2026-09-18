"""Edge-case integration tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["APP_ENABLE_CACHE"] = "false"
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _base_payload() -> dict:
    return {
        "scenario_id": "EDGE-1",
        "operator_notes": ["The cafeteria menu has changed next week."],
        "hours": [
            {
                "hour": h,
                "demand_kwh": 100.0,
                "solar_kwh": 80.0 if 6 <= h <= 18 else 0.0,
                "tariff_bdt_per_kwh": 10.0 + (h % 4),
            }
            for h in range(24)
        ],
        "battery": {
            "capacity_kwh": 200.0,
            "initial_energy_kwh": 80.0,
            "minimum_energy_kwh": 20.0,
            "max_charge_kwh_per_hour": 50.0,
            "max_discharge_kwh_per_hour": 50.0,
        },
    }


def test_post_with_three_notes(client: TestClient) -> None:
    payload = _base_payload()
    payload["operator_notes"] = [
        "Panel washing from 1 PM to 3 PM will leave 20% of normal solar.",
        "The library extended its book-return hours next week.",
        "Grid intake must stay at or below 100 kWh from 6 PM to 9 PM.",
    ]
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 200
    body = response.json()
    types = [d["directive_type"] for d in body["directive_interpretation"]]
    assert types == ["solar_reduction", "no_op", "max_grid_window"]


def test_post_with_one_note(client: TestClient) -> None:
    payload = _base_payload()
    payload["operator_notes"] = ["The cafeteria menu has changed next week."]
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert len(body["directive_interpretation"]) == 1


def test_post_with_two_notes(client: TestClient) -> None:
    payload = _base_payload()
    payload["operator_notes"] = [
        "Panel washing from 1 PM to 3 PM will leave 20% of normal solar.",
        "The cafeteria menu has changed next week.",
    ]
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert len(body["directive_interpretation"]) == 2


def test_post_with_four_notes_rejected(client: TestClient) -> None:
    payload = _base_payload()
    payload["operator_notes"] = ["a", "b", "c", "d"]
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 400


def test_post_with_zero_notes_rejected(client: TestClient) -> None:
    payload = _base_payload()
    payload["operator_notes"] = []
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 400


def test_post_with_negative_demand_rejected(client: TestClient) -> None:
    payload = _base_payload()
    payload["hours"][0]["demand_kwh"] = -10.0
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 400


def test_post_with_tariff_out_of_range_rejected(client: TestClient) -> None:
    payload = _base_payload()
    payload["hours"][0]["tariff_bdt_per_kwh"] = -1.0
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 400


def test_post_with_unknown_field_rejected(client: TestClient) -> None:
    payload = _base_payload()
    payload["mystery"] = "value"
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 400


def test_post_with_hours_out_of_range_rejected(client: TestClient) -> None:
    payload = _base_payload()
    payload["hours"][0]["hour"] = 99
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 400


def test_post_with_missing_hour(client: TestClient) -> None:
    payload = _base_payload()
    payload["hours"] = payload["hours"][:23]  # missing 1 hour
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 400


def test_post_with_decimal_values(client: TestClient) -> None:
    payload = _base_payload()
    payload["operator_notes"] = [
        "PV output should drop to 12.5% of forecast between 13:00 and 15:00."
    ]
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["directive_interpretation"][0]["directive_type"] == (
        "solar_reduction"
    )


def test_health_always_works(client: TestClient) -> None:
    for _ in range(3):
        r = client.get("/health")
        assert r.status_code == 200


def test_repeated_requests_idempotent(client: TestClient) -> None:
    payload = _base_payload()
    payload["operator_notes"] = [
        "Panel washing from 1 PM to 3 PM will leave 20% of normal solar."
    ]
    first = client.post("/optimize-energy", json=payload).json()
    second = client.post("/optimize-energy", json=payload).json()
    # Determinism: same scenario + same LLM should produce the same cost.
    assert first["total_cost_bdt"] == second["total_cost_bdt"]


def test_health_response_no_secrets(client: TestClient) -> None:
    body = client.get("/health").json()
    for k in body.keys():
        assert "secret" not in k.lower()
        assert "key" not in k.lower()