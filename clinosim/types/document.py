"""Document CIF dataclasses.

``NarrativeContext`` is the single input shape consumed by every
narrative generator (template + LLM); every generator receives it and
returns a ``NarrativeOutput``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from clinosim.modules._shared import is_jp


class FormatType(StrEnum):
    """Document content format type."""

    FREE_TEXT = "free_text"  # → DocumentReference (text content)
    COMPOSITION = "composition"  # → Composition (section structure)
    QUESTIONNAIRE_RESPONSE = "questionnaire_response"  # → QuestionnaireResponse (JP path active).


class DocumentType(StrEnum):
    """Document types.

    Initial scope: ``ADMISSION_HP`` + ``PROGRESS_NOTE`` +
    ``DISCHARGE_SUMMARY``. Expanded to cover nursing / outpatient / ED
    document types and JP-specific mandated documents from 厚生労働省.
    """

    # Core hospital documents.
    ADMISSION_HP = "admission_hp"  # LOINC 34117-2
    PROGRESS_NOTE = "progress_note"  # LOINC 11506-3
    DISCHARGE_SUMMARY = "discharge_summary"  # LOINC 18842-5
    # Nursing / outpatient / ED documents.
    ADMISSION_NURSING_ASSESSMENT = "admission_nursing_assessment"  # LOINC 78390-2
    NURSING_SHIFT_NOTE = "nursing_shift_note"  # LOINC 34746-8
    NURSING_DISCHARGE_SUMMARY = "nursing_discharge_summary"  # LOINC 34745-0
    OUTPATIENT_SOAP = "outpatient_soap"  # LOINC 34131-3
    ED_NOTE = "ed_note"  # LOINC 34878-9
    ED_TRIAGE_NOTE = "ed_triage_note"  # LOINC 54094-8
    # JP-mandated documents (厚生労働省 4帳票 — first two of the four).
    ADMISSION_CARE_PLAN = "admission_care_plan"  # LOINC 18776-5
    NUTRITION_CARE_PLAN = "nutrition_care_plan"  # LOINC 80791-7
    # JP-mandated (厚生労働省 4帳票 — final of the four).
    REHABILITATION_PLAN = "rehabilitation_plan"  # LOINC 34823-5
    # JP-CLINS 診療情報提供書 (referral note) — LOINC 57133-1 (JP-CLINS v1.12.0).
    REFERRAL_NOTE = "referral_note"
    # JP-eCheckup 健診結果報告書 (health-checkup report) — LOINC 53576-5 (JP-eCheckup v1.7.0, opt-in).
    HEALTH_CHECKUP_REPORT = "health_checkup_report"
    # Issue #961: 死亡診断書 (Death certificate) — LOINC 64297-5. Emitted on
    # every inpatient encounter whose discharge_disposition == "exp".
    # 医師法第 20 条 mandate; complements the existing 退院時サマリー rather
    # than replacing it (billing/administrative discharge summary still runs).
    DEATH_CERTIFICATE = "death_certificate"
    # Issue #961 extension: 死亡退院サマリー (Death discharge summary) — LOINC
    # 18842-5 (same code as the generic discharge summary; JP hospitals use
    # a specialized template with distinct sections — 入院時病状 / 治療経過 /
    # 終末期経過 / 死亡時状況 / 死因 / 合併症・併存症 / 家族への説明経過 /
    # 剖検の有無・所見). REPLACES the generic 退院時サマリー on deceased
    # encounters (`discharge_disposition == "exp"`); consumers see one
    # discharge-summary Composition per encounter, and its title
    # disambiguates death vs living discharge.
    DEATH_DISCHARGE_SUMMARY = "death_discharge_summary"


@dataclass(frozen=True)
class DocumentTypeSpec:
    """Document type registry entry.

    Moved from ``clinosim/modules/document/narrative/registry.py`` in the
    N-chain (2026-07-02) per the types rule ("all types defined in
    ``clinosim/types/``"); ``registry.py`` keeps the loader + a
    backwards-compat re-export.

    F-8 adv-1: removed ``display_en`` / ``display_ja`` fields. The display
    text for a document type is resolved at output time via
    ``code_lookup("loinc", spec.loinc_code, language)`` from
    ``clinosim/codes/data/loinc.yaml`` (the authoritative source). The
    spec's job is code + format + policy metadata only.
    """

    type_key: str
    loinc_code: str
    format_type: FormatType
    countries_supported: tuple[str, ...]
    generation_frequency: str
    composition_sections: tuple[str, ...] = field(default_factory=tuple)
    structured_form_yaml: str | None = None
    stage2_strategy: str = "template_only"
    llm_enabled_sections: tuple[str, ...] = field(default_factory=tuple)
    encounter_types_supported: tuple[str, ...] = field(default_factory=tuple)
    """Encounter types this spec applies to.

    Empty tuple (default) = no restriction; matches all encounter types (backwards-compat for
    specs like ADMISSION_HP / PROGRESS_NOTE / DISCHARGE_SUMMARY).
    Non-empty = explicit allowlist; values must be lowercase (e.g. 'inpatient', 'outpatient',
    'emergency'). Populated by Task 9 for the 6 new encounter-scoped document types.
    """

    composition_sections_jp: tuple[str, ...] = field(default_factory=tuple)
    """JP-CLINS-compliant section list.

    Empty tuple (default) means no JP-specific override; the
    country-neutral ``composition_sections`` is used. When non-empty,
    this replaces ``composition_sections`` for ``country == "JP"``. The
    section keys themselves are English snake_case identifiers that the
    narrative renderer consumes; conversion to the FHIR numeric section
    codes (``jp-codeSystem-clins-document-section``) happens inside the
    Composition builder.
    """

    llm_enabled_sections_jp: tuple[str, ...] = field(default_factory=tuple)
    """JP-CLINS-specific LLM-replacement sections.

    Empty tuple (default) means fall through to
    ``llm_enabled_sections``. Non-empty replaces it for ``country ==
    "JP"``. Keeping a JP-specific field lets JP LLM-replacement
    candidates be declared independently of the US-side list (which may
    contain US-only section names).
    """

    def composition_sections_for(self, country: str) -> tuple[str, ...]:
        """Return the section list for ``country``.

        JP-CLINS v1.12.0 requires a different discharge-summary
        structure than the traditional English six-section layout. When
        ``composition_sections_jp`` is populated and ``country == "JP"``,
        the JP-specific list is preferred. Otherwise the
        country-neutral ``composition_sections`` is returned as-is.
        """
        if is_jp(country) and self.composition_sections_jp:
            return self.composition_sections_jp
        return self.composition_sections

    def llm_enabled_sections_for(self, country: str) -> tuple[str, ...]:
        """Return the LLM-replacement section list for ``country``.

        v6 (2026-08-16): ``llm_enabled_sections_jp`` is ADDITIVE — the
        JP path returns the UNION of ``llm_enabled_sections`` (universal)
        and ``llm_enabled_sections_jp`` (JP-only extra sections, e.g.
        JP-CLINS eDS ``present_illness``). Earlier revisions REPLACED
        the universal list with the JP list, silently dropping
        ``hospital_course`` and ``discharge_instructions`` from LLM
        replacement for JP discharge_summary — producing the "identical
        template hospital_course across 11 patients" symptom the v8
        review flagged. The US path always returns
        ``llm_enabled_sections`` unchanged.
        """
        if is_jp(country) and self.llm_enabled_sections_jp:
            merged: list[str] = list(self.llm_enabled_sections)
            for s in self.llm_enabled_sections_jp:
                if s not in merged:
                    merged.append(s)
            return tuple(merged)
        return self.llm_enabled_sections


@dataclass
class NarrativeContext:
    """Single input shape consumed by every narrative generator (built from CIF by a ctx factory).

    Both template and LLM generators read only this dataclass and
    return a ``NarrativeOutput``. ``NarrativeOutput.facts_used`` tracks
    which CIF fields were consumed.
    """

    # === Patient axis ===
    patient: Any  # PatientProfile (typed as Any to avoid a circular import).

    # === Encounter axis ===
    encounter: Any  # EncounterRecord
    encounter_type: Any  # EncounterType enum

    # === Scenario source ===
    disease_protocol: Any | None  # Pydantic DiseaseProtocol
    encounter_protocol: Any | None  # Pydantic EncounterProtocol

    # === Scenario flow ===
    clinical_course_archetype: str
    severity: str
    day_index: int  # Day 0 = admission.
    los_days: int

    # === Generated clinical data ===
    vitals: list[Any]  # list[VitalSignRecord]
    lab_results: list[Any]  # list[OrderResult]
    medications: list[Any]  # list[MedicationAdministration]
    diagnoses: list[Any]  # list[ClinicalDiagnosis]
    procedures: list[Any]  # list[ProcedureRecord]
    allergies: list[Any]  # list[Allergy]

    # === Document-specific ===
    document_type: DocumentType
    target_lang: str  # "en" / "ja"
    locale: str  # "us" / "jp"

    # === AD-65 enhancements ===
    narrative_spine: NarrativeSpine | None = None  # E1 scenario anchoring
    materialized_facts: list[FactTag] = field(default_factory=list)  # E2 fact-first
    section_facts: dict[str, SectionFacts] = field(default_factory=dict)  # E3 per-section

    # === α-min-3: nursing 3-shift cadence ===
    # Neutral shift key from ClinicalDocument.shift ("night"/"day"/"evening"
    # for daily_3shift stubs; "" otherwise). NarrativePass sets this per stub;
    # the generator resolves the localized label at render time (AD-30 spirit).
    shift: str = ""

    # === chain 1a adv-1 (I-1): discharge prescription, separated ===
    # Normalized discharge_prescription.items ({"drug_name", "dose"} per
    # entry). ONLY source for the discharge_medications narrative section —
    # ctx.medications above stays MAR-only (in-hospital administrations) so
    # ICU drips / protocol orders never leak into discharge medication lists.
    discharge_medications: list[Any] = field(default_factory=list)

    # === chain 2 (rehabilitation_plan, 2026-07-04) ===
    # list[RehabSession] (clinosim/types/procedure.py) — unfiltered, mirrors the
    # existing `procedures` field's record-wide (not per-encounter) scope.
    rehab_sessions: list[Any] = field(default_factory=list)

    # === session-88j v6 (2026-08-16, inpatient blocker fix) ===
    # Complication tokens fired by the daily loop (e.g. "pneumothorax",
    # "aspiration_pneumonia"). Sourced from record.complications_occurred.
    # v5 dropped these entirely — inpatient discharge_summary /
    # progress_note / admission_hp had no way to surface a pneumothorax
    # that actually happened. Consumed by _build_extra_context to feed
    # the LLM prompt.
    complications_occurred: list[str] = field(default_factory=list)

    # === Issue #848 (in-hospital new-disease complication) ===
    # Working diagnoses arising DURING the admission. Populated by
    # ``engine._merge_disease_into_active_encounter`` when a life event
    # for a new disease fires while the patient is still admitted for an
    # earlier event — the second disease is recorded here rather than
    # opening a physically-impossible concurrent inpatient encounter.
    # Each entry is a dict with keys ``disease_id`` (str), ``onset_day``
    # (int, days since admission), ``onset_datetime`` (ISO-8601 str), and
    # ``source`` (str, currently always ``"in_hospital_complication"``).
    # Template renderers consult this alongside ``complications_occurred``
    # to render onset-day-aware phrases (e.g. "入院第30日目に急性心筋梗塞を
    # 発症"), and FHIR emit can use it to timestamp the secondary
    # Condition at intra-admission onset rather than at admission.
    working_diagnoses: list[dict] = field(default_factory=list)

    # === v9 (2026-08-17) nursing density fix ===
    # ADL / risk / intake-output snapshots consumed by nursing template
    # builders (`_build_adl_assessment`, `_build_risk_assessments`,
    # `_build_nursing_history` etc.). Sourced from
    # record.adl_assessments / record.nursing_risk_assessments /
    # record.intake_output_records. Empty list is the safe default —
    # template falls through to a hedged phrase rather than fabricating.
    adl_assessments: list[Any] = field(default_factory=list)
    nursing_risk_assessments: list[Any] = field(default_factory=list)
    intake_output_records: list[Any] = field(default_factory=list)

    # === Issue #819 follow-up: staff-name resolution at template time ===
    # Map of `staff_id → staff dict (from hospital.json)`. Populated by
    # `build_narrative_context` when the caller provides the hospital
    # roster. Template renderers use this to substitute raw practitioner
    # ids (`DR-CA-002`, `NS-OR-004`) with the practitioner's actual
    # name + role suffix (`加瀬 幸男 医師`) so the LLM never sees the
    # raw id — this fixes the 68% staff-id leak in DocumentReference
    # narratives (only Composition was covered by the post-hoc
    # `_localize_practitioner_ids_in_text` walker in PR #828).
    # Empty dict = no resolution attempted, template falls back to raw id.
    roster_map: dict[str, dict] = field(default_factory=dict)


@dataclass
class NarrativeOutput:
    """Return value of a generator; input to the emit builder.

    ★ Invariant: ``sections[key]`` is authoritative per section (LLM-replaced
    when applicable); ``raw_text`` is the unmodified template base for FREE_TEXT
    documents only. COMPOSITION builders must iterate ``sections``, not ``raw_text``.
    """

    raw_text: str = ""  # FREE_TEXT 用
    sections: dict[str, str] = field(default_factory=dict)  # COMPOSITION 用
    structured: dict = field(default_factory=dict)  # QUESTIONNAIRE_RESPONSE 用
    metadata: dict = field(default_factory=dict)  # {generator, lang, ...}
    facts_used: list[str] = field(default_factory=list)  # 使用 CIF field(audit 用)


@dataclass(frozen=True)
class FactTag:
    """Deterministic fact tag extracted from structural CIF (AD-65 E2 fact grounding)."""

    key: str  # "lab.troponin_i.day0"
    value: str  # "0.12 ng/mL"
    source: str  # "structural.observations" | "profile.demographics" | "scenario.archetype"


@dataclass
class NarrativeSpine:
    """DiseaseProtocol.narrative.* / EncounterProtocol.narrative.* canonical spine (E1)."""

    archetype: str = ""
    key_events: list[str] = field(default_factory=list)
    complications_expected: list[str] = field(default_factory=list)
    outcome_benchmark: str = ""
    disease_narrative_hints: dict[str, str] = field(default_factory=dict)


@dataclass
class SectionFacts:
    """Per-section extract for COMPOSITION docs (E3 section-level extraction)."""

    section_key: str = ""
    facts: list[FactTag] = field(default_factory=list)
    scenario_hint: str = ""
    llm_replaceable: bool = False


@dataclass
class SemanticCheckFinding:
    """One semantic-check violation (chain 1b T2).

    ``axis`` ∈ {"structure", "facts", "forbidden_pattern", "phrase",
    "numeric"} — the 5 check axes. Expectations-YAML schema problems are
    NOT findings: ``load_expectations`` raises fail-loud at load time
    (``check-narratives`` exits 2 before any document is checked).
    """

    axis: str = ""
    document_id: str = ""
    section: str = ""
    message: str = ""


@dataclass
class SemanticCheckReport:
    """Result of ``check_narratives`` over one narrative version (chain 1b T2).

    ``passed`` ⇔ no findings. ``info`` carries non-failing diagnostics
    (generator counts, skipped-for-mock counters, document totals).
    """

    cif_dir: str = ""
    version_id: str = ""
    document_count: int = 0
    findings: list[SemanticCheckFinding] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable shape for ``check-narratives --report PATH``."""
        return {
            "cif_dir": self.cif_dir,
            "version_id": self.version_id,
            "document_count": self.document_count,
            "passed": self.passed,
            "findings": [
                {
                    "axis": f.axis,
                    "document_id": f.document_id,
                    "section": f.section,
                    "message": f.message,
                }
                for f in self.findings
            ],
            "info": self.info,
        }


@runtime_checkable
class NarrativeGenerator(Protocol):
    """Unified narrative generator contract (N-1, N-chain 2026-07-02).

    Every Stage 2 generator (TemplateNarrativeGenerator, LLMNarrativeGenerator,
    test stubs) satisfies this structural interface. ``NarrativePass`` holds a
    ``NarrativeGenerator`` by constructor injection and delegates ``_generate``
    to it — the walk order / CIF I/O stays in the pass, the content production
    stays in the generator.
    """

    def generate(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Produce a NarrativeOutput for one document stub."""
        ...
