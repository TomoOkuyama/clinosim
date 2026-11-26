"""Issue #3888: an order re-routed to the ED bridge Encounter is requested by
the stay's ED physician; orders after the admission keep the admitting physician."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.encounters.encounter import resolve_encounter_id
from clinosim.modules.output.fhir_r4.lib.ed_reattribution import reattribute_ed_phase_by_time
from clinosim.modules.triage.engine import admitted_ed_stay

pytestmark = pytest.mark.unit

_IMP = "ENC-POP-000001-111"
_IMP_REF = f"Encounter/{resolve_encounter_id(_IMP)}"
_ED_REF = f"Encounter/{resolve_encounter_id(f'{_IMP}-ED')}"
_ADM = "2026-03-24T10:37:00"
_ATTENDING = "DR-IM-0001"
_ED_DOC = "DR-EM-0003"


def _ctx(ed_physician_id: str = _ED_DOC):
    enc = {
        "encounter_id": _IMP,
        "admit_source": "emd",
        "admission_datetime": _ADM,
        "attending_physician_id": _ATTENDING,
        "ed_physician_id": ed_physician_id,
    }
    return SimpleNamespace(record={"encounters": [enc]})


def _in_window() -> str:
    return (datetime.fromisoformat(_ADM) - admitted_ed_stay() / 2).isoformat() + "Z"


def _orders(t: str) -> list[dict]:
    req = {"reference": f"Practitioner/{_ATTENDING}"}
    return [
        {
            "resourceType": "MedicationRequest",
            "authoredOn": t,
            "encounter": {"reference": _IMP_REF},
            "requester": dict(req),
            "recorder": dict(req),
        },
        {
            "resourceType": "ServiceRequest",
            "authoredOn": t,
            "encounter": {"reference": _IMP_REF},
            "requester": dict(req),
            "performer": [dict(req)],
        },
    ]


def test_ed_phase_orders_are_requested_by_the_ed_physician() -> None:
    ed = {"reference": f"Practitioner/{_ED_DOC}"}
    for r in _orders(_in_window()):
        reattribute_ed_phase_by_time(r, _ctx())
        assert r["encounter"]["reference"] == _ED_REF
        assert r["requester"] == ed, r["resourceType"]
    mr, sr = _orders(_in_window())
    reattribute_ed_phase_by_time(mr, _ctx())
    reattribute_ed_phase_by_time(sr, _ctx())
    assert mr["recorder"] == ed  # the recorder mirrors the requester (medications.py)
    assert sr["performer"] == [ed]  # the performer fallback mirrors the requester


def test_orders_after_admission_keep_the_admitting_physician() -> None:
    att = {"reference": f"Practitioner/{_ATTENDING}"}
    for r in _orders("2026-03-24T11:00:00Z"):
        reattribute_ed_phase_by_time(r, _ctx())
        assert r["encounter"]["reference"] == _IMP_REF
        assert r["requester"] == att


def test_no_ed_physician_leaves_the_requester_unchanged() -> None:
    att = {"reference": f"Practitioner/{_ATTENDING}"}
    for r in _orders(_in_window()):
        reattribute_ed_phase_by_time(r, _ctx(ed_physician_id=""))
        assert r["encounter"]["reference"] == _ED_REF
        assert r["requester"] == att


def test_a_distinct_performer_is_not_overwritten() -> None:
    sr = _orders(_in_window())[1]
    sr["performer"] = [{"reference": "Organization/hospital-main"}]
    reattribute_ed_phase_by_time(sr, _ctx())
    assert sr["performer"] == [{"reference": "Organization/hospital-main"}]


def test_observation_without_requester_gets_none() -> None:
    obs = {"resourceType": "Observation", "effectiveDateTime": _in_window(), "encounter": {"reference": _IMP_REF}}
    reattribute_ed_phase_by_time(obs, _ctx())
    assert "requester" not in obs
