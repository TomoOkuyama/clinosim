"""Issue #3688: a vaccine given during an inpatient stay (the US hepatitis B
birth dose) is ordered at the admission like the other birth-stay
prophylaxis; the Immunization stays the only administration record."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.immunization.enricher import _order_stay_doses

pytestmark = pytest.mark.unit

_ENC = "ENC-POP-1-BABY-1"


def _rec(country: str = "US", enc_type: str = "inpatient") -> dict:
    return {
        "patient": SimpleNamespace(patient_id="POP-1-BABY", country=country, date_of_birth=date(2026, 2, 20)),
        "encounters": [
            {
                "encounter_id": _ENC,
                "encounter_type": enc_type,
                "admission_datetime": datetime(2026, 2, 20, 10, 0),
                "attending_physician_id": "DR-1",
            }
        ],
        "orders": [],
        "medication_administrations": [],
    }


def _imm(enc: str = _ENC, cvx: str = "08") -> dict:
    return {
        "vaccine_cvx": cvx,
        "occurrence_date": date(2026, 2, 20),
        "dose_number": 1,
        "encounter_id": enc,
        "status": "completed",
    }


def test_birth_dose_is_ordered_at_the_admission() -> None:
    rec = _rec()
    _order_stay_doses(rec, [_imm()], "US")
    (order,) = rec["orders"]
    assert order.order_id == f"ORD-{_ENC}-IMM-08-1"
    assert order.encounter_id == _ENC and order.ordered_by == "DR-1"
    assert order.ordered_datetime == datetime(2026, 2, 20, 10, 0)
    assert order.display_name == "Hepatitis B vaccine" and order.drug_id == "hepatitis_b_vaccine"
    assert order.route == "IM" and order.dose_quantity and order.dose_unit == "mL"


def test_no_medication_administration_is_added() -> None:
    rec = _rec()
    _order_stay_doses(rec, [_imm()], "US")
    assert rec["medication_administrations"] == []


def test_ordering_twice_adds_one_order() -> None:
    rec = _rec()
    _order_stay_doses(rec, [_imm()], "US")
    _order_stay_doses(rec, [_imm()], "US")
    assert len(rec["orders"]) == 1


def test_doses_given_outside_the_stay_are_not_ordered() -> None:
    rec = _rec()
    _order_stay_doses(rec, [_imm(enc="ENC-VAX-1"), _imm(enc="")], "US")
    assert rec["orders"] == []


def test_outpatient_record_gets_no_order() -> None:
    rec = _rec(enc_type="outpatient")
    _order_stay_doses(rec, [_imm()], "US")
    assert rec["orders"] == []
