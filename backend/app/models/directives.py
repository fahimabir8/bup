from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional
from typing_extensions import Annotated
from enum import Enum


class DirectiveType(str, Enum):
    SOLAR_REDUCTION = "solar_reduction"
    MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
    NO_CHARGE_WINDOW = "no_charge_window"
    NO_DISCHARGE_WINDOW = "no_discharge_window"
    MAX_GRID_WINDOW = "max_grid_window"
    NO_OP = "no_op"


class SolarReductionAdjustment(BaseModel):
    hours: Annotated[list[int], Field(min_length=1)]
    factor: Annotated[float, Field(ge=0, le=1)]

    @field_validator("hours")
    @classmethod
    def validate_hours(cls, v: list[int]) -> list[int]:
        if len(v) != len(set(v)):
            raise ValueError("hours must be unique")
        if any(not 0 <= h <= 23 for h in v):
            raise ValueError("hours must be between 0 and 23")
        if v != sorted(v):
            raise ValueError("hours must be in ascending order")
        return v


class MinimumBatteryReserveAdjustment(BaseModel):
    hours: Annotated[list[int], Field(min_length=1)]
    minimum_energy_kwh: Annotated[float, Field(ge=0)]

    @field_validator("hours")
    @classmethod
    def validate_hours(cls, v: list[int]) -> list[int]:
        if len(v) != len(set(v)):
            raise ValueError("hours must be unique")
        if any(not 0 <= h <= 23 for h in v):
            raise ValueError("hours must be between 0 and 23")
        if v != sorted(v):
            raise ValueError("hours must be in ascending order")
        return v


class NoChargeWindowAdjustment(BaseModel):
    hours: Annotated[list[int], Field(min_length=1)]

    @field_validator("hours")
    @classmethod
    def validate_hours(cls, v: list[int]) -> list[int]:
        if len(v) != len(set(v)):
            raise ValueError("hours must be unique")
        if any(not 0 <= h <= 23 for h in v):
            raise ValueError("hours must be between 0 and 23")
        if v != sorted(v):
            raise ValueError("hours must be in ascending order")
        return v


class NoDischargeWindowAdjustment(BaseModel):
    hours: Annotated[list[int], Field(min_length=1)]

    @field_validator("hours")
    @classmethod
    def validate_hours(cls, v: list[int]) -> list[int]:
        if len(v) != len(set(v)):
            raise ValueError("hours must be unique")
        if any(not 0 <= h <= 23 for h in v):
            raise ValueError("hours must be between 0 and 23")
        if v != sorted(v):
            raise ValueError("hours must be in ascending order")
        return v


class MaxGridWindowAdjustment(BaseModel):
    hours: Annotated[list[int], Field(min_length=1)]
    max_grid_kwh: Annotated[float, Field(ge=0)]

    @field_validator("hours")
    @classmethod
    def validate_hours(cls, v: list[int]) -> list[int]:
        if len(v) != len(set(v)):
            raise ValueError("hours must be unique")
        if any(not 0 <= h <= 23 for h in v):
            raise ValueError("hours must be between 0 and 23")
        if v != sorted(v):
            raise ValueError("hours must be in ascending order")
        return v


StructuredAdjustment = Annotated[
    SolarReductionAdjustment
    | MinimumBatteryReserveAdjustment
    | NoChargeWindowAdjustment
    | NoDischargeWindowAdjustment
    | MaxGridWindowAdjustment
    | None,
    Field(discriminator="directive_type"),
]


class DirectiveInterpretation(BaseModel):
    note_index: Annotated[int, Field(ge=0)]
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: Optional[
        SolarReductionAdjustment
        | MinimumBatteryReserveAdjustment
        | NoChargeWindowAdjustment
        | NoDischargeWindowAdjustment
        | MaxGridWindowAdjustment
    ] = None
    explanation: str = Field(min_length=1)

    @field_validator("structured_adjustment")
    @classmethod
    def validate_adjustment(cls, v, info) -> Optional[object]:
        directive_type = info.data.get("directive_type")
        applies = info.data.get("applies")

        if directive_type == DirectiveType.NO_OP:
            if applies:
                raise ValueError("no_op must have applies=false")
            if v is not None:
                raise ValueError("no_op must have structured_adjustment=null")
            return None

        if not applies:
            raise ValueError("non-no_op directives must have applies=true")
        if v is None:
            raise ValueError("non-no_op directives must have structured_adjustment")

        return v
