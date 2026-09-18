"""/optimize-energy endpoint."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from app.config import get_settings
from app.schemas.request import OptimizeEnergyRequest
from app.schemas.response import OptimizeEnergyResponse
from app.services.optimize_service import OptimizeService
from app.services import (
    OptimizationInternalError,
    OptimizationRequestError,
)

_LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["optimize"])


def _service_dep(request: Request) -> OptimizeService:
    svc = getattr(request.app.state, "optimize_service", None)
    if svc is None:
        raise RuntimeError("optimize_service not initialized")
    return svc


@router.post(
    "/optimize-energy",
    response_model=OptimizeEnergyResponse,
    status_code=status.HTTP_200_OK,
)
async def optimize_energy(
    payload: Dict[str, Any],
    service: OptimizeService = Depends(_service_dep),
) -> OptimizeEnergyResponse:
    """Run the full optimization pipeline for one scenario."""

    try:
        request = OptimizeEnergyRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_safe_validation_message(exc),
        ) from exc

    try:
        return await service.optimize(request)
    except OptimizationRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except OptimizationInternalError as exc:
        _LOGGER.exception("optimization failed for scenario %s",
                          request.scenario_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal optimization failure",
        ) from exc


def _safe_validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Invalid request payload"
    first = errors[0]
    loc = ".".join(str(p) for p in first.get("loc", []))
    msg = first.get("msg", "invalid")
    if loc:
        return f"Invalid request: {loc}: {msg}"
    return f"Invalid request: {msg}"


__all__ = ["router"]
