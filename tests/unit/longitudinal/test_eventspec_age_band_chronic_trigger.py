"""Phase 4b.2.α — EventSpec schema extensions:

* ``base_rate_by_age_band``: ``[AgeBandRate(age_lo, age_hi, rate)]`` list.
  When populated, ``step()`` picks the band's rate using ``context["age"]``
  instead of the scalar ``base_annual_rate``.
* ``RateModifierWhen.has_chronic``: alternative trigger to
  ``attribute + operator + value``. Fires when the person carries ANY of
  the listed chronic codes (available via ``context["chronic_conditions"]``).

These extensions prepare the migration of ``_annual_chronic_onset``
(aging pass) into the longitudinal engine's event pattern (Phase 4b.2.β),
where every ICD gains an event yaml with age-band incidence + optional
somatic-comorbidity multipliers (replacing today's
``_mental_health_onset_multiplier`` Python helper).

No existing event yamls use the new fields in this PR, so Phase 3 / 4a /
4b.1 cohorts stay byte-identical.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.patterns.event import (
    AgeBandRate,
    EventSpec,
    RateModifier,
    RateModifierWhen,
    step,
)

pytestmark = pytest.mark.unit


# === EventSpec validation ===


def test_eventspec_accepts_base_annual_rate_only_backwards_compat():
    """Existing Phase 3/4a/4b.1 yamls carry ``base_annual_rate`` only — unchanged."""
    spec = EventSpec(event_name="e1", emits_icd="X99", base_annual_rate=0.5)
    assert spec.base_annual_rate == 0.5
    assert spec.base_rate_by_age_band == []


def test_eventspec_accepts_age_band_only():
    """New schema path: band provides rate, base_annual_rate defaults to 0."""
    spec = EventSpec(
        event_name="e1",
        emits_icd="X99",
        base_annual_rate=0.0,
        base_rate_by_age_band=[
            AgeBandRate(age_lo=18, age_hi=44, rate=0.001),
            AgeBandRate(age_lo=45, age_hi=64, rate=0.005),
            AgeBandRate(age_lo=65, age_hi=120, rate=0.015),
        ],
    )
    assert len(spec.base_rate_by_age_band) == 3


# === step() uses age-band when context carries age ===


def _band_spec() -> EventSpec:
    return EventSpec(
        event_name="htn_onset",
        emits_icd="I10",
        base_annual_rate=0.0,
        base_rate_by_age_band=[
            AgeBandRate(age_lo=18, age_hi=44, rate=0.01),
            AgeBandRate(age_lo=45, age_hi=64, rate=0.05),
            AgeBandRate(age_lo=65, age_hi=120, rate=0.10),
        ],
    )


def test_step_uses_age_band_rate_when_age_in_context():
    """A 70-year-old picks the 0.10 band, which fires with seed=0 (0.637 > 0.10 → no)
    but let's just verify the rate selection, not fire path.

    Here we test with seed=0 at the ``0.10`` band: 0.637 > 0.10 → no fire.
    """
    spec = _band_spec()
    rng = np.random.default_rng(0)
    result = step(
        person_chronic=[],
        prev_history=[],
        rng=rng,
        spec=spec,
        context={"continuous": {}, "age": 70},
    )
    assert result.fired is False  # 0.637 > 0.10


def test_step_fires_at_age_band_rate_when_draw_below():
    """Seed yielding a draw < band rate triggers fire."""
    spec = _band_spec()
    # seed=3 draws 0.0856, which is < band rate 0.10 (65+ band) → fires.
    rng = np.random.default_rng(3)
    result = step(
        person_chronic=[],
        prev_history=[],
        rng=rng,
        spec=spec,
        context={"continuous": {}, "age": 70},
    )
    assert result.fired is True


def test_step_falls_back_to_scalar_when_age_missing_from_context():
    """Legacy context without ``age`` key uses ``base_annual_rate`` even if
    bands are populated (backwards-compat safety net)."""
    spec = EventSpec(
        event_name="e1",
        emits_icd="X99",
        base_annual_rate=0.5,
        base_rate_by_age_band=[AgeBandRate(age_lo=65, age_hi=120, rate=0.9)],
    )
    rng = np.random.default_rng(3)
    result = step(
        person_chronic=[],
        prev_history=[],
        rng=rng,
        spec=spec,
        context={"continuous": {}},  # no age key
    )
    # seed=3 draws 0.0856 < 0.5 → fire via scalar; band of 0.9 is ignored because age missing.
    assert result.fired is True


def test_step_zero_rate_when_age_outside_all_bands():
    """A pediatric person (age=10) with adult-only bands has 0 rate → never fires."""
    spec = _band_spec()
    rng = np.random.default_rng(0)
    result = step(
        person_chronic=[],
        prev_history=[],
        rng=rng,
        spec=spec,
        context={"continuous": {}, "age": 10},
    )
    assert result.fired is False


# === has_chronic trigger ===


def test_rate_modifier_when_has_chronic_fires_when_person_carries_any():
    """A modifier with ``has_chronic: [E11.9, I50]`` fires when the person's
    chronic_conditions carries either code."""
    spec = EventSpec(
        event_name="depression_onset",
        emits_icd="F32",
        base_annual_rate=0.01,
        rate_modifiers=[
            RateModifier(
                when=RateModifierWhen(has_chronic=["E11.9", "I50"]),
                factor=3.0,
            )
        ],
    )
    # Base 0.01 × 3.0 = 0.03; seed=34 draws 0.0040 < 0.03 → fires.
    rng = np.random.default_rng(34)
    result = step(
        person_chronic=["E11.9"],
        prev_history=[],
        rng=rng,
        spec=spec,
        context={"continuous": {}, "chronic_conditions": ["E11.9"]},
    )
    assert result.fired is True


def test_rate_modifier_when_has_chronic_does_not_fire_without_match():
    """Person without any of the listed chronics → modifier does NOT apply."""
    spec = EventSpec(
        event_name="depression_onset",
        emits_icd="F32",
        base_annual_rate=0.01,
        rate_modifiers=[
            RateModifier(
                when=RateModifierWhen(has_chronic=["E11.9", "I50"]),
                factor=3.0,
            )
        ],
    )
    # seed=53 draws 0.0111; base rate 0.01 (unmodified since person lacks the
    # trigger chronics) → 0.0111 > 0.01, so no fire.
    rng = np.random.default_rng(53)
    result = step(
        person_chronic=["J44"],
        prev_history=[],
        rng=rng,
        spec=spec,
        context={"continuous": {}, "chronic_conditions": ["J44"]},
    )
    assert result.fired is False


def test_rate_modifier_when_mutually_exclusive_trigger_fields():
    """``attribute+operator+value`` and ``has_chronic`` cannot both be set."""
    with pytest.raises(ValueError, match="exactly one of"):
        RateModifierWhen(
            attribute="hba1c",
            operator=">",
            value=9.0,
            has_chronic=["E11.9"],
        )


def test_rate_modifier_when_requires_exactly_one_trigger():
    """Neither trigger populated → validation error."""
    with pytest.raises(ValueError, match="exactly one of"):
        RateModifierWhen()
