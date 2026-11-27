"""A complication the stay already carries is accounted for by the carrying diagnosis (Issue #3905).

A coded complication whose ICD-10 category the stay already carries (principal,
secondary, working or chronic code) or an earlier complication already entered
adds no second Condition. It is recorded on ``clinical_diagnosis.carried_complications``
with the code that carries it, so the discharge-diagnosis list names it with that
code and ``Encounter.diagnosis`` points at the carrying Condition.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.locale.i18n import t
from clinosim.locale.loader import map_diagnosis_code
from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import build_discharge_diagnoses
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.output.fhir_r4.conditions.primary_ref import carrying_condition_ids
from clinosim.simulator.complication_dx import complication_diagnoses
from clinosim.simulator.complications import build_complication
from clinosim.types.clinical import ClinicalDiagnosis
from clinosim.types.document import NarrativeContext
from tests.unit.output.test_fhir_encounter_diagnosis_refs_3597 import _ctx as _bundle_ctx

pytestmark = pytest.mark.unit

_ILEUS = build_complication("constipation_ileus", 6, "2026-06-20T12:00:00", "daily_loop")
_ASPIRATION = build_complication("recurrent_aspiration", 3, "2026-06-17T12:00:00", "daily_loop")
_AKI = build_complication("acute_kidney_injury", 6, "2026-06-20T12:00:00", "daily_loop")


def test_a_chronic_condition_carries_the_complication() -> None:
    entries, carried = complication_diagnoses([_ILEUS], stay_codes=["S22.0", "I82.40"], chronic_codes=["K59", "I10"])
    assert entries == []
    assert carried == [{"name": "constipation_ileus", "carrying_code": "K59", "carrier": "chronic"}]


def test_the_principal_diagnosis_carries_the_complication() -> None:
    entries, carried = complication_diagnoses([_ASPIRATION], stay_codes=["J69.0"], chronic_codes=["K59"])
    assert entries == []
    assert carried == [{"name": "recurrent_aspiration", "carrying_code": "J69.0", "carrier": "stay"}]


def test_the_stay_is_searched_before_the_chronic_list() -> None:
    _, carried = complication_diagnoses([_ILEUS], stay_codes=["K59.0"], chronic_codes=["K59"])
    assert carried[0]["carrying_code"] == "K59.0"
    assert carried[0]["carrier"] == "stay"


def test_an_earlier_complication_carries_a_later_one_of_its_category() -> None:
    later = build_complication("venous_thromboembolism", 5, "2026-06-19T12:00:00", "daily_loop")
    earlier = build_complication("dvt", 2, "2026-06-16T12:00:00", "daily_loop")
    entries, carried = complication_diagnoses([earlier, later], stay_codes=[], chronic_codes=[])
    assert len(entries) == 1
    assert carried == [
        {"name": "venous_thromboembolism", "carrying_code": entries[0]["disease_id"], "carrier": "complication"}
    ]


def test_an_unblocked_complication_is_not_carried() -> None:
    entries, carried = complication_diagnoses([_AKI], stay_codes=["I21.9"], chronic_codes=["N18.3"])
    assert len(entries) == 1 and carried == []


def test_the_cif_field_defaults_to_empty() -> None:
    assert ClinicalDiagnosis().carried_complications == []


def _ctx(lang: str, diagnoses: list[dict], events: list[dict]) -> NarrativeContext:
    return NarrativeContext(
        patient=SimpleNamespace(patient_id="pt-3905", sex="M", age=70),
        encounter=SimpleNamespace(encounter_id="enc-3905"),
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=6,
        los_days=6,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=diagnoses,
        procedures=[],
        allergies=[],
        document_type=None,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        complications_events=events,
    )


def _secondary(lang: str, text: str) -> str:
    return text.split("Secondary diagnoses:" if lang == "en" else "副病名:")[1]


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_chronic_carried_complication_is_listed_with_the_chronic_code(lang: str) -> None:
    dx = {
        "discharge_diagnosis_code": "S22.0",
        "discharge_diagnosis_system": "icd-10-cm",
        "carried_complications": [{"name": "constipation_ileus", "carrying_code": "K59", "carrier": "chronic"}],
    }
    text, _ = build_discharge_diagnoses(
        TemplateNarrativeGenerator(), _ctx(lang, [dx], [{"name": "constipation_ileus"}])
    )
    secondary = _secondary(lang, text)
    name = "便秘性イレウス" if lang == "ja" else "constipation ileus"
    assert name in secondary
    # The chronic code in the country's system (JP K59 -> MHLW K59.0, US K59 -> K59.0).
    emitted = map_diagnosis_code("K59", "JP" if lang == "ja" else "US", sex="M")
    assert t("list_item.inline_dx_with_code", lang, display=name, code=emitted) in secondary


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_principal_carried_complication_is_not_a_separate_secondary_diagnosis(lang: str) -> None:
    dx = {
        "discharge_diagnosis_code": "J69.0",
        "discharge_diagnosis_system": "icd-10-cm",
        "carried_complications": [{"name": "recurrent_aspiration", "carrying_code": "J69.0", "carrier": "stay"}],
    }
    text, _ = build_discharge_diagnoses(
        TemplateNarrativeGenerator(), _ctx(lang, [dx], [{"name": "recurrent_aspiration"}])
    )
    assert "副病名" not in text and "Secondary" not in text


def _record_with_carried(carried: list[dict], chronic: list[dict], dx_extra: dict | None = None):
    dx = {
        "admission_diagnosis_code": "S22.0",
        "discharge_diagnosis_code": "S22.0",
        "working_diagnoses": [],
        "carried_complications": carried,
        **(dx_extra or {}),
    }
    return _bundle_ctx("JP", dx=dx, chronic=chronic)


def test_carrying_condition_ids_resolve_the_chronic_problem_list_condition() -> None:
    from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_conditions

    ctx = _record_with_carried(
        [{"name": "constipation_ileus", "carrying_code": "K59", "carrier": "chronic"}],
        [{"code": "K59"}, {"code": "I10"}],
    )
    conds = _bb_conditions(ctx)
    chronic = [c for c in conds if c["code"]["coding"][0]["code"] == map_diagnosis_code("K59", "JP", sex="M")]
    assert len(chronic) == 1
    ids = carrying_condition_ids(
        conds, ctx.record["clinical_diagnosis"]["carried_complications"], country="JP", patient_sex="M"
    )
    assert ids == [chronic[0]["id"]]


def test_a_carrier_that_has_no_condition_adds_no_dangling_reference() -> None:
    conds: list[dict] = []
    assert (
        carrying_condition_ids(conds, [{"name": "x", "carrying_code": "K59", "carrier": "chronic"}], country="JP") == []
    )


def test_encounter_diagnosis_references_the_carrying_condition() -> None:
    from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_conditions, _bb_encounters

    ctx = _record_with_carried(
        [{"name": "constipation_ileus", "carrying_code": "K59", "carrier": "chronic"}],
        [{"code": "K59"}, {"code": "I10"}],
    )
    (enc,) = [r for r in _bb_encounters(ctx) if r["resourceType"] == "Encounter"]
    chronic = [
        c for c in _bb_conditions(ctx) if c["code"]["coding"][0]["code"] == map_diagnosis_code("K59", "JP", sex="M")
    ]
    refs = [d["condition"]["reference"].split("/")[-1] for d in enc["diagnosis"]]
    assert chronic[0]["id"] in refs
    assert len(refs) == len(set(refs))
