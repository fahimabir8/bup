"""LLM interpreter protocol and shared types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol, runtime_checkable

from app.schemas.llm import LLMInterpretationEnvelope


@dataclass(frozen=True)
class InterpretationContext:
    """Inputs supplied to the LLM for one interpretation call."""

    scenario_id: str
    operator_notes: List[str]
    battery_capacity_kwh: float
    # Lightweight numeric context the LLM may use to reason about feasibility.
    peak_demand_kwh: float
    peak_solar_kwh: float
    peak_tariff_bdt_per_kwh: float
    initial_battery_energy_kwh: float
    base_minimum_energy_kwh: float


@dataclass(frozen=True)
class InterpretationResult:
    """Normalized output of an LLM call.

    `envelope` is the parsed Pydantic model. `raw_text` is the raw model
    output (only used for logs/debugging). `provider` and `model` describe
    who produced the output. `cache_hit` indicates whether the result was
    served from the cache.
    """

    envelope: LLMInterpretationEnvelope
    raw_text: str
    provider: str
    model: str
    cache_hit: bool = False


@runtime_checkable
class LLMInterpreter(Protocol):
    """The contract every LLM provider implementation must satisfy."""

    provider_name: str

    async def interpret(
        self,
        context: InterpretationContext,
    ) -> InterpretationResult:
        """Interpret the operator notes into a structured envelope."""


@runtime_checkable
class LLMInterpreterFactory(Protocol):
    """Factory used by the FastAPI dependency system."""

    def __call__(self) -> LLMInterpreter: ...


__all__ = [
    "InterpretationContext",
    "InterpretationResult",
    "LLMInterpreter",
    "LLMInterpreterFactory",
]


# Silence unused-import warnings for typing helpers.
_ = Optional
