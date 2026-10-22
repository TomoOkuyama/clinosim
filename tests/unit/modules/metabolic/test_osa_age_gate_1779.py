"""Issue #1779: pediatric G47.30 OSA inappropriate.

The audit at p=10000 5y US cohort found that 335 / 2553 pediatric
patients (13%) carried G47.30 — ~6-20× the US pediatric ICD-coded
reference. G47.30 ("Sleep apnea, unspecified") is clinically the adult
OSA leaf; pediatric OSA has its own leaf (G47.33) with much lower
prevalence (~1-2%) and different diagnostic / management pathways.

Root cause: ``g47_30_osa_enricher`` in ``clinosim/modules/metabolic/engine.py``
applied the adult BMI + sex-weighted Bernoulli to every PersonRecord
regardless of age. Fix: gate at age ≥ 18.

(Pediatric OSA via G47.33 — the clinically correct leaf — is a
separate follow-up PR with its own prevalence table and
polysomnography / adenotonsillectomy management pathways.)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from clinosim.modules.metabolic.engine import g47_30_osa_enricher


def _person(person_id: str, age: int, bmi: float = 42.0, sex: str = "M") -> MagicMock:
    """Build a minimal PersonRecord stub. BMI defaults to the ≥40 band
    where the adult OSA Bernoulli has the highest firing rate — the
    pediatric age gate must still block it regardless."""
    p = MagicMock()
    p.person_id = person_id
    p.age = age
    p.bmi = bmi
    p.sex = sex
    p.chronic_conditions = []
    return p


def _run(persons: list[MagicMock]) -> None:
    ctx = MagicMock()
    ctx.population.persons = {p.person_id: p for p in persons}
    g47_30_osa_enricher(ctx)


@pytest.mark.parametrize("pediatric_age", [0, 1, 5, 10, 15, 17])
def test_pediatric_person_never_gets_g47_30(pediatric_age: int) -> None:
    """Age < 18 must not receive G47.30, even at the highest-firing
    BMI tier (≥ 40) and male sex (the adult BMI × sex Bernoulli
    weighting that would otherwise draw G47.30 at ~75%)."""
    # Use enough persons at the same age to make a false negative
    # from the Bernoulli statistically improbable without the gate.
    persons = [_person(f"POP-{pediatric_age}-{i:03d}", pediatric_age) for i in range(50)]
    _run(persons)
    for p in persons:
        assert "G47.30" not in p.chronic_conditions, (
            f"Pediatric age={pediatric_age} must not receive G47.30; got {p.chronic_conditions}"
        )


def test_adult_cohort_still_receives_g47_30() -> None:
    """Age ≥ 18 at BMI ≥ 40 + male sex should receive G47.30 at the
    documented ~75% rate per the enricher's clinical basis. Verify
    at least ONE person in a 50-adult cohort gets the code so the
    gate hasn't accidentally silenced the entire enricher."""
    persons = [_person(f"POP-ADULT-{i:03d}", 55, bmi=42.0, sex="M") for i in range(50)]
    _run(persons)
    assigned = sum(1 for p in persons if "G47.30" in p.chronic_conditions)
    assert assigned > 0, "Adult cohort should still receive G47.30 at the ≥40 BMI tier"


def test_person_without_age_attr_defaults_to_zero_and_is_skipped() -> None:
    """Defensive: a PersonRecord missing the ``age`` attribute (older
    test stubs predating the age field) is treated as age=0 and
    skipped. Prevents a crash on malformed stubs rather than
    silently drawing G47.30 on them."""
    p = MagicMock(spec=["person_id", "bmi", "sex", "chronic_conditions"])
    p.person_id = "POP-NO-AGE"
    p.bmi = 42.0
    p.sex = "M"
    p.chronic_conditions = []
    _run([p])
    assert "G47.30" not in p.chronic_conditions
