"""Issue #3010: JP conditions are coded in WHO ICD-10 (MHLW ICD10-2013), never
in ICD-10-CM-only codes.

The lifestyle / SDOH conditions are generated with ICD-10-CM codes (F17.210,
F10.20, E66.3, E66.01, G47.30) and the obstetric history with Z87.59; JP output
folds each to its WHO code. Procedure.reasonCode, like Condition and
Encounter, carries the country's code.
"""

from __future__ import annotations

import pytest

from clinosim.codes import display as registry_display
from clinosim.locale.loader import map_diagnosis_code

pytestmark = pytest.mark.unit

_FOLDS = {
    "F17.210": "F17.2",  # Nicotine dependence, cigarettes → tobacco dependence syndrome
    "F10.20": "F10.2",  # Alcohol dependence, uncomplicated → alcohol dependence syndrome
    "E66.3": "E66.9",  # Overweight (BMI 25-29.9; 肥満 in Japan) → obesity, unspecified
    "E66.01": "E66.0",  # Morbid obesity due to excess calories → obesity due to excess calories
    "G47.30": "G47.3",  # Sleep apnea, unspecified → sleep apnoea
    "Z87.59": "Z87.5",  # History of other complications of pregnancy → history of pregnancy complications
}


def test_jp_nicotine_dependence_is_f17_2() -> None:
    assert map_diagnosis_code("F17.210", "JP") == "F17.2"
    assert registry_display("icd-10-mhlw", "F17.2", "ja") == "タバコ使用＜喫煙＞による精神及び行動の障害，依存症候群"


@pytest.mark.parametrize(("cm", "who"), sorted(_FOLDS.items()))
def test_lifestyle_codes_fold_to_who(cm: str, who: str) -> None:
    assert map_diagnosis_code(cm, "JP") == who
    assert registry_display("icd-10", who, "en")
    assert registry_display("icd-10", who, "ja") != registry_display("icd-10", who, "en")


@pytest.mark.parametrize("code", ["E66.9", "K76.0"])
def test_who_valid_lifestyle_codes_stay_and_resolve(code: str) -> None:
    assert map_diagnosis_code(code, "JP") == code
    assert registry_display("icd-10", code, "ja")


def test_procedure_reason_code_carries_the_jp_code() -> None:
    from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

    record = {
        "clinical_diagnosis": {"discharge_diagnosis_code": "Z12.11", "admission_diagnosis_code": "Z12.11"},
        "encounters": [],
    }
    proc = {
        "procedure_id": "PROC-1",
        "encounter_id": "",
        "procedure_code": "45378",
        "procedure_name": "colonoscopy",
        "performed_datetime": "2026-03-02T10:00:00",
    }
    res = _build_procedure(proc, "POP-1", 0, "JP", record=record)
    coding = res["reasonCode"][0]["coding"][0]
    assert coding["code"] == "Z12.1"
    assert coding["display"] == registry_display("icd-10-mhlw", "Z12.1", "ja")
