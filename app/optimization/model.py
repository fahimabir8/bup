"""Internal data model for the optimization layer.

This module wraps the request inputs and the EffectiveScenario into a
typed `EnergyScenario`. Everything downstream (MILP model, postprocess,
replay) consumes this single canonical type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.schemas.directives import EffectiveScenario
from app.schemas.request import BatteryInput, HourlyInput


@dataclass
class EnergyScenario:
    """A normalized, internally-consistent view of one 24-hour scenario."""

    scenario_id: str
    hours: List[HourlyInput] = field(default_factory=list)
    battery: BatteryInput = None  # type: ignore[assignment]
    effective: EffectiveScenario = None  # type: ignore[assignment]

    @classmethod
    def build(
        cls,
        scenario_id: str,
        hours: List[HourlyInput],
        battery: BatteryInput,
        effective: EffectiveScenario,
    ) -> "EnergyScenario":
        if len(hours) != 24:
            raise ValueError("hours must contain 24 entries")
        return cls(
            scenario_id=scenario_id,
            hours=hours,
            battery=battery,
            effective=effective,
        )


__all__ = ["EnergyScenario"]
