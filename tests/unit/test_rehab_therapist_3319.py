"""Issue #3319: each rehabilitation session records its roster therapist, the
FHIR Procedure carries it as performer, and the rehabilitation plan names it."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.output.fhir_r4.encounters.care_team import _build_care_team
from clinosim.modules.output.fhir_r4.procedures.rehab_sessions import _bb_rehab_sessions
from clinosim.modules.procedure.engine import generate_rehab_sessions
from clinosim.modules.staff.engine import assign_rehab_therapist, generate_roster
from clinosim.types.staff import StaffMember, StaffRoster
from tests.unit.modules.document.narrative.test_template_generator_rehabilitation_plan import (
    _make_ctx,
    _make_spec,
    _rehab_session,
)

pytestmark = pytest.mark.unit


def _roster() -> StaffRoster:
    return StaffRoster(
        members=[
            StaffMember(staff_id=f"PT-{i:03d}", name=f"PT {i}", role="physical_therapist", department="rehabilitation")
            for i in (1, 2, 3, 4)
        ]
        + [StaffMember(staff_id="OT-001", name="OT 1", role="occupational_therapist", department="rehabilitation")]
    )


def test_assign_is_stable_per_encounter_and_discipline() -> None:
    roster = _roster()
    first = assign_rehab_therapist(roster, "PT", "ENC-1")
    assert first.startswith("PT-")
    assert all(assign_rehab_therapist(roster, "PT", "ENC-1") == first for _ in range(5))
    assert assign_rehab_therapist(roster, "OT", "ENC-1") == "OT-001"
    # Different encounters spread over the physical therapists.
    assert len({assign_rehab_therapist(roster, "PT", f"ENC-{i}") for i in range(40)}) > 1


def test_assign_empty_when_no_therapist_or_unknown_discipline() -> None:
    assert assign_rehab_therapist(StaffRoster(), "PT", "ENC-1") == ""
    assert assign_rehab_therapist(_roster(), "XX", "ENC-1") == ""
    assert assign_rehab_therapist(_roster(), "ST", "ENC-1") == ""


@pytest.mark.parametrize("country", ["US", "JP"])
def test_generated_roster_has_therapists_and_sessions_record_one(country: str) -> None:
    roster = generate_roster({"departments": ["orthopedics", "rehabilitation"]}, country, np.random.default_rng(1))
    therapist = assign_rehab_therapist(roster, "PT", "ENC-9")
    assert roster.get_by_id(therapist).role == "physical_therapist"
    sessions = generate_rehab_sessions(
        "P1", "ENC-9", datetime(2024, 6, 17, 10, 0), 12, np.random.default_rng(2), country, therapist_id=therapist
    )
    assert sessions and {s.therapist_id for s in sessions} == {therapist}


def test_therapist_does_not_consume_rng() -> None:
    args = ("P1", "ENC-9", datetime(2024, 6, 17, 10, 0), 12)
    a = generate_rehab_sessions(*args, np.random.default_rng(2), "JP")
    b = generate_rehab_sessions(*args, np.random.default_rng(2), "JP", therapist_id="PT-001")
    assert [(s.activities, s.pain_score, s.day_post_op) for s in a] == [
        (s.activities, s.pain_score, s.day_post_op) for s in b
    ]


def test_session_therapist_is_the_care_team_therapist() -> None:
    roster = _roster()
    ids = [m.staff_id for m in roster.members]
    enc = {"encounter_id": "ENC-5", "encounter_type": "inpatient", "attending_physician_id": "DR-1"}
    pools = {
        "physical_therapist": [i for i in ids if i.startswith("PT")],
        "occupational_therapist": [],
    }
    team = _build_care_team(enc, "P1", "en", None, "US", pools)
    members = [p["member"]["reference"] for p in team["participant"]]
    assert f"Practitioner/{assign_rehab_therapist(roster, 'PT', 'ENC-5')}" in members


def _ctx(country: str):
    session = {
        "session_id": "REHAB-P1-001",
        "patient_id": "P1",
        "encounter_id": "ENC-5",
        "therapy_type": "PT",
        "therapist_id": "PT-002",
        "session_date": "2024-06-18T09:00:00",
        "duration_minutes": 30,
        "patient_participation": "good",
    }
    declined = {**session, "session_id": "REHAB-P1-002", "patient_participation": "refused", "therapist_id": ""}
    return SimpleNamespace(
        record={
            "rehab_sessions": [session, declined],
            "encounters": [{"encounter_id": "ENC-5"}],
            "diagnoses": [],
        },
        country=country,
        patient_id="P1",
        roster_map={},
        hospital_config={},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="",
        patient_sex="M",
    )


@pytest.mark.parametrize(("country", "ja"), [("US", False), ("JP", True)])
def test_fhir_procedure_carries_therapist_performer(country: str, ja: bool) -> None:
    done, not_done = _bb_rehab_sessions(_ctx(country))
    assert done["status"] == "completed"
    assert done["code"]["coding"][0]["code"] == "91251008"
    assert done["performedPeriod"] == {
        "start": done["performedPeriod"]["start"],
        "end": done["performedPeriod"]["end"],
    }
    performer = done["performer"][0]
    assert performer["actor"] == {"reference": "Practitioner/PT-002"}
    assert performer["function"]["coding"][0]["code"] == "36682004"
    assert ("理学療法" in done["code"]["text"]) is ja
    # No therapist recorded: no performer is invented; a refusal is not-done.
    assert "performer" not in not_done
    assert not_done["status"] == "not-done"
    assert not_done["statusReason"]["text"]


def _plan_text(sessions, roster_map, lang: str) -> str:
    ctx = _make_ctx(rehab_sessions=sessions, target_lang=lang, locale="jp" if lang == "ja" else "us")
    ctx.roster_map = roster_map
    return TemplateNarrativeGenerator().generate(ctx, _make_spec()).sections["rehab_team"]


def test_rehab_plan_names_the_therapist() -> None:
    roster_map = {"PT-002": {"name": "山田 花子", "role": "physical_therapist"}}
    sessions = [{**_rehab_session(), "therapist_id": "PT-002"}]
    text = _plan_text(sessions, roster_map, "ja")
    assert "山田 花子" in text and "担当者未定" not in text
    assert "Named therapist: Hanako" in _plan_text(sessions, {"PT-002": {"name": "Hanako"}}, "en")
    # No recorded therapist: still "not yet assigned", never an invented name.
    assert "担当者未定" in _plan_text([_rehab_session()], roster_map, "ja")
