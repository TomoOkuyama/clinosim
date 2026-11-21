"""The febrile re-check note reports elapsed minutes, including across an hour boundary."""

from datetime import datetime, timedelta

from clinosim.simulator.vitals_pipeline import _febrile_recheck_note


def test_interval_within_hour():
    t = datetime(2025, 1, 1, 10, 10)
    assert _febrile_recheck_note(t, t + timedelta(minutes=35)) == "febrile recheck after 35 min"


def test_interval_across_hour_boundary():
    t = datetime(2025, 1, 1, 10, 50)
    assert _febrile_recheck_note(t, t + timedelta(minutes=37)) == "febrile recheck after 37 min"
