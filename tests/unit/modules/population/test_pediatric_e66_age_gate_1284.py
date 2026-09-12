"""Regression guard for pediatric BMI-derived E66 age gate (#1284).

Pre-#1284 the BMI-derived Condition insertion block in
``clinosim/modules/population/engine.py`` fired the same adult
thresholds (25 / 30 / 40) for every age, so a p=10k s=354 audit
counted:

- 881 US pediatric patients (age 0-17) with any E66 code
- 52 US pediatric patients with E66.01 "morbid obesity"
- 15 toddlers aged 2-5 with E66.01 (BMI ≥ 40 is physiologically
  impossible in this age band)

Adult E66 thresholds are not the correct pediatric coding practice —
ICD-10-CM pairs pediatric obesity with ``Z68.5x`` BMI-for-age
percentiles, not the E66 cascade. Full pediatric-BMI modelling
(percentile sampling + `Z68.5x` emit) is deferred to the metabolic/
module (META #1137). This test locks in the scope-disciplined bug
fix: skip the E66 dispatch entirely below :data:`LEGAL_ADULT_AGE`.
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.unit


def test_pediatric_no_e66_from_generate_population() -> None:
    """End-to-end n=500 US: zero pediatric patients (age < LEGAL_ADULT_AGE)
    carry any E66 code (E66.01, E66.9, E66.3). Adult patients still do."""
    from clinosim.modules.population._population_workflow_thresholds import LEGAL_ADULT_AGE
    from clinosim.modules.population.engine import generate_population

    reg = generate_population(size=500, country="US", rng=np.random.default_rng(42))
    peds_with_e66: list[tuple[str, int, list[str]]] = []
    adult_e66_count = 0
    for person in reg.persons.values():
        codes = [str(c) for c in (getattr(person, "chronic_conditions", None) or [])]
        e66_codes = [c for c in codes if c in ("E66.01", "E66.9", "E66.3")]
        if not e66_codes:
            continue
        if person.age < LEGAL_ADULT_AGE:
            peds_with_e66.append((person.person_id, person.age, e66_codes))
        else:
            adult_e66_count += 1
    assert not peds_with_e66, (
        f"pediatric patients (age < LEGAL_ADULT_AGE) must not receive adult E66 codes; got {peds_with_e66[:5]}"
    )
    # Guard against over-gating: adults still emit E66 codes.
    assert adult_e66_count >= 1, "adult E66 emit must survive the age gate"


def test_pediatric_no_e66_jp_locale() -> None:
    """JP locale mirror of the US guard — the fix is locale-invariant."""
    from clinosim.modules.population._population_workflow_thresholds import LEGAL_ADULT_AGE
    from clinosim.modules.population.engine import generate_population

    reg = generate_population(size=500, country="JP", rng=np.random.default_rng(42))
    peds_with_e66: list[tuple[str, int, list[str]]] = []
    for person in reg.persons.values():
        codes = [str(c) for c in (getattr(person, "chronic_conditions", None) or [])]
        if person.age < LEGAL_ADULT_AGE and any(c in ("E66.01", "E66.9", "E66.3") for c in codes):
            peds_with_e66.append((person.person_id, person.age, [c for c in codes if c.startswith("E66")]))
    assert not peds_with_e66, f"JP pediatric patients must not receive adult E66 codes either; got {peds_with_e66[:5]}"


def test_pediatric_no_e66_01_toddlers() -> None:
    """Specific guard for the audit's most-jarring case — toddlers age 2-5
    receiving `E66.01` "Morbid (severe) obesity" (BMI ≥ 40, physically
    impossible in this age band). Pre-fix: 15 such toddlers per p=10k US."""
    import numpy as np

    from clinosim.modules.population.engine import generate_population

    reg = generate_population(size=1000, country="US", rng=np.random.default_rng(42))
    toddlers_morbid = [
        (person.person_id, person.age)
        for person in reg.persons.values()
        if 2 <= person.age <= 5 and "E66.01" in [str(c) for c in (getattr(person, "chronic_conditions", None) or [])]
    ]
    assert not toddlers_morbid, f"toddlers aged 2-5 must never carry E66.01; got {toddlers_morbid[:5]}"
