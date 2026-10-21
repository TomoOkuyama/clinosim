"""Phase 4c — cancer Markov stage integration in CIF.

p=200 US seed=42 5y cohort end-to-end:
- C-code adults carry their icd_base stage key in longitudinal_history
- non-cancer adults never gain any cancer-stage key (clinical_scope)
- a single-cancer patient's chronic_stages contains only that icd_base
- once at terminal (AJCC IV / BCLC D), stage stays absorbed
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import generate_population

CANCER_ICD_BASES = ["C16", "C18", "C22", "C34", "C50", "C61"]


@pytest.fixture(autouse=True)
def _clear_loader() -> None:
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


@pytest.mark.integration
def test_cancer_patients_gain_stage_history_across_5y():
    """A C-code adult must carry its icd_base key in
    longitudinal_history[-1].chronic_stages after 5 sim years, whether
    the cancer was present at sim-start (initial cohort) or acquired
    mid-sim via the Phase 4b.2.β onset-event dispatch (Phase 4b.2.γ
    makes same-year Markov initial draw guaranteed via scope
    re-evaluation after event fire)."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    found_counts = {b: 0 for b in CANCER_ICD_BASES}
    for person in registry.persons.values():
        if not person.longitudinal_history:
            continue
        last = person.longitudinal_history[-1]
        for b in CANCER_ICD_BASES:
            if any(c.startswith(b) for c in person.chronic_conditions):
                assert b in last.chronic_stages, f"{person.person_id} missing {b} stage"
                found_counts[b] += 1
    assert sum(found_counts.values()) >= 1, f"sample has no cancer patients — bump size or seed: {found_counts}"


@pytest.mark.integration
def test_non_cancer_patients_never_gain_cancer_stage_keys():
    """Review Focus #3: patient with no C-code never has any of the six
    icd_base keys in chronic_stages (clinical_scope gate)."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    for person in registry.persons.values():
        if any(c.startswith(tuple(CANCER_ICD_BASES)) for c in person.chronic_conditions):
            continue
        for snap in person.longitudinal_history:
            leaked = [b for b in CANCER_ICD_BASES if b in snap.chronic_stages]
            assert not leaked, f"non-cancer person {person.person_id} picked up {leaked}"


@pytest.mark.integration
def test_cancer_stage_icd_base_isolation():
    """Review Focus #4: single-cancer patient carries ONLY that icd_base
    in chronic_stages, not any other cancer's icd_base."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    checked = 0
    for person in registry.persons.values():
        c_prefixes = {b for b in CANCER_ICD_BASES if any(c.startswith(b) for c in person.chronic_conditions)}
        if len(c_prefixes) != 1:
            continue
        checked += 1
        only = next(iter(c_prefixes))
        for snap in person.longitudinal_history:
            others = [b for b in CANCER_ICD_BASES if b != only and b in snap.chronic_stages]
            assert not others, f"{person.person_id} ({only}) leaked {others}"
    assert checked >= 1, "no single-cancer patient in sample — bump size or seed"


@pytest.mark.integration
def test_cancer_stage_terminal_is_absorbing_across_years():
    """Review Focus #5: once at AJCC IV (or BCLC D for C22), stage stays
    there for every subsequent snapshot."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    for person in registry.persons.values():
        c_prefixes = {b for b in CANCER_ICD_BASES if any(c.startswith(b) for c in person.chronic_conditions)}
        for b in c_prefixes:
            terminal = "BCLC D" if b == "C22" else "AJCC IV"
            hit = False
            for snap in person.longitudinal_history:
                if snap.chronic_stages.get(b) == terminal:
                    hit = True
                if hit:
                    assert snap.chronic_stages.get(b) == terminal, f"{person.person_id} ({b}) left terminal state"
