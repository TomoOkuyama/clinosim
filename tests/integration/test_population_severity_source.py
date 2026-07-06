"""FP-SEV-MODEL Task 5: population severity follows the disease YAML distribution.

acute_mi authors `severity.distribution: {mild: 0.0, moderate: 0.65, severe: 0.35}`.
The old locale `severity_beta: [3, 3]` (clamped at 0.3) produces only ~16% severe;
sourcing severity from the disease YAML raises the severe fraction to ~35% —
a signal that distinguishes old (RED) from new (GREEN).
"""

import numpy as np
import pytest

from clinosim.modules.disease.severity import category_from_score
from clinosim.modules.population.engine import (
    generate_monthly_events,
    generate_population,
)

pytestmark = pytest.mark.integration


def _all_events(seed: int, size: int):
    registry = generate_population(size, "US", np.random.default_rng(seed))
    events = []
    rng = np.random.default_rng(seed + 1)
    for month in range(1, 13):
        events += generate_monthly_events(registry, 2024, month, rng, "US")
    return events


def test_acute_mi_severity_never_mild():
    events = _all_events(seed=42, size=6000)
    mi = [e for e in events if e.disease_id == "acute_mi"]
    if not mi:
        pytest.skip("no acute_mi events at this seed/size")
    mild = [e for e in mi if category_from_score(e.severity) == "mild"]
    assert not mild, f"{len(mild)}/{len(mi)} acute_mi events categorized as mild"


def test_acute_mi_severe_fraction_matches_disease_yaml():
    """acute_mi disease YAML says severe=0.35; old severity_beta[3,3] gives ~0.16.
    Threshold 0.25 separates the two."""
    events = _all_events(seed=42, size=6000)
    mi = [e for e in events if e.disease_id == "acute_mi"]
    if len(mi) < 40:
        pytest.skip(f"only {len(mi)} acute_mi events; too few to assert a fraction")
    severe = sum(1 for e in mi if category_from_score(e.severity) == "severe")
    frac = severe / len(mi)
    # Disease YAML base severe = 0.35; comorbidity modifiers push it higher for the
    # older/comorbid MI cohort. Old severity_beta gave ~0.11. Threshold 0.25 separates.
    assert frac > 0.25, f"acute_mi severe fraction {frac:.2f} — expected >=0.35 (disease YAML)"
