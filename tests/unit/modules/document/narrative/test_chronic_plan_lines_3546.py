"""Issue #3546: a chronic visit's plan and assessment lines state a therapy
change only when the record holds one.

Before the fix the AF line "rate-control therapy to be stepped up" was printed
whenever the heart rate was above target in a patient with atrial fibrillation,
with no rate-control drug on the medication list, and the statin line
"statin intensification ... indicated" for atorvastatin 80 mg beside
"Prescription unchanged".
"""

from __future__ import annotations

import pytest

from tests.unit.modules.document.narrative.test_visit_reason_soap_3249 import _record, _soap

pytestmark = pytest.mark.unit

_METOPROLOL = {"drug_name": "Metoprolol", "drug_id": "metoprolol", "dose": "50mg", "status": "active"}
_AMLODIPINE = {"drug_name": "Amlodipine", "drug_id": "amlodipine", "dose": "5mg", "status": "active"}


def _af(country: str, meds: list[dict]) -> dict[str, str]:
    record = _record(
        country=country,
        visit_type="chronic_followup",
        condition="I48",
        dx="I48",
        chronic=["I48", "I10"],
        vitals={"heart_rate": 110, "systolic_bp": 128, "diastolic_bp": 76},
        medications=meds,
    )
    return _soap(record, country)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_af_without_a_rate_control_drug_does_not_claim_a_step_up(country: str) -> None:
    soap = _af(country, [_AMLODIPINE])
    assert "stepped up" not in soap["P"] and "増量" not in soap["P"]
    assert (
        "starting a rate-control drug to be considered" if country == "US" else "レートコントロール薬の開始を検討"
    ) in soap["P"]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_af_on_a_rate_control_drug_with_an_unchanged_prescription_continues_it(country: str) -> None:
    soap = _af(country, [_METOPROLOL, _AMLODIPINE])
    assert "stepped up" not in soap["P"] and "増量" not in soap["P"]
    assert (
        "current rate-control regimen continued" if country == "US" else "現行のレートコントロール薬を継続"
    ) in soap["P"]


def _statin(country: str, dose: str, extra: list[dict] | None = None) -> dict[str, str]:
    record = _record(
        country=country,
        visit_type="chronic_followup",
        condition="E78",
        dx="E78",
        chronic=["E78", "I25"],
        labs=[
            {"lab_name": "LDL", "value": 74.0, "unit": "mg/dL", "flag": "H", "result_datetime": "2026-03-02T10:30:00"}
        ],
        medications=[
            {"drug_name": "Atorvastatin", "drug_id": "atorvastatin", "dose": dose, "status": "active"},
            *(extra or []),
        ],
    )
    return _soap(record, country)


def test_maximal_statin_with_ldl_above_threshold_gets_the_add_on_wording_only() -> None:
    soap = _statin("US", "80mg")
    assert "on maximal statin therapy; non-statin add-on recommended for review" in soap["A"]
    assert "intensification" not in soap["A"] and "indicated" not in soap["A"]


def test_statin_below_maximal_with_unchanged_prescription_is_a_recommendation() -> None:
    soap = _statin("US", "10mg")
    assert "statin intensification or a non-statin add-on recommended for review" in soap["A"]
    assert "indicated" not in soap["A"]


def test_maximal_statin_plus_add_on_says_therapy_is_to_be_reviewed() -> None:
    soap = _statin(
        "US", "80mg", [{"drug_name": "Ezetimibe", "drug_id": "ezetimibe", "dose": "10mg", "status": "active"}]
    )
    assert "plus a non-statin add-on; therapy to be reviewed" in soap["A"]
