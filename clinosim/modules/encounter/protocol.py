"""Encounter condition protocol loader — YAML-driven ED/outpatient conditions."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


# ---------------------------------------------------------------------------
# Narrative spec — Tier 1 #3 α-min-2 Task 6
# ---------------------------------------------------------------------------


class OutpatientSoapTemplate(BaseModel):
    """Outpatient SOAP note template fields for narrative generation."""

    subjective_ja: str = ""
    objective_ja: str = ""
    assessment_ja: str = ""
    plan_ja: str = ""


class EdPhysicalExam(BaseModel):
    """ED physical exam section templates."""

    general: str = ""
    cardiovascular: str = ""
    respiratory: str = ""
    abdominal: str = ""
    neurological: str = ""
    musculoskeletal: str = ""


class EdNoteTemplate(BaseModel):
    """ED physician note template fields for narrative generation."""

    chief_complaint_ja: str = ""
    hpi_ja: str = ""
    physical_exam_ja: EdPhysicalExam = Field(default_factory=EdPhysicalExam)
    ed_workup_summary_ja: str = ""
    disposition_ja: str = ""


class EdTriageTemplate(BaseModel):
    """ED triage template — common ESI/JTAS triage levels for this condition."""

    common_triage_levels: list[str] = Field(default_factory=list)


class EncounterNarrativeSpec(BaseModel):
    """α-min-2 encounter narrative wrapper.

    Only the sub-block relevant to the encounter type is populated:
    - outpatient: ``outpatient_soap_template``
    - emergency: ``ed_note_template`` + ``ed_triage_template``
    """

    outpatient_soap_template: OutpatientSoapTemplate | None = None
    ed_note_template: EdNoteTemplate | None = None
    ed_triage_template: EdTriageTemplate | None = None


# ---------------------------------------------------------------------------
# Protocol model
# ---------------------------------------------------------------------------


class EncounterConditionProtocol(BaseModel):
    """Loaded encounter (ED/outpatient) condition protocol from YAML.

    Validated by Pydantic (AD-18), mirroring DiseaseProtocol's in-module
    placement. Only the structurally essential fields are declared required;
    everything else is accepted permissively via ``extra="allow"`` so the rich,
    condition-specific sections (workup, treatment, etc.) pass through untouched.
    """

    model_config = ConfigDict(extra="allow")

    condition_id: str
    icd10_code: str
    chief_complaint: str | dict[str, str]  # str or {en: "...", ja: "..."}
    encounter_type: str
    department: str

    # Narrative spec (Tier 1 #3 α-min-2 Task 6): per-encounter-type narrative
    # templates.  Optional default = None so existing encounter YAMLs without a
    # narrative: block continue to validate without error.
    narrative: EncounterNarrativeSpec | None = None


def load_encounter_condition(condition_id: str) -> dict[str, Any]:
    """Load and validate a single encounter condition YAML.

    Returns the raw dict (callers expect a dict); validation guards against
    malformed YAML by raising a clear Pydantic error.
    """
    path = _REF_DIR / f"{condition_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Encounter condition not found: {path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    EncounterConditionProtocol.model_validate(data)
    return data


@lru_cache(maxsize=1)
def load_all_encounter_conditions() -> dict[str, dict[str, Any]]:
    """Auto-discover, validate, and load all encounter condition YAMLs. Cached."""
    conditions: dict[str, dict[str, Any]] = {}
    for yaml_file in sorted(_REF_DIR.glob("*.yaml")):
        data = yaml.safe_load(yaml_file.read_text())
        try:
            EncounterConditionProtocol.model_validate(data)
        except Exception as exc:  # narrow re-raise with offending filename
            raise ValueError(f"Invalid encounter condition YAML: {yaml_file.name}") from exc
        cid = data.get("condition_id", yaml_file.stem)
        conditions[cid] = data
    return conditions
