import pulp
from app.models.request import OptimizeEnergyRequest, HourData, BatteryData
from app.models.directives import DirectiveType
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class OptimizationError(Exception):
    pass


def solve_energy_optimization(
    request: OptimizeEnergyRequest,
    validated_directives: list[dict],
) -> tuple[list[dict], float, float, float]:
    effective_solar = _apply_solar_reductions(request, validated_directives)
    min_reserve_by_hour = _compute_min_reserves(request, validated_directives)
    no_charge_hours = _get_no_charge_hours(validated_directives)
    no_discharge_hours = _get_no_discharge_hours(validated_directives)
    max_grid_by_hour = _get_max_grid_limits(validated_directives)

    prob = pulp.LpProblem("GridWiseEnergyOptimization", pulp.LpMinimize)

    grid = {}
    solar_used = {}
    charge = {}
    discharge = {}
    battery_energy = {}

    for h in range(24):
        grid[h] = pulp.LpVariable(f"grid_{h}", lowBound=0)
        solar_used[h] = pulp.LpVariable(f"solar_used_{h}", lowBound=0, upBound=effective_solar[h])
        charge[h] = pulp.LpVariable(f"charge_{h}", lowBound=0)
        discharge[h] = pulp.LpVariable(f"discharge_{h}", lowBound=0)
        battery_energy[h] = pulp.LpVariable(f"battery_energy_{h}", lowBound=0)

    prob += pulp.lpSum(grid[h] * request.hours[h].tariff_bdt_per_kwh for h in range(24))

    for h in range(24):
        hour_data = request.hours[h]
        prob += (
            grid[h] + solar_used[h] + discharge[h]
            == hour_data.demand_kwh + charge[h]
        ), f"energy_balance_{h}"

        prob += solar_used[h] <= effective_solar[h], f"solar_limit_{h}"

        prob += charge[h] <= request.battery.max_charge_kwh_per_hour, f"max_charge_{h}"
        prob += discharge[h] <= request.battery.max_discharge_kwh_per_hour, f"max_discharge_{h}"

        if h == 0:
            prob += battery_energy[h] == request.battery.initial_energy_kwh + charge[h] - discharge[h], f"battery_init_{h}"
        else:
            prob += battery_energy[h] == battery_energy[h-1] + charge[h] - discharge[h], f"battery_transition_{h}"

        prob += battery_energy[h] >= min_reserve_by_hour[h], f"min_reserve_{h}"
        prob += battery_energy[h] <= request.battery.capacity_kwh, f"max_capacity_{h}"

        if h in no_charge_hours:
            prob += charge[h] == 0, f"no_charge_{h}"
        if h in no_discharge_hours:
            prob += discharge[h] == 0, f"no_discharge_{h}"
        if h in max_grid_by_hour:
            prob += grid[h] <= max_grid_by_hour[h], f"max_grid_{h}"

    prob += battery_energy[23] == request.battery.initial_energy_kwh, "end_of_day_neutrality"

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=25)
    prob.solve(solver)

    if pulp.LpStatus[prob.status] != "Optimal":
        raise OptimizationError(f"Optimization failed: {pulp.LpStatus[prob.status]}")

    hourly_plan = []
    total_grid = 0
    total_cost = 0
    peak_grid = 0

    for h in range(24):
        grid_val = pulp.value(grid[h])
        solar_val = pulp.value(solar_used[h])
        charge_val = pulp.value(charge[h])
        discharge_val = pulp.value(discharge[h])
        energy_after = pulp.value(battery_energy[h])

        if charge_val > 1e-6:
            action = "charge"
            battery_kwh = charge_val
        elif discharge_val > 1e-6:
            action = "discharge"
            battery_kwh = discharge_val
        else:
            action = "idle"
            battery_kwh = 0

        hourly_plan.append({
            "hour": h,
            "grid_kwh": round(grid_val, 2),
            "solar_used_kwh": round(solar_val, 2),
            "battery_action": action,
            "battery_kwh": round(battery_kwh, 2),
            "battery_energy_after_kwh": round(energy_after, 2),
        })

        total_grid += grid_val
        total_cost += grid_val * request.hours[h].tariff_bdt_per_kwh
        peak_grid = max(peak_grid, grid_val)

    return hourly_plan, round(total_grid, 2), round(total_cost, 2), round(peak_grid, 2)


def _apply_solar_reductions(request: OptimizeEnergyRequest, directives: list[dict]) -> list[float]:
    effective_solar = [h.solar_kwh for h in request.hours]
    for d in directives:
        if d["directive_type"] == DirectiveType.SOLAR_REDUCTION and d["applies"]:
            adj = d["structured_adjustment"]
            factor = adj["factor"]
            for h in adj["hours"]:
                effective_solar[h] *= factor
    return effective_solar


def _compute_min_reserves(request: OptimizeEnergyRequest, directives: list[dict]) -> list[float]:
    min_reserve = [request.battery.minimum_energy_kwh] * 24
    for d in directives:
        if d["directive_type"] == DirectiveType.MINIMUM_BATTERY_RESERVE and d["applies"]:
            adj = d["structured_adjustment"]
            min_e = adj["minimum_energy_kwh"]
            for h in adj["hours"]:
                min_reserve[h] = max(min_reserve[h], min_e)
    return min_reserve


def _get_no_charge_hours(directives: list[dict]) -> set[int]:
    hours = set()
    for d in directives:
        if d["directive_type"] == DirectiveType.NO_CHARGE_WINDOW and d["applies"]:
            hours.update(d["structured_adjustment"]["hours"])
    return hours


def _get_no_discharge_hours(directives: list[dict]) -> set[int]:
    hours = set()
    for d in directives:
        if d["directive_type"] == DirectiveType.NO_DISCHARGE_WINDOW and d["applies"]:
            hours.update(d["structured_adjustment"]["hours"])
    return hours


def _get_max_grid_limits(directives: list[dict]) -> dict[int, float]:
    limits = {}
    for d in directives:
        if d["directive_type"] == DirectiveType.MAX_GRID_WINDOW and d["applies"]:
            adj = d["structured_adjustment"]
            max_g = adj["max_grid_kwh"]
            for h in adj["hours"]:
                if h in limits:
                    limits[h] = min(limits[h], max_g)
                else:
                    limits[h] = max_g
    return limits


def generate_plan_summary(
    request: OptimizeEnergyRequest,
    directives: list[dict],
    hourly_plan: list[dict],
) -> str:
    applied = [d for d in directives if d["applies"]]
    if not applied:
        return "No applicable operator directives. Optimized schedule minimizes grid cost."

    parts = []
    for d in applied:
        dt = d["directive_type"]
        adj = d["structured_adjustment"]
        hours = adj["hours"]
        h_str = f"hours {hours[0]}-{hours[-1]}" if len(hours) > 1 else f"hour {hours[0]}"

        if dt == DirectiveType.SOLAR_REDUCTION:
            parts.append(f"Solar reduced to {adj['factor']*100:.0f}% during {h_str}")
        elif dt == DirectiveType.MINIMUM_BATTERY_RESERVE:
            parts.append(f"Battery reserve ≥{adj['minimum_energy_kwh']} kWh during {h_str}")
        elif dt == DirectiveType.NO_CHARGE_WINDOW:
            parts.append(f"No charging during {h_str}")
        elif dt == DirectiveType.NO_DISCHARGE_WINDOW:
            parts.append(f"No discharging during {h_str}")
        elif dt == DirectiveType.MAX_GRID_WINDOW:
            parts.append(f"Grid import ≤{adj['max_grid_kwh']} kWh during {h_str}")

    return "Applied: " + "; ".join(parts) + ". Schedule minimizes grid cost."
