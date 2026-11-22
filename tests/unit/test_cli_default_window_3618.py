"""Issue #3618: without --end the simulation window ends yesterday, so the
snapshot day is complete and no generated timestamp lies after generation."""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.simulator.cli_simulate import simulation_window

pytestmark = pytest.mark.unit


def test_default_end_is_the_previous_day():
    start, end = simulation_window(None, None, today=date(2026, 11, 22))
    assert end == date(2026, 11, 21)
    assert start == date(2025, 11, 21)


def test_explicit_end_is_used_as_given():
    start, end = simulation_window(None, "2026-11-22", today=date(2026, 11, 22))
    assert end == date(2026, 11, 22)
    assert start == date(2025, 11, 22)


def test_explicit_start_is_used_as_given():
    start, end = simulation_window("2026-01-01", None, today=date(2026, 11, 22))
    assert (start, end) == (date(2026, 1, 1), date(2026, 11, 21))
