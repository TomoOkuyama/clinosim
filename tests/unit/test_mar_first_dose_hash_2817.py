"""Issue #2817: MAR first-dose delays are hashes of the administration, not
draws from the stay's stream."""

from __future__ import annotations

import pytest

from clinosim.simulator._mar_thresholds import MAR_STAT_FIRST_DOSE_DELAY_MAX_EXCLUSIVE, MAR_STAT_FIRST_DOSE_DELAY_MIN
from clinosim.simulator.medication_pipeline import _first_dose_delay_min

pytestmark = pytest.mark.unit


def test_the_delay_is_deterministic_and_in_range() -> None:
    delays = [_first_dose_delay_min("P1", f"ORD-{i}", "day0") for i in range(2000)]
    assert delays == [_first_dose_delay_min("P1", f"ORD-{i}", "day0") for i in range(2000)]
    assert min(delays) >= MAR_STAT_FIRST_DOSE_DELAY_MIN
    assert max(delays) < MAR_STAT_FIRST_DOSE_DELAY_MAX_EXCLUSIVE
    # spans the range rather than collapsing to one value
    assert len(set(delays)) == MAR_STAT_FIRST_DOSE_DELAY_MAX_EXCLUSIVE - MAR_STAT_FIRST_DOSE_DELAY_MIN


def test_the_kind_of_dose_gives_an_independent_delay() -> None:
    kinds = [tuple(_first_dose_delay_min("P1", f"ORD-{i}", k) for k in ("single", "stat", "day0")) for i in range(200)]
    assert any(len(set(t)) > 1 for t in kinds)


def test_the_mar_draws_nothing_from_the_stay_stream_for_first_doses() -> None:
    import inspect

    from clinosim.simulator import medication_pipeline

    assert "rng.integers(MAR_STAT_FIRST_DOSE_DELAY_MIN" not in inspect.getsource(medication_pipeline._generate_mar)
