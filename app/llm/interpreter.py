"""High-level interpreter that ties together LLM output, JSON parsing,
and deterministic validation.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

from app.directives.validator import (
    InterpretationValidationError,
    validate_directive_interpretation,
)
from app.llm.base import (
    InterpretationContext,
    InterpretationResult,
    LLMInterpreter,
)
from app.schemas.directives import ValidatedDirectiveSet
from app.schemas.llm import LLMInterpretationEnvelope


_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$",
    re.IGNORECASE | re.DOTALL,
)


class LLMResponseFormatError(ValueError):
    """Raised when the LLM output cannot be parsed into the expected shape."""


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    match = _JSON_FENCE_RE.match(text)
    if match:
        return match.group(1).strip()
    return text


def parse_llm_output(raw_text: str) -> LLMInterpretationEnvelope:
    """Parse the raw LLM output into a `LLMInterpretationEnvelope`.

    Accepts fenced and unfenced JSON. Raises `LLMResponseFormatError`
    on any structural problem.
    """

    cleaned = _strip_code_fence(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMResponseFormatError(
            f"LLM output is not valid JSON: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise LLMResponseFormatError(
            "LLM output top-level must be an object"
        )
    items = data.get("directive_interpretation")
    if items is None:
        # Accept {"items": ...} style as a fallback.
        items = data.get("interpretations")
    if not isinstance(items, list):
        raise LLMResponseFormatError(
            "LLM output must contain 'directive_interpretation' list"
        )

    try:
        envelope = LLMInterpretationEnvelope.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        raise LLMResponseFormatError(
            f"LLM output failed schema validation: {exc}"
        ) from exc
    return envelope


async def interpret_with(
    interpreter: LLMInterpreter,
    context: InterpretationContext,
) -> tuple[InterpretationResult, ValidatedDirectiveSet]:
    """Run the interpreter once and validate its output deterministically."""

    result = await interpreter.interpret(context)
    envelope = parse_llm_output(result.raw_text)
    if result.envelope != envelope:  # type: ignore[comparison-overlap]
        # Provider may have already returned the parsed envelope.
        # Use the one we parsed locally to keep validation strict.
        pass
    validated = validate_directive_interpretation(
        envelope.directive_interpretation,
        expected_note_count=len(context.operator_notes),
    )
    return result, validated


__all__ = [
    "LLMResponseFormatError",
    "interpret_with",
    "parse_llm_output",
]


# Silence unused-import warnings.
_ = (Optional, List)
