"""Encounter condition protocol loader — YAML-driven ED/outpatient conditions."""

from __future__ import annotations

from collections.abc import Mapping
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

    model_config = ConfigDict(extra="forbid")

    subjective: dict[str, str] = Field(default_factory=dict)
    objective: dict[str, str] = Field(default_factory=dict)
    assessment: dict[str, str] = Field(default_factory=dict)
    plan: dict[str, str] = Field(default_factory=dict)


class EdPhysicalExam(BaseModel):
    """ED physical exam section templates."""

    model_config = ConfigDict(extra="forbid")

    general: str = ""
    cardiovascular: str = ""
    respiratory: str = ""
    abdominal: str = ""
    neurological: str = ""
    musculoskeletal: str = ""
    psychiatric: str = ""  # mental status examination (Issue #2129)


class EdNoteTemplate(BaseModel):
    """ED physician note template fields for narrative generation."""

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

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


class SymptomOnset(BaseModel):
    """How long before arrival the presenting problem began (Issue #2871).

    ``unit`` is ``hours`` for an injury or an abrupt illness and ``days`` for
    an illness that developed over days; ``range`` is the inclusive
    ``[low, high]`` span the narrative draws the number from (RNG-neutral,
    keyed on the encounter).
    """

    model_config = ConfigDict(extra="forbid")

    unit: Literal["hours", "days"]
    range: tuple[int, int]

    @model_validator(mode="after")
    def _check_range(self) -> SymptomOnset:
        low, high = self.range
        if not 1 <= low <= high:
            raise ValueError(f"onset range must satisfy 1 <= low <= high, got {list(self.range)}")
        return self


# Onset of a protocol that declares none: an illness of one to three days.
DEFAULT_SYMPTOM_ONSET = SymptomOnset(unit="days", range=(1, 3))


class EncounterNarrativeSpec(BaseModel):
    """α-min-2 encounter narrative wrapper.

    Only the sub-block relevant to the encounter type is populated:
    - outpatient: ``outpatient_soap_template``
    - emergency: ``ed_note_template`` + ``ed_triage_template``

    ``onset`` (any encounter type) sets the ``{onset_*}`` placeholders; a
    protocol without it gets ``DEFAULT_SYMPTOM_ONSET``.
    """

    model_config = ConfigDict(extra="forbid")

    onset: SymptomOnset | None = None
    outpatient_soap_template: OutpatientSoapTemplate | None = None
    ed_note_template: EdNoteTemplate | None = None
    ed_triage_template: EdTriageTemplate | None = None


# ---------------------------------------------------------------------------
# Protocol sections (Issue #2845: every YAML key is declared)
# ---------------------------------------------------------------------------


class _MeanSd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mean: float
    sd: float


class _ResultDistribution(BaseModel):
    """Condition-specific categorical result of a qualitative lab (Issue #2138)."""

    model_config = ConfigDict(extra="forbid")

    options: list[str] = Field(min_length=1)
    weights: list[float] = Field(min_length=1)


class _WorkupLab(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test: str
    probability: float = Field(default=1.0, ge=0.0, le=1.0)
    note: str | None = None  # authoring note, not read
    # Repeat the test (serial troponin etc.) ``interval_hours`` later.
    serial: bool = False
    interval_hours: float | None = None
    # Severity -> true value of the test for this presentation.
    value_by_severity: dict[str, float] = Field(default_factory=dict)
    result_distribution: _ResultDistribution | None = None


class _WorkupImaging(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test: str
    probability: float = Field(default=1.0, ge=0.0, le=1.0)
    note: str | None = None  # authoring note, not read


class _Workup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labs: list[_WorkupLab] = Field(default_factory=list)
    imaging: list[_WorkupImaging] = Field(default_factory=list)
    vitals: bool = False  # not read: ED vitals are always generated


class _Treatment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    probability: float = Field(default=1.0, ge=0.0, le=1.0)
    route: str | None = None
    intent: str | None = None
    locale_name: dict[str, str] = Field(default_factory=dict)
    locale_exclude: list[str] = Field(default_factory=list)


class _Prescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug: str
    dose: str | None = None
    route: str | None = None
    frequency: str | None = None
    duration_days: int | None = None
    probability: float = Field(default=1.0, ge=0.0, le=1.0)
    # Prescriptions sharing a group name are alternatives: one is written.
    choose_one: str | None = None
    locale_name: dict[str, str] = Field(default_factory=dict)
    locale_exclude: list[str] = Field(default_factory=list)


class _ScenarioOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test: str
    probability: float = Field(default=1.0, ge=0.0, le=1.0)


class _ScenarioTreatment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    probability: float = Field(default=1.0, ge=0.0, le=1.0)


class _Scenario(BaseModel):
    """A presentation variant (not read by the simulator yet; Issue #2845)."""

    model_config = ConfigDict(extra="forbid")

    description: str = ""
    probability: float = Field(default=0.0, ge=0.0, le=1.0)
    duration_modifier: float = 1.0
    discharge_note: str = ""
    additional_labs: list[str | _ScenarioOrder] = Field(default_factory=list)
    additional_imaging: list[str | _ScenarioOrder] = Field(default_factory=list)
    additional_treatment: list[str | _ScenarioTreatment] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Protocol model
# ---------------------------------------------------------------------------


AgeDistribution = Literal[
    "all", "all_ages", "adults", "adults_all", "adults_40plus", "adults_50plus", "elderly", "women_40plus"
]

AGE_DISTRIBUTION_MIN_AGE: dict[str, int] = {
    "adults": 18,
    "adults_all": 18,
    "adults_40plus": 40,
    "adults_50plus": 50,
    "elderly": 65,
    "women_40plus": 40,
}
"""Youngest age a protocol's ``age_distribution`` admits (no entry = any age).
Adult = 18 (age of majority used for the adult ED protocols)."""


def protocol_min_age(spec: Mapping[str, Any]) -> int | None:
    """The youngest age an encounter protocol is drawn for: its explicit
    ``min_age``, else the floor of its ``age_distribution`` (Issue #2874)."""
    if spec.get("min_age") is not None:
        return int(spec["min_age"])
    return AGE_DISTRIBUTION_MIN_AGE.get(str(spec.get("age_distribution") or ""))


class EncounterConditionProtocol(BaseModel):
    """Loaded encounter (ED/outpatient) condition protocol from YAML.

    Validated by Pydantic (AD-18), mirroring DiseaseProtocol's in-module
    placement. Every key a condition YAML may carry is declared, and an
    unknown (e.g. misspelled) key is rejected (Issue #2845). Callers read the
    validated raw dict, not this model.
    """

    model_config = ConfigDict(extra="forbid")

    condition_id: str
    icd10_code: str
    chief_complaint: str | dict[str, str]  # str or {en: "...", ja: "..."}
    encounter_type: str
    department: str

    # Chronic-code prefixes a resident must carry for this condition to be
    # drawn (exacerbations of a chronic disease, e.g. ["J45"] for asthma).
    requires_chronic_prefix: list[str] = []

    # Who presents with this condition (Issue #2874): bounds the ages it is
    # drawn for, see :data:`AGE_DISTRIBUTION_MIN_AGE`.
    age_distribution: AgeDistribution | None = None

    # Per-severity disposition (``discharge_home`` / ``transfer_psychiatric``)
    # and per-chronic-prefix diagnosis code overrides (Issue #2124).
    disposition: str | None = None
    disposition_by_severity: dict[str, Literal["discharge_home", "transfer_psychiatric"]] = {}
    by_chronic_prefix: dict[str, str] = {}
    # Severities a hospital with an inpatient unit of ``department`` admits
    # instead of treating in the ED (Issue #2132): {department, severities}.
    admitted_with_inpatient_unit: dict[str, Any] = {}
    # Most / least urgent triage level the condition allows before the vitals
    # floor (ESI / JTAS 1-5).
    triage_level_min: int | None = Field(default=None, ge=1, le=5)
    triage_level_max: int | None = Field(default=None, ge=1, le=5)

    # ED draw: base weight, age gate and month multipliers (phases/_ed_slot.py).
    probability: float = Field(default=0.05, ge=0.0)
    min_age: int | None = None
    max_age: int | None = None
    seasonal: dict[int, float] = {}
    severity_distribution: dict[str, float] = {}
    # Visit content (simulator/emergency.py).
    ed_stay_hours: dict[str, _MeanSd] = {}
    initial_state_impact: dict[str, dict[str, float]] = {}
    acid_base_type: str | None = None
    workup: _Workup | None = None
    treatment: list[_Treatment] = []
    discharge_prescriptions: list[_Prescription] = []
    # Outpatient renewal visits re-issue the current medications.
    prescriptions_renewed: bool = False

    # Declared but not read by the simulator (reported in Issue #2845).
    sex_ratio_female: float | None = None
    incidence_modifier: float | None = None
    followup_instructions: list[str] = []
    prescriptions: list[_Prescription] = []
    visit_duration_minutes: _MeanSd | None = None
    scenarios: dict[str, _Scenario] = {}

    # Narrative spec (Tier 1 #3 α-min-2 Task 6): per-encounter-type narrative
    # templates.  Optional default = None so existing encounter YAMLs without a
    # narrative: block continue to validate without error.
    narrative: EncounterNarrativeSpec | None = None

    # Patient instructions and follow-up given on discharge from the ED
    # (Issue #2871). An emergency protocol writes each as a language map
    # ({en, ja}); the ED note's disposition lists them for a patient sent home.
    discharge_instructions: list[dict[str, str] | str] = []
    follow_up: dict[str, str] = {}

    @model_validator(mode="after")
    def _emergency_instructions_are_language_maps(self) -> EncounterConditionProtocol:
        if self.encounter_type != "emergency":
            return self
        for item in self.discharge_instructions:
            if not isinstance(item, dict) or not {"en", "ja"} <= item.keys():
                raise ValueError(f"{self.condition_id}: discharge instruction {item!r} needs en and ja text")
        if self.discharge_instructions and not {"en", "ja"} <= self.follow_up.keys():
            raise ValueError(f"{self.condition_id}: follow_up needs en and ja text")
        return self

    @model_validator(mode="after")
    def _high_risk_orders_are_treatments(self) -> EncounterConditionProtocol:
        triage = self.narrative.ed_triage_template if self.narrative else None
        if not triage or not triage.high_risk_orders:
            return self
        names: set[str] = set()
        for tx in self.treatment:
            names.add(tx.name)
            names.update(tx.locale_name.values())
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
