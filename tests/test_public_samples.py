"""Tests against the official public sample cases (when present).

The tests look for the official file at two optional locations:

* `data/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json`
* `BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json` (project root)

If neither file is present the tests are skipped. This means the test
suite runs cleanly even when official sample data is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Iterable, List, Tuple

import pytest


SAMPLE_FILENAMES = (
    "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json",
    os.path.join(
        "data", "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
    ),
)


def _find_sample_file() -> str | None:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in SAMPLE_FILENAMES:
        path = (
            name if os.path.isabs(name) else os.path.join(base, name)
        )
        if os.path.exists(path):
            return path
    return None


def _load_cases() -> List[dict]:
    path = _find_sample_file()
    if path is None:
        return []
    with open(path, "r", encoding="utf-8") as f:
        envelope = json.load(f)
    return envelope.get("cases", [])


def pytest_generate_tests(metafunc):
    if "public_case" in metafunc.fixturenames:
        cases = _load_cases()
        if not cases:
            metafunc.parametrize("public_case", [], ids=[])
            return
        ids = [c.get("id", f"case-{i}") for i, c in enumerate(cases)]
        metafunc.parametrize("public_case", cases, ids=ids)


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


def test_public_samples_file_present_or_skipped() -> None:
    """The file MAY be absent; this test always passes."""

    path = _find_sample_file()
    if path is None:
        pytest.skip(
            "Official public sample file not present; "
            "synthetic and property-based validation used."
        )
    assert path is not None


def test_public_sample(public_case, service) -> None:
    """Run one public sample case end-to-end."""

    if not public_case:
        pytest.skip(
            "Official public sample file not present; "
            "synthetic and property-based validation used."
        )

    from app.schemas.request import OptimizeEnergyRequest
    from app.validation.response_validator import validate_response

    case_input = public_case["input"]
    expected = public_case["expected_output"]
    req = OptimizeEnergyRequest.model_validate(case_input)
    response = _run(service.optimize(req))

    # 1. Interpretation count and ordering.
    assert len(response.directive_interpretation) == len(
        expected["directive_interpretation"]
    ), (
        f"{public_case.get('id')}: expected "
        f"{len(expected['directive_interpretation'])} interpretations, "
        f"got {len(response.directive_interpretation)}"
    )
    for i, exp in enumerate(expected["directive_interpretation"]):
        got = response.directive_interpretation[i]
        assert got.note_index == exp["note_index"]
        assert got.applies == exp["applies"]
        assert got.directive_type.value == exp["directive_type"]

    # 2. Schedule length and replay invariants.
    assert len(response.hourly_plan) == 24
    interpretations = response.directive_interpretation
    report = validate_response(
        response.hourly_plan, req.hours, req.battery, interpretations
    )
    assert report.valid, report.errors

    # 3. Cost within tolerance.
    exp_cost = expected["total_cost_bdt"]
    got_cost = response.total_cost_bdt
    # Allow a small absolute tolerance; equivalent optimal solutions are
    # accepted as valid per the spec.
    assert abs(got_cost - exp_cost) <= 0.05, (
        f"{public_case.get('id')}: expected cost {exp_cost}, got {got_cost}"
    )

    # 4. Totals consistent.
    assert abs(report.total_grid_kwh - response.total_grid_kwh) < 1e-3
    assert abs(report.total_cost_bdt - response.total_cost_bdt) < 1e-3
    assert abs(report.peak_grid_kwh - response.peak_grid_kwh) < 1e-3
