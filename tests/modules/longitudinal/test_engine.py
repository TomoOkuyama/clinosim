"""Engine entry points — `advance_one_year`, `initial_snapshot`,
idempotency + backward-year guard + mid-sim scope entry.

See Phase 1 plan Task 4 brief + spec §5.1 for the signatures.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from clinosim.modules.longitudinal import loader as loader_mod
from clinosim.modules.longitudinal.engine import (
    advance_one_year,
    initial_snapshot,
)
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.types.population import PersonRecord

_HBA1C_YAML = """
attribute_id: hba1c
pattern: ar1
depends_on: []
clinical_scope:
  requires_chronic_codes: ["E11", "E10"]
  requires_age_band: [18, 120]
latent_name: hba1c
ar1:
  phi: 0.75
  sigma: 0.40
  mean_reversion_target: 7.3
clamp: [4.0, 15.0]
initial:
  mu: 1.95
  sigma: 0.17
  clamp: [4.5, 14.0]
per_encounter_noise:
  sigma: 0.20
"""

_SIM_SIGMA_ZERO_YAML = """
attribute_id: hba1c
pattern: ar1
depends_on: []
clinical_scope:
  requires_chronic_codes: ["E11", "E10"]
  requires_age_band: [18, 120]
latent_name: hba1c
ar1:
  phi: 1.0
  sigma: 0.0
  mean_reversion_target: 0.0
clamp: [-1000.0, 1000.0]
initial:
  mu: 2.0
  sigma: 0.0
  clamp: [-1000.0, 1000.0]
per_encounter_noise:
  sigma: 0.0
"""


@pytest.fixture
def hba1c_only_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install the standard hba1c yaml into an isolated loader dir."""
    monkeypatch.setattr(loader_mod, "_LONGITUDINAL_DIR", tmp_path)
    load_attribute_specs.cache_clear()
    (tmp_path / "hba1c_trajectory.yaml").write_text(_HBA1C_YAML, encoding="utf-8")
    return tmp_path


@pytest.fixture
def deterministic_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """phi=1 sigma=0 — deterministic AR(1) for exact assertions."""
    monkeypatch.setattr(loader_mod, "_LONGITUDINAL_DIR", tmp_path)
    load_attribute_specs.cache_clear()
    (tmp_path / "hba1c_trajectory.yaml").write_text(_SIM_SIGMA_ZERO_YAML, encoding="utf-8")
    return tmp_path


def _mk_person(*, chronic: list[str], age: int, person_id: str = "P1") -> PersonRecord:
    return PersonRecord(
        person_id=person_id,
        household_id="HH1",
        age=age,
        sex="M",
        date_of_birth=date(2024 - age, 6, 1),
        chronic_conditions=chronic,
    )


@pytest.mark.unit
def test_initial_snapshot_populates_hba1c_for_dm_person(hba1c_only_loader: Path) -> None:
    person = _mk_person(chronic=["E11.9"], age=55)
    rng = np.random.default_rng(42)
    snap = initial_snapshot(person, year=2021, init_rng=rng)
    assert snap.year == 2021
    assert "hba1c" in snap.continuous
    assert 4.5 <= snap.continuous["hba1c"] <= 14.0
    assert person.longitudinal_history == [snap]


@pytest.mark.unit
def test_initial_snapshot_omits_hba1c_for_non_dm_person(hba1c_only_loader: Path) -> None:
    person = _mk_person(chronic=["I10"], age=55)
    rng = np.random.default_rng(42)
    snap = initial_snapshot(person, year=2021, init_rng=rng)
    assert "hba1c" not in snap.continuous


@pytest.mark.unit
def test_advance_one_year_appends_and_returns_snapshot(hba1c_only_loader: Path) -> None:
    person = _mk_person(chronic=["E11.9"], age=55)
    initial_snapshot(person, year=2021, init_rng=np.random.default_rng(42))
    rng2 = np.random.default_rng(43)
    s1 = advance_one_year(person, year=2022, year_rng=rng2)
    assert s1.year == 2022
    assert person.longitudinal_history[-1] is s1
    assert len(person.longitudinal_history) == 2


@pytest.mark.unit
def test_advance_one_year_applies_ar1_step(deterministic_loader: Path) -> None:
    """phi=1 sigma=0 target=0 → h_next == h_prev."""
    person = _mk_person(chronic=["E11.9"], age=55)
    s0 = initial_snapshot(person, year=2021, init_rng=np.random.default_rng(0))
    prev = s0.continuous["hba1c"]
    s1 = advance_one_year(person, year=2022, year_rng=np.random.default_rng(0))
    assert s1.continuous["hba1c"] == pytest.approx(prev, abs=1e-9)


@pytest.mark.unit
def test_advance_one_year_raises_on_duplicate_year(hba1c_only_loader: Path) -> None:
    person = _mk_person(chronic=["E11.9"], age=55)
    initial_snapshot(person, year=2021, init_rng=np.random.default_rng(0))
    advance_one_year(person, year=2022, year_rng=np.random.default_rng(0))
    with pytest.raises(ValueError, match="already"):
        advance_one_year(person, year=2022, year_rng=np.random.default_rng(0))


@pytest.mark.unit
def test_advance_one_year_raises_on_backward_year(hba1c_only_loader: Path) -> None:
    """Review Focus 5. Year 5 then year 3 is a monotonicity break."""
    person = _mk_person(chronic=["E11.9"], age=55)
    initial_snapshot(person, year=2021, init_rng=np.random.default_rng(0))
    advance_one_year(person, year=2022, year_rng=np.random.default_rng(0))
    advance_one_year(person, year=2023, year_rng=np.random.default_rng(0))
    with pytest.raises(ValueError, match="backward|monotonic|prior"):
        advance_one_year(person, year=2021, year_rng=np.random.default_rng(0))


@pytest.mark.unit
def test_advance_one_year_requires_non_empty_state_history(hba1c_only_loader: Path) -> None:
    person = _mk_person(chronic=["E11.9"], age=55)
    with pytest.raises(ValueError, match="initial_snapshot|empty"):
        advance_one_year(person, year=2022, year_rng=np.random.default_rng(0))


@pytest.mark.unit
def test_mid_sim_scope_entry_starts_hba1c_latent(hba1c_only_loader: Path) -> None:
    """Review Focus 3. Non-DM at year 0 → add E11 before year 1
    advance → year-1 snapshot has `hba1c`."""
    person = _mk_person(chronic=["I10"], age=55)
    initial_snapshot(person, year=2021, init_rng=np.random.default_rng(0))
    assert "hba1c" not in person.longitudinal_history[0].continuous

    person.chronic_conditions.append("E11.9")
    s1 = advance_one_year(person, year=2022, year_rng=np.random.default_rng(1))
    assert "hba1c" in s1.continuous
    assert 4.5 <= s1.continuous["hba1c"] <= 14.0


@pytest.mark.unit
def test_initial_snapshot_raises_if_already_populated(hba1c_only_loader: Path) -> None:
    person = _mk_person(chronic=["E11.9"], age=55)
    initial_snapshot(person, year=2021, init_rng=np.random.default_rng(0))
    with pytest.raises(ValueError, match="already"):
        initial_snapshot(person, year=2021, init_rng=np.random.default_rng(0))
