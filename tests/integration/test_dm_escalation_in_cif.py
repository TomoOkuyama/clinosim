"""Phase 4a Task 7 — DM escalation cohort integration.

Confirms that:
- some DM patients escalate to Empagliflozin / Insulin glargine when their
  HbA1c trajectory crosses the threshold;
- non-DM patients never pick up either drug (clinical_scope gate holds);
- escalation does not re-fire year-over-year (fire_marker dedup via
  prior-year snapshot.med_additions holds end-to-end).
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import generate_population


@pytest.fixture(autouse=True)
def _clear_loader() -> None:
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


@pytest.mark.integration
def test_dm_patients_may_escalate_to_sglt2i_across_5y() -> None:
    """A p=200 US cohort advanced 5y should have at least one DM adult
    whose current_medications gained Empagliflozin via the longitudinal
    escalation path."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")

    dm_adults_with_sglt2i = 0
    dm_adults = 0
    for person in registry.persons.values():
        if person.age < 18:
            continue
        if not any(c.startswith(("E11", "E10")) for c in person.chronic_conditions):
            continue
        dm_adults += 1
        if any(hm.drug_name == "Empagliflozin" for hm in person.current_medications):
            dm_adults_with_sglt2i += 1
    assert dm_adults > 0, "sample has no DM adults — bump size or seed"
    assert dm_adults_with_sglt2i >= 1, (
        f"expected >= 1 DM adult escalated to Empagliflozin in p=200 5y, "
        f"got {dm_adults_with_sglt2i} of {dm_adults} DM adults"
    )


@pytest.mark.integration
def test_non_dm_patients_never_gain_dm_escalation_drugs() -> None:
    """Review Focus #4: a non-DM adult never picks up Empagliflozin or
    Insulin glargine — the clinical_scope ``requires_chronic_codes: [E11]``
    gate drops both yamls out of scope so the engine never dispatches
    them for non-DM persons."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")

    forbidden = {"Empagliflozin", "Dapagliflozin", "Insulin glargine"}
    for person in registry.persons.values():
        if person.age < 18:
            continue
        if any(c.startswith(("E11", "E10")) for c in person.chronic_conditions):
            continue
        on_forbidden = [hm.drug_name for hm in person.current_medications if hm.drug_name in forbidden]
        assert not on_forbidden, (
            f"non-DM person {person.person_id} picked up {on_forbidden} — "
            f"clinical_scope gate broken"
        )


@pytest.mark.integration
def test_dm_escalation_fires_at_most_once_per_person() -> None:
    """Fire_marker dedup end-to-end: an escalated patient's
    longitudinal_history contains the fire_marker in at most one
    snapshot's med_additions."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")

    for person in registry.persons.values():
        if not person.longitudinal_history:
            continue
        for marker in ("dm_escalate_sglt2i_e11", "dm_escalate_insulin_e11"):
            fires = sum(1 for snap in person.longitudinal_history if marker in snap.med_additions)
            assert fires <= 1, f"{person.person_id} fired {marker} {fires} times"
