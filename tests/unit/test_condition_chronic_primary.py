"""Chronic-condition-aware primary encounter diagnosis (data-quality follow-up).

When an outpatient encounter's primary (encounter) diagnosis is a chronic
condition the patient already carries (e.g. a diabetes follow-up visit coding
E11.9), the Condition must reflect that the disease is ongoing — not "resolved"
on the visit day with onset = visit date. A chronic primary diagnosis gets
clinicalStatus=active and onsetDateTime = the chronic onset date, while
recordedDate stays the visit date. Acute primary diagnoses are unchanged
(resolved on outpatient discharge, onset = visit date).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4_adapter import _build_conditions

pytestmark = pytest.mark.unit


def _primary(conditions: list[dict]) -> dict:
    return next(c for c in conditions if c["id"].endswith("-primary"))


def _status(cond: dict) -> str:
    return cond["clinicalStatus"]["coding"][0]["code"]


def test_outpatient_chronic_primary_is_active_with_chronic_onset() -> None:
    record = {
        "clinical_diagnosis": {"discharge_diagnosis_code": "E11.9"},
        "encounters": [
            {
                "encounter_id": "enc-1",
                "encounter_type": "outpatient",
                "admission_datetime": "2026-05-01T10:00:00",
                "discharge_datetime": "2026-05-01T11:00:00",
            }
        ],
        "patient": {"chronic_conditions": [{"code": "E11.9", "onset_date": "2020-03-15"}]},
    }
    primary = _primary(_build_conditions(record, "pat-1", "US"))
    assert _status(primary) == "active"
    assert primary["onsetDateTime"] == "2020-03-15"
    # recordedDate is when the diagnosis was recorded at this visit, not onset.
    assert primary["recordedDate"] == "2026-05-01"


def test_outpatient_acute_primary_stays_resolved_with_visit_onset() -> None:
    record = {
        "clinical_diagnosis": {"discharge_diagnosis_code": "J06.9"},  # acute URI
        "encounters": [
            {
                "encounter_id": "enc-2",
                "encounter_type": "outpatient",
                "admission_datetime": "2026-05-01T10:00:00",
                "discharge_datetime": "2026-05-01T11:00:00",
            }
        ],
        "patient": {"chronic_conditions": [{"code": "E11.9", "onset_date": "2020-03-15"}]},
    }
    primary = _primary(_build_conditions(record, "pat-2", "US"))
    assert _status(primary) == "resolved"
    assert primary["onsetDateTime"] == "2026-05-01"
    assert primary["recordedDate"] == "2026-05-01"
