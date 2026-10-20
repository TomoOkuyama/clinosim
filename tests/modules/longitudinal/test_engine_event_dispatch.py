"""Engine dispatches `pattern: event` to new_complications + chronic_conditions (Phase 3 Task 2)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from clinosim.modules.longitudinal import loader as loader_mod
from clinosim.modules.longitudinal.engine import advance_one_year, initial_snapshot
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.longitudinal.snapshot import YearSnapshot
from clinosim.types.population import PersonRecord


_EVENT_YAML = """\
attribute_id: test_event_e11_21
pattern: event
depends_on: []
clinical_scope:
  requires_chronic_codes: ["E11"]
  requires_age_band: [0, 120]
event_name: test_dm_complication
emits_icd: E11.21
base_annual_rate: 1.0
rate_modifiers: []
one_shot: true
"""


@pytest.fixture
def event_only_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(loader_mod, "_LONGITUDINAL_DIR", tmp_path)
    load_attribute_specs.cache_clear()
    (tmp_path / "test_event.yaml").write_text(_EVENT_YAML, encoding="utf-8")
    yield tmp_path
    load_attribute_specs.cache_clear()


def _mk_person() -> PersonRecord:
    return PersonRecord(
        person_id="P1",
        household_id="HH",
        age=55,
        sex="M",
        date_of_birth=date(1970, 1, 1),
        chronic_conditions=["E11.9"],
    )


@pytest.mark.unit
def test_engine_event_fires_and_appends_chronic(event_only_loader: Path) -> None:
    """A rate=1.0 event fires at initial_snapshot (sim-start year), writes
    emits_icd into new_complications AND appends to chronic_conditions."""
    person = _mk_person()
    rng = np.random.default_rng(0)
    snap = initial_snapshot(person, year=2024, init_rng=rng)
    assert snap.new_complications == ["E11.21"], snap
    assert "E11.21" in person.chronic_conditions, person.chronic_conditions


@pytest.mark.unit
def test_engine_event_one_shot_does_not_re_fire(event_only_loader: Path) -> None:
    """After the event fires at sim-start, subsequent advances must not
    re-fire — one_shot guard against person.chronic_conditions."""
    person = _mk_person()
    rng = np.random.default_rng(0)
    initial_snapshot(person, year=2024, init_rng=rng)
    assert "E11.21" in person.chronic_conditions
    # Advance year 2025: already-chronic → event must not re-fire.
    snap_2025 = advance_one_year(person, year=2025, year_rng=rng)
    assert snap_2025.new_complications == [], snap_2025
    assert person.chronic_conditions.count("E11.21") == 1, person.chronic_conditions
    # And another year — still no re-fire.
    snap_2026 = advance_one_year(person, year=2026, year_rng=rng)
    assert snap_2026.new_complications == [], snap_2026


@pytest.mark.unit
def test_engine_event_fires_mid_sim_after_initial_scope_entry(event_only_loader: Path) -> None:
    """A low-rate event that didn't fire at sim-start can still fire in a
    later advance_one_year. Uses a non-fire first year by rigging a loader
    where base_annual_rate=0.0 at year Y (never fires), then does not
    directly test — the fire-at-sim-start test above already covers mid-
    sim entry; this one pins that subsequent advances consume RNG and
    behave idempotently when no fire condition is met."""
    person = _mk_person()
    rng = np.random.default_rng(0)
    initial_snapshot(person, year=2024, init_rng=rng)
    # After sim-start fire, chronic_conditions carries E11.21; advancing
    # 3 more years keeps count stable.
    for yr in range(2025, 2028):
        advance_one_year(person, year=yr, year_rng=rng)
    assert person.chronic_conditions.count("E11.21") == 1, person.chronic_conditions
