"""Issue #3011: JP reports CRP in mg/dL (JCCLS 共用基準範囲 0.00-0.14 mg/dL).

The simulator keeps CRP in mg/L internally (CIF value, flags, thresholds);
the reporting unit of a country (``reference_range_lab.yaml``
``reporting_units``) converts it on output: the FHIR Observation value and
reference range, and the values narratives quote.
"""

from __future__ import annotations

import pytest

from clinosim.modules.observation.engine import determine_flag, reported_lab_results, reported_lab_value

pytestmark = pytest.mark.unit

_ORDER = {"display_name": "CRP", "encounter_id": "ENC-1", "ordered_datetime": "2026-03-02T07:00:00"}


def _result(value: float) -> dict:
    return {"lab_name": "CRP", "value": value, "unit": "mg/L", "flag": "H", "result_datetime": "2026-03-02T08:00:00"}


def test_a_jp_crp_of_50_mg_l_is_emitted_as_5_mg_dl() -> None:
    from clinosim.modules.output.fhir_r4.labs.observations import _build_lab_observation

    obs = _build_lab_observation(_ORDER, _result(50.0), "P1", 0, "JP", patient_sex="F", encounter_id="ENC-1")
    assert obs is not None
    assert obs["valueQuantity"]["value"] == 5.0
    assert obs["valueQuantity"]["unit"] == "mg/dL"
    assert obs["valueQuantity"]["code"] == "mg/dL"
    rr = obs["referenceRange"][0]
    assert (rr["low"]["value"], rr["high"]["value"], rr["high"]["unit"]) == (0, 0.14, "mg/dL")
    assert obs["interpretation"][0]["coding"][0]["code"] == "H"


def test_us_crp_stays_mg_l() -> None:
    from clinosim.modules.output.fhir_r4.labs.observations import _build_lab_observation

    obs = _build_lab_observation(_ORDER, _result(50.0), "P1", 0, "US", patient_sex="F", encounter_id="ENC-1")
    assert obs is not None
    assert (obs["valueQuantity"]["value"], obs["valueQuantity"]["unit"]) == (50.0, "mg/L")


def test_reported_value_and_unchanged_flags() -> None:
    assert reported_lab_value("CRP", 123.4, "mg/L", "JP") == (12.34, "mg/dL")
    assert reported_lab_value("CRP", 123.4, "mg/L", "US") == (123.4, "mg/L")
    assert reported_lab_value("WBC", 9800, "/uL", "JP") == (9800, "/uL")
    # The CIF flag is unchanged: JP judges 1.5 mg/L (0.15 mg/dL) high, 1.3 mg/L normal.
    assert determine_flag("CRP", 1.5, "F", "JP") == "H"
    assert determine_flag("CRP", 1.3, "F", "JP") is None


def test_narrative_lab_results_are_in_the_reporting_unit() -> None:
    labs = [
        {"lab_name": "CRP", "value": 87.0, "unit": "mg/L", "flag": "H"},
        {"lab_name": "WBC", "value": 12000, "unit": "/uL"},
    ]
    out = reported_lab_results(labs, "JP")
    assert out[0]["value"] == 8.7
    assert out[0]["unit"] == "mg/dL"
    assert out[1] == labs[1]
    assert labs[0]["value"] == 87.0  # the CIF entry is not modified
