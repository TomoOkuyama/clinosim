"""Document module reference data loaders (Tier 1 #3 α-min-1 PR1 Task 5).

Provides loaders for disease-agnostic baseline + per-disease override
reference data used by TemplateNarrativeGenerator (Task 6) and the
document enricher (Task 8).

Pattern follows clinosim/modules/allergy/engine.py (Task 2 precedent)
and clinosim/modules/document/narrative/registry.py (Task 3 precedent):
- @lru_cache(maxsize=1) loader singletons
- a Pydantic model per file (silent-no-op defense): empty top-level,
  missing required keys, empty buckets and missing per-entry fields all
  fail loud, and the model runs BEFORE the data is returned

File ownership:
  Task 5 (this file): loaders + YAML models
  Task 8: enricher engine (imports from this file)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, NamedTuple

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator

from clinosim.datafiles import load_validated_yaml
from clinosim.reference_data import load_reference_yaml

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
# Narrative-scoped reference data (Issue #983 chief_complaint_variants et al).
# Kept beside `narrative/template_generator.py` because the content is
# narrative-only (not consumed by FHIR or enrichment paths).
_NARRATIVE_REF_DIR = _HERE / "narrative" / "reference_data"
# META #1805 Phase D/E: authority-adjacent reference tables (nursing-content,
# discharge-instructions) now live under `clinosim/codes/data/clinosim-*.yaml`
# alongside the other `clinosim-*.yaml` catalogs
# (`clinosim-nursing-scores.yaml`, `snomed-maps.yaml`).

# Required top-level keys for baseline and the minimum archetype.
_PHYSICAL_EXAM_REQUIRED_BASELINE_ARCHETYPE = "uncomplicated_improvement"
_PHYSICAL_EXAM_REQUIRED_BASELINE_DAY = "day_0"
_PHYSICAL_EXAM_BODY_SYSTEMS = frozenset(
    {"general", "cardiovascular", "respiratory", "abdominal", "neurological", "psychiatric"}
)
# Issue #3260: body systems of the newborn exam set only.
_NEONATAL_EXAM_BODY_SYSTEMS = _PHYSICAL_EXAM_BODY_SYSTEMS | {"head", "skin", "umbilicus", "hips"}

# Required keys in baseline for discharge instructions.
_DISCHARGE_BASELINE_REQUIRED_KEYS = ("hydrate", "rest", "follow_up")


# ─────────────────────────────────────────────────────────────────
# chronic_soap_templates.yaml / hedging_phrases.yaml (shared registry loader)
# ─────────────────────────────────────────────────────────────────

# A language map: language code -> text (or phrase list).
_LangText = dict[str, str]
_LangPhrases = dict[str, list[str]]


class _ChronicSoapTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subjective: _LangText
    objective: _LangText
    assessment: _LangText
    plan: _LangText


class ChronicSoapTemplates(RootModel[dict[str, _ChronicSoapTemplate]]):
    """Shape of chronic_soap_templates.yaml: per ICD-10 category, the four
    SOAP sections as language maps."""


class _HedgingTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: _LangPhrases
    unconfirmed: _LangPhrases


class HedgingPhrases(RootModel[dict[str, _HedgingTopic]]):
    """Shape of hedging_phrases.yaml: per topic, the confirmed and the
    unconfirmed phrase lists of each language."""


# The registries ``load_document_data_yaml`` serves, with their models.
_REGISTRY_MODELS: dict[str, type[BaseModel]] = {
    "chronic_soap_templates.yaml": ChronicSoapTemplates,
    "hedging_phrases.yaml": HedgingPhrases,
}


@lru_cache(maxsize=8)
def load_document_data_yaml(filename: str) -> dict[str, Any]:
    """Load ``reference_data/<filename>`` of the document module, cached per file.

    For the small registries (``chronic_soap_templates.yaml``,
    ``hedging_phrases.yaml``) whose reader owns their shape; each is checked
    against its model in ``_REGISTRY_MODELS``. Returns ``{}`` for an empty
    file. The returned dict is shared: callers must not mutate it.
    """
    return load_validated_yaml(_REF_DIR / filename, _REGISTRY_MODELS[filename]) or {}


# ─────────────────────────────────────────────────────────────────
# physical_exam_findings.yaml
# ─────────────────────────────────────────────────────────────────


def _non_blank(text: str) -> str:
    if not text.strip():
        raise ValueError("must be a non-empty string")
    return text


_Text = Annotated[str, AfterValidator(_non_blank)]


def _not_empty(data: Any, file: str) -> Any:
    if not data:
        raise ValueError(f"{file}: empty top-level")
    return data


def _english_text(text: dict[str, str]) -> dict[str, str]:
    if "en" not in text or not str(text["en"]).strip():
        raise ValueError("a language map needs a non-empty 'en' entry")
    return text


_EnglishLangMap = Annotated[dict[str, str], AfterValidator(_english_text)]


class _JaundiceBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_mg_dl: float = Field(ge=0)
    text: _EnglishLangMap


class NeonatalExam(BaseModel):
    """The newborn exam set (Issue #3260): one language map per body system
    and the jaundice bands, ascending from 0 mg/dL."""

    model_config = ConfigDict(extra="forbid")

    systems: dict[str, _EnglishLangMap] = Field(min_length=1)
    jaundice: list[_JaundiceBand] = Field(min_length=1)

    @field_validator("systems")
    @classmethod
    def _known_systems(cls, systems: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        unknown = set(systems) - _NEONATAL_EXAM_BODY_SYSTEMS
        if unknown:
            raise ValueError(
                f"physical_exam_findings.yaml: neonatal.systems has unknown body systems {sorted(unknown)}"
            )
        return systems

    @field_validator("jaundice")
    @classmethod
    def _ascending_from_zero(cls, bands: list[_JaundiceBand]) -> list[_JaundiceBand]:
        lows = [band.min_mg_dl for band in bands]
        if lows[0] != 0 or lows != sorted(set(lows)):
            raise ValueError("physical_exam_findings.yaml: neonatal.jaundice must ascend strictly from min_mg_dl 0")
        return bands


class PhysicalExamFindings(BaseModel):
    """Shape of physical_exam_findings.yaml: the baseline must carry the
    ``uncomplicated_improvement`` / ``day_0`` exam with at least one
    recognised body system (the fallback every disease relies on), and the
    per-disease ``findings`` section must be present (it may be empty)."""

    model_config = ConfigDict(extra="forbid")

    baseline: dict[str, dict[str, Any]] = Field(min_length=1)
    neonatal: NeonatalExam
    findings: Any

    @model_validator(mode="before")
    @classmethod
    def _non_empty(cls, data: Any) -> Any:
        return _not_empty(data, "physical_exam_findings.yaml")

    @field_validator("baseline")
    @classmethod
    def _baseline_day_0_exam(cls, baseline: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        archetype, day = _PHYSICAL_EXAM_REQUIRED_BASELINE_ARCHETYPE, _PHYSICAL_EXAM_REQUIRED_BASELINE_DAY
        if not baseline.get(archetype):
            raise ValueError(f"physical_exam_findings.yaml: baseline missing required archetype '{archetype}'")
        day_0 = baseline[archetype].get(day)
        if not day_0 or not isinstance(day_0, dict):
            raise ValueError(f"physical_exam_findings.yaml: baseline.{archetype} missing a '{day}' mapping")
        if not any(system in day_0 for system in _PHYSICAL_EXAM_BODY_SYSTEMS):
            raise ValueError(
                f"physical_exam_findings.yaml: baseline.{archetype}.{day} has no recognised body-system key "
                f"(expected one of: {sorted(_PHYSICAL_EXAM_BODY_SYSTEMS)})"
            )
        return baseline


@lru_cache(maxsize=1)
def load_physical_exam_findings() -> dict[str, Any]:
    """Load physical_exam_findings.yaml + validate. Cached singleton.

    Returns the full top-level dict (with 'baseline' and 'findings' keys).
    Task 6 TemplateNarrativeGenerator uses the 'baseline' section as
    fallback and the 'findings' section for per-disease overrides.
    """
    return load_validated_yaml(_REF_DIR / "physical_exam_findings.yaml", PhysicalExamFindings)


# ─────────────────────────────────────────────────────────────────
# clinosim-discharge-instruction.yaml
# ─────────────────────────────────────────────────────────────────


def _known_condition_groups(groups: list[str]) -> list[str]:
    from clinosim.codes.valuesets import group_names

    unknown = sorted(set(groups) - group_names())
    if unknown:
        raise ValueError(f"unknown condition group(s) {unknown} (codes/data/valuesets.yaml)")
    return groups


def _known_drugs(refs: list[str]) -> list[str]:
    from clinosim.codes.drugs import all_drug_ids, drug_classes

    known = set(all_drug_ids())
    for drug_id in all_drug_ids():
        known.update(drug_classes(drug_id))
    unknown = sorted(set(refs) - known)
    if unknown:
        raise ValueError(f"unknown drug id or class {unknown} (codes/data/drugs.yaml)")
    return refs


class DischargeInstructionGate(BaseModel):
    """When a discharge instruction applies to the patient (Issue #3254).

    Every listed condition must hold; an omitted one does not restrict.
    ``age_min`` / ``age_max`` (inclusive, years at the encounter; an unknown
    age keeps the instruction) bound the age (Issue #3264);
    ``sex`` / ``smoking_status`` / ``alcohol_use`` list the patient values
    the instruction is for (an unrecorded value keeps the instruction);
    ``conditions`` / ``exclude_conditions`` name value-set groups
    (``codes/data/valuesets.yaml``) matched against the patient's chronic
    conditions and the encounter's diagnoses; ``discharge_drugs`` lists
    catalog drug ids or classes of which at least one must be on the
    discharge prescription — the drugs matched fill ``{drugs}``;
    ``aki_at_discharge`` keeps the instruction for a patient whose final
    creatinine still meets the AKI definition (Issue #3281)."""

    model_config = ConfigDict(extra="forbid")

    sex: list[str] | None = None
    age_min: int | None = None
    age_max: int | None = None
    smoking_status: list[str] | None = None
    alcohol_use: list[str] | None = None
    conditions: Annotated[list[str], AfterValidator(_known_condition_groups)] = Field(default_factory=list)
    exclude_conditions: Annotated[list[str], AfterValidator(_known_condition_groups)] = Field(default_factory=list)
    discharge_drugs: Annotated[list[str], AfterValidator(_known_drugs)] = Field(default_factory=list)
    vitamin_k_given: bool | None = None
    # Issue #3281: the stay's final creatinine still meets the KDIGO AKI definition.
    aki_at_discharge: bool = False


class _BilingualText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    en: Any
    ja: Any
    applies_when: DischargeInstructionGate | None = None

    @model_validator(mode="after")
    def _drugs_placeholder_needs_gate(self) -> _BilingualText:
        if any("{drugs}" in str(text) for text in (self.en, self.ja)) and not (
            self.applies_when and self.applies_when.discharge_drugs
        ):
            raise ValueError("an instruction with {drugs} needs applies_when.discharge_drugs")
        return self


class DischargeInstructions(BaseModel):
    """Shape of clinosim-discharge-instruction.yaml: a baseline with at least
    the hydrate / rest / follow_up instructions, and a ``disease_specific``
    section (possibly empty, entries possibly null); every instruction has
    an ``en`` and a ``ja`` text and an optional ``applies_when`` gate."""

    model_config = ConfigDict(extra="forbid")

    baseline: dict[str, _BilingualText] = Field(min_length=1)
    neonatal: dict[str, _BilingualText] | None = Field(default=None, min_length=1)
    disease_specific: dict[str, dict[str, _BilingualText] | None] | None

    @model_validator(mode="before")
    @classmethod
    def _non_empty(cls, data: Any) -> Any:
        return _not_empty(data, "clinosim-discharge-instruction.yaml")

    @field_validator("baseline")
    @classmethod
    def _required_instructions(cls, baseline: dict[str, _BilingualText]) -> dict[str, _BilingualText]:
        for key in _DISCHARGE_BASELINE_REQUIRED_KEYS:
            if key not in baseline:
                raise ValueError(f"clinosim-discharge-instruction.yaml: baseline missing required key '{key}'")
        return baseline


@lru_cache(maxsize=1)
def load_discharge_instructions() -> dict[str, Any]:
    """Load clinosim-discharge-instruction.yaml + validate. Cached singleton.

    Returns the full top-level dict (with 'baseline' and 'disease_specific' keys).
    Task 6 TemplateNarrativeGenerator merges baseline + disease_specific entries,
    with disease_specific taking precedence for shared keys.
    """
    data: dict[str, Any] = load_reference_yaml(_REF_DIR / "clinosim-discharge-instruction.yaml")
    DischargeInstructions.model_validate(data)
    return data


# ─────────────────────────────────────────────────────────────────
# hpi_pertinent_negatives.yaml (Issue #984)
# ─────────────────────────────────────────────────────────────────


def _has_english(entry: dict[str, str]) -> dict[str, str]:
    if "en" not in entry:
        raise ValueError("every negative needs English text (the fallback language)")
    return entry


class HpiPertinentNegative(BaseModel):
    """One pertinent negative: its text per language and, per language, the
    symptom terms it denies (Issue #3228)."""

    model_config = ConfigDict(extra="forbid")

    text: Annotated[dict[str, _Text], AfterValidator(_has_english)]
    symptoms: dict[str, list[_Text]] = Field(default_factory=dict)


class HpiPertinentNegatives(RootModel[dict[str, list[HpiPertinentNegative]]]):
    """Shape of hpi_pertinent_negatives.yaml: per disease, an ordered list of
    pertinent negatives; English text is required (Issue #3206)."""


class PertinentNegative(NamedTuple):
    """A pertinent negative resolved to one language: the phrase and the
    symptom terms it denies (empty when it denies none)."""

    text: str
    symptoms: tuple[str, ...]


@lru_cache(maxsize=1)
def load_hpi_pertinent_negatives() -> dict[str, list[HpiPertinentNegative]]:
    """Load hpi_pertinent_negatives.yaml. Cached singleton.

    Returns a ``{disease_id: [HpiPertinentNegative, ...]}`` mapping. Missing
    file → empty dict (silent no-op ROS tail).
    """
    path = _REF_DIR / "hpi_pertinent_negatives.yaml"
    if not path.exists():
        return {}
    data = load_validated_yaml(path, HpiPertinentNegatives) or {}
    return {str(d): [HpiPertinentNegative.model_validate(e) for e in entries] for d, entries in data.items()}


def hpi_pertinent_negatives(disease_id: str, lang: str) -> list[PertinentNegative]:
    """The pertinent negatives of ``disease_id`` in ``lang``, else English
    (text and symptom terms each fall back separately), else ``[]`` (spec
    §6 rule 1)."""
    from clinosim.locale.localized import normalize_lang

    code = normalize_lang(lang)
    out: list[PertinentNegative] = []
    for entry in load_hpi_pertinent_negatives().get(disease_id) or []:
        text = (entry.text.get(code) or entry.text["en"]).strip()
        terms = entry.symptoms.get(code) or entry.symptoms.get("en") or []
        out.append(PertinentNegative(text, tuple(t.strip() for t in terms)))
    return out


# ─────────────────────────────────────────────────────────────────
# ed_note_admitted.yaml (Issue #3243)
# ─────────────────────────────────────────────────────────────────

_VitalState = Literal["low", "normal", "high"]


class VitalLimits(BaseModel):
    """Adult limits of one vital sign; a reading below ``low`` is low, above
    ``high`` is high."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    low: float | None = None
    high: float | None = None


class ExamVitalTerm(BaseModel):
    """Exam terms (per language) stating ``vital`` and the reading states
    they are consistent with."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    vital: str
    states: list[_VitalState] = Field(min_length=1)
    terms: Annotated[dict[str, list[_Text]], AfterValidator(_has_english)]


class LocalizedPhrase(BaseModel):
    """A phrase per language; English is required (the fallback language)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: Annotated[dict[str, _Text], AfterValidator(_has_english)]
    replacement: Annotated[dict[str, _Text], AfterValidator(_has_english)]


class ArrivalPhrases(BaseModel):
    """Ambulance-arrival phrases of the HPI and the triage arrival modes that
    make them true."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ambulance_modes: list[str] = Field(min_length=1)
    phrases: list[LocalizedPhrase] = Field(min_length=1)


class EdNoteAdmitted(BaseModel):
    """Shape of ed_note_admitted.yaml: the data that keeps an admitted
    patient's ED note consistent with the arrival vitals and triage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    adult_vital_limits: dict[str, VitalLimits] = Field(min_length=1)
    clause_separators: Annotated[dict[str, list[str]], AfterValidator(_has_english)]
    exam_vital_terms: list[ExamVitalTerm] = Field(min_length=1)
    arrival: ArrivalPhrases

    @model_validator(mode="after")
    def _terms_name_a_limited_vital(self) -> EdNoteAdmitted:
        unknown = {term.vital for term in self.exam_vital_terms} - set(self.adult_vital_limits)
        if unknown:
            raise ValueError(f"exam_vital_terms name vitals without adult limits: {sorted(unknown)}")
        return self


@lru_cache(maxsize=1)
def load_ed_note_admitted() -> EdNoteAdmitted:
    """Load and validate ed_note_admitted.yaml. Cached singleton."""
    return EdNoteAdmitted.model_validate(load_validated_yaml(_REF_DIR / "ed_note_admitted.yaml", EdNoteAdmitted))


# ─────────────────────────────────────────────────────────────────
# disease_exam.yaml (Issues #3245, #3227)
# ─────────────────────────────────────────────────────────────────

# Body systems an authored disease exam may write (the order they are written
# in is ``renderers/_shared_helpers.PHYSICAL_EXAM_SYSTEMS``).
_DISEASE_EXAM_BODY_SYSTEMS = _NEONATAL_EXAM_BODY_SYSTEMS | {"musculoskeletal", "extremities", "obstetric"}
_SEVERITY_KEYS = ("mild", "moderate", "severe")
_AVPU_LEVELS = ("A", "V", "P", "U")
_NIHSS_MAX_SCORE = 42  # the NIH Stroke Scale totals 0-42


def _lang_or_severity_text(entry: dict[str, Any]) -> dict[str, Any]:
    """One exam text: a language map, or a ``mild`` / ``moderate`` / ``severe``
    map of language maps (at least one severity)."""
    if "en" in entry:
        _english_text(entry)
        return entry
    if not entry or set(entry) - set(_SEVERITY_KEYS):
        raise ValueError(f"an exam text is a language map or a map of {_SEVERITY_KEYS}, got keys {sorted(entry)}")
    for text in entry.values():
        _english_text(text)
    return entry


_ExamText = Annotated[dict[str, Any], AfterValidator(_lang_or_severity_text)]


class DiseaseExamEntry(BaseModel):
    """The admission exam of one disease: its ``general`` appearance (else
    the severity default) and the findings of the systems it affects."""

    model_config = ConfigDict(extra="forbid")

    general: _EnglishLangMap | None = None
    systems: dict[str, _ExamText]

    @field_validator("systems")
    @classmethod
    def _known_systems(cls, systems: dict[str, Any]) -> dict[str, Any]:
        unknown = set(systems) - _DISEASE_EXAM_BODY_SYSTEMS
        if unknown:
            raise ValueError(f"disease_exam.yaml: unknown body systems {sorted(unknown)}")
        return systems


class AtrialFibrillationExam(BaseModel):
    """When the exam writes an irregularly irregular rhythm (Issue #3227)."""

    model_config = ConfigDict(extra="forbid")

    disease_ids: list[str]
    condition_code_prefixes: list[str] = Field(min_length=1)
    irregular_stages: list[str] = Field(min_length=1)
    irregular: _EnglishLangMap
    regular_clauses: dict[str, list[str]]

    @field_validator("regular_clauses")
    @classmethod
    def _english_clauses(cls, clauses: dict[str, list[str]]) -> dict[str, list[str]]:
        if "en" not in clauses or not clauses["en"]:
            raise ValueError("regular_clauses needs English clauses")
        return clauses


class StrokeExam(BaseModel):
    """The focal deficit of an acute stroke exam (Issue #3227): one text per
    side of the weakness and severity, and the NIHSS band of each severity."""

    model_config = ConfigDict(extra="forbid")

    disease_ids: list[str] = Field(min_length=1)
    nihss: dict[str, Annotated[list[int], Field(min_length=2, max_length=2)]]
    right: dict[str, _EnglishLangMap]
    left: dict[str, _EnglishLangMap]
    nihss_format: _EnglishLangMap

    @model_validator(mode="after")
    def _complete(self) -> StrokeExam:
        for name, bands in (("nihss", self.nihss), ("right", self.right), ("left", self.left)):
            missing = set(_SEVERITY_KEYS) - set(bands)
            if missing:
                raise ValueError(f"disease_exam.yaml: stroke.{name} lacks severities {sorted(missing)}")
        for severity, (low, high) in self.nihss.items():
            if not 0 <= low <= high <= _NIHSS_MAX_SCORE:
                raise ValueError(
                    f"disease_exam.yaml: stroke.nihss.{severity} must be within 0-{_NIHSS_MAX_SCORE} and ascending"
                )
        for text in self.nihss_format.values():
            if "{score}" not in text or "{deficit}" not in text:
                raise ValueError("disease_exam.yaml: stroke.nihss_format needs {deficit} and {score} placeholders")
        return self


class DeliveryModeExam(BaseModel):
    """The exam of one mode of delivery (Issue #3245)."""

    model_config = ConfigDict(extra="forbid")

    general: _EnglishLangMap
    obstetric: _EnglishLangMap
    obstetric_no_age: _EnglishLangMap

    @model_validator(mode="after")
    def _placeholders(self) -> DeliveryModeExam:
        for text in self.obstetric.values():
            if "{weeks}" not in text or "{days}" not in text:
                raise ValueError("disease_exam.yaml: delivery obstetric text needs {weeks} and {days}")
        return self


class DeliveryExam(BaseModel):
    """Admission diagnosis codes of a delivery stay and the exam of each mode."""

    model_config = ConfigDict(extra="forbid")

    admission_codes: dict[str, str] = Field(min_length=1)
    modes: dict[str, DeliveryModeExam] = Field(min_length=1)

    @model_validator(mode="after")
    def _modes_defined(self) -> DeliveryExam:
        unknown = set(self.admission_codes.values()) - set(self.modes)
        if unknown:
            raise ValueError(f"disease_exam.yaml: delivery codes name undefined modes {sorted(unknown)}")
        return self


class DiseaseExam(BaseModel):
    """Shape of disease_exam.yaml."""

    model_config = ConfigDict(extra="forbid")

    consciousness: dict[str, _EnglishLangMap]
    general: dict[str, _EnglishLangMap]
    atrial_fibrillation: AtrialFibrillationExam
    stroke: StrokeExam
    delivery: DeliveryExam
    diseases: dict[str, DiseaseExamEntry] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _non_empty(cls, data: Any) -> Any:
        return _not_empty(data, "disease_exam.yaml")

    @model_validator(mode="after")
    def _complete(self) -> DiseaseExam:
        if set(self.consciousness) != set(_AVPU_LEVELS):
            raise ValueError(f"disease_exam.yaml: consciousness must have exactly the levels {_AVPU_LEVELS}")
        if set(self.general) != set(_SEVERITY_KEYS):
            raise ValueError(f"disease_exam.yaml: general must have exactly the severities {_SEVERITY_KEYS}")
        disease_dir = _HERE.parent / "disease" / "reference_data"
        named = {*self.diseases, *self.atrial_fibrillation.disease_ids, *self.stroke.disease_ids}
        unknown = sorted(d for d in named if not (disease_dir / f"{d}.yaml").exists())
        if unknown:
            raise ValueError(f"disease_exam.yaml: unknown disease ids {unknown}")
        return self


@lru_cache(maxsize=1)
def load_disease_exam() -> DiseaseExam:
    """Load and validate disease_exam.yaml. Cached singleton."""
    return DiseaseExam.model_validate(load_validated_yaml(_REF_DIR / "disease_exam.yaml", DiseaseExam))


# ─────────────────────────────────────────────────────────────────
# chief_complaint_variants.yaml (Issue #983)
# ─────────────────────────────────────────────────────────────────


class ChiefComplaintVariant(BaseModel):
    """One chief-complaint phrasing and the visit conditions it requires
    (Issue #3275). A bare string in the YAML is a variant with no condition.

    ``min_age`` / ``max_age`` bound the patient's age at the visit;
    ``onset_types`` lists the disease ``hpi_template.onset_type`` values the
    phrasing fits (a "today" phrasing fits ``acute``, an "N days ago" one
    ``subacute``); ``encounter_types`` lists the encounter types it fits. An
    empty field is no constraint, and a constraint whose visit value is
    unknown does not exclude the variant.
    """

    model_config = ConfigDict(extra="forbid")

    text: _Text
    min_age: int | None = Field(default=None, ge=0)
    max_age: int | None = Field(default=None, ge=0)
    onset_types: list[_Text] = Field(default_factory=list)
    encounter_types: list[_Text] = Field(default_factory=list)


class ChiefComplaintVariants(BaseModel):
    """Shape of chief_complaint_variants.yaml: per disease, a non-empty list
    of JP chief-complaint strings or conditioned variants. The first entry of
    a pool is the canonical complaint and carries no condition."""

    model_config = ConfigDict(extra="forbid")

    variants: dict[str, Annotated[list[_Text | ChiefComplaintVariant], Field(min_length=1)]] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _non_empty(cls, data: Any) -> Any:
        return _not_empty(data, "chief_complaint_variants.yaml")

    @model_validator(mode="after")
    def _head_is_unconditional(self) -> ChiefComplaintVariants:
        for key, pool in self.variants.items():
            head = pool[0]
            if isinstance(head, ChiefComplaintVariant) and (
                head.min_age is not None or head.max_age is not None or head.onset_types or head.encounter_types
            ):
                raise ValueError(f"chief_complaint_variants.yaml: the first variant of {key!r} must carry no condition")
        return self


@lru_cache(maxsize=1)
def load_chief_complaint_variant_rules() -> dict[str, list[ChiefComplaintVariant]]:
    """Load chief_complaint_variants.yaml + validate. Cached singleton.

    Returns ``{pool_key: [ChiefComplaintVariant, ...]}`` with a bare string
    normalised to a variant with no condition (Issue #3275).
    """
    raw = load_validated_yaml(_NARRATIVE_REF_DIR / "chief_complaint_variants.yaml", ChiefComplaintVariants)
    model = ChiefComplaintVariants.model_validate(raw)
    return {
        key: [v if isinstance(v, ChiefComplaintVariant) else ChiefComplaintVariant(text=v) for v in pool]
        for key, pool in model.variants.items()
    }


# ─────────────────────────────────────────────────────────────────
# bedside_procedure_codes.yaml (Issue #992)
# ─────────────────────────────────────────────────────────────────


class BedsideProcedureCodes(BaseModel):
    """Shape of bedside_procedure_codes.yaml: two non-empty code lists, and no
    code in both (a Procedure resolves to exactly one document type — an
    overlap would double-emit)."""

    model_config = ConfigDict(extra="forbid")

    procedure_note_codes: list[_Text] = Field(min_length=1)
    operative_note_codes: list[_Text] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _non_empty(cls, data: Any) -> Any:
        return _not_empty(data, "bedside_procedure_codes.yaml")

    @model_validator(mode="after")
    def _disjoint(self) -> BedsideProcedureCodes:
        overlap = {c.strip() for c in self.procedure_note_codes} & {c.strip() for c in self.operative_note_codes}
        if overlap:
            raise ValueError(
                f"bedside_procedure_codes.yaml: codes appear in both buckets "
                f"({sorted(overlap)}) — a Procedure must resolve to exactly one "
                f"document type"
            )
        return self


@lru_cache(maxsize=1)
def load_bedside_procedure_codes() -> dict[str, frozenset[str]]:
    """Load bedside_procedure_codes.yaml + validate. Cached singleton.

    Returns a mapping ``{"procedure_note": frozenset[str],
    "operative_note": frozenset[str]}`` — the two code sets that drive
    the per-Procedure document-type dispatch in
    ``clinosim/modules/document/engine.py`` (Issue #992 procedure_note
    partner set; Issue #991 operative_note partner set).

    Unknown top-level codes (any procedure_code not listed under either
    bucket) receive no per-procedure document — this is intentional so
    a `K002` bedside wound cleanup does not fabricate a formal note.
    """
    data = load_validated_yaml(_REF_DIR / "bedside_procedure_codes.yaml", BedsideProcedureCodes)
    return {
        "procedure_note": frozenset(str(c).strip() for c in data["procedure_note_codes"]),
        "operative_note": frozenset(str(c).strip() for c in data["operative_note_codes"]),
    }


# ─────────────────────────────────────────────────────────────────
# clinosim-nursing-content.yaml (Session 104 Tier 2)
# ─────────────────────────────────────────────────────────────────

_TextList = Annotated[list[_Text], Field(min_length=1)]


class _NursingTexts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ja: _TextList
    en: _TextList


class _NursingGoal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ja: _Text
    en: _Text


class _NursingCareDetail(BaseModel):
    """The care plan of an admission problem in the Japanese nursing-plan
    classification: a goal and the observation (OP), care (TP) and education
    (EP) interventions (Issue #3267)."""

    model_config = ConfigDict(extra="forbid")

    goal: _NursingGoal
    observation: _NursingTexts
    care: _NursingTexts
    education: _NursingTexts


class _NursingContentEntry(BaseModel):
    """One disease or chronic-condition entry. ``care_plan`` (a flat list of
    interventions) and ``care_plan_detail`` (goal + OP / TP / EP) are
    alternatives: an entry carries at least one. ``comorbidity`` (chronic
    entries) applies the entry alongside an acute entry; ``smoking_education``
    is taught to a current or former smoker only."""

    model_config = ConfigDict(extra="forbid")

    nursing_diagnoses: _NursingTexts
    care_plan: _NursingTexts | None = None
    care_plan_detail: _NursingCareDetail | None = None
    patient_education: _NursingTexts
    smoking_education: _NursingTexts | None = None
    comorbidity: bool = False

    @model_validator(mode="after")
    def _has_a_care_plan(self) -> _NursingContentEntry:
        if self.care_plan is None and self.care_plan_detail is None:
            raise ValueError("a nursing content entry needs care_plan or care_plan_detail")
        return self


class _NursingCategoryEntry(_NursingContentEntry):
    """A diagnosis-category entry: the ICD-10 code prefixes it covers (the
    longest matching prefix of the admission diagnosis wins)."""

    icd10_prefixes: list[_Text] = Field(min_length=1)


class NursingContent(BaseModel):
    """Shape of clinosim-nursing-content.yaml (session-104 Tier 2): at least
    one of the ``acute_disease`` / ``chronic_icd10`` axes, each a non-empty
    mapping whose entries carry nursing diagnoses, care plan and patient
    education as non-empty ``ja`` and ``en`` string lists."""

    model_config = ConfigDict(extra="forbid")

    acute_disease: dict[str, _NursingContentEntry] | None = Field(default=None, min_length=1)
    chronic_icd10: dict[str, _NursingContentEntry] | None = Field(default=None, min_length=1)
    neonatal: _NursingContentEntry | None = None
    diagnosis_category: dict[str, _NursingCategoryEntry] | None = Field(default=None, min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _an_axis(cls, data: Any) -> Any:
        _not_empty(data, "clinosim-nursing-content.yaml")
        if "acute_disease" not in data and "chronic_icd10" not in data:
            raise ValueError(
                "clinosim-nursing-content.yaml: missing both 'acute_disease' and 'chronic_icd10' top-level axes"
            )
        return data

    @field_validator("acute_disease", "chronic_icd10", mode="before")
    @classmethod
    def _present_axis_is_a_mapping(cls, entries: Any) -> Any:
        if not entries or not isinstance(entries, dict):
            raise ValueError("clinosim-nursing-content.yaml: axis is empty or not a mapping")
        return entries


@lru_cache(maxsize=1)
def load_nursing_content() -> dict[str, Any]:
    """Load clinosim-nursing-content.yaml + validate. Cached singleton.

    Returns the full top-level dict with `acute_disease` and
    `chronic_icd10` axes. Consumers (`section_builders.nursing.build_*`)
    merge acute-first then chronic-second, per-lang, deduplicating and
    capping the merged list.
    """
    data: dict[str, Any] = load_reference_yaml(_REF_DIR / "clinosim-nursing-content.yaml")
    NursingContent.model_validate(data)
    return data


# ─────────────────────────────────────────────────────────────────
# Narrative keyword tables read by their own narrative helpers
# (cc-pe-consistency-keywords, chronic-med-class-hints,
# ja_only_fallback_sections, narrative_extras_whitelists)
# ─────────────────────────────────────────────────────────────────


class _CcConditionLists(BaseModel):
    model_config = ConfigDict(extra="forbid")

    altered_consciousness: list[str]
    severe_dyspnea: list[str]


class _NegationTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    right: list[str]


class CcPeConsistencyKeywords(BaseModel):
    """Shape of cc-pe-consistency-keywords.yaml: the chief-complaint keywords
    and their right-adjacent negation tokens, and the JP physical-exam
    replacement pools (per condition, and per recorded AVPU level)."""

    model_config = ConfigDict(extra="forbid")

    cc_keywords: _CcConditionLists
    negation_tokens: _NegationTokens
    pe_replacement_pool: _CcConditionLists
    pe_replacement_pool_by_avpu: dict[str, list[str]]


class _ChronicMedClassHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefix: str
    en: list[str]
    ja: list[str]
    # Catalog drug classes (codes/data/drugs.yaml) of the condition's drugs: a
    # medication of one of them is cited whatever its name (Issue #3250).
    drug_classes: list[str] = []


class ChronicMedClassHints(BaseModel):
    """Shape of chronic-med-class-hints.yaml: per chronic-condition class, the
    medication-name hints in English and Japanese (and the ICD-10 prefix the
    class documents)."""

    model_config = ConfigDict(extra="forbid")

    classes: dict[str, _ChronicMedClassHint]


class _AsthmaControlBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age_min: int | None = None
    age_max: int | None = None
    phrase: str


class AsthmaControlInstruments(BaseModel):
    """Shape of asthma-control-instruments.yaml: the control-instrument phrase
    of an outpatient asthma note by age band, in match order (Issue #3264)."""

    model_config = ConfigDict(extra="forbid")

    bands: list[_AsthmaControlBand] = Field(min_length=1)


class JaOnlyFallbackSections(BaseModel):
    """Shape of ja_only_fallback_sections.yaml: the section slugs excused from
    the US Japanese-character gate."""

    model_config = ConfigDict(extra="forbid")

    sections: list[str]


class NarrativeExtrasWhitelists(BaseModel):
    """Shape of narrative_extras_whitelists.yaml: the document types that
    receive the biometrics and the health-literacy prompt extras."""

    model_config = ConfigDict(extra="forbid")

    biometrics: list[str]
    health_literacy: list[str]


# ─────────────────────────────────────────────────────────────────
# death_cause_chain.yaml (Issue #3255)
# ─────────────────────────────────────────────────────────────────

_ICD_CATEGORY_RANGE = r"^[A-Z][0-9]{2}(-[A-Z][0-9]{2})?$"


def _registered_diagnosis_code(code: str) -> str:
    """``code`` must name a registered ICD-10-CM code whose JP (WHO) form is
    registered too, so both certificates can print it."""
    from clinosim.codes import code_exists
    from clinosim.codes.icd10 import icd10_system
    from clinosim.locale.loaders.demographics import map_diagnosis_code

    for country in ("US", "JP"):
        emitted = map_diagnosis_code(code, country) or code
        if not code_exists(icd10_system(country), emitted, exact=True):
            raise ValueError(f"death_cause_chain.yaml: {code} ({country} {emitted}) is not a registered diagnosis code")
    return code


class DeathCauseChain(BaseModel):
    """Shape of death_cause_chain.yaml: the complications that can be the
    immediate cause of death (lower-case token -> internal ICD code or null),
    the sequel discharge codes and the contributing-condition categories."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    immediate_cause_complications: dict[
        Annotated[str, Field(pattern=r"^[a-z0-9_]+$")],
        Annotated[str, AfterValidator(_registered_diagnosis_code)] | None,
    ] = Field(min_length=1)
    sequel_codes: list[Annotated[str, AfterValidator(_registered_diagnosis_code)]] = Field(min_length=1)
    contributing_categories: dict[
        str, Annotated[list[Annotated[str, Field(pattern=_ICD_CATEGORY_RANGE)]], Field(min_length=1)]
    ] = Field(min_length=1)

    def is_contributing(self, code: str) -> bool:
        """Whether the 3-character category of ``code`` is in a contributing range."""
        category = (code or "")[:3]
        for spans in self.contributing_categories.values():
            for span in spans:
                low, _, high = span.partition("-")
                if low <= category <= (high or low):
                    return True
        return False


@lru_cache(maxsize=1)
def load_death_cause_chain() -> DeathCauseChain:
    """Load and validate death_cause_chain.yaml. Cached singleton."""
    return DeathCauseChain.model_validate(load_validated_yaml(_REF_DIR / "death_cause_chain.yaml", DeathCauseChain))


# ─────────────────────────────────────────────────────────────────
# death_course.yaml (Issue #3256)
# ─────────────────────────────────────────────────────────────────


def _snomed_code(code: str) -> str:
    from clinosim.codes import code_exists

    if not code_exists("snomed-ct", code, exact=True):
        raise ValueError(f"death_course.yaml: SNOMED {code} is not in codes/data/snomed-ct.yaml")
    return code


def _catalog_drug_class(name: str) -> str:
    from clinosim.codes.drugs import all_drug_ids, drug_classes

    if not any(name in drug_classes(drug_id) for drug_id in all_drug_ids()):
        raise ValueError(f"death_course.yaml: drug class {name!r} is not in codes/data/drugs.yaml")
    return name


def _catalog_procedure_type(name: str) -> str:
    from clinosim.codes.procedures import catalog_procedure_types

    if name not in catalog_procedure_types():
        raise ValueError(f"death_course.yaml: procedure type {name!r} is not in the procedure catalog")
    return name


_DrugClass = Annotated[str, AfterValidator(_catalog_drug_class)]


class _LifeSupport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window_hours: float = Field(gt=0)
    drug_classes: list[_DrugClass] = Field(min_length=1)
    excluded_drug_classes: list[_DrugClass] = Field(default_factory=list)
    ventilation_devices: list[str] = Field(default_factory=list)
    ventilation_procedure_types: list[Annotated[str, AfterValidator(_catalog_procedure_type)]] = Field(
        default_factory=list
    )


class _Resuscitation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    procedure_type_keywords: list[Annotated[str, Field(pattern=r"^[a-z]+$")]] = Field(min_length=1)
    procedure_codes: list[str] = Field(min_length=1)


class _TreatmentCourse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    drug_class_priority: list[_DrugClass] = Field(default_factory=list)
    max_named_drugs: int = Field(ge=1)
    max_named_procedures: int = Field(ge=1)
    max_named_diagnoses: int = Field(ge=1)


class _Duration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    days_below_weeks: int = Field(gt=7)


class DeathCourse(BaseModel):
    """Shape of death_course.yaml: what the death summary reads as the code
    status, life support at death and a recorded CPR, the treatment-course
    list lengths and the day/week boundary of the time to death."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    not_for_resuscitation_codes: list[Annotated[str, AfterValidator(_snomed_code)]] = Field(min_length=1)
    life_support: _LifeSupport
    resuscitation: _Resuscitation
    treatment_course: _TreatmentCourse
    duration: _Duration


@lru_cache(maxsize=1)
def load_death_course() -> DeathCourse:
    """Load and validate death_course.yaml. Cached singleton."""
    return DeathCourse.model_validate(load_validated_yaml(_REF_DIR / "death_course.yaml", DeathCourse))
