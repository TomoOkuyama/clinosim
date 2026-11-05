"""Issue #2585: culture results are linked to their order and to each other.

The organism Observation lists its susceptibilities in ``hasMember``; each
susceptibility is ``derivedFrom`` the organism. Organism, susceptibilities and
the microbiology report are ``basedOn`` the culture order(s) drawn for that
specimen, and those orders are completed.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.labs.microbiology import _bb_microbiology
from clinosim.modules.output.fhir_r4.labs.service_request import _bb_service_requests
from clinosim.modules.output.fhir_r4.lib.context import BundleContext

pytestmark = pytest.mark.unit

_ENC = "E1"


def _order(order_id: str, name: str, ordered: str) -> dict:
    return {
        "order_id": order_id,
        "encounter_id": _ENC,
        "patient_id": "P1",
        "order_type": "lab",
        "order_code": name,
        "display_name": name,
        "urgency": "stat",
        "clinical_intent": "",
        "ordered_datetime": ordered,
        "ordered_by": "doc1",
        "status": "placed",
        "panel_key": "",
        "result": None,
    }


def _culture(specimen: str = "blood", collected: str = "2025-11-19T10:47:00") -> dict:
    return {
        "encounter_id": _ENC,
        "specimen": specimen,
        "test_loinc": "600-7",
        "collected_datetime": collected,
        "reported_datetime": "2025-11-21T09:00:00",
        "growth": True,
        "organism_snomed": "3092008",
        "susceptibilities": [
            {"antibiotic_loinc": "19000-9", "interpretation": "S"},
            {"antibiotic_loinc": "18943-1", "interpretation": "R"},
        ],
    }


def _ctx(orders: list[dict], cultures: list[dict]) -> BundleContext:
    return BundleContext(
        record={"orders": orders, "microbiology": cultures},
        country="US",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="P1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id=_ENC,
        patient_sex="M",
    )


def _blood_draw() -> list[dict]:
    return [
        _order("O-bc1", "Blood_culture_set_1", "2025-11-19T10:49:00"),
        _order("O-bc2", "Blood_culture_set_2", "2025-11-19T10:49:00"),
        _order("O-uc", "Urine_culture", "2025-11-19T10:50:00"),
        _order("O-bcr", "Blood_culture_repeat_x2", "2025-11-24T20:47:00"),
    ]


def _split(resources: list[dict]) -> tuple[dict, list[dict], dict]:
    obs = [r for r in resources if r["resourceType"] == "Observation"]
    org = next(o for o in obs if "valueCodeableConcept" in o and o["code"]["coding"][0]["code"] == "600-7")
    sus = [o for o in obs if o is not org]
    dr = next(r for r in resources if r["resourceType"] == "DiagnosticReport")
    return org, sus, dr


def test_the_organism_lists_its_susceptibilities_and_each_derives_from_it() -> None:
    org, sus, _dr = _split(_bb_microbiology(_ctx(_blood_draw(), [_culture()])))
    assert len(sus) == 2
    assert org["hasMember"] == [{"reference": f"Observation/{s['id']}"} for s in sus]
    for s in sus:
        assert s["derivedFrom"] == [{"reference": f"Observation/{org['id']}"}]


def test_results_are_based_on_the_blood_cultures_of_that_draw() -> None:
    ctx = _ctx(_blood_draw(), [_culture()])
    srs = {sr["identifier"][0]["value"]: sr for sr in _bb_service_requests(ctx)}
    draw = sorted([{"reference": f"ServiceRequest/{srs[k]['id']}"} for k in ("O-bc1", "O-bc2")], key=str)
    org, sus, dr = _split(_bb_microbiology(ctx))
    for resource in (org, *sus, dr):
        assert sorted(resource["basedOn"], key=str) == draw


def test_the_orders_a_culture_reports_are_completed_and_the_others_are_not() -> None:
    ctx = _ctx(_blood_draw(), [_culture()])
    status = {sr["identifier"][0]["value"]: sr["status"] for sr in _bb_service_requests(ctx)}
    assert status["O-bc1"] == status["O-bc2"] == "completed"
    assert status["O-uc"] == "active"  # a different specimen
    assert status["O-bcr"] == "active"  # a later draw


def test_a_culture_without_an_order_for_its_specimen_gets_no_basedon() -> None:
    org, sus, dr = _split(_bb_microbiology(_ctx(_blood_draw(), [_culture(specimen="sputum")])))
    for resource in (org, *sus, dr):
        assert "basedOn" not in resource


def test_a_negative_culture_has_no_members() -> None:
    culture = {**_culture(), "growth": False, "organism_snomed": "", "susceptibilities": []}
    resources = _bb_microbiology(_ctx(_blood_draw(), [culture]))
    org = next(r for r in resources if r["resourceType"] == "Observation")
    assert "hasMember" not in org
    assert org["basedOn"]
