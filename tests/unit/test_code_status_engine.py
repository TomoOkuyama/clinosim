import numpy as np
import pytest

from clinosim.modules.code_status.engine import assign_code_status, load_reference

pytestmark = pytest.mark.unit
_TIERS = {t["key"]: t["snomed"] for t in load_reference()["tiers"]}
_FULL = _TIERS["full_code"]


def _rate_non_full(age, context, country="US", n=600):
    nf = 0
    for s in range(n):
        if assign_code_status(age, context, country, np.random.default_rng(s)) != _FULL:
            nf += 1
    return nf / n


def test_returns_valid_snomed():
    code = assign_code_status(80, "icu", "US", np.random.default_rng(1))
    assert code in set(_TIERS.values())


def test_deterministic():
    a = assign_code_status(80, "terminal", "US", np.random.default_rng(3))
    b = assign_code_status(80, "terminal", "US", np.random.default_rng(3))
    assert a == b


def test_terminal_more_non_full_than_routine():
    assert _rate_non_full(80, "terminal") > _rate_non_full(80, "routine")


def test_elderly_more_non_full_than_young_routine():
    assert _rate_non_full(90, "routine") > _rate_non_full(30, "routine")


def test_jp_routine_more_full_code_than_us():
    assert _rate_non_full(75, "routine", "JP") < _rate_non_full(75, "routine", "US")
