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
from typing import Annotated, Any, NamedTuple

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
    ``sex`` / ``smoking_status`` / ``alcohol_use`` list the patient values
    the instruction is for (an unrecorded value keeps the instruction);
    ``conditions`` / ``exclude_conditions`` name value-set groups
    (``codes/data/valuesets.yaml``) matched against the patient's chronic
    conditions and the encounter's diagnoses; ``discharge_drugs`` lists
    catalog drug ids or classes of which at least one must be on the
    discharge prescription — the drugs matched fill ``{drugs}``."""

    model_config = ConfigDict(extra="forbid")

    sex: list[str] | None = None
    smoking_status: list[str] | None = None
    alcohol_use: list[str] | None = None
    conditions: Annotated[list[str], AfterValidator(_known_condition_groups)] = Field(default_factory=list)
    exclude_conditions: Annotated[list[str], AfterValidator(_known_condition_groups)] = Field(default_factory=list)
    discharge_drugs: Annotated[list[str], AfterValidator(_known_drugs)] = Field(default_factory=list)


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
# chief_complaint_variants.yaml (Issue #983)
# ─────────────────────────────────────────────────────────────────


class ChiefComplaintVariants(BaseModel):
    """Shape of chief_complaint_variants.yaml: per disease, a non-empty list
    of non-empty JP chief-complaint strings."""

    model_config = ConfigDict(extra="forbid")

    variants: dict[str, Annotated[list[_Text], Field(min_length=1)]] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _non_empty(cls, data: Any) -> Any:
        return _not_empty(data, "chief_complaint_variants.yaml")


@lru_cache(maxsize=1)
def load_chief_complaint_variants() -> dict[str, list[str]]:
    """Load chief_complaint_variants.yaml + validate. Cached singleton.

    Returns ``{disease_id: [variant_ja, ...]}`` — flattened for O(1) lookup
    at narrative-build time (Issue #983). JP-only by design; US narrative
    keeps the existing single canonical CC (English disease_protocol chain).
    """
    data = load_validated_yaml(_NARRATIVE_REF_DIR / "chief_complaint_variants.yaml", ChiefComplaintVariants)
    return dict(data["variants"])


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


class _NursingContentEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nursing_diagnoses: _NursingTexts
    care_plan: _NursingTexts
    patient_education: _NursingTexts


class NursingContent(BaseModel):
    """Shape of clinosim-nursing-content.yaml (session-104 Tier 2): at least
    one of the ``acute_disease`` / ``chronic_icd10`` axes, each a non-empty
    mapping whose entries carry nursing diagnoses, care plan and patient
    education as non-empty ``ja`` and ``en`` string lists."""

    model_config = ConfigDict(extra="forbid")

    acute_disease: dict[str, _NursingContentEntry] | None = Field(default=None, min_length=1)
    chronic_icd10: dict[str, _NursingContentEntry] | None = Field(default=None, min_length=1)

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


class ChronicMedClassHints(BaseModel):
    """Shape of chronic-med-class-hints.yaml: per chronic-condition class, the
    medication-name hints in English and Japanese (and the ICD-10 prefix the
    class documents)."""

    model_config = ConfigDict(extra="forbid")

    classes: dict[str, _ChronicMedClassHint]


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
