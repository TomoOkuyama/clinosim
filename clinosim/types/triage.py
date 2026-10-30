"""Triage CIF dataclass.

Stored on ``Encounter.triage_data`` (``clinosim/types/encounter.py``) by the
triage enricher (``clinosim/modules/triage/engine.py``) and consumed by the
``ED_TRIAGE_NOTE`` renderer and the ED note triage section
(``clinosim/modules/document/narrative/renderers/``).
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
