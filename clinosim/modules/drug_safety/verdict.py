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

# Issue #1403 (S113→S114 drug_safety silent-events wire): each silent
# drug-modification path that used to `continue` without a trace now
# writes a `SafetySkipEntry` with an explicit `event_type` so the
# narrative context (`ctx.safety_skips`) can render event-appropriate
# clinical prose (Rule 2 cadence, prompt v17). The four values line up
# 1:1 with the `narrative_seed_bundle.yaml` Rule 2 cadences:
#   - avoid       — drug × drug pair conflict; drop candidate, optional
#                   substitute chosen by suggest_alternative
#   - hold        — disease-protocol `medication_holds` at admission or
#                   at discharge Rx; drug held for the duration of the
#                   acute state (AKI hold RAAS; stroke hold bisphos.)
#   - substitute  — active-clinical-state substitution (pregnancy Cat
#                   C/D → Methyldopa; JP C-section postop NSAID →
#                   Loxoprofen). Not a conflict — a planned swap.
#   - deescalate  — antibiotic de-escalation: original broad-spectrum
#                   agent STOPPED on day N when a narrower agent starts.
EventType = Literal["avoid", "hold", "substitute", "deescalate"]


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
    # Issue #1403: event category. Defaults to "avoid" so all four
    # existing constructor sites (pair-rule skips) keep their legacy
    # semantics without a callsite edit. New silent-drop / silent-swap
    # / silent-stop paths pass event_type explicitly.
    event_type: EventType = "avoid"
    # Optional day-index marker for `deescalate` events — the hospital
    # day on which the original agent was stopped (populated by the
    # DISCONTINUE marker consumer). Ignored by other event types.
    stopped_on_day: int | None = None
