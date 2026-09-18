"""Pydantic schemas for LLM outputs.

These models are what we expect the LLM to produce. They are intentionally
minimalistic: we only care about the `directive_interpretation` envelope.
The actual interpretation items share the ontology enum from
`app.schemas.directives`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.directives import DirectiveTypeEnum

# Re-declare the literal for clarity in structured LLM responses.
DirectiveTypeLiteral = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]


class LLMDirectiveInterpretationItem(BaseModel):
    """One interpretation entry produced by the LLM."""

    model_config = ConfigDict(extra="allow")

    note_index: int = Field(..., ge=0)
    applies: bool
    directive_type: DirectiveTypeLiteral
    structured_adjustment: Optional[Dict[str, Any]] = None
    explanation: str = Field(..., min_length=1)


class LLMInterpretationEnvelope(BaseModel):
    """Top-level envelope returned by the LLM."""

    model_config = ConfigDict(extra="ignore")

    directive_interpretation: List[LLMDirectiveInterpretationItem]


__all__ = [
    "DirectiveTypeLiteral",
    "LLMDirectiveInterpretationItem",
    "LLMInterpretationEnvelope",
]


# Compat: re-export the enum from directives so consumers only import schemas
__all__ += ["DirectiveTypeEnum"]
