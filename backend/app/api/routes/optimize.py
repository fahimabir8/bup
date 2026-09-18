from fastapi import APIRouter, HTTPException, Request
from app.models.request import OptimizeEnergyRequest
from app.models.response import OptimizeEnergyResponse, DirectiveInterpretationResponse, HourlyPlanEntry
from app.services.llm_interpreter import interpreter
from app.services.guardrails import validate_all_interpretations, GuardrailsValidationError
from app.services.optimizer import solve_energy_optimization, generate_plan_summary, OptimizationError
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=OptimizeEnergyResponse)
async def optimize_energy(request: OptimizeEnergyRequest):
    try:
        raw_interpretations = await interpreter.interpret(request)
    except Exception as e:
        logger.error(f"LLM interpretation error: {e}")
        raise HTTPException(status_code=500, detail="Failed to interpret operator notes")

    try:
        validated_directives = validate_all_interpretations(raw_interpretations, request)
    except GuardrailsValidationError as e:
        logger.warning(f"Guardrails validation failed: {e}")
        raise HTTPException(status_code=422, detail=f"Invalid directive interpretation: {e}")

    try:
        hourly_plan, total_grid, total_cost, peak_grid = solve_energy_optimization(request, validated_directives)
    except OptimizationError as e:
        logger.error(f"Optimization failed: {e}")
        raise HTTPException(status_code=500, detail=f"Optimization failed: {e}")

    plan_summary = generate_plan_summary(request, validated_directives, hourly_plan)

    directive_responses = []
    for d in validated_directives:
        adj = d["structured_adjustment"]
        if adj is not None:
            from app.models.directives import (
                SolarReductionAdjustment,
                MinimumBatteryReserveAdjustment,
                NoChargeWindowAdjustment,
                NoDischargeWindowAdjustment,
                MaxGridWindowAdjustment,
            )
            adj_type = d["directive_type"]
            if adj_type.value == "solar_reduction":
                adj_obj = SolarReductionAdjustment(**adj)
            elif adj_type.value == "minimum_battery_reserve":
                adj_obj = MinimumBatteryReserveAdjustment(**adj)
            elif adj_type.value == "no_charge_window":
                adj_obj = NoChargeWindowAdjustment(**adj)
            elif adj_type.value == "no_discharge_window":
                adj_obj = NoDischargeWindowAdjustment(**adj)
            elif adj_type.value == "max_grid_window":
                adj_obj = MaxGridWindowAdjustment(**adj)
            else:
                adj_obj = None
        else:
            adj_obj = None

        directive_responses.append(DirectiveInterpretationResponse(
            note_index=d["note_index"],
            applies=d["applies"],
            directive_type=d["directive_type"],
            structured_adjustment=adj_obj,
            explanation=d["explanation"],
        ))

    return OptimizeEnergyResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=directive_responses,
        hourly_plan=[HourlyPlanEntry(**h) for h in hourly_plan],
        total_grid_kwh=total_grid,
        total_cost_bdt=total_cost,
        peak_grid_kwh=peak_grid,
        plan_summary=plan_summary,
    )
