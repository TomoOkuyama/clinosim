"""Issue #1581 DM extension — glycemic trajectory annual drift."""

from __future__ import annotations

from datetime import date

import numpy as np

from clinosim.modules.population.aging import (
    _advance_glycemic_trajectory,
    _disease_progression,
    aging_sub_seed,
)
from clinosim.types.population import PersonRecord


def _dm_person(pid: str, age: int = 60) -> PersonRecord:
    p = PersonRecord(
        person_id=pid,
        household_id="HH-1",
        age=age,
        sex="M",
        date_of_birth=date(2026 - age, 1, 1),
    )
    p.chronic_conditions = ["E11.9"]
    return p


def test_glycemic_first_touch_initialises_trajectory() -> None:
    """First-year touch populates ``glycemic_trajectory`` with a
    plausible 0-1 glycemic_control value."""
    p = _dm_person("PT-DM-INIT-1")
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    assert 2026 in p.glycemic_trajectory
    gc = p.glycemic_trajectory[2026]
    assert 0.0 <= gc <= 1.0


def test_glycemic_subsequent_year_drifts_down_on_average() -> None:
    """Monte-Carlo: HbA1c (= inverse-gc) should drift UP (gc drifts
    DOWN) on average under baseline-care parameters (UKPDS). Compare
    mean gc at year 1 (first-touch) vs year 10 (post-9-year drift)
    across a cohort."""
    n = 400
    initial_gcs = []
    final_gcs = []
    for i in range(n):
        p = _dm_person(f"PT-DM-DRIFT-{i:04d}")
        # Year 2026 — first touch.
        _disease_progression(
            p,
            2026,
            np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
            {},
        )
        initial_gcs.append(p.glycemic_trajectory[2026])
        # Advance years 2027..2035.
        for y in range(2027, 2036):
            _disease_progression(
                p,
                y,
                np.random.default_rng(aging_sub_seed(p.person_id, y, "_disease_progression")),
                {},
            )
        final_gcs.append(p.glycemic_trajectory[2035])
    initial_mean = float(np.mean(initial_gcs))
    final_mean = float(np.mean(final_gcs))
    # Natural history: gc drifts DOWN (control worsens).
    assert final_mean < initial_mean, f"final {final_mean:.3f} should be < initial {initial_mean:.3f}"


def test_glycemic_trajectory_clamped_to_bounds() -> None:
    """``gc_min`` / ``gc_max`` bounds clamp the trajectory."""
    p = _dm_person("PT-DM-CLAMP-1")
    # Force start near the lower bound.
    p.glycemic_trajectory[2025] = 0.0
    # Advance several years — gc should stay at 0.0 under clamp
    # because drift is downward-biased and bounded.
    for y in range(2026, 2036):
        _disease_progression(
            p,
            y,
            np.random.default_rng(aging_sub_seed(p.person_id, y, "_disease_progression")),
            {},
        )
    assert all(0.0 <= gc <= 1.0 for gc in p.glycemic_trajectory.values())
    assert p.glycemic_trajectory[2035] >= 0.0


def test_glycemic_advance_helper_deterministic() -> None:
    """Same (person_id, year, prior gc) → same next gc."""

    def run(seed_year: int) -> float:
        p = _dm_person("PT-DM-DET-1")
        p.glycemic_trajectory[2026] = 0.7
        _advance_glycemic_trajectory(
            p,
            2027,
            np.random.default_rng(aging_sub_seed(p.person_id, seed_year, "_disease_progression")),
            {"gc_drift_mean": -0.025, "gc_drift_sd": 0.015, "gc_min": 0.0, "gc_max": 1.0},
        )
        return p.glycemic_trajectory[2027]

    assert run(2027) == run(2027)


def test_glycemic_non_dm_person_unaffected() -> None:
    """A person without E11/E10 does not get a glycemic trajectory."""
    p = _dm_person("PT-NON-DM-1")
    p.chronic_conditions = ["I10"]  # hypertension, not DM
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    assert p.glycemic_trajectory == {}
