"""An ED tetanus toxoid dose is an Immunization too (Issue #3685)."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.codes import lookup as display_for
from clinosim.modules.immunization.enricher import drop_wound_covered_doses, ed_vaccine_doses
from clinosim.types.encounter import ImmunizationRecord

pytestmark = pytest.mark.unit


def _record(mars: list, orders: list) -> SimpleNamespace:
    return SimpleNamespace(medication_administrations=mars, orders=orders)


def _mar(order_id: str, when: datetime, status: str = "given", drug_id: str = "tetanus_toxoid") -> SimpleNamespace:
    return SimpleNamespace(
        order_id=order_id, drug_id=drug_id, status=status, actual_datetime=when, administered_by="N-1"
    )


def _order(order_id: str, enc: str) -> SimpleNamespace:
    return SimpleNamespace(order_id=order_id, encounter_id=enc)


def test_given_tetanus_toxoid_mar_becomes_an_immunization() -> None:
    rec = _record([_mar("O1", datetime(2026, 9, 8, 22, 42))], [_order("O1", "ENC-ED-1")])
    [imm] = ed_vaccine_doses([rec])
    assert imm.vaccine_cvx == "35"
    assert imm.occurrence_date == date(2026, 9, 8)
    assert imm.encounter_id == "ENC-ED-1"
    assert imm.primary_source is True
    assert imm.lot_number
    assert imm.administered_by == "N-1"
    assert imm.status == "completed"


def test_other_drugs_and_undelivered_doses_give_none() -> None:
    rec = _record(
        [
            _mar("O1", datetime(2026, 9, 8, 22, 42), status="held"),
            _mar("O2", datetime(2026, 9, 8, 22, 42), drug_id="ibuprofen"),
            _mar("O3", None),  # type: ignore[arg-type]
        ],
        [_order("O1", "E"), _order("O2", "E"), _order("O3", "E")],
    )
    assert ed_vaccine_doses([rec]) == []


def test_same_dose_in_several_records_is_emitted_once() -> None:
    mar, order = _mar("O1", datetime(2026, 9, 8, 22, 42)), _order("O1", "ENC-ED-1")
    assert len(ed_vaccine_doses([_record([mar], [order]), _record([mar], [order])])) == 1


def test_cvx_35_is_registered_in_both_languages() -> None:
    assert "tetanus toxoid" in display_for("cvx", "35", "en").lower()
    assert display_for("cvx", "35", "ja")


def test_scheduled_tdap_inside_the_interval_is_dropped_outside_stays() -> None:
    ed = ImmunizationRecord(vaccine_cvx="35", occurrence_date=date(2026, 9, 8), encounter_id="E")
    soon = ImmunizationRecord(vaccine_cvx="115", occurrence_date=date(2028, 3, 1))
    late = ImmunizationRecord(vaccine_cvx="115", occurrence_date=date(2031, 9, 9))
    before = ImmunizationRecord(vaccine_cvx="115", occurrence_date=date(2026, 8, 1))
    flu = ImmunizationRecord(vaccine_cvx="150", occurrence_date=date(2026, 10, 1))
    kept = drop_wound_covered_doses([soon, late, before, flu], [ed])
    assert kept == [late, before, flu]
