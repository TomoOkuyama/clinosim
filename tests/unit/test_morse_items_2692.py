"""Issue #2692: the six Morse items are scored and the total is their sum."""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.observation.nursing import compute_morse_fall_risk

pytestmark = pytest.mark.unit

_ITEM_VALUES = {
    "morse_history": {0, 25},
    "morse_secondary_dx": {0, 15},
    "morse_ambulatory_aid": {0, 15, 30},
    "morse_iv": {0, 20},
    "morse_gait": {0, 10, 20},
    "morse_mental": {0, 15},
}


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize("mobility", [0, 5, 10, 15])
def test_the_total_is_the_sum_of_valid_items(seed: int, mobility: int) -> None:
    adl = {"barthel_score": 55, "mobility": mobility}
    total, _level, items = compute_morse_fall_risk(
        80, adl, "V", True, np.random.default_rng(seed), has_secondary_diagnosis=True
    )
    assert set(items) == set(_ITEM_VALUES)
    assert all(items[k] in allowed for k, allowed in _ITEM_VALUES.items())
    assert total == sum(items.values()) and total % 5 == 0


def test_secondary_diagnosis_and_ambulatory_aid_are_scored() -> None:
    _t, _l, items = compute_morse_fall_risk(
        50, {"barthel_score": 100, "mobility": 10}, "A", False, np.random.default_rng(0), has_secondary_diagnosis=True
    )
    assert items["morse_secondary_dx"] == 15 and items["morse_ambulatory_aid"] == 15


def test_the_stream_is_consumed_as_before() -> None:
    a, b = np.random.default_rng(3), np.random.default_rng(3)
    compute_morse_fall_risk(70, {"barthel_score": 80}, "A", False, a)
    b.integers(-5, 5, endpoint=True)
    assert a.random() == b.random()


def test_fall_history_follows_the_age_banded_share() -> None:
    from clinosim.modules.observation.nursing import morse_fall_history
    from clinosim.seeding import morse_fall_history_unit

    share = sum(morse_fall_history(80, morse_fall_history_unit(f"P{i}", "E")) for i in range(4000)) / 4000
    assert 0.27 < share < 0.33
    assert morse_fall_history_unit("P1", "E1") == morse_fall_history_unit("P1", "E1")
