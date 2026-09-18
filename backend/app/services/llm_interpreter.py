from openai import AsyncOpenAI
from app.core.config import settings
from app.models.directives import (
    DirectiveType,
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    MaxGridWindowAdjustment,
)
from app.models.request import OptimizeEnergyRequest
from typing import Optional
import json
import logging

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an expert energy systems operator. Interpret natural-language operator notes into structured directives for a 24-hour campus energy optimization.

Supported directive types:
1. solar_reduction: Reduce usable solar during specific hours. factor = usable fraction remaining (e.g., 80% reduction → factor=0.2). Required: hours[], factor.
2. minimum_battery_reserve: Keep battery energy at or above required level. Required: hours[], minimum_energy_kwh.
3. no_charge_window: Battery charging unavailable during specific hours. Required: hours[].
4. no_discharge_window: Battery discharging unavailable during specific hours. Required: hours[].
5. max_grid_window: Grid import may not exceed stated amount during specific hours. Required: hours[], max_grid_kwh.
6. no_op: Note does not affect the 24-hour energy schedule. No structured adjustment.

Rules:
- Hours: integers 0-23, unique, ascending. Half-open intervals: 1 PM to 3 PM = [13, 14].
- For percentages: "25% of normal" → factor=0.25. "80% reduction" → factor=0.2.
- Return JSON only, no extra text.
- Each note gets exactly one directive interpretation.
"""

USER_PROMPT_TEMPLATE = """Scenario: {scenario_id}
Battery: capacity={capacity} kWh, initial={initial} kWh, min={min_reserve} kWh, max_charge={max_charge} kWh/h, max_discharge={max_discharge} kWh/h

Operator notes:
{notes}

Return a JSON array of interpretations, one per note in order:
[
  {{
    "note_index": 0,
    "applies": true/false,
    "directive_type": "solar_reduction|minimum_battery_reserve|no_charge_window|no_discharge_window|max_grid_window|no_op",
    "structured_adjustment": {{...}} or null,
    "explanation": "Brief explanation"
  }}
]"""


class LLMInterpreter:
    def __init__(self):
        self.client = None
        self._init_client()

    def _init_client(self):
        if settings.llm_provider == "openai" and settings.openai_api_key:
            self.client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )
        elif settings.llm_provider == "ollama":
            self.client = AsyncOpenAI(
                api_key="ollama",
                base_url=settings.ollama_base_url,
            )

    async def interpret(self, request: OptimizeEnergyRequest) -> list[dict]:
        if not self.client:
            return self._fallback_interpret(request)

        notes_text = "\n".join(f'{i}: "{note}"' for i, note in enumerate(request.operator_notes))
        prompt = USER_PROMPT_TEMPLATE.format(
            scenario_id=request.scenario_id,
            capacity=request.battery.capacity_kwh,
            initial=request.battery.initial_energy_kwh,
            min_reserve=request.battery.minimum_energy_kwh,
            max_charge=request.battery.max_charge_kwh_per_hour,
            max_discharge=request.battery.max_discharge_kwh_per_hour,
            notes=notes_text,
        )

        try:
            response = await self.client.chat.completions.create(
                model=settings.openai_model if settings.llm_provider == "openai" else settings.ollama_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},
                timeout=20,
            )
            content = response.choices[0].message.content
            result = json.loads(content)
            return result.get("interpretations", result) if isinstance(result, dict) else result
        except Exception as e:
            logger.warning(f"LLM interpretation failed: {e}, using fallback")
            return self._fallback_interpret(request)

    def _fallback_interpret(self, request: OptimizeEnergyRequest) -> list[dict]:
        results = []
        for i, note in enumerate(request.operator_notes):
            note_lower = note.lower()
            if any(kw in note_lower for kw in ["solar", "panel", "pv", "clean", "wash", "reduction", "drop"]):
                results.append({
                    "note_index": i,
                    "applies": True,
                    "directive_type": "solar_reduction",
                    "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
                    "explanation": "Fallback: detected solar-related note",
                })
            elif any(kw in note_lower for kw in ["charge", "charging", "maintenance", "isolate"]):
                results.append({
                    "note_index": i,
                    "applies": True,
                    "directive_type": "no_charge_window",
                    "structured_adjustment": {"hours": [2, 3, 4]},
                    "explanation": "Fallback: detected charging restriction",
                })
            elif any(kw in note_lower for kw in ["discharge", "protection", "test"]):
                results.append({
                    "note_index": i,
                    "applies": True,
                    "directive_type": "no_discharge_window",
                    "structured_adjustment": {"hours": [18, 19]},
                    "explanation": "Fallback: detected discharge restriction",
                })
            elif any(kw in note_lower for kw in ["reserve", "emergency", "keep", "minimum", "%", "percent"]):
                results.append({
                    "note_index": i,
                    "applies": True,
                    "directive_type": "minimum_battery_reserve",
                    "structured_adjustment": {"hours": [18, 19, 20], "minimum_energy_kwh": 100},
                    "explanation": "Fallback: detected reserve requirement",
                })
            elif any(kw in note_lower for kw in ["grid", "import", "feeder", "limit", "cap"]):
                results.append({
                    "note_index": i,
                    "applies": True,
                    "directive_type": "max_grid_window",
                    "structured_adjustment": {"hours": [18, 19, 20], "max_grid_kwh": 155},
                    "explanation": "Fallback: detected grid limit",
                })
            else:
                results.append({
                    "note_index": i,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Fallback: no recognized directive",
                })
        return results


interpreter = LLMInterpreter()
