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
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from clinosim.datafiles import load_data_yaml, load_validated_yaml
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

# Required keys in baseline for discharge instructions.
_DISCHARGE_BASELINE_REQUIRED_KEYS = ("hydrate", "rest", "follow_up")


@lru_cache(maxsize=8)
def load_document_data_yaml(filename: str) -> dict[str, Any]:
    """Load ``reference_data/<filename>`` of the document module, cached per file.

    For the small unvalidated registries (``chronic_soap_templates.yaml``,
    ``hedging_phrases.yaml``) whose reader owns their shape. Returns ``{}``
    for an empty file. The returned dict is shared: callers must not mutate it.
    """
    return load_data_yaml(_REF_DIR / filename) or {}


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


class PhysicalExamFindings(BaseModel):
    """Shape of physical_exam_findings.yaml: the baseline must carry the
    ``uncomplicated_improvement`` / ``day_0`` exam with at least one
    recognised body system (the fallback every disease relies on), and the
    per-disease ``findings`` section must be present (it may be empty)."""

    model_config = ConfigDict(extra="allow")

    baseline: dict[str, dict[str, Any]] = Field(min_length=1)
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


class _BilingualText(BaseModel):
    model_config = ConfigDict(extra="allow")

    en: Any
    ja: Any


class DischargeInstructions(BaseModel):
    """Shape of clinosim-discharge-instruction.yaml: a baseline with at least
    the hydrate / rest / follow_up instructions, and a ``disease_specific``
    section (possibly empty, entries possibly null); every instruction has
    an ``en`` and a ``ja`` text."""

    model_config = ConfigDict(extra="allow")

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


@lru_cache(maxsize=1)
def load_hpi_pertinent_negatives() -> dict[str, list[str]]:
    """Load hpi_pertinent_negatives.yaml. Cached singleton.

    Returns a ``{disease_id: [neg_phrase, ...]}`` mapping. Missing file
    or invalid shape → empty dict (silent no-op ROS tail; template
    falls back to the pre-#984 HPI body). Content is JP-only; EN
    locale currently emits its own locale-neutral HPI seed and does
    not consult this file.
    """
    path = _REF_DIR / "hpi_pertinent_negatives.yaml"
    if not path.exists():
        return {}
    data = load_data_yaml(path) or {}
    out: dict[str, list[str]] = {}
    if not isinstance(data, dict):
        return out
    for disease_id, phrases in data.items():
        if not isinstance(phrases, list):
            continue
        cleaned = [str(p).strip() for p in phrases if p and isinstance(p, str) and str(p).strip()]
        if cleaned:
            out[str(disease_id)] = cleaned
    return out


# ─────────────────────────────────────────────────────────────────
# chief_complaint_variants.yaml (Issue #983)
# ─────────────────────────────────────────────────────────────────


class ChiefComplaintVariants(BaseModel):
    """Shape of chief_complaint_variants.yaml: per disease, a non-empty list
    of non-empty JP chief-complaint strings."""

    model_config = ConfigDict(extra="allow")

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

    model_config = ConfigDict(extra="allow")

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
    model_config = ConfigDict(extra="allow")

    ja: _TextList
    en: _TextList


class _NursingContentEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    nursing_diagnoses: _NursingTexts
    care_plan: _NursingTexts
    patient_education: _NursingTexts


class NursingContent(BaseModel):
    """Shape of clinosim-nursing-content.yaml (session-104 Tier 2): at least
    one of the ``acute_disease`` / ``chronic_icd10`` axes, each a non-empty
    mapping whose entries carry nursing diagnoses, care plan and patient
    education as non-empty ``ja`` and ``en`` string lists."""

    model_config = ConfigDict(extra="allow")

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
    `chronic_icd10` axes. Consumers (`template_generator._build_nursing_*`)
    merge acute-first then chronic-second, per-lang, deduplicating and
    capping the merged list.
    """
    data: dict[str, Any] = load_reference_yaml(_REF_DIR / "clinosim-nursing-content.yaml")
    NursingContent.model_validate(data)
    return data
