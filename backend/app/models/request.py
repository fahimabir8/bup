from pydantic import BaseModel, Field, field_validator
from typing import Literal
from typing_extensions import Annotated


class HourData(BaseModel):
    hour: Annotated[int, Field(ge=0, le=23)]
    demand_kwh: Annotated[float, Field(ge=0)]
    solar_kwh: Annotated[float, Field(ge=0)]
    tariff_bdt_per_kwh: Annotated[float, Field(ge=0)]

    @field_validator("hour")
    @classmethod
    def validate_hour(cls, v: int) -> int:
        if not 0 <= v <= 23:
            raise ValueError("hour must be between 0 and 23")
        return v


class BatteryData(BaseModel):
    capacity_kwh: Annotated[float, Field(gt=0)]
    initial_energy_kwh: Annotated[float, Field(ge=0)]
    minimum_energy_kwh: Annotated[float, Field(ge=0)]
    max_charge_kwh_per_hour: Annotated[float, Field(gt=0)]
    max_discharge_kwh_per_hour: Annotated[float, Field(gt=0)]

    @field_validator("initial_energy_kwh")
    @classmethod
    def validate_initial_energy(cls, v: float, info) -> float:
        if "capacity_kwh" in info.data and v > info.data["capacity_kwh"]:
            raise ValueError("initial_energy_kwh cannot exceed capacity_kwh")
        return v

    @field_validator("minimum_energy_kwh")
    @classmethod
    def validate_minimum_energy(cls, v: float, info) -> float:
        if "capacity_kwh" in info.data and v > info.data["capacity_kwh"]:
            raise ValueError("minimum_energy_kwh cannot exceed capacity_kwh")
        return v


class OptimizeEnergyRequest(BaseModel):
    scenario_id: str = Field(min_length=1)
    operator_notes: Annotated[list[str], Field(min_length=1, max_length=3)]
    hours: Annotated[list[HourData], Field(min_length=24, max_length=24)]
    battery: BatteryData

    @field_validator("hours")
    @classmethod
    def validate_hours(cls, v: list[HourData]) -> list[HourData]:
        if len(v) != 24:
            raise ValueError("hours must contain exactly 24 entries")
        hour_set = set(h.hour for h in v)
        if hour_set != set(range(24)):
            raise ValueError("hours must contain all integers 0-23 exactly once")
        return v

    @field_validator("operator_notes")
    @classmethod
    def validate_operator_notes(cls, v: list[str]) -> list[str]:
        for note in v:
            if not note.strip():
                raise ValueError("operator_notes cannot contain empty strings")
        return v
