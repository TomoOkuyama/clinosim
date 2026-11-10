"""Country parameters come from locale YAML, not Python constants (Issue #3142;
docs/design-guides/country-profile-spec.md §7 step 3).

The values are pinned to what the removed Python constants held, so the move
is byte-identical.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from clinosim.locale.loader import load_care_practice, load_population_genetics
from clinosim.locale.loaders.country_parameters import CarePractice
from clinosim.modules.identity.providers.jp import JPIdentityProvider
from clinosim.modules.identity.providers.us import USIdentityProvider
from clinosim.modules.population._demographics import _derive_rh_factor
from clinosim.modules.population.inheritance import derive_newborn_rh_factor
from clinosim.modules.procedure.engine import generate_rehab_sessions
from clinosim.simulator.discharge_gate import _check_discharge_ready
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


def test_discharge_criteria() -> None:
    us = load_care_practice("US").discharge_criteria
    jp = load_care_practice("JP").discharge_criteria
    assert (us.inflammation_max, us.perfusion_min, us.renal_min, us.volume_abs_max, us.ph_abs_max) == (
        0.10,
        0.7,
        0.5,
        0.3,
        0.2,
    )
    assert (jp.inflammation_max, jp.perfusion_min, jp.renal_min, jp.volume_abs_max, jp.ph_abs_max) == (
        0.05,
        0.8,
        0.6,
        0.2,
        0.15,
    )


def test_discharge_gate_reads_the_country_criteria() -> None:
    # inflammation 0.07: under the US ceiling (0.10), over the JP one (0.05).
    state = PhysiologicalState(inflammation_level=0.07)
    assert _check_discharge_ready(state, 5, "us")
    assert not _check_discharge_ready(state, 5, "japan")


def test_time_to_surgery_and_rehab_session() -> None:
    us, jp = load_care_practice("US"), load_care_practice("JP")
    assert (us.time_to_surgery_hours.mean, us.time_to_surgery_hours.sd, us.time_to_surgery_hours.floor) == (
        24.0,
        12.0,
        6.0,
    )
    assert (jp.time_to_surgery_hours.mean, jp.time_to_surgery_hours.sd, jp.time_to_surgery_hours.floor) == (
        48.0,
        24.0,
        12.0,
    )
    assert (us.rehab_session_minutes, jp.rehab_session_minutes) == (30, 40)


def test_rehab_sessions_use_the_country_length() -> None:
    from datetime import datetime

    for country, minutes in (("US", 30), ("JP", 40)):
        sessions = generate_rehab_sessions("P", "E", datetime(2026, 1, 1, 9), 6, np.random.default_rng(0), country)
        assert sessions and {s.duration_minutes for s in sessions} == {minutes}


def test_population_genetics() -> None:
    us, jp = load_population_genetics("US"), load_population_genetics("JP")
    assert (us.rh_positive_fraction, jp.rh_positive_fraction) == (0.85, 0.995)
    assert us.abo_allele_frequencies == {"A": 0.264, "B": 0.071, "O": 0.665}
    assert jp.abo_allele_frequencies == {"A": 0.279, "B": 0.169, "O": 0.552}
    assert us.drug_metabolism_phenotypes == {"poor": 0.07, "normal": 0.70, "rapid": 0.15, "ultra_rapid": 0.08}
    assert jp.drug_metabolism_phenotypes == {"poor": 0.15, "normal": 0.65, "rapid": 0.15, "ultra_rapid": 0.05}


def test_rh_factor_reads_the_country_fraction() -> None:
    ids = [f"P{i}" for i in range(2000)]
    us_neg = sum(_derive_rh_factor(i, "US") == "-" for i in ids)
    jp_neg = sum(_derive_rh_factor(i, "JP") == "-" for i in ids)
    assert 200 < us_neg < 400 and jp_neg < 30
    assert derive_newborn_rh_factor("B1", "+", "japan") == derive_newborn_rh_factor("B1", "+", "JP")


@pytest.mark.parametrize("unknown", ["FR", ""])
def test_unknown_country_raises(unknown: str) -> None:
    with pytest.raises(KeyError):
        load_care_practice(unknown)
    with pytest.raises(KeyError):
        load_population_genetics(unknown)


def test_unknown_keys_are_rejected() -> None:
    data = load_care_practice("US").model_dump()
    data["surprise"] = 1
    with pytest.raises(ValidationError):
        CarePractice.model_validate(data)


def _member(pid: str, age: int, occupation: str = "office") -> SimpleNamespace:
    return SimpleNamespace(person_id=pid, age=age, occupation=occupation)


def test_jp_late_elderly_gate_is_read_from_identity_config() -> None:
    from clinosim.locale.loader import load_identity_config

    config = load_identity_config("JP")
    members = [_member("a", 74), _member("b", 76)]
    base = JPIdentityProvider().assign_household(members, np.random.default_rng(1), config)
    assert base["b"].category == "late_elderly" and base["a"].category != "late_elderly"
    moved = dict(config, age_gates={**config["age_gates"], "late_elderly_min_age": 70})
    shifted = JPIdentityProvider().assign_household(members, np.random.default_rng(1), moved)
    assert shifted["a"].category == "late_elderly"


def test_us_medicare_gate_is_read_from_identity_config() -> None:
    from clinosim.locale.loader import load_identity_config

    config = load_identity_config("US")
    assert config["age_gates"]["medicare_min_age"] == 65
    members = [_member("a", 66)]
    out = USIdentityProvider().assign_household(members, np.random.default_rng(3), config)
    assert out["a"].category.startswith("medicare")
