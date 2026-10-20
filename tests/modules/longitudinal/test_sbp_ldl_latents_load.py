"""Phase 4b.1 — new AR(1) latents (SBP, LDL) load with expected parameters."""

from __future__ import annotations

from datetime import date

import numpy as np

from clinosim.modules.longitudinal import engine as le
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.types.population import PersonRecord


def test_sbp_latent_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "sbp" in specs
    spec = specs["sbp"]
    assert spec.pattern == "ar1"
    assert spec.body.latent_name == "sbp"
    assert spec.body.phi == 0.80
    assert spec.body.sigma == 8.0
    assert spec.body.mean_reversion_target == 145.0
    assert spec.body.clamp == [90.0, 220.0]
    assert spec.clinical_scope.requires_chronic_codes == ["I1"]
    assert spec.clinical_scope.requires_age_band == [18, 120]


def test_sbp_latent_out_of_scope_for_non_htn_person():
    """A non-HTN person's longitudinal history must NOT carry an 'sbp'
    key — the scope gate drops the attribute before any RNG draw."""
    load_attribute_specs.cache_clear()
    p = PersonRecord(
        person_id="PX",
        household_id="HX",
        age=45,
        sex="M",
        date_of_birth=date(1980, 1, 1),
        chronic_conditions=["E11.9"],
    )
    snap = le.initial_snapshot(p, 2024, np.random.default_rng(0))
    assert "sbp" not in snap.continuous


def test_ldl_latent_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "ldl" in specs
    spec = specs["ldl"]
    assert spec.pattern == "ar1"
    assert spec.body.latent_name == "ldl"
    assert spec.body.phi == 0.80
    assert spec.body.sigma == 12.0
    assert spec.body.mean_reversion_target == 165.0
    assert spec.body.clamp == [60.0, 300.0]
    assert spec.clinical_scope.requires_chronic_codes == ["E78"]
    assert spec.clinical_scope.requires_age_band == [18, 120]


def test_ldl_latent_out_of_scope_for_non_dyslipidemia_person():
    """Review Focus #2: non-E78 person's longitudinal history must NOT
    carry an 'ldl' key — scope gate drops attribute, zero RNG draw."""
    load_attribute_specs.cache_clear()
    p = PersonRecord(
        person_id="PX",
        household_id="HX",
        age=45,
        sex="M",
        date_of_birth=date(1980, 1, 1),
        chronic_conditions=["E11.9"],
    )
    snap = le.initial_snapshot(p, 2024, np.random.default_rng(0))
    assert "ldl" not in snap.continuous
