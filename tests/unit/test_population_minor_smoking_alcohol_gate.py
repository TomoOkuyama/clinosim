"""Regression guard for the minor-age smoking / alcohol override.

Concrete failure this test guards
---------------------------------
`POP-000621 (村上 かおり)` in the JP p=10000 output rendered as::

    {
      "code": {"text": "飲酒歴"},
      "valueCodeableConcept": {"text": "機会飲酒者"}
    }

despite the patient's birth date (2016-07-26) making them 8 years old at
the encounter's `effectiveDateTime`. Reported by the webapp maintainer
2026-08-13 ("POP-000621 の村上かおり、10歳なのに機会飲酒者になっている").

The pre-fix `population/engine.py` sampled `alcohol_use` and
`smoking_status` from the sex-specific lifestyle distribution regardless
of age. Issue #360 G7 attempted an age gate by skipping the sampling
call, but that shifted the RNG cursor and broke the F4 memoize test
(`test_engine_memoize.py::test_memoize_hit_bit_identical`) — reverted.

The current fix consumes the RNG draw (cursor preserved, memoize stays
byte-identical) and overrides the sampled result to `"never"` /
`"none"` when `age < LEGAL_ADULT_AGE`.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.population._population_workflow_thresholds import LEGAL_ADULT_AGE

pytestmark = pytest.mark.unit


def _generate(seed: int, population: int = 200):
    """Generate a small population and return the CIF Person records."""
    from clinosim.modules.population.engine import generate_population

    registry = generate_population(
        size=population,
        country="JP",
        rng=np.random.default_rng(seed),
    )
    return list(registry.persons.values())


def test_no_minor_has_current_smoking_status():
    """No person below the legal-adult age is marked as current or former
    smoker (both imply having smoked, which minors should not have)."""
    people = _generate(seed=42, population=200)
    minors = [p for p in people if p.age < LEGAL_ADULT_AGE]
    assert minors, "test fixture must include some minors"
    for p in minors:
        assert p.smoking_status == "never", (
            f"minor age={p.age} has smoking_status={p.smoking_status!r} — must be 'never' per LEGAL_ADULT_AGE gate"
        )


def test_no_minor_is_a_drinker():
    """No person below the legal-adult age is marked as social or heavy drinker."""
    people = _generate(seed=42, population=200)
    minors = [p for p in people if p.age < LEGAL_ADULT_AGE]
    assert minors
    for p in minors:
        assert p.alcohol_use == "none", (
            f"minor age={p.age} has alcohol_use={p.alcohol_use!r} — must be 'none' per LEGAL_ADULT_AGE gate"
        )


def test_adults_still_sample_from_distribution():
    """Adults are unaffected by the gate — their smoking / alcohol status
    still comes from the demographics distribution (multi-value)."""
    people = _generate(seed=42, population=500)
    adults = [p for p in people if p.age >= LEGAL_ADULT_AGE]
    smoking_variety = {p.smoking_status for p in adults}
    alcohol_variety = {p.alcohol_use for p in adults}
    # At population=500 seed=42 there must be more than one value in each
    # (the fallback distribution puts non-trivial mass on multiple options).
    assert len(smoking_variety) > 1, f"expected multiple smoking statuses among adults; got {smoking_variety}"
    assert len(alcohol_variety) > 1, f"expected multiple alcohol statuses among adults; got {alcohol_variety}"


def test_legal_adult_age_constant_is_twenty():
    """Pin the constant so a future well-meaning tweak does not silently
    move the gate below JP-legal age."""
    assert LEGAL_ADULT_AGE == 20
