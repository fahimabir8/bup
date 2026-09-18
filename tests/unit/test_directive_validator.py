"""Unit tests for the deterministic directive validator."""

from __future__ import annotations

import pytest

from app.directives.validator import (
    InterpretationValidationError,
    validate_directive_interpretation,
)
from app.schemas.directives import (
    BatteryReserveAdjustment,
    DirectiveTypeEnum,
    GridCapAdjustment,
    HoursOnlyAdjustment,
    SolarReductionAdjustment,
)
from app.schemas.llm import LLMDirectiveInterpretationItem


def _solar(note_index, hours, factor):
    return LLMDirectiveInterpretationItem(
        note_index=note_index,
        applies=True,
        directive_type="solar_reduction",
        structured_adjustment={"hours": hours, "factor": factor},
        explanation="test",
    )


def _no_op(note_index):
    return LLMDirectiveInterpretationItem(
        note_index=note_index,
        applies=False,
        directive_type="no_op",
        structured_adjustment=None,
        explanation="not relevant",
    )


def test_coverage_must_match() -> None:
    items = [_solar(0, [12, 13], 0.5)]
    with pytest.raises(InterpretationValidationError):
        validate_directive_interpretation(items, expected_note_count=2)


def test_indices_must_be_contiguous() -> None:
    items = [
        _solar(0, [12, 13], 0.5),
        LLMDirectiveInterpretationItem(
            note_index=2,
            applies=True,
            directive_type="solar_reduction",
            structured_adjustment={"hours": [12, 13], "factor": 0.5},
            explanation="x",
        ),
    ]
    with pytest.raises(InterpretationValidationError):
        validate_directive_interpretation(items, expected_note_count=2)


def test_unsupported_directive_rejected() -> None:
    # The schema rejects unknown directive types at construction time. The
    # validator's own check is redundant with Pydantic but kept as defence in
    # depth.
    with pytest.raises(Exception):
        LLMDirectiveInterpretationItem(
            note_index=0,
            applies=True,
            directive_type="explode_battery",
            structured_adjustment={"hours": [12, 13], "factor": 0.5},
            explanation="x",
        )

    # Direct call into the validator with a mocked LLMDirectiveInterpretationItem
    # bypasses Pydantic to confirm the validator itself enforces the rule.
    class _Bypass:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    bypass = _Bypass(
        note_index=0,
        applies=True,
        directive_type="explode_battery",
        structured_adjustment={"hours": [12, 13], "factor": 0.5},
        explanation="x",
    )
    with pytest.raises(InterpretationValidationError):
        validate_directive_interpretation([bypass], expected_note_count=1)


def test_no_op_requires_applies_false_and_null_adjustment() -> None:
    items = [
        LLMDirectiveInterpretationItem(
            note_index=0,
            applies=True,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="x",
        )
    ]
    with pytest.raises(InterpretationValidationError):
        validate_directive_interpretation(items, expected_note_count=1)


def test_factor_out_of_range_rejected() -> None:
    items = [_solar(0, [12, 13], 1.5)]
    with pytest.raises(InterpretationValidationError):
        validate_directive_interpretation(items, expected_note_count=1)


def test_hours_invalid_range_rejected() -> None:
    items = [_solar(0, [24], 0.5)]
    with pytest.raises(InterpretationValidationError):
        validate_directive_interpretation(items, expected_note_count=1)


def test_hours_not_unique_rejected() -> None:
    items = [_solar(0, [12, 12], 0.5)]
    with pytest.raises(InterpretationValidationError):
        validate_directive_interpretation(items, expected_note_count=1)


def test_hours_not_ascending_rejected() -> None:
    items = [_solar(0, [13, 12], 0.5)]
    with pytest.raises(InterpretationValidationError):
        validate_directive_interpretation(items, expected_note_count=1)


def test_solar_happy_path() -> None:
    items = [_solar(0, [12, 13], 0.5)]
    validated = validate_directive_interpretation(items, expected_note_count=1)
    assert validated.directives[0].directive_type == DirectiveTypeEnum.SOLAR_REDUCTION
    assert validated.directives[0].adjustment["factor"] == 0.5


def test_reserve_happy_path() -> None:
    items = [
        LLMDirectiveInterpretationItem(
            note_index=0,
            applies=True,
            directive_type="minimum_battery_reserve",
            structured_adjustment={"hours": [18, 19], "minimum_energy_kwh": 100.0},
            explanation="x",
        )
    ]
    validated = validate_directive_interpretation(items, expected_note_count=1)
    assert validated.directives[0].directive_type == DirectiveTypeEnum.MINIMUM_BATTERY_RESERVE
    assert validated.directives[0].adjustment["minimum_energy_kwh"] == 100.0


def test_no_charge_happy_path() -> None:
    items = [
        LLMDirectiveInterpretationItem(
            note_index=0,
            applies=True,
            directive_type="no_charge_window",
            structured_adjustment={"hours": [2, 3, 4]},
            explanation="x",
        )
    ]
    validated = validate_directive_interpretation(items, expected_note_count=1)
    assert validated.directives[0].directive_type == DirectiveTypeEnum.NO_CHARGE_WINDOW
    assert validated.directives[0].adjustment["hours"] == [2, 3, 4]


def test_no_discharge_happy_path() -> None:
    items = [
        LLMDirectiveInterpretationItem(
            note_index=0,
            applies=True,
            directive_type="no_discharge_window",
            structured_adjustment={"hours": [18, 19]},
            explanation="x",
        )
    ]
    validated = validate_directive_interpretation(items, expected_note_count=1)
    assert validated.directives[0].directive_type == DirectiveTypeEnum.NO_DISCHARGE_WINDOW


def test_grid_cap_happy_path() -> None:
    items = [
        LLMDirectiveInterpretationItem(
            note_index=0,
            applies=True,
            directive_type="max_grid_window",
            structured_adjustment={"hours": [17, 18], "max_grid_kwh": 100.0},
            explanation="x",
        )
    ]
    validated = validate_directive_interpretation(items, expected_note_count=1)
    assert validated.directives[0].directive_type == DirectiveTypeEnum.MAX_GRID_WINDOW


def test_mixed_notes() -> None:
    items = [
        _solar(0, [12, 13], 0.5),
        _no_op(1),
        LLMDirectiveInterpretationItem(
            note_index=2,
            applies=True,
            directive_type="no_charge_window",
            structured_adjustment={"hours": [14, 15]},
            explanation="x",
        ),
    ]
    validated = validate_directive_interpretation(items, expected_note_count=3)
    types = [d.directive_type for d in validated.directives]
    assert types == [
        DirectiveTypeEnum.SOLAR_REDUCTION,
        DirectiveTypeEnum.NO_OP,
        DirectiveTypeEnum.NO_CHARGE_WINDOW,
    ]


def test_adjustment_schemas_strict() -> None:
    # SolarReductionAdjustment directly
    with pytest.raises(Exception):
        SolarReductionAdjustment(hours=[12], factor=1.1)
    with pytest.raises(Exception):
        SolarReductionAdjustment(hours=[12, 12], factor=0.5)
    with pytest.raises(Exception):
        SolarReductionAdjustment(hours=[13, 12], factor=0.5)
    with pytest.raises(Exception):
        BatteryReserveAdjustment(hours=[18], minimum_energy_kwh=-1)
    with pytest.raises(Exception):
        HoursOnlyAdjustment(hours=[-1])
    with pytest.raises(Exception):
        GridCapAdjustment(hours=[18], max_grid_kwh=-1)


def test_applies_must_be_true_for_non_no_op() -> None:
    items = [
        LLMDirectiveInterpretationItem(
            note_index=0,
            applies=False,
            directive_type="solar_reduction",
            structured_adjustment={"hours": [12, 13], "factor": 0.5},
            explanation="x",
        )
    ]
    with pytest.raises(InterpretationValidationError):
        validate_directive_interpretation(items, expected_note_count=1)


def test_missing_adjustment_for_non_no_op() -> None:
    items = [
        LLMDirectiveInterpretationItem(
            note_index=0,
            applies=True,
            directive_type="solar_reduction",
            structured_adjustment=None,
            explanation="x",
        )
    ]
    with pytest.raises(InterpretationValidationError):
        validate_directive_interpretation(items, expected_note_count=1)
