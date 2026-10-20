"""Phase 4b.2.β Task 2 — 30 adult-chronic onset event yamls present + adult-gated."""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs

pytestmark = pytest.mark.unit


EXPECTED_30 = [
    "I10",
    "E11.9",
    "E78",
    "J44",
    "N18",
    "I50",
    "I48",
    "I25",
    "M81",
    "F00",
    "G20",
    "E03",
    "K21",
    "J45",
    "N40",
    "M17",
    "G35",
    "F32",
    "F33",
    "F41.1",
    "C15",
    "C16",
    "C25",
    "C67",
    "C71",
    "C18",
    "C22",
    "C34",
    "C50",
    "C61",
]


def _attr_id(icd: str) -> str:
    return f"{icd.lower().replace('.', '_')}_onset"


def test_all_thirty_adult_chronic_onset_yamls_registered():
    specs = load_attribute_specs()
    missing = [_attr_id(icd) for icd in EXPECTED_30 if _attr_id(icd) not in specs]
    assert not missing, f"missing event attribute yamls: {missing}"


def test_every_chronic_onset_event_is_age_gated_18_plus():
    """All 30 migrated events are adult-only (age-band lo >= 18)."""
    specs = load_attribute_specs()
    for icd in EXPECTED_30:
        attr_id = _attr_id(icd)
        spec = specs[attr_id]
        lo, _hi = spec.clinical_scope.requires_age_band
        assert lo >= 18, f"{attr_id} is not adult-only (lo={lo})"


def test_event_requires_adult_age_band():
    """Review Focus #1: pediatric person (age<18) does not acquire adult
    chronic conditions via a migrated event yaml."""
    specs = load_attribute_specs()
    i10 = specs["i10_onset"]
    assert i10.clinical_scope.requires_age_band[0] == 18


def test_event_does_not_refire_when_already_held():
    """Review Focus #4: EventSpec one_shot: True + chronic_conditions
    dedup prevents re-fire. Verified against i10_onset yaml."""
    from clinosim.modules.longitudinal.patterns.event import step

    specs = load_attribute_specs()
    body = specs["i10_onset"].body
    rng = np.random.default_rng(3)  # draws 0.0856 — would fire at any adult band
    result = step(
        person_chronic=["I10"],
        prev_history=[],
        rng=rng,
        spec=body,
        context={"continuous": {}, "age": 70, "chronic_conditions": ["I10"]},
    )
    assert result.fired is False


def test_sex_locked_onset_yamls_declare_requires_sex():
    """N40 (BPH, male) and C61 (prostate, male) must carry
    `clinical_scope.requires_sex: M` so the engine excludes females."""
    specs = load_attribute_specs()
    assert specs["n40_onset"].clinical_scope.requires_sex == "M"
    assert specs["c61_onset"].clinical_scope.requires_sex == "M"
