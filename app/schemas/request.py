"""Request schema for /optimize-energy.

These models are the structural contract between callers and the service.
We validate structure with Pydantic and apply additional semantic
checks via the `validate_request_payload` helper.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HourlyInput(BaseModel):
    """Inputs for a single hour."""

    model_config = ConfigDict(extra="forbid")

    hour: int = Field(..., ge=0, le=23, description="Hour of the day, 0..23")
    demand_kwh: float = Field(
        ..., ge=0, description="Electrical demand in kWh"
    )
    solar_kwh: float = Field(
        ..., ge=0, description="Solar forecast in kWh"
    )
    tariff_bdt_per_kwh: float = Field(
        ..., ge=0, description="Electricity tariff in BDT/kWh"
    )


class BatteryInput(BaseModel):
    """Battery configuration."""

    model_config = ConfigDict(extra="forbid")

    capacity_kwh: float = Field(..., gt=0, description="Battery capacity")
    initial_energy_kwh: float = Field(
        ..., ge=0, description="State of charge at hour 0"
    )
    minimum_energy_kwh: float = Field(
        ..., ge=0, description="Base minimum reserve"
    )
    max_charge_kwh_per_hour: float = Field(
        ..., ge=0, description="Maximum per-hour charge"
    )
    max_discharge_kwh_per_hour: float = Field(
        ..., ge=0, description="Maximum per-hour discharge"
    )


class OptimizeEnergyRequest(BaseModel):
    """Top-level request payload."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., min_length=1)
    operator_notes: List[str] = Field(..., min_length=1, max_length=3)
    hours: List[HourlyInput] = Field(..., min_length=24, max_length=24)
    battery: BatteryInput

    @field_validator("scenario_id", mode="before")
    @classmethod
    def _validate_scenario_id(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("scenario_id must be a string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("scenario_id must be a non-empty string")
        return stripped

    @field_validator("operator_notes")
    @classmethod
    def _validate_operator_notes(cls, value: List[str]) -> List[str]:
        if not isinstance(value, list):
            raise ValueError("operator_notes must be a list")
        if not (1 <= len(value) <= 3):
            raise ValueError(
                "operator_notes must contain 1, 2, or 3 non-empty strings"
            )
        cleaned: List[str] = []
        for idx, note in enumerate(value):
            if not isinstance(note, str):
                raise ValueError(f"operator_notes[{idx}] must be a string")
            stripped = note.strip()
            if not stripped:
                raise ValueError(
                    f"operator_notes[{idx}] must be a non-empty string"
                )
            cleaned.append(stripped)
        return cleaned

    @model_validator(mode="after")
    def _validate_hours(self) -> "OptimizeEnergyRequest":
        hours = self.hours
        if len(hours) != 24:
            raise ValueError("hours must contain exactly 24 entries")

        seen = set()
        for entry in hours:
            if entry.hour in seen:
                raise ValueError(
                    "hours must contain unique integers from 0 to 23"
                )
            seen.add(entry.hour)
        if seen != set(range(24)):
            raise ValueError(
                "hours must cover the entire 24-hour horizon 0..23"
            )
        return self


def validate_request_payload(payload: Dict[str, Any]) -> OptimizeEnergyRequest:
    """Parse and validate a raw request payload.

    Raises pydantic.ValidationError on failure. Returns the parsed
    request on success. The helper exists so callers can use a single
    import line regardless of where the validation occurs.
    """

    return OptimizeEnergyRequest.model_validate(payload)


__all__ = [
    "BatteryInput",
    "HourlyInput",
    "OptimizeEnergyRequest",
    "validate_request_payload",
]
