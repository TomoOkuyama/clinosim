"""Treatment / supportive order classification (canonical single-source).

Both inpatient disease-YAML ``supportive[]`` and encounter (ED/outpatient) YAML
``treatment[]`` items feed into ``Order`` records that flow downstream to
MedicationRequest / MedicationAdministration (MEDICATION) or Procedure
(PROCEDURE) or CarePlan-ish (THERAPY) FHIR resources.

Historically each call site (``modules/order/engine.py`` supportive loop and
``simulator/emergency.py`` treatment loop) carried its own inline keyword table.
The two lists diverged and encounter-YAML items like "Cardiac monitoring",
"Dark room rest", "Oral fluids encouraged", "Wound irrigation" leaked out as
MedicationRequest (J5 pattern — a rule that must fire in every venue but only
fires in one). This module owns the single keyword tables so any future
call site imports and cannot silently drift.

The classifier is intentionally text-based (display_name substring match) so
the same tables cover English encounter-YAML names and English disease-YAML
detail strings. Localization to JP happens later in the FHIR builder — the
classification decision is made once against the English source name.
"""

from __future__ import annotations

from clinosim.types.encounter import OrderType

PROCEDURE_KEYWORDS: tuple[str, ...] = (
    # Devices — worn / inserted / attached
    "cervical collar",
    "splint",
    "cast",
    "sling",
    "brace",
    "compression device",
    "sequential compression",
    "graduated compression",
    "ipc device",
    "compression stocking",
    "foley",
    "catheter placement",
    "catheter insertion",
    "endotracheal",
    "chest tube",
    "drain",
    "iv line",
    "ecg lead",
    "ekg lead",
    "tourniquet",
    # Ventilation / oxygen delivery devices
    "nppv",
    "cpap",
    "bipap",
    "non-invasive ventilation",
    "positive pressure",
    "mechanical ventilation",
    "intubation",
    "oxygen therapy",
    "oxygen supplementation",
    "nasal cannula",
    # Wound / skin manipulation
    "dressing",
    "bandage",
    "wound care",
    "wound clean",
    # Note: "wound assessment" intentionally NOT here — it's an observation /
    # documentation activity, classified as THERAPY via the "assessment" kw.
    "wound irrigation",
    "wound protection",
    "wound closure",
    "suture",
    "staple",
    "tissue adhesive",
    "wrap",
    "adhesive (",
    "packing",
    "cauterization",
    # Musculoskeletal manipulation
    "closed reduction",
    "reduction",
    "traction",
    "immobili",
    # Interventional procedures
    "endoscopy",
    "biopsy",
    "polypectomy",
    "hemodialysis",
    "dialysis",
    "foreign body removal",
    "rust ring removal",
    "vertebroplasty",
    "procedural sedation",
    # CY6-14 (Chain-6): CRRT — continuous renal replacement therapy is a
    # procedure regardless of how it's spelled. Both the canonical acronym
    # and the expanded form register here.
    "crrt",
    "continuous renal replacement",
    # Physical modalities (topical devices)
    "ice pack",
    "heat pack",
    "heat application",
    "cold application",
    # Nebulizer as a bare setup (nebulized DRUG matches "nebulized" NOT "nebulizer")
    "nebulizer",
    # Irrigation (physical intervention)
    "irrigation",
    # Spirometry setup itself (the drill vs the instruction — instruction → THERAPY,
    # bare spirometry / device → PROCEDURE)
)

# Strong THERAPY indicators — the detail text describes a protocol / clinical
# plan rather than a specific drug. Wins over MEDICATION_TYPE_HINTS so that
# `{type: "DVT_prophylaxis", detail: "therapeutic_anticoagulation ..."}` is
# classified as THERAPY even though DVT_prophylaxis is normally MEDICATION.
# Added in the C6-C7 residual sweep (2026-07-11) to stop plan text from
# emitting as MedicationRequest / MedicationAdministration.
PROTOCOL_TEXT_KEYWORDS: tuple[str, ...] = (
    "parkland formula",
    "parkland式",
    "therapeutic_anticoagulation",
    "therapeutic anticoagulation",
    "治療的抗凝固療法",
    "抗凝固療法 (置換",
    "anticoagulation (substitution",
    "replaces prophylactic",
    "置換 予防投与",
)


THERAPY_KEYWORDS: tuple[str, ...] = (
    # Observation / monitoring (non-invasive care plan)
    "monitoring",
    "observation",
    "surveillance",
    # Consultation / assessment / screening
    "consult",
    "consultation",
    "assessment",
    "screening",
    "evaluation",
    # Education / counseling
    "education",
    "counseling",
    "counselling",
    "interview",
    "reassurance",
    "instruction",
    # Rehab / exercise
    "exercise",
    "training",
    "gait",
    "range of motion",
    "modalities",
    "modality",
    "spirometry",
    # Rest / positioning / oral care
    "dark room rest",
    "bed rest",
    "rest",
    "oral fluids",
    "hydration encouraged",
    "fluid restriction",
    "elevation",
    # Medication review is not itself a medication order
    "medication review",
    "review and adjustment",
    # CY6-15 / CY6-16 (Chain-6): resuscitation formulas / therapeutic
    # protocols are care-plan instructions, not specific drug orders. The
    # underlying fluid (LR / NS) is placed as a separate ADM-M order.
    "parkland formula",
    "parkland式",
    "治療的抗凝固療法",
    "therapeutic anticoagulation",
    "抗凝固療法 (置換",
    "anticoagulation (substitution",
)

MEDICATION_TYPE_HINTS: frozenset[str] = frozenset(
    {
        "IV_fluid",
        "iv_fluid",
        "K_replacement",
        "antibiotic",
        "antipyretic",
        "DVT_prophylaxis",
        "PPI",
        "lactulose",
        "bronchodilator",
        "steroid",
        "iv_insulin",
        "IV_insulin",
        "anticoagulant",
        "vasopressor",
        "antiemetic",
        "analgesic",
        "pain_management",
        "rate_control",
        "anti_inflammatory",
        "thrombolytic",
        "diuretic",
    }
)

CARE_PLAN_TYPE_HINTS: frozenset[str] = frozenset(
    {
        "NPO",
        "fall_precautions",
        "BP_management",
        "neuro_checks",
        "bed_rest",
        "leg_elevation",
        "compression_stocking",
        "fluid_restriction",
        "sodium_restriction",
        "diet",
        "daily_weight",
        "monitoring",
        "continuous_telemetry",
        "HOB_elevation",
        "large_bore_IV",
        "glucose_check",
        "O2",
        "fluid_balance",
        "IV_fluid_restriction",
        "head_elevation",
        "spinal_precautions",
        "isolation",
        "wound_care",
    }
)


def _matches_keyword(text_lower: str, keywords: tuple[str, ...]) -> bool:
    return any(kw in text_lower for kw in keywords)


def classify_encounter_treatment(display_name: str) -> OrderType:
    """Classify an ED / encounter-YAML ``treatment[].name`` item.

    Encounter YAML treatments have no type hint — the display_name is the only
    signal. Default is MEDICATION because most treatment items are drugs
    (Acetaminophen, IV normal saline, Ondansetron, etc.). Explicit non-drug
    keywords override to PROCEDURE or THERAPY.

    Precedence: PROCEDURE_KEYWORDS > THERAPY_KEYWORDS > MEDICATION (default).
    """
    lowered = display_name.lower()
    if _matches_keyword(lowered, PROCEDURE_KEYWORDS):
        return OrderType.PROCEDURE
    if _matches_keyword(lowered, THERAPY_KEYWORDS):
        return OrderType.THERAPY
    return OrderType.MEDICATION


def classify_inpatient_supportive(display_name: str, type_hint: str) -> OrderType:
    """Classify an inpatient disease-YAML ``supportive[]`` item.

    Supportive items have both an explicit ``type`` field (e.g. ``IV_fluid``,
    ``continuous_telemetry``) and a free-text ``detail`` field. PROCEDURE
    keywords in detail override everything (a "DVT_prophylaxis" typed order
    whose detail is "Sequential compression device" is a device, not a drug).
    PROTOCOL_TEXT_KEYWORDS in detail also override the type hint — text like
    "Parkland formula" / "therapeutic_anticoagulation" describes a clinical
    plan, not a specific drug, so it should be THERAPY regardless of the
    (often-inherited) type field.
    Otherwise the type hint decides: MEDICATION types stay MEDICATION even
    if the detail contains an incidental THERAPY keyword ("consider medication
    review at day 3"), and CARE_PLAN types stay THERAPY. Only when the type
    hint is unknown do THERAPY keywords in the detail get a chance.

    Precedence: PROCEDURE_KEYWORDS > PROTOCOL_TEXT_KEYWORDS (THERAPY) >
    MEDICATION_TYPE_HINTS > CARE_PLAN_TYPE_HINTS > THERAPY_KEYWORDS >
    "drug" substring → MEDICATION > THERAPY.
    """
    lowered = display_name.lower()
    if _matches_keyword(lowered, PROCEDURE_KEYWORDS):
        return OrderType.PROCEDURE
    # C6-C7 residual sweep: plan-text overrides MEDICATION type_hint.
    if _matches_keyword(lowered, PROTOCOL_TEXT_KEYWORDS):
        return OrderType.THERAPY
    if type_hint in MEDICATION_TYPE_HINTS:
        return OrderType.MEDICATION
    if type_hint in CARE_PLAN_TYPE_HINTS:
        return OrderType.THERAPY
    if _matches_keyword(lowered, THERAPY_KEYWORDS):
        return OrderType.THERAPY
    if type_hint and "drug" in type_hint.lower():
        return OrderType.MEDICATION
    return OrderType.THERAPY
