from app.models.directives import (
    DirectiveType,
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    MaxGridWindowAdjustment,
)
from app.models.request import OptimizeEnergyRequest
from app.models.request import BatteryData
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class GuardrailsValidationError(Exception):
    pass


def validate_interpretation(
    interpretation: dict,
    request: OptimizeEnergyRequest,
) -> dict:
    note_index = interpretation.get("note_index")
    applies = interpretation.get("applies")
    directive_type = interpretation.get("directive_type")
    structured_adjustment = interpretation.get("structured_adjustment")
    explanation = interpretation.get("explanation", "")

    if note_index is None:
        raise GuardrailsValidationError("Missing note_index")

    if not isinstance(applies, bool):
        raise GuardrailsValidationError("applies must be boolean")

    try:
        directive_type = DirectiveType(directive_type)
    except ValueError:
        raise GuardrailsValidationError(f"Invalid directive_type: {directive_type}")

    if directive_type == DirectiveType.NO_OP:
        if applies:
            raise GuardrailsValidationError("no_op must have applies=false")
        if structured_adjustment is not None:
            raise GuardrailsValidationError("no_op must have structured_adjustment=null")
        return {
            "note_index": note_index,
            "applies": False,
            "directive_type": DirectiveType.NO_OP,
            "structured_adjustment": None,
            "explanation": explanation or "This note does not affect today's energy schedule.",
        }

    if not applies:
        raise GuardrailsValidationError("non-no_op directives must have applies=true")

    if structured_adjustment is None:
        raise GuardrailsValidationError("non-no_op directives must have structured_adjustment")

    validated_adjustment = _validate_structured_adjustment(
        directive_type, structured_adjustment, request.battery
    )

    return {
        "note_index": note_index,
        "applies": True,
        "directive_type": directive_type,
        "structured_adjustment": validated_adjustment,
        "explanation": explanation,
    }


def _validate_structured_adjustment(
    directive_type: DirectiveType,
    adjustment: dict,
    battery: BatteryData,
) -> dict:
    hours = adjustment.get("hours", [])

    if not hours:
        raise GuardrailsValidationError("hours array cannot be empty")

    if len(hours) != len(set(hours)):
        raise GuardrailsValidationError("hours must be unique")

    if any(not isinstance(h, int) or h < 0 or h > 23 for h in hours):
        raise GuardrailsValidationError("hours must be integers 0-23")

    if hours != sorted(hours):
        raise GuardrailsValidationError("hours must be in ascending order")

    if directive_type == DirectiveType.SOLAR_REDUCTION:
        factor = adjustment.get("factor")
        if factor is None:
            raise GuardrailsValidationError("solar_reduction requires factor")
        if not isinstance(factor, (int, float)) or factor < 0 or factor > 1:
            raise GuardrailsValidationError("factor must be between 0 and 1")
        return SolarReductionAdjustment(hours=hours, factor=factor).model_dump()

    elif directive_type == DirectiveType.MINIMUM_BATTERY_RESERVE:
        min_energy = adjustment.get("minimum_energy_kwh")
        if min_energy is None:
            raise GuardrailsValidationError("minimum_battery_reserve requires minimum_energy_kwh")
        if not isinstance(min_energy, (int, float)) or min_energy < 0:
            raise GuardrailsValidationError("minimum_energy_kwh must be non-negative")
        if min_energy > battery.capacity_kwh:
            raise GuardrailsValidationError("minimum_energy_kwh cannot exceed battery capacity")
        return MinimumBatteryReserveAdjustment(hours=hours, minimum_energy_kwh=min_energy).model_dump()

    elif directive_type == DirectiveType.NO_CHARGE_WINDOW:
        return NoChargeWindowAdjustment(hours=hours).model_dump()

    elif directive_type == DirectiveType.NO_DISCHARGE_WINDOW:
        return NoDischargeWindowAdjustment(hours=hours).model_dump()

    elif directive_type == DirectiveType.MAX_GRID_WINDOW:
        max_grid = adjustment.get("max_grid_kwh")
        if max_grid is None:
            raise GuardrailsValidationError("max_grid_window requires max_grid_kwh")
        if not isinstance(max_grid, (int, float)) or max_grid < 0:
            raise GuardrailsValidationError("max_grid_kwh must be non-negative")
        return MaxGridWindowAdjustment(hours=hours, max_grid_kwh=max_grid).model_dump()

    else:
        raise GuardrailsValidationError(f"Unknown directive_type: {directive_type}")


def validate_all_interpretations(
    interpretations: list[dict],
    request: OptimizeEnergyRequest,
) -> list[dict]:
    if len(interpretations) != len(request.operator_notes):
        raise GuardrailsValidationError(
            f"Expected {len(request.operator_notes)} interpretations, got {len(interpretations)}"
        )

    validated = []
    seen_indices = set()

    for interp in interpretations:
        note_index = interp.get("note_index")
        if note_index in seen_indices:
            raise GuardrailsValidationError(f"Duplicate note_index: {note_index}")
        seen_indices.add(note_index)

        validated.append(validate_interpretation(interp, request))

    expected_indices = set(range(len(request.operator_notes)))
    if seen_indices != expected_indices:
        missing = expected_indices - seen_indices
        raise GuardrailsValidationError(f"Missing note_indices: {sorted(missing)}")

    return validated
