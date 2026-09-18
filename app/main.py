"""FastAPI application factory and lifespan management."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.health import router as health_router
from app.api.optimize import router as optimize_router
from app.config import (
    get_settings,
    require_production_provider,
    reset_settings_cache,
)
from app.services.optimize_service import OptimizeService


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings.server.log_level)

    if os.getenv("GRIDWISE_REQUIRE_PROD_PROVIDER", "").lower() in {"1", "true"}:
        require_production_provider(settings)

    if settings.llm.provider.lower() != "mock":
        # Production / real LLM provider: initialize eagerly so failures
        # surface at startup.
        try:
            service = OptimizeService.from_settings(settings)
        except Exception:  # noqa: BLE001
            logging.exception("Failed to initialize LLM interpreter")
            raise
    else:
        service = OptimizeService.with_mock(settings)

    app.state.optimize_service = service
    app.state.settings = settings
    logging.info(
        "GridWise ready: provider=%s model=%s",
        settings.llm.provider,
        settings.llm.model or "(default)",
    )
    try:
        yield
    finally:
        # Reset cached settings between test runs.
        reset_settings_cache()


def create_app() -> FastAPI:
    app = FastAPI(
        title="GridWise",
        version=__version__,
        description="LLM-Assisted Smart Campus Energy Optimization API",
        lifespan=lifespan,
    )

    # Permissive CORS so the bundled static frontend (typically served
    # from a different port during development) can call the API
    # without a reverse proxy. Tighten allow_origins for production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(optimize_router)

    @app.exception_handler(Exception)
    async def _safe_exception_handler(_, exc: Exception):  # noqa: ANN001
        logging.exception("Unhandled error")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app


app = create_app()


__all__ = ["app", "create_app", "lifespan"]
