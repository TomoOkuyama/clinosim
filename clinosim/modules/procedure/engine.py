"""Procedure engine — surgical and procedural workflow simulation.

Generates procedure events (surgery, bedside procedures) with timing,
team assignment, complications, and physiological state changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np



@dataclass
class ProcedureRecord:
    """Complete record of a surgical/procedural event."""

    procedure_id: str = ""
    patient_id: str = ""
    encounter_id: str = ""
    procedure_type: str = ""  # "ORIF" | "hemiarthroplasty" | "thoracentesis" | ...
    procedure_code: str = ""  # K-code (JP) or CPT (US)
    procedure_name: str = ""

    # Timing
    start_datetime: datetime = field(default_factory=datetime.now)
    end_datetime: datetime = field(default_factory=datetime.now)
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


def simulate_surgery(
    patient: Any,
    disease_id: str,
    encounter_id: str,
    admission_time: datetime,
    protocol: Any,
    rng: np.random.Generator,
    country: str = "JP",
) -> tuple[ProcedureRecord, dict[str, float]]:
    """Simulate a surgical procedure. Returns the record and state impacts.

    Currently supports: hip fracture ORIF/hemiarthroplasty.
    """
    proc_data = protocol.procedure if hasattr(protocol, "procedure") and protocol.procedure else {}

    # Time to surgery
    if country == "JP":
        hours_to_surgery = max(12, float(rng.normal(48, 24)))  # JP: Day 1-2
    else:
        hours_to_surgery = max(6, float(rng.normal(24, 12)))  # US: target < 24h

    surgery_start = admission_time + timedelta(hours=hours_to_surgery)

    # Duration
    dur_config = proc_data.get("typical_duration_minutes", {"mean": 90, "sd": 30})
    duration = int(max(30, rng.normal(dur_config.get("mean", 90), dur_config.get("sd", 30))))

    # Anesthesia
    anesthesia = proc_data.get("anesthesia", "spinal or general")
    if "spinal" in anesthesia:
        anesthesia_type = "spinal" if rng.random() < 0.6 else "general"
    else:
        anesthesia_type = "general"

    # ASA class
    age = patient.age if hasattr(patient, "age") else 75
    n_conditions = len(patient.chronic_conditions) if hasattr(patient, "chronic_conditions") else 1
    asa = 2
    if n_conditions >= 2 or age >= 80:
        asa = 3
    if n_conditions >= 3 and age >= 85:
        asa = 4

    # EBL
    ebl_config = proc_data.get("estimated_blood_loss_ml", {"mean": 300, "sd": 150})
    ebl = int(max(50, rng.normal(ebl_config.get("mean", 300), ebl_config.get("sd", 150))))

    # Intraop complications
    intraop_comps = []
    if rng.random() < 0.03:
        intraop_comps.append("excessive_bleeding")
        ebl = int(ebl * 2)
    if rng.random() < 0.01:
        intraop_comps.append("anesthesia_hypotension")

    # Procedure type (hip fracture specific)
    if disease_id == "hip_fracture":
        if rng.random() < 0.55:
            proc_type = "ORIF"
            proc_code = "K0461" if country == "JP" else "27236"
            proc_name = "Open reduction internal fixation, femur"
            implants = ["compression hip screw" if rng.random() < 0.5 else "intramedullary nail"]
        else:
            proc_type = "hemiarthroplasty"
            proc_code = "K0811" if country == "JP" else "27125"
            proc_name = "Hemiarthroplasty, femoral head"
            implants = ["bipolar femoral prosthesis"]
    else:
        proc_type = "surgery"
        proc_code = ""
        proc_name = f"Surgical procedure for {disease_id}"
        implants = []

    record = ProcedureRecord(
        procedure_id=f"PROC-{patient.patient_id}-001",
        patient_id=patient.patient_id,
        encounter_id=encounter_id,
        procedure_type=proc_type,
        procedure_code=proc_code,
        procedure_name=proc_name,
        start_datetime=surgery_start,
        end_datetime=surgery_start + timedelta(minutes=duration),
        duration_minutes=duration,
        primary_surgeon_id="SURG-PLACEHOLDER-001",
        anesthesiologist_id="ANES-PLACEHOLDER-001",
        anesthesia_type=anesthesia_type,
        asa_class=asa,
        estimated_blood_loss_ml=ebl,
        implants_used=implants,
        intraop_complications=intraop_comps,
        preop_diagnosis=disease_id,
        postop_diagnosis=disease_id,
    )

    # State impacts from surgery
    state_impacts: dict[str, float] = {}
    # Blood loss → anemia
    if ebl > 200:
        state_impacts["anemia_level"] = ebl / 5000  # 500mL ≈ 0.1 increase
    # Fluid administration
    state_impacts["volume_status"] = 0.10  # IV fluid during surgery
    # Inflammation from tissue trauma
    state_impacts["inflammation_level"] = 0.10
    # Excessive bleeding → perfusion impact
    if ebl > 800:
        state_impacts["perfusion_status"] = -0.10

    return record, state_impacts


@dataclass
class RehabSession:
    """Record of a rehabilitation session."""

    session_id: str = ""
    patient_id: str = ""
    encounter_id: str = ""
    therapy_type: str = "PT"  # "PT" | "OT" | "ST"
    session_date: datetime = field(default_factory=datetime.now)
    duration_minutes: int = 40
    day_post_op: int = 0
    activities: list[str] = field(default_factory=list)
    patient_participation: str = "good"
    pain_score: int | None = None
    functional_progress: str = "stable"


def generate_rehab_sessions(
    patient_id: str,
    encounter_id: str,
    surgery_date: datetime,
    total_days: int,
    rng: np.random.Generator,
    country: str = "JP",
) -> list[RehabSession]:
    """Generate rehabilitation sessions for post-surgical recovery."""
    sessions: list[RehabSession] = []

    # Rehab starts POD 1 (day after surgery)
    start_day = 1
    duration = 40 if country == "JP" else 30

    activities_by_phase = {
        "early": ["bed exercises", "sitting up", "standing with assist"],
        "mid": ["walker ambulation", "stair practice", "transfer training"],
        "late": ["independent ambulation", "ADL practice", "stair climbing"],
    }

    for day_offset in range(start_day, total_days):
        # Skip some days randomly (weekend reduction, patient fatigue)
        if rng.random() < 0.1:
            continue

        # Determine phase
        if day_offset <= 3:
            phase = "early"
        elif day_offset <= 14:
            phase = "mid"
        else:
            phase = "late"

        activities = list(rng.choice(activities_by_phase[phase], size=min(3, len(activities_by_phase[phase])), replace=False))

        pain = int(max(0, min(10, rng.normal(4 - day_offset * 0.1, 1.5))))

        participation = "good"
        if pain > 6:
            participation = "fair"
        if rng.random() < 0.05:
            participation = "refused"

        progress = "improved" if day_offset > 3 else "stable"
        if participation == "refused":
            progress = "unable_to_assess"

        session = RehabSession(
            session_id=f"REHAB-{patient_id}-{day_offset:03d}",
            patient_id=patient_id,
            encounter_id=encounter_id,
            therapy_type="PT",
            session_date=surgery_date + timedelta(days=day_offset, hours=10),
            duration_minutes=duration,
            day_post_op=day_offset,
            activities=activities,
            patient_participation=participation,
            pain_score=pain,
            functional_progress=progress,
        )
        sessions.append(session)

    return sessions
