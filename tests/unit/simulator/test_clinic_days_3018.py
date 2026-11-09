"""Issue #3018: scheduled outpatient visits are held on clinic days.

A visit drawn on a closed day (Sunday, a national / federal holiday, JP 年末年始
29 Dec - 3 Jan) moves to the next clinic day; one that would leave its
calendar year moves to the previous clinic day instead. Saturday clinics open.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.locale.clinic_calendar import clinic_visit_day, is_clinic_day

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("country", "drawn", "held"),
    [
        ("JP", date(2024, 1, 1), date(2024, 1, 4)),  # 元日 + 年末年始 -> Thursday 4 Jan
        ("JP", date(2023, 12, 31), date(2023, 12, 28)),  # 年末: the next clinic day is in 2024
        ("JP", date(2024, 5, 3), date(2024, 5, 7)),  # 憲法記念日 .. 振替休日 6 May
        ("JP", date(2024, 3, 17), date(2024, 3, 18)),  # Sunday
        ("JP", date(2024, 3, 16), date(2024, 3, 16)),  # Saturday clinic
        ("JP", date(2024, 3, 19), date(2024, 3, 19)),  # an ordinary Tuesday
        ("US", date(2024, 7, 4), date(2024, 7, 5)),  # Independence Day
        ("US", date(2022, 12, 26), date(2022, 12, 27)),  # Christmas on Sunday, observed Monday
        ("US", date(2024, 11, 28), date(2024, 11, 29)),  # Thanksgiving
        ("US", date(2024, 1, 1), date(2024, 1, 2)),
        ("US", date(2024, 12, 29), date(2024, 12, 30)),  # Sunday
        ("US", date(2024, 12, 30), date(2024, 12, 30)),  # JP closes, US does not
    ],
)
def test_visit_moves_to_a_clinic_day(country: str, drawn: date, held: date) -> None:
    assert clinic_visit_day(drawn, country) == held
    assert is_clinic_day(held, country)


def test_a_follow_up_drawn_on_new_years_day_moves_to_4_january() -> None:
    assert clinic_visit_day(date(2024, 1, 1), "JP") == date(2024, 1, 4)


def test_post_discharge_follow_up_is_on_a_clinic_day() -> None:
    from clinosim.simulator.phases._post_discharge import schedule_post_discharge

    discharge = datetime(2023, 12, 17, 10, 30)  # + 14 days = Sunday 31 Dec
    enc = SimpleNamespace(discharge_datetime=discharge)
    record = SimpleNamespace(deceased=False, encounters=[enc])
    ctx = SimpleNamespace(followup_data={}, config=SimpleNamespace(country="JP"))
    when = schedule_post_discharge(record, ctx)
    assert when == datetime(2024, 1, 4, 10, 30)


def test_an_orphan_vaccination_due_on_a_sunday_is_given_on_monday(monkeypatch) -> None:
    from clinosim.modules.immunization.enricher import enrich_immunizations
    from clinosim.types.encounter import ImmunizationRecord
    from tests.unit.modules.immunization.test_companion_vaccination_encounter import (
        _mk_record,
        _StubConfig,
        _StubCtx,
    )

    monkeypatch.setattr(
        "clinosim.modules.immunization.enricher.generate_immunizations",
        lambda *_a, **_k: [ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 3, 15))],
    )
    monkeypatch.setattr("clinosim.modules.immunization.enricher.load_schedule", lambda country: {})
    ctx = _StubCtx()
    ctx.config = _StubConfig(country="US", time_range=("2025-09-08", "2026-09-07"))
    ctx.records = [_mk_record("pt-x", [])]
    enrich_immunizations(ctx)
    [imm] = ctx.records[0].immunizations
    [enc] = [e for e in ctx.records[0].encounters if e.encounter_id == imm.encounter_id]
    assert imm.occurrence_date == date(2026, 3, 16)
    assert enc.admission_datetime.date() == date(2026, 3, 16)


def test_a_vaccination_due_on_the_closed_last_day_moves_back() -> None:
    from clinosim.modules.immunization.enricher import _clinic_day_within

    # 2026-11-01 is a Sunday and the record's as-of date: the previous clinic day.
    assert _clinic_day_within(date(2026, 11, 1), "US", date(2025, 11, 1), date(2026, 11, 1)) == date(2026, 10, 31)
