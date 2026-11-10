"""Health-checkup body measurements are vital-sign eCheckup Observations
(Issue #3167).

The checkup's BMI and blood pressure are measured on the body, not on a
specimen. Like the JP-eCheckup 1.7.0 sample report, each is one
``JP_Observation_eCheckupGeneral`` Observation with a single category and
the MHLW health-checkup item code alone: no laboratory category, lab
profile, specimen or analyzer method, and no LOINC vital-sign code (the
HL7 validator checks an Observation coded LOINC 39156-5 / 8480-6 against
the HL7 ``bmi`` / ``bp`` profiles, which a single eCheckup measurement
cannot meet). The checkup encounter charts one BMI: the checkup result,
computed from the height and weight charted on that encounter.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.output.fhir_r4.labs.observations import _build_lab_observation

pytestmark = pytest.mark.unit

_ITEM_SYSTEM = "urn:oid:1.2.392.200119.6.1005"
_PROFILE = "http://jpfhir.jp/fhir/eCheckup/StructureDefinition/JP_Observation_eCheckupGeneral"
_JP_CATEGORY = "http://jpfhir.jp/fhir/core/CodeSystem/JP_SimpleObservationCategory_CS"
_LOINC = "http://loinc.org"


def _obs(lab_name: str, value: float, unit: str, intent: str = "health_checkup") -> dict:
    order = {
        "display_name": lab_name,
        "order_code": lab_name,
        "clinical_intent": intent,
        "encounter_id": "CHK-1",
        "ordered_datetime": "2026-04-01T09:30:00",
    }
    result = {"lab_name": lab_name, "value": value, "unit": unit, "result_datetime": "2026-04-01T10:00:00"}
    obs = _build_lab_observation(order, result, "P1", 0, "JP", encounter_id="CHK-1")
    assert obs is not None
    return obs


def _finished(obs: dict) -> tuple[dict, dict | None]:
    from clinosim.modules.output.fhir_r4.builder import _finalize_resource

    specimen = _finalize_resource(obs, "JP", {})
    return obs, specimen


@pytest.mark.parametrize(
    ("lab_name", "unit", "item"),
    [
        ("BMI", "kg/m2", "9N011000000000001"),
        ("SBP", "mm[Hg]", "9A751000000000001"),
        ("DBP", "mm[Hg]", "9A761000000000001"),
    ],
)
def test_a_checkup_body_measurement_is_a_vital_sign_echeckup_observation(lab_name: str, unit: str, item: str) -> None:
    obs, specimen = _finished(_obs(lab_name, 120.0, unit))
    assert [(c["system"], c["code"]) for c in obs["code"]["coding"]] == [(_ITEM_SYSTEM, item)]
    assert obs["code"]["text"]
    assert obs["category"] == [{"coding": [{"system": _JP_CATEGORY, "code": "vital-signs"}], "text": "バイタルサイン"}]
    # The report profile and JP Core's JP_Observation_Common (its base); no lab profile.
    assert set(obs["meta"]["profile"]) == {
        _PROFILE,
        "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common",
    }
    assert "method" not in obs
    assert "specimen" not in obs and specimen is None
    assert len(obs["referenceRange"]) == 1


@pytest.mark.parametrize(("lab_name", "unit"), [("HbA1c", "%"), ("LDL", "mg/dL")])
def test_a_checkup_specimen_test_stays_a_laboratory_result(lab_name: str, unit: str) -> None:
    obs, specimen = _finished(_obs(lab_name, 6.0, unit))
    assert any(c["system"] == _LOINC for c in obs["code"]["coding"])
    assert any(c["system"] == _ITEM_SYSTEM for c in obs["code"]["coding"])
    assert [c["coding"][0]["code"] for c in obs["category"]] == ["laboratory"]
    assert _PROFILE in obs["meta"]["profile"]
    assert "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS" in obs["meta"]["profile"]
    assert obs["specimen"] and specimen is not None


def test_a_body_measurement_outside_the_checkup_is_unchanged() -> None:
    obs = _obs("SBP", 120.0, "mm[Hg]", intent="")
    assert obs["code"]["coding"][0]["system"] != _ITEM_SYSTEM
    assert _PROFILE not in obs["meta"]["profile"]


def _anthro_codes(record: dict) -> list[str]:
    from clinosim.modules.output.fhir_r4.labs.anthropometrics import _bb_anthropometrics

    ctx = SimpleNamespace(
        record=record,
        patient_data={
            "patient_id": "P1",
            "sex": "M",
            "date_of_birth": "1970-01-01",
            "height_cm": 170.0,
            "weight_kg": 70.0,
        },
        country="JP",
    )
    return [o["code"]["coding"][0]["code"] for o in _bb_anthropometrics(ctx)]  # type: ignore[arg-type]


def test_the_checkup_encounter_charts_one_bmi() -> None:
    enc = {"encounter_id": "CHK-1", "admission_datetime": "2026-04-01T09:00:00"}
    bmi_order = {"encounter_id": "CHK-1", "clinical_intent": "health_checkup", "result": {"lab_name": "BMI"}}
    assert "39156-5" not in _anthro_codes({"encounters": [enc], "orders": [bmi_order]})
    assert {"8302-2", "29463-7"} <= set(_anthro_codes({"encounters": [enc], "orders": [bmi_order]}))
    assert "39156-5" in _anthro_codes({"encounters": [enc], "orders": []})


def test_the_checkup_bmi_is_computed_from_the_charted_height_and_weight() -> None:
    from clinosim.modules.health_checkup.engine import _build_checkup_encounter, _build_checkup_lab_results
    from clinosim.modules.population.encounter_anthropometry import encounter_anthropometrics

    patient = SimpleNamespace(
        patient_id="P1",
        sex="M",
        date_of_birth=date(1970, 1, 1),
        age=56,
        height_cm=170.0,
        weight_kg=78.0,
        bmi=27.0,
        baseline_vitals=None,
        chronic_conditions=[],
        lipid_state=None,
    )
    enc = _build_checkup_encounter("P1", date(2026, 4, 1), 1)
    results = _build_checkup_lab_results("P1", patient, enc, np.random.default_rng(7), "JP")
    charted = encounter_anthropometrics(patient, enc.encounter_id, enc.admission_datetime, "JP")
    assert {r.lab_name: r.value for r in results}["BMI"] == round(charted["bmi"], 1)
    assert isinstance(enc.admission_datetime, datetime)


def test_the_checkup_bmi_leaves_the_other_results_unchanged() -> None:
    from clinosim.modules.health_checkup.engine import _derive_checkup_values

    patient = SimpleNamespace(age=56, chronic_conditions=[], bmi=27.0, baseline_vitals=None, sex="M", patient_id="P1")
    a = _derive_checkup_values(patient, np.random.default_rng(7), charted_bmi=22.0)
    b = _derive_checkup_values(patient, np.random.default_rng(7), charted_bmi=31.0)
    assert (a["BMI"], b["BMI"]) == (22.0, 31.0)
    # The values before the change (seed 7): the BMI draw stays in the
    # stream, so the later results keep their values.
    before = {
        "SBP": 121.49372768754235,
        "DBP": 74.04051750623223,
        "HbA1c": 5.041128979349127,
        "LDL": 106.45329214828277,
    }
    for values in (a, b):
        assert {k: v for k, v in values.items() if k != "BMI"} == pytest.approx(before, abs=1e-9)
