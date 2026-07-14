"""Tests for TemplateNarrativeGenerator α-min-2 extensions (Task 8).

Covers 6 new DocumentTypes:
  COMPOSITION: ADMISSION_NURSING_ASSESSMENT / NURSING_DISCHARGE_SUMMARY /
               OUTPATIENT_SOAP / ED_NOTE
  FREE_TEXT:   NURSING_SHIFT_NOTE / ED_TRIAGE_NOTE

Test pattern: create fake DocumentTypeSpec with the intended sections (Task 9
will register these in document_type_specs.yaml; tests here are generator-only).

Locale decisions:
  - Nursing/ED composition sections are JP-primary; EN locale falls back to JP
    text (same pattern as PROGRESS_NOTE with ja_only_fallback). For fields with
    explicit EN from encounter_protocol (not yet implemented), EN is used; absent
    field defaults to generic EN phrase.
  - ED_TRIAGE_NOTE and NURSING_SHIFT_NOTE free-text always produce non-empty text
    regardless of whether triage_data / primary_nurse_id are set.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, FormatType, NarrativeContext
from clinosim.types.patient import PatientProfile
from clinosim.types.triage import TriageData

# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────


def _make_patient() -> PatientProfile:
    """Build a minimal PatientProfile for testing."""
    patient = PatientProfile(patient_id="pt-alpha2-test")
    patient.chronic_conditions = []
    patient.current_medications = []
    patient.allergies = []
    patient.smoking_status = "former"
    patient.alcohol_use = "occasional"
    patient.occupation = "office"
    return patient


def _make_encounter(
    triage_data: TriageData | None = None,
    primary_nurse_id: str = "",
) -> Any:
    """Build a minimal EncounterRecord-like namespace for testing."""
    return SimpleNamespace(
        encounter_id="enc-alpha2-test",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        triage_data=triage_data,
        primary_nurse_id=primary_nurse_id,
    )


def _make_outpatient_encounter_protocol(
    subjective_ja: str = "息切れが続いている",
    objective_ja: str = "SpO2 96%、体温 37.2°C",
    assessment_ja: str = "慢性閉塞性肺疾患（COPD）の急性増悪",
    plan_ja: str = "吸入ステロイド継続、次回 2 週間後再診",
) -> Any:
    """Build a mock EncounterConditionProtocol with SOAP narrative."""
    soap = SimpleNamespace(
        subjective_ja=subjective_ja,
        objective_ja=objective_ja,
        assessment_ja=assessment_ja,
        plan_ja=plan_ja,
    )
    narrative = SimpleNamespace(
        outpatient_soap_template=soap,
        ed_note_template=None,
        ed_triage_template=None,
    )
    return SimpleNamespace(
        condition_id="copd_exacerbation",
        narrative=narrative,
    )


def _make_ed_encounter_protocol(
    chief_complaint_ja: str = "胸痛・呼吸困難",
    hpi_ja: str = "安静時胸痛が突然出現、発汗を伴う",
    ed_workup_summary_ja: str = "ECG・トロポニン・胸部 X 線施行",
    disposition_ja: str = "心内科入院",
) -> Any:
    """Build a mock EncounterConditionProtocol with ED note narrative."""
    physical_exam = SimpleNamespace(
        general="意識清明",
        cardiovascular="頻脈 110 bpm",
        respiratory="呼吸音両側清",
        abdominal="軟、圧痛なし",
        neurological="神経学的異常なし",
        musculoskeletal="",
    )
    ed_note = SimpleNamespace(
        chief_complaint_ja=chief_complaint_ja,
        hpi_ja=hpi_ja,
        physical_exam_ja=physical_exam,
        ed_workup_summary_ja=ed_workup_summary_ja,
        disposition_ja=disposition_ja,
    )
    narrative = SimpleNamespace(
        outpatient_soap_template=None,
        ed_note_template=ed_note,
        ed_triage_template=None,
    )
    return SimpleNamespace(
        condition_id="chest_pain_acs",
        narrative=narrative,
    )


def _make_ctx(
    document_type: DocumentType,
    target_lang: str = "ja",
    locale: str = "jp",
    encounter: Any = None,
    encounter_protocol: Any = None,
    day_index: int = 0,
    los_days: int = 5,
    severity: str = "moderate",
) -> NarrativeContext:
    """Build a minimal NarrativeContext for testing α-min-2 document types."""
    return NarrativeContext(
        patient=_make_patient(),
        encounter=encounter or _make_encounter(),
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=encounter_protocol,
        clinical_course_archetype="uncomplicated_improvement",
        severity=severity,
        day_index=day_index,
        los_days=los_days,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=document_type,
        target_lang=target_lang,
        locale=locale,
    )


def _make_nursing_assessment_spec() -> DocumentTypeSpec:
    """Fake DocumentTypeSpec for ADMISSION_NURSING_ASSESSMENT (Task 9 will register in YAML)."""
    return DocumentTypeSpec(
        type_key="admission_nursing_assessment",
        loinc_code="78390-2",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp", "us"),
        generation_frequency="once",
        composition_sections=(
            "nursing_history",
            "adl_assessment",
            "risk_assessments",
            "nursing_diagnosis",
            "care_plan",
        ),
    )


def _make_nursing_discharge_spec() -> DocumentTypeSpec:
    """Fake DocumentTypeSpec for NURSING_DISCHARGE_SUMMARY."""
    return DocumentTypeSpec(
        type_key="nursing_discharge_summary",
        loinc_code="34745-0",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp", "us"),
        generation_frequency="once",
        composition_sections=(
            "admission_status",
            "nursing_interventions_provided",
            "patient_education",
            "discharge_readiness",
        ),
    )


def _make_outpatient_soap_spec() -> DocumentTypeSpec:
    """Fake DocumentTypeSpec for OUTPATIENT_SOAP."""
    return DocumentTypeSpec(
        type_key="outpatient_soap",
        loinc_code="34131-3",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp", "us"),
        generation_frequency="per_visit",
        composition_sections=("subjective", "objective", "assessment", "plan"),
    )


def _make_ed_note_spec() -> DocumentTypeSpec:
    """Fake DocumentTypeSpec for ED_NOTE."""
    return DocumentTypeSpec(
        type_key="ed_note",
        loinc_code="34878-9",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp", "us"),
        generation_frequency="once",
        composition_sections=(
            "chief_complaint",
            "hpi",
            "triage_details",
            "physical_exam",
            "ed_workup",
            "assessment",
            "disposition",
        ),
    )


def _make_nursing_shift_spec() -> DocumentTypeSpec:
    """Fake DocumentTypeSpec for NURSING_SHIFT_NOTE."""
    return DocumentTypeSpec(
        type_key="nursing_shift_note",
        loinc_code="34746-8",
        format_type=FormatType.FREE_TEXT,
        countries_supported=("jp", "us"),
        generation_frequency="per_shift",
    )


def _make_ed_triage_spec() -> DocumentTypeSpec:
    """Fake DocumentTypeSpec for ED_TRIAGE_NOTE."""
    return DocumentTypeSpec(
        type_key="ed_triage_note",
        loinc_code="54094-8",
        format_type=FormatType.FREE_TEXT,
        countries_supported=("jp", "us"),
        generation_frequency="once",
    )


# ─────────────────────────────────────────────────────────────────
# 1. ADMISSION_NURSING_ASSESSMENT — COMPOSITION
# ─────────────────────────────────────────────────────────────────


def test_admission_nursing_assessment_returns_sections_dict() -> None:
    """ADMISSION_NURSING_ASSESSMENT must return populated sections dict."""
    spec = _make_nursing_assessment_spec()
    ctx = _make_ctx(DocumentType.ADMISSION_NURSING_ASSESSMENT)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert isinstance(out.sections, dict), "sections must be a dict"
    for section in spec.composition_sections:
        assert section in out.sections, f"section {section!r} missing"
        assert out.sections[section].strip() != "", f"section {section!r} must not be empty"


def test_admission_nursing_assessment_all_sections_non_empty() -> None:
    """All sections must have non-empty string values."""
    spec = _make_nursing_assessment_spec()
    ctx = _make_ctx(DocumentType.ADMISSION_NURSING_ASSESSMENT, target_lang="ja")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    for section, text in out.sections.items():
        assert isinstance(text, str)
        assert text.strip() != "", f"section {section!r} is empty"


def test_admission_nursing_assessment_jp_has_japanese_text() -> None:
    """JP locale nursing assessment sections must contain Japanese characters."""
    spec = _make_nursing_assessment_spec()
    ctx = _make_ctx(DocumentType.ADMISSION_NURSING_ASSESSMENT, target_lang="ja", locale="jp")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    all_text = " ".join(out.sections.values())
    has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in all_text)
    assert has_jp, f"JP nursing assessment sections contain no Japanese text: {all_text[:300]!r}"


def test_admission_nursing_assessment_en_no_crash() -> None:
    """EN locale nursing assessment must not crash and must return non-empty sections."""
    spec = _make_nursing_assessment_spec()
    ctx = _make_ctx(DocumentType.ADMISSION_NURSING_ASSESSMENT, target_lang="en", locale="us")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    for section in spec.composition_sections:
        assert section in out.sections
        assert out.sections[section].strip() != ""


def test_admission_nursing_assessment_includes_primary_nurse() -> None:
    """When primary_nurse_id is set, it appears in the output."""
    spec = _make_nursing_assessment_spec()
    enc = _make_encounter(primary_nurse_id="nurse-RN-001")
    ctx = _make_ctx(DocumentType.ADMISSION_NURSING_ASSESSMENT, encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    all_text = " ".join(out.sections.values())
    assert "nurse-RN-001" in all_text, (
        f"primary_nurse_id 'nurse-RN-001' not found in sections: {all_text[:400]!r}"
    )


# ─────────────────────────────────────────────────────────────────
# 2. NURSING_DISCHARGE_SUMMARY — COMPOSITION
# ─────────────────────────────────────────────────────────────────


def test_nursing_discharge_summary_returns_sections_dict() -> None:
    """NURSING_DISCHARGE_SUMMARY must return populated sections dict."""
    spec = _make_nursing_discharge_spec()
    ctx = _make_ctx(DocumentType.NURSING_DISCHARGE_SUMMARY, day_index=5, los_days=5)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert isinstance(out.sections, dict)
    for section in spec.composition_sections:
        assert section in out.sections, f"section {section!r} missing"
        assert out.sections[section].strip() != ""


def test_nursing_discharge_summary_jp_has_japanese_text() -> None:
    """JP locale nursing discharge sections must contain Japanese characters."""
    spec = _make_nursing_discharge_spec()
    ctx = _make_ctx(
        DocumentType.NURSING_DISCHARGE_SUMMARY, target_lang="ja", day_index=5, los_days=5
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    all_text = " ".join(out.sections.values())
    has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in all_text)
    assert has_jp, "JP nursing discharge sections contain no Japanese text"


def test_nursing_discharge_summary_los_days_appear_in_output() -> None:
    """LOS days should appear in nursing discharge summary (admission_status)."""
    spec = _make_nursing_discharge_spec()
    ctx = _make_ctx(
        DocumentType.NURSING_DISCHARGE_SUMMARY, target_lang="ja", day_index=7, los_days=7
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    all_text = " ".join(out.sections.values())
    assert "7" in all_text, f"LOS 7 days not found in nursing discharge: {all_text[:400]!r}"


# ─────────────────────────────────────────────────────────────────
# 3. OUTPATIENT_SOAP — COMPOSITION
# ─────────────────────────────────────────────────────────────────


def test_outpatient_soap_returns_sections_dict() -> None:
    """OUTPATIENT_SOAP must return sections with S/O/A/P keys."""
    spec = _make_outpatient_soap_spec()
    ctx = _make_ctx(DocumentType.OUTPATIENT_SOAP)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert isinstance(out.sections, dict)
    for section in ("subjective", "objective", "assessment", "plan"):
        assert section in out.sections, f"section {section!r} missing"
        assert out.sections[section].strip() != ""


def test_outpatient_soap_uses_encounter_protocol_template() -> None:
    """OUTPATIENT_SOAP subjective section comes from encounter_protocol.narrative.outpatient_soap_template."""
    spec = _make_outpatient_soap_spec()
    protocol = _make_outpatient_encounter_protocol(
        subjective_ja="持続する息切れで来院",
        assessment_ja="COPD 増悪疑い",
    )
    ctx = _make_ctx(
        DocumentType.OUTPATIENT_SOAP,
        encounter_protocol=protocol,
        target_lang="ja",
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "持続する息切れ" in out.sections.get("subjective", ""), (
        f"subjective_ja not used: {out.sections.get('subjective', '')!r}"
    )
    assert "COPD" in out.sections.get("assessment", ""), (
        f"assessment_ja not used: {out.sections.get('assessment', '')!r}"
    )


def test_outpatient_soap_no_encounter_protocol_graceful() -> None:
    """OUTPATIENT_SOAP without encounter_protocol must not crash."""
    spec = _make_outpatient_soap_spec()
    ctx = _make_ctx(DocumentType.OUTPATIENT_SOAP, encounter_protocol=None)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    for section in spec.composition_sections:
        assert section in out.sections
        assert out.sections[section].strip() != ""


def test_outpatient_soap_en_locale_no_crash() -> None:
    """OUTPATIENT_SOAP with EN locale must not crash and return non-empty sections."""
    spec = _make_outpatient_soap_spec()
    ctx = _make_ctx(DocumentType.OUTPATIENT_SOAP, target_lang="en", locale="us")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    for section in spec.composition_sections:
        assert section in out.sections
        assert out.sections[section].strip() != ""


# ─────────────────────────────────────────────────────────────────
# 4. ED_NOTE — COMPOSITION
# ─────────────────────────────────────────────────────────────────


def test_ed_note_returns_sections_dict() -> None:
    """ED_NOTE must return a populated sections dict with ED-specific keys."""
    spec = _make_ed_note_spec()
    triage = TriageData(
        level="3",
        level_system="ESI",
        arrival_mode="ambulance",
        chief_complaint_summary="胸痛",
    )
    enc = _make_encounter(triage_data=triage)
    ctx = _make_ctx(DocumentType.ED_NOTE, encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert isinstance(out.sections, dict)
    for section in spec.composition_sections:
        assert section in out.sections, f"section {section!r} missing"
        assert out.sections[section].strip() != ""


def test_ed_note_triage_details_uses_triage_data() -> None:
    """ED_NOTE triage_details section must include triage level from triage_data."""
    spec = _make_ed_note_spec()
    triage = TriageData(
        level="2",
        level_system="ESI",
        arrival_mode="ambulance",
        chief_complaint_summary="胸痛・呼吸困難",
    )
    enc = _make_encounter(triage_data=triage)
    ctx = _make_ctx(DocumentType.ED_NOTE, encounter=enc, target_lang="ja")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    triage_text = out.sections.get("triage_details", "")
    assert "ESI" in triage_text or "2" in triage_text, (
        f"triage_data not reflected in triage_details: {triage_text!r}"
    )


def test_ed_note_uses_encounter_protocol_template() -> None:
    """ED_NOTE sections come from encounter_protocol.narrative.ed_note_template."""
    spec = _make_ed_note_spec()
    protocol = _make_ed_encounter_protocol(
        chief_complaint_ja="突然の胸痛",
        hpi_ja="安静時胸痛 30 分、冷汗あり",
    )
    ctx = _make_ctx(DocumentType.ED_NOTE, encounter_protocol=protocol, target_lang="ja")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "突然の胸痛" in out.sections.get("chief_complaint", ""), (
        f"chief_complaint_ja not used: {out.sections.get('chief_complaint', '')!r}"
    )
    assert "30 分" in out.sections.get("hpi", ""), (
        f"hpi_ja not used: {out.sections.get('hpi', '')!r}"
    )


def test_ed_note_no_triage_data_graceful() -> None:
    """ED_NOTE with triage_data=None must not crash; triage_details gets generic phrase."""
    spec = _make_ed_note_spec()
    enc = _make_encounter(triage_data=None)
    ctx = _make_ctx(DocumentType.ED_NOTE, encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "triage_details" in out.sections
    assert out.sections["triage_details"].strip() != ""


def test_ed_note_no_encounter_protocol_graceful() -> None:
    """ED_NOTE without encounter_protocol must not crash."""
    spec = _make_ed_note_spec()
    ctx = _make_ctx(DocumentType.ED_NOTE, encounter_protocol=None)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    for section in spec.composition_sections:
        assert section in out.sections
        assert out.sections[section].strip() != ""


# ─────────────────────────────────────────────────────────────────
# 5. NURSING_SHIFT_NOTE — FREE_TEXT
# ─────────────────────────────────────────────────────────────────


def test_nursing_shift_note_returns_raw_text() -> None:
    """NURSING_SHIFT_NOTE must return non-empty raw_text."""
    spec = _make_nursing_shift_spec()
    ctx = _make_ctx(DocumentType.NURSING_SHIFT_NOTE, day_index=2)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.raw_text.strip() != "", "NURSING_SHIFT_NOTE raw_text must not be empty"


def test_nursing_shift_note_jp_has_japanese_text() -> None:
    """JP locale NURSING_SHIFT_NOTE must contain Japanese characters."""
    spec = _make_nursing_shift_spec()
    ctx = _make_ctx(DocumentType.NURSING_SHIFT_NOTE, target_lang="ja", locale="jp", day_index=1)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in out.raw_text)
    assert has_jp, f"JP shift note has no Japanese text: {out.raw_text[:300]!r}"


def test_nursing_shift_note_includes_day_info() -> None:
    """NURSING_SHIFT_NOTE must include day_index information."""
    spec = _make_nursing_shift_spec()
    ctx = _make_ctx(DocumentType.NURSING_SHIFT_NOTE, day_index=3, los_days=7)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    # day 3 (Day 4 in 1-based) or "3" should appear somewhere
    has_day_info = "3" in out.raw_text or "4" in out.raw_text or "Day" in out.raw_text
    assert has_day_info, f"Day info not found in shift note: {out.raw_text!r}"


def test_nursing_shift_note_with_primary_nurse() -> None:
    """NURSING_SHIFT_NOTE should include primary_nurse_id when available."""
    spec = _make_nursing_shift_spec()
    enc = _make_encounter(primary_nurse_id="nurse-RN-042")
    ctx = _make_ctx(DocumentType.NURSING_SHIFT_NOTE, encounter=enc, day_index=0)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "nurse-RN-042" in out.raw_text, (
        f"primary_nurse_id not in shift note: {out.raw_text!r}"
    )


def test_nursing_shift_note_no_primary_nurse_graceful() -> None:
    """NURSING_SHIFT_NOTE without primary_nurse_id must not crash."""
    spec = _make_nursing_shift_spec()
    enc = _make_encounter(primary_nurse_id="")
    ctx = _make_ctx(DocumentType.NURSING_SHIFT_NOTE, encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.raw_text.strip() != ""


# ─────────────────────────────────────────────────────────────────
# 6. ED_TRIAGE_NOTE — FREE_TEXT
# ─────────────────────────────────────────────────────────────────


def test_ed_triage_note_returns_raw_text() -> None:
    """ED_TRIAGE_NOTE must return non-empty raw_text."""
    spec = _make_ed_triage_spec()
    triage = TriageData(
        level="3",
        level_system="ESI",
        arrival_mode="ambulance",
        chief_complaint_summary="腹痛",
    )
    enc = _make_encounter(triage_data=triage)
    ctx = _make_ctx(DocumentType.ED_TRIAGE_NOTE, encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.raw_text.strip() != "", "ED_TRIAGE_NOTE raw_text must not be empty"


def test_ed_triage_note_uses_triage_data() -> None:
    """ED_TRIAGE_NOTE raw_text must include triage level, system, and arrival_mode."""
    spec = _make_ed_triage_spec()
    triage = TriageData(
        level="1",
        level_system="JTAS",
        arrival_mode="ambulance",
        chief_complaint_summary="意識消失",
    )
    enc = _make_encounter(triage_data=triage)
    ctx = _make_ctx(DocumentType.ED_TRIAGE_NOTE, encounter=enc, target_lang="ja")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    raw = out.raw_text
    assert "JTAS" in raw or "1" in raw, f"triage level_system not in triage note: {raw!r}"
    assert "意識消失" in raw, f"chief_complaint_summary not in triage note: {raw!r}"
    assert "ambulance" in raw or "救急車" in raw, (
        f"arrival_mode not in triage note: {raw!r}"
    )


def test_ed_triage_note_no_triage_data_graceful() -> None:
    """ED_TRIAGE_NOTE with triage_data=None must produce a graceful generic phrase."""
    spec = _make_ed_triage_spec()
    enc = _make_encounter(triage_data=None)
    ctx = _make_ctx(DocumentType.ED_TRIAGE_NOTE, encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.raw_text.strip() != "", "raw_text must not be empty even without triage_data"


def test_ed_triage_note_jtas_level() -> None:
    """ED_TRIAGE_NOTE with JTAS triage system includes JTAS label."""
    spec = _make_ed_triage_spec()
    triage = TriageData(
        level="2",
        level_system="JTAS",
        arrival_mode="walk-in",
        chief_complaint_summary="高熱・悪寒",
    )
    enc = _make_encounter(triage_data=triage)
    ctx = _make_ctx(DocumentType.ED_TRIAGE_NOTE, encounter=enc, target_lang="ja", locale="jp")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "JTAS" in out.raw_text or "2" in out.raw_text


# ─────────────────────────────────────────────────────────────────
# 7. metadata / determinism
# ─────────────────────────────────────────────────────────────────


def test_all_new_types_metadata_generator_field() -> None:
    """All 6 new document types must include generator=template in metadata."""
    gen = TemplateNarrativeGenerator()
    test_cases = [
        (DocumentType.ADMISSION_NURSING_ASSESSMENT, _make_nursing_assessment_spec()),
        (DocumentType.NURSING_DISCHARGE_SUMMARY, _make_nursing_discharge_spec()),
        (DocumentType.OUTPATIENT_SOAP, _make_outpatient_soap_spec()),
        (DocumentType.ED_NOTE, _make_ed_note_spec()),
        (DocumentType.NURSING_SHIFT_NOTE, _make_nursing_shift_spec()),
        (DocumentType.ED_TRIAGE_NOTE, _make_ed_triage_spec()),
    ]
    for doc_type, spec in test_cases:
        ctx = _make_ctx(doc_type)
        out = gen.generate(ctx, spec)
        assert out.metadata.get("generator") == "template", (
            f"{doc_type}: metadata.generator != 'template'"
        )


def test_all_new_types_deterministic() -> None:
    """Two calls with same NarrativeContext produce identical output for all 6 new types."""
    gen = TemplateNarrativeGenerator()
    triage = TriageData(level="3", level_system="ESI", arrival_mode="walk-in", chief_complaint_summary="発熱")
    enc = _make_encounter(triage_data=triage, primary_nurse_id="nurse-001")
    test_cases = [
        (DocumentType.ADMISSION_NURSING_ASSESSMENT, _make_nursing_assessment_spec()),
        (DocumentType.NURSING_DISCHARGE_SUMMARY, _make_nursing_discharge_spec()),
        (DocumentType.OUTPATIENT_SOAP, _make_outpatient_soap_spec()),
        (DocumentType.ED_NOTE, _make_ed_note_spec()),
        (DocumentType.NURSING_SHIFT_NOTE, _make_nursing_shift_spec()),
        (DocumentType.ED_TRIAGE_NOTE, _make_ed_triage_spec()),
    ]
    for doc_type, spec in test_cases:
        ctx = _make_ctx(doc_type, encounter=enc)
        out1 = gen.generate(ctx, spec)
        out2 = gen.generate(ctx, spec)
        assert out1.raw_text == out2.raw_text, f"{doc_type}: raw_text not deterministic"
        assert out1.sections == out2.sections, f"{doc_type}: sections not deterministic"
