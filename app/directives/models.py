"""Shared internal models used by the directives package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class InterpretationIssue:
    """A single deterministic validation problem."""

    note_index: int
    code: str
    message: str


@dataclass
class InterpretationValidationReport:
    """Aggregated report from the deterministic validator."""

    issues: List[InterpretationIssue] = field(default_factory=list)

    @property
    def is_ok(self) -> bool:
        return not self.issues

    def add(self, note_index: int, code: str, message: str) -> None:
        self.issues.append(
            InterpretationIssue(note_index, code, message)
        )

    def first_message(self) -> Optional[str]:
        if not self.issues:
            return None
        return self.issues[0].message


__all__ = ["InterpretationIssue", "InterpretationValidationReport"]
