"""Issue #2996: a calendar clinic visit is not held while the patient is admitted.

A visit dated inside an inpatient stay moves to the same clock time on the
day after discharge; it is dropped when the patient is still admitted at the
snapshot or the move would take it into the next calendar year.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.simulator._dispatch import InpatientStayIndex
from clinosim.simulator.phases._healthcare_calendar import dispatch_calendar_event, visit_time_outside_stays
from clinosim.types.encounter import EncounterType
from clinosim.types.population import LifeEvent

pytestmark = pytest.mark.unit


def _stay(pid: str, admit: datetime, discharge: datetime | None) -> SimpleNamespace:
    return SimpleNamespace(
        patient=SimpleNamespace(patient_id=pid),
        encounters=[
            SimpleNamespace(
                encounter_type=EncounterType.INPATIENT, admission_datetime=admit, discharge_datetime=discharge
            )
        ],
    )


def _outpatient(pid: str, at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        patient=SimpleNamespace(patient_id=pid),
        encounters=[SimpleNamespace(encounter_type=EncounterType.OUTPATIENT, admission_datetime=at)],
    )


def test_a_follow_up_dated_inside_a_stay_is_moved_after_discharge() -> None:
    records = [_stay("P1", datetime(2026, 1, 20, 14, 0), datetime(2026, 1, 27, 11, 0))]
    index = InpatientStayIndex()
    moved = visit_time_outside_stays(index, records, "P1", datetime(2026, 1, 26, 10, 43))
    assert moved == datetime(2026, 1, 28, 10, 43)


def test_a_visit_outside_any_stay_keeps_its_time() -> None:
    records = [
        _stay("P1", datetime(2026, 1, 20, 14, 0), datetime(2026, 1, 27, 11, 0)),
        _stay("P2", datetime(2026, 2, 1, 8, 0), datetime(2026, 2, 9, 11, 0)),
        _outpatient("P1", datetime(2026, 2, 3, 10, 0)),
    ]
    index = InpatientStayIndex()
    for when in (datetime(2026, 1, 20, 10, 0), datetime(2026, 1, 27, 11, 0), datetime(2026, 2, 3, 10, 0)):
        assert visit_time_outside_stays(index, records, "P1", when) == when


def test_back_to_back_stays_push_the_visit_past_both() -> None:
    records = [
        _stay("P1", datetime(2026, 3, 1, 9, 0), datetime(2026, 3, 5, 10, 0)),
        _stay("P1", datetime(2026, 3, 6, 7, 0), datetime(2026, 3, 12, 10, 0)),
    ]
    assert visit_time_outside_stays(InpatientStayIndex(), records, "P1", datetime(2026, 3, 3, 10, 30)) == datetime(
        2026, 3, 13, 10, 30
    )


def test_still_admitted_at_the_snapshot_drops_the_visit() -> None:
    records = [_stay("P1", datetime(2026, 10, 20, 9, 0), None)]
    assert visit_time_outside_stays(InpatientStayIndex(), records, "P1", datetime(2026, 10, 25, 10, 0)) is None


def test_the_index_sees_records_appended_after_it_was_built() -> None:
    records: list = []
    index = InpatientStayIndex()
    assert visit_time_outside_stays(index, records, "P1", datetime(2026, 5, 2, 10, 0)) == datetime(2026, 5, 2, 10, 0)
    records.append(_stay("P1", datetime(2026, 5, 1, 9, 0), datetime(2026, 5, 4, 10, 0)))
    assert visit_time_outside_stays(index, records, "P1", datetime(2026, 5, 2, 10, 0)) == datetime(2026, 5, 5, 10, 0)


class _Person:
    person_id = "P1"

    def in_population_at(self, when) -> bool:
        return True


def _ctx(records: list) -> SimpleNamespace:
    return SimpleNamespace(
        population=SimpleNamespace(get_person=lambda pid: _Person()),
        patient_records=records,
        inpatient_stays=InpatientStayIndex(),
        outpatient_day_ends={},
        master_seed=42,
        config=SimpleNamespace(country="US"),
    )


def test_dispatch_postpones_a_visit_inside_a_stay_without_simulating_it() -> None:
    records = [_stay("P1", datetime(2026, 6, 10, 9, 0), datetime(2026, 6, 15, 10, 0))]
    event = LifeEvent(person_id="P1", event_type="chronic_visit", timestamp=date(2026, 6, 12), disease_id="I10")
    postponed = dispatch_calendar_event(event, _ctx(records))
    assert postponed is not None and postponed.date() == date(2026, 6, 16)
    assert len(records) == 1


def test_dispatch_drops_a_visit_the_stay_pushes_into_next_year() -> None:
    records = [_stay("P1", datetime(2026, 12, 20, 9, 0), datetime(2026, 12, 31, 10, 0))]
    event = LifeEvent(person_id="P1", event_type="chronic_visit", timestamp=date(2026, 12, 28), disease_id="I10")
    assert dispatch_calendar_event(event, _ctx(records)) is None
    assert len(records) == 1


def test_a_post_discharge_follow_up_inside_a_readmission_is_not_held() -> None:
    from clinosim.simulator.phases._post_discharge import dispatch_post_discharge

    index_stay = _stay("P1", datetime(2026, 4, 1, 9, 0), datetime(2026, 4, 6, 10, 0))
    readmission = _stay("P1", datetime(2026, 4, 15, 8, 0), datetime(2026, 4, 25, 10, 0))
    records = [index_stay, readmission]
    dispatch_post_discharge(index_stay, datetime(2026, 4, 20, 10, 0), _ctx(records))  # type: ignore[arg-type]
    assert records == [index_stay, readmission]
