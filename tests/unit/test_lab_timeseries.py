"""Tests for `clinosim.modules.document.narrative.lab_timeseries`.

The lab_timeseries module transforms raw CIF `lab_results` (list of
LabResult-shaped dicts) + the encounter's `admission_datetime` into
per-day views the narrative renderer consumes. This test suite pins:

1. `day_of_lab` — result_datetime → day-since-admission.
2. `labs_measured_on_day` — subset filter.
3. `latest_by_lab_name` — carry-forward "current state" pivot.
4. `lab_trend` — improving / worsening / stable / initial per lab.

Determinism-critical: the module is pure — no rng, no I/O. Tests can
build lab_results inline.
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.unit


def _lab(name: str, value: float, day_offset_days: int, flag: str = "", hour: int = 6):
    """Build a lab_results-shaped dict for tests.

    day_offset_days is added to the reference admission time
    2026-04-08T00:00 to produce the result_datetime.
    """
    from datetime import timedelta

    adm = datetime(2026, 4, 8, 0, 0, 0)
    dt = adm + timedelta(days=day_offset_days, hours=hour)
    return {
        "lab_name": name,
        "value": value,
        "unit": "mmol/L",
        "flag": flag,
        "result_datetime": dt.isoformat(),
    }


ADM = datetime(2026, 4, 8, 8, 0, 0)


# ---------------------------------------------------------------------------
# day_of_lab
# ---------------------------------------------------------------------------


def test_day_of_lab_admission_day_is_zero():
    from clinosim.modules.document.narrative.lab_timeseries import day_of_lab

    lab = _lab("Glucose", 500.0, day_offset_days=0, hour=10)
    # Admission at 2026-04-08T00:00; lab at 2026-04-08T10:00 → same day
    adm = datetime(2026, 4, 8, 0, 0, 0)
    assert day_of_lab(lab, adm) == 0


def test_day_of_lab_next_day_is_one():
    from clinosim.modules.document.narrative.lab_timeseries import day_of_lab

    adm = datetime(2026, 4, 8, 0, 0, 0)
    lab = _lab("Glucose", 400.0, day_offset_days=1, hour=6)
    assert day_of_lab(lab, adm) == 1


def test_day_of_lab_missing_datetime_returns_none():
    from clinosim.modules.document.narrative.lab_timeseries import day_of_lab

    assert day_of_lab({"lab_name": "X", "value": 1.0}, datetime(2026, 4, 8)) is None


def test_day_of_lab_missing_admission_returns_none():
    from clinosim.modules.document.narrative.lab_timeseries import day_of_lab

    lab = _lab("Glucose", 500.0, day_offset_days=0)
    assert day_of_lab(lab, None) is None


def test_day_of_lab_pre_admission_negative():
    from clinosim.modules.document.narrative.lab_timeseries import day_of_lab

    adm = datetime(2026, 4, 8, 12, 0, 0)
    # Lab at 2026-04-07 (day before admission)
    lab = {"lab_name": "X", "value": 1.0, "result_datetime": "2026-04-07T08:00:00"}
    assert day_of_lab(lab, adm) == -1


# ---------------------------------------------------------------------------
# labs_measured_on_day
# ---------------------------------------------------------------------------


def test_labs_measured_on_day_filters_by_day_index():
    from clinosim.modules.document.narrative.lab_timeseries import labs_measured_on_day

    labs = [
        _lab("Glucose", 518, 0),
        _lab("Glucose", 400, 1),
        _lab("K", 5.8, 0),
        _lab("K", 5.4, 1),
    ]
    adm = datetime(2026, 4, 8, 0, 0, 0)
    today0 = labs_measured_on_day(labs, adm, 0)
    assert len(today0) == 2
    assert {row["value"] for row in today0} == {518, 5.8}
    today1 = labs_measured_on_day(labs, adm, 1)
    assert {row["value"] for row in today1} == {400, 5.4}


def test_labs_measured_on_day_empty_when_none_match():
    from clinosim.modules.document.narrative.lab_timeseries import labs_measured_on_day

    labs = [_lab("Glucose", 500, 0)]
    adm = datetime(2026, 4, 8, 0, 0, 0)
    assert labs_measured_on_day(labs, adm, 5) == []


def test_labs_measured_on_day_skips_labs_without_datetime():
    from clinosim.modules.document.narrative.lab_timeseries import labs_measured_on_day

    labs = [{"lab_name": "X", "value": 1.0}, _lab("Glucose", 500, 0)]
    adm = datetime(2026, 4, 8, 0, 0, 0)
    assert len(labs_measured_on_day(labs, adm, 0)) == 1


# ---------------------------------------------------------------------------
# latest_by_lab_name
# ---------------------------------------------------------------------------


def test_latest_by_lab_name_returns_most_recent_up_to_day():
    from clinosim.modules.document.narrative.lab_timeseries import latest_by_lab_name

    labs = [
        _lab("Glucose", 518, 0, hour=6),
        _lab("Glucose", 400, 0, hour=18),  # same day, later
        _lab("Glucose", 350, 1),
        _lab("Glucose", 300, 2),
    ]
    adm = datetime(2026, 4, 8, 0, 0, 0)
    latest = latest_by_lab_name(labs, adm, up_to_day=1)
    assert latest["Glucose"]["value"] == 350
    latest_day0 = latest_by_lab_name(labs, adm, up_to_day=0)
    # Two day-0 entries, later one wins (18h > 6h)
    assert latest_day0["Glucose"]["value"] == 400


def test_latest_by_lab_name_excludes_future_labs():
    from clinosim.modules.document.narrative.lab_timeseries import latest_by_lab_name

    labs = [_lab("Glucose", 300, 5)]
    adm = datetime(2026, 4, 8, 0, 0, 0)
    # up_to_day=1 → future day-5 lab excluded
    assert latest_by_lab_name(labs, adm, up_to_day=1) == {}


def test_latest_by_lab_name_multi_test():
    from clinosim.modules.document.narrative.lab_timeseries import latest_by_lab_name

    labs = [
        _lab("Glucose", 518, 0),
        _lab("HCO3", 10.1, 0),
        _lab("HCO3", 14.0, 2),
    ]
    adm = datetime(2026, 4, 8, 0, 0, 0)
    latest = latest_by_lab_name(labs, adm, up_to_day=5)
    assert latest["Glucose"]["value"] == 518
    assert latest["HCO3"]["value"] == 14.0


# ---------------------------------------------------------------------------
# lab_trend
# ---------------------------------------------------------------------------


def test_lab_trend_improving_when_flag_normalizes():
    """Glucose day 0 [critical] → day 1 [H] is IMPROVING."""
    from clinosim.modules.document.narrative.lab_timeseries import lab_trend

    labs = [
        _lab("Glucose", 518, 0, flag="critical"),
        _lab("Glucose", 300, 1, flag="H"),
    ]
    adm = datetime(2026, 4, 8, 0, 0, 0)
    trend = lab_trend(labs, adm, day_index=1)
    assert len(trend) == 1
    row = trend[0]
    assert row["name"] == "Glucose"
    assert row["current_value"] == 300
    assert row["prior_value"] == 518
    assert row["direction"] == "improving"


def test_lab_trend_worsening_when_flag_gets_worse():
    """K day 0 normal → day 1 [H] is WORSENING."""
    from clinosim.modules.document.narrative.lab_timeseries import lab_trend

    labs = [
        _lab("K", 4.0, 0, flag=""),
        _lab("K", 5.8, 1, flag="H"),
    ]
    adm = datetime(2026, 4, 8, 0, 0, 0)
    trend = lab_trend(labs, adm, day_index=1)
    assert trend[0]["direction"] == "worsening"


def test_lab_trend_stable_when_flags_equal_and_similar_value():
    from clinosim.modules.document.narrative.lab_timeseries import lab_trend

    labs = [
        _lab("Glucose", 300, 0, flag="H"),
        _lab("Glucose", 310, 1, flag="H"),  # both H, similar magnitude
    ]
    adm = datetime(2026, 4, 8, 0, 0, 0)
    trend = lab_trend(labs, adm, day_index=1)
    assert trend[0]["direction"] == "stable"


def test_lab_trend_initial_when_no_prior():
    """First-ever measurement is INITIAL."""
    from clinosim.modules.document.narrative.lab_timeseries import lab_trend

    labs = [_lab("Glucose", 518, 0, flag="critical")]
    adm = datetime(2026, 4, 8, 0, 0, 0)
    trend = lab_trend(labs, adm, day_index=0)
    assert trend[0]["direction"] == "initial"


def test_lab_trend_only_returns_today_measured_labs():
    """Labs measured on other days are not in today's trend list."""
    from clinosim.modules.document.narrative.lab_timeseries import lab_trend

    labs = [
        _lab("Glucose", 518, 0, flag="critical"),
        _lab("HCO3", 10.1, 0, flag="L"),
    ]
    adm = datetime(2026, 4, 8, 0, 0, 0)
    # On day 1, nothing was measured → empty trend
    assert lab_trend(labs, adm, day_index=1) == []


def test_lab_trend_prior_from_earlier_day():
    """Prior is the CLOSEST earlier measurement, not the first."""
    from clinosim.modules.document.narrative.lab_timeseries import lab_trend

    labs = [
        _lab("Glucose", 500, 0, flag="critical"),
        _lab("Glucose", 300, 2, flag="H"),  # gap on day 1
        _lab("Glucose", 200, 3, flag=""),
    ]
    adm = datetime(2026, 4, 8, 0, 0, 0)
    trend = lab_trend(labs, adm, day_index=3)
    # Prior for day-3's 200 is day-2's 300 (not day-0's 500)
    assert trend[0]["prior_value"] == 300
    assert trend[0]["prior_day"] == 2
    assert trend[0]["direction"] == "improving"
