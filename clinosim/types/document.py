"""Document CIF dataclasses(Tier 1 #3 α-min-1 PR1).

NarrativeContext は全 narrative 生成の統一 input、全 generator(template / LLM)
が同 schema で受け取り、NarrativeOutput を返す。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class FormatType(str, Enum):
    """Document content format type."""

    FREE_TEXT = "free_text"                  # → DocumentReference (text content)
    COMPOSITION = "composition"              # → Composition (section structure)
    QUESTIONNAIRE_RESPONSE = "questionnaire_response"  # → QuestionnaireResponse(β-JP-1 で active)


class DocumentType(str, Enum):
    """Document types.

    α-min-1 scope: ADMISSION_HP + PROGRESS_NOTE + DISCHARGE_SUMMARY.
    α-min-2 scope: +6 nursing/outpatient/ED entries below.
    後続 phase で enum 値追加(β-JP-1 で JP 厚労省必須 doc)。
    """

    # α-min-1 scope(既存)
    ADMISSION_HP = "admission_hp"            # LOINC 34117-2
    PROGRESS_NOTE = "progress_note"          # LOINC 11506-3
    DISCHARGE_SUMMARY = "discharge_summary"  # LOINC 18842-5
    # α-min-2 scope(new)
    ADMISSION_NURSING_ASSESSMENT = "admission_nursing_assessment"  # LOINC 78390-2 (verified 2026-07)
    NURSING_SHIFT_NOTE = "nursing_shift_note"                      # LOINC 34746-8 (verified 2026-07)
    NURSING_DISCHARGE_SUMMARY = "nursing_discharge_summary"        # LOINC 34745-0 (verified 2026-07)
    OUTPATIENT_SOAP = "outpatient_soap"                            # LOINC 34131-3 (verified 2026-07)
    ED_NOTE = "ed_note"                                            # LOINC 34878-9 (verified 2026-07)
    ED_TRIAGE_NOTE = "ed_triage_note"                             # LOINC 54094-8 (verified 2026-07)
    # β-JP-1 chain 2 (厚労省4帳票, first sub-project)
    ADMISSION_CARE_PLAN = "admission_care_plan"                   # LOINC 18776-5 (verified 2026-07-03)
    NUTRITION_CARE_PLAN = "nutrition_care_plan"                   # LOINC 80791-7 (verified 2026-07-03)
    # β-JP-1 chain 2 (厚労省4帳票, third and final sub-project)
    REHABILITATION_PLAN = "rehabilitation_plan"                   # LOINC 34823-5 (verified 2026-07-04)
    # P2-13 PR2b (session 47) JP-CLINS 診療情報提供書 — LOINC 57133-1
    REFERRAL_NOTE = "referral_note"                               # LOINC 57133-1 (JP-CLINS v1.12.0)
    # P2-13 PR3 (session 47) JP-eCheckup General 健診結果報告書 — LOINC 53576-5(opt-in)
    HEALTH_CHECKUP_REPORT = "health_checkup_report"               # LOINC 53576-5 (JP-eCheckup v1.7.0)


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
    α-min-1 specs like ADMISSION_HP / PROGRESS_NOTE / DISCHARGE_SUMMARY).
    Non-empty = explicit allowlist; values must be lowercase (e.g. 'inpatient', 'outpatient',
    'emergency'). Populated by Task 9 for the 6 new encounter-scoped document types.
    """

    composition_sections_jp: tuple[str, ...] = field(default_factory=tuple)
    """JP-CLINS 準拠の section 一覧(P2-13 PR2a、session 47)。

    空 tuple(既定)= JP override なし、``composition_sections`` を使用。
    非空 = country=JP の場合に ``composition_sections`` を置換する。
    ここに書く section キー自体は英語 snake_case で narrative renderer が
    消費する識別子。FHIR 側の番号 code(jp-codeSystem-clins-document-section)
    への変換は Composition builder 側で行う。
    """

    llm_enabled_sections_jp: tuple[str, ...] = field(default_factory=tuple)
    """JP-CLINS 固有の LLM 差替対象 section(P2-13 PR2a、session 47)。

    空(既定)= ``llm_enabled_sections`` に fall through。
    非空 = country=JP の場合に ``llm_enabled_sections`` を置換する。
    US locale の llm_enabled_sections(US-only section 名を含む)と独立に
    JP section の LLM 差替候補を宣言できるようにするための field。
    """

    def composition_sections_for(self, country: str) -> tuple[str, ...]:
        """指定 country の section 一覧を返す。

        JP-CLINS v1.12.0 は退院時サマリーで従来の英語 6-section とは
        異なる構造を要求するため、``composition_sections_jp`` が populate
        されており country=JP のときは JP 固有 list を優先する。それ以外は
        country-neutral な ``composition_sections`` をそのまま返す。
        """
        if country.upper() == "JP" and self.composition_sections_jp:
            return self.composition_sections_jp
        return self.composition_sections

    def llm_enabled_sections_for(self, country: str) -> tuple[str, ...]:
        """指定 country の LLM 差替対象 section 一覧を返す。

        JP path は ``llm_enabled_sections_jp`` が populate されていれば
        それを、無ければ ``llm_enabled_sections`` を返す。US path は
        常に ``llm_enabled_sections`` を返す。
        """
        if country.upper() == "JP" and self.llm_enabled_sections_jp:
            return self.llm_enabled_sections_jp
        return self.llm_enabled_sections


@dataclass
class NarrativeContext:
    """全 narrative 生成の統一 input(CIF → ctx factory が組み立てる)。

    Generator(template / LLM)は本 dataclass のみ参照、結果を NarrativeOutput
    で返す。NarrativeOutput.facts_used で使用 CIF field を tracking。
    """

    # === Patient 軸 ===
    patient: Any                         # PatientProfile(避循環 import 用 Any)

    # === Encounter 軸 ===
    encounter: Any                       # EncounterRecord
    encounter_type: Any                  # EncounterType enum

    # === Scenario source ===
    disease_protocol: Any | None         # Pydantic DiseaseProtocol
    encounter_protocol: Any | None       # Pydantic EncounterProtocol

    # === Scenario flow ===
    clinical_course_archetype: str
    severity: str
    day_index: int                       # 入院 day 0 = admission
    los_days: int

    # === 生成済 clinical data ===
    vitals: list[Any]                    # list[VitalSignRecord]
    lab_results: list[Any]               # list[OrderResult]
    medications: list[Any]               # list[MedicationAdministration]
    diagnoses: list[Any]                 # list[ClinicalDiagnosis]
    procedures: list[Any]                # list[ProcedureRecord]
    allergies: list[Any]                 # list[Allergy]

    # === Document-specific ===
    document_type: DocumentType
    target_lang: str                     # "en" / "ja"
    locale: str                          # "us" / "jp"

    # === AD-65 enhancements ===
    narrative_spine: NarrativeSpine | None = None  # E1 scenario anchoring
    materialized_facts: list[FactTag] = field(default_factory=list)  # E2 fact-first
    section_facts: dict[str, SectionFacts] = field(default_factory=dict)  # E3 per-section

    # === α-min-3: nursing 3-shift cadence ===
    # Neutral shift key from ClinicalDocument.shift ("night"/"day"/"evening"
    # for daily_3shift stubs; "" otherwise). NarrativePass sets this per stub;
    # the generator resolves the localized label at render time (AD-30 spirit).
    shift: str = ""

    # === β-JP-1 chain 1a adv-1 (I-1): discharge prescription, separated ===
    # Normalized discharge_prescription.items ({"drug_name", "dose"} per
    # entry). ONLY source for the discharge_medications narrative section —
    # ctx.medications above stays MAR-only (in-hospital administrations) so
    # ICU drips / protocol orders never leak into discharge medication lists.
    discharge_medications: list[Any] = field(default_factory=list)

    # === β-JP-1 chain 2 (rehabilitation_plan, 2026-07-04) ===
    # list[RehabSession] (clinosim/types/procedure.py) — unfiltered, mirrors the
    # existing `procedures` field's record-wide (not per-encounter) scope.
    rehab_sessions: list[Any] = field(default_factory=list)


@dataclass
class NarrativeOutput:
    """Generator 戻り値、emit builder の入力。

    ★ Invariant: ``sections[key]`` is authoritative per section (LLM-replaced
    when applicable); ``raw_text`` is the unmodified template base for FREE_TEXT
    documents only. COMPOSITION builders must iterate ``sections``, not ``raw_text``.
    """

    raw_text: str = ""                       # FREE_TEXT 用
    sections: dict[str, str] = field(default_factory=dict)    # COMPOSITION 用
    structured: dict = field(default_factory=dict)            # QUESTIONNAIRE_RESPONSE 用
    metadata: dict = field(default_factory=dict)              # {generator, lang, ...}
    facts_used: list[str] = field(default_factory=list)       # 使用 CIF field(audit 用)


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
    """One semantic-check violation (β-JP-1 chain 1b T2).

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
