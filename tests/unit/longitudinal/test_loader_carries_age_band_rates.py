"""Phase 4b.2.β Final-review C1 regression — `_build_event_body` must
carry `base_rate_by_age_band` through to the EventSpec.

Reviewer caught: the loader popped `base_annual_rate` + `rate_modifiers`
etc. but never popped `base_rate_by_age_band`, so every migrated 30-ICD
yaml parsed with an empty band + base_annual_rate=0.0 → zero fire rate
at runtime. This test pins the end-to-end wire: a yaml declaration
`base_rate_by_age_band: [{age_lo: X, age_hi: Y, rate: Z}]` must surface
on the loaded `EventSpec.base_rate_by_age_band` field.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.longitudinal.patterns.event import step

pytestmark = pytest.mark.unit


def test_loader_carries_base_rate_by_age_band_onto_eventspec():
    """`i10_onset.yaml` declares non-empty `base_rate_by_age_band`;
    the loaded spec must reflect that, not drop it."""
    specs = load_attribute_specs()
    body = specs["i10_onset"].body
    assert body.base_rate_by_age_band, (
        f"i10_onset base_rate_by_age_band empty — loader did not carry it; base_annual_rate={body.base_annual_rate}"
    )
    # The yaml declares a non-zero rate for 40-59.
    rates = {(b.age_lo, b.age_hi): b.rate for b in body.base_rate_by_age_band}
    assert rates.get((40, 59), 0.0) > 0.0, f"i10_onset 40-59 rate is zero: {rates}"


def test_i10_onset_actually_fires_at_runtime():
    """Monte-Carlo over 2000 adult-50 draws of i10_onset: fire count
    must land near expected = 2000 × 0.016683 ≈ 33. The reviewer's
    C1 reproduction showed `fires = 0` on this exact shape. ≥ 15
    passes the regression bar."""
    specs = load_attribute_specs()
    body = specs["i10_onset"].body
    fires = 0
    for seed in range(2000):
        rng = np.random.default_rng(seed)
        result = step(
            [],
            [],
            rng,
            body,
            context={"continuous": {}, "age": 50, "chronic_conditions": []},
        )
        if result.fired:
            fires += 1
    assert fires >= 15, f"i10_onset is dormant: only {fires}/2000 fires at age 50 (expected ~33 for rate 0.016683)"
