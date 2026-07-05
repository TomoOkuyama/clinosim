"""Unit tests for AVPU consciousness-level inference in the inpatient simulator."""

import numpy as np
import pytest

from clinosim.simulator.inpatient import _loc_for
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


def test_loc_for_reaches_unresponsive_at_severe_shock():
    """AVPU 'U' (unresponsive) must be reachable when perfusion is severely
    compromised (refractory shock). Before this fix, _loc_for's threshold
    ladder topped out at 'V'/'P', so GCS/Braden severe-end scores never
    appeared in generated data (2026-06-20 realism audit finding)."""
    state = PhysiologicalState(perfusion_status=0.1)
    seen = {_loc_for(state, "sepsis", 3, np.random.default_rng(seed)) for seed in range(200)}
    assert "U" in seen


def test_loc_for_does_not_regress_existing_bands():
    """Existing V/P/A bands must still fire for their prior perfusion ranges."""
    moderate_shock = PhysiologicalState(perfusion_status=0.35)
    seen = {_loc_for(moderate_shock, "sepsis", 3, np.random.default_rng(seed)) for seed in range(200)}
    assert seen <= {"V", "P"}

    healthy = PhysiologicalState(perfusion_status=1.0)
    assert _loc_for(healthy, "acute_mi", 3, np.random.default_rng(1)) == "A"
