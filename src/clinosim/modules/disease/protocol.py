"""Disease protocol loader and data structures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

# reference_data is at project root: clinosim/modules/disease/reference_data/
_REFERENCE_DATA_DIR = Path(__file__).parent.parent.parent.parent.parent / "modules" / "disease" / "reference_data"


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


def load_disease_protocol(disease_id: str) -> DiseaseProtocol:
    """Load a disease protocol YAML and validate."""
    filename = f"{disease_id}.yaml"
    protocol_path = _REFERENCE_DATA_DIR / filename
    if not protocol_path.exists():
        raise FileNotFoundError(f"Disease protocol not found: {protocol_path}")

    with open(protocol_path) as f:
        data = yaml.safe_load(f)

    return DiseaseProtocol(**data)
