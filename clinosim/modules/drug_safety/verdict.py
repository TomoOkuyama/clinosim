"""Verdict and skip-entry dataclasses for the drug_safety module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["allowed", "minor", "moderate", "major", "contraindicated"]

SEVERITY_RANK: dict[Severity, int] = {
    "allowed": 0,
    "minor": 1,
    "moderate": 2,
    "major": 3,
    "contraindicated": 4,
}

_DEFAULT_ACTION: dict[Severity, str] = {
    "allowed": "emit",
    "minor": "emit",
    "moderate": "emit_with_note",
    "major": "skip",
    "contraindicated": "skip",
}


@dataclass(frozen=True)
class SafetyVerdict:
    severity: Severity
    rule_id: str | None
    matched_classes: tuple[str, str] | None
    matched_active_drug: str | None
    rationale_en: str | None
    rationale_ja: str | None
    substitution_hint: str | None

    @property
    def is_allowed(self) -> bool:
        return self.severity == "allowed"

    @property
    def default_action(self) -> str:
        return _DEFAULT_ACTION[self.severity]


@dataclass
class SafetySkipEntry:
    encounter_id: str
    candidate_drug: str
    candidate_drug_ja: str
    active_conflict: str
    active_conflict_ja: str
    verdict: SafetyVerdict
    substituted_with: str | None
    substituted_with_ja: str | None
    context_hint: str | None
    timestamp: str
