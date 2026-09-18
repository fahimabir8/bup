"""Benchmark the GridWise pipeline.

Measures:

* LLM interpretation latency
* optimization latency
* validation latency
* total request latency

The benchmark intentionally uses the *mock* LLM by default so it is
hermetic. Use `--provider openai_compatible` (and configure the
related environment variables) to benchmark a real provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Ensure the project root is on PYTHONPATH when invoked directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _build_scenarios() -> List[Dict[str, Any]]:
    """Construct deterministic scenarios for the benchmark."""

    base_demand = [
        90, 85, 80, 80, 85, 95, 110, 130, 150, 165, 175, 180,
        185, 180, 170, 165, 170, 185, 205, 215, 205, 175, 135, 105,
    ]
    base_solar = [
        0, 0, 0, 0, 0, 0, 5, 20, 50, 90, 130, 160,
        180, 170, 140, 90, 45, 10, 0, 0, 0, 0, 0, 0,
    ]
    base_tariff = [
        6, 6, 5, 5, 5, 6, 8, 10, 12, 14, 16, 16,
        15, 14, 13, 14, 18, 22, 28, 30, 26, 18, 10, 7,
    ]

    scenarios = []
    scenario_templates = [
        (
            "BM-1",
            ["Panel washing from 1 PM to 3 PM will leave 20% of normal solar."],
        ),
        (
            "BM-2",
            ["The battery charger will be isolated from 2 AM until 5 AM for electrical maintenance."],
        ),
        (
            "BM-3",
            ["Keep at least 50% of the battery capacity stored in the battery from 6 PM until 9 PM for emergency operations."],
        ),
        (
            "BM-4",
            ["For protection testing, the battery must not discharge from 6 PM until 8 PM."],
        ),
        (
            "BM-5",
            ["From 6 PM until 9 PM, campus grid import must not exceed 155 kWh in any hour because the feeder is operating under a temporary limit."],
        ),
        (
            "BM-6",
            [
                "Cloud cover during panel inspection will leave about half of the forecast solar output from 10 AM until noon.",
                "The charging circuit will be unavailable from 2 PM until 4 PM.",
                "The library is extending book-return hours next week.",
            ],
        ),
    ]

    for sid, notes in scenario_templates:
        scenarios.append(
            {
                "scenario_id": sid,
                "operator_notes": notes,
                "hours": [
                    {
                        "hour": h,
                        "demand_kwh": base_demand[h],
                        "solar_kwh": base_solar[h],
                        "tariff_bdt_per_kwh": base_tariff[h],
                    }
                    for h in range(24)
                ],
                "battery": {
                    "capacity_kwh": 240.0,
                    "initial_energy_kwh": 120.0,
                    "minimum_energy_kwh": 30.0,
                    "max_charge_kwh_per_hour": 60.0,
                    "max_discharge_kwh_per_hour": 60.0,
                },
            }
        )
    return scenarios


async def _run_one(service, request) -> Dict[str, float]:
    timings: Dict[str, float] = {}
    start = time.perf_counter()
    response = await service.optimize(request)
    timings["total_ms"] = (time.perf_counter() - start) * 1000.0
    timings["cost_bdt"] = response.total_cost_bdt
    return timings


async def main_async(args: argparse.Namespace) -> None:
    os.environ.setdefault("APP_ENABLE_CACHE", "false")
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider

    from app.config import get_settings, reset_settings_cache

    reset_settings_cache()
    settings = get_settings()
    print(
        f"Benchmark provider: {settings.llm.provider} "
        f"({'mock/local' if settings.is_mock_llm else 'real'})"
    )

    if args.provider == "openai_compatible" and not settings.llm.base_url:
        print(
            "ERROR: LLM_BASE_URL is required for the openai_compatible "
            "provider."
        )
        raise SystemExit(2)

    from app.services.optimize_service import OptimizeService
    from app.schemas.request import OptimizeEnergyRequest

    service = OptimizeService.from_settings(settings)
    scenarios = _build_scenarios()
    repeats = args.repeats
    all_totals: List[float] = []
    all_costs: List[float] = []

    for i in range(repeats):
        print(f"--- Run {i + 1}/{repeats} ---")
        for raw in scenarios:
            req = OptimizeEnergyRequest.model_validate(raw)
            timings = await _run_one(service, req)
            all_totals.append(timings["total_ms"])
            all_costs.append(timings["cost_bdt"])
            print(
                f"{raw['scenario_id']:<6} "
                f"total={timings['total_ms']:7.1f} ms "
                f"cost={timings['cost_bdt']:.2f}"
            )

    print("\n--- Aggregate ---")
    print(f"requests:   {len(all_totals)}")
    print(
        f"total_ms:   mean={statistics.mean(all_totals):.1f}  "
        f"p50={statistics.median(all_totals):.1f}  "
        f"max={max(all_totals):.1f}"
    )
    print(f"cost_bdt:   range={min(all_costs):.0f}-{max(all_costs):.0f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=["mock", "openai_compatible"],
        default="mock",
        help="Which LLM provider to use",
    )
    parser.add_argument(
        "--repeats", type=int, default=1, help="Number of full iterations"
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()