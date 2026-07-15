"""Procedure / rehabilitation CIF record types.

Plain runtime data types (AD-18 @dataclass). Per AD-30 the CIF is language-neutral —
procedure display names are NOT stored; consumers resolve them via
``code_lookup("k-codes"|"cpt", code, lang)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# See clinosim/types/clinical.py for rationale (determinism chain, 2026-07-04).
_UNSET_DATETIME = datetime(1970, 1, 1)

__all__ = ["ProcedureRecord", "RehabSession"]


@dataclass
class ProcedureRecord:
    """Complete record of a surgical/procedural event."""

    procedure_id: str = ""
    patient_id: str = ""
    encounter_id: str = ""
    procedure_type: str = ""  # "ORIF" | "hemiarthroplasty" | "thoracentesis" | ...
    procedure_code: str = ""  # K-code (JP) or CPT (US) — primary code for this country
    procedure_code_jp: str = ""  # K-code (always populated if available)
    procedure_code_us: str = ""  # CPT (always populated if available)
    # Per AD-30 (CIF is language-neutral), procedure display name is NOT stored
    # in CIF. Consumers resolve via code_lookup("k-codes"|"cpt", code, lang).

    # Timing
    start_datetime: datetime = field(default_factory=lambda: _UNSET_DATETIME)
    end_datetime: datetime = field(default_factory=lambda: _UNSET_DATETIME)
    duration_minutes: int = 90

    # Team
    primary_surgeon_id: str = ""
    anesthesiologist_id: str = ""
    assistant_ids: list[str] = field(default_factory=list)

    # Anesthesia
    anesthesia_type: str = "general"  # "general" | "spinal" | "local" | "sedation"
    asa_class: int = 2

    # Findings
    estimated_blood_loss_ml: int = 300
    specimens_sent: list[str] = field(default_factory=list)
    implants_used: list[str] = field(default_factory=list)
    intraop_complications: list[str] = field(default_factory=list)

    # Pre/post
    preop_diagnosis: str = ""
    postop_diagnosis: str = ""

    # Surgical approach (from disease YAML procedure.approach)
    approach: str = ""

    # FHIR Procedure structural fields (SNOMED CT codes)
    # category_code: 387713003 surgical / 103693007 diagnostic / 277132007 therapeutic
    category_code: str = ""
    body_site_code: str = ""  # SNOMED body site (empty if not applicable)
    # outcome_code: 385669000 successful / 385670004 partial / 385671000 unsuccessful
    outcome_code: str = ""
    complication_codes: list[str] = field(default_factory=list)  # SNOMED complication codes
    location_id: str = ""  # FHIR Location id (e.g. "loc-or-1" for operating rooms)


@dataclass
class RehabSession:
    """Record of a rehabilitation session."""

    session_id: str = ""
    patient_id: str = ""
    encounter_id: str = ""
    therapy_type: str = "PT"  # "PT" | "OT" | "ST"
    session_date: datetime = field(default_factory=lambda: _UNSET_DATETIME)
    duration_minutes: int = 40
    day_post_op: int = 0
    activities: list[str] = field(default_factory=list)
    patient_participation: str = "good"
    pain_score: int | None = None
    functional_progress: str = "stable"
