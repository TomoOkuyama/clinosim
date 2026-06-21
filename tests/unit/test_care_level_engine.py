import numpy as np
import pytest

from clinosim.modules.care_level.engine import assign_care_level

pytestmark = pytest.mark.unit
_LEVELS = {"", "support1", "support2", "care1", "care2", "care3", "care4", "care5"}


def _certified_rate(age, n=600):
    return sum(assign_care_level(age, "JP", np.random.default_rng(s)) != "" for s in range(n)) / n


def test_returns_valid_or_empty():
    assert assign_care_level(85, "JP", np.random.default_rng(1)) in _LEVELS


def test_deterministic():
    a = assign_care_level(85, "JP", np.random.default_rng(3))
    b = assign_care_level(85, "JP", np.random.default_rng(3))
    assert a == b


def test_elderly_more_certified_than_young():
    assert _certified_rate(88) > _certified_rate(50)


def test_non_jp_never_certified():
    assert all(assign_care_level(88, "US", np.random.default_rng(s)) == "" for s in range(50))
