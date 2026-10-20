"""Engine dispatches `pattern: markov` to YearSnapshot.chronic_stages (Phase 2 Task 2)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from clinosim.modules.longitudinal import loader as loader_mod
from clinosim.modules.longitudinal.engine import advance_one_year, initial_snapshot
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.types.population import PersonRecord


_MARKOV_YAML = """\
attribute_id: test_markov
pattern: markov
depends_on: []
clinical_scope:
  requires_chronic_codes: ["TEST"]
  requires_age_band: [0, 120]
state_name: test_stage
icd_base: TEST
states: ["A", "B"]
initial_distribution:
  A: 1.0
transitions:
  A: {B: 1.0}
  B: {}
"""


@pytest.fixture
def markov_only_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(loader_mod, "_LONGITUDINAL_DIR", tmp_path)
    load_attribute_specs.cache_clear()
    (tmp_path / "test_markov.yaml").write_text(_MARKOV_YAML, encoding="utf-8")
    yield tmp_path
    load_attribute_specs.cache_clear()


def _mk_person() -> PersonRecord:
    return PersonRecord(
        person_id="P1",
        household_id="HH1",
        age=55,
        sex="M",
        date_of_birth=date(1970, 6, 1),
        chronic_conditions=["TEST"],
    )


@pytest.mark.unit
def test_engine_dispatches_markov_to_chronic_stages(markov_only_loader: Path) -> None:
    person = _mk_person()
    rng = np.random.default_rng(0)
    snap0 = initial_snapshot(person, year=2024, init_rng=rng)
    assert snap0.chronic_stages == {"TEST": "A"}, snap0
    assert snap0.continuous == {}, snap0

    snap1 = advance_one_year(person, year=2025, year_rng=rng)
    assert snap1.chronic_stages == {"TEST": "B"}, snap1
    assert snap1.continuous == {}, snap1
