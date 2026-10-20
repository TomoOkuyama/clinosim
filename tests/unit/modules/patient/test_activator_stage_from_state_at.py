"""Phase 2 Task 8 — activator stage-string reads from `state_at`.

The activator populates ``ChronicCondition.stage`` for each ICD at
Layer-2 activation. Phase 2 flips the source of truth: stage comes
from the longitudinal engine's ``state_at(person, as_of_year)
.chronic_stages[code_base]`` rather than the retired
``person.disease_stages`` dict.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.longitudinal.snapshot import YearSnapshot
from clinosim.modules.patient.activator import _derive_chronic_conditions
from clinosim.types.population import PersonRecord


@pytest.mark.unit
def test_derive_chronic_conditions_reads_stage_from_longitudinal_engine():
    """A person with longitudinal_history carrying chronic_stages["N18"]="CKD G3b"
    at year 2024 must produce a ChronicCondition with stage="CKD G3b" when
    the activator runs with as_of_year=2024."""
    person = PersonRecord(
        person_id="P1",
        household_id="HH",
        age=70,
        sex="M",
        date_of_birth=date(1954, 6, 1),
        chronic_conditions=["N18"],
        longitudinal_history=[
            YearSnapshot(year=2024, chronic_stages={"N18": "CKD G3b"}),
        ],
    )
    rng = np.random.default_rng(0)
    out = _derive_chronic_conditions(person, rng, as_of_year=2024)
    assert len(out) == 1
    cond = out[0]
    assert cond.code == "N18"
    assert cond.stage == "CKD G3b", f"got stage={cond.stage!r}"


@pytest.mark.unit
def test_derive_chronic_conditions_returns_empty_stage_when_pre_scope():
    """If the person's history starts at year 2026 and the activator asks
    for year 2024 (pre-condition), the stage comes back empty — the
    person did not yet carry the stage at that year."""
    person = PersonRecord(
        person_id="P2",
        household_id="HH",
        age=70,
        sex="M",
        date_of_birth=date(1954, 6, 1),
        chronic_conditions=["N18"],
        longitudinal_history=[
            YearSnapshot(year=2026, chronic_stages={"N18": "CKD G1"}),
        ],
    )
    rng = np.random.default_rng(0)
    out = _derive_chronic_conditions(person, rng, as_of_year=2024)
    assert out[0].stage == "", f"expected empty, got {out[0].stage!r}"
