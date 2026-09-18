"""Generate synthetic GridWise sample scenarios.

Each scenario is a fully self-contained JSON object following the
public sample format (input + expected_output) so that the same
validation script can run against both official and generated data.

The cases are deterministic (fixed random seed) and clearly labelled
as SELF-GENERATED in their IDs and explanations.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
from typing import Any, Dict, List, Tuple


SCENARIO_PREFIX = "SYN-"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _demand_curve(seed: int) -> List[float]:
    rng = random.Random(seed)
    base = [80 + 15 * math.sin(math.pi * h / 24) for h in range(24)]
    base = [max(40.0, b + rng.uniform(-5.0, 5.0)) for b in base]
    evening = [10 if 17 <= h <= 22 else 0 for h in range(24)]
    return [_clamp(b + e, 30.0, 250.0) for b, e in zip(base, evening)]


def _solar_curve(seed: int) -> List[float]:
    rng = random.Random(seed)
    out = []
    for h in range(24):
        if 6 <= h <= 18:
            peak = 200.0 * math.exp(-((h - 12.5) ** 2) / 10.0)
            out.append(_clamp(peak + rng.uniform(-10.0, 10.0), 0.0, 220.0))
        else:
            out.append(0.0)
    return out


def _tariff_curve(seed: int) -> List[float]:
    rng = random.Random(seed)
    base = 6.0
    peak = 28.0
    out = []
    for h in range(24):
        if 18 <= h <= 22:
            v = peak + rng.uniform(-1.0, 1.0)
        elif 8 <= h <= 17:
            v = 12.0 + rng.uniform(-1.5, 2.5)
        elif 6 <= h <= 7:
            v = 8.0 + rng.uniform(-0.5, 0.5)
        else:
            v = base + rng.uniform(-0.5, 0.5)
        out.append(_clamp(v, 4.0, 32.0))
    return out


def _battery(seed: int) -> Dict[str, float]:
    rng = random.Random(seed)
    cap = _clamp(rng.uniform(150.0, 400.0), 100.0, 500.0)
    initial = _clamp(rng.uniform(0.35, 0.65) * cap, 20.0, cap - 10.0)
    minimum = _clamp(rng.uniform(0.10, 0.20) * cap, 0.0, cap / 2)
    rate = _clamp(rng.uniform(30.0, 80.0), 10.0, cap / 2)
    return {
        "capacity_kwh": round(cap, 2),
        "initial_energy_kwh": round(initial, 2),
        "minimum_energy_kwh": round(minimum, 2),
        "max_charge_kwh_per_hour": round(rate, 2),
        "max_discharge_kwh_per_hour": round(rate, 2),
    }


def _hours(
    demand: List[float],
    solar: List[float],
    tariff: List[float],
) -> List[Dict[str, Any]]:
    return [
        {
            "hour": h,
            "demand_kwh": round(demand[h], 2),
            "solar_kwh": round(solar[h], 2),
            "tariff_bdt_per_kwh": round(tariff[h], 2),
        }
        for h in range(24)
    ]


def _case(
    case_id: str,
    operator_notes: List[str],
    seed: int,
    tag: str,
    description: str,
) -> Dict[str, Any]:
    demand = _demand_curve(seed)
    solar = _solar_curve(seed)
    tariff = _tariff_curve(seed)
    battery = _battery(seed)
    hours = _hours(demand, solar, tariff)
    return {
        "id": case_id,
        "tag": tag,
        "description": description,
        "input": {
            "scenario_id": case_id,
            "operator_notes": operator_notes,
            "hours": hours,
            "battery": battery,
        },
    }


def build_cases() -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []

    cases.append(
        _case(
            f"{SCENARIO_PREFIX}SOLAR-01",
            [
                "PV production will fall to one-fifth between 13:00 and 15:00."
            ],
            seed=101,
            tag="solar_reduction",
            description="Paraphrased solar reduction using 13:00-15:00 format.",
        )
    )
    cases.append(
        _case(
            f"{SCENARIO_PREFIX}SOLAR-02",
            [
                "Panel maintenance means only 20% of normal solar should be counted from 1 PM through 2 PM."
            ],
            seed=102,
            tag="solar_reduction",
            description="Solar reduction using '20% of normal solar' phrasing.",
        )
    )
    cases.append(
        _case(
            f"{SCENARIO_PREFIX}SOLAR-03",
            [
                "Expect an 80 percent decrease in rooftop generation during 1-3 PM."
            ],
            seed=103,
            tag="solar_reduction",
            description="Solar reduction with percentage-decrease phrasing.",
        )
    )

    cases.append(
        _case(
            f"{SCENARIO_PREFIX}RESERVE-01",
            [
                "Keep at least 120 kWh stored from 6 PM to 9 PM."
            ],
            seed=201,
            tag="minimum_battery_reserve",
            description="Battery reserve with explicit kWh value.",
        )
    )
    cases.append(
        _case(
            f"{SCENARIO_PREFIX}RESERVE-02",
            [
                "The battery must retain a minimum of 120 units through the evening peak."
            ],
            seed=202,
            tag="minimum_battery_reserve",
            description="Reserve with non-standard unit phrasing.",
        )
    )

    cases.append(
        _case(
            f"{SCENARIO_PREFIX}NOCHARGE-01",
            [
                "Battery charging is unavailable from 2 PM to 4 PM."
            ],
            seed=301,
            tag="no_charge_window",
            description="No-charge window with natural phrasing.",
        )
    )
    cases.append(
        _case(
            f"{SCENARIO_PREFIX}NOCHARGE-02",
            [
                "Do not replenish the storage unit during hours 14 and 15."
            ],
            seed=302,
            tag="no_charge_window",
            description="No-charge window using 'hours X and Y' phrasing.",
        )
    )

    cases.append(
        _case(
            f"{SCENARIO_PREFIX}NODISCHARGE-01",
            [
                "Keep the battery from discharging between 6 PM and 8 PM."
            ],
            seed=401,
            tag="no_discharge_window",
            description="No-discharge window with 'between X and Y' phrasing.",
        )
    )

    cases.append(
        _case(
            f"{SCENARIO_PREFIX}GRIDCAP-01",
            [
                "Grid import must stay at or below 100 kWh during 5-7 PM."
            ],
            seed=501,
            tag="max_grid_window",
            description="Grid cap using 'stay at or below' phrasing.",
        )
    )
    cases.append(
        _case(
            f"{SCENARIO_PREFIX}GRIDCAP-02",
            [
                "Do not draw more than 100 kWh from the utility during hours 17 and 18."
            ],
            seed=502,
            tag="max_grid_window",
            description="Grid cap using 'do not draw more than' phrasing.",
        )
    )

    cases.append(
        _case(
            f"{SCENARIO_PREFIX}DISTRACTOR-01",
            ["The cafeteria menu has changed next week."],
            seed=601,
            tag="no_op",
            description="Single distractor note.",
        )
    )
    cases.append(
        _case(
            f"{SCENARIO_PREFIX}DISTRACTOR-02",
            ["The registration deadline moved to next month."],
            seed=602,
            tag="no_op",
            description="Single distractor note (registrations).",
        )
    )
    cases.append(
        _case(
            f"{SCENARIO_PREFIX}DISTRACTOR-03",
            ["The sports department updated its event calendar."],
            seed=603,
            tag="no_op",
            description="Single distractor note (sports).",
        )
    )

    cases.append(
        _case(
            f"{SCENARIO_PREFIX}MULTI-01",
            [
                "Panel washing from 1 PM to 3 PM will leave 20% of normal solar.",
                "Battery must hold at least 80 kWh from 6 PM to 9 PM.",
            ],
            seed=701,
            tag="two_directives",
            description="Two applicable directives, solar + reserve.",
        )
    )
    cases.append(
        _case(
            f"{SCENARIO_PREFIX}MULTI-02",
            [
                "The battery charger will be isolated from 2 AM until 5 AM for electrical maintenance.",
                "From 6 PM until 9 PM, campus grid import must not exceed 130 kWh because the feeder is operating under a temporary limit.",
            ],
            seed=702,
            tag="two_directives",
            description="Two applicable directives, no-charge + grid cap.",
        )
    )
    cases.append(
        _case(
            f"{SCENARIO_PREFIX}MULTI-03",
            [
                "Expect an 80% reduction in rooftop solar between 11 AM and 2 PM because of inverter work.",
                "The student affairs office will publish club notices tomorrow.",
                "Grid intake must stay at or below 150 kWh from 6 PM to 9 PM while the substation is constrained.",
            ],
            seed=703,
            tag="three_notes",
            description="Three notes, one distractor, two applicable directives.",
        )
    )

    cases.append(
        _case(
            f"{SCENARIO_PREFIX}DECIMAL-01",
            [
                "PV output should drop to 12.5% of forecast between 13:00 and 15:00.",
                "Reserve at least 87.5 kWh from 6 PM to 9 PM.",
            ],
            seed=801,
            tag="decimal_values",
            description="Decimal kWh and percent values.",
        )
    )

    cases.append(
        _case(
            f"{SCENARIO_PREFIX}PARAPHRASE-01",
            [
                "Expect a 70% drop in rooftop generation during 1-3 PM.",
                "Avoid charging the battery from 14:00 to 16:00.",
                "Keep 75 kWh in the battery from 18:00 to 21:00.",
            ],
            seed=901,
            tag="multiple_paraphrases",
            description="Three paraphrased directives of different types.",
        )
    )

    return cases


def build_envelope(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "metadata": {
            "label": "SELF-GENERATED TEST CASE",
            "notice": "NOT OFFICIAL ORGANIZER SAMPLE",
            "description": (
                "Deterministic synthetic scenarios produced by "
                "scripts/generate_samples.py. Used to validate the "
                "GridWise service when official samples are unavailable."
            ),
        },
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=os.path.join(
            os.path.dirname(__file__), "..", "data", "generated_samples.json"
        ),
        help="Output file path",
    )
    args = parser.parse_args()

    envelope = build_envelope(build_cases())
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2)
    print(f"Wrote {len(envelope['cases'])} cases to {args.output}")


if __name__ == "__main__":
    main()