"""Disease protocol loader and data structures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

# reference_data is in the same package: clinosim/modules/disease/reference_data/
_REFERENCE_DATA_DIR = Path(__file__).parent / "reference_data"


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


def load_disease_protocol(disease_id: str) -> DiseaseProtocol:
    """Load a disease protocol YAML and validate."""
    filename = f"{disease_id}.yaml"
    protocol_path = _REFERENCE_DATA_DIR / filename
    if not protocol_path.exists():
        raise FileNotFoundError(f"Disease protocol not found: {protocol_path}")

    with open(protocol_path) as f:
        data = yaml.safe_load(f)

    return DiseaseProtocol(**data)
