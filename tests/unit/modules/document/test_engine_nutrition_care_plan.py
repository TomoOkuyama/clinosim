"""document_enricher dispatch tests for nutrition_care_plan (chain 2).

Covers the NEW admission_once_los_gt_7 generation_frequency — proves BOTH
the positive case (LOS>7 fires) and the negative case (LOS<=7 does not
fire), per the admission_care_plan adv-1 lesson (design spec §5).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.engine import document_enricher


def _make_record(encounter_type: str, los_days: int, country: str = "jp") -> dict[str, Any]:
    admission_dt = datetime(2026, 7, 1, 10, 0)
    return {
        "patient": {"patient_id": f"pt-ncp-engine-{los_days}"},
        "encounters": [
            {
                "encounter_id": f"enc-ncp-engine-{los_days}",
                "encounter_type": encounter_type,
                "status": "completed",
                "admission_datetime": admission_dt,
                "discharge_datetime": admission_dt + timedelta(days=los_days),
                "attending_physician_id": "dr-ncp-engine-test",
                "primary_nurse_id": "ns-ncp-engine-test",
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


def _ncp_docs(record: dict[str, Any]) -> list[Any]:
    return [d for d in record["documents"] if getattr(d, "task_type", "") == "nutrition_care_plan"]


def test_jp_inpatient_los_gt_7_gets_one_nutrition_care_plan_stub() -> None:
    record = _run_enricher(_make_record("inpatient", los_days=10), "jp")
    docs = _ncp_docs(record)
    assert len(docs) == 1
    assert docs[0].loinc_code == "80791-7"


def test_jp_inpatient_los_exactly_7_gets_zero_stubs() -> None:
    """Boundary: LOS==7 must NOT fire (spec requires strictly > 7)."""
    record = _run_enricher(_make_record("inpatient", los_days=7), "jp")
    assert len(_ncp_docs(record)) == 0


def test_jp_inpatient_los_5_gets_zero_stubs() -> None:
    record = _run_enricher(_make_record("inpatient", los_days=5), "jp")
    assert len(_ncp_docs(record)) == 0


def test_jp_icu_los_gt_7_gets_one_nutrition_care_plan_stub() -> None:
    record = _run_enricher(_make_record("icu", los_days=14), "jp")
    assert len(_ncp_docs(record)) == 1


def test_jp_rehab_inpatient_los_gt_7_gets_zero_stubs() -> None:
    record = _run_enricher(_make_record("rehab_inpatient", los_days=20), "jp")
    assert len(_ncp_docs(record)) == 0


def test_us_inpatient_los_gt_7_gets_zero_stubs() -> None:
    record = _run_enricher(_make_record("inpatient", los_days=10), "us")
    assert len(_ncp_docs(record)) == 0
