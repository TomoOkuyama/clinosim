"""A baby's daily bilirubin readings are one trajectory: a per-baby level plus
a small day-to-day variation, so consecutive readings do not fall and rise at
random (Issue #3668), while each day's distribution is still the configured
one."""

from __future__ import annotations

import statistics

import pytest

from clinosim.modules.newborn import build_bilirubin_observations
from clinosim.modules.newborn.engine import load_newborn_config
from tests.unit.modules.newborn.test_bilirubin_cchd_ophthalmic import _newborn_record

pytestmark = pytest.mark.unit
_N = 600


def _series(i: int) -> list[float]:
    return [e["value_mg_dl"] for e in build_bilirubin_observations(_newborn_record(f"POP-{i:06d}-BABY"))]


def test_readings_do_not_fall_between_days() -> None:
    worst = 0.0
    for i in range(_N):
        s = _series(i)
        assert len(s) == 3
        worst = max(worst, max(a - b for a, b in zip(s, s[1:], strict=False)))
    assert worst <= 1.0, worst


def test_a_baby_high_on_day_one_stays_high() -> None:
    pairs = [(_series(i)[0], _series(i)[2]) for i in range(_N)]
    d1, d3 = [p[0] for p in pairs], [p[1] for p in pairs]
    assert statistics.correlation(d1, d3) > 0.8


def test_day_marginals_match_the_configuration() -> None:
    cfg = load_newborn_config()["bilirubin"]
    by_day = list(zip(*[_series(i) for i in range(_N)], strict=True))
    for idx, day in enumerate(cfg["schedule_days"]):
        assert statistics.mean(by_day[idx]) == pytest.approx(cfg["mean_by_day"][day], abs=0.35)
        assert statistics.pstdev(by_day[idx]) == pytest.approx(cfg["std_by_day"][day], abs=0.4)


def test_series_is_deterministic_and_independent_of_the_stay_length() -> None:
    assert _series(7) == _series(7)
    short = build_bilirubin_observations(_newborn_record("POP-000007-BABY", los_days=2))
    assert [e["value_mg_dl"] for e in short] == _series(7)[: len(short)]


def test_level_correlation_is_configured() -> None:
    assert 0.9 <= load_newborn_config()["bilirubin"]["level_correlation"] < 1
