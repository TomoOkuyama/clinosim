"""E11.9 is not emitted alongside a diabetic complication code (Issue #3873).

``E11.9`` (type 2 diabetes without complications) stays in the CIF as the
internal driver; every emit site resolves through
``clinosim.modules.population.condition_mutex``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions
from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
    chronic_condition_id,
    primary_condition_ref_from_codes,
)
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter
from clinosim.modules.population.condition_mutex import (
    principal_code_for_problem_list,
    redundant_uncomplicated_diabetes_indices,
    without_redundant_uncomplicated_diabetes,
)
from clinosim.simulator.outpatient import _visit_diagnosis_code

pytestmark = pytest.mark.unit

_ENC = {
    "encounter_id": "enc-1",
    "encounter_type": "outpatient",
    "admission_datetime": "2026-05-01T10:00:00",
    "discharge_datetime": "2026-05-01T11:00:00",
}


def _record(chronic: list[str], primary: str = "") -> dict:
    return {
        "clinical_diagnosis": {"discharge_diagnosis_code": primary, "working_diagnoses": []},
        "encounters": [dict(_ENC)],
        "patient": {"chronic_conditions": [{"code": c, "onset_date": "2020-01-01"} for c in chronic]},
    }


def _codes(conditions: list[dict]) -> list[str]:
    return [c["code"]["coding"][0]["code"] for c in conditions]


# --- the canonical resolver -------------------------------------------------


@pytest.mark.parametrize("complication", ["E11.21", "E11.311", "E11.42", "E11.3"])
def test_e119_is_redundant_beside_a_complication(complication: str) -> None:
    assert redundant_uncomplicated_diabetes_indices(["E11.9", "I10", complication]) == {0}


def test_e119_is_kept_without_a_complication_and_other_codes_are_never_dropped() -> None:
    assert redundant_uncomplicated_diabetes_indices(["E11.9", "I10"]) == frozenset()
    assert redundant_uncomplicated_diabetes_indices(["E11.9", "E11.21"]) == {0}
    # E10.x / E13.x are other diabetes types: no relation to E11.9
    assert redundant_uncomplicated_diabetes_indices(["E11.9", "E10.21"]) == frozenset()


def test_resolver_reads_strings_mappings_and_objects() -> None:
    items = ["E11.9", {"code": "E11.311"}, SimpleNamespace(code="I10")]
    kept = without_redundant_uncomplicated_diabetes(items)
    assert kept == items[1:]
    assert principal_code_for_problem_list("E11.9", items) == "E11.311"
    assert principal_code_for_problem_list("E11.9", ["E11.9"]) == "E11.9"
    assert principal_code_for_problem_list("I10", items) == "I10"


# --- FHIR emit --------------------------------------------------------------


@pytest.mark.parametrize("country", ["US", "JP"])
def test_condition_list_has_no_e119_beside_a_complication(country: str) -> None:
    conds = _build_conditions(_record(["E11.9", "E11.311", "I10"]), "pat-1", country)
    emitted = _codes(conds)
    assert not any(c.startswith("E11.9") for c in emitted)
    assert len(emitted) == 2
    # the complication keeps the id of its position in chronic_conditions
    ids = {c["id"] for c in conds}
    assert any(chronic_condition_id("pat-1", 1) in i for i in ids)


def test_condition_list_keeps_e119_without_a_complication() -> None:
    assert _codes(_build_conditions(_record(["E11.9", "I10"]), "pat-1", "US")) == ["E11.9", "I10"]


def test_followup_whose_principal_is_e119_resolves_to_the_complication() -> None:
    ref = primary_condition_ref_from_codes("E11.9", ["E11.9", "E11.311"], "pat-1", "enc-1")
    assert ref == chronic_condition_id("pat-1", 1)
    conds = _build_conditions(_record(["E11.9", "E11.311"], primary="E11.9"), "pat-1", "US")
    assert _codes(conds) == ["E11.311"]


def _diagnosis_refs(chronic: list[str], primary: str) -> list[str]:
    res = _build_encounter(
        dict(_ENC),
        "pat-1",
        primary_dx_code=primary,
        country="US",
        chronic_condition_codes=chronic,
        diagnosis_condition_ids=None,
    )
    return [d["condition"]["reference"].split("/")[-1] for d in res.get("diagnosis", [])]


def test_encounter_diagnosis_never_pairs_e119_with_a_complication() -> None:
    refs = _diagnosis_refs(["E11.9", "E11.311", "E11.42"], "E11.9")
    assert chronic_condition_id("pat-1", 0) not in refs
    assert refs[0] == chronic_condition_id("pat-1", 1)  # principal = the complication
    assert chronic_condition_id("pat-1", 2) in refs
    assert len(refs) == len(set(refs))


# --- the outpatient visit's principal diagnosis ------------------------------


def test_visit_principal_is_the_complication_code() -> None:
    patient = SimpleNamespace(chronic_conditions=[SimpleNamespace(code="E11.9"), SimpleNamespace(code="E11.311")])
    assert _visit_diagnosis_code("E11.9", "", "chronic_followup", patient=patient) == "E11.311"
    plain = SimpleNamespace(chronic_conditions=[SimpleNamespace(code="E11.9")])
    assert _visit_diagnosis_code("E11.9", "", "chronic_followup", patient=plain) == "E11.9"
    assert _visit_diagnosis_code("E11.9", "", "chronic_followup") == "E11.9"


# --- the CIF keeps E11.9 as the driver ----------------------------------------


def test_cif_driver_still_finds_the_e119_followup_spec() -> None:
    from clinosim.locale.loader import load_chronic_followup

    assert "E11.9" in load_chronic_followup()


# --- narrative problem lists -------------------------------------------------


def _narrative_ctx(lang: str, codes: list[str]) -> SimpleNamespace:
    from clinosim.types.document import DocumentType

    patient = SimpleNamespace(
        chronic_conditions=[SimpleNamespace(code=c, stage="") for c in codes],
        current_medications=[],
        age=63,
        sex="F",
        date_of_birth=None,
    )
    return SimpleNamespace(
        patient=patient,
        encounter=SimpleNamespace(chief_complaint="", primary_nurse_id=""),
        diagnoses=[],
        lab_results=[],
        vitals=[],
        medications=[],
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        document_type=DocumentType.ADMISSION_HP,
        materialized_facts=[],
        section_facts={},
        authored_datetime=None,
        roster_map={},
    )


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_problem_lists_do_not_pair_e119_with_a_complication(lang: str) -> None:
    from clinosim.modules.document.narrative.renderers._shared_helpers import ordered_chronic_conditions
    from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
        build_past_medical_history,
    )
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

    ctx = _narrative_ctx(lang, ["E11.9", "E11.21", "I10"])
    assert [c.code for c in ordered_chronic_conditions(ctx)] == ["E11.21", "I10"]
    text, _ = build_past_medical_history(TemplateNarrativeGenerator(), ctx)
    assert "E11.2" in text
    assert "E11.9" not in text

    plain = _narrative_ctx(lang, ["E11.9", "I10"])
    assert "E11.9" in build_past_medical_history(TemplateNarrativeGenerator(), plain)[0]


def test_e119_of_a_record_before_the_complication_was_recorded_is_superseded() -> None:
    """A record whose own snapshot has no complication still lists E11.9; once the
    patient's later records carry a complication code, that entry is inactive from
    the day the complication was first recorded (not an active E11.9 beside E11.3)."""
    first_seen = {"": "2025-09-01T09:00:00", "E11.9": "2025-09-01T09:00:00", "E11.311": "2026-02-24T09:00:00"}
    conds = _build_conditions(_record(["E11.9", "I10"]), "pat-1", "US", first_seen)
    e119 = next(c for c in conds if c["code"]["coding"][0]["code"] == "E11.9")
    assert e119["clinicalStatus"]["coding"][0]["code"] == "inactive"
    assert e119["abatementDateTime"].startswith("2026-02-24")
    plain = _build_conditions(_record(["E11.9", "I10"]), "pat-1", "US", {"": "2025-09-01T09:00:00"})
    assert (
        next(c for c in plain if c["code"]["coding"][0]["code"] == "E11.9")["clinicalStatus"]["coding"][0]["code"]
        == "active"
    )
