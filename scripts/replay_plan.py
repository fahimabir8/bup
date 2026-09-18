"""Replay a saved schedule against the canonical validator.

Reads a JSON file of the form:

{
  "hours": [ { "hour": 0, "demand_kwh": ..., ... }, ... ],
  "battery": { ... },
  "plan": [ { "hour": 0, "grid_kwh": ..., ... }, ... ],
  "interpretations": [ { "note_index": 0, ... }, ... ]  // optional
}

Prints the validation result.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

from app.config import get_settings
from app.schemas.directives import (
    DirectiveInterpretationItem,
    DirectiveTypeEnum,
)
from app.schemas.request import BatteryInput, HourlyInput
from app.schemas.response import HourlyPlanItem
from app.validation.replay import replay_plan


def _load(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_interpretations(
    raw_list,
) -> list[DirectiveInterpretationItem]:
    out = []
    for raw in raw_list:
        out.append(
            DirectiveInterpretationItem(
                note_index=raw["note_index"],
                applies=raw["applies"],
                directive_type=DirectiveTypeEnum(raw["directive_type"]),
                structured_adjustment=raw.get("structured_adjustment"),
                explanation=raw.get("explanation", ""),
            )
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Path to a replay payload JSON file")
    args = parser.parse_args()

    payload = _load(args.path)
    hours = [HourlyInput.model_validate(h) for h in payload["hours"]]
    battery = BatteryInput.model_validate(payload["battery"])
    plan = [HourlyPlanItem.model_validate(h) for h in payload["plan"]]
    interpretations = _parse_interpretations(
        payload.get("interpretations", [])
    )

    settings = get_settings()
    result = replay_plan(
        plan=plan,
        hours=hours,
        battery=battery,
        interpretations=interpretations,
        numerical=settings.numerical,
    )

    print("valid:", result.valid)
    for err in result.errors:
        print("error:", err)
    for warn in result.warnings:
        print("warn:", warn)
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())