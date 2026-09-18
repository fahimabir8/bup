from fastapi import APIRouter, HTTPException
from app.models.request import OptimizeEnergyRequest
from app.models.response import OptimizeEnergyResponse

router = APIRouter()


@router.post("", response_model=OptimizeEnergyResponse)
async def optimize_energy(request: OptimizeEnergyRequest):
    # TODO: Implement LLM interpretation + guardrails + optimizer
    raise HTTPException(status_code=501, detail="Not implemented yet")
