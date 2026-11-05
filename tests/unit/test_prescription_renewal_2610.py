"""Issue #2610: a renewal ends the previous prescription; each states its end."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.order.prescription_supersede import prescription_closures

pytestmark = pytest.mark.unit


def _rec(pid: str, enc_id: str, etype: str, issued: datetime, items: list[dict], dod: date | None = None):
    enc = SimpleNamespace(encounter_id=enc_id, encounter_type=etype, admission_datetime=issued)
    rx = SimpleNamespace(issue_date=issued, items=items)
    patient = SimpleNamespace(patient_id=pid, date_of_death=dod)
    return SimpleNamespace(patient=patient, encounters=[enc], discharge_prescription=rx)


_END = date(2025, 12, 31)


def _item(name: str, days: int = 28) -> dict:
    return {"drug_name": name, "dose": "5mg", "duration_days": days}


def test_a_renewal_completes_the_earlier_prescription_and_links_to_it() -> None:
    a = _rec("P1", "ENC-A", "outpatient", datetime(2025, 3, 1, 10), [_item("Amlodipine"), _item("Atorvastatin", 90)])
    b = _rec("P1", "ENC-B", "outpatient", datetime(2025, 4, 1, 10), [_item("Amlodipine")])
    closures = prescription_closures([b, a], _END)
    assert closures[("ENC-A", 1)] == {"status": "completed", "end_date": "2025-04-01"}
    assert closures[("ENC-B", 1)]["prior_rx"] == {"encounter_id": "ENC-A", "encounter_type": "outpatient", "seq": 1}
    # Atorvastatin was not renewed: its 90-day supply ends 2025-05-30, before the end of the run.
    assert closures[("ENC-A", 2)] == {"status": "completed", "end_date": "2025-05-30"}
    # The CIF items are not changed (the closure depends on the snapshot).
    assert "status" not in a.discharge_prescription.items[0]


def test_the_last_prescription_still_in_supply_stays_active() -> None:
    a = _rec("P1", "ENC-A", "inpatient", datetime(2025, 12, 20, 10), [_item("Amlodipine", 30)])
    assert prescription_closures([a], _END) == {}


def test_a_death_stops_the_prescription() -> None:
    a = _rec("P1", "ENC-A", "outpatient", datetime(2025, 3, 1, 10), [_item("Amlodipine", 90)], dod=date(2025, 4, 10))
    assert prescription_closures([a], _END)[("ENC-A", 1)] == {"status": "stopped", "end_date": "2025-04-10"}


def test_the_medication_request_carries_status_end_and_prior() -> None:
    from clinosim.modules.output.fhir_r4.medications.medications import _build_discharge_medication_request

    item = {
        **_item("Amlodipine"),
        "status": "completed",
        "end_date": "2025-04-01",
        "prior_rx": {"encounter_id": "ENC-0", "encounter_type": "outpatient", "seq": 2},
    }
    mr = _build_discharge_medication_request(item, "P1", "US", "ENC-A", "outpatient", 1, "2025-03-01T10:00:00Z")
    assert mr["status"] == "completed"
    assert mr["dispenseRequest"]["validityPeriod"]["end"].startswith("2025-04-01")
    assert mr["priorPrescription"]["reference"].startswith("MedicationRequest/")


def test_a_drug_listed_twice_links_only_its_first_copy() -> None:
    a = _rec("P1", "ENC-A", "outpatient", datetime(2025, 3, 1, 10), [_item("Methyldopa"), _item("Methyldopa")])
    b = _rec("P1", "ENC-B", "outpatient", datetime(2025, 4, 1, 10), [_item("Methyldopa"), _item("Methyldopa")])
    closures = prescription_closures([a, b], _END)
    assert closures[("ENC-B", 1)]["prior_rx"]["seq"] == 1
    assert "prior_rx" not in closures.get(("ENC-B", 2), {})
    assert closures[("ENC-A", 2)]["status"] == "completed"
