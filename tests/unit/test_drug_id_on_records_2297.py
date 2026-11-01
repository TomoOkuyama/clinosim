"""Medication records carry the catalog drug_id (Issue #2297)."""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import drug_ref, has_drug
from clinosim.types.encounter import MedicationAdministration, Order, OrderType, PrescriptionRecord
from clinosim.types.patient import HomeMedication

pytestmark = pytest.mark.unit


def test_records_get_their_drug_id_when_created() -> None:
    assert HomeMedication(drug_name="Atorvastatin").drug_id == "atorvastatin"
    assert MedicationAdministration(drug_name="ワルファリン").drug_id == "warfarin"
    assert Order(order_type=OrderType.MEDICATION, display_name="Rivaroxaban 20mg").drug_id == "rivaroxaban"
    rx = PrescriptionRecord(items=[{"drug_name": "Amlodipine", "dose": "5mg"}])
    assert rx.items[0]["drug_id"] == "amlodipine"


def test_non_medication_orders_and_unknown_drugs_have_no_id() -> None:
    assert Order(order_type=OrderType.LAB, display_name="Warfarin level").drug_id == ""
    assert HomeMedication(drug_name="Unobtainium").drug_id == ""


def test_an_explicit_drug_id_is_kept() -> None:
    assert HomeMedication(drug_name="Coumadin", drug_id="warfarin").drug_id == "warfarin"


def test_drug_ref_and_has_drug() -> None:
    assert drug_ref("warfarin") == drug_ref("Coumadin") == drug_ref("ワルファリン") == "warfarin"
    meds = [HomeMedication(drug_name="Atorvastatin"), {"drug_name": "Apixaban 5mg"}]
    assert has_drug(meds, "atorvastatin")
    assert has_drug(meds, "statin")
    assert has_drug(meds, "anticoagulant.doac")
    assert not has_drug(meds, "warfarin")
