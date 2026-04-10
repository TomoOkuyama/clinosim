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

    # Surgical approach (from disease YAML procedure.approach)
    approach: str = ""

    # FHIR Procedure structural fields (SNOMED CT codes)
    category_code: str = ""        # 387713003 (surgical) / 103693007 (diagnostic) / 277132007 (therapeutic)
    body_site_code: str = ""       # SNOMED body site (empty if not applicable)
    outcome_code: str = ""         # 385669000 (successful) / 385670004 (partial) / 385671000 (unsuccessful)
    complication_codes: list[str] = field(default_factory=list)  # SNOMED complication codes
    location_id: str = ""          # FHIR Location id (e.g. "loc-or-1" for operating rooms)


def simulate_surgery(
    patient: Any,
    disease_id: str,
    encounter_id: str,
    admission_time: datetime,
    protocol: Any,
    rng: np.random.Generator,
    country: str = "JP",
    surgeon_id: str = "",
    anesthesiologist_id: str = "",
    operating_rooms: int = 2,
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
        # Read procedure details from disease YAML (fallback to generic)
        proc_type = proc_data.get("type", "surgery").split("/")[0].strip().split(" or ")[0].strip()
        if country == "JP":
            proc_code = proc_data.get("procedure_code_jp", "")
        else:
            proc_code = proc_data.get("procedure_code_us", "")
        proc_name = proc_data.get("type", "") or f"Surgical procedure for {disease_id}"
        implants = []

    # Surgical approach from disease YAML (protocol.procedure.approach)
    approach_map = proc_data.get("approach", {}) or {}
    approach = approach_map.get(proc_type, "") if isinstance(approach_map, dict) else str(approach_map)

    # Metadata (SNOMED category / body site), outcome, location
    meta = _PROCEDURE_METADATA.get(proc_type) or _PROCEDURE_METADATA["surgery"]
    or_number = int(rng.integers(1, max(2, operating_rooms + 1)))
    location_id = f"loc-or-{or_number}"

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
        primary_surgeon_id=surgeon_id,
        anesthesiologist_id=anesthesiologist_id,
        anesthesia_type=anesthesia_type,
        asa_class=asa,
        estimated_blood_loss_ml=ebl,
        implants_used=implants,
        intraop_complications=intraop_comps,
        preop_diagnosis=disease_id,
        postop_diagnosis=disease_id,
        approach=approach,
        category_code=meta.category_code,
        body_site_code=meta.body_site_code,
        outcome_code=_derive_outcome(intraop_comps),
        complication_codes=_map_complications(intraop_comps),
        location_id=location_id,
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


# ============================================================
# SNOMED CT codes used by this module (resolved via clinosim.codes at output time)
# ============================================================
_SCT_CATEGORY_SURGICAL = "387713003"
_SCT_CATEGORY_DIAGNOSTIC = "103693007"
_SCT_CATEGORY_THERAPEUTIC = "277132007"

_SCT_OUTCOME_SUCCESS = "385669000"
_SCT_OUTCOME_PARTIAL = "385670004"
_SCT_OUTCOME_UNSUCCESS = "385671000"

# Complication type → SNOMED code
_COMPLICATION_SCT: dict[str, str] = {
    "excessive_bleeding": "131148009",          # Bleeding
    "anesthesia_hypotension": "45007003",       # Hypotension
    "surgical_site_infection": "87317003",
    "ards": "67782005",
}


# ============================================================
# Procedure metadata table
# ============================================================
# Maps procedure_type → FHIR Procedure category + body site (SNOMED).
# Used by both simulate_surgery and generate_bedside_procedures to populate
# the structural FHIR fields.
@dataclass(frozen=True)
class ProcedureMeta:
    category_code: str         # SNOMED category
    body_site_code: str = ""   # SNOMED body site (empty if n/a)


_PROCEDURE_METADATA: dict[str, ProcedureMeta] = {
    # --- Surgeries ---
    "ORIF": ProcedureMeta(_SCT_CATEGORY_SURGICAL, "71341001"),              # femur
    "hemiarthroplasty": ProcedureMeta(_SCT_CATEGORY_SURGICAL, "29836001"),  # hip region
    "surgery": ProcedureMeta(_SCT_CATEGORY_SURGICAL, ""),
    # --- Bedside / routine ---
    "urinary_catheter": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "89837001"),  # bladder
    "central_line": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "113257007"),     # cardiovascular
    "arterial_line": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "58602004"),     # peripheral vascular
    "lumbar_puncture": ProcedureMeta(_SCT_CATEGORY_DIAGNOSTIC, "32713005"),    # vertebral column
    "thoracentesis": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "118375008"),    # intrathoracic
    "paracentesis": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "818983003"),     # abdomen
    "intubation": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "74262004"),        # oral cavity
    "nasogastric_tube": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "74262004"),  # oral cavity
    "chest_tube": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "118375008"),       # intrathoracic
    "wound_debridement": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "87642003"), # skin/subcut
    "cardioversion": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "113257007"),    # cardiovascular
    "blood_transfusion": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "38266002"), # entire body
    "dialysis_acute": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "80581009"),    # upper urinary tract
    "bronchoscopy": ProcedureMeta(_SCT_CATEGORY_DIAGNOSTIC, "39607008"),       # lung
    "echocardiography": ProcedureMeta(_SCT_CATEGORY_DIAGNOSTIC, "113257007"),  # cardiovascular
}


def _derive_outcome(complications: list[str]) -> str:
    """Derive SNOMED outcome code from complication list."""
    if not complications:
        return _SCT_OUTCOME_SUCCESS
    # Anesthesia hypotension / minor bleeding → partially successful
    return _SCT_OUTCOME_PARTIAL


def _map_complications(intraop_comps: list[str]) -> list[str]:
    """Map internal complication keys → SNOMED codes."""
    return [_COMPLICATION_SCT[c] for c in intraop_comps if c in _COMPLICATION_SCT]


# ============================================================
# Bedside / routine inpatient procedures
# ============================================================

# (procedure_type, CPT, K-code, name_en, name_ja, anesthesia)
_BEDSIDE_PROCEDURES: list[tuple[str, str, str, str, str, str]] = [
    ("urinary_catheter", "51702", "D002", "Urinary catheter insertion", "尿道カテーテル挿入", "none"),
    ("central_line", "36556", "G005-2", "Central venous catheter insertion", "中心静脈カテーテル挿入", "local"),
    ("arterial_line", "36620", "G005-3", "Arterial line insertion", "動脈ライン挿入", "local"),
    ("lumbar_puncture", "62270", "D004", "Lumbar puncture", "腰椎穿刺", "local"),
    ("thoracentesis", "32555", "D010", "Thoracentesis", "胸腔穿刺", "local"),
    ("paracentesis", "49083", "D011", "Paracentesis", "腹腔穿刺", "local"),
    ("intubation", "31500", "J044", "Endotracheal intubation", "気管挿管", "sedation"),
    ("nasogastric_tube", "43752", "J034", "Nasogastric tube insertion", "経鼻胃管挿入", "none"),
    ("chest_tube", "32551", "D012", "Chest tube insertion", "胸腔ドレーン挿入", "local"),
    ("wound_debridement", "97597", "K002", "Wound debridement", "創傷デブリードマン", "local"),
    ("cardioversion", "92960", "K599", "Electrical cardioversion", "電気的カルジオバージョン", "sedation"),
    ("blood_transfusion", "36430", "K920", "Blood transfusion", "輸血", "none"),
    ("dialysis_acute", "90935", "J038", "Acute hemodialysis", "急性血液透析", "none"),
    ("bronchoscopy", "31622", "D302", "Bronchoscopy", "気管支鏡検査", "sedation"),
    ("echocardiography", "93306", "D215", "Transthoracic echocardiography", "経胸壁心エコー", "none"),
]

# Rules: (disease_id or category) → [(procedure_type, probability)]
# category keywords checked against disease_id
_PROCEDURE_RULES: list[tuple[str | list[str], list[tuple[str, float]]]] = [
    # Universal: urinary catheter for severe patients
    (["sepsis", "acute_mi", "heart_failure", "cerebral_infarction", "hemorrhagic_stroke",
      "subdural_hematoma", "traffic_accident_severe"],
     [("urinary_catheter", 0.85)]),
    # Moderate-severe inpatients: urinary catheter
    (["copd_exacerbation", "gi_bleeding", "acute_pancreatitis", "diabetic_ketoacidosis",
      "liver_cirrhosis_decompensated", "pulmonary_embolism", "acute_kidney_injury"],
     [("urinary_catheter", 0.50)]),
    # Sepsis / critical: central line, arterial line
    (["sepsis"],
     [("central_line", 0.70), ("arterial_line", 0.50), ("blood_transfusion", 0.15)]),
    # Heart failure: echocardiography
    (["heart_failure_exacerbation"],
     [("echocardiography", 0.80), ("urinary_catheter", 0.60)]),
    # Acute MI: arterial line, echo
    (["acute_mi"],
     [("arterial_line", 0.60), ("central_line", 0.40), ("echocardiography", 0.90)]),
    # Stroke: nasogastric tube (dysphagia risk), lumbar puncture
    (["cerebral_infarction", "hemorrhagic_stroke"],
     [("nasogastric_tube", 0.30), ("echocardiography", 0.50)]),
    # Hemorrhagic stroke / subdural: intubation
    (["hemorrhagic_stroke", "subdural_hematoma"],
     [("intubation", 0.40), ("central_line", 0.50), ("arterial_line", 0.40)]),
    # GI bleeding: nasogastric tube, blood transfusion
    (["gi_bleeding"],
     [("nasogastric_tube", 0.50), ("blood_transfusion", 0.60), ("central_line", 0.30)]),
    # Liver cirrhosis: paracentesis, nasogastric tube
    (["liver_cirrhosis_decompensated"],
     [("paracentesis", 0.70), ("nasogastric_tube", 0.25), ("blood_transfusion", 0.30)]),
    # Pneumonia/aspiration: bronchoscopy in severe cases
    (["bacterial_pneumonia", "aspiration_pneumonia"],
     [("bronchoscopy", 0.15), ("intubation", 0.10)]),
    # DKA: central line, arterial line
    (["diabetic_ketoacidosis"],
     [("central_line", 0.35), ("arterial_line", 0.20)]),
    # Pulmonary embolism: echo
    (["pulmonary_embolism"],
     [("echocardiography", 0.70), ("central_line", 0.20)]),
    # Ileus: nasogastric tube
    (["ileus"],
     [("nasogastric_tube", 0.80)]),
    # AKI: dialysis in severe cases
    (["acute_kidney_injury"],
     [("dialysis_acute", 0.30), ("central_line", 0.40)]),
    # Atrial fibrillation: cardioversion, echo
    (["atrial_fibrillation_rvr"],
     [("cardioversion", 0.25), ("echocardiography", 0.60)]),
    # Pancreatitis: nasogastric tube
    (["acute_pancreatitis"],
     [("nasogastric_tube", 0.40), ("central_line", 0.20)]),
    # Trauma: central line, arterial line, blood transfusion
    (["traffic_accident_severe"],
     [("central_line", 0.70), ("arterial_line", 0.60), ("blood_transfusion", 0.50),
      ("intubation", 0.30), ("chest_tube", 0.25)]),
    # Cellulitis with severe: wound debridement
    (["cellulitis"],
     [("wound_debridement", 0.30)]),
]


def generate_bedside_procedures(
    patient_id: str,
    encounter_id: str,
    disease_id: str,
    admission_time: datetime,
    severity: str,
    rng: np.random.Generator,
    country: str = "US",
) -> list[ProcedureRecord]:
    """Generate bedside/routine procedures based on disease and severity.

    Uses rule-based matching: disease_id is matched against _PROCEDURE_RULES,
    and each candidate procedure fires with its probability, scaled by severity.
    """
    severity_mult = {"severe": 1.3, "moderate": 1.0, "mild": 0.5}.get(severity, 1.0)
    proc_lookup = {p[0]: p for p in _BEDSIDE_PROCEDURES}

    triggered: dict[str, float] = {}  # procedure_type → max probability
    for disease_match, proc_list in _PROCEDURE_RULES:
        match_list = disease_match if isinstance(disease_match, list) else [disease_match]
        if disease_id not in match_list:
            continue
        for proc_type, prob in proc_list:
            # Take the highest probability across matching rules
            triggered[proc_type] = max(triggered.get(proc_type, 0), prob)

    results: list[ProcedureRecord] = []
    proc_idx = 0
    for proc_type, base_prob in triggered.items():
        prob = min(1.0, base_prob * severity_mult)
        if rng.random() >= prob:
            continue
        spec = proc_lookup.get(proc_type)
        if not spec:
            continue

        _, cpt, kcode, name_en, name_ja, anesthesia = spec
        code = kcode if country == "JP" else cpt
        name = name_ja if country == "JP" else name_en

        # Timing: most bedside procedures happen within first 24h
        hours_offset = max(0.5, float(rng.exponential(6)))  # median ~6h post-admission
        proc_time = admission_time + timedelta(hours=hours_offset)
        duration = int(max(10, rng.normal(30, 10)))

        meta = _PROCEDURE_METADATA.get(proc_type)
        record = ProcedureRecord(
            procedure_id=f"PROC-{patient_id}-{proc_idx + 2:03d}",
            patient_id=patient_id,
            encounter_id=encounter_id,
            procedure_type=proc_type,
            procedure_code=code,
            procedure_name=name,
            start_datetime=proc_time,
            end_datetime=proc_time + timedelta(minutes=duration),
            duration_minutes=duration,
            primary_surgeon_id="",
            anesthesia_type=anesthesia,
            category_code=meta.category_code if meta else _SCT_CATEGORY_THERAPEUTIC,
            body_site_code=meta.body_site_code if meta else "",
            outcome_code=_SCT_OUTCOME_SUCCESS,
            complication_codes=[],
            location_id="",
        )
        results.append(record)
        proc_idx += 1

    return results


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
