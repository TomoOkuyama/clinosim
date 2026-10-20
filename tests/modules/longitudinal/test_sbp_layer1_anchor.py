"""Phase 4b.1 — SBP base-year initialization for HTN adults.

Phase 4b.1 Ruling: PersonRecord (Layer-1) has no systolic_bp field —
systolic_bp lives on PatientProfile (Layer-2 only). Unlike BMI (which
has a Layer-1 anchor), SBP's sim-start value comes from the yaml's
``initial:`` block for every HTN adult. This test pins that behavior
so a future Layer-1 BP anchor can be slotted in later without silent
drift (Review Focus #3 trimmed from "continuity to Layer-1" down to
"base-year population").
"""

from __future__ import annotations

import numpy as np

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.population.engine import generate_population


def test_sbp_populated_at_base_year_for_htn_adults():
    load_attribute_specs.cache_clear()
    registry = generate_population(
        size=100, country="US", rng=np.random.default_rng(42), base_year=2024,
    )
    found_htn = False
    for person in registry.persons.values():
        if not any(c.startswith("I1") for c in person.chronic_conditions):
            continue
        if person.age < 18:
            continue
        found_htn = True
        snap = person.longitudinal_history[0]
        assert "sbp" in snap.continuous
        # yaml initial: mu=4.976 sigma=0.08 → clamped to [90, 220], expected
        # population range ~130-165 under the lognormal.
        sbp = snap.continuous["sbp"]
        assert 90.0 <= sbp <= 220.0
    assert found_htn, "sample has no HTN adults — bump size or seed"
