"""Opt-in RNG-isolated disease incidence leaves existing events untouched (#2044)."""

from __future__ import annotations

import copy

import pytest

from clinosim import determinism
from clinosim.modules.population.engine import _load_demographics, generate_monthly_events, generate_population

pytestmark = pytest.mark.unit

_NEW = "elective_knee_arthroplasty"


def _events(demo: dict, seed: int = 11) -> list:
    registry = generate_population(1500, "US", determinism.default_rng(3), demo=demo)
    out = []
    for month in (1, 2, 3):
        out += generate_monthly_events(
            registry, 2025, month, determinism.default_rng(seed + month), country="US", demo=demo, master_seed=seed
        )
    return out


def _key(e) -> tuple:
    return (e.person_id, e.timestamp, e.disease_id, e.severity, e.requires_hospital)


def test_isolated_disease_adds_events_without_shifting_others() -> None:
    base_demo = copy.deepcopy(_load_demographics("US"))
    base_demo["disease_incidence"].pop(_NEW, None)
    with_new = copy.deepcopy(base_demo)
    with_new["disease_incidence"][_NEW] = {
        "age_rates": {50: 60000},
        "event_type": "elective_admission",
        "prerequisite_condition": "M17",
        "always_hospitalize": True,
        "rng_isolated": True,
    }
    before = [_key(e) for e in _events(base_demo)]
    after = _events(with_new)
    assert [_key(e) for e in after if e.disease_id != _NEW] == before
    added = [e for e in after if e.disease_id == _NEW]
    assert added and all(e.requires_hospital for e in added)


def test_isolated_draws_depend_on_master_seed() -> None:
    demo = copy.deepcopy(_load_demographics("US"))
    demo["disease_incidence"][_NEW] = {
        "age_rates": {50: 60000},
        "prerequisite_condition": "M17",
        "always_hospitalize": True,
        "rng_isolated": True,
    }
    a = {(e.person_id, e.timestamp) for e in _events(demo, seed=11) if e.disease_id == _NEW}
    b = {(e.person_id, e.timestamp) for e in _events(demo, seed=12) if e.disease_id == _NEW}
    assert a != b
