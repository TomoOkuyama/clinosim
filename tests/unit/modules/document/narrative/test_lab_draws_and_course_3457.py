"""One analyte of one blood draw is one value in a progress note (Issue #3457),
and the key-lab course names only a meaningful change (Issue #3455, lab part)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._progress_course import lab_course_lines
from clinosim.modules.document.narrative.lab_timeseries import group_draws, lab_trend, select_notable_labs

pytestmark = pytest.mark.unit

ADMIT = "2026-04-13T08:00:00"


def _lab(name, value, flag, at, unit=""):
    return {"lab_name": name, "value": value, "unit": unit, "flag": flag, "result_datetime": at}


def _ctx(labs, key_labs, *, day, lang="en"):
    return SimpleNamespace(
        target_lang=lang,
        day_index=day,
        lab_results=labs,
        encounter={"admission_datetime": ADMIT},
        disease_protocol=SimpleNamespace(expected_lab_distributions={"admission": dict.fromkeys(key_labs, {})}),
    )


def test_group_draws_splits_on_the_window_from_the_first_row() -> None:
    from datetime import timedelta

    at = datetime(2026, 4, 14, 7, 0)
    rows = [(at, "a"), (at + timedelta(minutes=61), "b"), (at + timedelta(minutes=125), "c")]
    draws = group_draws(rows, timedelta(minutes=120))
    assert [[lab for _, lab in d] for d in draws] == [["a", "b"], ["c"]]


def test_three_potassium_rows_of_one_day_are_one_trend_entry() -> None:
    labs = [
        _lab("K", 4.8, "H", "2026-04-13T08:30:00", "mmol/L"),
        _lab("K", 5.6, "H", "2026-04-14T07:00:00", "mmol/L"),
        _lab("K", 5.1, "H", "2026-04-14T07:20:00", "mmol/L"),
        _lab("K", 5.3, "H", "2026-04-14T07:55:00", "mmol/L"),
    ]
    trend = lab_trend(labs, ADMIT, 1)
    assert len(trend) == 1
    assert trend[0]["prior_value"] == 4.8 and trend[0]["current_value"] == 5.3


def test_prior_of_a_notable_lab_is_never_a_row_of_the_same_draw() -> None:
    labs = [
        _lab("Creatinine", 1.8, "H", "2026-04-13T09:00:00", "mg/dL"),
        _lab("Creatinine", 2.45, "H", "2026-04-14T07:26:00", "mg/dL"),
        _lab("Creatinine", 2.10, "H", "2026-04-14T07:31:00", "mg/dL"),
    ]
    picks = select_notable_labs(labs, ADMIT, 1, as_of=datetime(2026, 4, 14, 12, 0))
    assert len(picks) == 1
    assert picks[0].prior_value == 1.8


def test_identical_sibling_rows_do_not_become_the_prior() -> None:
    labs = [
        _lab("Creatinine", 2.62, "H", "2026-04-15T06:56:00", "mg/dL"),
        _lab("Creatinine", 2.62, "H", "2026-04-15T07:58:00", "mg/dL"),
    ]
    (pick,) = select_notable_labs(labs, ADMIT, 2, as_of=datetime(2026, 4, 15, 12, 0))
    assert pick.prior_value is None


def test_same_draw_rise_is_not_aki() -> None:
    """KDIGO's rise is against an earlier draw, not a sibling row minutes apart."""
    labs = [
        _lab("Creatinine", 1.0, "", "2026-04-14T07:00:00", "mg/dL"),
        _lab("Creatinine", 1.5, "H", "2026-04-14T07:30:00", "mg/dL"),
    ]
    (pick,) = select_notable_labs(labs, ADMIT, 1, as_of=datetime(2026, 4, 14, 12, 0))
    assert pick.finding is None


def test_glucose_106_to_114_is_not_a_course_claim() -> None:
    labs = [
        _lab("Glucose", 106, "", "2026-04-13T09:00:00", "mg/dL"),
        _lab("Glucose", 114, "H", "2026-04-14T07:00:00", "mg/dL"),
    ]
    assert lab_course_lines(_ctx(labs, ["Glucose"], day=1), None) == []


def test_meaningful_change_is_named_once_per_analyte() -> None:
    labs = [
        _lab("Creatinine", 1.8, "H", "2026-04-13T09:00:00", "mg/dL"),
        _lab("Creatinine", 2.45, "H", "2026-04-14T07:26:00", "mg/dL"),
        _lab("Creatinine", 2.10, "H", "2026-04-14T07:31:00", "mg/dL"),
    ]
    (line,) = lab_course_lines(_ctx(labs, ["Creatinine"], day=1), None)
    assert line.count("1.8") == 1 and "→" in line
    assert line.lower().count("creatinine") == 1


def test_relative_threshold_applies_without_an_absolute_rule() -> None:
    small = [
        _lab("CRP", 10.0, "H", "2026-04-13T09:00:00", "mg/dL"),
        _lab("CRP", 8.5, "H", "2026-04-14T07:00:00", "mg/dL"),
    ]
    big = [
        _lab("CRP", 10.0, "H", "2026-04-13T09:00:00", "mg/dL"),
        _lab("CRP", 5.0, "H", "2026-04-14T07:00:00", "mg/dL"),
    ]
    assert lab_course_lines(_ctx(small, ["CRP"], day=1), None) == []
    assert len(lab_course_lines(_ctx(big, ["CRP"], day=1), None)) == 1


def test_dimensionless_unit_leaves_no_stray_separator() -> None:
    labs = [
        _lab("PT_INR", 1.2, "", "2026-04-13T09:00:00", "{INR}"),
        _lab("PT_INR", 2.4, "H", "2026-04-14T07:00:00", "{INR}"),
    ]
    (line,) = lab_course_lines(_ctx(labs, ["PT_INR"], day=1), None)
    assert " ," not in line and " )" not in line
