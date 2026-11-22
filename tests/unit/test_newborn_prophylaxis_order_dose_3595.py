"""Issue #3595: newborn prophylaxis orders carry the protocol dose."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.newborn.enricher import _add_orders_for_administrations
from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_request
from clinosim.types.encounter import MedicationAdministration

pytestmark = pytest.mark.unit


def _order_for(drug: str, dose: str, route: str):
    enc = SimpleNamespace(
        encounter_id="ENC-B", admission_datetime=datetime(2025, 5, 1, 10), attending_physician_id="DR-OB-001"
    )
    rec = SimpleNamespace(patient=SimpleNamespace(patient_id="P1-BABY"), encounters=[enc], orders=[])
    mar = MedicationAdministration(
        order_id="ORD-ENC-B-X",
        drug_name=drug,
        dose=dose,
        scheduled_datetime=datetime(2025, 5, 1, 16),
        actual_datetime=datetime(2025, 5, 1, 16),
        route=route,
    )
    _add_orders_for_administrations(rec, [mar])
    return rec.orders[0]


def test_vitamin_k_order_has_dose() -> None:
    o = _order_for("Vitamin K1 (phytonadione) 1 mg IM", "1 mg", "IM")
    assert (o.dose_quantity, o.dose_unit) == (1.0, "mg")


def test_jp_menatetrenone_order_has_dose() -> None:
    o = _order_for("ケイツーシロップ (メナテトレノン 2 mg 経口)", "2 mg", "PO")
    assert (o.dose_quantity, o.dose_unit) == (2.0, "mg")


def test_ointment_order_keeps_dose_as_sig_text() -> None:
    o = _order_for("Erythromycin 0.5% ophthalmic ointment (Ilotycin)", "1 cm ribbon each eye", "OPH")
    assert o.dose_quantity is None and o.dose_text_en == "1 cm ribbon each eye"


def _mr(o) -> dict:
    d = {k: getattr(o, k) for k in ("order_id", "display_name", "route", "frequency", "frequency_per_day")}
    d.update(dose_quantity=o.dose_quantity, dose_unit=o.dose_unit, dose_text_en=o.dose_text_en)
    d["ordered_datetime"] = "2025-05-01T10:00:00"
    return d


def test_us_vitamin_k_request_has_dose_and_ingredient_and_product_codes() -> None:
    o = _order_for("Vitamin K1 (phytonadione) 1 mg IM", "1 mg", "IM")
    mr = _build_medication_request(_mr(o), "P1-BABY", "US")
    dq = mr["dosageInstruction"][0]["doseAndRate"][0]["doseQuantity"]
    assert dq["value"] == 1 and dq["code"] == "mg"
    codes = {c["code"] for c in mr["medicationCodeableConcept"]["coding"]}
    assert {"312424", "8308"} <= codes


def test_us_ointment_request_has_sig_text() -> None:
    o = _order_for("Erythromycin 0.5% ophthalmic ointment (Ilotycin)", "1 cm ribbon each eye", "OPH")
    mr = _build_medication_request(_mr(o), "P1-BABY", "US")
    assert "1 cm ribbon each eye" in mr["dosageInstruction"][0]["text"]
