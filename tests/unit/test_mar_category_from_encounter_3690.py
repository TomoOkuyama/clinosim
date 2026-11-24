"""Issue #3690: MedicationAdministration.category follows the Encounter class."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.medications.medications import (
    _build_medication_admin,
    align_ma_category_with_encounters,
)

pytestmark = pytest.mark.unit

_MAR = {
    "drug_name": "Lidocaine",
    "dose": "2 mL",
    "route": "SC",
    "order_id": "ORD-1",
    "status": "completed",
    "actual_datetime": "2026-03-01T09:00:00",
}


def _cat(enc_type: str | None, country: str = "US") -> str:
    kwargs = {} if enc_type is None else {"encounter_type": enc_type}
    r = _build_medication_admin(_MAR, "P1", 0, country, encounter_id="ENC1", **kwargs)
    return r["category"]["coding"][0]["code"]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_category_follows_the_encounter_class(country: str) -> None:
    assert _cat("emergency", country) == "outpatient"
    assert _cat("outpatient", country) == "outpatient"
    assert _cat("inpatient", country) == "inpatient"
    assert _cat(None, country) == "inpatient"


def test_bundle_pass_recategorises_by_final_encounter_class() -> None:
    def ma(ctx: str) -> dict:
        r = _build_medication_admin(_MAR, "P1", 0, "US", encounter_id="ENC1")
        r["context"] = {"reference": f"Encounter/{ctx}"}
        return {"resource": r}

    entries = [
        {"resource": {"resourceType": "Encounter", "id": "imp", "class": {"code": "IMP"}}},
        {"resource": {"resourceType": "Encounter", "id": "imp-ed", "class": {"code": "EMER"}}},
        {"resource": {"resourceType": "Encounter", "id": "amb", "class": {"code": "AMB"}}},
        ma("imp"),
        ma("imp-ed"),
        ma("amb"),
    ]
    align_ma_category_with_encounters(entries)
    codes = [e["resource"]["category"]["coding"][0]["code"] for e in entries[3:]]
    assert codes == ["inpatient", "outpatient", "outpatient"]
