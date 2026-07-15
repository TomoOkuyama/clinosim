"""Triage CIF dataclass(Tier 1 #3 α-min-2 PR1).

EncounterRecord.triage_data に格納、FHIR builder + ED_TRIAGE_NOTE
narrative generator が参照。level_system = "JTAS" or "ESI"、locale-gated。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class TriageData:
    """ED triage data(AD-30 code-only CIF、display は output で解決)."""

    level: str = ""  # e.g. "1"..."5"
    level_system: str = ""  # "JTAS" | "ESI"
    arrival_mode: str = ""  # "walk-in" | "ambulance" | "police" | "helicopter" | "private_vehicle"
    triage_time: datetime | None = None
    acuity_score: float | None = None  # 0-100 数値スコア
    chief_complaint_summary: str = ""  # triage 時 chief complaint 短文
