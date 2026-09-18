"""OpenAI-compatible LLM interpreter implementation.

Works with any chat-completions endpoint that accepts the OpenAI schema,
including OpenAI, Ollama, vLLM, LM Studio, and various hosted gateways.
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


class LLMConfigurationError(RuntimeError):
    """Raised when the provider is misconfigured."""


class LLMRemoteError(RuntimeError):
    """Raised on transport or HTTP errors from the provider."""


class OpenAICompatibleInterpreter(LLMInterpreter):
    """Async OpenAI-compatible chat-completions interpreter."""

    provider_name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 12.0,
        max_retries: int = 1,
    ) -> None:
        if not base_url:
            raise LLMConfigurationError(
                "LLM_BASE_URL is required for the OpenAI-compatible provider"
            )
        if not model:
            raise LLMConfigurationError(
                "LLM_MODEL is required for the OpenAI-compatible provider"
            )

        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max(0, max_retries)

    async def interpret(
        self, context: InterpretationContext
    ) -> InterpretationResult:
        url = f"{self._base_url}/chat/completions"
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
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
            # Encourage providers to return JSON natively when supported.
            "response_format": {"type": "json_object"},
        }

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout
                ) as client:
                    response = await client.post(
                        url, json=body, headers=headers
                    )
                if response.status_code >= 500:
                    raise LLMRemoteError(
                        f"provider returned {response.status_code}"
                    )
                if response.status_code >= 400:
                    # Hard failure, no retry.
                    raise LLMRemoteError(
                        f"provider returned {response.status_code}"
                    )
                data = response.json()
                break
            except (httpx.HTTPError, LLMRemoteError) as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    raise LLMRemoteError(
                        f"provider call failed after "
                        f"{attempt + 1} attempt(s): {exc}"
                    ) from exc
                # Brief backoff before retry.
                await asyncio.sleep(0.2 * (attempt + 1))
        else:  # pragma: no cover - loop always breaks or raises
            raise LLMRemoteError(
                f"provider call failed: {last_exc}"
            )

        raw_text = _extract_message_text(data)
        envelope = LLMInterpretationEnvelope.model_validate_json(raw_text)
        return InterpretationResult(
            envelope=envelope,
            raw_text=raw_text,
            provider=self.provider_name,
            model=self._model,
        )


def _extract_message_text(payload: Dict[str, Any]) -> str:
    """Extract the assistant message text from an OpenAI-style payload."""

    try:
        choices = payload["choices"]
    except (KeyError, TypeError) as exc:
        raise LLMRemoteError(
            "provider response missing 'choices' field"
        ) from exc
    if not choices:
        raise LLMRemoteError("provider returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if content is None:
        raise LLMRemoteError("provider response missing 'message.content'")
    if isinstance(content, list):
        # OpenAI's newer style -- join text parts.
        parts = []
        for part in content:
            if isinstance(part, dict) and "text" in part:
                parts.append(str(part["text"]))
        content = "".join(parts)
    if not isinstance(content, str):
        raise LLMRemoteError(
            "provider response content is not text"
        )
    return content


__all__ = [
    "LLMConfigurationError",
    "LLMRemoteError",
    "OpenAICompatibleInterpreter",
]