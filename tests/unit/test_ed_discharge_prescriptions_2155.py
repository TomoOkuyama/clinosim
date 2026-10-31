"""ED discharge prescriptions declared in encounter protocols reach the CIF (Issue #2155)."""

from __future__ import annotations

import copy
from datetime import datetime

import pytest

from clinosim import determinism
from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.locale.loader import load_demographics
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.emergency import _simulate_ed_visit

pytestmark = pytest.mark.unit

_T = datetime(2024, 6, 1, 14, 0)


def _visit(condition: dict, *, sex: str = "M", age: int = 40, country: str = "US", seed: int = 3):
    rng = determinism.default_rng(seed)
    roster = generate_roster("medium", country, rng)
    person = PersonRecord(
        person_id="T-1", household_id="H-1", age=age, sex=sex, date_of_birth=datetime(2024 - age, 1, 1).date()
    )
    patient = activate_patient(person, rng, load_demographics(country))
    return _simulate_ed_visit(patient, condition, _T, roster, rng, country=country, force_severity="mild")


def _all_certain(name: str) -> dict:
    cond = copy.deepcopy(load_encounter_condition(name))
    for rx in cond["discharge_prescriptions"]:
        rx["probability"] = 1.0
    return cond


def _drugs(record) -> list[str]:
    rx = record.discharge_prescription
    return [i["drug_name"] for i in rx.items] if rx else []


def test_treat_and_release_visit_carries_protocol_prescriptions(monkeypatch: pytest.MonkeyPatch) -> None:
    import clinosim.modules.encounter.protocol as protocol_mod

    cond = _all_certain("renal_colic")
    monkeypatch.setattr(protocol_mod, "load_encounter_condition", lambda _cid: cond)
    record = _visit(cond)
    assert record.encounters[0].discharge_disposition == DischargeDisposition.HOME
    assert _drugs(record) == ["Tamsulosin", "Ibuprofen", "Oxycodone"]
    item = record.discharge_prescription.items[0]
    assert (item["dose"], item["route"], item["frequency"], item["duration_days"]) == ("0.4mg", "PO", "daily", 14)
    assert record.discharge_prescription.prescriber_id == record.encounters[0].attending_physician_id


def test_tamsulosin_for_ureteral_stone_is_not_blocked_by_the_bph_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Medical expulsive therapy is indicated in adults of either sex (AUA 2016).
    import clinosim.modules.encounter.protocol as protocol_mod

    cond = _all_certain("renal_colic")
    monkeypatch.setattr(protocol_mod, "load_encounter_condition", lambda _cid: cond)
    assert "Tamsulosin" in _drugs(_visit(cond, sex="F", age=35))


def test_prescription_draw_leaves_the_rest_of_the_visit_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    import clinosim.modules.encounter.protocol as protocol_mod

    with_rx = load_encounter_condition("renal_colic")
    without = copy.deepcopy(with_rx)
    without["discharge_prescriptions"] = []
    monkeypatch.setattr(protocol_mod, "load_encounter_condition", lambda _cid: with_rx)
    a = _visit(with_rx)
    monkeypatch.setattr(protocol_mod, "load_encounter_condition", lambda _cid: without)
    b = _visit(without)
    assert b.discharge_prescription is None
    assert [o.display_name for o in a.orders] == [o.display_name for o in b.orders]
    assert [(v.timestamp, v.heart_rate) for v in a.vital_signs] == [(v.timestamp, v.heart_rate) for v in b.vital_signs]


def test_locale_exclusion_drops_drugs_not_marketed_in_japan(monkeypatch: pytest.MonkeyPatch) -> None:
    import clinosim.modules.encounter.protocol as protocol_mod

    cond = _all_certain("renal_colic")
    monkeypatch.setattr(protocol_mod, "load_encounter_condition", lambda _cid: cond)
    assert "Oxycodone" not in _drugs(_visit(cond, country="JP"))


def _protocol_drugs() -> list[tuple[str, str, str]]:
    import glob

    import yaml

    out = set()
    for f in glob.glob("clinosim/modules/encounter/reference_data/*.yaml"):
        for rx in (yaml.safe_load(open(f, encoding="utf-8")) or {}).get("discharge_prescriptions") or []:
            for country in ("US", "JP"):
                if country in (rx.get("locale_exclude") or []):
                    continue
                name = (rx.get("locale_name") or {}).get(country.lower()) or rx["drug"]
                out.add((country, name, str(rx.get("route") or "")))
    return sorted(out)


@pytest.mark.parametrize(("country", "drug", "route"), _protocol_drugs())
def test_every_protocol_prescription_is_coded(country: str, drug: str, route: str) -> None:
    from clinosim.simulator.emergency import _DOSE_IN_NAME

    item_name = " ".join(_DOSE_IN_NAME.sub("", drug).split())
    for name in (drug, item_name):
        concept, _ = _resolve_medication_concept(name, order_code="", country=country, route=route)
        assert concept["coding"][0]["code"] != "NOCODED", f"{country}: {name}"


@pytest.mark.parametrize(("encounter_type", "rp"), [("emergency", "2"), ("inpatient", "2"), ("outpatient", "1")])
def test_discharge_prescription_rp_group_does_not_collide_with_visit_orders(encounter_type: str, rp: str) -> None:
    # ED treatment orders use Rp group 1, so the take-home prescription of
    # an ED visit is a separate Rp group (as on inpatient discharge).
    from clinosim.modules.output.fhir_r4.medications.medications import _build_discharge_medication_request

    item = {"drug_name": "Ibuprofen 600mg", "dose": "600mg", "route": "PO", "frequency": "tid PRN", "duration_days": 7}
    mr = _build_discharge_medication_request(item, "P-1", "JP", "ENC-1", encounter_type, 1, "2024-06-01T16:00:00")
    rp_ids = [i["value"] for i in mr["identifier"] if i["system"].endswith("Medication-RPGroupNumber")]
    assert rp_ids == [rp]


@pytest.mark.parametrize(("name", "at_departure"), [("renal_colic", True), ("orthopedic_injection", False)])
def test_issue_date_follows_the_visit_kind(monkeypatch: pytest.MonkeyPatch, name: str, at_departure: bool) -> None:
    # An ED take-home script is written when the patient leaves; a clinic
    # visit's prescription is dated at the visit start, as the outpatient
    # renewal prescription is.
    import clinosim.modules.encounter.protocol as protocol_mod

    cond = _all_certain(name)
    monkeypatch.setattr(protocol_mod, "load_encounter_condition", lambda _cid: cond)
    record = _visit(cond)
    enc = record.encounters[0]
    expected = enc.discharge_datetime if at_departure else enc.admission_datetime
    assert record.discharge_prescription.issue_date == expected
