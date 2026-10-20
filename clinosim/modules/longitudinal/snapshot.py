"""`YearSnapshot` dataclass + CIF-friendly serialisation helpers.

The year-indexed snapshot that `PersonRecord.state_history: list[YearSnapshot]`
holds. One entry per sim year per alive person: continuous latents
(HbA1c, LDL, BP) and discrete chronic stages (CKD, CCS, NYHA, CDR)
live in their own buckets; event-pattern attributes record new ICD
onsets and medication additions / removals for the year.

Written through the CIF writer's existing `asdict(patient_record)` +
`json.dump` path — the dataclass contains only built-in Python types
(int / float / str / list / dict), so no custom encoder support is
needed.

See the Phase 1 longitudinal spec at
``docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md``
§4.1 for the field roster and §3.3 for the pattern composition that
writes into each bucket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class YearSnapshot:
    """One sim year's longitudinal state for one person.

    All fields except ``year`` default to empty collections so the
    engine's AR(1) / Markov / event patterns can read-then-write
    without pre-populating per-attribute buckets.
    """

    year: int
    continuous: dict[str, float] = field(default_factory=dict)
    chronic_stages: dict[str, str] = field(default_factory=dict)
    new_complications: list[str] = field(default_factory=list)
    med_additions: list[str] = field(default_factory=list)
    med_removals: list[str] = field(default_factory=list)


def yearsnapshot_from_dict(d: dict[str, Any]) -> YearSnapshot:
    """Build a ``YearSnapshot`` from its ``asdict`` form.

    Tolerates missing optional keys so a legacy / pre-field-addition
    dict (e.g. a snapshot persisted before Phase 2 adds a new field)
    still deserialises cleanly. ``year`` is mandatory — a dict without
    it has no identity, and ``KeyError`` is the right failure.
    """
    return YearSnapshot(
        year=d["year"],
        continuous=dict(d.get("continuous") or {}),
        chronic_stages=dict(d.get("chronic_stages") or {}),
        new_complications=list(d.get("new_complications") or []),
        med_additions=list(d.get("med_additions") or []),
        med_removals=list(d.get("med_removals") or []),
    )
