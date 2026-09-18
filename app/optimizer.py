from typing import List, Tuple
import numpy as np
from scipy.optimize import linprog

from app.models import (
    OptimizeEnergyRequest,
    DirectiveInterpretation,
    DirectiveTypeEnum,
    HourlyPlanItem,
    BatteryActionEnum,
    OptimizeEnergyResponse
)


def solve_gridwise_optimization(
    request: OptimizeEnergyRequest,
    directive_interpretations: List[DirectiveInterpretation]
) -> OptimizeEnergyResponse:
    """
    Solves the 24-hour microgrid optimization problem using SciPy HiGHS LP solver.
    """
    hours_input = request.hours
    battery = request.battery
    N = 24

    # 1. Process directive constraints across hours 0..23
    solar_factors = np.ones(N)
    min_reserves = np.full(N, battery.minimum_energy_kwh)
    max_charge_rates = np.full(N, battery.max_charge_kwh_per_hour)
    max_discharge_rates = np.full(N, battery.max_discharge_kwh_per_hour)
    max_grid_caps = np.full(N, np.inf)

    for interp in directive_interpretations:
        if not interp.applies or not interp.structured_adjustment:
            continue

        adj = interp.structured_adjustment
        target_hours = adj.get("hours", [])

        if interp.directive_type == DirectiveTypeEnum.SOLAR_REDUCTION:
            factor = float(adj.get("factor", 1.0))
            for h in target_hours:
                if 0 <= h < N:
                    solar_factors[h] *= factor

        elif interp.directive_type == DirectiveTypeEnum.MINIMUM_BATTERY_RESERVE:
            res_kwh = float(adj.get("minimum_energy_kwh", battery.minimum_energy_kwh))
            for h in target_hours:
                if 0 <= h < N:
                    min_reserves[h] = max(min_reserves[h], res_kwh)

        elif interp.directive_type == DirectiveTypeEnum.NO_CHARGE_WINDOW:
            for h in target_hours:
                if 0 <= h < N:
                    max_charge_rates[h] = 0.0

        elif interp.directive_type == DirectiveTypeEnum.NO_DISCHARGE_WINDOW:
            for h in target_hours:
                if 0 <= h < N:
                    max_discharge_rates[h] = 0.0

        elif interp.directive_type == DirectiveTypeEnum.MAX_GRID_WINDOW:
            cap = float(adj.get("max_grid_kwh", np.inf))
            for h in target_hours:
                if 0 <= h < N:
                    max_grid_caps[h] = min(max_grid_caps[h], cap)

    # 2. Setup LP Variables:
    # 5 variables per hour: (grid, solar_used, charge, discharge, battery_energy_after)
    # Total variables = 24 * 5 = 120
    # Index mapping for hour h:
    # g_idx = 5*h + 0
    # s_idx = 5*h + 1
    # c_idx = 5*h + 2
    # d_idx = 5*h + 3
    # E_idx = 5*h + 4

    num_vars = N * 5
    c_obj = np.zeros(num_vars)
    bounds = []

    for h in range(N):
        h_data = hours_input[h]
        # Objective coefficient: tariff for grid_kwh
        c_obj[5 * h + 0] = h_data.tariff_bdt_per_kwh

        # Bounds:
        # grid_kwh: [0, max_grid_caps[h]]
        bounds.append((0, max_grid_caps[h]))
        # solar_used_kwh: [0, solar_kwh * factor]
        effective_solar = h_data.solar_kwh * solar_factors[h]
        bounds.append((0, effective_solar))
        # charge_kwh: [0, max_charge_rates[h]]
        bounds.append((0, max_charge_rates[h]))
        # discharge_kwh: [0, max_discharge_rates[h]]
        bounds.append((0, max_discharge_rates[h]))
        # battery_energy_after_kwh: [min_reserves[h], capacity_kwh]
        bounds.append((min_reserves[h], battery.capacity_kwh))

    # 3. Equality Constraints:
    # A_eq * x = b_eq
    # a) Power Balance for each hour: grid + solar_used + discharge - charge = demand
    # b) Battery Dynamics for each hour:
    #    h=0: E_0 - c_0 + d_0 = initial_energy
    #    h>0: E_h - E_{h-1} - c_h + d_h = 0
    # c) End of day neutrality: E_23 = initial_energy (already captured by battery dynamics + E_23 = initial_energy)

    A_eq_rows = []
    b_eq_rows = []

    # Power balance: 24 equations
    for h in range(N):
        h_data = hours_input[h]
        row = np.zeros(num_vars)
        row[5 * h + 0] = 1.0  # grid
        row[5 * h + 1] = 1.0  # solar
        row[5 * h + 3] = 1.0  # discharge
        row[5 * h + 2] = -1.0 # charge
        A_eq_rows.append(row)
        b_eq_rows.append(h_data.demand_kwh)

    # Battery dynamics: 24 equations
    for h in range(N):
        row = np.zeros(num_vars)
        row[5 * h + 4] = 1.0   # E_h
        row[5 * h + 2] = -1.0  # - c_h
        row[5 * h + 3] = 1.0   # + d_h
        if h > 0:
            row[5 * (h - 1) + 4] = -1.0 # - E_{h-1}

        A_eq_rows.append(row)
        if h == 0:
            b_eq_rows.append(battery.initial_energy_kwh)
        else:
            b_eq_rows.append(0.0)

    # End of day battery neutrality: E_23 = initial_energy_kwh
    row_end = np.zeros(num_vars)
    row_end[5 * 23 + 4] = 1.0
    A_eq_rows.append(row_end)
    b_eq_rows.append(battery.initial_energy_kwh)

    A_eq = np.array(A_eq_rows)
    b_eq = np.array(b_eq_rows)

    # Solve LP
    res = linprog(c=c_obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method='highs')

    if not res.success:
        raise RuntimeError(f"Optimization failed: {res.message}")

    sol = res.x

    # 4. Construct Hourly Plan items
    hourly_plan: List[HourlyPlanItem] = []
    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0

    for h in range(N):
        grid_kwh = float(np.round(sol[5 * h + 0], 4))
        solar_used = float(np.round(sol[5 * h + 1], 4))
        charge_kwh = float(np.round(sol[5 * h + 2], 4))
        discharge_kwh = float(np.round(sol[5 * h + 3], 4))
        energy_after = float(np.round(sol[5 * h + 4], 4))

        if charge_kwh > 1e-3:
            action = BatteryActionEnum.CHARGE
            b_kwh = charge_kwh
        elif discharge_kwh > 1e-3:
            action = BatteryActionEnum.DISCHARGE
            b_kwh = discharge_kwh
        else:
            action = BatteryActionEnum.IDLE
            b_kwh = 0.0

        hourly_plan.append(HourlyPlanItem(
            hour=h,
            grid_kwh=grid_kwh,
            solar_used_kwh=solar_used,
            battery_action=action,
            battery_kwh=b_kwh,
            battery_energy_after_kwh=energy_after
        ))

        total_grid += grid_kwh
        total_cost += grid_kwh * hours_input[h].tariff_bdt_per_kwh
        if grid_kwh > peak_grid:
            peak_grid = grid_kwh

    total_grid = round(total_grid, 2)
    total_cost = round(total_cost, 2)
    peak_grid = round(peak_grid, 2)

    plan_summary = (
        f"Optimized 24-hour energy schedule for scenario {request.scenario_id}. "
        f"Achieves a total cost of {total_cost} BDT with {total_grid} kWh grid import "
        f"and peak demand of {peak_grid} kWh while respecting all operational directives."
    )

    return OptimizeEnergyResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=directive_interpretations,
        hourly_plan=hourly_plan,
        total_grid_kwh=total_grid,
        total_cost_bdt=total_cost,
        peak_grid_kwh=peak_grid,
        plan_summary=plan_summary
    )
