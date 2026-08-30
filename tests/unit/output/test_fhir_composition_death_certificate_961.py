"""Issue #961: death certificate (死亡診断書) Composition emit tests.

Locks in the fix for the s89-era gap where 47/6389 deceased patients in
the JP p=6389 dataset received only a generic 退院時サマリー Composition
and no 死亡診断書 despite 医師法第 20 条 mandating one for every
physician-certified death.

Coverage:
  - engine.py dispatch: `discharge_once_if_deceased` fires only when
    `encounter.discharge_disposition == "exp"`
  - engine.py dispatch: no fire when patient discharged home / snapshot
    in-progress
  - composition.py: LOINC 64297-5 lands on Composition.type.coding
  - composition.py: JP dispatch uses jpfhir-doc-typecodes system + JP
    title 死亡診断書 (dual-slot in .text)
  - composition.py: US dispatch uses LOINC system + EN title
    "Death certificate"
  - narrative builder: immediate_cause_of_death section populates ICD-10
    from the encounter's clinical_diagnosis
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from clinosim.modules.document.engine import document_enricher
from clinosim.modules.output.fhir_r4.documents.composition import _bb_compositions
from clinosim.types.clinical import ClinicalDiagnosis, ClinicalDocument, ClinicalDocumentNarrative
from clinosim.types.encounter import Encounter, EncounterStatus, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_record(*, deceased: bool, discharge_disposition: str) -> CIFPatientRecord:
    """Build a minimal inpatient CIFPatientRecord for the enricher.

    Uses a completed 3-day inpatient stay; when `deceased=True` the
    discharge_disposition is set to "exp" (mirrors inpatient.py:537).
    """
    admission = datetime(2026, 4, 10, 9, 0, 0)
    discharge = admission + timedelta(days=3)
    encounter = Encounter(
        encounter_id="ENC-DEATH-001",
        patient_id="pt-961-a",
        encounter_type=EncounterType.INPATIENT,
        status=EncounterStatus.COMPLETED,
        admission_datetime=admission,
        discharge_datetime=discharge,
        attending_physician_id="DR-CA-002",
        primary_nurse_id="NS-CA-004",
        discharge_disposition=discharge_disposition,
    )
    return CIFPatientRecord(
        patient=PatientProfile(patient_id="pt-961-a", age=79, sex="F"),
        encounters=[encounter],
        deceased=deceased,
        clinical_diagnosis=ClinicalDiagnosis(
            discharge_diagnosis_code="I21.0",
            discharge_diagnosis_system="icd-10-cm",
        ),
    )


def _fake_ctx_for_enricher(record: CIFPatientRecord, country: str) -> SimpleNamespace:
    return SimpleNamespace(
        master_seed=42,
        records=[record],
        config=SimpleNamespace(
            country=country,
            snapshot_date=None,
            module_enabled=lambda name: False,
        ),
    )


def _fake_bb_ctx(record_dict: dict, country: str) -> SimpleNamespace:
    return SimpleNamespace(
        record=record_dict,
        country=country,
        patient_id=record_dict.get("patient", {}).get("patient_id", "pt-961-a"),
        primary_enc_id=record_dict.get("encounters", [{}])[0].get("encounter_id", ""),
        roster_map={},
        hospital_config={},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        patient_sex="F",
    )


# ------------------------------------------------------------------
# engine.py dispatch — fires only on discharge_disposition == "exp"
# ------------------------------------------------------------------


def test_engine_emits_death_certificate_stub_when_discharge_disposition_is_exp() -> None:
    record = _make_record(deceased=True, discharge_disposition="exp")
    ctx = _fake_ctx_for_enricher(record, country="jp")

    document_enricher(ctx)

    doc_tasks = [d.task_type for d in record.documents]
    assert "death_certificate" in doc_tasks, (
        f"expected death_certificate on a discharge_disposition='exp' encounter, got {doc_tasks}"
    )
    # Issue #961 extension: on deceased encounters the specialized 死亡退院
    # サマリー REPLACES the generic 退院時サマリー — consumers see exactly
    # one discharge-summary Composition per encounter, and its title
    # tells them whether the patient survived. Both docs share LOINC
    # 18842-5, so task_type is the discriminator here.
    assert "death_discharge_summary" in doc_tasks, (
        f"expected death_discharge_summary on a deceased-inpatient encounter, got {doc_tasks}"
    )
    assert "discharge_summary" not in doc_tasks, (
        f"generic discharge_summary must NOT fire on a deceased encounter (DDS replaces), got {doc_tasks}"
    )

    dc = next(d for d in record.documents if d.task_type == "death_certificate")
    assert dc.loinc_code == "64297-5"
    assert dc.encounter_id == "ENC-DEATH-001"
    assert dc.patient_id == "pt-961-a"


def test_engine_does_not_emit_death_certificate_on_home_discharge() -> None:
    record = _make_record(deceased=False, discharge_disposition="home")
    ctx = _fake_ctx_for_enricher(record, country="jp")

    document_enricher(ctx)

    doc_tasks = [d.task_type for d in record.documents]
    assert "death_certificate" not in doc_tasks, f"death_certificate must NOT fire on a home discharge, got {doc_tasks}"
    # Living discharges keep the generic 退院時サマリー and get no DDS.
    assert "discharge_summary" in doc_tasks
    assert "death_discharge_summary" not in doc_tasks


def test_engine_does_not_emit_death_certificate_on_in_progress_encounter() -> None:
    """AD-32: an in-progress encounter (discharge_datetime=None) cannot
    certify death — even a deceased flag is not enough."""
    record = _make_record(deceased=True, discharge_disposition="")
    record.encounters[0].status = EncounterStatus.IN_PROGRESS
    record.encounters[0].discharge_datetime = None
    ctx = _fake_ctx_for_enricher(record, country="jp")

    document_enricher(ctx)

    doc_tasks = [d.task_type for d in record.documents]
    assert "death_certificate" not in doc_tasks


def test_engine_emits_death_certificate_on_us_locale_too() -> None:
    record = _make_record(deceased=True, discharge_disposition="exp")
    ctx = _fake_ctx_for_enricher(record, country="us")

    document_enricher(ctx)

    doc_tasks = [d.task_type for d in record.documents]
    assert "death_certificate" in doc_tasks


# ------------------------------------------------------------------
# composition.py — FHIR Composition emission shape
# ------------------------------------------------------------------


def _stubbed_narrative() -> ClinicalDocumentNarrative:
    return ClinicalDocumentNarrative(
        sections={
            "immediate_cause_of_death": "直接死因: 急性心筋梗塞（I21.0）。",
            "duration_of_immediate_cause": "直接死因までの期間: 約3日。",
            "underlying_cause_of_death": "原死因: 急性心筋梗塞（I21）。",
            "contributing_conditions": "影響を及ぼした傷病名: 該当なし。",
            "manner_of_death": "死因の種類: 病死及び自然死。",
            "autopsy_status": "解剖の有無: 無。",
        },
        generator="template",
    )


def _build_stub_dc_doc(language: str) -> ClinicalDocument:
    return ClinicalDocument(
        document_id="doc-ENC-DEATH-001-99",
        task_type="death_certificate",
        loinc_code="64297-5",
        patient_id="pt-961-a",
        encounter_id="ENC-DEATH-001",
        author_practitioner_id="DR-CA-002",
        authored_datetime="2026-04-13T09:00:00",
        period_start="2026-04-10T09:00:00",
        period_end="2026-04-13T09:00:00",
        language=language,
        format_type="composition",
        narrative=_stubbed_narrative(),
    )


def test_jp_death_certificate_composition_uses_jpfhir_doc_typecodes_and_jp_title() -> None:
    doc = _build_stub_dc_doc(language="ja")
    record_dict = {
        "patient": {"patient_id": "pt-961-a"},
        "encounters": [{"encounter_id": "ENC-DEATH-001"}],
        "documents": [doc],
    }
    ctx = _fake_bb_ctx(record_dict, country="jp")

    out = _bb_compositions(ctx)

    dc_comp = next(
        c for c in out if any(cd.get("code") == "64297-5" for cd in ((c.get("type") or {}).get("coding") or []))
    )
    assert dc_comp["resourceType"] == "Composition"
    typ = dc_comp["type"]
    assert typ["coding"][0]["system"] == "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
    assert typ["coding"][0]["code"] == "64297-5"
    # Dual-slot: text carries the JP display so consumers reading
    # CodeableConcept.text see 死亡診断書 too.
    assert typ["text"] == "死亡診断書"
    assert dc_comp["title"] == "死亡診断書"
    # LOINC 64297-5 has JA display "死亡診断書" per loinc.yaml — same value.
    assert typ["coding"][0]["display"] == "死亡診断書"


def test_us_death_certificate_composition_uses_loinc_and_english_title() -> None:
    doc = _build_stub_dc_doc(language="en")
    # US narrative renders EN section values; swap for readability.
    doc.narrative.sections = {
        "immediate_cause_of_death": "Immediate cause of death: Acute MI (I21.0).",
        "duration_of_immediate_cause": "Time from onset to death: ~3 days.",
        "underlying_cause_of_death": "Underlying cause of death: Acute MI (I21).",
        "contributing_conditions": "Contributing conditions: none documented.",
        "manner_of_death": "Manner of death: natural / disease-related.",
        "autopsy_status": "Autopsy performed: no.",
    }
    record_dict = {
        "patient": {"patient_id": "pt-961-a"},
        "encounters": [{"encounter_id": "ENC-DEATH-001"}],
        "documents": [doc],
    }
    ctx = _fake_bb_ctx(record_dict, country="us")

    out = _bb_compositions(ctx)

    dc_comp = next(
        c for c in out if any(cd.get("code") == "64297-5" for cd in ((c.get("type") or {}).get("coding") or []))
    )
    typ = dc_comp["type"]
    # US path goes through the generic builder — LOINC is the type coding.
    assert typ["coding"][0]["system"] == "http://loinc.org"
    assert typ["coding"][0]["code"] == "64297-5"
    assert typ["coding"][0]["display"] == "Death certificate"
    assert dc_comp["title"] == "Death certificate"


def test_death_certificate_composition_sections_render_localized_titles() -> None:
    """JP section titles should be the legal-form labels (直接死因 etc.),
    US section titles should be the English display names — not the raw
    English slug (`immediate_cause_of_death`)."""
    doc_ja = _build_stub_dc_doc(language="ja")
    record_ja = {
        "patient": {"patient_id": "pt-961-a"},
        "encounters": [{"encounter_id": "ENC-DEATH-001"}],
        "documents": [doc_ja],
    }
    out_ja = _bb_compositions(_fake_bb_ctx(record_ja, country="jp"))
    dc_ja = next(c for c in out_ja if (c.get("type") or {}).get("coding", [{}])[0].get("code") == "64297-5")
    ja_titles = [s.get("title") for s in dc_ja.get("section", [])]
    assert "直接死因" in ja_titles
    assert "原死因" in ja_titles
    assert "解剖の有無" in ja_titles

    doc_en = _build_stub_dc_doc(language="en")
    record_en = {
        "patient": {"patient_id": "pt-961-a"},
        "encounters": [{"encounter_id": "ENC-DEATH-001"}],
        "documents": [doc_en],
    }
    out_en = _bb_compositions(_fake_bb_ctx(record_en, country="us"))
    dc_en = next(c for c in out_en if (c.get("type") or {}).get("coding", [{}])[0].get("code") == "64297-5")
    en_titles = [s.get("title") for s in dc_en.get("section", [])]
    assert "Immediate cause of death" in en_titles
    assert "Underlying cause of death" in en_titles
    # Never leak the raw snake_case slug — that was the pre-#961 hazard
    # for freshly-added section keys.
    assert not any(t == "immediate_cause_of_death" for t in en_titles)


# ------------------------------------------------------------------
# Issue #961 extension — 死亡退院サマリー (Death discharge summary)
# ------------------------------------------------------------------


def _stubbed_dds_narrative_ja() -> ClinicalDocumentNarrative:
    return ClinicalDocumentNarrative(
        sections={
            "admission_state": "患者は2026-04-10 09:00に急性心筋梗塞にて緊急入院。",
            "treatment_course": "入院期間3日間において、集学的治療を継続。",
            "terminal_course": "死亡直前、急速な循環動態悪化を呈し死亡確認。",
            "circumstances_of_death": "病棟にて担当医立会いのもと死亡確認。",
            "cause_of_death": "死因: 急性心筋梗塞（I21.0）。",
            "complications_and_comorbidities": "合併症・併存症: 特記なし。",
            "family_communication": "家族への説明経過: 立会いのもと死亡確認。",
            "autopsy_status_and_findings": "剖検の有無・所見: 剖検施行せず。",
        },
        generator="template",
    )


def _build_stub_dds_doc(language: str) -> ClinicalDocument:
    return ClinicalDocument(
        document_id="doc-ENC-DEATH-001-98",
        task_type="death_discharge_summary",
        loinc_code="18842-5",
        patient_id="pt-961-a",
        encounter_id="ENC-DEATH-001",
        author_practitioner_id="DR-CA-002",
        authored_datetime="2026-04-13T09:00:00",
        period_start="2026-04-10T09:00:00",
        period_end="2026-04-13T09:00:00",
        language=language,
        format_type="composition",
        narrative=_stubbed_dds_narrative_ja(),
    )


def test_jp_death_discharge_summary_composition_has_death_title() -> None:
    """DDS shares LOINC 18842-5 with the generic discharge summary but
    MUST emit the 死亡退院サマリー title so consumers can disambiguate
    death vs living discharge from Composition.type/title."""
    doc = _build_stub_dds_doc(language="ja")
    record_dict = {
        "patient": {"patient_id": "pt-961-a"},
        "encounters": [{"encounter_id": "ENC-DEATH-001"}],
        "documents": [doc],
    }
    ctx = _fake_bb_ctx(record_dict, country="jp")

    out = _bb_compositions(ctx)

    dds = next(c for c in out if c.get("title") == "死亡退院サマリー")
    assert dds["resourceType"] == "Composition"
    typ = dds["type"]
    assert typ["coding"][0]["system"] == "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
    assert typ["coding"][0]["code"] == "18842-5"
    assert typ["coding"][0]["display"] == "死亡退院サマリー"
    assert typ["text"] == "死亡退院サマリー"


def test_us_death_discharge_summary_composition_has_english_death_title() -> None:
    doc = _build_stub_dds_doc(language="en")
    doc.narrative.sections = {
        "admission_state": "The patient was admitted urgently on 2026-04-10.",
        "treatment_course": "Over 3 days, multidisciplinary treatment was provided.",
        "terminal_course": "In the final hours the patient deteriorated and death was confirmed.",
        "circumstances_of_death": "Death was confirmed on the ward under attending care.",
        "cause_of_death": "Cause of death: Acute MI (I21.0).",
        "complications_and_comorbidities": "No notable in-hospital complications.",
        "family_communication": "Family was present at time of death.",
        "autopsy_status_and_findings": "Autopsy not performed.",
    }
    record_dict = {
        "patient": {"patient_id": "pt-961-a"},
        "encounters": [{"encounter_id": "ENC-DEATH-001"}],
        "documents": [doc],
    }
    ctx = _fake_bb_ctx(record_dict, country="us")

    out = _bb_compositions(ctx)

    dds = next(c for c in out if c.get("title") == "Death discharge summary")
    typ = dds["type"]
    assert typ["coding"][0]["system"] == "http://loinc.org"
    assert typ["coding"][0]["code"] == "18842-5"
    assert typ["coding"][0]["display"] == "Death discharge summary"


def test_dds_section_titles_localized_ja() -> None:
    doc = _build_stub_dds_doc(language="ja")
    record_dict = {
        "patient": {"patient_id": "pt-961-a"},
        "encounters": [{"encounter_id": "ENC-DEATH-001"}],
        "documents": [doc],
    }
    out = _bb_compositions(_fake_bb_ctx(record_dict, country="jp"))
    dds = next(c for c in out if c.get("title") == "死亡退院サマリー")
    titles = [s.get("title") for s in dds.get("section", [])]
    for expected in (
        "入院時病状",
        "治療経過",
        "終末期経過",
        "死亡時状況",
        "死因",
        "合併症・併存症",
        "家族への説明経過",
        "剖検の有無・所見",
    ):
        assert expected in titles, f"missing DDS JP section title '{expected}' in {titles}"


# ------------------------------------------------------------------
# Template builders — must produce clinically-defensible narrative
# from CIF alone (no LLM required)
# ------------------------------------------------------------------


def _make_narrative_ctx_for_dds(country: str = "jp"):
    """Build a NarrativeContext for template-only builder tests."""
    from clinosim.types.document import DocumentType, NarrativeContext

    encounter = Encounter(
        encounter_id="ENC-DDS-TEST",
        patient_id="pt-dds",
        encounter_type=EncounterType.INPATIENT,
        status=EncounterStatus.COMPLETED,
        admission_datetime=datetime(2026, 4, 10, 9, 0, 0),
        discharge_datetime=datetime(2026, 4, 13, 15, 0, 0),
        attending_physician_id="DR-CA-002",
        primary_nurse_id="NS-CA-004",
        discharge_disposition="exp",
    )
    diagnosis = ClinicalDiagnosis(
        admission_diagnosis_code="I21.0",
        admission_diagnosis_system="icd-10-cm",
        discharge_diagnosis_code="I21.0",
        discharge_diagnosis_system="icd-10-cm",
    )
    return NarrativeContext(
        patient=PatientProfile(patient_id="pt-dds", age=79, sex="F", chronic_conditions=["I25", "E11"]),
        encounter=encounter,
        encounter_type=EncounterType.INPATIENT,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="typical",
        severity="severe",
        day_index=3,
        los_days=3,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[diagnosis],
        procedures=[],
        allergies=[],
        document_type=DocumentType.DEATH_DISCHARGE_SUMMARY,
        target_lang="ja" if country == "jp" else "en",
        locale=country,
        complications_occurred=["pneumothorax"],
    )


def test_dds_admission_state_template_is_clinically_defensible_ja() -> None:
    """Template MUST produce non-empty JP narrative containing disease
    display + admission datetime — no placeholder, no LLM required."""
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

    ctx = _make_narrative_ctx_for_dds(country="jp")
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_dds_admission_state(ctx)
    assert text and "心筋梗塞" in text
    assert "2026-04-10" in text
    assert "重症" in text  # severity=severe → 重症
    assert "ctx.encounter.admission_datetime" in facts


def test_dds_treatment_course_template_is_clinically_defensible_ja() -> None:
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

    ctx = _make_narrative_ctx_for_dds(country="jp")
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_dds_treatment_course(ctx)
    assert text and "3" in text  # 3 days LOS
    assert "ctx.los_days" in facts


def test_dds_terminal_course_template_references_disease_ja() -> None:
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

    ctx = _make_narrative_ctx_for_dds(country="jp")
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_dds_terminal_course(ctx)
    assert text
    assert "心筋梗塞" in text
    assert "死亡" in text


def test_dds_cause_of_death_agrees_with_dc_immediate_cause() -> None:
    """DDS 死因 and DC 直接死因 sections must resolve from the same
    _dc_resolve_primary_cause helper — cross-document consistency."""
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

    ctx = _make_narrative_ctx_for_dds(country="jp")
    gen = TemplateNarrativeGenerator()
    dds_text, _ = gen._build_dds_cause_of_death(ctx)
    dc_text, _ = gen._build_dc_immediate_cause(ctx)
    # Both must name the same ICD code + display.
    assert "I21.0" in dds_text
    assert "I21.0" in dc_text
    assert "心筋梗塞" in dds_text
    assert "心筋梗塞" in dc_text


def test_dds_autopsy_and_dc_autopsy_agree_per_encounter() -> None:
    """The SHA256 sampling helper must produce the same answer in both
    documents for the same encounter — no drift."""
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

    ctx = _make_narrative_ctx_for_dds(country="jp")
    gen = TemplateNarrativeGenerator()
    dc_text, _ = gen._build_dc_autopsy_status(ctx)
    dds_text, _ = gen._build_dds_autopsy_status_and_findings(ctx)
    # DC uses "解剖の有無: 有（病理解剖）" for performed, "解剖の有無: 無" for none
    dc_performed = "有（病理解剖）" in dc_text
    dds_performed = "剖検は施行せず" not in dds_text
    assert dc_performed == dds_performed, f"DC and DDS autopsy status disagreed: DC={dc_text!r}, DDS={dds_text!r}"


def test_dc_duration_uses_bucket_for_multi_day_stay_ja() -> None:
    """3-day LOS → 'days' bucket; must contain 約3日 phrase."""
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

    ctx = _make_narrative_ctx_for_dds(country="jp")
    gen = TemplateNarrativeGenerator()
    text, _ = gen._build_dc_duration_of_immediate_cause(ctx)
    assert "3日" in text
    assert "入院前の経過は本記録範囲外" in text


def test_dc_contributing_conditions_includes_chronic_and_complication_ja() -> None:
    """Enriched contributing_conditions must fold in both chronic
    conditions AND in-hospital complications."""
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

    ctx = _make_narrative_ctx_for_dds(country="jp")
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_dc_contributing_conditions(ctx)
    assert "I25" in text or "慢性" in text
    assert "pneumothorax" in text
    assert "ctx.patient.chronic_conditions" in facts
    assert "ctx.complications_occurred" in facts
