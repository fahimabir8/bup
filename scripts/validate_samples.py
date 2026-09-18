"""Validate the GridWise service against official or generated sample cases.

The script auto-discovers sample files in:

* `data/public_samples.json`
* `data/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json`
* `BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json` (project root)

A specific path can also be supplied via `--file`.

For each sample:

1. POST the input to `/optimize-energy`
2. Validate the response schema
3. Confirm directive interpretation matches
4. Replay the plan
5. Verify totals
6. Compare cost against the official reference within tolerance
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx


DEFAULT_SEARCH_PATHS = (
    os.path.join("data", "public_samples.json"),
    os.path.join(
        "data",
        "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json",
    ),
    "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json",
)


def _find_file(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        if os.path.exists(explicit):
            return explicit
        return None
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in DEFAULT_SEARCH_PATHS:
        candidate = (
            rel if os.path.isabs(rel) else os.path.join(here, rel)
        )
        if os.path.exists(candidate):
            return candidate
    return None


def _load_cases(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        envelope = json.load(f)
    return envelope.get("cases", [])


def _check_case(
    client: httpx.Client,
    endpoint: str,
    case: Dict[str, Any],
    tolerance: float,
) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    case_id = case.get("id", "?")
    payload = case["input"]
    response = client.post(endpoint, json=payload)
    if response.status_code != 200:
        return False, [
            f"{case_id}: HTTP {response.status_code} "
            f"{response.text[:200]}"
        ]
    body = response.json()

    expected = case.get("expected_output")
    # 1. interpretation length / ordering (only when expected_output is present)
    if expected is not None:
        interp = body.get("directive_interpretation", [])
        exp_interp = expected.get("directive_interpretation", [])
        if len(interp) != len(exp_interp):
            errors.append(
                f"{case_id}: expected {len(exp_interp)} interpretations, "
                f"got {len(interp)}"
            )
        for i, exp in enumerate(exp_interp):
            if i >= len(interp):
                continue
            got = interp[i]
            if got.get("note_index") != exp.get("note_index"):
                errors.append(
                    f"{case_id}: note_index mismatch at {i}"
                )
            if got.get("applies") != exp.get("applies"):
                errors.append(
                    f"{case_id}: applies mismatch at {i} "
                    f"(got {got.get('applies')}, expected "
                    f"{exp.get('applies')})"
                )
            if got.get("directive_type") != exp.get("directive_type"):
                errors.append(
                    f"{case_id}: directive_type mismatch at {i} "
                    f"(got {got.get('directive_type')}, expected "
                    f"{exp.get('directive_type')})"
                )
        # 2. cost tolerance
        cost_got = body.get("total_cost_bdt")
        cost_exp = expected.get("total_cost_bdt")
        if cost_exp is not None and abs(cost_got - cost_exp) > tolerance:
            errors.append(
                f"{case_id}: cost diff {abs(cost_got - cost_exp):.2f} > "
                f"{tolerance:.2f}"
            )
    # 3. plan invariants
    plan = body.get("hourly_plan", [])
    if len(plan) != 24:
        errors.append(f"{case_id}: plan length {len(plan)} != 24")
    last_energy = plan[-1].get("battery_energy_after_kwh")
    init = payload["battery"]["initial_energy_kwh"]
    if abs(last_energy - init) > 1e-2:
        errors.append(
            f"{case_id}: end-of-day battery {last_energy} != "
            f"initial {init}"
        )
    # 4. totals
    total_grid_recalc = sum(h["grid_kwh"] for h in plan)
    if abs(total_grid_recalc - body.get("total_grid_kwh", 0)) > 1e-2:
        errors.append(
            f"{case_id}: total_grid_kwh {body.get('total_grid_kwh')} "
            f"!= sum(plan.grid_kwh) {total_grid_recalc}"
        )
    return (not errors), errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file", help="Path to a JSON file containing sample cases"
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the running GridWise service",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="Allowed absolute cost tolerance",
    )
    parser.add_argument(
        "--start-server",
        action="store_true",
        help="Spawn an in-process FastAPI server (mock LLM) for validation",
    )
    args = parser.parse_args()

    sample_path = _find_file(args.file)
    if sample_path is None:
        print(
            "ERROR: no sample file found. Place official or generated "
            "samples in one of the supported locations.",
            file=sys.stderr,
        )
        return 2

    cases = _load_cases(sample_path)
    if not cases:
        print(f"WARNING: no cases found in {sample_path}", file=sys.stderr)
        return 0

    print(f"Validating {len(cases)} case(s) from {sample_path}")

    endpoint = f"{args.url.rstrip('/')}/optimize-energy"
    all_errors: List[str] = []

    if args.start_server:
        from fastapi.testclient import TestClient

        from app.main import create_app

        os.environ["LLM_PROVIDER"] = os.environ.get("LLM_PROVIDER", "mock")
        os.environ["APP_ENABLE_CACHE"] = "false"
        app = create_app()
        with TestClient(app) as client:
            for case in cases:
                ok, errors = _check_case(
                    client, endpoint, case, args.tolerance
                )
                all_errors.extend(errors)
                status = "PASS" if ok else "FAIL"
                print(f"  {status}: {case.get('id')}")
    else:
        with httpx.Client(timeout=60.0) as client:
            try:
                health = client.get(f"{args.url.rstrip('/')}/health")
            except httpx.HTTPError as exc:
                print(
                    f"ERROR: cannot reach {args.url}: {exc}",
                    file=sys.stderr,
                )
                return 3
            if health.status_code != 200:
                print(
                    f"ERROR: health endpoint returned {health.status_code}",
                    file=sys.stderr,
                )
                return 3
            for case in cases:
                ok, errors = _check_case(
                    client, endpoint, case, args.tolerance
                )
                all_errors.extend(errors)
                status = "PASS" if ok else "FAIL"
                print(f"  {status}: {case.get('id')}")

    print()
    if all_errors:
        print(f"{len(all_errors)} failure(s):")
        for err in all_errors:
            print(f"  - {err}")
        return 1
    print("All cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())