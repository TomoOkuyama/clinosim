"""JP inpatient Encounters record the DPC discharge outcome (Issue #3150).

JP-CLINS JP_Encounter_eCS binds ``hospitalization.dischargeDisposition``
(required, 1..1) to the jpfhir discharge-disposition value set — the DPC
様式1 退院時転帰 codes. The outcome is derived from the simulated course,
not from the destination; US output keeps the HL7 discharge-disposition
(destination) coding.
"""

from __future__ import annotations

import pytest

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules.encounter.discharge_outcome import discharge_outcome
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter

pytestmark = pytest.mark.unit

_JP_URI = "http://jpfhir.jp/fhir/Common/CodeSystem/discharge-disposition"


def _imp(**overrides: object) -> dict:
    base = {
        "encounter_id": "ENC-3150",
        "encounter_type": "inpatient",
        "status": "completed",
        "admission_datetime": "2026-01-15T10:00:00",
        "discharge_datetime": "2026-01-22T14:00:00",
        "chief_complaint": "Pneumonia",
        "admit_source": "emd",
        "discharge_disposition": "home",
        "clinical_course_archetype": "smooth_recovery",
        "admission_diagnosis_code": "J18.9",
    }
    base.update(overrides)
    return base


def _dispo(enc: dict, country: str, deceased: bool = False) -> dict:
    res = _build_encounter(enc, patient_id="POP-1", country=country, deceased=deceased)
    return res["hospitalization"]["dischargeDisposition"]


@pytest.mark.parametrize(
    ("overrides", "deceased", "outcome", "code"),
    [
        ({}, False, "improved", "1"),
        (
            {"discharge_disposition": "snf", "clinical_course_archetype": "plateau_then_recovery"},
            False,
            "unchanged",
            "4",
        ),
        (
            {"discharge_disposition": "snf", "clinical_course_archetype": "gradual_deterioration"},
            False,
            "worsened",
            "5",
        ),
        ({"discharge_disposition": "exp"}, True, "death_from_condition", "6"),
        ({"admission_diagnosis_code": "O80"}, False, "other", "9"),
    ],
)
def test_improved_unchanged_worsened_death_and_other_stays_in_jp(
    overrides: dict, deceased: bool, outcome: str, code: str
) -> None:
    enc = _imp(**overrides)
    assert discharge_outcome(enc, deceased=deceased) == outcome
    concept = _dispo(enc, "JP", deceased)
    (coding,) = concept["coding"]
    assert (coding["system"], coding["code"]) == (_JP_URI, code)
    assert coding["display"] == code_lookup("jpfhir-discharge-disposition", code, "ja")
    assert concept["text"] == coding["display"]


@pytest.mark.parametrize(
    ("overrides", "deceased", "code"),
    [
        ({}, False, "home"),
        ({"discharge_disposition": "snf"}, False, "snf"),
        ({"discharge_disposition": ""}, True, "exp"),
    ],
)
def test_us_keeps_the_hl7_destination_coding(overrides: dict, deceased: bool, code: str) -> None:
    concept = _dispo(_imp(**overrides), "US", deceased)
    (coding,) = concept["coding"]
    assert (coding["system"], coding["code"]) == (get_system_uri("hl7-discharge-disposition"), code)
    assert concept["text"] == code_lookup("hl7-discharge-disposition", code, "en")


def test_a_jp_emergency_visit_keeps_its_destination() -> None:
    enc = _imp(encounter_type="emergency", discharge_disposition="psy")
    res = _build_encounter(enc, patient_id="POP-1", country="JP")
    coding = res["hospitalization"]["dischargeDisposition"]["coding"][0]
    assert coding["code"] == "psy"


def test_jp_codes_are_the_jpfhir_value_set() -> None:
    from clinosim.locale.loader import load_code_mapping

    table = load_code_mapping("discharge_disposition", "JP")
    assert set(table["IMP"]["codes"].values()) <= {"1", "3", "4", "5", "6", "7", "9"}


def test_the_record_level_admission_diagnosis_is_used() -> None:
    # The CIF records a delivery's O80 on the clinical diagnosis, not the encounter.
    enc = _imp(admission_diagnosis_code="")
    res = _build_encounter(enc, patient_id="POP-1", country="JP", admit_dx_code="O80")
    assert res["hospitalization"]["dischargeDisposition"]["coding"][0]["code"] == "9"
