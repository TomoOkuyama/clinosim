"""document_enricher dispatch tests for rehabilitation_plan (chain 2, third
and final chain-2 sub-project).

Covers the NEW admission_once_if_rehab_sessions generation_frequency — proves
BOTH the positive case (RehabSession present -> fires) and the negative case
(no RehabSession -> does not fire), per the nutrition_care_plan adv-1 lesson
(design spec §5). Also proves the encounter_types_supported=[inpatient]-only
scope: icu must NOT fire even with rehab sessions present (design spec §1 —
icu is a verified-unreachable EncounterType value; declaring support for it
would be a new aspirational-scaffold violation).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.engine import document_enricher


def _rehab_session(encounter_id: str, session_date: datetime) -> dict[str, Any]:
    return {
        "session_id": f"REHAB-{encounter_id}-001",
        "patient_id": "pt-rp-engine-test",
        "encounter_id": encounter_id,
        "therapy_type": "PT",
        "session_date": session_date,
        "duration_minutes": 40,
        "day_post_op": 1,
        "activities": ["bed exercises"],
        "patient_participation": "good",
        "pain_score": 3,
        "functional_progress": "stable",
    }


def _make_record(encounter_type: str, with_rehab: bool, encounter_id: str = "enc-rp-engine-test") -> dict[str, Any]:
    admission_dt = datetime(2026, 7, 1, 10, 0)
    return {
        "patient": {"patient_id": "pt-rp-engine-test"},
        "encounters": [
            {
                "encounter_id": encounter_id,
                "encounter_type": encounter_type,
                "status": "completed",
                "admission_datetime": admission_dt,
                "discharge_datetime": admission_dt + timedelta(days=10),
                "attending_physician_id": "dr-rp-engine-test",
                "primary_nurse_id": "ns-rp-engine-test",
            }
        ],
        "documents": [],
        "extensions": {},
        "physiological_states": [],
        "rehab_sessions": ([_rehab_session(encounter_id, admission_dt + timedelta(days=1))] if with_rehab else []),
    }


def _run_enricher(record: dict[str, Any], country: str) -> dict[str, Any]:
    ctx = SimpleNamespace(
        master_seed=42,
        records=[record],
        config=SimpleNamespace(country=country),
    )
    document_enricher(ctx)
    return record


def _rp_docs(record: dict[str, Any]) -> list[Any]:
    return [d for d in record["documents"] if getattr(d, "task_type", "") == "rehabilitation_plan"]


def test_jp_inpatient_with_rehab_sessions_gets_one_stub() -> None:
    record = _run_enricher(_make_record("inpatient", with_rehab=True), "jp")
    docs = _rp_docs(record)
    assert len(docs) == 1
    assert docs[0].loinc_code == "34823-5"


def test_jp_inpatient_without_rehab_sessions_gets_zero_stubs() -> None:
    record = _run_enricher(_make_record("inpatient", with_rehab=False), "jp")
    assert len(_rp_docs(record)) == 0


def test_jp_icu_with_rehab_sessions_gets_zero_stubs() -> None:
    """icu is not in encounter_types_supported (design spec §1: icu never fires
    in production, declaring support for it would be a new aspirational scaffold)."""
    record = _run_enricher(_make_record("icu", with_rehab=True), "jp")
    assert len(_rp_docs(record)) == 0


def test_us_inpatient_with_rehab_sessions_gets_zero_stubs() -> None:
    record = _run_enricher(_make_record("inpatient", with_rehab=True), "us")
    assert len(_rp_docs(record)) == 0


def test_authored_datetime_is_first_rehab_session_date_not_admission_date() -> None:
    """authored_datetime should reflect when the rehab plan was actually
    assessed (first session date), not the admission date (design spec §3b)."""
    record = _run_enricher(_make_record("inpatient", with_rehab=True), "jp")
    doc = _rp_docs(record)[0]
    assert doc.authored_datetime == "2026-07-02T10:00:00"
