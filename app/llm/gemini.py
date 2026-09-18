"""Native Google Gemini LLM interpreter implementation.

Talks to Gemini's native ``generateContent`` REST endpoint and forces
structured JSON output via ``response_mime_type=application/json``.
This is a first-class provider in the GridWise LLM layer — it does
NOT reuse the OpenAI-compatible plumbing because the project no longer
depends on OpenAI.

Endpoint contract:

    POST {base_url}/v1beta/models/{model}:generateContent?key={api_key}
    Body:
        {
          "system_instruction": {"parts": [{"text": "..."}]},
          "contents": [{"role": "user", "parts": [{"text": "..."}]}],
          "generationConfig": {
            "temperature": 0,
            "response_mime_type": "application/json"
          }
        }

The default ``base_url`` is ``https://generativelanguage.googleapis.com``
(the public Google AI Studio endpoint). The interpreter strips a
trailing slash from the configured value and appends the path itself.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

from app.llm.base import (
    InterpretationContext,
    InterpretationResult,
    LLMInterpreter,
)
from app.llm.prompts import SYSTEM_PROMPT, build_user_payload
from app.schemas.llm import LLMInterpretationEnvelope

_LOGGER = logging.getLogger(__name__)

DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"


class LLMConfigurationError(RuntimeError):
    """Raised when the provider is misconfigured."""


class LLMRemoteError(RuntimeError):
    """Raised on transport or HTTP errors from the provider."""


class GeminiInterpreter(LLMInterpreter):
    """Async Google Gemini ``generateContent`` interpreter.

    Parameters
    ----------
    api_key:
        Google AI Studio API key. Required.
    model:
        Gemini model id, e.g. ``gemini-2.0-flash`` or ``gemini-1.5-pro``.
    base_url:
        Root URL of the Generative Language API. Defaults to Google's
        hosted endpoint. Override only when routing through a proxy.
    timeout_seconds:
        Per-request HTTP timeout.
    max_retries:
        Number of retries on transient errors (5xx and network errors).
    """

    provider_name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_GEMINI_BASE_URL,
        timeout_seconds: float = 12.0,
        max_retries: int = 1,
    ) -> None:
        if not api_key:
            raise LLMConfigurationError(
                "GEMINI_API_KEY (or LLM_API_KEY) is required for the "
                "gemini provider"
            )
        if not model:
            raise LLMConfigurationError(
                "LLM_MODEL is required for the gemini provider "
                "(e.g. 'gemini-2.0-flash')"
            )

        self._api_key = api_key
        # Strip any trailing slashes / ``/v1beta`` the user may include.
        self._base_url = base_url.rstrip("/")
        # Avoid double-versioning if the user supplied ``.../v1beta``.
        for suffix in ("/v1beta", "/v1"):
            if self._base_url.endswith(suffix):
                self._base_url = self._base_url[: -len(suffix)]
                break
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max(0, max_retries)

    async def interpret(
        self, context: InterpretationContext
    ) -> InterpretationResult:
        url = (
            f"{self._base_url}/v1beta/models/{self._model}:generateContent"
        )
        user_payload = build_user_payload(
            context.operator_notes,
            {
                "scenario_id": context.scenario_id,
                "battery_capacity_kwh": context.battery_capacity_kwh,
                "initial_battery_energy_kwh": context.initial_battery_energy_kwh,
                "base_minimum_energy_kwh": context.base_minimum_energy_kwh,
                "peak_demand_kwh": context.peak_demand_kwh,
                "peak_solar_kwh": context.peak_solar_kwh,
                "peak_tariff_bdt_per_kwh": context.peak_tariff_bdt_per_kwh,
            },
        )

        body: Dict[str, Any] = {
            "system_instruction": {
                "parts": [{"text": SYSTEM_PROMPT}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_payload}],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                # Ask Gemini to return JSON natively. This is honored on
                # the public generateContent endpoint for current models.
                "response_mime_type": "application/json",
            },
        }

        params = {"key": self._api_key}
        headers = {"Content-Type": "application/json"}

        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout
                ) as client:
                    response = await client.post(
                        url, params=params, json=body, headers=headers
                    )
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    raise LLMRemoteError(
                        f"gemini call failed after {attempt + 1} "
                        f"attempt(s): {exc}"
                    ) from exc
                await asyncio.sleep(0.2 * (attempt + 1))
                continue

            if response.status_code >= 500:
                last_exc = LLMRemoteError(
                    f"gemini returned {response.status_code}"
                )
                if attempt >= self._max_retries:
                    raise last_exc
                await asyncio.sleep(0.2 * (attempt + 1))
                continue

            if response.status_code >= 400:
                # Hard failure: surface the provider's error body.
                snippet = response.text[:300]
                raise LLMRemoteError(
                    f"gemini returned {response.status_code}: {snippet}"
                )

            try:
                data = response.json()
            except Exception as exc:  # noqa: BLE001
                raise LLMRemoteError(
                    f"gemini response was not JSON: {exc}"
                ) from exc
            break
        else:  # pragma: no cover - loop always breaks or raises
            raise LLMRemoteError(
                f"gemini call failed: {last_exc}"
            )

        raw_text = _extract_gemini_text(data)
        # Validate locally so downstream code can rely on the parsed shape.
        envelope = LLMInterpretationEnvelope.model_validate_json(raw_text)
        return InterpretationResult(
            envelope=envelope,
            raw_text=raw_text,
            provider=self.provider_name,
            model=self._model,
        )


def _extract_gemini_text(payload: Dict[str, Any]) -> str:
    """Extract the assistant text from a Gemini ``generateContent`` payload.

    Expected shape::

        {
          "candidates": [
            {
              "content": {"parts": [{"text": "..."}], "role": "model"},
              "finishReason": "STOP"
            }
          ]
        }
    """

    try:
        candidates = payload["candidates"]
    except (KeyError, TypeError) as exc:
        raise LLMRemoteError(
            "gemini response missing 'candidates' field"
        ) from exc

    if not candidates:
        raise LLMRemoteError("gemini returned no candidates")

    candidate = candidates[0] or {}
    # Surface safety blocks / quota messages instead of silently failing.
    finish_reason = candidate.get("finishReason")
    if finish_reason and finish_reason not in {"STOP", "MAX_TOKENS"}:
        raise LLMRemoteError(
            f"gemini candidate finished with reason: {finish_reason}"
        )

    content = candidate.get("content") or {}
    parts = content.get("parts")
    if not parts:
        raise LLMRemoteError("gemini response missing 'content.parts'")

    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict) and "text" in part and part["text"]:
            chunks.append(str(part["text"]))
    if not chunks:
        raise LLMRemoteError("gemini response contained no text parts")
    return "".join(chunks)


__all__ = [
    "DEFAULT_GEMINI_BASE_URL",
    "DEFAULT_GEMINI_MODEL",
    "GeminiInterpreter",
    "LLMConfigurationError",
    "LLMRemoteError",
]
