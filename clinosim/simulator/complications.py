"""Complication-event schema helpers (Phase 1a, 2026-09-22).

``CIFPatientRecord.complications_occurred`` was a bare ``list[str]`` up to
v0.6.3, which meant an adverse event could not carry an onset day. That
loss surfaced as a temporal-leak audit (see PR #1452 write-up): day-N
progress-note narratives referenced future events because the LLM prompt
context had no way to tell "this happened on day 8" from "this happened
on day 1". Phase 1a lifts entries to a dict shape:

    {
      "name": str,            # canonical complication token / disease id
      "onset_day": int | None,# 0-indexed calendar days from admission
      "onset_datetime": str | None,  # ISO-8601 timestamp (fine-grained)
      "source": str,          # provenance — see SOURCES below
    }

Backward compat: v0.6.x CIF JSON files still round-trip as bare strings.
``_normalize_complication`` accepts both forms and returns the canonical
dict. ``complication_names`` returns the plain names for legacy code
paths (validator set-membership, CSV export) that do not yet consume
onset information.

Producers (2026-09-22 audit):
  * ``simulator/daily_loop.py`` — ``daily_loop`` complications
  * ``simulator/engine.py::_merge_disease_into_active_encounter`` —
    ``in_hospital_new_disease``
  * ``simulator/engine.py::_run_deterministic_enumeration`` —
    ``scenario_forced``
  * ``modules/diagnosis/lab_derived_dx.py`` — ``lab_derived``

The ``legacy`` source is reserved for entries synthesised on read from
pre-Phase-1 bare-string CIF JSON.
"""

from __future__ import annotations

from typing import Any

SOURCES: frozenset[str] = frozenset(
    {
        "daily_loop",
        "in_hospital_new_disease",
        "lab_derived",
        "scenario_forced",
        "legacy",
        "unknown",
    }
)


def _normalize_complication(entry: Any) -> dict[str, Any]:
    """Coerce a complications_occurred entry to the canonical dict shape.

    Accepts a bare string (pre-Phase-1 legacy form) or a dict (new
    schema). Unknown / missing dict fields are filled with the safe
    defaults ``onset_day = None`` / ``onset_datetime = None`` /
    ``source = "unknown"`` so downstream consumers can rely on the keys
    existing.
    """
    if isinstance(entry, str):
        return {
            "name": entry,
            "onset_day": None,
            "onset_datetime": None,
            "source": "legacy",
        }
    if not isinstance(entry, dict):
        return {
            "name": str(entry),
            "onset_day": None,
            "onset_datetime": None,
            "source": "unknown",
        }
    onset_day = entry.get("onset_day")
    try:
        onset_day_int = int(onset_day) if onset_day is not None else None
    except (TypeError, ValueError):
        onset_day_int = None
    onset_dt = entry.get("onset_datetime")
    source = str(entry.get("source", "unknown"))
    return {
        "name": str(entry.get("name", "")),
        "onset_day": onset_day_int,
        "onset_datetime": str(onset_dt) if onset_dt is not None else None,
        "source": source if source in SOURCES else "unknown",
    }


def normalized_complications(entries: list[Any] | None) -> list[dict[str, Any]]:
    """Return every entry coerced to the canonical dict shape.

    Used by narrative context builders that need the full event payload
    (``onset_day`` for temporal filtering, ``source`` for provenance)
    rather than just the names — see
    ``NarrativeContext.complications_events``.
    """
    if not entries:
        return []
    return [_normalize_complication(e) for e in entries]


def complication_names(entries: list[Any] | None) -> list[str]:
    """Return just the ``name`` field of each entry (legacy read path).

    Preserves order and duplicates. Empty-name entries are dropped so
    legacy validator set-membership does not include ``""``.
    """
    if not entries:
        return []
    out: list[str] = []
    for e in entries:
        n = _normalize_complication(e)["name"]
        if n:
            out.append(n)
    return out


def build_complication(
    name: str,
    onset_day: int | None,
    onset_datetime: str | None,
    source: str,
) -> dict[str, Any]:
    """Build a canonical complication dict entry for producer sites."""
    if source not in SOURCES:
        raise ValueError(f"Unknown complication source {source!r}; expected one of {sorted(SOURCES)}")
    return {
        "name": str(name),
        "onset_day": int(onset_day) if onset_day is not None else None,
        "onset_datetime": str(onset_datetime) if onset_datetime is not None else None,
        "source": source,
    }
