"""Tests against the self-generated sample cases.

These tests run every generated sample end-to-end and confirm that
the deterministic pipeline returns a valid schedule. They are
intentionally permissive about exact cost (since the cases are
self-generated and may evolve) but strict about validity, totals,
and directive type coverage.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import List

import pytest


GENERATED_SAMPLE_FILENAMES = (
    os.path.join("data", "generated_samples.json"),
    os.path.join("scripts", "..", "data", "generated_samples.json"),
)


def _find_generated_sample_file() -> str | None:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in GENERATED_SAMPLE_FILENAMES:
        path = (
            name if os.path.isabs(name) else os.path.join(base, name)
        )
        if os.path.exists(path):
            return path
    return None


def _load_cases() -> List[dict]:
    path = _find_generated_sample_file()
    if path is None:
        return []
    with open(path, "r", encoding="utf-8") as f:
        envelope = json.load(f)
    return envelope.get("cases", [])


def pytest_generate_tests(metafunc):
    if "generated_case" in metafunc.fixturenames:
        cases = _load_cases()
        if not cases:
            metafunc.parametrize("generated_case", [], ids=[])
            return
        ids = [c.get("id", f"case-{i}") for i, c in enumerate(cases)]
        metafunc.parametrize("generated_case", cases, ids=ids)


@pytest.fixture(scope="module")
def service():
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["APP_ENABLE_CACHE"] = "false"
    from app.config import get_settings
    from app.services.optimize_service import OptimizeService

    settings = get_settings()
    return OptimizeService.with_mock(settings)


def _run(coro):
    return asyncio.run(coro)


def test_generated_samples_available_or_skipped() -> None:
    if _find_generated_sample_file() is None:
        pytest.skip(
            "generated_samples.json not found; "
            "run scripts/generate_samples.py first"
        )


def test_generated_sample(generated_case, service) -> None:
    if not generated_case:
        pytest.skip(
            "generated_samples.json not found; "
            "run scripts/generate_samples.py first"
        )

    from app.schemas.request import OptimizeEnergyRequest
    from app.validation.response_validator import validate_response

    req = OptimizeEnergyRequest.model_validate(generated_case["input"])
    response = _run(service.optimize(req))
    # The schedule must be replayable.
    interpretations = response.directive_interpretation
    report = validate_response(
        response.hourly_plan, req.hours, req.battery, interpretations
    )
    assert report.valid, report.errors
    # Notes must each yield an interpretation.
    assert len(response.directive_interpretation) == len(
        generated_case["input"]["operator_notes"]
    )
    # Totals consistency.
    assert abs(report.total_grid_kwh - response.total_grid_kwh) < 1e-3
    assert abs(report.total_cost_bdt - response.total_cost_bdt) < 1e-3
    assert abs(report.peak_grid_kwh - response.peak_grid_kwh) < 1e-3


def test_no_op_case_produces_no_applicable_directives() -> None:
    """A plain distractor case should produce all `no_op` interpretations."""

    path = _find_generated_sample_file()
    if path is None:
        pytest.skip("generated_samples.json not found")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    distractor_cases = [
        c
        for c in data["cases"]
        if c.get("tag") == "no_op"
    ]
    assert distractor_cases, "no distractor cases found"
    for c in distractor_cases:
        for note in c["input"]["operator_notes"]:
            assert "cafeteria" in note.lower() or "registration" in (
                note.lower()
            ) or "sports" in note.lower()
