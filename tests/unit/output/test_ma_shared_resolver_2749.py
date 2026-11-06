"""Issue #2749: a MedicationAdministration's drug is coded by the resolver its MedicationRequest uses."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.medications.medications import (
    _build_medication_admin,
    _resolve_medication_concept,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("name", ["Lactated Ringer's", "Ceftriaxone 1g", "Acetaminophen"])
def test_administration_is_coded_like_its_order(country: str, name: str) -> None:
    mar = {"drug_name": name, "route": "IV", "status": "given", "scheduled_datetime": "2025-03-01T09:00:00"}
    ma = _build_medication_admin(mar, "P1", 1, country=country, encounter_id="E1")
    concept, _ = _resolve_medication_concept(name, "", country, route="IV")
    ma_codes = [c["code"] for c in ma["medicationCodeableConcept"].get("coding", [])]
    mr_codes = [c["code"] for c in concept.get("coding", [])]
    assert mr_codes and ma_codes[-len(mr_codes) :] == mr_codes  # an SCD may precede the ingredient
