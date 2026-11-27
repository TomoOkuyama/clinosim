"""The allergy-interaction caution note follows the cohort country (Issue #3929).

The inpatient callers pass the disease-YAML slot (``japan``, not ``jp``) as
``country``; the language map is keyed by country code, so the note and its
author were written in English for a JP cohort.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.simulator.medication_pipeline import apply_drug_safety_gate_to_orders
from clinosim.types.allergy import Allergy
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 3, 1, 10, 0)
_SULFONAMIDE = "387406002"


def _caution_note(country: str) -> dict:
    patient = PatientProfile(patient_id="PT-1", age=40, sex="F")
    patient.allergies = [Allergy(allergy_id="1", allergen_code=_SULFONAMIDE, category="medication")]
    order = Order(
        order_id="ORD-1",
        encounter_id="ENC-1",
        patient_id="PT-1",
        order_type=OrderType.MEDICATION,
        order_code="",
        display_name="Furosemide 40mg",
        urgency="routine",
        clinical_intent="test",
        ordered_datetime=_WHEN,
        ordered_by="DR-1",
        status=OrderStatus.PLACED,
    )
    (out,) = apply_drug_safety_gate_to_orders(
        [order], patient=patient, encounter_id="ENC-1", ordered_datetime=_WHEN, country=country
    )
    (note,) = out.notes
    return note


@pytest.mark.parametrize("country", ["japan", "jp", "JP"])
def test_jp_slot_writes_the_caution_and_author_in_japanese(country: str) -> None:
    note = _caution_note(country)
    assert note["text"].startswith("併用注意: ")
    assert "Drug interaction" not in note["text"]
    assert note["authorReference"]["display"] == "処方チェックシステム"


@pytest.mark.parametrize("country", ["us", "US"])
def test_us_slot_keeps_the_english_caution(country: str) -> None:
    note = _caution_note(country)
    assert note["text"].startswith("Drug interaction (caution): ")
    assert note["authorReference"]["display"] == "Prescription safety check"
