"""`YearSnapshot` dataclass + CIF-friendly serialisation helpers.

The year-indexed snapshot that ``PersonRecord.longitudinal_history`` holds:
one entry per sim year per alive person (continuous latents, discrete
chronic stages, new onsets and medication changes). Lives in
``clinosim.types`` (Issue #2210); ``clinosim.modules.longitudinal.snapshot``
re-exports it.
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
