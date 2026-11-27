"""Issue #3913: the discharge diagnosis of a delivery stay is the principal
obstetric code (O80 / O82, or the complication that makes the delivery
complicated), with Z37.0 (outcome of delivery) a secondary diagnosis, per the
ICD-10-CM Official Guidelines Section I.C.15.b.5: "A code from category Z37,
Outcome of delivery, should be included on every maternal record when a
delivery has occurred" (a secondary code; I.C.15.n.3: "Z37.0, Single live
birth, is the only outcome of delivery code appropriate for use with O80")."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions
from clinosim.modules.output.fhir_r4.conditions.primary_ref import encounter_diagnosis_condition_ids
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter
from tests.unit.simulator.test_perinatal_complication_coding import _CESAREAN, _VAGINAL, _deliver

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize(("pid", "principal"), [(_VAGINAL, "O80"), (_CESAREAN, "O82")])
def test_uncomplicated_delivery_discharges_with_the_obstetric_code(country: str, pid: str, principal: str) -> None:
    dx = _deliver(pid, [], country=country).clinical_diagnosis
    assert dx.admission_diagnosis_code == dx.discharge_diagnosis_code == principal
    assert dx.secondary_diagnosis_codes == ["Z37.0"]


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("pid", [_VAGINAL, _CESAREAN])
def test_complicated_delivery_discharges_with_the_principal_complication(country: str, pid: str) -> None:
    dx = _deliver(pid, ["O24.9", "O14.9"], country=country).clinical_diagnosis
    assert dx.discharge_diagnosis_code == dx.admission_diagnosis_code == "O24.9"
    assert [w["disease_id"] for w in dx.working_diagnoses] == ["O14.9"]
    assert dx.secondary_diagnosis_codes == ["Z37.0"]


def _fhir_roles(rec) -> dict[str, str]:
    """DD / CM role -> the ICD code of the Condition it points at, from the CIF record."""
    from dataclasses import asdict

    cd = asdict(rec.clinical_diagnosis)
    enc = rec.encounters[0]
    record = {
        "patient": {"patient_id": "POP-000042", "sex": "F"},
        "clinical_diagnosis": cd,
        "encounters": [
            {
                "encounter_id": enc.encounter_id,
                "encounter_type": "inpatient",
                "admission_datetime": enc.admission_datetime.isoformat(),
                "discharge_datetime": enc.discharge_datetime.isoformat(),
                "attending_physician_id": "DR-1",
                "status": "completed",
            }
        ],
        "deceased": False,
    }
    conds = _build_conditions(record, patient_id="POP-000042", country="US")
    ref = conds[0]["encounter"]["reference"]
    resource = _build_encounter(
        record["encounters"][0],
        "POP-000042",
        primary_dx_code=cd["discharge_diagnosis_code"],
        admit_dx_code=cd["admission_diagnosis_code"],
        country="US",
        patient_sex="F",
        diagnosis_condition_ids=encounter_diagnosis_condition_ids(conds, ref),
    )
    by_id = {c["id"]: c["code"]["coding"][0]["code"] for c in conds}
    return {
        d["use"]["coding"][0]["code"]: by_id[d["condition"]["reference"].split("/", 1)[1]]
        for d in resource["diagnosis"]
    }


def test_encounter_marks_the_obstetric_code_dd_and_the_outcome_cm() -> None:
    roles = _fhir_roles(_deliver(_VAGINAL, []))
    assert roles["DD"].startswith("O80")
    assert roles["CM"].startswith("Z37")
    assert "AD" not in roles  # one code is both the admission and the discharge diagnosis


def test_complicated_delivery_encounter_has_the_complication_as_dd() -> None:
    roles = _fhir_roles(_deliver(_VAGINAL, ["O14.9", "O42.9"]))
    assert roles["DD"].startswith("O14")


@pytest.mark.parametrize(("lang", "system", "country_locale"), [("en", "icd-10-cm", "us"), ("ja", "icd-10", "jp")])
def test_discharge_summary_diagnoses_lead_with_the_obstetric_code(lang: str, system: str, country_locale: str) -> None:
    from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import (
        build_discharge_diagnoses,
    )
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
    from clinosim.types.document import DocumentType, NarrativeContext

    rec = _deliver(_VAGINAL, [], country="JP" if lang == "ja" else "US")
    from dataclasses import asdict

    ctx = NarrativeContext(
        patient={"patient_id": "P1"},
        encounter={"encounter_id": "ENC-1"},
        encounter_type="inpatient",
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=4,
        los_days=5,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[asdict(rec.clinical_diagnosis)],
        procedures=[],
        allergies=[],
        document_type=DocumentType.DISCHARGE_SUMMARY,
        target_lang=lang,
        locale=country_locale,
    )
    text = build_discharge_diagnoses(TemplateNarrativeGenerator(), ctx)[0]
    assert "O80" in text and "Z37.0" in text, text
    assert text.index("O80") < text.index("Z37.0"), text
