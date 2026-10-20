"""Event pattern `step` unit tests (Phase 3 Task 1)."""

from __future__ import annotations

import numpy as np

from clinosim.modules.longitudinal.patterns.event import EventSpec, step
from clinosim.modules.longitudinal.snapshot import YearSnapshot


def test_step_fires_at_base_rate():
    spec = EventSpec(
        event_name="x",
        emits_icd="E11.21",
        base_annual_rate=1.0,
        rate_modifiers=[],
        one_shot=True,
    )
    rng = np.random.default_rng(0)
    result = step([], [], rng, spec, context={})
    assert result.fired
    assert result.emits_icd == "E11.21"


def test_step_zero_rate_never_fires():
    spec = EventSpec(
        event_name="x",
        emits_icd="E11.21",
        base_annual_rate=0.0,
        rate_modifiers=[],
        one_shot=True,
    )
    rng = np.random.default_rng(0)
    for _ in range(100):
        assert not step([], [], rng, spec, context={}).fired


def test_step_one_shot_guard_against_chronic():
    """Review Focus #1 + #3: emits_icd already in person_chronic → never re-fires."""
    spec = EventSpec(
        event_name="x",
        emits_icd="E11.21",
        base_annual_rate=1.0,
        rate_modifiers=[],
        one_shot=True,
    )
    rng = np.random.default_rng(0)
    result = step(["E11.21"], [], rng, spec, context={})
    assert not result.fired


def test_step_one_shot_guard_against_prior_new_complications():
    spec = EventSpec(
        event_name="x",
        emits_icd="E11.21",
        base_annual_rate=1.0,
        rate_modifiers=[],
        one_shot=True,
    )
    rng = np.random.default_rng(0)
    prior = [YearSnapshot(year=2024, new_complications=["E11.21"])]
    result = step([], prior, rng, spec, context={})
    assert not result.fired


def test_step_rate_modifier_multiplies():
    spec = EventSpec(
        event_name="x",
        emits_icd="E11.21",
        base_annual_rate=0.1,
        rate_modifiers=[{"when": {"attribute": "hba1c", "operator": ">", "value": 9.0}, "factor": 3.0}],
        one_shot=True,
    )
    hits = 0
    for seed in range(2000):
        rng = np.random.default_rng(seed)
        r = step([], [], rng, spec, context={"continuous": {"hba1c": 10.0}})
        if r.fired:
            hits += 1
    rate = hits / 2000
    assert 0.26 < rate < 0.34, f"3.0 * 0.1 = 0.3 expected, got {rate:.3f}"


def test_step_rate_modifier_absent_latent_ignored():
    """Review Focus #2: context has no continuous["hba1c"] (non-DM person)
    → modifier is a no-op, base rate applies."""
    spec = EventSpec(
        event_name="x",
        emits_icd="E11.21",
        base_annual_rate=0.1,
        rate_modifiers=[{"when": {"attribute": "hba1c", "operator": ">", "value": 9.0}, "factor": 3.0}],
        one_shot=True,
    )
    hits = 0
    for seed in range(2000):
        rng = np.random.default_rng(seed)
        r = step([], [], rng, spec, context={"continuous": {}})
        if r.fired:
            hits += 1
    rate = hits / 2000
    assert 0.08 < rate < 0.12, f"base 0.1 expected under absent-latent, got {rate:.3f}"


def test_step_rate_clamp_to_one():
    """Compounded modifiers past 1.0 clamp at 1.0 → always fire."""
    spec = EventSpec(
        event_name="x",
        emits_icd="E11.21",
        base_annual_rate=0.5,
        rate_modifiers=[{"when": {"attribute": "hba1c", "operator": ">", "value": 9.0}, "factor": 3.0}],
        one_shot=True,
    )
    rng = np.random.default_rng(0)
    for _ in range(50):
        r = step([], [], rng, spec, context={"continuous": {"hba1c": 10.0}})
        assert r.fired
