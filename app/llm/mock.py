"""Mock LLM interpreter used for local automated tests.

The mock must NEVER be the production default. It exists so that the
test suite can exercise the full interpretation pipeline without an
external API.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from app.llm.base import (
    InterpretationContext,
    InterpretationResult,
    LLMInterpreter,
)
from app.llm.prompts import INTERPRETER_PROMPT_VERSION

# A very small normalization helper, NOT a substitution for the LLM.
_HOUR_WORDS: Dict[str, int] = {
    "noon": 12,
    "midnight": 0,
    "1am": 1,
    "2am": 2,
    "3am": 3,
    "4am": 4,
    "5am": 5,
    "6am": 6,
    "7am": 7,
    "8am": 8,
    "9am": 9,
    "10am": 10,
    "11am": 11,
    "12pm": 12,
    "1pm": 13,
    "2pm": 14,
    "3pm": 15,
    "4pm": 16,
    "5pm": 17,
    "6pm": 18,
    "7pm": 19,
    "8pm": 20,
    "9pm": 21,
    "10pm": 22,
    "11pm": 23,
}


def _parse_clock(token: str) -> Optional[int]:
    token = token.strip().lower().strip(",.;:")
    token = re.sub(r"\s+", " ", token)
    # Direct word lookup first (handles "noon", "midnight", etc.)
    if token in _HOUR_WORDS:
        return _HOUR_WORDS[token]
    m = re.match(
        r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?$",
        token,
    )
    if not m:
        # Try alternative with the time first (no :\d{2} form).
        m = re.match(r"^(\d{1,2})\s*(am|pm)$", token)
        if not m:
            return None
        hour = int(m.group(1))
        suffix = m.group(2)
        if suffix == "pm" and hour < 12:
            hour += 12
        if suffix == "am" and hour == 12:
            hour = 0
        return hour if 0 <= hour <= 23 else None
    hour = int(m.group(1))
    minutes = int(m.group(2) or 0)
    suffix = m.group(3)
    if suffix and suffix.endswith("."):
        suffix = suffix[:-1]
    if suffix == "pm" and hour < 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0
    if minutes != 0:
        # Whole-hour semantics only.
        return None
    if not (0 <= hour <= 23):
        return None
    return hour


def _parse_window(text: str) -> Optional[List[int]]:
    """Return ascending hours for phrases like "1 PM to 3 PM"."""

    text = text.lower()
    text = text.replace("until", " to ").replace(" through ", " to ")
    text = text.replace("–", "-").replace("—", "-")
    # Normalise noon / midnight to numeric phrases so the regex captures them.
    text = text.replace("noon", "12 pm")
    text = text.replace("midnight", "12 am")

    patterns = [
        # Match colon-separated time ranges first: "13:00-15:00"
        r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})",
        # "hours 18-20"
        r"hours?\s*(\d{1,2})\s*(?:to|-)\s*(\d{1,2})",
        # "between 1 PM and 3 PM"
        r"between\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+and\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        # "1 PM to/until 3 PM" (clock-form)
        r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:to|until|-)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        # "from 1 PM to/until 3 PM"
        r"from\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:to|until|-)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        groups = m.groups()
        if pat.startswith("(\\d{1,2}):(\\d{2})"):
            start = int(groups[0])
            end = int(groups[2])
        elif pat.startswith("hours?"):
            start = int(groups[0])
            end = int(groups[1])
        else:
            start = _parse_clock(groups[0])
            end = _parse_clock(groups[1])
            if start is None or end is None:
                continue
        if end <= start:
            continue
        return list(range(start, end))
    return None


@dataclass
class MockRule:
    """A simple rule used by the deterministic mock LLM.

    The mock applies rules in order. The first matching rule whose
    `applies_if` predicate returns True wins; otherwise `no_op` is
    produced. This keeps the mock useful for tests without turning
    it into a phrase dictionary that replaces the real LLM.
    """

    name: str
    predicate: Callable[[str, InterpretationContext], bool]
    build: Callable[[str, InterpretationContext], dict]


@dataclass
class MockState:
    rules: List[MockRule] = field(default_factory=list)


def _default_rules() -> List[MockRule]:
    """Built-in rule set for the mock interpreter."""

    rules: List[MockRule] = []

    def _has(text: str, *keywords: str) -> bool:
        lowered = text.lower()
        return any(kw in lowered for kw in keywords)

    def _window(text: str) -> Optional[List[int]]:
        return _parse_window(text)

    # ---- Solar reduction -------------------------------------------------
    def solar_predicate(text: str, ctx: InterpretationContext) -> bool:
        return _has(
            text,
            "solar",
            "panel",
            "pv",
            "rooftop",
            "inverter",
        ) and not _has(text, "no charge", "no discharge", "cap")

    def solar_build(text: str, ctx: InterpretationContext) -> dict:
        lowered = text.lower()
        hours = _window(text) or []
        if not hours:
            # Fallback: assume single hour at noon if text mentions noon.
            if "noon" in lowered:
                hours = [12]

        factor = 1.0
        # First try the "remaining" pattern: "<verb> <pct>% of ..." or
        # "<pct>% of normal/forecast/usable".
        remaining_patterns = [
            r"(?:leave|only|about|around|roughly|approximately|leaves|kept at)\s+(\d{1,3})\s*(?:%|percent)",
            r"(\d{1,3})\s*(?:%|percent)\s+of\s+(?:normal|forecast|the forecast|usable|panels?)",
        ]
        reduction_patterns = [
            r"(\d{1,3})\s*(?:%|percent)\s+(?:reduction|reduced|decrease|less)",
            r"(?:reduction|reduced|decrease)\s+of\s+(\d{1,3})\s*(?:%|percent)",
        ]
        for pat in remaining_patterns:
            m = re.search(pat, lowered)
            if m:
                pct = float(m.group(1))
                factor = max(0.0, min(1.0, pct / 100.0))
                break
        else:
            for pat in reduction_patterns:
                m = re.search(pat, lowered)
                if m:
                    pct = float(m.group(1))
                    factor = max(0.0, min(1.0, 1.0 - pct / 100.0))
                    break
            else:
                # Verbal fractions.
                verbal_remaining = {
                    "half": 0.5,
                    "one fifth": 0.2,
                    "one-fifth": 0.2,
                    "one quarter": 0.25,
                    "one-quarter": 0.25,
                    "one third": 1 / 3,
                    "one-third": 1 / 3,
                    "two thirds": 2 / 3,
                    "two-thirds": 2 / 3,
                    "three quarters": 0.75,
                    "three-quarters": 0.75,
                }
                verbal_reduction = {
                    "half reduction": 0.5,
                }
                for k, v in verbal_remaining.items():
                    if k in lowered:
                        factor = v
                        break
                else:
                    for k, v in verbal_reduction.items():
                        if k in lowered:
                            factor = 1.0 - v
                            break
        if not hours:
            raise ValueError("solar note without parseable time window")
        return {
            "directive_type": "solar_reduction",
            "hours": hours,
            "factor": factor,
        }

    rules.append(
        MockRule("solar_reduction", solar_predicate, solar_build)
    )

    # ---- Battery reserve --------------------------------------------------
    def reserve_predicate(text: str, ctx: InterpretationContext) -> bool:
        lowered = text.lower()
        kw_reserve = any(
            k in lowered
            for k in (
                "reserve",
                "retain",
                "remain",
                "minimum",
                "at least",
                "must stay above",
                "must not drop below",
                "must remain",
                "must retain",
                "must keep",
                "do not allow",
                "below",
                "data center",
                "emergency",
            )
        )
        kw_discharge_window = any(
            k in lowered for k in ("no discharge", "do not discharge")
        )
        kw_charge_window = any(
            k in lowered for k in ("no charge", "do not charge")
        )
        kw_grid = any(
            k in lowered
            for k in ("grid import", "grid intake", "feeder")
        )
        if kw_discharge_window or kw_charge_window or kw_grid:
            return False
        # Distinguish "below" alone: only relevant if the note mentions
        # an energy / kWh value to constrain the battery.
        return kw_reserve

    def reserve_build(text: str, ctx: InterpretationContext) -> dict:
        hours = _window(text) or []
        if not hours:
            raise ValueError("reserve note without parseable time window")
        m = re.search(
            r"(\d+(?:\.\d+)?)\s*kwh", text.lower()
        )
        if m:
            min_kwh = float(m.group(1))
        elif "half" in text.lower() or "50%" in text.lower():
            min_kwh = float(ctx.battery_capacity_kwh) * 0.5
        elif "half of" in text.lower():
            min_kwh = float(ctx.battery_capacity_kwh) * 0.5
        else:
            raise ValueError("reserve note without parseable kWh value")
        return {
            "directive_type": "minimum_battery_reserve",
            "hours": hours,
            "minimum_energy_kwh": min_kwh,
        }

    rules.append(
        MockRule("minimum_battery_reserve", reserve_predicate, reserve_build)
    )

    # ---- No-charge window -------------------------------------------------
    def no_charge_predicate(text: str, ctx: InterpretationContext) -> bool:
        lowered = text.lower()
        kw_charge = any(
            kw in lowered
            for kw in (
                "no charge",
                "no-charge",
                "charging-circuit",
                "charging circuit",
                "charger",
                "do not replenish",
                "prohibit grid charging",
                "battery charging is unavailable",
                "battery charging is disabled",
                "charger isolated",
                "charging is unavailable",
            )
        )
        kw_discharge = any(
            kw in lowered
            for kw in ("discharge", "no discharge")
        )
        return kw_charge and not kw_discharge

    def no_charge_build(text: str, ctx: InterpretationContext) -> dict:
        hours = _window(text) or []
        if not hours:
            raise ValueError("no_charge note without parseable time window")
        return {
            "directive_type": "no_charge_window",
            "hours": hours,
        }

    rules.append(
        MockRule("no_charge_window", no_charge_predicate, no_charge_build)
    )

    # ---- No-discharge window ---------------------------------------------
    def no_discharge_predicate(text: str, ctx: InterpretationContext) -> bool:
        return _has(
            text,
            "no discharge",
            "no-discharge",
            "do not discharge",
            "disable battery discharging",
            "battery must not discharge",
            "prohibit battery discharge",
            "must not discharge",
        )

    def no_discharge_build(text: str, ctx: InterpretationContext) -> dict:
        hours = _window(text) or []
        if not hours:
            raise ValueError("no_discharge note without parseable time window")
        return {
            "directive_type": "no_discharge_window",
            "hours": hours,
        }

    rules.append(
        MockRule("no_discharge_window", no_discharge_predicate, no_discharge_build)
    )

    # ---- Grid cap ---------------------------------------------------------
    def grid_predicate(text: str, ctx: InterpretationContext) -> bool:
        return _has(
            text,
            "grid import",
            "grid intake",
            "campus grid",
            "feeder",
            "transformer",
            "substation",
            "grid cap",
            "max_grid",
            "must not exceed",
            "must stay at or below",
            "must stay at or under",
            "capped",
        )

    def grid_build(text: str, ctx: InterpretationContext) -> dict:
        hours = _window(text) or []
        if not hours:
            raise ValueError("grid cap note without parseable time window")
        m = re.search(r"(\d+(?:\.\d+)?)\s*kwh", text.lower())
        if not m:
            raise ValueError("grid cap note without parseable kWh value")
        return {
            "directive_type": "max_grid_window",
            "hours": hours,
            "max_grid_kwh": float(m.group(1)),
        }

    rules.append(MockRule("max_grid_window", grid_predicate, grid_build))

    return rules


class MockInterpreter(LLMInterpreter):
    """Deterministic mock interpreter with a small rule set.

    This is intentionally simple. It exists to keep the test suite
    independent of any real provider; it must NEVER be selected for
    production use. The interpreter raises `LLMResponseFormatError`
    if its rules cannot produce a valid envelope for the input notes.
    """

    provider_name = "mock"
    prompt_version = INTERPRETER_PROMPT_VERSION

    def __init__(self, rules: Optional[List[MockRule]] = None) -> None:
        self._rules = rules if rules is not None else _default_rules()

    async def interpret(
        self, context: InterpretationContext
    ) -> InterpretationResult:
        # Simulate async behavior without blocking the loop.
        await asyncio.sleep(0)

        items = []
        for idx, note in enumerate(context.operator_notes):
            payload = None
            for rule in self._rules:
                try:
                    matched = bool(rule.predicate(note, context))
                except Exception:  # noqa: BLE001
                    matched = False
                if matched:
                    try:
                        payload = rule.build(note, context)
                    except Exception:  # noqa: BLE001
                        payload = None
                    if payload is not None:
                        break

            if payload is None:
                items.append(
                    {
                        "note_index": idx,
                        "applies": False,
                        "directive_type": "no_op",
                        "structured_adjustment": None,
                        "explanation": (
                            "This note does not affect today's energy "
                            "schedule."
                        ),
                    }
                )
            else:
                items.append(
                    {
                        "note_index": idx,
                        "applies": True,
                        "directive_type": payload["directive_type"],
                        "structured_adjustment": {
                            k: v
                            for k, v in payload.items()
                            if k != "directive_type"
                        },
                        "explanation": _mock_explanation(
                            payload["directive_type"]
                        ),
                    }
                )

        raw_text = json.dumps({"directive_interpretation": items})
        from app.schemas.llm import LLMInterpretationEnvelope

        envelope = LLMInterpretationEnvelope.model_validate_json(raw_text)
        return InterpretationResult(
            envelope=envelope,
            raw_text=raw_text,
            provider=self.provider_name,
            model="mock-rule-engine",
        )


def _mock_explanation(directive_type: str) -> str:
    return {
        "solar_reduction": (
            "Solar availability is reduced during the operator-specified "
            "maintenance window."
        ),
        "minimum_battery_reserve": (
            "Battery minimum reserve is raised during the operator-specified "
            "evening window."
        ),
        "no_charge_window": (
            "Battery charging is disabled during the operator-specified "
            "maintenance window."
        ),
        "no_discharge_window": (
            "Battery discharging is disabled during the operator-specified "
            "protection-testing window."
        ),
        "max_grid_window": (
            "Grid import is capped during the operator-specified feeder "
            "constraint window."
        ),
        "no_op": "This note does not affect today's energy schedule.",
    }.get(directive_type, "Operator note interpreted.")


def build_mock_interpreter() -> MockInterpreter:
    """Factory used by the FastAPI dependency system."""

    return MockInterpreter()


__all__ = ["MockInterpreter", "MockRule", "MockState", "build_mock_interpreter"]
