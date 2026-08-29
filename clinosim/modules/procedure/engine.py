"""Procedure engine — surgical and procedural workflow simulation.

Generates procedure events (surgery, bedside procedures) with timing,
team assignment, complications, and physiological state changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from clinosim import determinism
from clinosim.modules._shared import is_jp
from clinosim.modules.disease.acuity import NEURO_LOC_MONITORING_DISEASES
from clinosim.modules.procedure._bedside_thresholds import (
    BEDSIDE_DURATION_MEAN_MIN,
    BEDSIDE_DURATION_MIN_MIN,
    BEDSIDE_DURATION_STD_MIN,
    BEDSIDE_HOURS_OFFSET_EXPONENTIAL_MEAN,
    BEDSIDE_HOURS_OFFSET_MIN,
    BEDSIDE_SEVERITY_MILD_MULTIPLIER,
    BEDSIDE_SEVERITY_MODERATE_MULTIPLIER,
    BEDSIDE_SEVERITY_MULTIPLIER_FALLBACK,
    BEDSIDE_SEVERITY_SEVERE_MULTIPLIER,
)
from clinosim.modules.procedure._rehab_thresholds import (
    REHAB_IMPROVED_MIN_POD,
    REHAB_JP_SESSION_DURATION_MIN,
    REHAB_PAIN_BASE_SCORE,
    REHAB_PAIN_DECAY_PER_POD,
    REHAB_PAIN_FAIR_PARTICIPATION_THRESHOLD,
    REHAB_PAIN_MAX_SCORE,
    REHAB_PAIN_MIN_SCORE,
    REHAB_PAIN_STD,
    REHAB_PHASE_EARLY_MAX_POD,
    REHAB_PHASE_MID_MAX_POD,
    REHAB_REFUSAL_PROBABILITY,
    REHAB_SESSION_START_HOUR,
    REHAB_SKIP_DAY_PROBABILITY,
    REHAB_START_POD,
    REHAB_US_SESSION_DURATION_MIN,
)
from clinosim.modules.procedure._surgery_thresholds import (
    ASA_AGE_HIGH_THRESHOLD,
    ASA_AGE_LOW_THRESHOLD,
    ASA_BASE_CLASS,
    ASA_COMORBIDITY_HIGH_THRESHOLD,
    ASA_COMORBIDITY_LOW_THRESHOLD,
    ASA_HIGH_CLASS,
    ASA_LOW_CLASS,
    DEFAULT_EBL_MEAN_ML,
    DEFAULT_EBL_STD_ML,
    DEFAULT_SURGERY_DURATION_MEAN_MIN,
    DEFAULT_SURGERY_DURATION_STD_MIN,
    EBL_ANEMIA_LIFT_DIVISOR,
    EBL_ANEMIA_LIFT_THRESHOLD_ML,
    EBL_MAJOR_BLEED_PERFUSION_PENALTY,
    EBL_MAJOR_BLEED_THRESHOLD_ML,
    EBL_MIN_ML,
    HIP_FRACTURE_ORIF_INTRAMEDULLARY_NAIL_PROBABILITY,
    HIP_FRACTURE_ORIF_PROBABILITY,
    INTRAOP_ANESTHESIA_HYPOTENSION_PROBABILITY,
    INTRAOP_EBL_BLEEDING_MULTIPLIER,
    INTRAOP_EXCESSIVE_BLEEDING_PROBABILITY,
    JP_TIME_TO_SURGERY_FLOOR_HOURS,
    JP_TIME_TO_SURGERY_MEAN_HOURS,
    JP_TIME_TO_SURGERY_STD_HOURS,
    SPINAL_ANESTHESIA_PROBABILITY_WHEN_ALLOWED,
    SURGERY_DURATION_MIN_MIN,
    SURGERY_INFLAMMATION_LIFT,
    SURGERY_VOLUME_LIFT,
    US_TIME_TO_SURGERY_FLOOR_HOURS,
    US_TIME_TO_SURGERY_MEAN_HOURS,
    US_TIME_TO_SURGERY_STD_HOURS,
)
from clinosim.seeding import issue939_procedure_seed
from clinosim.types.procedure import ProcedureRecord, RehabSession

__all__ = ["ProcedureRecord", "RehabSession"]


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
    if is_jp(country):
        hours_to_surgery = max(
            JP_TIME_TO_SURGERY_FLOOR_HOURS,
            float(rng.normal(JP_TIME_TO_SURGERY_MEAN_HOURS, JP_TIME_TO_SURGERY_STD_HOURS)),
        )
    else:
        hours_to_surgery = max(
            US_TIME_TO_SURGERY_FLOOR_HOURS,
            float(rng.normal(US_TIME_TO_SURGERY_MEAN_HOURS, US_TIME_TO_SURGERY_STD_HOURS)),
        )

    surgery_start = admission_time + timedelta(hours=hours_to_surgery)

    # Duration
    dur_config = proc_data.get(
        "typical_duration_minutes",
        {"mean": DEFAULT_SURGERY_DURATION_MEAN_MIN, "sd": DEFAULT_SURGERY_DURATION_STD_MIN},
    )
    duration = int(
        max(
            SURGERY_DURATION_MIN_MIN,
            rng.normal(
                dur_config.get("mean", DEFAULT_SURGERY_DURATION_MEAN_MIN),
                dur_config.get("sd", DEFAULT_SURGERY_DURATION_STD_MIN),
            ),
        )
    )

    # Anesthesia
    anesthesia = proc_data.get("anesthesia", "spinal or general")
    if "spinal" in anesthesia:
        anesthesia_type = "spinal" if rng.random() < SPINAL_ANESTHESIA_PROBABILITY_WHEN_ALLOWED else "general"
    else:
        anesthesia_type = "general"

    # ASA class
    age = patient.age if hasattr(patient, "age") else 75
    n_conditions = len(patient.chronic_conditions) if hasattr(patient, "chronic_conditions") else 1
    asa = ASA_BASE_CLASS
    if n_conditions >= ASA_COMORBIDITY_LOW_THRESHOLD or age >= ASA_AGE_LOW_THRESHOLD:
        asa = ASA_LOW_CLASS
    if n_conditions >= ASA_COMORBIDITY_HIGH_THRESHOLD and age >= ASA_AGE_HIGH_THRESHOLD:
        asa = ASA_HIGH_CLASS

    # EBL
    ebl_config = proc_data.get("estimated_blood_loss_ml", {"mean": DEFAULT_EBL_MEAN_ML, "sd": DEFAULT_EBL_STD_ML})
    ebl = int(
        max(
            EBL_MIN_ML,
            rng.normal(ebl_config.get("mean", DEFAULT_EBL_MEAN_ML), ebl_config.get("sd", DEFAULT_EBL_STD_ML)),
        )
    )

    # Intraop complications
    intraop_comps = []
    if rng.random() < INTRAOP_EXCESSIVE_BLEEDING_PROBABILITY:
        intraop_comps.append("excessive_bleeding")
        ebl = int(ebl * INTRAOP_EBL_BLEEDING_MULTIPLIER)
    if rng.random() < INTRAOP_ANESTHESIA_HYPOTENSION_PROBABILITY:
        intraop_comps.append("anesthesia_hypotension")

    # Procedure type (hip fracture specific)
    if disease_id == "hip_fracture":
        if rng.random() < HIP_FRACTURE_ORIF_PROBABILITY:
            proc_type = "ORIF"
            proc_code_jp = "K0461"
            proc_code_us = "27236"
            implants = [
                "compression hip screw"
                if rng.random() < HIP_FRACTURE_ORIF_INTRAMEDULLARY_NAIL_PROBABILITY
                else "intramedullary nail"
            ]
        else:
            proc_type = "hemiarthroplasty"
            proc_code_jp = "K0811"
            proc_code_us = "27125"
            implants = ["bipolar femoral prosthesis"]
    else:
        # Read procedure codes from disease YAML
        proc_type = proc_data.get("type", "surgery").split("/")[0].strip().split(" or ")[0].strip()
        proc_code_jp = proc_data.get("procedure_code_jp", "")
        proc_code_us = proc_data.get("procedure_code_us", "")
        implants = []

    # Primary code for this country
    proc_code = proc_code_jp if is_jp(country) else proc_code_us

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
        procedure_code_jp=proc_code_jp,
        procedure_code_us=proc_code_us,
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
    if ebl > EBL_ANEMIA_LIFT_THRESHOLD_ML:
        state_impacts["anemia_level"] = ebl / EBL_ANEMIA_LIFT_DIVISOR
    # Fluid administration
    state_impacts["volume_status"] = SURGERY_VOLUME_LIFT
    # Inflammation from tissue trauma
    state_impacts["inflammation_level"] = SURGERY_INFLAMMATION_LIFT
    # Excessive bleeding → perfusion impact
    if ebl > EBL_MAJOR_BLEED_THRESHOLD_ML:
        state_impacts["perfusion_status"] = EBL_MAJOR_BLEED_PERFUSION_PENALTY

    return record, state_impacts


# ============================================================
# SNOMED CT codes used by this module (resolved via clinosim.codes at output time)
# ============================================================
_SCT_CATEGORY_SURGICAL = "387713003"
# feedback FB-F8: SNOMED 103693007 は inactive、active 386053000 "Evaluation
# procedure" に更新(cycle 8 拡張)。
_SCT_CATEGORY_DIAGNOSTIC = "386053000"
_SCT_CATEGORY_THERAPEUTIC = "277132007"

_SCT_OUTCOME_SUCCESS = "385669000"
_SCT_OUTCOME_PARTIAL = "385670004"
_SCT_OUTCOME_UNSUCCESS = "385671000"

# Complication type → SNOMED code
_COMPLICATION_SCT: dict[str, str] = {
    "excessive_bleeding": "131148009",  # Bleeding
    "anesthesia_hypotension": "45007003",  # Hypotension
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
    category_code: str  # SNOMED category
    body_site_code: str = ""  # SNOMED body site (empty if n/a)


_PROCEDURE_METADATA: dict[str, ProcedureMeta] = {
    # --- Surgeries ---
    "ORIF": ProcedureMeta(_SCT_CATEGORY_SURGICAL, "71341001"),  # femur
    "hemiarthroplasty": ProcedureMeta(_SCT_CATEGORY_SURGICAL, "29836001"),  # hip region
    "surgery": ProcedureMeta(_SCT_CATEGORY_SURGICAL, ""),
    # --- Bedside / routine ---
    "urinary_catheter": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "89837001"),  # bladder
    "central_line": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "113257007"),  # cardiovascular
    "arterial_line": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "58602004"),  # peripheral vascular
    "lumbar_puncture": ProcedureMeta(_SCT_CATEGORY_DIAGNOSTIC, "32713005"),  # vertebral column
    "thoracentesis": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "118375008"),  # intrathoracic
    "paracentesis": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "818983003"),  # abdomen
    "intubation": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "74262004"),  # oral cavity
    "nasogastric_tube": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "74262004"),  # oral cavity
    "chest_tube": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "118375008"),  # intrathoracic
    "wound_debridement": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "87642003"),  # skin/subcut
    "cardioversion": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "113257007"),  # cardiovascular
    "blood_transfusion": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "38266002"),  # entire body
    "dialysis_acute": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "80581009"),  # upper urinary tract
    "bronchoscopy": ProcedureMeta(_SCT_CATEGORY_DIAGNOSTIC, "39607008"),  # lung
    "echocardiography": ProcedureMeta(_SCT_CATEGORY_DIAGNOSTIC, "113257007"),  # cardiovascular
    # CO-3: ED procedures.
    "ecg_12lead": ProcedureMeta(_SCT_CATEGORY_DIAGNOSTIC, "80891009"),  # heart
    "iv_line": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "58602004"),  # peripheral vascular
    "wound_care": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "87642003"),  # skin
    "short_arm_splint": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "8205005"),  # wrist
    "reduction_closed": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "8205005"),  # wrist
    "oxygen_therapy": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "39607008"),  # lung
    # Issue #939: standard-of-care interventions for cardiology / neurosurgery
    # / GI-obstruction admissions. SNOMED body-site codes verified against
    # the SNOMED International browser (browser.ihtsdotools.org).
    "coronary_pci": ProcedureMeta(_SCT_CATEGORY_SURGICAL, "41801008"),  # coronary artery
    "pacemaker_implant": ProcedureMeta(_SCT_CATEGORY_SURGICAL, "80891009"),  # heart
    "craniotomy_hematoma_evacuation": ProcedureMeta(_SCT_CATEGORY_SURGICAL, "12738006"),  # brain
    "ileus_tube_placement": ProcedureMeta(_SCT_CATEGORY_THERAPEUTIC, "26107004"),  # small intestine
    "bowel_resection": ProcedureMeta(_SCT_CATEGORY_SURGICAL, "30315005"),  # large intestine
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
    # CO-3: ED-typical procedures. CPT codes verified
    # (AMA CPT 2024). K-codes intentionally BLANK — MHLW authoritative
    # verification deferred to a separate chain (mirrors cycle 2 C2-15 YJ
    # policy: no fabrication).  A subsequent chain will populate K-codes
    # from the MHLW 診療報酬点数表 master and re-verify each entry.
    ("ecg_12lead", "93000", "", "12-lead ECG", "12誘導心電図", "none"),
    ("iv_line", "96360", "", "IV line placement", "末梢静脈路確保", "local"),
    ("wound_care", "12001", "", "Simple wound repair", "創傷処理", "local"),
    ("short_arm_splint", "29075", "", "Short arm splint", "短腕シーネ固定", "none"),
    ("reduction_closed", "25605", "", "Closed reduction of wrist fracture", "手関節骨折徒手整復", "local"),
    ("oxygen_therapy", "94640", "", "Oxygen therapy (nebulizer)", "酸素療法", "none"),
    # Issue #939: cardiology / neurosurgery / GI-obstruction interventions.
    # JP codes verified against MHLW 診療報酬点数表 (令和6年度); CPT descriptors
    # from AMA CPT 2024. Each of these five entries has its dispatch drawn
    # from a per-encounter sub-RNG (issue939_procedure_seed) so the additive
    # emissions do NOT cascade the shared patient-scoped stream.
    ("coronary_pci", "92920", "K546", "Percutaneous coronary intervention (PCI)", "経皮的冠動脈形成術", "local"),
    (
        "pacemaker_implant",
        "33208",
        "K597",
        "Permanent pacemaker implantation",
        "ペースメーカー移植術",
        "local",
    ),
    (
        "craniotomy_hematoma_evacuation",
        "61312",
        "K164-1",
        "Craniotomy for intracranial hematoma evacuation",
        "頭蓋内血腫除去術（開頭）",
        "general",
    ),
    (
        "ileus_tube_placement",
        "44500",
        "J034-2",
        "Long tube (ileus tube) placement for bowel obstruction",
        "イレウス用ロングチューブ挿入法",
        "none",
    ),
    ("bowel_resection", "44140", "K719", "Colectomy (bowel resection)", "結腸切除術", "general"),
]

# Rules: (disease_id or category) → [(procedure_type, probability)]
# category keywords checked against disease_id
_PROCEDURE_RULES: list[tuple[str | list[str], list[tuple[str, float]]]] = [
    # Universal: urinary catheter for severe patients
    (
        [
            "sepsis",
            "acute_mi",
            "heart_failure",
            "cerebral_infarction",
            "hemorrhagic_stroke",
            "subdural_hematoma",
            "traffic_accident_severe",
        ],
        [("urinary_catheter", 0.85)],
    ),
    # Moderate-severe inpatients: urinary catheter
    (
        [
            "copd_exacerbation",
            "gi_bleeding",
            "acute_pancreatitis",
            "diabetic_ketoacidosis",
            "liver_cirrhosis_decompensated",
            "pulmonary_embolism",
            "acute_kidney_injury",
        ],
        [("urinary_catheter", 0.50)],
    ),
    # Sepsis / critical: central line, arterial line
    (["sepsis"], [("central_line", 0.70), ("arterial_line", 0.50), ("blood_transfusion", 0.15)]),
    # Heart failure: echocardiography
    (["heart_failure_exacerbation"], [("echocardiography", 0.80), ("urinary_catheter", 0.60)]),
    # Acute MI: arterial line, echo
    (["acute_mi"], [("arterial_line", 0.60), ("central_line", 0.40), ("echocardiography", 0.90)]),
    # Stroke: nasogastric tube (dysphagia risk), lumbar puncture
    (["cerebral_infarction", "hemorrhagic_stroke"], [("nasogastric_tube", 0.30), ("echocardiography", 0.50)]),
    # Hemorrhagic stroke / subdural: intubation. Same 2-disease pair as
    # `NEURO_LOC_MONITORING_DISEASES` — kept as `list(...)` because the outer
    # rule table's item type is `list[str]`, but membership stays synced with
    # the canonical set.
    (
        list(NEURO_LOC_MONITORING_DISEASES),
        [("intubation", 0.40), ("central_line", 0.50), ("arterial_line", 0.40)],
    ),
    # GI bleeding: nasogastric tube, blood transfusion
    (["gi_bleeding"], [("nasogastric_tube", 0.50), ("blood_transfusion", 0.60), ("central_line", 0.30)]),
    # Liver cirrhosis: paracentesis, nasogastric tube
    (
        ["liver_cirrhosis_decompensated"],
        [("paracentesis", 0.70), ("nasogastric_tube", 0.25), ("blood_transfusion", 0.30)],
    ),
    # Pneumonia/aspiration: bronchoscopy in severe cases
    (["bacterial_pneumonia", "aspiration_pneumonia"], [("bronchoscopy", 0.15), ("intubation", 0.10)]),
    # DKA: central line, arterial line
    (["diabetic_ketoacidosis"], [("central_line", 0.35), ("arterial_line", 0.20)]),
    # Pulmonary embolism: echo
    (["pulmonary_embolism"], [("echocardiography", 0.70), ("central_line", 0.20)]),
    # Ileus: nasogastric tube
    (["ileus"], [("nasogastric_tube", 0.80)]),
    # AKI: dialysis in severe cases
    (["acute_kidney_injury"], [("dialysis_acute", 0.30), ("central_line", 0.40)]),
    # Atrial fibrillation: cardioversion, echo
    (["atrial_fibrillation_rvr"], [("cardioversion", 0.25), ("echocardiography", 0.60)]),
    # Pancreatitis: nasogastric tube
    (["acute_pancreatitis"], [("nasogastric_tube", 0.40), ("central_line", 0.20)]),
    # Trauma: central line, arterial line, blood transfusion
    (
        ["traffic_accident_severe"],
        [
            ("central_line", 0.70),
            ("arterial_line", 0.60),
            ("blood_transfusion", 0.50),
            ("intubation", 0.30),
            ("chest_tube", 0.25),
        ],
    ),
    # Cellulitis with severe: wound debridement
    (["cellulitis"], [("wound_debridement", 0.30)]),
    # CO-3: ED-specific rules keyed on ED condition_ids.
    # Aligned with JP-common ED workflow; probabilities from clinical practice
    # (JEMS 2022 protocols).
    (["chest_pain", "syncope", "arrhythmia", "acute_coronary_syndrome_ed"], [("ecg_12lead", 0.98), ("iv_line", 0.85)]),
    (
        ["wrist_fracture", "ankle_fracture", "distal_radius_fracture"],
        [("reduction_closed", 0.55), ("short_arm_splint", 0.85)],
    ),
    (["laceration", "minor_wound"], [("wound_care", 0.90)]),
    (["viral_gastroenteritis", "dehydration", "acute_gastritis"], [("iv_line", 0.70)]),
    (["asthma_exacerbation_ed", "copd_exacerbation_ed"], [("oxygen_therapy", 0.80), ("iv_line", 0.60)]),
    (["head_injury_minor", "concussion"], [("iv_line", 0.50)]),
]


# Issue #939 — cardiology / neurosurgery / GI-obstruction interventions.
# Kept in a SEPARATE dispatch table (not `_PROCEDURE_RULES`) because these
# five procedures draw from a per-(encounter, proc_type) sub-RNG
# (`issue939_procedure_seed`) instead of the shared patient-scoped `rng`.
# Splitting the tables lets the shared-rng loop stay byte-identical for
# every disease_id — only the isolated loop below consumes new randomness,
# and it draws from a stream that no other consumer touches.
#
# Baseline probabilities align with the "Expected behavior" section of
# Issue #939: PCI ~85% of MI, pacemaker ~10% of HFrEF admits, craniotomy
# ~35% of surgical-candidate ICH, ileus tube ~60% conservative-management,
# bowel resection ~20% failed-conservative. Tuned probabilities live here
# rather than in yaml for parity with `_PROCEDURE_RULES`; a future scope
# item can migrate both tables to a shared per-disease dispatch yaml.
_ISSUE939_PROCEDURE_RULES: list[tuple[list[str], list[tuple[str, float]]]] = [
    # Acute MI — primary PCI is standard-of-care for STEMI/NSTEMI.
    (["acute_mi"], [("coronary_pci", 0.85)]),
    # Heart failure exacerbation — CRT/pacemaker/ICD implanted in a
    # minority of HFrEF admits (JCS guideline ~10-15% overall uptake).
    (["heart_failure_exacerbation"], [("pacemaker_implant", 0.10)]),
    # Intracerebral / subdural hemorrhage — surgical evacuation for the
    # portion who meet JSNS criteria (deep/moderate volume + declining LOC).
    (["hemorrhagic_stroke", "subdural_hematoma"], [("craniotomy_hematoma_evacuation", 0.35)]),
    # Bowel obstruction / ileus — long tube first-line; resection for
    # failed conservative management (~20% escalation rate).
    (["ileus"], [("ileus_tube_placement", 0.60), ("bowel_resection", 0.20)]),
]

# Procedure types dispatched from `_ISSUE939_PROCEDURE_RULES` — used to guard
# against accidental duplication into `_PROCEDURE_RULES` in future edits.
_ISSUE939_PROCEDURE_TYPES: frozenset[str] = frozenset(
    proc_type for _match, rules in _ISSUE939_PROCEDURE_RULES for proc_type, _prob in rules
)


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
    severity_mult = {
        "severe": BEDSIDE_SEVERITY_SEVERE_MULTIPLIER,
        "moderate": BEDSIDE_SEVERITY_MODERATE_MULTIPLIER,
        "mild": BEDSIDE_SEVERITY_MILD_MULTIPLIER,
    }.get(severity, BEDSIDE_SEVERITY_MULTIPLIER_FALLBACK)
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

        _, cpt, kcode, _name_en, _name_ja, anesthesia = spec
        # CO-3 review: when JP export and no authoritative K-code
        # is registered, skip emission rather than emit an empty code (broken
        # FHIR). Mirrors the cycle 2 no-fabrication policy — real K-codes will
        # land when the MHLW verification chain populates them.
        if is_jp(country) and not kcode:
            continue
        code = kcode if is_jp(country) else cpt
        # Names not stored — FHIR adapter resolves via code_lookup (AD-30)

        # Timing: most bedside procedures happen within first 24h
        hours_offset = max(BEDSIDE_HOURS_OFFSET_MIN, float(rng.exponential(BEDSIDE_HOURS_OFFSET_EXPONENTIAL_MEAN)))
        proc_time = admission_time + timedelta(hours=hours_offset)
        duration = int(max(BEDSIDE_DURATION_MIN_MIN, rng.normal(BEDSIDE_DURATION_MEAN_MIN, BEDSIDE_DURATION_STD_MIN)))

        meta = _PROCEDURE_METADATA.get(proc_type)
        record = ProcedureRecord(
            procedure_id=f"PROC-{patient_id}-{proc_idx + 2:03d}",
            patient_id=patient_id,
            encounter_id=encounter_id,
            procedure_type=proc_type,
            procedure_code=code,
            procedure_code_jp=kcode,
            procedure_code_us=cpt,
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

    # Issue #939 — isolated sub-RNG loop for cardiology / neurosurgery /
    # GI-obstruction interventions. Runs AFTER the shared-rng loop so
    # `proc_idx` continues incrementing (procedure_id uniqueness) but the
    # per-encounter sub-RNG does not touch the shared patient stream.
    for disease_match, proc_list in _ISSUE939_PROCEDURE_RULES:
        if disease_id not in disease_match:
            continue
        for proc_type, base_prob in proc_list:
            sub_rng = determinism.default_rng(issue939_procedure_seed(encounter_id, proc_type))
            prob = min(1.0, base_prob * severity_mult)
            if sub_rng.random() >= prob:
                continue
            spec = proc_lookup.get(proc_type)
            if not spec:
                continue

            _, cpt, kcode, _name_en, _name_ja, anesthesia = spec
            if is_jp(country) and not kcode:
                continue
            code = kcode if is_jp(country) else cpt

            hours_offset = max(
                BEDSIDE_HOURS_OFFSET_MIN,
                float(sub_rng.exponential(BEDSIDE_HOURS_OFFSET_EXPONENTIAL_MEAN)),
            )
            proc_time = admission_time + timedelta(hours=hours_offset)
            duration = int(
                max(
                    BEDSIDE_DURATION_MIN_MIN,
                    sub_rng.normal(BEDSIDE_DURATION_MEAN_MIN, BEDSIDE_DURATION_STD_MIN),
                )
            )

            meta = _PROCEDURE_METADATA.get(proc_type)
            record = ProcedureRecord(
                procedure_id=f"PROC-{patient_id}-{proc_idx + 2:03d}",
                patient_id=patient_id,
                encounter_id=encounter_id,
                procedure_type=proc_type,
                procedure_code=code,
                procedure_code_jp=kcode,
                procedure_code_us=cpt,
                start_datetime=proc_time,
                end_datetime=proc_time + timedelta(minutes=duration),
                duration_minutes=duration,
                primary_surgeon_id="",
                anesthesia_type=anesthesia,
                category_code=meta.category_code if meta else _SCT_CATEGORY_SURGICAL,
                body_site_code=meta.body_site_code if meta else "",
                outcome_code=_SCT_OUTCOME_SUCCESS,
                complication_codes=[],
                location_id="",
            )
            results.append(record)
            proc_idx += 1

    return results


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
    start_day = REHAB_START_POD
    duration = REHAB_JP_SESSION_DURATION_MIN if is_jp(country) else REHAB_US_SESSION_DURATION_MIN

    activities_by_phase = {
        "early": ["bed exercises", "sitting up", "standing with assist"],
        "mid": ["walker ambulation", "stair practice", "transfer training"],
        "late": ["independent ambulation", "ADL practice", "stair climbing"],
    }

    for day_offset in range(start_day, total_days):
        # Skip some days randomly (weekend reduction, patient fatigue)
        if rng.random() < REHAB_SKIP_DAY_PROBABILITY:
            continue

        # Determine phase
        if day_offset <= REHAB_PHASE_EARLY_MAX_POD:
            phase = "early"
        elif day_offset <= REHAB_PHASE_MID_MAX_POD:
            phase = "mid"
        else:
            phase = "late"

        activities = list(
            rng.choice(activities_by_phase[phase], size=min(3, len(activities_by_phase[phase])), replace=False)
        )  # noqa: E501

        pain = int(
            max(
                REHAB_PAIN_MIN_SCORE,
                min(
                    REHAB_PAIN_MAX_SCORE,
                    rng.normal(REHAB_PAIN_BASE_SCORE - day_offset * REHAB_PAIN_DECAY_PER_POD, REHAB_PAIN_STD),
                ),
            )
        )

        participation = "good"
        if pain > REHAB_PAIN_FAIR_PARTICIPATION_THRESHOLD:
            participation = "fair"
        if rng.random() < REHAB_REFUSAL_PROBABILITY:
            participation = "refused"

        progress = "improved" if day_offset > REHAB_IMPROVED_MIN_POD else "stable"
        if participation == "refused":
            progress = "unable_to_assess"

        session = RehabSession(
            session_id=f"REHAB-{patient_id}-{day_offset:03d}",
            patient_id=patient_id,
            encounter_id=encounter_id,
            therapy_type="PT",
            session_date=surgery_date + timedelta(days=day_offset, hours=REHAB_SESSION_START_HOUR),
            duration_minutes=duration,
            day_post_op=day_offset,
            activities=activities,
            patient_participation=participation,
            pain_score=pain,
            functional_progress=progress,
        )
        sessions.append(session)

    return sessions
