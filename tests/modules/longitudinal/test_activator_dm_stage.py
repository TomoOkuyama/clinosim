"""Activator DM stage-string migration (line ~440).

The E11 / E10 branch of `_build_chronic_conditions` now reads
HbA1c from `state_at(person, as_of_year).continuous["hba1c"]`
instead of the retired `_glycemic_control_at_year` /
`hba1c_from_glycemic_control` chain.

See Phase 1 plan Task 9 brief.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.longitudinal.engine import initial_snapshot, state_at
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.patient import activator as activator_mod
from clinosim.types.patient import ChronicCondition
from clinosim.types.population import PersonRecord


@pytest.fixture(autouse=True)
def _clear_loader() -> None:
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


def _dm_person_with_history(hba1c_values: dict[int, float]) -> PersonRecord:
    """Build a person with E11 and a hand-set longitudinal_history."""
    years = sorted(hba1c_values)
    p = PersonRecord(
        person_id="dm-stage",
        household_id="HH",
        age=55,
        sex="M",
        date_of_birth=date(1970, 6, 1),
        chronic_conditions=["E11.9"],
    )
    initial_snapshot(p, year=years[0], init_rng=np.random.default_rng(0))
    p.longitudinal_history[0].continuous["hba1c"] = hba1c_values[years[0]]
    from clinosim.modules.longitudinal.engine import advance_one_year

    for y in years[1:]:
        advance_one_year(p, year=y, year_rng=np.random.default_rng(0))
        p.longitudinal_history[-1].continuous["hba1c"] = hba1c_values[y]
    return p


@pytest.mark.unit
def test_e11_stage_string_reads_from_longitudinal_history() -> None:
    """Pin: for E11 at as_of_year=2023 with longitudinal_history
    carrying hba1c=9.1 at 2023, stage string is 'HbA1c 9.1%'."""
    person = _dm_person_with_history({2021: 7.5, 2022: 8.2, 2023: 9.1})
    rng = np.random.default_rng(0)
    conditions = activator_mod._derive_chronic_conditions(
        person=person,
        rng=rng,
        as_of_year=2023,
    )
    e11 = next(c for c in conditions if c.code.startswith("E11"))
    assert e11.stage == "HbA1c 9.1%"


@pytest.mark.unit
def test_e11_stage_string_tracks_year() -> None:
    """Different year → different stage string from the same person."""
    person = _dm_person_with_history({2021: 6.5, 2022: 8.0, 2023: 10.2})
    conditions_2021 = activator_mod._derive_chronic_conditions(
        person=person,
        rng=np.random.default_rng(0),
        as_of_year=2021,
    )
    conditions_2023 = activator_mod._derive_chronic_conditions(
        person=person,
        rng=np.random.default_rng(0),
        as_of_year=2023,
    )
    e11_21 = next(c for c in conditions_2021 if c.code.startswith("E11"))
    e11_23 = next(c for c in conditions_2023 if c.code.startswith("E11"))
    assert e11_21.stage == "HbA1c 6.5%"
    assert e11_23.stage == "HbA1c 10.2%"


@pytest.mark.unit
def test_glycemic_control_at_year_helper_is_gone() -> None:
    """The retired helper must be absent — a surviving reference
    would silently use stale glycemic_trajectory data."""
    assert not hasattr(activator_mod, "_glycemic_control_at_year")


@pytest.mark.unit
def test_hba1c_from_glycemic_control_import_is_gone() -> None:
    """The activator module no longer imports hba1c_from_glycemic_control
    (physiology.engine still exports it for the protocol-override
    path at inpatient.py:627)."""
    import inspect

    src = inspect.getsource(activator_mod)
    assert "from clinosim.modules.physiology.engine import hba1c_from_glycemic_control" not in src
