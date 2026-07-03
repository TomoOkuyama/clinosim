"""document_enricher dispatch tests for admission_care_plan (chain 2).

No production code change expected — proves the existing generic
specs_for_country / specs_for_encounter_type / admission_once dispatch in
document_enricher already handles the new JP-only spec correctly (design
spec §3a claim).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.engine import document_enricher


def _make_record(encounter_type: str, status: str = "completed") -> dict[str, Any]:
    return {
        "patient": {"patient_id": "pt-acp-engine-test"},
        "encounters": [
            {
                "encounter_id": "enc-acp-engine-test",
                "encounter_type": encounter_type,
                "status": status,
                "admission_datetime": datetime(2026, 7, 1, 10, 0),
                "discharge_datetime": datetime(2026, 7, 5, 10, 0),
                "attending_physician_id": "dr-acp-engine-test",
                "primary_nurse_id": "ns-acp-engine-test",
            }
        ],
        "documents": [],
        "extensions": {},
        "physiological_states": [],
    }


def _run_enricher(record: dict[str, Any], country: str) -> dict[str, Any]:
    ctx = SimpleNamespace(
        master_seed=42,
        records=[record],
        config=SimpleNamespace(country=country),
    )
    document_enricher(ctx)
    return record


def _acp_docs(record: dict[str, Any]) -> list[Any]:
    return [d for d in record["documents"] if getattr(d, "task_type", "") == "admission_care_plan"]


def test_jp_inpatient_gets_one_admission_care_plan_stub() -> None:
    record = _run_enricher(_make_record("inpatient"), "jp")
    docs = _acp_docs(record)
    assert len(docs) == 1
    assert docs[0].loinc_code == "18776-5"
    assert docs[0].period_start == datetime(2026, 7, 1, 10, 0).isoformat()


def test_jp_icu_gets_one_admission_care_plan_stub() -> None:
    record = _run_enricher(_make_record("icu"), "jp")
    assert len(_acp_docs(record)) == 1


def test_jp_rehab_inpatient_gets_zero_admission_care_plan_stubs() -> None:
    record = _run_enricher(_make_record("rehab_inpatient"), "jp")
    assert len(_acp_docs(record)) == 0


def test_jp_outpatient_gets_zero_admission_care_plan_stubs() -> None:
    record = _run_enricher(_make_record("outpatient"), "jp")
    assert len(_acp_docs(record)) == 0


def test_jp_emergency_gets_zero_admission_care_plan_stubs() -> None:
    record = _run_enricher(_make_record("emergency"), "jp")
    assert len(_acp_docs(record)) == 0


def test_us_inpatient_gets_zero_admission_care_plan_stubs() -> None:
    record = _run_enricher(_make_record("inpatient"), "us")
    assert len(_acp_docs(record)) == 0
