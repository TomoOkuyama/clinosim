"""Phase 2 Task 6 — mid-sim scope entry for Markov attributes.

Original Review Focus #1 phrasing presumed the activator pre-seeded
``ChronicCondition.stage`` before ``initial_snapshot`` ran. In the
actual Phase 1+ data flow that cannot happen: ``initial_snapshot`` is
called at Layer-1 generation (``population.engine``) BEFORE the
activator populates ``PatientProfile.chronic_conditions`` objects,
and ``PersonRecord.chronic_conditions`` carries only the ICD code
string (no stage).

What matters instead is mid-sim scope entry: a person who gains a
chronic ICD at year Y+2 via ``_annual_chronic_onset`` (aging pass)
must have ``advance_one_year`` draw the initial stage from the yaml's
``initial_distribution`` on the first exposure. The engine's
``_apply_pattern`` fall-through path (``prev_snapshot.chronic_stages``
has no entry for the icd_base) covers this.

See the plan's Task 6 Ruling in the Phase 2 progress ledger.
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


# Terminal yaml with p=0 anywhere, so after initial draw we observe the
# distribution's single mass without further movement.
_CKD_YAML_G3A_ONLY = """\
attribute_id: ckd_stage_n18_test
pattern: markov
depends_on: []
clinical_scope:
  requires_chronic_codes: ["N18"]
  requires_age_band: [0, 120]
state_name: ckd_stage
icd_base: N18
states: ["CKD G1", "CKD G2", "CKD G3a"]
initial_distribution:
  "CKD G3a": 1.0
transitions:
  "CKD G1": {}
  "CKD G2": {}
  "CKD G3a": {}
"""


@pytest.fixture
def ckd_only_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(loader_mod, "_LONGITUDINAL_DIR", tmp_path)
    load_attribute_specs.cache_clear()
    (tmp_path / "ckd_only.yaml").write_text(_CKD_YAML_G3A_ONLY, encoding="utf-8")
    yield tmp_path
    load_attribute_specs.cache_clear()


@pytest.mark.unit
def test_mid_sim_scope_entry_draws_initial_distribution(ckd_only_loader: Path) -> None:
    """A person who has NO N18 at sim-start (year 2024) advances through
    year 2025 with no stage set, then gains N18 at year 2026 and advances
    at year 2027 — the engine must draw from initial_distribution on
    first exposure, NOT raise or leave chronic_stages[icd_base] empty."""
    person = PersonRecord(
        person_id="P1",
        household_id="HH",
        age=70,
        sex="M",
        date_of_birth=date(1954, 6, 1),
        chronic_conditions=[],  # no N18 at sim start
    )
    rng = np.random.default_rng(0)
    snap_start = initial_snapshot(person, year=2024, init_rng=rng)
    assert "N18" not in snap_start.chronic_stages, snap_start

    # year 2025 — still no N18
    snap_2025 = advance_one_year(person, year=2025, year_rng=rng)
    assert "N18" not in snap_2025.chronic_stages, snap_2025

    # mid-sim onset: aging pass added N18 before year 2026 advance
    person.chronic_conditions.append("N18")

    # year 2026 — N18 now in scope, no prior stage: draw from initial_distribution
    snap_2026 = advance_one_year(person, year=2026, year_rng=rng)
    assert snap_2026.chronic_stages.get("N18") == "CKD G3a", (
        f"mid-sim scope entry failed; expected CKD G3a from init draw, "
        f"got {snap_2026.chronic_stages.get('N18')!r}"
    )
