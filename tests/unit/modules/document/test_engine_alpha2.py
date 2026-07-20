"""Unit tests for document enricher α-min-2 encounter-type gating (Task 10).

Tests cover:
- Inpatient encounter (LOS=1) → 4 documents (H&P + Discharge + nursing admission + nursing discharge)
- Outpatient encounter → 1 OUTPATIENT_SOAP document only
- Emergency encounter → 1 ED_NOTE + 1 ED_TRIAGE_NOTE
- ClinicalImpression only emitted for inpatient/icu/rehab_inpatient (not outpatient/emergency)
- encounter_once frequency dispatches to day_index=0
- Cancelled encounter → no documents (α-min-1 behavior preserved)
- α-min-1 specs (admission_hp / progress_note / discharge_summary) do NOT leak into outpatient
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from clinosim.modules.document.engine import document_enricher

# ─── Fixtures ────────────────────────────────────────────────────────────────

ADMISSION_DT = datetime(2026, 7, 1, 10, 0)
LOS_1_DT = ADMISSION_DT + timedelta(days=1)  # same-day discharge
LOS_3_DT = ADMISSION_DT + timedelta(days=3)


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
    discharge_dt: datetime | None = LOS_1_DT,
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
) -> SimpleNamespace:
    if encounter is None:
        encounter = _make_encounter()
    return SimpleNamespace(
        patient=_make_patient(),
        encounters=[encounter],
        documents=[],
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


def test_inpatient_encounter_los1_gets_5_documents() -> None:
    """Inpatient LOS=1 → 5 documents: H&P + progress_note(1) + Discharge +
    nursing admission + nursing discharge.

    Issue #337 (session 62): 従来 LOS=1 で progress_note を skip していたが、
    eDS Composition (discharge_summary、discharge_once) は LOS=1 でも emit
    されるため hospitalCourseSection.entry min=1 の valid DocumentReference
    target 欠落 → v9 で 3 件 slice error 発火。LOS=1 の 1 progress_note は
    「入院当日 = 全入院期間の hospital course summary」として clinically
    valid、spec 準拠と両立。

    daily_3shift (nursing_shift_note) は 3-per-day cadence 保持のため
    LOS=1 skip を維持。
    """
    encounter = _make_encounter(enc_type="inpatient", discharge_dt=LOS_1_DT)
    record = _make_record(encounter)
    ctx = _make_ctx(record)
    document_enricher(ctx)

    docs = record.documents
    task_types = [d.task_type for d in docs]

    assert "admission_hp" in task_types, f"expected admission_hp in {task_types}"
    assert "discharge_summary" in task_types, f"expected discharge_summary in {task_types}"
    assert "admission_nursing_assessment" in task_types, f"expected admission_nursing_assessment in {task_types}"
    assert "nursing_discharge_summary" in task_types, f"expected nursing_discharge_summary in {task_types}"
    # Issue #337: progress_note (daily) は LOS=1 で 1 件 emit(spec 準拠)
    assert task_types.count("progress_note") == 1, (
        f"progress_note must have exactly 1 emit for LOS=1 (Issue #337), got {task_types}"
    )
    # nursing_shift_note (daily_3shift) は LOS=1 で依然 skip
    assert "nursing_shift_note" not in task_types, f"nursing_shift_note must be skipped for LOS=1, got {task_types}"
    assert len(docs) == 5, f"Expected 5 documents for LOS=1 inpatient (Issue #337), got {len(docs)}: {task_types}"


def test_inpatient_encounter_los3_gets_16_documents() -> None:
    """Inpatient LOS=3 → 16 documents: H&P + PN×3 + DS + nursing admission + shift×9 + nursing DS.

    α-min-3: nursing_shift_note is `daily_3shift` (3 notes per LOS day:
    night/day/evening) → 3 days × 3 shifts = 9 shift notes.
    """
    encounter = _make_encounter(enc_type="inpatient", discharge_dt=LOS_3_DT)
    record = _make_record(encounter)
    ctx = _make_ctx(record)
    document_enricher(ctx)

    docs = record.documents
    task_types = [d.task_type for d in docs]

    assert task_types.count("admission_hp") == 1
    assert task_types.count("progress_note") == 3
    assert task_types.count("discharge_summary") == 1
    assert task_types.count("admission_nursing_assessment") == 1
    assert task_types.count("nursing_shift_note") == 9
    assert task_types.count("nursing_discharge_summary") == 1
    assert len(docs) == 16, f"Expected 16 documents for LOS=3 inpatient, got {len(docs)}: {task_types}"


def test_outpatient_encounter_gets_only_outpatient_soap() -> None:
    """Outpatient encounter → exactly 1 OUTPATIENT_SOAP document; no inpatient docs."""
    encounter = _make_encounter(enc_type="outpatient", discharge_dt=LOS_1_DT)
    record = _make_record(encounter)
    ctx = _make_ctx(record)
    document_enricher(ctx)

    docs = record.documents
    task_types = [d.task_type for d in docs]

    assert task_types == ["outpatient_soap"], f"Outpatient must emit exactly ['outpatient_soap'], got {task_types}"

    soap = docs[0]
    assert soap.encounter_id == "enc1"
    assert soap.loinc_code == "34131-3"
    assert soap.format_type == "composition"


def test_outpatient_encounter_no_inpatient_docs_leak() -> None:
    """Outpatient encounter must NOT receive admission_hp / progress_note / discharge_summary."""
    encounter = _make_encounter(enc_type="outpatient", discharge_dt=LOS_1_DT)
    record = _make_record(encounter)
    ctx = _make_ctx(record)
    document_enricher(ctx)

    task_types = [d.task_type for d in record.documents]
    for inpatient_type in (
        "admission_hp",
        "progress_note",
        "discharge_summary",
        "admission_nursing_assessment",
        "nursing_shift_note",
        "nursing_discharge_summary",
    ):
        assert inpatient_type not in task_types, (
            f"Inpatient spec '{inpatient_type}' must NOT leak into outpatient encounter"
        )


def test_emergency_encounter_gets_ed_note_plus_triage() -> None:
    """Emergency encounter → exactly 1 ED_NOTE + 1 ED_TRIAGE_NOTE = 2 documents total."""
    encounter = _make_encounter(enc_type="emergency", discharge_dt=LOS_1_DT)
    record = _make_record(encounter)
    ctx = _make_ctx(record)
    document_enricher(ctx)

    docs = record.documents
    task_types = [d.task_type for d in docs]

    assert "ed_note" in task_types, f"ED encounter must emit ed_note, got {task_types}"
    assert "ed_triage_note" in task_types, f"ED encounter must emit ed_triage_note, got {task_types}"
    assert len(docs) == 2, f"Expected 2 documents for emergency encounter, got {len(docs)}: {task_types}"

    ed_note = next(d for d in docs if d.task_type == "ed_note")
    assert ed_note.loinc_code == "34878-9"
    assert ed_note.encounter_id == "enc1"

    triage_note = next(d for d in docs if d.task_type == "ed_triage_note")
    assert triage_note.loinc_code == "54094-8"
    assert triage_note.encounter_id == "enc1"


def test_emergency_encounter_no_inpatient_docs_leak() -> None:
    """Emergency encounter must NOT receive any inpatient or outpatient document types."""
    encounter = _make_encounter(enc_type="emergency", discharge_dt=LOS_1_DT)
    record = _make_record(encounter)
    ctx = _make_ctx(record)
    document_enricher(ctx)

    task_types = [d.task_type for d in record.documents]
    for other_type in (
        "admission_hp",
        "progress_note",
        "discharge_summary",
        "admission_nursing_assessment",
        "nursing_shift_note",
        "nursing_discharge_summary",
        "outpatient_soap",
    ):
        assert other_type not in task_types, f"Non-ED spec '{other_type}' must NOT appear in emergency encounter docs"


def test_clinical_impression_only_for_inpatient() -> None:
    """ClinicalImpression is emitted only for inpatient/icu/rehab_inpatient, NOT for outpatient/emergency."""
    for enc_type in ("inpatient", "icu", "rehab_inpatient"):
        encounter = _make_encounter(enc_type=enc_type, discharge_dt=LOS_1_DT)
        record = _make_record(encounter)
        ctx = _make_ctx(record)
        document_enricher(ctx)
        impressions = record.extensions.get("clinical_impressions", [])
        assert len(impressions) > 0, f"ClinicalImpression must be emitted for enc_type='{enc_type}'"

    for enc_type in ("outpatient", "emergency"):
        encounter = _make_encounter(enc_type=enc_type, discharge_dt=LOS_1_DT)
        record = _make_record(encounter)
        ctx = _make_ctx(record)
        document_enricher(ctx)
        impressions = record.extensions.get("clinical_impressions", [])
        assert len(impressions) == 0, (
            f"ClinicalImpression must NOT be emitted for enc_type='{enc_type}', got {len(impressions)}"
        )


def test_encounter_once_frequency_emits_at_day_0() -> None:
    """encounter_once frequency emits exactly 1 document with authored_datetime = admission_dt."""
    encounter = _make_encounter(enc_type="outpatient", discharge_dt=LOS_1_DT)
    record = _make_record(encounter)
    ctx = _make_ctx(record)
    document_enricher(ctx)

    docs = record.documents
    assert len(docs) == 1
    soap = docs[0]
    # authored_datetime should be the admission datetime (day 0)
    assert soap.authored_datetime == ADMISSION_DT.isoformat(), (
        f"encounter_once doc authored_datetime must be admission_dt, got '{soap.authored_datetime}'"
    )
    assert soap.period_start == ADMISSION_DT.isoformat()


def test_cancelled_encounter_no_documents_alpha2() -> None:
    """Cancelled encounter → no documents and no clinical impressions (α-min-1 behavior preserved)."""
    for enc_type in ("inpatient", "outpatient", "emergency"):
        encounter = _make_encounter(enc_type=enc_type, status="cancelled", discharge_dt=None)
        record = _make_record(encounter)
        ctx = _make_ctx(record)
        document_enricher(ctx)

        assert record.documents == [], f"Cancelled {enc_type} encounter must produce no documents"
        assert record.extensions.get("clinical_impressions", []) == [], (
            f"Cancelled {enc_type} encounter must produce no clinical impressions"
        )


def test_encounter_once_document_id_prefix() -> None:
    """encounter_once documents use the DOC_REFERENCE_ID_PREFIX canonical prefix."""
    from clinosim.modules.document import DOC_REFERENCE_ID_PREFIX

    encounter = _make_encounter(enc_type="emergency", enc_id="enc-ed-1", discharge_dt=LOS_1_DT)
    record = _make_record(encounter)
    ctx = _make_ctx(record)
    document_enricher(ctx)

    for doc in record.documents:
        assert doc.document_id.startswith(DOC_REFERENCE_ID_PREFIX), (
            f"document_id '{doc.document_id}' must start with '{DOC_REFERENCE_ID_PREFIX}'"
        )
        assert "enc-ed-1" in doc.document_id, f"document_id '{doc.document_id}' must contain encounter_id 'enc-ed-1'"
