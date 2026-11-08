"""One-time vaccines can be documented as declined (Issue #2207)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.immunization.engine import IMMUNIZATION_NOT_DONE_RECORDING_RATE, generate_immunizations

pytestmark = pytest.mark.unit

_SCHEDULE = {
    "ppsv23": {
        "cvx": "33",
        "min_age": 65,
        "available_from": "2000-01-01",
        "frequency": "once",
        "coverage_by_age_sex": {"65-99": {"M": 0.5, "F": 0.5}},
    }
}


def test_once_vaccine_emits_not_done_at_the_documented_rate() -> None:
    patient = SimpleNamespace(date_of_birth=date(1950, 5, 1), age=75, sex="F", patient_id="P1")
    n = 4000
    not_done = 0
    for seed in range(n):
        recs = generate_immunizations(patient, _SCHEDULE, date(2025, 6, 1), np.random.default_rng(seed))
        not_done += sum(1 for r in recs if r.status == "not-done")
    # Half the patients skip the dose; 2 % of those chart a refusal.
    expected = n * 0.5 * IMMUNIZATION_NOT_DONE_RECORDING_RATE
    assert abs(not_done - expected) < 4 * expected**0.5
    assert not_done > 0


def test_no_refusal_of_a_vaccine_the_patient_is_not_eligible_for() -> None:
    """Issue #2868: coverage 0 at this age means not eligible, never declined."""
    patient = SimpleNamespace(date_of_birth=date(1950, 5, 1), age=75, sex="F", patient_id="P1")
    schedule = {"ppsv23": {**_SCHEDULE["ppsv23"], "coverage_by_age_sex": {}}}
    for seed in range(500):
        assert generate_immunizations(patient, schedule, date(2025, 6, 1), np.random.default_rng(seed)) == []
