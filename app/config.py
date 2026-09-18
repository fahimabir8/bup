"""Centralized configuration for GridWise.

All runtime configuration is sourced from environment variables.
Defaults are conservative and safe for production use, while still allowing
the project to run locally in development mode with the mock LLM.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional


# LLM prompt version is part of cache keys and observability
INTERPRETER_PROMPT_VERSION = "1.0"

# Name of the dotenv file the loader should read by default. Set the
# ``DOTENV_PATH`` env var to override (useful for tests).
_DOTENV_FILENAME = ".env"


def _load_dotenv(path: Optional[str] = None) -> None:
    """Populate ``os.environ`` from a ``.env`` file.

    Minimal implementation: only sets variables that are not already
    present in the environment, so explicit shell exports and Docker
    ``env_file`` always win. Handles ``KEY=value``, ``export KEY=value``,
    blank lines, and ``#`` comments. Quoted values have their quotes
    stripped; inline ``#`` comments are tolerated after a space.

    This avoids a runtime dependency on ``python-dotenv`` while still
    letting ``python -m uvicorn app.main:app`` pick up ``.env`` without
    requiring ``set -a; . ./.env; set +a`` shenanigans.
    """

    target = path or os.getenv("DOTENV_PATH")
    if not target:
        # Default: look for a .env in the current working directory or
        # the project root (the directory containing this package).
        cwd_candidate = Path.cwd() / _DOTENV_FILENAME
        if cwd_candidate.is_file():
            target = str(cwd_candidate)
        else:
            # ``app/`` lives at <project>/app; the project root is its parent.
            project_root = Path(__file__).resolve().parent.parent
            root_candidate = project_root / _DOTENV_FILENAME
            if root_candidate.is_file():
                target = str(root_candidate)

    if not target:
        return

    dotenv_path = Path(target)
    if not dotenv_path.is_file():
        return

    try:
        text = dotenv_path.read_text(encoding="utf-8")
    except OSError:
        return

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        # Drop inline comments after a whitespace-separated ``#``.
        if " #" in value:
            value = value.split(" #", 1)[0]
        value = value.strip()
        # Strip a single matching pair of surrounding quotes.
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {'"', "'"}
        ):
            value = value[1:-1]
        # Never overwrite an explicitly-set environment variable.
        if key not in os.environ:
            os.environ[key] = value


# Load .env at import time so configuration is consistent across
# uvicorn / pytest / direct script invocation. Idempotent and safe.
_load_dotenv()


def _getenv_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value is not None and value != "" else default


def _getenv_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _getenv_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _getenv_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LLMConfig:
    """Provider-agnostic LLM configuration.

    The ``provider`` field picks the implementation. Supported values
    are ``"gemini"``, ``"openai_compatible"``, and ``"mock"``. The
    remaining fields are only consumed by the network-backed providers;
    ``base_url`` is optional for Gemini (defaults to the public Google
    endpoint) and required for ``openai_compatible``.
    """

    provider: str = "gemini"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 12.0
    max_retries: int = 1
    cache_max_entries: int = 256
    cache_ttl_seconds: int = 300
    prompt_version: str = INTERPRETER_PROMPT_VERSION


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    enable_cache: bool = True


@dataclass(frozen=True)
class NumericalConfig:
    """Centralized numerical tolerance and rounding constants."""

    # The challenge accepts roughly 0.01 kWh / 0.01 BDT tolerance.
    # We use a slightly looser internal tolerance for the optimizer.
    abs_tolerance: float = 1e-3
    # Tolerance for active integer/binary indicator checks
    action_tolerance: float = 1e-4
    # Battery action ramp tolerance for "action select"
    action_select_tolerance: float = 1e-3
    # Final rounding precision for API outputs (kWh / BDT)
    output_precision: int = 4
    # Tolerance for "tiny value" normalization to 0.0
    zero_tolerance: float = 1e-6
    # Hard timeout for the optimizer in seconds
    solver_timeout_seconds: float = 25.0


@dataclass(frozen=True)
class Settings:
    llm: LLMConfig = field(default_factory=LLMConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    numerical: NumericalConfig = field(default_factory=NumericalConfig)

    @property
    def is_mock_llm(self) -> bool:
        return self.llm.provider.lower() == "mock"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _build_settings()


def _build_settings() -> Settings:
    provider = _getenv_str("LLM_PROVIDER", "gemini").lower()
    # Key precedence: GEMINI_API_KEY for the gemini provider, otherwise
    # fall back to the generic LLM_API_KEY. This lets users paste their
    # Google AI Studio key under its natural name.
    if provider == "gemini":
        api_key = _getenv_str("GEMINI_API_KEY", "") or _getenv_str(
            "LLM_API_KEY", ""
        )
    else:
        api_key = _getenv_str("LLM_API_KEY", "") or _getenv_str(
            "GEMINI_API_KEY", ""
        )

    llm = LLMConfig(
        provider=provider,
        base_url=_getenv_str("LLM_BASE_URL", "") or _getenv_str(
            "GEMINI_BASE_URL", ""
        ),
        api_key=api_key,
        model=_getenv_str("LLM_MODEL", ""),
        timeout_seconds=_getenv_float("LLM_TIMEOUT_SECONDS", 12.0),
        max_retries=_getenv_int("LLM_MAX_RETRIES", 1),
        cache_max_entries=_getenv_int("LLM_CACHE_MAX_ENTRIES", 256),
        cache_ttl_seconds=_getenv_int("LLM_CACHE_TTL_SECONDS", 300),
        prompt_version=INTERPRETER_PROMPT_VERSION,
    )
    server = ServerConfig(
        host=_getenv_str("APP_HOST", "0.0.0.0"),
        port=_getenv_int("APP_PORT", 8000),
        log_level=_getenv_str("APP_LOG_LEVEL", "info"),
        enable_cache=_getenv_bool("APP_ENABLE_CACHE", True),
    )
    numerical = NumericalConfig(
        abs_tolerance=_getenv_float("GRIDWISE_ABS_TOL", 1e-3),
        action_tolerance=_getenv_float("GRIDWISE_ACTION_TOL", 1e-4),
        action_select_tolerance=_getenv_float(
            "GRIDWISE_ACTION_SELECT_TOL", 1e-3
        ),
        output_precision=_getenv_int("GRIDWISE_OUTPUT_PRECISION", 4),
        zero_tolerance=_getenv_float("GRIDWISE_ZERO_TOL", 1e-6),
        solver_timeout_seconds=_getenv_float(
            "GRIDWISE_SOLVER_TIMEOUT", 25.0
        ),
    )
    return Settings(llm=llm, server=server, numerical=numerical)


def reset_settings_cache() -> None:
    """Reset cached settings; intended for tests."""

    get_settings.cache_clear()


def require_production_provider(settings: Settings) -> None:
    """Raise if the settings would silently use the mock provider.

    Production deployments must opt-out of the mock by setting
    LLM_PROVIDER to something other than "mock".
    """

    if settings.is_mock_llm:
        raise RuntimeError(
            "LLM_PROVIDER=mock is not allowed in production. "
            "Set LLM_PROVIDER to a real provider (e.g. openai_compatible)."
        )


__all__ = [
    "INTERPRETER_PROMPT_VERSION",
    "LLMConfig",
    "ServerConfig",
    "NumericalConfig",
    "Settings",
    "get_settings",
    "reset_settings_cache",
    "require_production_provider",
]
