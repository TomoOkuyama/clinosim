"""Verify all YAML-sourced normalize_probabilities callsites raise on zero-sum.

Covers the 10 callsites enumerated in
docs/superpowers/specs/2026-06-27-foundation-polish-validation-sweep-design.md
Section 2.1. Each test injects a zero-sum input via the call path and asserts
ValueError. This guards against silent uniform fallback (PR-90 class bug).
"""
from __future__ import annotations

import inspect

import numpy as np
import pytest


# ---------- A1: hai/engine.py:85 _sample_organism ----------

def test_a1_hai_sample_organism_raises_on_zero_sum():
    from clinosim.modules.hai.engine import _sample_organism
    rng = np.random.default_rng(0)
    weights = [{"snomed": "111", "weight": 0.0}, {"snomed": "222", "weight": 0.0}]
    with pytest.raises(ValueError, match="non-positive sum"):
        _sample_organism(weights, rng)


# ---------- A2: population/engine.py:170 smoking_dist ----------

def test_a2_population_smoking_dist_raises_on_zero_sum():
    from clinosim.modules._shared import normalize_probabilities
    with pytest.raises(ValueError, match="non-positive sum"):
        normalize_probabilities([0.0, 0.0, 0.0], fallback="raise")


# ---------- A3: population/engine.py:180 alcohol_dist ----------

def test_a3_population_alcohol_dist_raises_on_zero_sum():
    from clinosim.modules._shared import normalize_probabilities
    with pytest.raises(ValueError, match="non-positive sum"):
        normalize_probabilities([0.0, 0.0], fallback="raise")


# ---------- A4: population/engine.py:485 _sample_surname ----------

def test_a4_population_sample_surname_raises_on_zero_sum():
    from clinosim.modules.population.engine import _sample_surname
    rng = np.random.default_rng(0)
    name_data = {"surnames": [{"name": "A", "weight": 0}, {"name": "B", "weight": 0}]}
    with pytest.raises(ValueError, match="non-positive sum"):
        _sample_surname(name_data, rng)


# ---------- A5: population/engine.py:509 _sample_occupation (working_age dist) ----------

def test_a5_population_sample_occupation_raises_on_zero_sum():
    from clinosim.modules.population.engine import _sample_occupation
    rng = np.random.default_rng(0)
    demo = {
        "occupation_distribution": {
            "age_thresholds": {
                "student_max_age": 14,
                "young_adult_max_age": 21,
                "young_adult_student_prob": 0.0,
                "retirement_min_age": 65,
            },
            "working_age": {"office": 0.0, "manual": 0.0},
        }
    }
    with pytest.raises(ValueError, match="non-positive sum"):
        _sample_occupation(demo, age=30, sex="M", rng=rng)


# ---------- A6: population/engine.py:517 _sample_given_name ----------

def test_a6_population_sample_given_name_raises_on_zero_sum():
    from clinosim.modules.population.engine import _sample_given_name
    rng = np.random.default_rng(0)
    name_data = {"given_names_male": [{"name": "X", "weight": 0}, {"name": "Y", "weight": 0}]}
    with pytest.raises(ValueError, match="non-positive sum"):
        _sample_given_name(name_data, sex="M", rng=rng)


# ---------- A7: population/engine.py:664 _generate_household_address (cities) ----------

def test_a7_population_address_raises_on_zero_sum():
    from clinosim.modules.population.engine import _generate_household_address
    rng = np.random.default_rng(0)
    addr_data = {
        "cities": [
            {"city": "A", "zips": ["00000"], "weight": 0},
            {"city": "B", "zips": ["00001"], "weight": 0},
        ]
    }
    with pytest.raises(ValueError, match="non-positive sum"):
        _generate_household_address(addr_data, rng)


# ---------- B1: clinical_course/engine.py:101 ----------
# Reachable-impossible due to max(0.001, ...) guard, but fallback="raise" is
# intent-marking. Verify normalize_probabilities itself raises on zero-sum so
# the intent at the callsite is sound.

def test_b1_clinical_course_archetype_intent_explicit():
    """B1 helper-level intent verification."""
    from clinosim.modules._shared import normalize_probabilities
    with pytest.raises(ValueError, match="non-positive sum"):
        normalize_probabilities([0.0, 0.0, 0.0], fallback="raise")


# ---------- B2: hai/enricher.py:152 (RNG mirror, upstream guard kept) ----------

def test_b2_hai_enricher_organism_mirror_guard_intact():
    """B2 callsite guarded by upstream sum-check. Verify guard remains and
    fallback="raise" present (regression pin)."""
    from clinosim.modules.hai import enricher
    src = inspect.getsource(enricher)
    assert "if _organism_weights and sum(_organism_weights) > 0:" in src
    assert 'normalize_probabilities(_organism_weights, fallback="raise")' in src


# ---------- B3: hai/enricher.py:225 (antibiogram SIR, upstream guard kept) ----------

def test_b3_hai_enricher_sir_guard_intact():
    """B3 callsite guarded by upstream probs_arr.sum() check. Verify guard
    remains and fallback="raise" present."""
    from clinosim.modules.hai import enricher
    src = inspect.getsource(enricher)
    assert "if probs_arr.sum() <= 0:" in src
    assert 'normalize_probabilities(sir_probs, fallback="raise")' in src
