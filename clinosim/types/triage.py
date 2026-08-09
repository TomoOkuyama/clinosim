"""Triage CIF dataclass.

Stored on ``EncounterRecord.triage_data`` and consumed by the FHIR
builder and the ``ED_TRIAGE_NOTE`` narrative generator.
``level_system`` is ``"JTAS"`` (JP) or ``"ESI"`` (US), locale-gated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class TriageData:
    """ED triage data (AD-30 code-only CIF; display resolved at output time)."""

    level: str = ""  # e.g. "1"..."5"
    level_system: str = ""  # "JTAS" | "ESI"
    arrival_mode: str = ""  # "walk-in" | "ambulance" | "police" | "helicopter" | "private_vehicle"
    triage_time: datetime | None = None
    acuity_score: float | None = None  # 0-100 numeric score
    chief_complaint_summary: str = ""  # Short chief-complaint text captured at triage time.
