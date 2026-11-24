"""Issue #3692: JP_eCS_Department states the department of the referenced Encounter."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.lib.ecs_extensions import build_ecs_department_extension
from clinosim.modules.output.fhir_r4.post_process.profile import fill_ecs_department_from_encounters

pytestmark = pytest.mark.unit

_PLACEHOLDER = build_ecs_department_extension()["valueCodeableConcept"]["text"]


def _enc(i: str, dept: str) -> dict:
    return {"resource": {"resourceType": "Encounter", "id": i, "serviceType": {"text": dept}}}


def _res(rt: str, enc: str | None) -> dict:
    r: dict = {"resourceType": rt, "extension": [build_ecs_department_extension()]}
    if enc:
        r["encounter"] = {"reference": f"Encounter/{enc}"}
    return {"resource": r}


def _dept(entry: dict) -> str:
    return entry["resource"]["extension"][0]["valueCodeableConcept"]["text"]


def test_medication_request_and_condition_take_the_encounter_department() -> None:
    entries = [
        _enc("e1", "循環器内科"),
        _enc("e1-ed", "救急科"),
        _res("MedicationRequest", "e1"),
        _res("Condition", "e1-ed"),
    ]
    fill_ecs_department_from_encounters(entries, "JP")
    assert _dept(entries[2]) == "循環器内科"
    assert _dept(entries[3]) == "救急科"


def test_problem_list_condition_and_unknown_encounter_keep_the_placeholder() -> None:
    entries = [_enc("e1", "循環器内科"), _res("Condition", None), _res("Condition", "missing")]
    fill_ecs_department_from_encounters(entries, "JP")
    assert _dept(entries[1]) == _PLACEHOLDER
    assert _dept(entries[2]) == _PLACEHOLDER


def test_us_untouched() -> None:
    entries = [_enc("e1", "Cardiology"), _res("MedicationRequest", "e1")]
    fill_ecs_department_from_encounters(entries, "US")
    assert _dept(entries[1]) == _PLACEHOLDER
