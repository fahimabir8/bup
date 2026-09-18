from fastapi import FastAPI, HTTPException
from app.models import OptimizeEnergyRequest, OptimizeEnergyResponse
from app.interpreter import interpret_operator_notes
from app.optimizer import solve_gridwise_optimization

app = FastAPI(
    title="GridWise Microgrid Energy Optimization Service",
    description="LLM-Assisted Microgrid Optimizer for BUP CSE Fest 2026 Preliminary",
    version="2.0"
)


@app.get("/")
def read_root():
    return {
        "service": "GridWise Energy Optimizer",
        "status": "healthy",
        "endpoint": "POST /optimize-energy"
    }


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/optimize-energy", response_model=OptimizeEnergyResponse)
def optimize_energy(request: OptimizeEnergyRequest):
    try:
        # 1. Interpret natural-language operator notes into structured directives
        directive_interpretations = interpret_operator_notes(
            operator_notes=request.operator_notes,
            battery_capacity=request.battery.capacity_kwh
        )

        # 2. Solve LP optimization model given inputs & interpreted directives
        response = solve_gridwise_optimization(
            request=request,
            directive_interpretations=directive_interpretations
        )

        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
