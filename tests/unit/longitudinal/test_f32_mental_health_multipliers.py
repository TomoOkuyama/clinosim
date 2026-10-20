"""Phase 4b.2.β Task 2 — F32 mental-health multiplier migration verify.

Review Focus #5: F32 base × 2.0 (DM) × 2.5 (cancer prefix) etc. matches
the semantics of the retired `_mental_health_onset_multiplier` helper.
"""

from __future__ import annotations

import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs

pytestmark = pytest.mark.unit


def _factor_map(body) -> dict:
    """Group modifiers by trigger shape so tests can assert the compound
    factor independent of which trigger field was used."""
    out = {}
    for m in body.rate_modifiers:
        if m.when.has_chronic_prefix:
            key = ("prefix", tuple(m.when.has_chronic_prefix))
        elif m.when.has_chronic:
            key = ("exact", tuple(m.when.has_chronic))
        else:
            key = ("attribute", m.when.attribute)
        out[key] = m.factor
    return out


def test_f32_onset_multipliers_match_retired_helper_with_r3_fix():
    """F32 carries 4 rate_modifiers migrated from
    `mental_health_onset_multipliers.yaml::F32`.

    Phase 4b.2.β Final-review R3 revisit: DM / HF rules migrated to
    `has_chronic_prefix` (not EXACT `has_chronic`). The Python helper
    used `exact & chronic_set` which was dormant for the real E11.9
    cohort — a semantic-preserving migration ships a known-ineffective
    rule. Switching to prefix match makes the rule effective for E11.9
    / E10.9 sub-codes AND I50.9, matching the yaml's clinical intent.
    """
    specs = load_attribute_specs()
    body = specs["f32_onset"].body
    factors = _factor_map(body)
    assert factors.get(("prefix", ("E10", "E11"))) == 2.0  # diabetes (R3 prefix)
    assert factors.get(("prefix", ("I50",))) == 2.0  # heart_failure (R3 prefix)
    assert factors.get(("prefix", ("C",))) == 2.5  # cancer prefix
    assert factors.get(("exact", ("I69.3", "I69.1"))) == 2.0  # post-stroke exact


def test_f33_onset_multipliers_match_f32():
    specs = load_attribute_specs()
    body = specs["f33_onset"].body
    factors = _factor_map(body)
    assert factors.get(("prefix", ("E10", "E11"))) == 2.0
    assert factors.get(("prefix", ("I50",))) == 2.0
    assert factors.get(("prefix", ("C",))) == 2.5
    assert factors.get(("exact", ("I69.3", "I69.1"))) == 2.0


def test_f41_1_onset_multipliers_match_retired_helper_with_r3_fix():
    """F41.1 uses lower multipliers + no post-stroke rule (anxiety has
    1.5 for DM/HF, 2.0 for cancer prefix). DM/HF migrate to prefix per
    R3 revisit."""
    specs = load_attribute_specs()
    body = specs["f41_1_onset"].body
    factors = _factor_map(body)
    assert factors.get(("prefix", ("E10", "E11"))) == 1.5  # diabetes_anxiety
    assert factors.get(("prefix", ("I50",))) == 1.5  # heart_failure_anxiety
    assert factors.get(("prefix", ("C",))) == 2.0  # cancer_anxiety
    # No post-stroke multiplier for F41.1 — the retired yaml had none.
    assert ("exact", ("I69.3", "I69.1")) not in factors
