"""A stay admitted through the ED has its ED phase attended by an ED physician (Issue #3874)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim import determinism
from clinosim.modules.document.engine import _pick_document_author
from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_encounters, _bb_practitioners
from clinosim.modules.staff.engine import assign_ed_physician, generate_roster
from clinosim.modules.triage.engine import triage_enricher
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

_HOSPITAL = {
    "available_departments": ["emergency_medicine", "internal_medicine", "cardiology"],
    "wards": {"emergency_medicine": ["ER"], "internal_medicine": ["3N"], "cardiology": ["5E"]},
    "resource_capacity": {"inpatient_beds": 120, "operating_rooms": 3},
}


def _roster(country: str = "US"):
    return generate_roster("medium", country, determinism.default_rng(3), hospital_config=_HOSPITAL)


def test_assign_ed_physician_is_an_ed_physician_and_stable() -> None:
    roster = _roster()
    ids = {assign_ed_physician(roster, f"ENC-{i}") for i in range(40)}
    assert ids and all(i.startswith("DR-EM-") for i in ids)
    assert len(ids) > 1  # spread over the ED pool, not one fixed physician
    assert assign_ed_physician(roster, "ENC-7") == assign_ed_physician(roster, "ENC-7")


def test_assign_ed_physician_without_an_ed_pool_is_empty() -> None:
    roster = _roster()
    roster.members = [m for m in roster.members if not m.staff_id.startswith("DR-EM-")]
    assert assign_ed_physician(roster, "ENC-1") == ""


def test_assign_ed_physician_consumes_no_rng() -> None:
    roster = _roster()
    rng = determinism.default_rng(11)
    before = rng.bit_generator.state
    assign_ed_physician(roster, "ENC-1")
    assert rng.bit_generator.state == before


def _via_ed_record(roster, with_roster: bool = True):
    enc = SimpleNamespace(
        encounter_id="ENC-T-1",
        encounter_type="inpatient",
        admit_source="emd",
        severity="moderate",
        admission_datetime=datetime(2024, 6, 1, 14, 0),
        attending_physician_id="DR-CA-002",
        chief_complaint="Chest pain",
        triage_nurse_id="",
        ed_physician_id="",
        triage_data=None,
    )
    record = SimpleNamespace(encounters=[enc], physiological_states=[], condition_event=None, vital_signs=[])
    ctx = SimpleNamespace(
        records=[record],
        config=SimpleNamespace(country="US"),
        master_seed=42,
        roster=roster if with_roster else None,
    )
    return ctx, enc


def test_triage_enricher_assigns_the_ed_physician_of_a_via_ed_stay() -> None:
    roster = _roster()
    ctx, enc = _via_ed_record(roster)
    triage_enricher(ctx)
    assert enc.ed_physician_id.startswith("DR-EM-")
    assert enc.ed_physician_id == assign_ed_physician(roster, "ENC-T-1")
    assert enc.attending_physician_id == "DR-CA-002"  # the admitting specialist keeps the stay


def test_the_ed_note_is_authored_by_the_ed_physician() -> None:
    spec = load_document_type_specs()[DocumentType("ed_note")]
    assert spec.author_role == "ed_physician"
    enc = SimpleNamespace(attending_physician_id="DR-CA-002", ed_physician_id="DR-EM-003")
    assert _pick_document_author(spec, enc) == "DR-EM-003"


def test_the_ed_note_of_an_ed_only_visit_keeps_the_attending() -> None:
    spec = load_document_type_specs()[DocumentType("ed_note")]
    enc = SimpleNamespace(attending_physician_id="DR-EM-002", ed_physician_id="")
    assert _pick_document_author(spec, enc) == "DR-EM-002"


def _ctx(country: str, ed_physician: str, roster_map: dict | None = None) -> BundleContext:
    imp_id = "ENC-000001"
    encounters = [
        {
            "encounter_id": imp_id,
            "encounter_type": "inpatient",
            "status": "completed",
            "admission_datetime": "2026-01-15T10:00:00",
            "discharge_datetime": "2026-01-20T14:00:00",
            "admit_source": "emd",
            "admit_source_encounter_id": f"{imp_id}-ED",
            "attending_physician_id": "DR-CA-002",
            "ed_physician_id": ed_physician,
            "chief_complaint": "Chest pain",
        }
    ]
    return BundleContext(
        record={"encounters": encounters, "orders": []},
        country=country,
        roster_map=roster_map or {},
        hospital_config={},
        patient_data={"chronic_conditions": []},
        patient_id="POP-000001",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id=imp_id,
        patient_sex="M",
    )


def _attender(resource: dict) -> str:
    [attender] = [p for p in resource["participant"] if p["type"][0]["coding"][0]["code"] == "ATND"]
    return attender["individual"]["reference"]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_bridge_encounter_names_the_ed_physician_and_the_stay_keeps_the_specialist(country: str) -> None:
    resources = _bb_encounters(_ctx(country, "DR-EM-003"))
    bridge = next(r for r in resources if r["class"]["code"] == "EMER")
    stay = next(r for r in resources if r["class"]["code"] == "IMP")
    assert _attender(bridge).endswith("DR-EM-003")
    assert _attender(stay).endswith("DR-CA-002")


def test_bridge_encounter_of_an_older_record_falls_back_to_the_attending() -> None:
    bridge = next(r for r in _bb_encounters(_ctx("US", "")) if r["class"]["code"] == "EMER")
    assert _attender(bridge).endswith("DR-CA-002")


def test_the_ed_physician_has_a_practitioner_resource() -> None:
    roster_map = {
        sid: {"staff_id": sid, "role": "physician", "name": sid, "department": "x", "specialty": "x"}
        for sid in ("DR-CA-002", "DR-EM-003")
    }
    ctx = _ctx("US", "DR-EM-003", roster_map)
    ctx.record["encounters"][0]["attending_physician_id"] = "DR-CA-002"
    emitted = {r["identifier"][0]["value"] for r in _bb_practitioners(ctx) if r["resourceType"] == "Practitioner"}
    assert any("DR-EM-003" in v for v in emitted)
