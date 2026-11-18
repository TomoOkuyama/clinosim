"""Issue #3263: no encounter contradicts a chronic condition's onset. A
condition an earlier encounter did not list is not dated before that encounter:
its onset moves to the day after the last such encounter (first documented
later), and a condition no earlier encounter contradicts keeps its onset."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.simulator.chronic_reconcile import reconcile_chronic_onsets
from clinosim.types.patient import ChronicCondition

pytestmark = pytest.mark.unit


def _rec(pid: str, when: datetime, conds: dict[str, date]) -> SimpleNamespace:
    return SimpleNamespace(
        patient=SimpleNamespace(
            patient_id=pid,
            chronic_conditions=[ChronicCondition(code=c, onset_date=o) for c, o in conds.items()],
        ),
        encounters=[SimpleNamespace(admission_datetime=when)],
    )


def _onsets(rec: SimpleNamespace) -> dict[str, date]:
    return {c.code: c.onset_date for c in rec.patient.chronic_conditions}


def test_onset_before_an_earlier_encounter_that_lacked_the_condition_moves_after_it() -> None:
    early = _rec("P", datetime(2024, 11, 30, 9), {"E78": date(2010, 1, 1)})
    late = _rec("P", datetime(2025, 2, 3, 9), {"E78": date(2010, 1, 1), "I10": date(2024, 4, 18)})
    later = _rec("P", datetime(2025, 5, 5, 9), {"E78": date(2010, 1, 1), "I10": date(2024, 4, 18)})
    reconcile_chronic_onsets([later, early, late])
    assert _onsets(late)["I10"] == date(2024, 12, 1)
    assert _onsets(later)["I10"] == date(2024, 12, 1)
    assert _onsets(late)["E78"] == date(2010, 1, 1)


def test_a_condition_no_earlier_encounter_contradicts_keeps_its_onset() -> None:
    early = _rec("P", datetime(2024, 11, 30, 9), {"I10": date(2020, 1, 1)})
    late = _rec("P", datetime(2025, 2, 3, 9), {"I10": date(2020, 1, 1)})
    reconcile_chronic_onsets([early, late])
    assert _onsets(early)["I10"] == _onsets(late)["I10"] == date(2020, 1, 1)


def test_the_onset_never_passes_the_first_encounter_that_lists_it() -> None:
    early = _rec("P", datetime(2025, 1, 10, 9), {})
    late = _rec("P", datetime(2025, 1, 10, 15), {"I10": date(2020, 1, 1)})
    reconcile_chronic_onsets([early, late])
    assert _onsets(late)["I10"] == date(2025, 1, 10)


def test_patients_are_reconciled_separately() -> None:
    a = _rec("A", datetime(2025, 1, 1, 9), {})
    b = _rec("B", datetime(2025, 6, 1, 9), {"I10": date(2020, 1, 1)})
    reconcile_chronic_onsets([a, b])
    assert _onsets(b)["I10"] == date(2020, 1, 1)
