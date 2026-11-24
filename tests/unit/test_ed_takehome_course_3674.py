"""Issue #3674: an ED take-home prescription with a short supply is an acute course."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.medications.medications import _build_discharge_medication_request

pytestmark = pytest.mark.unit


def _course(encounter_type: str, duration, country: str = "US") -> str:
    r = _build_discharge_medication_request(
        {"drug_name": "Ibuprofen", "dose": "600 mg", "route": "PO", "duration_days": duration},
        patient_id="P1",
        country=country,
        encounter_id="ENC1",
        encounter_type=encounter_type,
        seq=1,
        authored_on="2026-08-01T09:00:00Z",
    )
    return r["courseOfTherapyType"]["coding"][0]["code"]


def _category(encounter_type: str) -> str:
    r = _build_discharge_medication_request(
        {"drug_name": "Ibuprofen", "dose": "600 mg", "route": "PO", "duration_days": 7},
        patient_id="P1",
        country="US",
        encounter_id="ENC1",
        encounter_type=encounter_type,
        seq=1,
        authored_on="2026-08-01T09:00:00Z",
    )
    return r["category"][0]["coding"][0]["code"]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_ed_short_supply_is_acute(country: str) -> None:
    assert _course("emergency", 7, country) == "acute"


def test_ed_long_or_open_ended_supply_is_continuous() -> None:
    assert _course("emergency", 30) == "continuous"
    assert _course("emergency", None) == "continuous"


def test_ambulatory_renewal_and_inpatient_discharge_unchanged() -> None:
    assert _course("outpatient", 7) == "continuous"
    assert _course("inpatient", 7) == "acute"
    assert _course("inpatient", 30) == "continuous"


def test_ed_category_stays_outpatient() -> None:
    assert _category("emergency") == "outpatient"
