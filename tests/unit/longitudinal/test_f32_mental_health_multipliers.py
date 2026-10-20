"""Phase 4b.2.β Task 2 — F32 mental-health multiplier migration verify.

Review Focus #5: F32 base × 2.0 (DM) × 2.5 (cancer prefix) etc. matches
the semantics of the retired `_mental_health_onset_multiplier` helper.
"""

from __future__ import annotations

import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs

pytestmark = pytest.mark.unit


def test_f32_onset_multiplier_rules_match_retired_helper():
    """F32 carries 4 rate_modifiers migrated verbatim from the retired
    `mental_health_onset_multipliers.yaml::F32` block.

    Ruling (Task 2): `requires_any_chronic: [E10, E11]` migrates as
    `has_chronic: [E10, E11]` (EXACT match, same as the Python helper).
    This preserves the current dormant-for-E11.9-cohort semantic.
    Changing to `has_chronic_prefix` would fix the dormant-code bug but
    is out of scope for the migration.
    """
    specs = load_attribute_specs()
    body = specs["f32_onset"].body
    factors = {}
    for m in body.rate_modifiers:
        key = tuple(m.when.has_chronic or m.when.has_chronic_prefix or ())
        factors[key] = m.factor
    assert factors.get(("E10", "E11")) == 2.0  # diabetes_depression
    assert factors.get(("I50",)) == 2.0  # heart_failure_depression
    assert factors.get(("C",)) == 2.5  # cancer_depression (prefix)
    assert factors.get(("I69.3", "I69.1")) == 2.0  # post_stroke_depression


def test_f33_onset_multiplier_rules_match_f32():
    """F33 shares F32's multiplier set per the retired yaml."""
    specs = load_attribute_specs()
    body = specs["f33_onset"].body
    factors = {}
    for m in body.rate_modifiers:
        key = tuple(m.when.has_chronic or m.when.has_chronic_prefix or ())
        factors[key] = m.factor
    assert factors.get(("E10", "E11")) == 2.0
    assert factors.get(("I50",)) == 2.0
    assert factors.get(("C",)) == 2.5
    assert factors.get(("I69.3", "I69.1")) == 2.0


def test_f41_1_onset_multiplier_rules_match_retired_helper():
    """F41.1 uses lower multipliers + no post-stroke rule per the
    retired yaml (anxiety has 1.5 for DM/HF, 2.0 for cancer prefix,
    no stroke multiplier)."""
    specs = load_attribute_specs()
    body = specs["f41_1_onset"].body
    factors = {}
    for m in body.rate_modifiers:
        key = tuple(m.when.has_chronic or m.when.has_chronic_prefix or ())
        factors[key] = m.factor
    assert factors.get(("E10", "E11")) == 1.5  # diabetes_anxiety
    assert factors.get(("I50",)) == 1.5  # heart_failure_anxiety
    assert factors.get(("C",)) == 2.0  # cancer_anxiety (prefix)
    # No post-stroke multiplier for F41.1 — the retired yaml does not have one.
    assert ("I69.3", "I69.1") not in factors
