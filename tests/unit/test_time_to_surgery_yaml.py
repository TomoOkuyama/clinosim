"""simulate_surgery honours procedure.time_to_surgery from the disease YAML (#2067)."""

from __future__ import annotations

import statistics

import numpy as np
import pytest

from clinosim.modules.procedure.engine import _hours_to_surgery

pytestmark = pytest.mark.unit


def _sample(proc_data: dict, country: str, n: int = 400) -> list[float]:
    rng = np.random.default_rng(1)
    return [_hours_to_surgery(proc_data, country, rng) for _ in range(n)]


def test_yaml_time_to_surgery_is_used_per_country() -> None:
    proc = {"time_to_surgery": {"us": {"mean_hours": 3, "sd_hours": 2}, "japan": {"mean_hours": 4, "sd_hours": 3}}}
    us, jp = _sample(proc, "US"), _sample(proc, "JP")
    assert 2.5 < statistics.median(us) < 4.0 and min(us) >= 1.5
    assert 3.5 < statistics.median(jp) < 5.5 and min(jp) >= 2.0


def test_missing_time_to_surgery_keeps_defaults() -> None:
    us = _sample({}, "US")
    assert 20 < statistics.median(us) < 28 and min(us) >= 6.0


def test_yaml_matching_defaults_is_draw_identical() -> None:
    hip = {"time_to_surgery": {"us": {"mean_hours": 24, "sd_hours": 12}}}
    assert _sample(hip, "US") == _sample({}, "US")
