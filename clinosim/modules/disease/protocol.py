"""Disease protocol loader and data structures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# reference_data is in the same package: clinosim/modules/disease/reference_data/
_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


# ---------------------------------------------------------------------------
# Narrative spec models (Tier 1 #3 α-min-1 Task 4)
# ---------------------------------------------------------------------------


class PhysicalExamSystemFindings(BaseModel):
    """Severity-stratified physical exam findings for a single organ system.

    Use ``all`` for severity-agnostic findings (e.g. "整、心雑音なし").
    Use ``mild`` / ``moderate`` / ``severe`` for severity-specific wording.
    """

    mild: str = ""
    moderate: str = ""
    severe: str = ""
    all: str | None = None  # severity-agnostic override


class PhysicalExamDayFindings(BaseModel):
    """Physical exam findings for a single clinical day grouped by organ system."""

    general: PhysicalExamSystemFindings = Field(default_factory=PhysicalExamSystemFindings)
    cardiovascular: PhysicalExamSystemFindings = Field(
        default_factory=PhysicalExamSystemFindings
    )
    respiratory: PhysicalExamSystemFindings = Field(default_factory=PhysicalExamSystemFindings)
    abdominal: str = ""
    neurological: str = ""


class HpiTemplate(BaseModel):
    """HPI (history of present illness) template parameters."""

    onset_pattern: dict[str, str] = Field(default_factory=dict)  # mild/moderate/severe → text
    trigger_options: list[str] = Field(default_factory=list)


class DischargeInstructions(BaseModel):
    """Discharge instruction texts keyed by language (``en`` / ``ja``)."""

    follow_up: dict[str, str] = Field(default_factory=dict)
    activity: dict[str, str] = Field(default_factory=dict)
    medications: dict[str, str] = Field(default_factory=dict)
    emergency: dict[str, str] = Field(default_factory=dict)
    diet_lifestyle: dict[str, str] = Field(default_factory=dict)


class NarrativeSpec(BaseModel):
    """Top-level narrative specification stored under ``DiseaseProtocol.narrative``.

    Consumed by TemplateNarrativeGenerator (Task 6) to produce per-disease
    clinical narratives rather than generic boilerplate.
    ``physical_exam_findings`` maps:  archetype_name → day_str → PhysicalExamDayFindings
    """

    hpi_template: HpiTemplate = Field(default_factory=HpiTemplate)
    physical_exam_findings: dict[str, dict[str, PhysicalExamDayFindings]] = Field(
        default_factory=dict
    )
    discharge_instructions: DischargeInstructions = Field(default_factory=DischargeInstructions)


class DailyTrajectoryEntry(BaseModel):
    """SOAP-structured clinical note entry for a single inpatient day."""

    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""


class ImagingOrderSpec(BaseModel):
    """Imaging order entry inside DiseaseProtocol (Tier 1 #2 PR1).

    One entry = one imaging study ordered at a specific day in the admission.
    The imaging enricher (Task 4) uses ``abnormal_rate_by_severity`` to sample
    whether the study is normal or abnormal and pick an impression template.
    """

    modality: str
    body_site: str
    views: list[str] = Field(default_factory=list)
    urgency: str = "routine"
    clinical_indication: str = ""
    day: int = 0
    contrast: bool = False
    only_if_severity: list[str] = Field(default_factory=list)
    abnormal_rate_by_severity: dict[str, float] = Field(default_factory=dict)


class DiseaseProtocol(BaseModel):
    """Loaded disease protocol from YAML. Validated by Pydantic."""

    disease_id: str
    icd_codes: dict[str, Any]
    incidence: dict[str, Any]
    severity: dict[str, Any]
    presenting_symptoms: list[dict[str, Any]] = []
    course_archetypes: dict[str, Any] = {}
    initial_state_impact: dict[str, dict[str, float]] = {}
    diagnostic: dict[str, Any] = {}
    order_protocols: dict[str, Any] = {}
    target_los: dict[str, Any] = {}
    complications: list[dict[str, Any]] = []
    readmission: dict[str, Any] = {}
    likelihood_ratios: dict[str, Any] = {}
    expected_lab_distributions: dict[str, Any] = {}
    expected_vital_distributions: dict[str, Any] = {}
    drugs: dict[str, Any] = {}
    drug_interactions: list[dict[str, Any]] = []
    reference_ranges: dict[str, Any] = {}
    outcome_benchmarks: dict[str, Any] = {}

    # Disease metadata (eliminates hardcoding in simulator)
    chief_complaint: str | dict[str, str] = ""  # str or {en: "...", ja: "..."}
    department: str = "internal_medicine"
    encounter_type: str = "medical"  # "medical" | "surgical" | "trauma"
    requires_surgery: bool = False
    minimum_severity: str | None = None  # force minimum severity (e.g. "moderate" for fracture)
    readmission_eligible: bool = True  # False for surgical conditions like fractures
    procedure: dict[str, Any] = {}  # Surgical procedure details (approach, duration, etc.)
    medication_holds: list[dict[str, Any]] = []  # Home medications to hold during this admission
    # Acute coronary syndrome → primary myocardial necrosis (drives high troponin/CK-MB,
    # vs the mild type-2 elevation any cardiac dysfunction produces). AD-55.
    causes_myocardial_injury: bool = False
    # VTE-spectrum scenario flag (PE / DVT / embolic ischemic stroke): pushes
    # D-dimer into the clinically positive range. NOT for hemorrhagic_stroke
    # (intracerebral fibrinolysis is captured by coagulation_status alone),
    # and NOT for AF / sepsis / COPD that order D-dimer to screen for
    # complications — their D-dimer rises only via inflammation / DIC. Phase 2a.
    causes_vte: bool = False
    # Primary acid-base disturbance mechanism — routes the scenario's ph_status between the
    # metabolic (HCO3) and respiratory (pCO2) axes so blood gas + compensation are coherent
    # (e.g. DKA = metabolic → Kussmaul low pCO2; COPD = respiratory → compensatory high
    # HCO3). "metabolic" | "respiratory" | "mixed". AD-57.
    acid_base_type: str = "metabolic"
    # Chronic glycemic control implied by the scenario (1.0=excellent .. 0.0=very poor).
    # When set (e.g. DKA/HHS imply long-standing poor control), the inpatient simulator
    # overrides the patient's sampled glycemic_control for this admission so HbA1c is
    # coherently high even for new-onset diabetes (no prior E11 condition). AD-57.
    chronic_glycemic_control: float | None = None
    # Imaging orders (Tier 1 #2 PR1, AD-56): list of imaging studies to place at
    # specified admission days. Optional default = [] so existing disease YAMLs without
    # imaging_orders: remain valid (no-op safe Pydantic optional field).
    imaging_orders: list[ImagingOrderSpec] = Field(default_factory=list)
    # Narrative spec (Tier 1 #3 α-min-1 Task 4): hpi_template, physical_exam_findings,
    # discharge_instructions.  Optional default = None so existing disease YAMLs without
    # a narrative: block continue to validate without error.
    narrative: NarrativeSpec | None = None


def load_disease_protocol(disease_id: str) -> DiseaseProtocol:
    """Load a disease protocol YAML and validate."""
    filename = f"{disease_id}.yaml"
    protocol_path = _REF_DIR / filename
    if not protocol_path.exists():
        raise FileNotFoundError(f"Disease protocol not found: {protocol_path}")

    with open(protocol_path) as f:
        data = yaml.safe_load(f)

    return DiseaseProtocol(**data)
