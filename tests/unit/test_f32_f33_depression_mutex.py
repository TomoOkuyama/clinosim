"""F32 vs F33 mutex — recurrent depressive disorder subsumes single-episode.

Per ICD-10-CM §F30-F39, F33 (recurrent depressive disorder) subsumes
F32 (depressive episode, single). Dual presence on the same person's
``chronic_conditions`` list is a clinical-coherence defect.

The mutex is enforced at two sites:

1. The initial-cohort sampler in ``clinosim/modules/population/engine.py``
   (chronic_prevalence loop — both codes are drawn independently via
   per-code Bernoulli, so a non-trivial fraction of adults would land
   with both).
2. The longitudinal event dispatch in
   ``clinosim/modules/longitudinal/engine.py`` (``f33_onset`` event
   firing on a person who already carries F32 from initial cohort).

The helper lives at ``clinosim/modules/population/condition_mutex.py``;
these tests cover the helper directly and the longitudinal engine path.
Audit motivation: p=2000 US seed=42 5y cohort had 2 adults with both
F32 and F33 on their problem list (Cycle 2 H3 finding).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.longitudinal.engine import _apply_pattern
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.longitudinal.patterns.event import EventSpec
from clinosim.modules.longitudinal.snapshot import YearSnapshot
from clinosim.modules.population.condition_mutex import apply_depression_mutex
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helper-level — ``apply_depression_mutex`` behaviour
# ---------------------------------------------------------------------------


def test_mutex_drops_f32_when_f33_present():
    conds = ["I10", "F32", "F33"]
    apply_depression_mutex(conds)
    assert conds == ["I10", "F33"]


def test_mutex_noop_when_only_f32_present():
    conds = ["F32", "E11.9"]
    apply_depression_mutex(conds)
    assert conds == ["F32", "E11.9"]


def test_mutex_noop_when_only_f33_present():
    conds = ["F33", "E11.9"]
    apply_depression_mutex(conds)
    assert conds == ["F33", "E11.9"]


def test_mutex_noop_when_neither_present():
    conds = ["I10", "E11.9", "F41.1"]
    original = list(conds)
    apply_depression_mutex(conds)
    assert conds == original


def test_mutex_preserves_order_of_other_codes():
    conds = ["F32", "I10", "F33", "E11.9", "M17"]
    apply_depression_mutex(conds)
    # F32 dropped, every other code's relative order preserved
    assert conds == ["I10", "F33", "E11.9", "M17"]


# ---------------------------------------------------------------------------
# Longitudinal engine — F33 onset event drops F32 at firing time
# ---------------------------------------------------------------------------


def _adult_with_f32(age: int = 55) -> PersonRecord:
    """50-something with F32 already on the problem list."""
    return PersonRecord(
        person_id="P-DEP",
        household_id="H",
        sex="F",
        age=age,
        date_of_birth=date(2024 - age, 3, 15),
        chronic_conditions=["I10", "F32"],
    )


def test_longitudinal_f33_onset_removes_pre_existing_f32():
    """Dispatch the ``f33_onset`` event with a forced-fire rate against a
    person who carries F32 from the initial-cohort sampler. Expect:

    * F33 appended to ``chronic_conditions``.
    * F32 removed from ``chronic_conditions``.
    * ``snapshot.new_complications`` records F33.
    """
    # Load the real spec, then clone its body with a forced-fire rate so
    # we exercise the engine's post-fire mutex path deterministically.
    specs = load_attribute_specs()
    f33_spec = specs["f33_onset"]
    assert f33_spec.body.emits_icd == "F33", "yaml invariant"

    forced_body = EventSpec(
        event_name=f33_spec.body.event_name,
        emits_icd="F33",
        base_annual_rate=1.0,
        base_rate_by_age_band=[],
        rate_modifiers=[],
        one_shot=True,
    )
    forced_spec = f33_spec.model_copy(update={"body": forced_body})

    person = _adult_with_f32(age=55)
    snapshot = YearSnapshot(year=2026)
    rng = np.random.default_rng(0)

    _apply_pattern(forced_spec, snapshot, rng, person=person, prev_snapshot=None)

    assert "F33" in person.chronic_conditions, "F33 must be appended"
    assert "F32" not in person.chronic_conditions, "F32 must be dropped when F33 fires (ICD-10-CM §F30-F39 subsumption)"
    assert "I10" in person.chronic_conditions, "unrelated codes untouched"
    assert "F33" in snapshot.new_complications


def test_longitudinal_f33_onset_leaves_person_without_f32_alone():
    """Mutex is a no-op when the person did not already have F32."""
    specs = load_attribute_specs()
    f33_spec = specs["f33_onset"]
    forced_body = EventSpec(
        event_name=f33_spec.body.event_name,
        emits_icd="F33",
        base_annual_rate=1.0,
        base_rate_by_age_band=[],
        rate_modifiers=[],
        one_shot=True,
    )
    forced_spec = f33_spec.model_copy(update={"body": forced_body})

    person = PersonRecord(
        person_id="P-NEW",
        household_id="H",
        sex="M",
        age=55,
        date_of_birth=date(1971, 1, 1),
        chronic_conditions=["I10"],
    )
    snapshot = YearSnapshot(year=2026)
    rng = np.random.default_rng(0)

    _apply_pattern(forced_spec, snapshot, rng, person=person, prev_snapshot=None)

    assert person.chronic_conditions == ["I10", "F33"]
