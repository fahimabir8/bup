"""Canonical numerical utilities shared across validation paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Approximate tolerance used across the codebase. The actual values are
# injected via settings; this module re-exports the configured tolerance.
@dataclass(frozen=True)
class Tols:
    abs_tolerance: float = 1e-3
    action_tolerance: float = 1e-4
    zero_tolerance: float = 1e-6


DEFAULT_TOLS = Tols()


def within_tolerance(value: float, target: float, tol: float = DEFAULT_TOLS.abs_tolerance) -> bool:
    return abs(value - target) <= tol


def normalize_zero(value: float, tol: float = DEFAULT_TOLS.zero_tolerance) -> float:
    if abs(value) < tol:
        return 0.0
    return float(value)


def safe_ratio(num: float, denom: float) -> Optional[float]:
    if denom == 0:
        return None
    return num / denom


__all__ = ["Tols", "DEFAULT_TOLS", "within_tolerance", "normalize_zero", "safe_ratio"]
