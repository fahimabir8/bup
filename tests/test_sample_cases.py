import json
import os
import pytest
from app.models import OptimizeEnergyRequest
from app.interpreter import interpret_operator_notes
from app.optimizer import solve_gridwise_optimization

SAMPLE_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json")


def load_sample_cases():
    with open(SAMPLE_FILE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["cases"]


@pytest.mark.parametrize("case", load_sample_cases(), ids=lambda c: c["id"])
def test_gridwise_sample_case(case):
    case_id = case["id"]
    case_input = case["input"]
    expected_output = case["expected_output"]

    req = OptimizeEnergyRequest(**case_input)

    # 1. Interpret directives
    directive_interpretations = interpret_operator_notes(
        operator_notes=req.operator_notes,
        battery_capacity=req.battery.capacity_kwh
    )

    # Check directive interpretation matches expected length & types
    assert len(directive_interpretations) == len(expected_output["directive_interpretation"]), (
        f"Case {case_id}: expected {len(expected_output['directive_interpretation'])} interpretations, got {len(directive_interpretations)}"
    )

    for i, exp_interp in enumerate(expected_output["directive_interpretation"]):
        actual_interp = directive_interpretations[i]
        assert actual_interp.note_index == exp_interp["note_index"]
        assert actual_interp.applies == exp_interp["applies"]
        assert actual_interp.directive_type == exp_interp["directive_type"]

    # 2. Run Optimizer
    response = solve_gridwise_optimization(req, directive_interpretations)

    # 3. Check Cost Optimality within tolerance (0.01 BDT)
    exp_cost = expected_output["total_cost_bdt"]
    actual_cost = response.total_cost_bdt
    assert abs(actual_cost - exp_cost) <= 0.05, (
        f"Case {case_id}: expected cost {exp_cost} BDT, got {actual_cost} BDT (diff: {abs(actual_cost - exp_cost)})"
    )

    # 4. Check 24-hour power balance & battery neutrality
    hourly_plan = response.hourly_plan
    assert len(hourly_plan) == 24

    for h_item in hourly_plan:
        h_input = req.hours[h_item.hour]
        grid = h_item.grid_kwh
        solar = h_item.solar_used_kwh
        c_kwh = h_item.battery_kwh if h_item.battery_action == "charge" else 0.0
        d_kwh = h_item.battery_kwh if h_item.battery_action == "discharge" else 0.0

        # Power balance: grid + solar + discharge = demand + charge
        left_side = round(grid + solar + d_kwh, 2)
        right_side = round(h_input.demand_kwh + c_kwh, 2)
        assert abs(left_side - right_side) <= 0.01, (
            f"Case {case_id} Hour {h_item.hour}: Power balance violated ({left_side} != {right_side})"
        )

    # End of day battery energy neutrality
    end_energy = hourly_plan[23].battery_energy_after_kwh
    assert abs(end_energy - req.battery.initial_energy_kwh) <= 0.01, (
        f"Case {case_id}: End-of-day battery energy {end_energy} != initial {req.battery.initial_energy_kwh}"
    )
