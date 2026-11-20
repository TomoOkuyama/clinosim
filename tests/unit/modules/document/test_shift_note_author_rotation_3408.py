"""Issue #3408: nursing shift notes are written by the nurse on duty, not all
by the admission's primary nurse."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.document.engine import document_enricher
from clinosim.modules.nursing.engine import load_nursing_shift_rotation, shift_note_author
from clinosim.types.staff import StaffMember, StaffRoster

pytestmark = pytest.mark.unit

ADMISSION_DT = datetime(2026, 7, 1, 10, 0)


def _roster(n: int = 6, ward: str = "W1") -> StaffRoster:
    return StaffRoster(
        members=[
            StaffMember(staff_id=f"NS-{i:03d}", name=f"n{i}", role="nurse", department="IM", ward=ward)
            for i in range(1, n + 1)
        ]
    )


def _run(roster: StaffRoster | None, days: int = 6, enc_id: str = "enc1") -> list:
    enc = SimpleNamespace(
        encounter_id=enc_id,
        encounter_type="inpatient",
        status="completed",
        admission_datetime=ADMISSION_DT,
        discharge_datetime=ADMISSION_DT + timedelta(days=days),
        attending_physician_id="dr1",
        primary_nurse_id="NS-001",
        ward_id="W1",
        department_id="IM",
    )
    record = SimpleNamespace(
        patient=SimpleNamespace(patient_id="pt1", chronic_conditions=[], current_medications=[], allergies=[]),
        encounters=[enc],
        documents=[],
        extensions={},
        physiological_states=[],
    )
    document_enricher(
        SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace(country="us"), roster=roster)
    )
    return record.documents


def _shift_notes(docs: list) -> list:
    return [d for d in docs if d.task_type == "nursing_shift_note"]


def test_multi_day_stay_has_several_authors_and_they_are_ward_nurses() -> None:
    docs = _run(_roster())
    authors = {d.author_practitioner_id for d in _shift_notes(docs)}
    assert len(authors) > 1
    assert authors <= {f"NS-{i:03d}" for i in range(1, 7)}


def test_nurse_works_at_most_one_shift_per_calendar_day() -> None:
    per_day: dict[str, list[str]] = {}
    for d in _shift_notes(_run(_roster())):
        per_day.setdefault(d.period_start[:10], []).append(d.author_practitioner_id)
    assert per_day
    for day, authors in per_day.items():
        assert len(authors) == len(set(authors)), (day, authors)


def test_primary_nurse_keeps_some_but_not_all_day_shifts() -> None:
    day = [d.author_practitioner_id for d in _shift_notes(_run(_roster(), days=20)) if d.shift == "day"]
    share = Counter(day)["NS-001"] / len(day)
    assert 0.2 < share < 0.95
    assert all(d.author_practitioner_id != "NS-001" for d in _shift_notes(_run(_roster(), days=20)) if d.shift != "day")


def test_assessment_and_care_plan_keep_the_primary_nurse() -> None:
    docs = _run(_roster())
    nursing = [d for d in docs if d.task_type == "admission_nursing_assessment"]
    assert nursing and all(d.author_practitioner_id == "NS-001" for d in nursing)


def test_deterministic_for_same_input() -> None:
    a = [d.author_practitioner_id for d in _shift_notes(_run(_roster()))]
    b = [d.author_practitioner_id for d in _shift_notes(_run(_roster()))]
    assert a == b


def test_no_roster_keeps_the_primary_nurse() -> None:
    authors = {d.author_practitioner_id for d in _shift_notes(_run(None))}
    assert authors == {"NS-001"}


def test_single_nurse_ward_falls_back_to_primary() -> None:
    authors = {d.author_practitioner_id for d in _shift_notes(_run(_roster(n=1)))}
    assert authors == {"NS-001"}


def test_helper_draws_nothing_and_is_pure() -> None:
    enc = SimpleNamespace(encounter_id="e", primary_nurse_id="NS-001", ward_id="W1", department_id="IM")
    r = _roster()
    assert shift_note_author(r, enc, "2026-07-02", "night", set()) == shift_note_author(
        r, enc, "2026-07-02", "night", set()
    )


def test_rotation_yaml_loads_with_a_fractional_share() -> None:
    assert 0.0 <= load_nursing_shift_rotation().day_shift_primary_share <= 1.0
