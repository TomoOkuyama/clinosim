"""Phase 4b.1 — HTN + lipid escalation cohort integration.

Mirrors tests/integration/test_dm_escalation_in_cif.py. p=200 US 5y:
- HTN adults with sustained SBP > 140 may accumulate Hydrochlorothiazide;
- dyslipidemia adults with sustained LDL > 160 may accumulate Rosuvastatin;
- non-HTN non-lipid adults never pick up any of the three escalation
  drugs (clinical_scope gate holds — Review Focus #5);
- fire_marker dedup end-to-end for all three new yamls (one fire per
  person max).
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
def test_htn_patients_may_escalate_to_third_agent_across_5y() -> None:
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    htn_adults = 0
    htn_adults_with_hctz = 0
    for person in registry.persons.values():
        if person.age < 18:
            continue
        if not any(c.startswith("I1") for c in person.chronic_conditions):
            continue
        htn_adults += 1
        if any(hm.drug_name == "Hydrochlorothiazide" for hm in person.current_medications):
            htn_adults_with_hctz += 1
    assert htn_adults > 0, "sample has no HTN adults — bump size or seed"
    assert htn_adults_with_hctz >= 1, (
        f"expected >= 1 HTN adult escalated to Hydrochlorothiazide in p=200 5y, "
        f"got {htn_adults_with_hctz} of {htn_adults} HTN adults"
    )


@pytest.mark.integration
def test_lipid_patients_may_escalate_to_high_intensity_across_5y() -> None:
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    lipid_adults = 0
    lipid_adults_with_rosuvastatin = 0
    for person in registry.persons.values():
        if person.age < 18:
            continue
        if not any(c.startswith("E78") for c in person.chronic_conditions):
            continue
        lipid_adults += 1
        if any(hm.drug_name == "Rosuvastatin" for hm in person.current_medications):
            lipid_adults_with_rosuvastatin += 1
    assert lipid_adults > 0, "sample has no dyslipidemia adults — bump size or seed"
    assert lipid_adults_with_rosuvastatin >= 1, (
        f"expected >= 1 dyslipidemia adult escalated to Rosuvastatin in p=200 5y, "
        f"got {lipid_adults_with_rosuvastatin} of {lipid_adults} dyslipidemia adults"
    )


@pytest.mark.integration
def test_non_htn_non_lipid_patients_never_gain_escalation_drugs() -> None:
    """Review Focus #5: clinical_scope invariance — a patient without I1x
    and without E78 never picks up any of the three new escalation drugs."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    forbidden = {"Hydrochlorothiazide", "Rosuvastatin", "Ezetimibe"}
    for person in registry.persons.values():
        if person.age < 18:
            continue
        has_htn = any(c.startswith("I1") for c in person.chronic_conditions)
        has_lipid = any(c.startswith("E78") for c in person.chronic_conditions)
        if has_htn or has_lipid:
            continue
        on_forbidden = [hm.drug_name for hm in person.current_medications if hm.drug_name in forbidden]
        assert not on_forbidden, (
            f"non-HTN non-lipid person {person.person_id} picked up {on_forbidden} — clinical_scope gate broken"
        )


@pytest.mark.integration
def test_htn_and_lipid_escalation_fire_markers_dedup_across_years() -> None:
    """Fire_marker dedup end-to-end for all three new yamls — each marker
    appears at most once in a person's longitudinal_history."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    for person in registry.persons.values():
        if not person.longitudinal_history:
            continue
        for marker in (
            "htn_escalate_third_agent_i10",
            "lipid_escalate_high_intensity_e78",
            "lipid_escalate_ezetimibe_e78",
        ):
            fires = sum(1 for snap in person.longitudinal_history if marker in snap.med_additions)
            assert fires <= 1, f"{person.person_id} fired {marker} {fires} times"
