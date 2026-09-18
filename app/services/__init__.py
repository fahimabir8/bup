"""Service layer: composes LLM interpretation, validation, optimization,
post-processing, and replay validation into a single end-to-end action.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from app.config import (
    LLMConfig,
    Settings,
    get_settings,
)
from app.directives.applier import (
    apply_directives,
    detect_infeasible_preconditions,
)
from app.directives.validator import InterpretationValidationError
from app.llm.base import (
    InterpretationContext,
    InterpretationResult,
    LLMInterpreter,
)
from app.llm.interpreter import (
    LLMResponseFormatError,
    interpret_with,
)
from app.llm.mock import MockInterpreter
from app.llm.openai_compatible import (
    LLMConfigurationError,
    OpenAICompatibleInterpreter,
)
from app.optimization.model import EnergyScenario
from app.optimization.postprocess import (
    PostprocessContext,
    build_response,
)
from app.optimization.solver import (
    InfeasibleScenarioError,
    SolverFailureError,
    solve,
)
from app.schemas.directives import DirectiveTypeEnum
from app.schemas.llm import LLMInterpretationEnvelope
from app.schemas.request import OptimizeEnergyRequest
from app.schemas.response import OptimizeEnergyResponse
from app.validation.response_validator import (
    ResponseValidationReport,
    validate_response,
)

_LOGGER = logging.getLogger(__name__)


class OptimizationRequestError(ValueError):
    """Raised for client-attributable failures (HTTP 4xx)."""


class OptimizationInternalError(RuntimeError):
    """Raised for server-attributable failures (HTTP 5xx)."""


@dataclass
class _CacheEntry:
    envelope: LLMInterpretationEnvelope
    raw_text: str
    provider: str
    model: str
    created_at: float
    last_accessed: float


@dataclass
class InterpretationCache:
    """Tiny TTL+LRU cache for LLM interpretation results."""

    max_entries: int = 256
    ttl_seconds: int = 300
    entries: dict[str, _CacheEntry] = field(default_factory=dict)

    @staticmethod
    def _fingerprint_key(
        notes: list[str],
        capacity_kwh: float,
        model: str,
        prompt_version: str,
    ) -> str:
        digest = hashlib.sha256()
        for note in notes:
            digest.update(b"n\x00")
            digest.update(note.strip().lower().encode("utf-8"))
        digest.update(b"c\x00")
        digest.update(f"{capacity_kwh:.6f}".encode("utf-8"))
        digest.update(b"m\x00")
        digest.update(model.encode("utf-8"))
        digest.update(b"v\x00")
        digest.update(prompt_version.encode("utf-8"))
        return digest.hexdigest()

    def get(
        self,
        notes: list[str],
        capacity_kwh: float,
        model: str,
        prompt_version: str,
    ) -> Optional[InterpretationResult]:
        if self.max_entries <= 0:
            return None
        key = self._fingerprint_key(notes, capacity_kwh, model, prompt_version)
        entry = self.entries.get(key)
        if entry is None:
            return None
        now = time.monotonic()
        if now - entry.created_at > self.ttl_seconds:
            self.entries.pop(key, None)
            return None
        entry.last_accessed = now
        return InterpretationResult(
            envelope=entry.envelope,
            raw_text=entry.raw_text,
            provider=entry.provider,
            model=entry.model,
            cache_hit=True,
        )

    def put(
        self,
        notes: list[str],
        capacity_kwh: float,
        model: str,
        prompt_version: str,
        result: InterpretationResult,
    ) -> None:
        if self.max_entries <= 0:
            return
        now = time.monotonic()
        key = self._fingerprint_key(notes, capacity_kwh, model, prompt_version)
        self.entries[key] = _CacheEntry(
            envelope=result.envelope,
            raw_text=result.raw_text,
            provider=result.provider,
            model=result.model,
            created_at=now,
            last_accessed=now,
        )
        if len(self.entries) > self.max_entries:
            # Drop least-recently-used entries.
            ordered = sorted(
                self.entries.items(), key=lambda kv: kv[1].last_accessed
            )
            for k, _ in ordered[: len(self.entries) - self.max_entries]:
                self.entries.pop(k, None)


def build_interpreter(
    llm_cfg: LLMConfig, settings: Settings
) -> LLMInterpreter:
    if llm_cfg.provider.lower() == "mock":
        return MockInterpreter()
    if llm_cfg.provider.lower() in {"openai_compatible", "openai"}:
        return OpenAICompatibleInterpreter(
            base_url=llm_cfg.base_url,
            api_key=llm_cfg.api_key,
            model=llm_cfg.model,
            timeout_seconds=llm_cfg.timeout_seconds,
        )
    raise LLMConfigurationError(
        f"Unknown LLM provider: {llm_cfg.provider}"
    )


@dataclass
class OptimizeService:
    """Coordinates LLM interpretation, directives, optimization, and replay."""

    interpreter: LLMInterpreter
    cache: InterpretationCache
    settings: Settings

    @classmethod
    def from_settings(cls, settings: Settings) -> "OptimizeService":
        interpreter = build_interpreter(settings.llm, settings)
        cache = InterpretationCache(
            max_entries=settings.llm.cache_max_entries,
            ttl_seconds=settings.llm.cache_ttl_seconds,
        )
        return cls(interpreter=interpreter, cache=cache, settings=settings)

    @classmethod
    def with_mock(cls, settings: Settings) -> "OptimizeService":
        return cls(
            interpreter=MockInterpreter(),
            cache=InterpretationCache(max_entries=0, ttl_seconds=0),
            settings=settings,
        )

    async def optimize(
        self, request: OptimizeEnergyRequest
    ) -> OptimizeEnergyResponse:
        """Run the full optimization pipeline."""

        timings: dict[str, float] = {}
        start = time.perf_counter()

        # ----- 1. LLM interpretation -------------------------------------
        llm_start = time.perf_counter()
        context = self._build_context(request)
        cached = None
        if self.settings.server.enable_cache:
            cached = self.cache.get(
                request.operator_notes,
                request.battery.capacity_kwh,
                self.settings.llm.model or self.interpreter.provider_name,
                self.settings.llm.prompt_version,
            )
        if cached is not None:
            result = cached
        else:
            result = await self.interpreter.interpret(context)
            if self.settings.server.enable_cache:
                self.cache.put(
                    request.operator_notes,
                    request.battery.capacity_kwh,
                    result.model,
                    self.settings.llm.prompt_version,
                    result,
                )
        timings["llm_ms"] = (time.perf_counter() - llm_start) * 1000.0

        # ----- 2. Validator + applier -----------------------------------
        try:
            _, validated = await interpret_with(self.interpreter, context)
        except LLMResponseFormatError as exc:
            raise OptimizationRequestError(str(exc)) from exc
        except InterpretationValidationError as exc:
            raise OptimizationRequestError(str(exc)) from exc

        interpretations = self._build_response_interpretations(
            request.operator_notes, result.envelope
        )
        # If the LLM envelope was valid, interpretations equals validated directives.
        # If envelope was invalid, validated has the validated entries; we surface
        # only the response-ready items from the envelope to keep the API contract.

        effective = apply_directives(
            request.hours, request.battery, validated
        )
        precondition_errors = detect_infeasible_preconditions(
            request.hours, request.battery, effective
        )
        if precondition_errors:
            raise OptimizationRequestError(
                "; ".join(precondition_errors)
            )

        scenario = EnergyScenario.build(
            scenario_id=request.scenario_id,
            hours=request.hours,
            battery=request.battery,
            effective=effective,
        )

        # ----- 3. Optimization ------------------------------------------
        opt_start = time.perf_counter()
        try:
            raw = solve(scenario)
        except InfeasibleScenarioError as exc:
            raise OptimizationRequestError(str(exc)) from exc
        except SolverFailureError as exc:
            raise OptimizationInternalError(str(exc)) from exc
        timings["opt_ms"] = (time.perf_counter() - opt_start) * 1000.0

        # ----- 4. Postprocess + replay validation -----------------------
        post_start = time.perf_counter()
        ctx = PostprocessContext(
            scenario_id=request.scenario_id,
            hours=request.hours,
            battery=request.battery,
            interpretations=interpretations,
        )
        response, plan = build_response(ctx, raw, self.settings.numerical)

        report = validate_response(
            plan=plan,
            hours=request.hours,
            battery=request.battery,
            interpretations=interpretations,
        )
        if not report.valid:
            raise OptimizationInternalError(
                "replay validation failed: "
                + "; ".join(report.errors)
            )

        if (
            abs(report.total_grid_kwh - response.total_grid_kwh) > 1e-3
            or abs(report.total_cost_bdt - response.total_cost_bdt) > 1e-3
            or abs(report.peak_grid_kwh - response.peak_grid_kwh) > 1e-3
        ):
            raise OptimizationInternalError(
                "totals disagree between response and recalculated plan"
            )

        timings["post_ms"] = (time.perf_counter() - post_start) * 1000.0
        timings["total_ms"] = (time.perf_counter() - start) * 1000.0

        _LOGGER.info(
            "optimization success scenario_id=%s notes=%d llm_ms=%.1f opt_ms=%.1f "
            "post_ms=%.1f total_ms=%.1f cost=%.2f",
            request.scenario_id,
            len(request.operator_notes),
            timings["llm_ms"],
            timings["opt_ms"],
            timings["post_ms"],
            timings["total_ms"],
            response.total_cost_bdt,
        )
        return response

    def _build_context(
        self, request: OptimizeEnergyRequest
    ) -> InterpretationContext:
        hours_sorted = sorted(request.hours, key=lambda h: h.hour)
        peak_demand = max(h.demand_kwh for h in hours_sorted)
        peak_solar = max(h.solar_kwh for h in hours_sorted)
        peak_tariff = max(h.tariff_bdt_per_kwh for h in hours_sorted)
        return InterpretationContext(
            scenario_id=request.scenario_id,
            operator_notes=list(request.operator_notes),
            battery_capacity_kwh=request.battery.capacity_kwh,
            peak_demand_kwh=float(peak_demand),
            peak_solar_kwh=float(peak_solar),
            peak_tariff_bdt_per_kwh=float(peak_tariff),
            initial_battery_energy_kwh=request.battery.initial_energy_kwh,
            base_minimum_energy_kwh=request.battery.minimum_energy_kwh,
        )

    def _build_response_interpretations(
        self,
        notes: list[str],
        envelope: LLMInterpretationEnvelope,
    ) -> list:
        # Preserve API contract (single item per note, deterministic order).
        items = sorted(
            envelope.directive_interpretation, key=lambda x: x.note_index
        )
        from app.schemas.directives import DirectiveInterpretationItem

        out: list[DirectiveInterpretationItem] = []
        for item in items:
            out.append(
                DirectiveInterpretationItem(
                    note_index=item.note_index,
                    applies=item.applies,
                    directive_type=DirectiveTypeEnum(item.directive_type),
                    structured_adjustment=item.structured_adjustment,
                    explanation=item.explanation,
                )
            )
        return out


__all__ = [
    "InterpretationCache",
    "OptimizeService",
    "OptimizationInternalError",
    "OptimizationRequestError",
]
