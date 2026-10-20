"""Phase 2 Task 7 — multiplier_fn kwarg threaded through advance_one_year.

The engine accepts an optional callable
``multiplier_fn(person, icd_base, year) -> float`` and passes the
returned multiplier into ``markov.step`` so Markov stage advance is
scaled per-person per-icd. Phase 2 wires
``aging._comorbidity_multiplier`` as the real callable.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from clinosim.modules.longitudinal import loader as loader_mod
from clinosim.modules.longitudinal.engine import advance_one_year, initial_snapshot
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.types.population import PersonRecord

# Base p=0.1 CKD advance; a multiplier of 3.0 → 0.3 effective rate.
_CKD_YAML = """\
attribute_id: ckd_stage_n18_mult_test
pattern: markov
depends_on: []
clinical_scope:
  requires_chronic_codes: ["N18"]
  requires_age_band: [0, 120]
state_name: ckd_stage
icd_base: N18
states: ["CKD G1", "CKD G2"]
initial_distribution:
  "CKD G1": 1.0
transitions:
  "CKD G1": {"CKD G2": 0.1}
  "CKD G2": {}
"""


@pytest.fixture
def ckd_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(loader_mod, "_LONGITUDINAL_DIR", tmp_path)
    load_attribute_specs.cache_clear()
    (tmp_path / "ckd.yaml").write_text(_CKD_YAML, encoding="utf-8")
    yield tmp_path
    load_attribute_specs.cache_clear()


def _mk_person(pid: str) -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id="HH",
        age=70,
        sex="M",
        date_of_birth=date(1954, 6, 1),
        chronic_conditions=["N18"],
    )


@pytest.mark.unit
def test_advance_one_year_applies_multiplier_fn(ckd_loader: Path) -> None:
    """Across many seeds, advance rate ≈ 3.0 × 0.1 = 0.3 under multiplier 3.0."""
    hits = 0
    trials = 2000
    for seed in range(trials):
        person = _mk_person(f"P{seed}")
        rng = np.random.default_rng(seed)
        initial_snapshot(person, year=2024, init_rng=rng)
        advance_one_year(
            person,
            year=2025,
            year_rng=rng,
            multiplier_fn=lambda person, icd, year: 3.0,
        )
        if person.longitudinal_history[-1].chronic_stages["N18"] == "CKD G2":
            hits += 1
    rate = hits / trials
    assert 0.26 < rate < 0.34, f"expected ~0.30 under multiplier 3.0 × base 0.1, got {rate:.3f}"


@pytest.mark.unit
def test_advance_one_year_without_multiplier_uses_base_rate(ckd_loader: Path) -> None:
    """No multiplier_fn → rate ≈ 0.1 (base)."""
    hits = 0
    trials = 2000
    for seed in range(trials):
        person = _mk_person(f"P{seed}")
        rng = np.random.default_rng(seed)
        initial_snapshot(person, year=2024, init_rng=rng)
        advance_one_year(person, year=2025, year_rng=rng)
        if person.longitudinal_history[-1].chronic_stages["N18"] == "CKD G2":
            hits += 1
    rate = hits / trials
    assert 0.07 < rate < 0.13, f"expected ~0.10 base rate, got {rate:.3f}"
