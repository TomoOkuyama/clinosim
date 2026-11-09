"""Issue #3012: Japanese ibuprofen stays within the ブルフェン label — 200 mg
three times daily, 600 mg/day for adults; children by weight from 5 years.
US regimens are unchanged."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest

from clinosim.codes.drugs import drug_ref
from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.modules.encounter.protocol import load_all_encounter_conditions, load_encounter_condition
from clinosim.modules.order.label_dose import doses_per_day, within_label
from clinosim.modules.order.pediatric_dose import pediatric_order_name
from clinosim.simulator.emergency import _ed_discharge_prescription
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_MG = re.compile(r"(\d+(?:\.\d+)?)\s*mg", re.IGNORECASE)


def _ibuprofen_items(country: str, n: int = 40) -> list[dict]:
    items: list[dict] = []
    protocol = load_encounter_condition("low_back_pain")
    for i in range(n):
        patient = PatientProfile(patient_id=f"PT-{i}", age=45, sex="M")
        t0 = datetime(2025, 3, 1, 10, 0)
        enc = Encounter(encounter_id=f"ENC-{i}", patient_id=patient.patient_id)
        enc.encounter_type = EncounterType.EMERGENCY
        enc.admission_datetime = t0
        enc.discharge_datetime = t0 + timedelta(hours=3)
        enc.discharge_disposition = DischargeDisposition.HOME
        rx = _ed_discharge_prescription(protocol, patient, enc, ["M54.5"], country, "low_back_pain")
        items += [it for it in (rx.items if rx else []) if drug_ref(str(it["drug_name"])) == "ibuprofen"]
    return items


def test_the_jp_low_back_pain_prescription_is_200mg_tid() -> None:
    items = _ibuprofen_items("JP")
    assert items
    assert {(it["dose"], it["frequency"]) for it in items} == {("200mg", "tid")}


def test_the_us_low_back_pain_prescription_is_unchanged() -> None:
    items = _ibuprofen_items("US")
    assert items
    assert {(it["dose"], it["frequency"]) for it in items} == {("600mg", "tid")}


@pytest.mark.parametrize(
    ("regimen", "expected"),
    [
        (("Ibuprofen 600mg", "tid"), ("Ibuprofen 200mg", "tid")),
        (("Ibuprofen 400mg", "Q6H PRN"), ("Ibuprofen 200mg", "tid PRN")),
        (("Ibuprofen 400mg", ""), ("Ibuprofen 200mg", "")),
        (("Ibuprofen 100mg", "tid"), ("Ibuprofen 100mg", "tid")),
        (("Acetaminophen 500mg", "q6h PRN"), ("Acetaminophen 500mg", "q6h PRN")),
    ],
)
def test_within_label_keeps_jp_ibuprofen_at_most_600mg_a_day(regimen: tuple, expected: tuple) -> None:
    assert within_label(*regimen, "JP") == expected


def test_within_label_leaves_us_regimens_alone() -> None:
    assert within_label("Ibuprofen 600mg", "q6h PRN", "US") == ("Ibuprofen 600mg", "q6h PRN")


def _jp_regimens() -> list[tuple[str, str, str]]:
    """Every ibuprofen ED treatment and take-home prescription of the
    encounter YAMLs, as written for JP (locale_name / locale_frequency)."""
    out = []
    for cid, cond in load_all_encounter_conditions().items():
        for tx in cond.get("treatment") or []:
            name = str((tx.get("locale_name") or {}).get("jp") or tx.get("name", ""))
            if drug_ref(name) == "ibuprofen" and "JP" not in (tx.get("locale_exclude") or []):
                out.append((cid, name, ""))
        for rx in cond.get("discharge_prescriptions") or []:
            name = str((rx.get("locale_name") or {}).get("jp") or rx.get("drug", ""))
            freq = str((rx.get("locale_frequency") or {}).get("jp") or rx.get("frequency", ""))
            if drug_ref(name) == "ibuprofen" and "JP" not in (rx.get("locale_exclude") or []):
                out.append((cid, name, freq))
    return out


def test_every_jp_encounter_ibuprofen_regimen_is_within_the_label() -> None:
    """The YAMLs themselves carry the JP regimen (the runtime guard is a
    backstop): 200 mg a dose and at most 600 mg a day."""
    regimens = _jp_regimens()
    assert len(regimens) >= 15
    for cid, name, freq in regimens:
        mg = float(_MG.search(name).group(1))  # type: ignore[union-attr]
        assert mg <= 200, (cid, name)
        assert mg * doses_per_day(freq) <= 600, (cid, name, freq)
        assert within_label(name, freq, "JP") == (name, freq), (cid, name, freq)


def test_jp_children_get_ibuprofen_by_weight_within_the_label() -> None:
    # 6 years, 20 kg: 4 mg/kg = 80 mg a dose (240 mg/day, label 200-300 mg/day at 5-7 y).
    assert pediatric_order_name("Ibuprofen 200mg", 72, 20.0, "JP") == "Ibuprofen 80mg"
    # 14 years, 60 kg: capped at the adult 200 mg.
    assert pediatric_order_name("Ibuprofen 200mg", 168, 60.0, "JP") == "Ibuprofen 200mg"
    # Below 5 years the JP label gives no dose.
    assert pediatric_order_name("Ibuprofen 200mg", 36, 14.0, "JP") is None
    # US keeps 10 mg/kg from 6 months.
    assert pediatric_order_name("Ibuprofen 400mg", 36, 14.0, "US") == "Ibuprofen 140mg"
