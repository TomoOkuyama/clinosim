"""BMI initial seed from Layer-1 PatientProfile.bmi (Phase 3 Task 5, Review Focus #5).

The yaml's initial_distribution is a dummy; production seeds BMI into
the sim-start YearSnapshot.continuous["bmi"] from the person's
Layer-1 bmi value. This test exercises the real Layer-1 generation
path to confirm continuity.
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_layer1_bmi_matches_sim_start_snapshot() -> None:
    """Generate a tiny cohort via population.generate_population and
    assert that for every adult, state_at(person, base_year).continuous
    ["bmi"] equals person.bmi."""
    import numpy as np

    from clinosim.modules.longitudinal.engine import state_at
    from clinosim.modules.population.engine import generate_population

    registry = generate_population(
        size=20,
        country="US",
        rng=np.random.default_rng(42),
        base_year=2024,
    )
    adults = [p for p in registry.persons.values() if p.age >= 18]
    assert len(adults) >= 5, f"too few adults ({len(adults)}) to assert continuity"
    for person in adults:
        snap = state_at(person, 2024)
        bmi_in_snap = snap.continuous.get("bmi")
        assert bmi_in_snap is not None, f"person {person.person_id!r} missing bmi in snapshot"
        assert bmi_in_snap == pytest.approx(person.bmi), (
            f"person {person.person_id!r} snap bmi {bmi_in_snap} != layer1 bmi {person.bmi}"
        )
