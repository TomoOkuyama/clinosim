"""Encounter condition protocol loader — YAML-driven ED/outpatient conditions."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clinosim.datafiles import load_data_yaml

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


# ---------------------------------------------------------------------------
# Narrative spec — Tier 1 #3 α-min-2 Task 6
# ---------------------------------------------------------------------------


class OutpatientSoapTemplate(BaseModel):
    """Outpatient SOAP note template fields for narrative generation. Each
    field is a language map (Issue #2507)."""

    subjective: dict[str, str] = Field(default_factory=dict)
    objective: dict[str, str] = Field(default_factory=dict)
    assessment: dict[str, str] = Field(default_factory=dict)
    plan: dict[str, str] = Field(default_factory=dict)


class EdPhysicalExam(BaseModel):
    """ED physical exam section templates."""

    general: str = ""
    cardiovascular: str = ""
    respiratory: str = ""
    abdominal: str = ""
    neurological: str = ""
    musculoskeletal: str = ""
    psychiatric: str = ""  # mental status examination (Issue #2129)


class EdNoteTemplate(BaseModel):
    """ED physician note template fields for narrative generation."""

    # Language maps (Issue #2507); `physical_exam` maps a language to the
    # per-body-system findings.
    chief_complaint: dict[str, str] = Field(default_factory=dict)
    hpi: dict[str, str] = Field(default_factory=dict)
    physical_exam: dict[str, EdPhysicalExam] = Field(default_factory=dict)
    ed_workup_summary: dict[str, str] = Field(default_factory=dict)
    disposition: dict[str, str] = Field(default_factory=dict)


class EdTriageTemplate(BaseModel):
    """ED triage template (Issue #2864): the ESI / JTAS levels the condition is
    triaged at (they bound the triage draw) and the treatment orders that mark
    an ESI v4 high-risk presentation (level 2, e.g. IM epinephrine for
    anaphylaxis)."""

    common_triage_levels: list[str] = Field(default_factory=list)
    high_risk_orders: list[str] = Field(default_factory=list)

    @field_validator("common_triage_levels")
    @classmethod
    def _levels_one_to_five(cls, levels: list[str]) -> list[str]:
        bad = [lv for lv in levels if lv not in {"1", "2", "3", "4", "5"}]
        if bad:
            raise ValueError(f"common_triage_levels must be '1'-'5', got {bad}")
        return levels

    @model_validator(mode="after")
    def _high_risk_reaches_level_two(self) -> EdTriageTemplate:
        if self.high_risk_orders and not any(int(lv) <= 2 for lv in self.common_triage_levels):
            raise ValueError("high_risk_orders need a common_triage_levels entry of '1' or '2'")
        return self


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

    # Chronic-code prefixes a resident must carry for this condition to be
    # drawn (exacerbations of a chronic disease, e.g. ["J45"] for asthma).
    requires_chronic_prefix: list[str] = []

    # Per-severity disposition (``discharge_home`` / ``transfer_psychiatric``)
    # and per-chronic-prefix diagnosis code overrides (Issue #2124).
    disposition_by_severity: dict[str, Literal["discharge_home", "transfer_psychiatric"]] = {}
    by_chronic_prefix: dict[str, str] = {}
    # Severities a hospital with an inpatient unit of ``department`` admits
    # instead of treating in the ED (Issue #2132): {department, severities}.
    admitted_with_inpatient_unit: dict[str, Any] = {}
    # Most / least urgent triage level the condition allows before the vitals
    # floor (ESI / JTAS 1-5).
    triage_level_min: int | None = Field(default=None, ge=1, le=5)
    triage_level_max: int | None = Field(default=None, ge=1, le=5)

    # Narrative spec (Tier 1 #3 α-min-2 Task 6): per-encounter-type narrative
    # templates.  Optional default = None so existing encounter YAMLs without a
    # narrative: block continue to validate without error.
    narrative: EncounterNarrativeSpec | None = None

    @model_validator(mode="after")
    def _high_risk_orders_are_treatments(self) -> EncounterConditionProtocol:
        triage = self.narrative.ed_triage_template if self.narrative else None
        if not triage or not triage.high_risk_orders:
            return self
        names: set[str] = set()
        for tx in (self.model_extra or {}).get("treatment") or []:
            names.add(str(tx.get("name", "")))
            names.update(str(v) for v in (tx.get("locale_name") or {}).values())
        unknown = sorted(set(triage.high_risk_orders) - names)
        if unknown:
            raise ValueError(f"{self.condition_id}: high_risk_orders {unknown} are not treatment names")
        return self


def _validate_encounter_route_vocabulary(condition_id: str, data: Any) -> None:
    """Issue #458: import-time route vocabulary check for encounter YAMLs.

    Sibling of `disease.protocol._validate_drug_route_vocabulary`. Delegates
    to `validate_yaml_route_value` so the recognized set stays single-sourced.
    """
    from clinosim.modules.output.fhir_r4.lib.reference_data import iter_route_values, validate_yaml_route_value

    for raw in iter_route_values(data):
        validate_yaml_route_value(raw, source=f"encounter {condition_id!r}")


@lru_cache(maxsize=64)
def load_encounter_condition(condition_id: str) -> dict[str, Any]:
    """Load and validate a single encounter condition YAML.

    Returns the raw dict (callers expect a dict); validation guards against
    malformed YAML by raising a clear Pydantic error. Cached (maxsize=64 covers
    the ~46 conditions with margin); the returned dict is a SHARED read-only
    instance — no call site mutates it (verified by grep during the
    loader-commonization refactor).
    """
    path = _REF_DIR / f"{condition_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Encounter condition not found: {path}")
    data = load_data_yaml(path)
    EncounterConditionProtocol.model_validate(data)
    _validate_encounter_route_vocabulary(condition_id, data)
    return data


@lru_cache(maxsize=1)
def load_all_encounter_conditions() -> dict[str, dict[str, Any]]:
    """Auto-discover, validate, and load all encounter condition YAMLs. Cached."""
    conditions: dict[str, dict[str, Any]] = {}
    for yaml_file in sorted(_REF_DIR.glob("*.yaml")):
        data = load_data_yaml(yaml_file)
        try:
            EncounterConditionProtocol.model_validate(data)
        except Exception as exc:  # narrow re-raise with offending filename
            raise ValueError(f"Invalid encounter condition YAML: {yaml_file.name}") from exc
        cid = data.get("condition_id", yaml_file.stem)
        _validate_encounter_route_vocabulary(cid, data)
        conditions[cid] = data
    return conditions
