"""Topo-order contract: events depending on AR1 latents read the same-year value (Phase 3 Task 4).

Guards against a dispatch regression where events might read the prior-
year AR1 snapshot instead of the current-year latent. The engine's
topological sort over `depends_on` must schedule `hba1c` before any
event with `depends_on: [hba1c]`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from clinosim.modules.longitudinal import loader as loader_mod
from clinosim.modules.longitudinal.engine import initial_snapshot
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.types.population import PersonRecord

# Deterministic AR1: phi=1.0, sigma=0, so step() always returns the
# mean_reversion_target=10.0 regardless of prior value.
_HBA1C_FIXED_YAML = """\
attribute_id: hba1c
pattern: ar1
depends_on: []
clinical_scope:
  requires_chronic_codes: ["E11", "E10"]
  requires_age_band: [0, 120]
latent_name: hba1c
ar1:
  phi: 1.0
  sigma: 0.0
  mean_reversion_target: 10.0
clamp: [4.0, 15.0]
initial:
  mu: 2.303   # exp(2.303) ≈ 10.0
  sigma: 0.0
  clamp: [4.0, 15.0]
"""

# Event depends on hba1c; fires only when hba1c > 9.0 (modifier factor=1000
# ensures effectively 100 % fire if the condition is met).
_EVENT_READS_HBA1C_YAML = """\
attribute_id: test_dm_event
pattern: event
depends_on: [hba1c]
clinical_scope:
  requires_chronic_codes: ["E11"]
  requires_age_band: [0, 120]
event_name: test_dm_event
emits_icd: E11.21
base_annual_rate: 0.001
rate_modifiers:
  - when: {attribute: hba1c, operator: ">", value: 9.0}
    factor: 1000.0
one_shot: true
"""


@pytest.fixture
def hba1c_and_event_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(loader_mod, "_LONGITUDINAL_DIR", tmp_path)
    load_attribute_specs.cache_clear()
    (tmp_path / "hba1c.yaml").write_text(_HBA1C_FIXED_YAML, encoding="utf-8")
    (tmp_path / "test_event.yaml").write_text(_EVENT_READS_HBA1C_YAML, encoding="utf-8")
    yield tmp_path
    load_attribute_specs.cache_clear()


@pytest.mark.unit
def test_event_sees_same_year_ar1_latent(hba1c_and_event_loader: Path) -> None:
    """At initial_snapshot: hba1c runs first (depends_on=[]), fills
    continuous["hba1c"]=10.0; event then reads context and fires because
    10.0 > 9.0 modifier triggers at 1000× base rate (clamped to 1.0)."""
    person = PersonRecord(
        person_id="P1",
        household_id="HH",
        age=55,
        sex="M",
        date_of_birth=date(1970, 1, 1),
        chronic_conditions=["E11.9"],
    )
    rng = np.random.default_rng(0)
    snap = initial_snapshot(person, year=2024, init_rng=rng)
    assert snap.continuous.get("hba1c") == pytest.approx(10.0, abs=0.01), snap
    assert snap.new_complications == ["E11.21"], (
        f"event did not fire; new_complications={snap.new_complications!r} — "
        f"topo order may be reading prior-year AR1 instead of same-year"
    )
