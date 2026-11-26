"""Issue #3868: a cancer's surveillance procedure carries its own cancer as
indication, goes to the cancer's own visit when one follows, and is not
worded as a screening test of an unrelated visit."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from clinosim.locale.loader import load_chronic_followup
from clinosim.simulator.outpatient import _followup_procedures
from clinosim.types.encounter import Encounter
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit

_VISIT = datetime(2025, 7, 28, 10, 32)


def _patient(*codes: str) -> PatientProfile:
    p = PatientProfile(patient_id="POP-T-3868")
    p.chronic_conditions = [ChronicCondition(code=c, stage="") for c in codes]
    p.sex = "F"
    return p


def _run(patient: PatientProfile, code: str, spec: dict[str, Any], visit_type: str = "chronic_followup", when=_VISIT):
    enc = Encounter(encounter_id=f"ENC-{code}-{when:%m%d}", attending_physician_id="DR-1")
    return _followup_procedures(patient, spec, code, visit_type, enc, when, "US")


def _colonoscopy(procs) -> list:
    return [p for p in procs if p.procedure_code_us == "45378"]


def test_procedure_record_has_an_indication_field() -> None:
    from clinosim.types.procedure import ProcedureRecord

    assert ProcedureRecord().indication_code == ""


def test_unrelated_visit_defers_a_cancer_procedure_to_the_oncology_visit_that_follows() -> None:
    patient = _patient("I10", "C18")
    assert _colonoscopy(_run(patient, "I10", load_chronic_followup()["I10"])) == []


def test_oncology_visit_carries_the_cancers_own_procedure_with_its_indication() -> None:
    patient = _patient("I10", "C18")
    fanout_spec = {"labs": [], "visit_reason": {"en": "Oncology survivorship follow-up"}, "fanout": True}
    procs = _colonoscopy(_run(patient, "C18", fanout_spec))
    assert len(procs) == 1 and procs[0].indication_code == "C18"


def test_own_block_visit_marks_its_procedure_with_its_own_code() -> None:
    patient = _patient("C18")
    procs = _colonoscopy(_run(patient, "C18", load_chronic_followup()["C18"]))
    assert len(procs) == 1 and procs[0].indication_code == "C18"


def test_without_an_oncology_visit_to_follow_the_procedure_keeps_its_cancer_as_reason() -> None:
    patient = _patient("I10", "C18")
    patient.visit_ledger.specialty_visits.add(("oncology", _VISIT.year, None))  # the year's oncology visit is done
    procs = _colonoscopy(_run(patient, "I10", load_chronic_followup()["I10"]))
    assert len(procs) == 1 and procs[0].indication_code == "C18"


def test_visit_that_starts_no_specialty_follow_up_keeps_the_procedure() -> None:
    patient = _patient("I10", "C18")
    procs = _colonoscopy(_run(patient, "flu_vaccination", {"labs": []}))
    assert len(procs) == 1 and procs[0].indication_code == "C18"


def test_a_specialty_visit_of_another_specialty_does_not_take_the_cancers_procedure() -> None:
    patient = _patient("I48", "C18")
    spec = {"labs": [], "fanout": True}
    assert _colonoscopy(_run(patient, "I48", spec)) == []


def test_an_ordinary_procedure_of_the_visits_own_block_is_marked_with_that_block() -> None:
    patient = _patient("G47.30")
    procs = _run(patient, "G47.30", load_chronic_followup()["G47.30"])
    assert procs and all(p.indication_code == "G47.30" for p in procs)


# ── FHIR reason ────────────────────────────────────────────────────────


def _record(chronic: list[str]) -> dict[str, Any]:
    return {
        "patient": {"patient_id": "POP-T-3868", "sex": "F", "chronic_conditions": [{"code": c} for c in chronic]},
        "encounters": [{"encounter_id": "ENC-1", "encounter_type": "outpatient"}],
        "clinical_diagnosis": {"admission_diagnosis_code": "I10", "discharge_diagnosis_code": "I10"},
    }


def _proc(indication: str = "") -> dict[str, Any]:
    return {
        "procedure_id": "PROC-1",
        "encounter_id": "ENC-1",
        "procedure_type": "Colonoscopy",
        "procedure_code": "45378",
        "procedure_code_us": "45378",
        "start_datetime": datetime(2025, 7, 28, 10, 42),
        "end_datetime": datetime(2025, 7, 28, 11, 12),
        "indication_code": indication,
    }


@pytest.mark.parametrize("country", ["US", "JP"])
def test_fhir_reason_prefers_the_indication_over_the_visits_diagnosis(country: str) -> None:
    from clinosim.modules.output.fhir_r4.conditions.primary_ref import chronic_condition_id
    from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

    res = _build_procedure(_proc("C18"), "POP-T-3868", 0, country, record=_record(["I10", "C18"]))
    code = res["reasonCode"][0]["coding"][0]["code"]
    assert code.startswith("C18"), res["reasonCode"]
    assert res["reasonReference"] == [{"reference": f"Condition/{chronic_condition_id('POP-T-3868', 1)}"}]


def test_fhir_reason_without_an_indication_is_the_visits_diagnosis() -> None:
    from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

    res = _build_procedure(_proc(), "POP-T-3868", 0, "US", record=_record(["I10", "C18"]))
    assert res["reasonCode"][0]["coding"][0]["code"].startswith("I10")


# ── narrative ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("country", ["US", "JP"])
def test_screening_items_leave_out_a_procedure_of_another_condition(country: str) -> None:
    from types import SimpleNamespace

    from clinosim.modules.document.narrative._visit_reason import _screening_items

    def _ctx(indication: str):
        proc = {
            "procedure_type": "Colonoscopy",
            "procedure_code_us": "45378",
            "procedure_code": "45378",
            "indication_code": indication,
        }
        return SimpleNamespace(
            target_lang="ja" if country == "JP" else "en",
            locale=country.lower(),
            lab_results=[],
            orders=[],
            procedures=[proc],
            visit_condition_id="diabetic_retinopathy_screening",
            authored_datetime=None,
            encounter=None,
        )

    assert "olonoscopy" not in _screening_items(_ctx("C18")) and "大腸" not in _screening_items(_ctx("C18"))
    assert _screening_items(_ctx("")) != ""
