"""Phase 4b.2.β Task 3 — `_annual_chronic_onset` + mental-health helper retirement."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.longitudinal.engine import advance_one_year, initial_snapshot
from clinosim.modules.population import aging
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def test_annual_chronic_onset_function_is_removed():
    assert not hasattr(aging, "_annual_chronic_onset")


def test_mental_health_onset_multiplier_helper_is_removed():
    assert not hasattr(aging, "_mental_health_onset_multiplier")


def test_annual_incidence_helpers_are_removed():
    """Supporting helpers also retire with `_annual_chronic_onset`."""
    assert not hasattr(aging, "_derive_annual_incidence_from_prevalence")
    assert not hasattr(aging, "_load_annual_incidence_for_locale")
    assert not hasattr(aging, "_ChronicIncidenceSpec")
    assert not hasattr(aging, "_STATE_PERIOD_ONSET_SKIP_CODES")


def test_advance_population_passes_no_longer_include_annual_chronic_onset():
    import inspect

    src = inspect.getsource(aging.advance_population)
    assert "_annual_chronic_onset" not in src


def test_engine_ignores_legacy_state_period_codes():
    """Review Focus #2: legacy Z34 / Z37 on a person's chronic_conditions
    does not break the engine."""
    person = PersonRecord(
        person_id="P-LEGACY",
        household_id="H1",
        sex="F",
        age=44,
        date_of_birth=date(1980, 1, 1),
        chronic_conditions=["Z34", "Z37", "I10"],
    )
    initial_snapshot(person, year=2024, init_rng=np.random.default_rng(0))
    advance_one_year(
        person,
        year=2025,
        year_rng=np.random.default_rng(0),
    )
    # Does not raise. New complications or chronic entries are a function
    # of the engine's own event dispatch, not of the legacy Z34/Z37 codes.
