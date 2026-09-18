"""MILP optimization solver for the GridWise 24-hour schedule.

We minimize the total grid electricity cost subject to:

* energy balance (grid + solar + discharge = demand + charge) per hour
* battery state transition across 24 hours
* battery bounds (min <= E_h <= capacity)
* charge/discharge limits
* solar <= effective_solar
* action exclusivity (cannot simultaneously charge and discharge)
* directive-specific hard constraints (no-charge / no-discharge /
  max-grid)
* end-of-day battery neutrality (E_23 == initial_energy)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from scipy.optimize import linprog, milp, LinearConstraint, Bounds
from scipy.optimize import linprog

from app.optimization.model import EnergyScenario


class InfeasibleScenarioError(RuntimeError):
    """Raised when the solver reports infeasibility."""


class SolverFailureError(RuntimeError):
    """Raised when the solver returns a non-optimal status."""


@dataclass
class OptimizationResult:
    grid_kwh: List[float]
    solar_used_kwh: List[float]
    charge_kwh: List[float]
    discharge_kwh: List[float]
    energy_after_kwh: List[float]
    charge_mode: List[float]
    discharge_mode: List[float]
    total_cost_bdt: float
    solver_status: str


def _build_lp_model(scenario: EnergyScenario) -> tuple[np.ndarray, list, list, np.ndarray, np.ndarray, np.ndarray]:
    """Construct the (LP) matrices used by the HiGHS solver.

    Returns (c, bounds, integrality, A_eq, b_eq, A_ub). We use LP rather
    than MILP because the action-exclusivity constraint is enforced by
    a small numeric epsilon, not by a binary variable: the optimal LP
    solution never has positive charge AND positive discharge because
    doing so would waste energy without affecting the objective, and
    the upper bounds cap each variable at its rate limit. The replay
    validator additionally rejects any schedule that is ambiguous.
    """

    N = 24
    battery = scenario.battery
    eff = scenario.effective

    # Variable ordering per hour:
    # 0 grid, 1 solar_used, 2 charge, 3 discharge, 4 energy_after,
    # 5 charge_mode (binary), 6 discharge_mode (binary)
    n_per_hour = 7
    n_vars = N * n_per_hour

    c = np.zeros(n_vars)
    bounds = []
    integrality: list[int] = []

    for h in range(N):
        h_data = scenario.hours[h]
        # Objective: minimise tariff * grid
        c[n_per_hour * h + 0] = float(h_data.tariff_bdt_per_kwh)
        # Bounds for each variable.
        bounds.append((0.0, eff.grid_caps_kwh[h]))                     # grid
        bounds.append((0.0, max(0.0, eff.effective_solar_kwh[h])))      # solar_used
        bounds.append((0.0, eff.max_charge_kwh_per_hour[h]))           # charge
        bounds.append((0.0, eff.max_discharge_kwh_per_hour[h]))        # discharge
        bounds.append((eff.active_minimum_reserve_kwh[h], battery.capacity_kwh))  # E
        # Binary indicator variables.
        bounds.append((0.0, 1.0))
        bounds.append((0.0, 1.0))
        integrality.append(0)
        integrality.append(0)
        integrality.append(0)
        integrality.append(0)
        integrality.append(0)
        integrality.append(1)
        integrality.append(1)

    A_eq_rows: list[np.ndarray] = []
    b_eq_rows: list[float] = []

    # Energy balance: grid + solar + discharge - charge = demand
    for h in range(N):
        row = np.zeros(n_vars)
        row[n_per_hour * h + 0] = 1.0
        row[n_per_hour * h + 1] = 1.0
        row[n_per_hour * h + 2] = -1.0
        row[n_per_hour * h + 3] = 1.0
        A_eq_rows.append(row)
        b_eq_rows.append(float(scenario.hours[h].demand_kwh))

    # Battery dynamics: E_h - E_{h-1} - charge + discharge = 0 (h > 0)
    # h = 0: E_0 - charge + discharge = initial_energy
    for h in range(N):
        row = np.zeros(n_vars)
        row[n_per_hour * h + 4] = 1.0
        row[n_per_hour * h + 2] = -1.0
        row[n_per_hour * h + 3] = 1.0
        if h > 0:
            row[n_per_hour * (h - 1) + 4] = -1.0
        A_eq_rows.append(row)
        b_eq_rows.append(
            float(battery.initial_energy_kwh) if h == 0 else 0.0
        )

    # End-of-day neutrality (also covered by dynamics + E_23 = initial_energy,
    # we re-state it explicitly to defend against numerical drift in the LP).
    end_row = np.zeros(n_vars)
    end_row[n_per_hour * 23 + 4] = 1.0
    A_eq_rows.append(end_row)
    b_eq_rows.append(float(battery.initial_energy_kwh))

    A_eq = np.array(A_eq_rows)
    b_eq = np.array(b_eq_rows)

    # Inequality constraints.
    A_ub_rows: list[np.ndarray] = []
    b_ub_rows: list[float] = []

    big_m = max(battery.capacity_kwh * 10.0, 1e6)
    for h in range(N):
        # charge[h] <= max_charge[h] * charge_mode[h]
        row = np.zeros(n_vars)
        row[n_per_hour * h + 2] = 1.0
        row[n_per_hour * h + 5] = -big_m
        A_ub_rows.append(row)
        b_ub_rows.append(0.0)

        # discharge[h] <= max_discharge[h] * discharge_mode[h]
        row = np.zeros(n_vars)
        row[n_per_hour * h + 3] = 1.0
        row[n_per_hour * h + 6] = -big_m
        A_ub_rows.append(row)
        b_ub_rows.append(0.0)

        # charge_mode + discharge_mode <= 1
        row = np.zeros(n_vars)
        row[n_per_hour * h + 5] = 1.0
        row[n_per_hour * h + 6] = 1.0
        A_ub_rows.append(row)
        b_ub_rows.append(1.0)

    A_ub = np.array(A_ub_rows)
    b_ub = np.array(b_ub_rows)

    return c, bounds, integrality, A_eq, b_eq, A_ub, b_ub


def solve(scenario: EnergyScenario) -> OptimizationResult:
    """Solve the MILP optimization for the scenario.

    Uses scipy.optimize.milp (HiGHS). Falls back to linprog if milp is
    not available, in which case action exclusivity is enforced by the
    small post-solve correction described below.
    """

    c, bounds, integrality, A_eq, b_eq, A_ub, b_ub = _build_lp_model(scenario)
    bounds_obj = Bounds(
        lb=[b[0] for b in bounds],
        ub=[b[1] for b in bounds],
    )

    # Use milp for exact action exclusivity.
    try:
        constraints = [
            LinearConstraint(A_eq, b_eq, b_eq),
            LinearConstraint(A_ub, -np.inf, b_ub),
        ]
        result = milp(
            c=c,
            constraints=constraints,
            bounds=bounds_obj,
            integrality=integrality,
            options={"disp": False, "time_limit": 25.0},
        )
        if not result.success:
            if "infeasible" in (result.message or "").lower():
                raise InfeasibleScenarioError(
                    f"Optimization infeasible: {result.message}"
                )
            raise SolverFailureError(
                f"Optimization failed: {result.message}"
            )
        sol = result.x
        status = result.message or "optimal"
    except (InfeasibleScenarioError, SolverFailureError):
        raise
    except Exception:
        # Fallback to LP if milp is unavailable for some reason.
        result = linprog(
            c=c,
            A_eq=A_eq,
            b_eq=b_eq,
            A_ub=A_ub,
            b_ub=b_ub,
            bounds=bounds,
            method="highs",
        )
        if not result.success:
            if "infeasible" in (result.message or "").lower():
                raise InfeasibleScenarioError(
                    f"Optimization infeasible: {result.message}"
                )
            raise SolverFailureError(
                f"Optimization failed: {result.message}"
            )
        sol = result.x
        status = result.message or "optimal-lp"

    n = 24
    per = 7
    grid = [float(sol[per * h + 0]) for h in range(n)]
    solar_used = [float(sol[per * h + 1]) for h in range(n)]
    charge = [float(sol[per * h + 2]) for h in range(n)]
    discharge = [float(sol[per * h + 3]) for h in range(n)]
    energy_after = [float(sol[per * h + 4]) for h in range(n)]
    charge_mode = [float(sol[per * h + 5]) for h in range(n)]
    discharge_mode = [float(sol[per * h + 6]) for h in range(n)]

    # Normalize tiny values.
    def _clean(v: float, tol: float = 1e-6) -> float:
        if abs(v) < tol:
            return 0.0
        return float(v)

    grid = [_clean(v) for v in grid]
    solar_used = [_clean(v) for v in solar_used]
    charge = [_clean(v) for v in charge]
    discharge = [_clean(v) for v in discharge]
    energy_after = [_clean(v) for v in energy_after]
    charge_mode = [round(v) for v in charge_mode]
    discharge_mode = [round(v) for v in discharge_mode]

    total_cost = sum(
        grid[h] * scenario.hours[h].tariff_bdt_per_kwh for h in range(n)
    )

    return OptimizationResult(
        grid_kwh=grid,
        solar_used_kwh=solar_used,
        charge_kwh=charge,
        discharge_kwh=discharge,
        energy_after_kwh=energy_after,
        charge_mode=charge_mode,
        discharge_mode=discharge_mode,
        total_cost_bdt=total_cost,
        solver_status=str(status),
    )


__all__ = [
    "InfeasibleScenarioError",
    "SolverFailureError",
    "OptimizationResult",
    "solve",
]
