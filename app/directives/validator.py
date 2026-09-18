"""Deterministic validation of LLM-produced interpretations.

The validator runs AFTER the LLM (or mock) has produced a structural
JSON envelope and parsed it into Pydantic models. It enforces the
invariants that the optimizer must be able to trust:

* coverage (one interpretation per input note, indices contiguous)
* allowed directive types
* applies/adjustment semantics for no_op vs. other directives
* hours invariant (integers, in 0..23, unique, ascending)
* numeric range checks for factor/reserve/grid cap

The validator never reinterprets the LLM; it only judges validity.
Failures are returned as a structured report.
"""

from __future__ import annotations

from typing import List, Sequence

from app.directives.models import InterpretationValidationReport
from app.schemas.directives import (
    BatteryReserveAdjustment,
    DirectiveTypeEnum,
    GridCapAdjustment,
    HoursOnlyAdjustment,
    SolarReductionAdjustment,
    ValidatedDirective,
    ValidatedDirectiveSet,
)
from app.schemas.llm import LLMDirectiveInterpretationItem


class InterpretationValidationError(ValueError):
    """Raised when the deterministic interpretation checks fail.

    The message is safe to surface to API clients.
    """


def _check_hours(
    report: InterpretationValidationReport,
    note_index: int,
    hours_raw,
) -> List[int] | None:
    """Verify hours invariant; return the cleaned list or None."""

    if hours_raw is None:
        report.add(note_index, "missing_hours", "hours missing")
        return None

    if not isinstance(hours_raw, list) or not hours_raw:
        report.add(note_index, "invalid_hours", "hours must be a non-empty list")
        return None

    cleaned: List[int] = []
    seen = set()
    for h in hours_raw:
        # Strict integer check: bool subclasses int but isn't valid.
        if isinstance(h, bool) or not isinstance(h, int):
            report.add(
                note_index,
                "invalid_hour_type",
                "hours must contain integer values",
            )
            return None
        if h < 0 or h > 23:
            report.add(
                note_index,
                "hour_out_of_range",
                f"hour {h} outside 0..23",
            )
            return None
        if h in seen:
            report.add(
                note_index, "duplicate_hour", f"duplicate hour {h}"
            )
            return None
        seen.add(h)
        cleaned.append(h)

    if cleaned != sorted(cleaned):
        report.add(
            note_index, "hours_not_sorted", "hours must be ascending"
        )
        return None

    return cleaned


def _validate_solar_reduction(
    report: InterpretationValidationReport,
    item: LLMDirectiveInterpretationItem,
    adj,
) -> ValidatedDirective | None:
    cleaned_hours = _check_hours(report, item.note_index, adj.get("hours"))
    if cleaned_hours is None:
        return None

    factor_raw = adj.get("factor")
    if factor_raw is None or isinstance(factor_raw, bool) or not isinstance(
        factor_raw, (int, float)
    ):
        report.add(
            item.note_index,
            "missing_factor",
            "solar_reduction requires numeric factor",
        )
        return None
    try:
        adj_obj = SolarReductionAdjustment(hours=cleaned_hours, factor=float(factor_raw))
    except Exception as exc:  # noqa: BLE001
        report.add(
            item.note_index,
            "invalid_factor",
            f"solar_reduction factor invalid: {exc}",
        )
        return None

    return ValidatedDirective(
        note_index=item.note_index,
        directive_type=DirectiveTypeEnum.SOLAR_REDUCTION,
        applies=True,
        adjustment={
            "hours": adj_obj.hours,
            "factor": adj_obj.factor,
        },
    )


def _validate_battery_reserve(
    report: InterpretationValidationReport,
    item: LLMDirectiveInterpretationItem,
    adj,
) -> ValidatedDirective | None:
    cleaned_hours = _check_hours(report, item.note_index, adj.get("hours"))
    if cleaned_hours is None:
        return None

    min_raw = adj.get("minimum_energy_kwh")
    if min_raw is None or isinstance(min_raw, bool) or not isinstance(
        min_raw, (int, float)
    ):
        report.add(
            item.note_index,
            "missing_minimum",
            "minimum_battery_reserve requires numeric minimum_energy_kwh",
        )
        return None

    try:
        adj_obj = BatteryReserveAdjustment(
            hours=cleaned_hours,
            minimum_energy_kwh=float(min_raw),
        )
    except Exception as exc:  # noqa: BLE001
        report.add(
            item.note_index,
            "invalid_minimum",
            f"minimum_battery_reserve invalid: {exc}",
        )
        return None

    return ValidatedDirective(
        note_index=item.note_index,
        directive_type=DirectiveTypeEnum.MINIMUM_BATTERY_RESERVE,
        applies=True,
        adjustment={
            "hours": adj_obj.hours,
            "minimum_energy_kwh": adj_obj.minimum_energy_kwh,
        },
    )


def _validate_hours_only(
    report: InterpretationValidationReport,
    item: LLMDirectiveInterpretationItem,
    adj,
    dtype: DirectiveTypeEnum,
) -> ValidatedDirective | None:
    cleaned_hours = _check_hours(report, item.note_index, adj.get("hours"))
    if cleaned_hours is None:
        return None
    try:
        adj_obj = HoursOnlyAdjustment(hours=cleaned_hours)
    except Exception as exc:  # noqa: BLE001
        report.add(
            item.note_index,
            f"invalid_{dtype.value}",
            f"{dtype.value} invalid: {exc}",
        )
        return None
    return ValidatedDirective(
        note_index=item.note_index,
        directive_type=dtype,
        applies=True,
        adjustment={"hours": adj_obj.hours},
    )


def _validate_grid_cap(
    report: InterpretationValidationReport,
    item: LLMDirectiveInterpretationItem,
    adj,
) -> ValidatedDirective | None:
    cleaned_hours = _check_hours(report, item.note_index, adj.get("hours"))
    if cleaned_hours is None:
        return None

    cap_raw = adj.get("max_grid_kwh")
    if cap_raw is None or isinstance(cap_raw, bool) or not isinstance(
        cap_raw, (int, float)
    ):
        report.add(
            item.note_index,
            "missing_max_grid",
            "max_grid_window requires numeric max_grid_kwh",
        )
        return None
    try:
        adj_obj = GridCapAdjustment(
            hours=cleaned_hours,
            max_grid_kwh=float(cap_raw),
        )
    except Exception as exc:  # noqa: BLE001
        report.add(
            item.note_index,
            "invalid_grid_cap",
            f"max_grid_window invalid: {exc}",
        )
        return None
    return ValidatedDirective(
        note_index=item.note_index,
        directive_type=DirectiveTypeEnum.MAX_GRID_WINDOW,
        applies=True,
        adjustment={
            "hours": adj_obj.hours,
            "max_grid_kwh": adj_obj.max_grid_kwh,
        },
    )


def validate_directive_interpretation(
    items: Sequence[LLMDirectiveInterpretationItem],
    expected_note_count: int,
) -> ValidatedDirectiveSet:
    """Validate the LLM-produced interpretation envelope deterministically.

    Returns a `ValidatedDirectiveSet` on success. Raises
    `InterpretationValidationError` on failure with a safe message.
    """

    report = InterpretationValidationReport()

    # ---- Coverage check
    if len(items) != expected_note_count:
        raise InterpretationValidationError(
            f"interpretation must contain exactly {expected_note_count} "
            f"entries (one per operator note); got {len(items)}"
        )

    indices = [item.note_index for item in items]
    if indices != list(range(expected_note_count)):
        raise InterpretationValidationError(
            "interpretation note_index values must be exactly "
            "0..N-1 in ascending order"
        )
    if len(set(indices)) != len(indices):
        raise InterpretationValidationError(
            "interpretation note_index values must be unique"
        )

    validated: List[ValidatedDirective] = []

    for item in items:
        try:
            dtype = DirectiveTypeEnum(item.directive_type)
        except ValueError:
            report.add(
                item.note_index,
                "unsupported_directive",
                f"directive_type '{item.directive_type}' is not supported",
            )
            continue

        if dtype == DirectiveTypeEnum.NO_OP:
            if item.applies is not False:
                report.add(
                    item.note_index,
                    "no_op_applies_must_be_false",
                    "no_op must have applies == false",
                )
                continue
            if item.structured_adjustment is not None:
                report.add(
                    item.note_index,
                    "no_op_adjustment_must_be_null",
                    "no_op must have structured_adjustment == null",
                )
                continue
            if not item.explanation or not isinstance(item.explanation, str):
                report.add(
                    item.note_index,
                    "missing_explanation",
                    "explanation must be a non-empty string",
                )
                continue
            # Persist a synthetic validated entry to preserve ordering.
            validated.append(
                ValidatedDirective(
                    note_index=item.note_index,
                    directive_type=DirectiveTypeEnum.NO_OP,
                    applies=False,
                    adjustment={},
                )
            )
            continue

        # Non no_op: applies must be True and adjustment must be present.
        if item.applies is not True:
            report.add(
                item.note_index,
                "applies_must_be_true",
                f"{dtype.value} must have applies == true",
            )
            continue
        if item.structured_adjustment is None:
            report.add(
                item.note_index,
                "missing_adjustment",
                f"{dtype.value} must have a structured_adjustment",
            )
            continue
        if not isinstance(item.structured_adjustment, dict):
            report.add(
                item.note_index,
                "invalid_adjustment_type",
                f"{dtype.value} structured_adjustment must be an object",
            )
            continue
        if not item.explanation or not isinstance(item.explanation, str):
            report.add(
                item.note_index,
                "missing_explanation",
                "explanation must be a non-empty string",
            )
            continue

        adj = item.structured_adjustment

        if dtype == DirectiveTypeEnum.SOLAR_REDUCTION:
            vd = _validate_solar_reduction(report, item, adj)
        elif dtype == DirectiveTypeEnum.MINIMUM_BATTERY_RESERVE:
            vd = _validate_battery_reserve(report, item, adj)
        elif dtype == DirectiveTypeEnum.NO_CHARGE_WINDOW:
            vd = _validate_hours_only(
                report, item, adj, DirectiveTypeEnum.NO_CHARGE_WINDOW
            )
        elif dtype == DirectiveTypeEnum.NO_DISCHARGE_WINDOW:
            vd = _validate_hours_only(
                report, item, adj, DirectiveTypeEnum.NO_DISCHARGE_WINDOW
            )
        elif dtype == DirectiveTypeEnum.MAX_GRID_WINDOW:
            vd = _validate_grid_cap(report, item, adj)
        else:  # pragma: no cover - enum exhaustive
            report.add(
                item.note_index,
                "unsupported_directive",
                f"directive_type '{dtype.value}' is not supported",
            )
            continue

        if vd is not None:
            validated.append(vd)

    if not report.is_ok:
        first = report.first_message()
        raise InterpretationValidationError(
            f"interpretation validation failed: {first}"
        )

    # Sort by note_index for deterministic ordering regardless of LLM output order.
    validated.sort(key=lambda d: d.note_index)
    return ValidatedDirectiveSet(directives=validated)


__all__ = [
    "InterpretationValidationError",
    "validate_directive_interpretation",
]
