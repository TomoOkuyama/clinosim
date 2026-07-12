"""Clinical state types — physiological state, state changes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

# Deliberately obvious non-real sentinel — replaces the former datetime.now()/
# date.today() default that made byte-diff output depend on wall-clock
# execution time (determinism chain, 2026-07-04). Fields using this default
# are either always overridden by the caller or never read downstream; if
# this value surfaces in real output, that indicates a missing override.
_UNSET_DATETIME = datetime(1970, 1, 1)
_UNSET_DATE = date(1970, 1, 1)


@dataclass
class PhysiologicalState:
    """Snapshot of all hidden state variables at a point in time."""

    timestamp: datetime = field(default_factory=lambda: _UNSET_DATETIME)
    patient_id: str = ""

    inflammation_level: float = 0.03  # 0.0–1.0
    renal_function: float = 1.0  # 0.0–1.0
    cardiac_function: float = 1.0  # 0.0–1.0
    hepatic_function: float = 1.0  # 0.0–1.0
    anemia_level: float = 0.0  # 0.0–1.0
    coagulation_status: float = 0.0  # 0.0–1.0
    volume_status: float = 0.0  # -1.0–+1.0
    perfusion_status: float = 1.0  # 0.0–1.0
    ph_status: float = 0.0  # -1.0–+1.0  (acid-base disturbance magnitude; neg = acidemia)
    # Routes the ph_status disturbance between the metabolic (HCO3) and respiratory (pCO2)
    # axes: 0.0 = purely metabolic (e.g. DKA, lactic acidosis, uremia), 1.0 = purely
    # respiratory (e.g. COPD/asthma CO2 retention). Set from the disease scenario's
    # acid_base_type or the patient's chronic respiratory conditions. AD-57.
    respiratory_fraction: float = 0.0  # 0.0–1.0
    # Anion gap axis. Distinct from ph_status (acid-base magnitude) and
    # respiratory_fraction (metabolic vs respiratory routing). Drives the Cl
    # axis only — does NOT mutate pH/HCO3/pCO2 or feed apply_coupling_rules.
    #  0.0 = normal AG (8-12 mEq/L), Cl follows HCO3 1:1 when HCO3 drops
    #        (default healthy and most non-acid-base diseases)
    # +1.0 = high-AG metabolic acidosis (DKA/sepsis/uremia/lactic). Unmeasured
    #        anion (ketone/lactate/SO4/PO4) absorbs the HCO3 deficit, so Cl
    #        stays near normal even with low HCO3.
    # -1.0 = non-AG hyperchloremic acidosis (diarrhea, RTA, saline-induced).
    #        Cl rises 1:1 with HCO3 deficit to maintain electroneutrality.
    anion_gap_status: float = 0.0  # -1.0 to +1.0
    # Acute glycemic state: 0.0 = euglycemia, positive = hyperglycemia (DKA/HHS drives this
    # up, e.g. 0.6 ≈ 300–500 mg/dL), negative = hypoglycemia. Distinct from the chronic
    # diabetes baseline (has_diabetes). Set from the disease scenario. AD-57.
    glucose_status: float = 0.0  # -1.0–+1.0
    sodium_status: float = 0.0  # -1.0–+1.0  (neg = hyponatremia, pos = hypernatremia)
    # Chronic glycemic control for diabetics: 1.0 = excellent (HbA1c ~6%), 0.0 = very poor
    # (HbA1c ~12%). None = non-diabetic. Patient-stable; seeded from the E11 ChronicCondition
    # by initialize_state and NOT moved by acute disease onset (HbA1c is a ~3-month average).
    glycemic_control: float | None = None


@dataclass
class StateChangeDirective:
    """Instruction to update physiological state variables."""

    timestamp: datetime = field(default_factory=lambda: _UNSET_DATETIME)
    patient_id: str = ""
    source: str = ""  # "disease_progression" | "treatment_effect" | "complication"
    changes: dict[str, float] = field(default_factory=dict)
    reason: str = ""


@dataclass
class ConditionEvent:
    """What actually happens to the patient (hidden ground truth). AD-28.

    This is the TRUE cause of the patient's condition, which may or may not
    be correctly identified by the clinical process.
    """

    condition_id: str = ""
    condition_type: str = "known_disease"  # "known_disease" | "mixed" | "unknown"

    # For known_disease / mixed: the actual diseases driving state changes
    ground_truth_diseases: list[str] = field(default_factory=list)

    # For unknown: the symptom pattern without identified cause
    symptom_pattern: str = ""  # "fever_unknown" | "weight_loss" | "malaise"

    # Combined state impact from all causes (applied to physiology)
    state_impacts: dict[str, float] = field(default_factory=dict)

    # Presenting symptoms (what the patient reports)
    presenting_symptoms: list[dict] = field(default_factory=list)


@dataclass
class ClinicalDiagnosis:
    """What the hospital concludes (may differ from ground truth). AD-28.

    This is the diagnosis as recorded in the EHR — the clinical output,
    not the hidden truth. CIF stores ONLY codes; display text is resolved
    at output time via the clinosim.codes module.
    """

    admission_diagnosis_code: str = ""  # ICD at admission (often vague: R50.9, J18.9)
    admission_diagnosis_system: str = "icd-10-cm"  # code system key
    working_diagnoses: list[dict] = field(default_factory=list)  # [{code, day, confidence}]
    discharge_diagnosis_code: str = ""  # ICD at discharge
    discharge_diagnosis_system: str = "icd-10-cm"

    # Hidden fields (in CIF, not in clinical output)
    diagnosis_correct: bool = True  # does discharge dx match ground truth?
    missed_diagnoses: list[str] = field(default_factory=list)  # ground truth not identified
    overcalled_diagnoses: list[str] = field(default_factory=list)  # diagnosed but not present


@dataclass
class ClinicalDocumentNarrative:
    """Narrative subtree of a ClinicalDocument (AD-65).

    Serialization boundary:
      - Written to cif/narratives/<version>/documents/<enc>/<doc_type>.json
      - NEVER written to structural CIF (cif_writer strips this)
      - Loaded and merged by CIFReader at FHIR emit time.
    """

    text: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    structured: dict = field(default_factory=dict)
    generator: str = "none"
    generator_metadata: dict = field(default_factory=dict)
    generated_at: str = ""
    facts_used: list[str] = field(default_factory=list)


@dataclass
class ClinicalDocument:
    """Two-pass lifecycle (AD-65):
    1. document_enricher (POST_ENCOUNTER) creates stub with narrative=None.
    2. TemplateNarrativePass populates `narrative`.
    3. CIFReader merges structural + narrative before FHIR emit.
    """

    document_id: str = ""
    task_type: str = ""  # LLMTaskType value
    loinc_code: str = ""  # e.g. "18842-5"
    patient_id: str = ""
    encounter_id: str = ""
    author_practitioner_id: str = ""
    related_procedure_id: str = ""  # set for operative_note / procedure_note
    authored_datetime: str = ""  # ISO 8601
    period_start: str = ""
    period_end: str = ""
    language: str = "en"
    content_type: str = "text/plain; charset=utf-8"
    format_type: str = ""
    # α-min-3: neutral nursing shift key ("night" / "day" / "evening") for
    # daily_3shift documents; "" for all other frequencies. Metadata only —
    # localized labels (日勤/準夜/深夜) are resolved at Stage 2 render time
    # by language (AD-30 spirit: no display text in structural CIF).
    shift: str = ""
    # P2-13 PR3 sub-PR-D(session 47):JP-eCheckup 健診種別。
    # HEALTH_CHECKUP_REPORT stub 以外は "" のまま。値:
    #   "occupational"   → 事業者健診(section 01031/01032)
    #   "specific"       → 特定健診(section 01011/01012)
    #   "regional_union" → 広域連合健診(section 01021/01022)
    # health_checkup enricher が患者年齢から決定的に選択する。
    checkup_type: str = ""
    narrative: ClinicalDocumentNarrative | None = None


@dataclass
class NarrativeVersionManifest:
    """cif/narratives/<version>/manifest.json shape."""

    version_id: str
    generator: str
    generator_config: dict
    generated_at: str
    encounter_count: int
    document_count: int
    document_counts_by_type: dict[str, int]
    doc_types_enabled: list[str]
    languages_used: list[str]
    llm_cost_report: dict
    # β-JP-1 chain 1b T3: regex passed via `narrate --patient-filter` ("" =
    # full cohort). Recorded so a partial version is self-describing —
    # `regenerate-goldens` refuses filters, and consumers can detect that a
    # version does not cover the whole cohort.
    patient_filter: str = ""
    # β-JP-1 chain 1b adv-1 I-1: True ⇔ patient_filter was set for this run.
    # Cheap partial-version detection for downstream consumers (export
    # guards, tooling) without inspecting the regex string.
    partial: bool = False


@dataclass
class ClinicalImpressionRecord:
    """Daily working diagnosis update(Tier 1 #3 α-min-1).

    FHIR ClinicalImpression resource への source data。
    入院 daily emit、CIFPatientRecord.extensions["clinical_impressions"]
    に格納(AD-55 Module pattern)。
    """

    impression_id: str = ""  # "ci-{enc}-{day}"
    encounter_id: str = ""
    date: date = field(default_factory=lambda: _UNSET_DATE)
    day_index: int = 0
    description: str = ""  # 短い要約
    summary: str = ""  # 詳細
    investigation_refs: list[str] = field(default_factory=list)  # Observation id refs
    finding_refs: list[str] = field(default_factory=list)  # Condition id refs
    prognosis: str = ""
    practitioner_id: str = ""  # 主治医
    # AD-32 snapshot semantics: True only for the current (latest) day of an in-progress
    # encounter. All prior days remain "completed" (clinical picture was fully documented).
    # Drives ClinicalImpression.status "in-progress" vs "completed" in _fhir_clinical_impression.py.
    is_in_progress: bool = False
