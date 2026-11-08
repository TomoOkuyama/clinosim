"""ESI level bounded by the protocol and the ESI v4 resource rule (Issue #2864)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim import determinism
from clinosim.modules.encounter.protocol import EdTriageTemplate, EncounterConditionProtocol
from clinosim.modules.triage.engine import (
    condition_triage_bounds,
    pick_triage_level,
    resource_count,
    triage_enricher,
)

pytestmark = pytest.mark.unit


def _order(order_type: str, name: str = "", route: str = "") -> SimpleNamespace:
    return SimpleNamespace(order_type=order_type, display_name=name, route=route, encounter_id="E1")


def _vs(**kw) -> SimpleNamespace:
    base = {
        "timestamp": datetime(2026, 5, 1, 9, 10),
        "heart_rate": 80,
        "respiratory_rate": 16,
        "spo2": 98.0,
        "systolic_bp": 125,
        "pain_score": 2,
        "consciousness_level": "A",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _levels(
    condition: str, severity: str, orders: list, vitals: list | None = None, country: str = "US", n: int = 200
) -> set[str]:
    out: set[str] = set()
    for i in range(n):
        enc = SimpleNamespace(
            encounter_type="emergency",
            severity=severity,
            encounter_id="E1",
            admission_datetime=datetime(2026, 5, 1, 9),
            chief_complaint="",
        )
        record = SimpleNamespace(
            encounters=[enc],
            orders=orders,
            vital_signs=vitals or [],
            condition_event=SimpleNamespace(ground_truth_diseases=[condition]),
        )
        triage_enricher(SimpleNamespace(config=SimpleNamespace(country=country), records=[record], master_seed=i))
        out.add(enc.triage_data.level)
    return out


# ----- bounded draw -----


@pytest.mark.parametrize("severity", ["mild", "moderate", "severe"])
def test_draw_stays_inside_the_bounds(severity: str) -> None:
    rng = determinism.default_rng(1)
    assert {pick_triage_level(severity, "ESI", rng, (2, 3)) for _ in range(500)} <= {"2", "3"}


def test_draw_with_no_weight_inside_the_bounds_is_clamped() -> None:
    rng = determinism.default_rng(1)
    assert {pick_triage_level("mild", "ESI", rng, (1, 2)) for _ in range(200)} == {"2"}


def test_bounded_draw_uses_one_draw() -> None:
    """The bounds change the drawn level, not the stream position."""
    a, b = determinism.default_rng(7), determinism.default_rng(7)
    pick_triage_level("moderate", "ESI", a)
    pick_triage_level("moderate", "ESI", b, (2, 3))
    assert a.random() == b.random()


def test_bounds_come_from_common_triage_levels() -> None:
    def rec(cond: str) -> SimpleNamespace:
        return SimpleNamespace(condition_event=SimpleNamespace(ground_truth_diseases=[cond]))

    assert condition_triage_bounds(rec("chest_pain_noncardiac")) == (2, 3)
    assert condition_triage_bounds(rec("uti_uncomplicated")) == (3, 4)
    assert condition_triage_bounds(rec("opioid_overdose")) == (1, 2)


def test_chest_pain_and_urticaria_stay_in_their_levels() -> None:
    workup = [_order("lab", "Troponin"), _order("imaging", "ECG")]
    assert _levels("chest_pain_noncardiac", "mild", workup) <= {"2", "3"}
    assert _levels("allergic_reaction_mild", "severe", []) <= {"2", "3", "4"}


# ----- resource rule -----


def test_resource_count_by_type() -> None:
    labs = [_order("lab", "WBC"), _order("lab", "CRP"), _order("lab", "Urinalysis")]
    assert resource_count([]) == 0
    assert resource_count(labs) == 1
    assert resource_count(labs + [_order("imaging", "CT")]) == 2
    assert resource_count([_order("medication", "Ondansetron 4mg", "IV")]) == 1
    assert resource_count([_order("medication", "Ibuprofen 400mg", "PO")]) == 0
    assert resource_count([_order("procedure", "Ice pack application")]) == 0
    assert resource_count([_order("procedure", "Suture closure")]) == 1
    assert resource_count([_order("therapy", "Observation")]) == 0


def test_uti_with_lab_and_iv_resources_is_level_3() -> None:
    orders = [_order("lab", "Urinalysis"), _order("lab", "WBC"), _order("medication", "Ceftriaxone 1g", "IV")]
    assert _levels("uti_uncomplicated", "mild", orders) == {"3"}


def test_uti_with_labs_only_is_level_4() -> None:
    orders = [_order("lab", "Urinalysis"), _order("lab", "WBC"), _order("lab", "Creatinine")]
    assert _levels("uti_uncomplicated", "mild", orders) == {"4"}


def test_no_resources_is_clamped_to_the_least_urgent_common_level() -> None:
    assert _levels("uti_uncomplicated", "mild", []) == {"4"}
    assert _levels("viral_uri", "mild", []) == {"5"}


def test_epinephrine_makes_anaphylaxis_level_2() -> None:
    orders = [_order("medication", "Epinephrine 0.3mg", "IM")]
    assert _levels("allergic_reaction_mild", "mild", orders) == {"2"}


def test_high_risk_orders_must_name_a_treatment() -> None:
    base = {
        "condition_id": "x",
        "icd10_code": "T78.40",
        "chief_complaint": "x",
        "encounter_type": "emergency",
        "department": "emergency_medicine",
        "treatment": [{"name": "Epinephrine 0.3mg"}],
    }
    ok = {"ed_triage_template": {"common_triage_levels": ["2", "3"], "high_risk_orders": ["Epinephrine 0.3mg"]}}
    EncounterConditionProtocol.model_validate({**base, "narrative": ok})
    bad = {"ed_triage_template": {"common_triage_levels": ["2", "3"], "high_risk_orders": ["Naloxone"]}}
    with pytest.raises(ValueError, match="not treatment names"):
        EncounterConditionProtocol.model_validate({**base, "narrative": bad})
    with pytest.raises(ValueError, match="'1' or '2'"):
        EdTriageTemplate.model_validate({"common_triage_levels": ["3", "4"], "high_risk_orders": ["x"]})


# ----- vitals cap still wins -----


def test_vitals_cap_goes_below_the_bounds() -> None:
    assert _levels("viral_uri", "mild", [], [_vs(spo2=87.0)]) == {"2"}
    assert _levels("uti_uncomplicated", "mild", [], [_vs(heart_rate=120)]) == {"3"}


def test_jtas_follows_the_same_rule() -> None:
    assert _levels("uti_uncomplicated", "mild", [_order("lab", "Urinalysis")], country="JP") == {"4"}
