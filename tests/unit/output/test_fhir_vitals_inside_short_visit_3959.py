"""A vital-sign Observation stays inside its Encounter (Issue #3959).

The temperature (+30 s), respiratory rate (+60 s) and SpO2 (+5 s) of a vital-sign
set are timed a few seconds after the set. A vaccination visit of 5 minutes whose
vitals are stamped at the visit end put them after the Encounter's period end.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.labs.observations import _shifted_vital_time
from clinosim.modules.output.fhir_r4.lib.ed_reattribution import vital_sign_encounter_end
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_vitals

_VISIT_START = "2025-10-14T10:10:00"
_VISIT_END = "2025-10-14T10:15:00"


def _vitals(ts: str, **extra) -> dict:
    return {
        "timestamp": ts,
        "heart_rate": 72,
        "respiratory_rate": 16,
        "systolic_bp": 120,
        "diastolic_bp": 75,
        "spo2": 98,
        "temperature_celsius": 36.8,
        **extra,
    }


def _ctx(encounters: list[dict], vital_signs: list[dict], primary: str = "ENC-OP-1") -> SimpleNamespace:
    return SimpleNamespace(
        record={"encounters": encounters, "vital_signs": vital_signs},
        patient_data={"date_of_birth": "1980-01-01", "age": 45},
        patient_id="P1",
        country="JP",
        primary_enc_id=primary,
    )


def _clinic_visit(start: str = _VISIT_START, end: str = _VISIT_END) -> dict:
    return {
        "encounter_id": "ENC-OP-1",
        "encounter_type": "outpatient",
        "admission_datetime": start,
        "discharge_datetime": end,
    }


def _naive(value: str) -> datetime:
    return datetime.fromisoformat(value.split("+")[0])


def test_shifted_vitals_of_a_set_at_the_visit_end_stay_inside_the_encounter() -> None:
    ctx = _ctx([_clinic_visit()], [_vitals(_VISIT_END)])
    observations = _bb_vitals(ctx)
    assert observations
    end = _naive(_VISIT_END)
    for obs in observations:
        assert _naive(obs["effectiveDateTime"]) <= end, obs["code"]["text"]
    by_loinc = {o["code"]["coding"][0]["code"]: o for o in observations}
    # temperature (8310-5), respiratory rate (9279-1), SpO2 (2708-6): all at the visit end
    for loinc in ("8310-5", "9279-1", "2708-6"):
        assert _naive(by_loinc[loinc]["effectiveDateTime"]) == end


def test_an_offset_that_fits_inside_the_visit_is_kept() -> None:
    ctx = _ctx([_clinic_visit()], [_vitals("2025-10-14T10:12:00")])
    by_loinc = {o["code"]["coding"][0]["code"]: o for o in _bb_vitals(ctx)}
    assert _naive(by_loinc["8310-5"]["effectiveDateTime"]) == datetime(2025, 10, 14, 10, 12, 30)
    assert _naive(by_loinc["9279-1"]["effectiveDateTime"]) == datetime(2025, 10, 14, 10, 13, 0)
    assert _naive(by_loinc["2708-6"]["effectiveDateTime"]) == datetime(2025, 10, 14, 10, 12, 5)


def test_vitals_of_the_ed_bridge_end_with_the_ed_phase() -> None:
    from clinosim.modules._shared import ED_TRIAGE_DATA_SOURCE
    from clinosim.modules.triage.engine import admitted_ed_stay

    admission = datetime(2026, 6, 27, 12, 57)
    imp = {
        "encounter_id": "ENC-IMP-1",
        "encounter_type": "inpatient",
        "admit_source": "emd",
        "admission_datetime": admission.isoformat(),
        "discharge_datetime": "2026-07-02T10:00:00",
    }
    arrival = _vitals((admission).isoformat(), data_source=ED_TRIAGE_DATA_SOURCE)
    ctx = _ctx([imp], [arrival], primary="ENC-IMP-1")
    assert vital_sign_encounter_end(arrival, ctx) == admission
    assert admission - admitted_ed_stay() < admission
    for obs in _bb_vitals(ctx):
        assert _naive(obs["effectiveDateTime"]) <= admission


def test_encounter_end_is_that_of_the_encounter_the_set_is_attributed_to() -> None:
    ctx = _ctx([_clinic_visit()], [])
    assert vital_sign_encounter_end(_vitals(_VISIT_END), ctx) == datetime(2025, 10, 14, 10, 15)


def test_no_encounter_end_leaves_the_offset_alone() -> None:
    ctx = _ctx([{"encounter_id": "ENC-OP-1", "admission_datetime": _VISIT_START}], [])
    assert vital_sign_encounter_end(_vitals(_VISIT_END), ctx) is None


@pytest.mark.parametrize(
    ("base", "offset", "end", "expected"),
    [
        ("10:15:00", 30, "10:15:00", "10:15:00"),
        ("10:14:40", 30, "10:15:00", "10:15:00"),
        ("10:14:00", 30, "10:15:00", "10:14:30"),
        ("10:15:00", 30, None, "10:15:30"),
        # a set already stamped after the end is never pulled earlier than the set itself
        ("10:16:00", 30, "10:15:00", "10:16:00"),
    ],
)
def test_shifted_vital_time(base: str, offset: int, end: str | None, expected: str) -> None:
    day = "2025-10-14T"
    result = _shifted_vital_time(
        datetime.fromisoformat(day + base), offset, datetime.fromisoformat(day + end) if end else None
    )
    assert result == datetime.fromisoformat(day + expected)
