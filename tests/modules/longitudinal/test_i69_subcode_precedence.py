"""Sub-code precedence for I69 Markov attributes (Phase 2 Task 5, Review Focus #2 & #5).

A person with chronic_conditions=["I69.3"] must advance under the
sub-code I69.3 attribute, not the base I69 fallback. A person with
chronic_conditions=["I69"] (bare, no sub) advances under the base.
Both attributes target the same icd_base "I69" family, so the engine
MUST select ONE per person per year via longest-prefix match on
requires_chronic_codes vs chronic_conditions.

Test shape: both yamls share icd_base "I69" and set up a sentinel
state ``WRONG`` that only the base yaml transitions into. Filenames
are chosen so the BASE yaml sorts alphabetically AFTER the sub-code
yaml — so without longest-prefix selection, the base yaml's write
would run second and overwrite the sub-code result with ``WRONG``
for the I69.3-carrying person. Proper selection runs only the
sub-code yaml for ["I69.3"].
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

_SUB_YAML = """\
attribute_id: stroke_sequela_stage_i69_3
pattern: markov
depends_on: []
clinical_scope:
  requires_chronic_codes: ["I69.3"]
  requires_age_band: [0, 120]
state_name: stroke_sequela_stage
icd_base: I69
states: ["mRS 0", "mRS 1", "WRONG"]
initial_distribution:
  "mRS 0": 1.0
transitions:
  "mRS 0": {"mRS 1": 1.0}
  "mRS 1": {}
  "WRONG": {}
"""

# Base yaml advances aggressively to a sentinel 'WRONG' state. If
# longest-prefix selection is wrong, the base yaml runs after the sub
# for an I69.3 person and overwrites to WRONG.
_BASE_YAML = """\
attribute_id: stroke_sequela_stage_zzz_i69_base
pattern: markov
depends_on: []
clinical_scope:
  requires_chronic_codes: ["I69"]
  requires_age_band: [0, 120]
state_name: stroke_sequela_stage
icd_base: I69
states: ["mRS 0", "mRS 1", "WRONG"]
initial_distribution:
  "mRS 0": 1.0
transitions:
  "mRS 0": {"WRONG": 1.0}
  "mRS 1": {"WRONG": 1.0}
  "WRONG": {}
"""


@pytest.fixture
def i69_family_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(loader_mod, "_LONGITUDINAL_DIR", tmp_path)
    load_attribute_specs.cache_clear()
    # Filenames: 'aaa_...' < 'zzz_...' so sub yaml loads BEFORE base. Without
    # longest-prefix selection, base runs second and wins (writes WRONG).
    (tmp_path / "aaa_stroke_sequela_i69_3.yaml").write_text(_SUB_YAML, encoding="utf-8")
    (tmp_path / "zzz_stroke_sequela_i69_base.yaml").write_text(_BASE_YAML, encoding="utf-8")
    yield tmp_path
    load_attribute_specs.cache_clear()


def _mk_person(chronic: list[str], person_id: str) -> PersonRecord:
    return PersonRecord(
        person_id=person_id,
        household_id="HH",
        age=70,
        sex="M",
        date_of_birth=date(1954, 6, 1),
        chronic_conditions=chronic,
    )


@pytest.mark.unit
def test_i69_subcode_selects_subcode_attribute(i69_family_loader: Path) -> None:
    """Review Focus #2: ["I69.3"] person uses sub-code yaml, not base.

    Without selection, base runs after sub and writes WRONG. With
    longest-prefix selection, only sub runs → mRS 1.
    """
    person = _mk_person(["I69.3"], "P_SUB")
    rng = np.random.default_rng(0)
    initial_snapshot(person, year=2024, init_rng=rng)
    snap = advance_one_year(person, year=2025, year_rng=rng)
    assert snap.chronic_stages["I69"] == "mRS 1", (
        f"expected sub-code outcome 'mRS 1', got {snap.chronic_stages['I69']!r} — "
        f"base-code yaml leaked WRONG, longest-prefix selection missing"
    )


@pytest.mark.unit
def test_i69_bare_base_code_selects_base_attribute(i69_family_loader: Path) -> None:
    """Review Focus #5: ["I69"] person uses base yaml only.

    Sub-code is out of scope (requires_chronic_codes=["I69.3"] does
    not match bare "I69"). Base runs → WRONG state.
    """
    person = _mk_person(["I69"], "P_BASE")
    rng = np.random.default_rng(0)
    initial_snapshot(person, year=2024, init_rng=rng)
    snap = advance_one_year(person, year=2025, year_rng=rng)
    assert snap.chronic_stages["I69"] == "WRONG", snap
