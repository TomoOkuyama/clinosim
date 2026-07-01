"""Unit tests for document enricher (Tier 1 #3 α-min-1 Task 8).

Tests cover:
- ADMISSION_HP emission for inpatient encounter
- PROGRESS_NOTE daily emission (LOS=5 → 5 entries)
- DISCHARGE_SUMMARY emission for completed inpatient
- DISCHARGE_SUMMARY skipped for in-progress encounter (AD-32)
- ClinicalImpressionRecord daily emission (LOS=5 → 5 entries)
- Cancelled encounter skip
- Locale gating: US context excludes JP-only specs
- Determinism: same seed + encounter → identical documents
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from clinosim.modules.document import (
    CLINICAL_IMPRESSION_ID_PREFIX,
    DOC_REFERENCE_ID_PREFIX,
)
from clinosim.modules.document.engine import document_enricher
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.types.clinical import ClinicalDocument, ClinicalImpressionRecord
from clinosim.types.document import DocumentType, FormatType

# ─── Fixtures ────────────────────────────────────────────────────────────────

ADMISSION_DT = datetime(2026, 7, 1, 10, 0)
LOS_5_DT = ADMISSION_DT + timedelta(days=5)


def _make_patient(pid: str = "pt1") -> SimpleNamespace:
    return SimpleNamespace(
        patient_id=pid,
        chronic_conditions=[],
        current_medications=[],
        allergies=[],
        smoking_status="never",
        alcohol_use="none",
        occupation="",
    )


def _make_encounter(
    enc_id: str = "enc1",
    enc_type: str = "inpatient",
    status: str = "completed",
    admission_dt: datetime = ADMISSION_DT,
    discharge_dt: datetime | None = LOS_5_DT,
    attending_id: str = "dr1",
) -> SimpleNamespace:
    return SimpleNamespace(
        encounter_id=enc_id,
        encounter_type=enc_type,
        status=status,
        admission_datetime=admission_dt,
        discharge_datetime=discharge_dt,
        attending_physician_id=attending_id,
    )


def _make_record(
    encounter: SimpleNamespace | None = None,
    extra_docs: list | None = None,
) -> SimpleNamespace:
    if encounter is None:
        encounter = _make_encounter()
    return SimpleNamespace(
        patient=_make_patient(),
        encounters=[encounter],
        documents=extra_docs if extra_docs is not None else [],
        extensions={},
        vital_signs=[],
        lab_results=[],
        medication_administrations=[],
        diagnoses=[],
        procedures=[],
        physiological_states=[],
    )


def _make_ctx(
    record: SimpleNamespace,
    country: str = "us",
    master_seed: int = 42,
) -> SimpleNamespace:
    return SimpleNamespace(
        master_seed=master_seed,
        records=[record],
        config=SimpleNamespace(country=country),
    )


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_document_enricher_emits_admission_hp_for_inpatient_encounter() -> None:
    """INPATIENT encounter → exactly 1 ADMISSION_HP document."""
    record = _make_record()
    ctx = _make_ctx(record)
    document_enricher(ctx)

    docs = record.documents
    hp_docs = [d for d in docs if d.task_type == "admission_hp"]
    assert len(hp_docs) == 1

    hp = hp_docs[0]
    assert hp.encounter_id == "enc1"
    assert hp.patient_id == "pt1"
    assert hp.loinc_code == "34117-2"
    assert hp.document_id.startswith(f"{DOC_REFERENCE_ID_PREFIX}enc1-")
    assert hp.author_practitioner_id == "dr1"
    assert isinstance(hp, ClinicalDocument)


def test_document_enricher_emits_progress_note_daily() -> None:
    """LOS=5 days → 5 PROGRESS_NOTE documents, one per day."""
    encounter = _make_encounter(
        admission_dt=ADMISSION_DT,
        discharge_dt=ADMISSION_DT + timedelta(days=5),
    )
    record = _make_record(encounter)
    ctx = _make_ctx(record)
    document_enricher(ctx)

    progress_docs = [d for d in record.documents if d.task_type == "progress_note"]
    assert len(progress_docs) == 5
    assert all(d.encounter_id == "enc1" for d in progress_docs)
    assert all(d.loinc_code == "11506-3" for d in progress_docs)
    assert all(isinstance(d, ClinicalDocument) for d in progress_docs)


def test_document_enricher_emits_discharge_summary_for_completed_inpatient() -> None:
    """Completed inpatient encounter → exactly 1 DISCHARGE_SUMMARY."""
    record = _make_record()  # default: completed, LOS=5
    ctx = _make_ctx(record)
    document_enricher(ctx)

    ds_docs = [d for d in record.documents if d.task_type == "discharge_summary"]
    assert len(ds_docs) == 1
    assert ds_docs[0].loinc_code == "18842-5"
    assert ds_docs[0].encounter_id == "enc1"


def test_document_enricher_skips_discharge_summary_for_in_progress_encounter() -> None:
    """AD-32: in-progress encounter (discharge_datetime=None) must NOT emit DISCHARGE_SUMMARY."""
    encounter = _make_encounter(
        status="in_progress",
        discharge_dt=None,
    )
    record = _make_record(encounter)
    ctx = _make_ctx(record)
    document_enricher(ctx)

    ds_docs = [d for d in record.documents if d.task_type == "discharge_summary"]
    assert len(ds_docs) == 0, "DISCHARGE_SUMMARY must be skipped for in-progress encounter"

    # ADMISSION_HP still emitted
    hp_docs = [d for d in record.documents if d.task_type == "admission_hp"]
    assert len(hp_docs) == 1


def test_document_enricher_emits_clinical_impressions_daily() -> None:
    """LOS=5 → 5 ClinicalImpressionRecords in extensions['clinical_impressions']."""
    encounter = _make_encounter(
        admission_dt=ADMISSION_DT,
        discharge_dt=ADMISSION_DT + timedelta(days=5),
    )
    record = _make_record(encounter)
    ctx = _make_ctx(record)
    document_enricher(ctx)

    impressions = record.extensions.get("clinical_impressions", [])
    assert len(impressions) == 5
    assert all(isinstance(imp, ClinicalImpressionRecord) for imp in impressions)

    assert impressions[0].encounter_id == "enc1"
    assert impressions[0].day_index == 0
    assert impressions[0].impression_id == f"{CLINICAL_IMPRESSION_ID_PREFIX}enc1-0"

    assert impressions[4].day_index == 4
    assert impressions[4].impression_id == f"{CLINICAL_IMPRESSION_ID_PREFIX}enc1-4"

    # Dates are sequential from admission
    for i, imp in enumerate(impressions):
        expected_date = ADMISSION_DT.date() + timedelta(days=i)
        assert imp.date == expected_date


def test_document_enricher_skips_cancelled_encounter() -> None:
    """CANCELLED encounter → no documents and no clinical impressions emitted."""
    encounter = _make_encounter(status="cancelled", discharge_dt=None)
    record = _make_record(encounter)
    ctx = _make_ctx(record)
    document_enricher(ctx)

    assert record.documents == []
    assert record.extensions.get("clinical_impressions", []) == []


def test_document_enricher_locale_gating_us_excludes_jp_only_specs() -> None:
    """US context: only US-supported specs applied; JP-only spec produces 0 docs for US."""
    jp_only_spec = DocumentTypeSpec(
        type_key="admission_hp",       # valid DocumentType value
        loinc_code="34117-2",
        display_en="JP-only H&P",
        display_ja="JP限定入院記録",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp",),
        generation_frequency="admission_once",
        composition_sections=("chief_complaint",),
    )

    with patch("clinosim.modules.document.engine.specs_for_country") as mock_specs:
        # "jp" gets the JP-only spec; "us" gets nothing
        mock_specs.side_effect = lambda c: [jp_only_spec] if c == "jp" else []

        # US context: 0 docs (no applicable specs)
        record_us = _make_record()
        ctx_us = _make_ctx(record_us, country="us")
        document_enricher(ctx_us)
        assert record_us.documents == [], "US context must not generate JP-only docs"

        # JP context: 1 doc (jp_only_spec, admission_once)
        record_jp = _make_record()
        ctx_jp = _make_ctx(record_jp, country="jp")
        document_enricher(ctx_jp)
        assert len(record_jp.documents) == 1
        assert record_jp.documents[0].task_type == "admission_hp"
        # JP locale → language field should be "ja"
        assert record_jp.documents[0].language == "ja"


# NOTE (AD-65): the former test_document_enricher_preserves_sections_for_composition
# asserted that document_enricher populates ClinicalDocument.sections with composition
# content. That is no longer this stage's responsibility: per the AD-65 two-pass
# architecture, document_enricher (POST_ENCOUNTER) only creates structural stubs with
# narrative=None; TemplateNarrativePass (Stage 2) is what populates
# ClinicalDocument.narrative.sections. That behavior is covered at the correct
# boundary by tests/unit/test_template_narrative_pass.py. Deleted rather than
# force-passed against a stub.


def test_document_enricher_stub_has_no_narrative() -> None:
    """AD-65 Stage 1/Stage 2 boundary: document_enricher only creates structural
    stubs; narrative content (text/sections) is populated later by
    TemplateNarrativePass, not by the enricher. Every doc emitted here must
    carry narrative=None regardless of format_type.
    """
    record = _make_record()
    ctx = _make_ctx(record)
    document_enricher(ctx)

    assert len(record.documents) > 0
    assert all(d.narrative is None for d in record.documents), (
        "document_enricher must not populate narrative — that is Stage 2's job"
    )


def test_document_enricher_sets_format_type_for_dispatch() -> None:
    """I-1 regression: ClinicalDocument.format_type must match the
    DocumentTypeSpec.format_type.value so Task 9 builder can dispatch.
    Task 8 fix: enricher now passes format_type=spec.format_type.value at all 3 emission sites.
    """
    record = _make_record()
    ctx = _make_ctx(record)
    document_enricher(ctx)

    # PROGRESS_NOTE → free_text
    progress_docs = [d for d in record.documents if d.task_type == "progress_note"]
    assert len(progress_docs) > 0
    for d in progress_docs:
        assert d.format_type == "free_text", (
            f"progress_note must have format_type='free_text', got '{d.format_type}'"
        )

    # ADMISSION_HP → composition
    hp_docs = [d for d in record.documents if d.task_type == "admission_hp"]
    assert len(hp_docs) == 1
    assert hp_docs[0].format_type == "composition", (
        f"admission_hp must have format_type='composition', got '{hp_docs[0].format_type}'"
    )

    # DISCHARGE_SUMMARY → composition
    ds_docs = [d for d in record.documents if d.task_type == "discharge_summary"]
    assert len(ds_docs) == 1
    assert ds_docs[0].format_type == "composition", (
        f"discharge_summary must have format_type='composition', got '{ds_docs[0].format_type}'"
    )


def test_document_enricher_deterministic() -> None:
    """Same master_seed + same encounter → identical document IDs and task types.

    AD-65 note: narrative text is no longer produced by document_enricher (it
    stays None until TemplateNarrativePass runs), so text-equality is no
    longer part of this stage's determinism contract; see
    tests/unit/test_template_narrative_pass.py::test_template_pass_deterministic
    for narrative-stage determinism coverage.
    """

    def _run(seed: int) -> tuple[list[ClinicalDocument], list[ClinicalImpressionRecord]]:
        record = _make_record(encounter=_make_encounter())
        ctx = _make_ctx(record, master_seed=seed)
        document_enricher(ctx)
        impressions: list[ClinicalImpressionRecord] = record.extensions.get(
            "clinical_impressions", []
        )
        return record.documents, impressions

    docs1, imps1 = _run(42)
    docs2, imps2 = _run(42)

    assert len(docs1) == len(docs2)
    for d1, d2 in zip(docs1, docs2):
        assert d1.document_id == d2.document_id
        assert d1.task_type == d2.task_type
        assert d1.language == d2.language

    assert len(imps1) == len(imps2)
    for i1, i2 in zip(imps1, imps2):
        assert i1.impression_id == i2.impression_id
        assert i1.day_index == i2.day_index
        assert i1.date == i2.date
