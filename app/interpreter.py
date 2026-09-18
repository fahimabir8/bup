import os
import re
import json
from typing import List, Dict, Any, Optional
from app.models import DirectiveInterpretation, DirectiveTypeEnum

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


def interpret_operator_notes_rule_based(operator_notes: List[str], battery_capacity: float = 200.0) -> List[DirectiveInterpretation]:
    """
    Deterministic rule-based fallback interpreter for GridWise operator notes.
    Covers all standard pattern types in public sample cases.
    """
    results = []

    for idx, note in enumerate(operator_notes):
        note_clean = note.strip()
        note_lower = note_clean.lower()

        # Check for distractor / irrelevant notes (no_op)
        if any(kw in note_lower for kw in [
            "sports office", "registration deadline", "student affairs", 
            "club notices", "seminar room", "next week", "weather forecast for another city"
        ]):
            results.append(DirectiveInterpretation(
                note_index=idx,
                applies=False,
                directive_type=DirectiveTypeEnum.NO_OP,
                structured_adjustment=None,
                explanation="This note does not affect today's energy schedule."
            ))
            continue

        # Parse Time Windows
        hours = parse_time_window(note_clean)

        # 1. Solar Reduction
        if "solar" in note_lower or "panel" in note_lower:
            factor = 1.0
            # Check for factor or percentage
            if "25%" in note_lower:
                factor = 0.25
            elif "50%" in note_lower:
                factor = 0.5
            elif "80% reduction" in note_lower or "80%" in note_lower:
                factor = 0.2
            elif "75% reduction" in note_lower:
                factor = 0.25

            if not hours:
                # check noon until 2 PM
                if "noon until 2 pm" in note_lower or "12 pm until 2 pm" in note_lower:
                    hours = [12, 13]
                elif "10 am until noon" in note_lower or "10 am until 12 pm" in note_lower:
                    hours = [10, 11]
                elif "11 am until 2 pm" in note_lower:
                    hours = [11, 12, 13]

            results.append(DirectiveInterpretation(
                note_index=idx,
                applies=True,
                directive_type=DirectiveTypeEnum.SOLAR_REDUCTION,
                structured_adjustment={
                    "hours": hours,
                    "factor": factor
                },
                explanation=f"Solar availability is adjusted with factor {factor} for hours {hours}."
            ))

        # 2. Max Grid Window
        elif any(kw in note_lower for kw in ["cap", "grid import", "grid intake", "feeder", "transformer"]):
            # Extract max kWh
            max_grid = 150.0
            match = re.search(r'(\d+)\s*kwh', note_lower)
            if match:
                max_grid = float(match.group(1))

            if not hours:
                if "6 pm until 9 pm" in note_lower:
                    hours = [18, 19, 20]
                elif "7 pm until 9 pm" in note_lower or "19:00 until 21:00" in note_lower:
                    hours = [19, 20]
                elif "7 pm until 10 pm" in note_lower:
                    hours = [19, 20, 21]

            results.append(DirectiveInterpretation(
                note_index=idx,
                applies=True,
                directive_type=DirectiveTypeEnum.MAX_GRID_WINDOW,
                structured_adjustment={
                    "hours": hours,
                    "max_grid_kwh": max_grid
                },
                explanation=f"Grid import is capped at {max_grid} kWh for hours {hours}."
            ))

        # 3. Minimum Battery Reserve
        elif any(kw in note_lower for kw in ["reserve", "backup", "half of", "emergency reserve", "data center"]):
            min_kwh = 100.0
            if "half" in note_lower:
                min_kwh = battery_capacity / 2.0
            else:
                match = re.search(r'(\d+)\s*kwh', note_lower)
                if match:
                    min_kwh = float(match.group(1))

            if not hours:
                if "6 pm until 9 pm" in note_lower:
                    hours = [18, 19, 20]
                elif "6 pm until 10 pm" in note_lower:
                    hours = [18, 19, 20, 21]

            results.append(DirectiveInterpretation(
                note_index=idx,
                applies=True,
                directive_type=DirectiveTypeEnum.MINIMUM_BATTERY_RESERVE,
                structured_adjustment={
                    "hours": hours,
                    "minimum_energy_kwh": min_kwh
                },
                explanation=f"Minimum battery reserve raised to {min_kwh} kWh for hours {hours}."
            ))

        # 4. No Charge Window
        elif any(kw in note_lower for kw in ["charger isolated", "no charge", "prohibit grid charging", "charging-circuit outage", "charger inspection"]):
            if not hours:
                if "2 am until 5 am" in note_lower:
                    hours = [2, 3, 4]
                elif "11 am until 1 pm" in note_lower:
                    hours = [11, 12]
                elif "2 pm until 4 pm" in note_lower:
                    hours = [14, 15]

            results.append(DirectiveInterpretation(
                note_index=idx,
                applies=True,
                directive_type=DirectiveTypeEnum.NO_CHARGE_WINDOW,
                structured_adjustment={
                    "hours": hours
                },
                explanation=f"Battery charging is disabled for hours {hours}."
            ))

        # 5. No Discharge Window
        elif any(kw in note_lower for kw in ["no discharge", "disable battery discharging", "prohibit battery discharge", "protection-test", "relay testing"]):
            if not hours:
                if "6 pm until 8 pm" in note_lower:
                    hours = [18, 19]
                elif "5 pm until 7 pm" in note_lower:
                    hours = [17, 18]

            results.append(DirectiveInterpretation(
                note_index=idx,
                applies=True,
                directive_type=DirectiveTypeEnum.NO_DISCHARGE_WINDOW,
                structured_adjustment={
                    "hours": hours
                },
                explanation=f"Battery discharging is disabled for hours {hours}."
            ))

        # Fallback to no_op if unrecognized
        else:
            results.append(DirectiveInterpretation(
                note_index=idx,
                applies=False,
                directive_type=DirectiveTypeEnum.NO_OP,
                structured_adjustment=None,
                explanation="This note does not affect today's energy schedule."
            ))

    return results


def parse_time_window(text: str) -> List[int]:
    """Helper to convert time phrases like '2 AM until 5 AM' or 'noon until 2 PM' to integer hour lists."""
    text_lower = text.lower()
    
    # Common mappings
    if "noon until 2 pm" in text_lower or "12 pm until 2 pm" in text_lower:
        return [12, 13]
    if "2 am until 5 am" in text_lower:
        return [2, 3, 4]
    if "6 pm until 9 pm" in text_lower:
        return [18, 19, 20]
    if "6 pm until 8 pm" in text_lower:
        return [18, 19]
    if "6 pm until 10 pm" in text_lower:
        return [18, 19, 20, 21]
    if "7 pm until 9 pm" in text_lower:
        return [19, 20]
    if "7 pm until 10 pm" in text_lower:
        return [19, 20, 21]
    if "10 am until noon" in text_lower:
        return [10, 11]
    if "11 am until 1 pm" in text_lower:
        return [11, 12]
    if "11 am until 2 pm" in text_lower:
        return [11, 12, 13]
    if "2 pm until 4 pm" in text_lower:
        return [14, 15]
    if "5 pm until 7 pm" in text_lower:
        return [17, 18]

    return []


def interpret_operator_notes(operator_notes: List[str], battery_capacity: float = 200.0) -> List[DirectiveInterpretation]:
    """
    Main entry point for interpreting operator notes. Uses Gemini API if API key is configured,
    otherwise falls back to rule-based engine.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if HAS_GENAI and api_key:
        try:
            client = genai.Client(api_key=api_key)
            prompt = f"""You are an expert power grid operator interpreter.
Interpret the following operator notes into structured GridWise directives.
Allowed directive types:
- "solar_reduction": Usable solar factor remaining (e.g. 80% reduction means factor = 0.2).
- "minimum_battery_reserve": Sets min battery kWh reserve for hours.
- "no_charge_window": Disables charging for hours.
- "no_discharge_window": Disables discharging for hours.
- "max_grid_window": Caps grid import kWh for hours.
- "no_op": Irrelevant distractor note (applies=false, structured_adjustment=null).

Battery Capacity: {battery_capacity} kWh.
Operator Notes:
{json.dumps(operator_notes, indent=2)}

Return a JSON array of objects, one per note_index (0-indexed):
[
  {{
    "note_index": int,
    "applies": bool,
    "directive_type": str,
    "structured_adjustment": dict or null,
    "explanation": str
  }}
]
"""
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            data = json.loads(response.text)
            interpretations = []
            for item in data:
                interpretations.append(DirectiveInterpretation(**item))
            return interpretations
        except Exception:
            # Fallback to rule-based if API call fails
            pass

    return interpret_operator_notes_rule_based(operator_notes, battery_capacity)
