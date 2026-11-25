"""Issue #3807: a questionnaire total score is coded by its instrument and
attributed to the clinician, not to a laboratory analyzer path.

PHQ-9 / GAD-7 / C-SSRS / EPDS Observations carry their LOINC instrument code
only (no JP-CLINS laboratory codings, no laboratory profile) and their
performer is the encounter's clinician, never the laboratory technician.
Laboratory results are unchanged.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.labs.observations import _bb_labs, _build_lab_observation
from clinosim.modules.output.fhir_r4.lib.context import BundleContext

pytestmark = pytest.mark.unit

SCORES = ["PHQ-9", "GAD-7", "C-SSRS", "EPDS"]
LOINC = "http://loinc.org"


def _obs(name: str, country: str, **kw) -> dict:
    order = {"display_name": name, "ordered_datetime": "2026-05-12T10:00:00", "ordered_by": "DR-1"}
    result = {
        "lab_name": name,
        "value": 11.0 if name in SCORES else 13.5,
        "unit": "",
        "result_datetime": "2026-05-12T10:30:00",
        "performed_by": "LT-1",
    }
    r = _build_lab_observation(
        order, result, patient_id="POP-000002", index=1, country=country, patient_sex="F", encounter_id="ENC-001", **kw
    )
    assert r is not None
    return r


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("name", SCORES)
def test_score_is_coded_with_loinc_only(name: str, country: str) -> None:
    r = _obs(name, country)
    assert [c["system"] for c in r["code"]["coding"]] == [LOINC]
    assert r["code"]["text"]
    assert "profile" not in r.get("meta", {}) or not any("LabResult" in p for p in r["meta"]["profile"])


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("name", SCORES)
def test_score_performer_is_the_clinician_not_the_lab_technician(name: str, country: str) -> None:
    r = _obs(name, country)
    assert r["performer"] == [{"reference": "Practitioner/DR-1"}]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_score_without_orderer_uses_the_encounter_clinician(country: str) -> None:
    order = {"display_name": "EPDS", "ordered_datetime": "2026-05-12T10:00:00"}
    result = {
        "lab_name": "EPDS",
        "value": 9.0,
        "unit": "",
        "result_datetime": "2026-05-12T11:00:00",
        "performed_by": "LT-1",
    }
    r = _build_lab_observation(order, result, "P", 1, country, "F", "ENC-001", encounter_clinician="ATT-7")
    assert r is not None
    assert r["performer"] == [{"reference": "Practitioner/ATT-7"}]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_score_with_no_clinician_has_no_performer(country: str) -> None:
    order = {"display_name": "EPDS", "ordered_datetime": "2026-05-12T10:00:00"}
    result = {
        "lab_name": "EPDS",
        "value": 9.0,
        "unit": "",
        "result_datetime": "2026-05-12T11:00:00",
        "performed_by": "LT-1",
    }
    r = _build_lab_observation(order, result, "P", 1, country, "F", "ENC-001")
    assert r is not None
    assert "performer" not in r


def test_jp_laboratory_result_keeps_the_technician() -> None:
    r = _obs("Hb", "JP")
    assert r["performer"] == [{"reference": "Practitioner/LT-1"}]


def test_us_laboratory_result_keeps_the_technician() -> None:
    assert _obs("Hb", "US")["performer"] == [{"reference": "Practitioner/LT-1"}]


def test_bundle_labs_pass_the_encounter_attending() -> None:
    record = {
        "encounters": [{"encounter_id": "ENC-001", "attending_physician_id": "ATT-7"}],
        "orders": [
            {
                "order_type": "lab",
                "display_name": "EPDS",
                "order_id": "ORD-1",
                "ordered_datetime": "2026-05-12T10:00:00",
                "result": {
                    "lab_name": "EPDS",
                    "value": 9.0,
                    "unit": "",
                    "result_datetime": "2026-05-12T11:00:00",
                    "performed_by": "LT-1",
                },
            }
        ],
    }
    ctx = BundleContext(
        record=record,
        country="JP",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="P",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="ENC-001",
        patient_sex="F",
    )
    (obs,) = _bb_labs(ctx)
    assert obs["performer"] == [{"reference": "Practitioner/ATT-7"}]
