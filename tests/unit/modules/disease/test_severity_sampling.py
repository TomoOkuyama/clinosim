"""FP-SEV-MODEL Task 3: sample_severity + shared categorical primitive."""

from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.disease.severity import (
    SEVERITY_SCORE_RANGES,
    category_from_score,
    sample_severity,
    sample_severity_category,
)

pytestmark = pytest.mark.unit


def _person(**kw):
    base = dict(
        age=60,
        sex="M",
        chronic_conditions=[],
        current_medications=[],
        bmi=22.0,
        smoking_status="never",
        alcohol_use="none",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _protocol(distribution, modifiers=None, minimum=None):
    sev = {"distribution": distribution}
    if modifiers is not None:
        sev["modifiers"] = modifiers
    return SimpleNamespace(severity=sev, minimum_severity=minimum)


def test_category_follows_distribution():
    rng = np.random.default_rng(42)
    dist = {"mild": 0.0, "moderate": 1.0, "severe": 0.0}
    cats = [sample_severity_category(dist, [], _person(), rng, None) for _ in range(200)]
    assert set(cats) == {"moderate"}


def test_minimum_clamp_excludes_below():
    rng = np.random.default_rng(1)
    dist = {"mild": 0.9, "moderate": 0.1, "severe": 0.0}
    cats = [sample_severity_category(dist, [], _person(), rng, "moderate") for _ in range(200)]
    assert "mild" not in cats


def test_modifier_raises_severe_rate():
    dist = {"mild": 0.2, "moderate": 0.6, "severe": 0.2}
    mods = [{"condition": "age_over_75", "severe_multiplier": 3.0}]
    rng = np.random.default_rng(7)
    young = [sample_severity_category(dist, mods, _person(age=50), rng, None) for _ in range(500)]
    rng = np.random.default_rng(7)
    elderly = [sample_severity_category(dist, mods, _person(age=80), rng, None) for _ in range(500)]
    assert elderly.count("severe") > young.count("severe")


def test_sample_severity_score_within_category_range():
    rng = np.random.default_rng(3)
    proto = _protocol({"mild": 0.34, "moderate": 0.33, "severe": 0.33})
    for _ in range(300):
        cat, score = sample_severity(proto, _person(), rng)
        lo, hi = SEVERITY_SCORE_RANGES[cat]
        assert lo <= score <= hi
        assert category_from_score(score) == cat


def test_sample_severity_deterministic():
    p = _protocol({"mild": 0.34, "moderate": 0.33, "severe": 0.33})
    a = sample_severity(p, _person(), np.random.default_rng(99))
    b = sample_severity(p, _person(), np.random.default_rng(99))
    assert a == b
