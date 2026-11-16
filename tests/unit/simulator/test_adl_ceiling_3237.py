"""Issue #3237: the inpatient Barthel Index respects the premorbid ceiling
set by a staged chronic functional condition (dementia CDR stage)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
from pydantic import ValidationError

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.simulator.adl_ceiling import (
    BARTHEL_ITEM_MAX,
    AdlCeilingRules,
    adl_ceiling_rules,
    barthel_item_caps,
)
from clinosim.simulator.vitals_pipeline import _generate_adl_assessment
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2025, 3, 1, 10)
_HEALTHY = PhysiologicalState(inflammation_level=0.0, perfusion_status=1.0, renal_function=1.0)


def _patient(age: int, *conditions: ChronicCondition) -> PatientProfile:
    return PatientProfile(patient_id="P1", sex="F", age=age, chronic_conditions=list(conditions))


def _dementia(stage: str) -> ChronicCondition:
    return ChronicCondition(code="F00", stage=stage)


def _items(adl) -> dict[str, int]:
    return {k: getattr(adl, k) for k in BARTHEL_ITEM_MAX}


@pytest.mark.parametrize("stage", ["CDR 1", "CDR 2", "CDR 3"])
@pytest.mark.parametrize("seed", range(20))
def test_dementia_patient_never_exceeds_the_stage_ceiling(stage: str, seed: int) -> None:
    caps = barthel_item_caps(_patient(60, _dementia(stage)))
    ceiling = sum(caps.values())
    assert ceiling < 100
    rng = np.random.default_rng(seed)
    for day in (0, 7, 14, 21, 28, 70):
        adl = _generate_adl_assessment(_HEALTHY, _patient(60, _dementia(stage)), day, _ADMIT, rng)
        assert adl is not None
        assert adl.barthel_score <= ceiling
        assert adl.barthel_score == sum(_items(adl).values())
        for k, v in _items(adl).items():
            assert v <= caps[k], (k, v, caps[k])


def test_cdr3_cannot_be_documented_continent_or_independent_in_self_care() -> None:
    caps = barthel_item_caps(_patient(80, _dementia("CDR 3")))
    assert caps["bathing"] == caps["grooming"] == caps["dressing"] == caps["toilet_use"] == 0
    assert caps["bladder_control"] == 0
    assert sum(caps.values()) <= sum(barthel_item_caps(_patient(80, _dementia("CDR 2"))).values())


def test_stage_ceilings_are_monotonic_in_cdr() -> None:
    totals = [
        sum(barthel_item_caps(_patient(80, _dementia(s))).values()) for s in ("CDR 0.5", "CDR 1", "CDR 2", "CDR 3")
    ]
    assert totals == sorted(totals, reverse=True)
    assert totals[0] == 100


# Outputs of master before Issue #3237 (seeded) — a patient without a
# staged functional condition is unchanged, draw for draw.
_PINNED = [
    (82, 0, 1, (65, 5, 5, 5, 5, 10, 5, 5, 10, 10, 5), 0.9504636963259353),
    (82, 7, 2, (100, 10, 5, 5, 10, 10, 10, 10, 15, 15, 10), 0.2984911434141233),
    (90, 14, 3, (100, 10, 5, 5, 10, 10, 10, 10, 15, 15, 10), 0.2368105065960997),
    (60, 21, 4, (95, 10, 5, 5, 10, 10, 10, 10, 15, 15, 5), 0.5113275528143616),
]


@pytest.mark.parametrize(("age", "day", "seed", "expected", "next_draw"), _PINNED)
@pytest.mark.parametrize(
    "conditions",
    [(ChronicCondition(code="E11.9", stage="HbA1c 7.2%"),), (_dementia("CDR 0.5"),), (ChronicCondition(code="F00"),)],
)
def test_patient_without_a_functional_ceiling_is_unchanged(age, day, seed, expected, next_draw, conditions) -> None:
    rng = np.random.default_rng(seed)
    state = PhysiologicalState(inflammation_level=0.3, perfusion_status=0.9, renal_function=0.8)
    adl = _generate_adl_assessment(state, _patient(age, *conditions), day, _ADMIT, rng)
    assert adl is not None
    assert (adl.barthel_score, *_items(adl).values()) == expected
    assert float(rng.random()) == next_draw


@pytest.mark.parametrize("seed", range(5))
def test_the_ceiling_consumes_the_same_draws(seed: int) -> None:
    a, b = np.random.default_rng(seed), np.random.default_rng(seed)
    _generate_adl_assessment(_HEALTHY, _patient(70), 7, _ADMIT, a)
    _generate_adl_assessment(_HEALTHY, _patient(70, _dementia("CDR 3")), 7, _ADMIT, b)
    assert float(a.random()) == float(b.random())


def test_every_dementia_stage_has_a_ceiling_entry() -> None:
    for rule in adl_ceiling_rules().conditions:
        body = load_attribute_specs()[rule.stage_attribute].body
        assert set(rule.item_caps_by_stage) == set(body.states)


def _rule(**over) -> dict:
    rule = {"stage_attribute": "dementia_stage_f00", "item_caps_by_stage": {"CDR 3": {"bathing": 0}}}
    rule.update(over)
    return {"conditions": [rule]}


@pytest.mark.parametrize(
    "bad",
    [
        _rule(stage_attribute="no_such_attribute"),
        _rule(item_caps_by_stage={"CDR 9": {"bathing": 0}}),
        _rule(item_caps_by_stage={"CDR 3": {"walking": 0}}),
        _rule(item_caps_by_stage={"CDR 3": {"bathing": 10}}),
        _rule(item_caps_by_stage={"CDR 3": {"dressing": 3}}),
        _rule(unknown_key=1),
    ],
)
def test_invalid_rules_fail_at_load(bad: dict) -> None:
    with pytest.raises(ValidationError):
        AdlCeilingRules.model_validate(bad)
