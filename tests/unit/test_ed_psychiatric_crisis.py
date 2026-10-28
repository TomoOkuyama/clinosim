"""ED psychiatric crisis: per-severity disposition and per-prefix diagnosis code (Issue #2124)."""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.simulator.emergency import ed_diagnosis_code, ed_disposition

_COND = "suicidal_ideation_depression"


def _patient(*codes: str) -> SimpleNamespace:
    return SimpleNamespace(chronic_conditions=[SimpleNamespace(code=c) for c in codes])


def test_psychiatric_transfer_by_severity() -> None:
    spec = load_encounter_condition(_COND)
    assert ed_disposition(spec, "mild") is DischargeDisposition.HOME
    assert ed_disposition(spec, "moderate") is DischargeDisposition.PSY
    assert ed_disposition(spec, "severe") is DischargeDisposition.PSY


def test_other_ed_conditions_still_go_home() -> None:
    spec = load_encounter_condition("anxiety_panic_attack")
    assert ed_disposition(spec, "severe") is DischargeDisposition.HOME
    assert ed_disposition(None, "moderate") is DischargeDisposition.HOME


def test_recurrent_depression_codes_f33() -> None:
    spec = load_encounter_condition(_COND)
    assert ed_diagnosis_code(spec, _patient("F32.9")) == "F32.2"
    assert ed_diagnosis_code(spec, _patient("F33.9")) == "F33.2"
    assert ed_diagnosis_code(spec, _patient("F32.9", "F33.9")) == "F33.2"
    assert ed_diagnosis_code(load_encounter_condition("anxiety_panic_attack"), _patient("F33.9")) == "F41.0"


def test_condition_requires_depression_and_adult() -> None:
    spec = load_encounter_condition(_COND)
    assert sorted(spec["requires_chronic_prefix"]) == ["F32", "F33"]
    assert spec["min_age"] >= 18


def test_suicidal_ideation_is_high_risk_triage() -> None:
    from clinosim.modules.triage.engine import condition_triage_bounds

    record = SimpleNamespace(condition_event=SimpleNamespace(ground_truth_diseases=[_COND]))
    assert condition_triage_bounds(record) == (2, 2)
    other = SimpleNamespace(condition_event=SimpleNamespace(ground_truth_diseases=["ankle_sprain"]))
    assert condition_triage_bounds(other) == (1, 5)
    assert condition_triage_bounds(SimpleNamespace(condition_event=None)) == (1, 5)
