"""Issue #1760: pediatric ED visits receive adult-pattern cardiac
chief complaints.

The audit at p=10000 5y US cohort found 284 pediatric (age < 18) ED
encounters assigned adult cardiac chief complaints:

* "Chest pain, rule out acute coronary syndrome" (ACS workup) — 220
  pediatric encounters.
* "Palpitations, dyspnea, chest tightness, anxiety" (F41.0 panic
  disorder) — 64 pediatric encounters.

Both are adult clinical phenomenology: pediatric ACS prevalence is
near zero and pediatric panic disorder is clinically rare before
mid-adolescence. The ED visit sampler in
`clinosim/simulator/engine.py` applied the condition pool without
an age filter.

Fix: encounter yamls carry optional `min_age` / `max_age` fields;
the sampler zeros the probability weight for a condition whose age
band does not include the person. The gate is RNG-neutral — the
probability list length stays at N so the `slot_rng.choice` draw
is byte-stable across the gate's introduction.
"""

from __future__ import annotations

import pytest

from clinosim.modules.encounter.protocol import load_encounter_condition


def test_chest_pain_noncardiac_has_adult_age_gate() -> None:
    """ACS rule-out workup is adult-only — the encounter yaml must
    declare `min_age: 18` so the ED sampler filters it from the
    pediatric condition pool."""
    spec = load_encounter_condition("chest_pain_noncardiac")
    assert spec is not None
    assert spec.get("min_age") == 18, (
        f"chest_pain_noncardiac must declare min_age=18 for the ED sampler; got min_age={spec.get('min_age')!r}"
    )


def test_anxiety_panic_attack_has_adolescent_age_gate() -> None:
    """F41.0 Panic disorder phenomenology is adolescent-adult. The
    encounter yaml must declare `min_age: 15` so the ED sampler
    filters it from the pre-adolescent condition pool."""
    spec = load_encounter_condition("anxiety_panic_attack")
    assert spec is not None
    assert spec.get("min_age") == 15, (
        f"anxiety_panic_attack must declare min_age=15 for the ED sampler; got min_age={spec.get('min_age')!r}"
    )


@pytest.mark.parametrize(
    "condition_id,expected_min_age",
    [
        ("chest_pain_noncardiac", 18),
        ("anxiety_panic_attack", 15),
    ],
)
def test_encounter_yaml_min_age_type_is_int(condition_id: str, expected_min_age: int) -> None:
    """The sampler coerces `min_age` to `int()`; the yaml value must be
    numeric (int or float castable to int), not a string. A yaml string
    would silently fail the comparison and defeat the gate."""
    spec = load_encounter_condition(condition_id)
    assert isinstance(spec.get("min_age"), int), (
        f"{condition_id}.min_age must be an int, got {type(spec.get('min_age')).__name__}"
    )
    assert spec["min_age"] == expected_min_age
