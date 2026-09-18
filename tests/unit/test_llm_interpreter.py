"""Unit tests for LLM output parsing."""

from __future__ import annotations

import pytest

from app.llm.interpreter import (
    LLMResponseFormatError,
    parse_llm_output,
)


def test_parse_unfenced_json() -> None:
    raw = '{"directive_interpretation": [{"note_index": 0, "applies": true, "directive_type": "solar_reduction", "structured_adjustment": {"hours": [12, 13], "factor": 0.5}, "explanation": "x"}]}'
    env = parse_llm_output(raw)
    assert env.directive_interpretation[0].directive_type == "solar_reduction"


def test_parse_fenced_json() -> None:
    raw = '```json\n{"directive_interpretation": []}\n```'
    env = parse_llm_output(raw)
    assert env.directive_interpretation == []


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(LLMResponseFormatError):
        parse_llm_output("not json")


def test_parse_missing_envelope_raises() -> None:
    with pytest.raises(LLMResponseFormatError):
        parse_llm_output('{"foo": []}')


def test_parse_items_not_list_raises() -> None:
    with pytest.raises(LLMResponseFormatError):
        parse_llm_output(
            '{"directive_interpretation": "not-a-list"}'
        )


def test_parse_unknown_fields_ignored() -> None:
    raw = (
        '{"extra": 1, "directive_interpretation": [], "meta": "x"}'
    )
    env = parse_llm_output(raw)
    assert env.directive_interpretation == []