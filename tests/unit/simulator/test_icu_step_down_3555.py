"""The ICU exit of a stay (Issue #3555): derived from the recorded days of
ICU-level support, deterministic, never for a death."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.simulator import daily_loop as dl
from clinosim.simulator.icu_step_down import day_has_icu_support, step_down_day
from clinosim.simulator.oxygen_course import OxygenCourse
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import Order, OrderStatus, OrderType, VitalSignRecord

pytestmark = pytest.mark.unit

_QUIET = dict(
    physiology_needs_icu=False,
    ventilated=False,
    vasoactive_infusion=False,
    consciousness_levels=["A", "A"],
    oxygen_flows_lpm=[2.0],
    icu_complication=False,
)


@pytest.mark.parametrize(
    "override",
    [
        {"physiology_needs_icu": True},
        {"ventilated": True},
        {"vasoactive_infusion": True},
        {"consciousness_levels": ["A", "P"]},
        {"oxygen_flows_lpm": [2.0, 8.0]},
        {"icu_complication": True},
    ],
)
def test_each_criterion_alone_is_icu_support(override: dict) -> None:
    assert day_has_icu_support(**{**_QUIET, **override})


def test_an_unrecorded_consciousness_level_is_not_support() -> None:
    assert not day_has_icu_support(**{**_QUIET, "consciousness_levels": ["", "A"]})


def test_a_quiet_day_has_no_icu_support() -> None:
    assert not day_has_icu_support(**_QUIET)
    assert not day_has_icu_support(**{**_QUIET, "consciousness_levels": ["A", "V"], "oxygen_flows_lpm": []})


def test_first_day_after_which_support_stays_absent() -> None:
    # transfer day 1; support on days 1 and 2, none from day 3; 8 hospital days
    support = [False, True, True, False, False, False, False, False]
    assert step_down_day(1, support, 8, died=False) == (3, "criteria")


def test_support_returning_later_delays_the_step_down() -> None:
    support = [True, False, False, True, False, False, False, False]
    # day 1 and 2 are quiet but day 3 has support again: not before day 4
    assert step_down_day(0, support, 8, died=False) == (4, "criteria")


def test_min_icu_stay_of_one_full_day() -> None:
    support = [False] * 8
    assert step_down_day(2, support, 8, died=False) == (3, "criteria")


def test_criteria_never_met_steps_down_the_day_before_discharge() -> None:
    support = [True] * 7 + [False]
    assert step_down_day(0, support, 8, died=False) == (6, "before_discharge")


def test_stay_too_short_has_no_step_down() -> None:
    # transfer on the last or second-to-last day: nothing left for a ward stay
    assert step_down_day(5, [True] * 6, 6, died=False) == (None, "")
    assert step_down_day(4, [True] * 6, 6, died=False) == (None, "")
    assert step_down_day(3, [True] * 6, 6, died=False) == (4, "before_discharge")


def test_step_down_is_never_on_the_discharge_day() -> None:
    day, _ = step_down_day(0, [False] * 5, 5, died=False)
    assert day is not None and day <= 3


def test_death_keeps_the_icu() -> None:
    assert step_down_day(0, [False] * 8, 8, died=True) == (None, "")


def test_no_transfer_no_step_down() -> None:
    assert step_down_day(-1, [False] * 8, 8, died=False) == (None, "")


# -- the daily loop's record of a day's ICU-level support ---------------------

_ADMIT = datetime(2026, 6, 18, 9, 0)


def _run(**kw) -> SimpleNamespace:
    base = dict(
        state=PhysiologicalState(),
        oxygen=OxygenCourse(),
        orders=[],
        vitals=[],
        icu_support=[],
        icu_trigger_days=set(),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _record(run: SimpleNamespace, day: int) -> bool:
    dl._record_icu_support(SimpleNamespace(admission_time=_ADMIT), run, day)
    return run.icu_support[-1]


def _vital(day: int, **kw) -> VitalSignRecord:
    return VitalSignRecord(timestamp=_ADMIT + timedelta(days=day, hours=3), heart_rate=80, **kw)


def test_a_quiet_ward_level_day_is_recorded_without_support() -> None:
    run = _run(vitals=[_vital(1, consciousness_level="A", oxygen_flow_rate_lpm=2.0)])
    assert _record(run, 1) is False


def test_ventilation_that_day_is_support_even_when_extubated_at_the_next_day_start() -> None:
    run = _run()
    run.oxygen.start_ventilation(_ADMIT + timedelta(days=1, hours=1))
    run.oxygen.end_ventilation(_ADMIT.replace(hour=0) + timedelta(days=2))
    assert _record(run, 1) is True
    assert _record(run, 2) is False


def test_a_reading_with_reduced_consciousness_or_high_flow_is_support() -> None:
    assert _record(_run(vitals=[_vital(0, consciousness_level="P")]), 0) is True
    assert _record(_run(vitals=[_vital(0, consciousness_level="A", oxygen_flow_rate_lpm=8.5)]), 0) is True


def test_an_icu_complication_that_day_is_support() -> None:
    assert _record(_run(icu_trigger_days={3}), 3) is True
    assert _record(_run(icu_trigger_days={3}), 4) is False


def test_a_running_vasopressor_infusion_is_support_until_it_is_stopped() -> None:
    from clinosim.simulator.vasoactive_support import vasoactive_infusion_during

    day1 = _ADMIT.replace(hour=0) + timedelta(days=1)
    drip = Order(
        order_id="O1",
        encounter_id="E",
        patient_id="P",
        order_type=OrderType.MEDICATION,
        display_name="Norepinephrine",
        drug_id="norepinephrine",
        frequency="continuous",
        ordered_datetime=day1 + timedelta(hours=2),
        status=OrderStatus.PLACED,
    )
    assert vasoactive_infusion_during([drip], day1, day1 + timedelta(days=1))
    assert not vasoactive_infusion_during([drip], day1 - timedelta(days=1), day1)  # not yet ordered
    drip.status, drip.end_datetime = OrderStatus.STOPPED, day1 + timedelta(days=1)
    assert vasoactive_infusion_during([drip], day1, day1 + timedelta(days=1))
    assert not vasoactive_infusion_during([drip], day1 + timedelta(days=1), day1 + timedelta(days=2))


def test_oxygen_flow_below_the_non_rebreather_level_is_ward_level() -> None:
    assert not day_has_icu_support(**{**_QUIET, "oxygen_flows_lpm": [2.0, 6.0, 7.5]})
    assert day_has_icu_support(**{**_QUIET, "oxygen_flows_lpm": [8.0]})
