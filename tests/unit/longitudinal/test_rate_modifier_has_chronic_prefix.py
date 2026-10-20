"""Phase 4b.2.β Task 1 — `has_chronic_prefix` rate-modifier trigger.

Mirrors the Python helper `_mental_health_onset_multiplier`'s
`requires_any_chronic_prefix` semantics: startswith-match on ANY of
the listed prefixes against `context["chronic_conditions"]`.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.patterns.event import (
    EventSpec,
    RateModifier,
    RateModifierWhen,
    step,
)

pytestmark = pytest.mark.unit


def test_has_chronic_prefix_fires_when_person_has_matching_prefix():
    spec = EventSpec(
        event_name="depression_onset",
        emits_icd="F32",
        base_annual_rate=0.01,
        rate_modifiers=[
            RateModifier(when=RateModifierWhen(has_chronic_prefix=["C"]), factor=2.5),
        ],
    )
    # seed=34 draws 0.0040 < base × 2.5 = 0.025 → fires.
    rng = np.random.default_rng(34)
    result = step(
        person_chronic=["C18"],
        prev_history=[],
        rng=rng,
        spec=spec,
        context={"continuous": {}, "chronic_conditions": ["C18"]},
    )
    assert result.fired is True


def test_has_chronic_prefix_no_match_leaves_base_rate():
    spec = EventSpec(
        event_name="depression_onset",
        emits_icd="F32",
        base_annual_rate=0.01,
        rate_modifiers=[
            RateModifier(when=RateModifierWhen(has_chronic_prefix=["C"]), factor=2.5),
        ],
    )
    # seed=53 draws 0.0111 > base 0.01 → no fire (modifier not applied).
    rng = np.random.default_rng(53)
    result = step(
        person_chronic=["I10"],
        prev_history=[],
        rng=rng,
        spec=spec,
        context={"continuous": {}, "chronic_conditions": ["I10"]},
    )
    assert result.fired is False


def test_three_way_mutual_exclusivity_rejects_two_triggers():
    with pytest.raises(ValueError, match="exactly one of"):
        RateModifierWhen(has_chronic=["E11.9"], has_chronic_prefix=["C"])


def test_three_way_mutual_exclusivity_rejects_zero_triggers():
    with pytest.raises(ValueError, match="exactly one of"):
        RateModifierWhen()
