"""Unit tests for the document enricher `daily_3shift` frequency (α-min-3).

NURSING_SHIFT_NOTE moves from 1 note per LOS day (`daily`) to the realistic
acute-care cadence of 3 notes per LOS day (`daily_3shift`): night (00:00) /
day (08:00) / evening (16:00), chronological within each calendar day.

Covers:
- 3 × LOS-days stubs with unique deterministic ids carrying a shift token
- authored_datetime = day date + shift offset (00:00 / 08:00 / 16:00)
- neutral shift key ("night"/"day"/"evening") stored on the stub (AD-30 spirit:
  labels are resolved at Stage 2 render time by language, never baked into CIF)
- LOS=1 same-day skip rule mirrors the `daily` branch (spec §7)
- AD-32 in-progress encounters use the same los_days proxy as `daily`
- non-3shift documents keep shift == "" (backward compat)
- structural invariant: nursing_shift_note count == 3 × progress_note count
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.document import DOC_REFERENCE_ID_PREFIX
from clinosim.modules.document.engine import SHIFT_SCHEDULE, document_enricher

pytestmark = pytest.mark.unit

ADMISSION_DT = datetime(2026, 7, 1, 10, 0)
LOS_1_DT = ADMISSION_DT + timedelta(days=1)
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
    discharge_dt: datetime | None = LOS_3_DT,
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


def _make_record(encounter: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        patient=_make_patient(),
        encounters=[encounter],
        documents=[],
        extensions={},
        physiological_states=[],
    )


def _make_ctx(record: SimpleNamespace, country: str = "us") -> SimpleNamespace:
    return SimpleNamespace(
        master_seed=42,
        records=[record],
        config=SimpleNamespace(country=country),
    )


def _shift_notes(record: SimpleNamespace) -> list:
    return [d for d in record.documents if d.task_type == "nursing_shift_note"]


# ─── SHIFT_SCHEDULE canonical constant ──────────────────────────────────────


def test_shift_schedule_is_canonical_3_shifts_chronological() -> None:
    """SHIFT_SCHEDULE = night 00:00 / day 08:00 / evening 16:00, chronological."""
    keys = [k for k, _ in SHIFT_SCHEDULE]
    hours = [h for _, h in SHIFT_SCHEDULE]
    assert keys == ["night", "day", "evening"]
    assert hours == [0, 8, 16]
    assert hours == sorted(hours), "shifts must be chronological within a calendar day"


# ─── daily_3shift emission ───────────────────────────────────────────────────


def test_los3_emits_9_nursing_shift_notes() -> None:
    """LOS=3 inpatient → 3 shifts × 3 days = 9 nursing_shift_note stubs."""
    record = _make_record(_make_encounter(discharge_dt=LOS_3_DT))
    document_enricher(_make_ctx(record))
    notes = _shift_notes(record)
    assert len(notes) == 9, f"Expected 9 shift notes for LOS=3, got {len(notes)}"


def test_shift_note_count_is_3x_progress_note_count() -> None:
    """nursing_shift_note (daily_3shift) == 3 × progress_note (daily), same skip rules."""
    record = _make_record(_make_encounter(discharge_dt=LOS_3_DT))
    document_enricher(_make_ctx(record))
    progress = [d for d in record.documents if d.task_type == "progress_note"]
    assert len(_shift_notes(record)) == 3 * len(progress)


def test_shift_keys_complete_per_day() -> None:
    """Each LOS day carries exactly one night + one day + one evening note."""
    record = _make_record(_make_encounter(discharge_dt=LOS_3_DT))
    document_enricher(_make_ctx(record))
    by_date: dict[str, list[str]] = {}
    for doc in _shift_notes(record):
        authored = datetime.fromisoformat(doc.authored_datetime)
        by_date.setdefault(authored.date().isoformat(), []).append(doc.shift)
    assert len(by_date) == 3, f"Expected notes on 3 distinct dates, got {sorted(by_date)}"
    for day, shifts in by_date.items():
        assert shifts == ["night", "day", "evening"], (
            f"Day {day}: expected chronological [night, day, evening], got {shifts}"
        )


def test_authored_datetime_uses_shift_hour_offsets() -> None:
    """authored_datetime = calendar day date + 00:00 / 08:00 / 16:00 (not admission time)."""
    record = _make_record(_make_encounter(discharge_dt=LOS_3_DT))
    document_enricher(_make_ctx(record))
    hours = {datetime.fromisoformat(d.authored_datetime).hour for d in _shift_notes(record)}
    assert hours == {0, 8, 16}, f"Expected shift hours {{0, 8, 16}}, got {hours}"
    minutes = {datetime.fromisoformat(d.authored_datetime).minute for d in _shift_notes(record)}
    assert minutes == {0}, f"Shift note minutes must be 00, got {minutes}"


def test_period_matches_authored_datetime() -> None:
    """period_start == period_end == authored_datetime (mirrors the daily branch)."""
    record = _make_record(_make_encounter(discharge_dt=LOS_3_DT))
    document_enricher(_make_ctx(record))
    for doc in _shift_notes(record):
        assert doc.period_start == doc.authored_datetime
        assert doc.period_end == doc.authored_datetime


def test_document_ids_unique_with_shift_token() -> None:
    """document_id extends the id scheme with a shift token and stays globally unique."""
    record = _make_record(_make_encounter(enc_id="enc-3s-1", discharge_dt=LOS_3_DT))
    document_enricher(_make_ctx(record))
    ids = [d.document_id for d in _shift_notes(record)]
    assert len(ids) == len(set(ids)), f"Duplicate document ids: {ids}"
    for doc in _shift_notes(record):
        assert doc.document_id.startswith(DOC_REFERENCE_ID_PREFIX)
        assert "enc-3s-1" in doc.document_id
        assert doc.document_id.endswith(f"-{doc.shift}"), (
            f"id '{doc.document_id}' must carry shift token '-{doc.shift}'"
        )
    all_ids = [d.document_id for d in record.documents]
    assert len(all_ids) == len(set(all_ids)), "shift ids must not collide with other docs"


def test_shift_key_stored_on_stub_is_neutral() -> None:
    """Stubs carry the neutral shift key; no localized labels in structural CIF (AD-30)."""
    record = _make_record(_make_encounter(discharge_dt=LOS_3_DT))
    document_enricher(_make_ctx(record, country="jp"))
    for doc in _shift_notes(record):
        assert doc.shift in {"night", "day", "evening"}, f"non-neutral shift: {doc.shift!r}"


def test_non_3shift_documents_have_empty_shift() -> None:
    """All non-daily_3shift documents keep shift == '' (backward compat)."""
    record = _make_record(_make_encounter(discharge_dt=LOS_3_DT))
    document_enricher(_make_ctx(record))
    for doc in record.documents:
        if doc.task_type != "nursing_shift_note":
            assert doc.shift == "", f"{doc.task_type} must not carry a shift key"


def test_stub_only_no_narrative_content() -> None:
    """AD-65: daily_3shift stubs are structural only (narrative=None)."""
    record = _make_record(_make_encounter(discharge_dt=LOS_3_DT))
    document_enricher(_make_ctx(record))
    for doc in _shift_notes(record):
        assert doc.narrative is None


# ─── skip rules (mirror `daily`) ─────────────────────────────────────────────


def test_los1_same_day_encounter_skips_shift_notes() -> None:
    """Spec §7: LOS=1 same-day encounters emit no intermediate shift notes."""
    record = _make_record(_make_encounter(discharge_dt=LOS_1_DT))
    document_enricher(_make_ctx(record))
    assert _shift_notes(record) == []


def test_in_progress_encounter_uses_los_proxy() -> None:
    """AD-32: in-progress encounter (discharge=None) emits 3 notes per elapsed day.

    physiological_states has one entry per day + admission state; len=4 → 3 days,
    same proxy the `daily` branch uses via _compute_los_days.
    """
    record = _make_record(_make_encounter(discharge_dt=None, status="in_progress"))
    record.physiological_states = [SimpleNamespace()] * 4  # admission + 3 days
    document_enricher(_make_ctx(record))
    assert len(_shift_notes(record)) == 9


def test_cancelled_encounter_emits_no_shift_notes() -> None:
    """AD-32: cancelled encounters produce no documents at all."""
    record = _make_record(_make_encounter(status="cancelled", discharge_dt=None))
    document_enricher(_make_ctx(record))
    assert record.documents == []


def test_outpatient_and_emergency_get_no_shift_notes() -> None:
    """daily_3shift spec keeps the inpatient/icu/rehab allowlist (AD-64)."""
    for enc_type in ("outpatient", "emergency"):
        record = _make_record(_make_encounter(enc_type=enc_type, discharge_dt=LOS_1_DT))
        document_enricher(_make_ctx(record))
        assert _shift_notes(record) == [], f"shift note leaked into {enc_type}"
