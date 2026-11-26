"""Issue #3830: a stay is not discharged as improved while hyperkalemia or a
severe metabolic acidosis of an unrecovered AKI persists."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.simulator.aki_response import (
    aki_course,
    aki_response_rules,
    discharge_extension_days,
    discharge_findings_unresolved,
    discharge_findings_unresolved_from_records,
    metabolic_findings_unresolved,
)
from clinosim.types.encounter import OrderResult

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 3, 1, 8, 0)


def _lab(day: int, name: str, value: float) -> OrderResult:
    return OrderResult(result_datetime=_T0 + timedelta(days=day), lab_name=name, value=value)


def test_high_potassium_or_severe_acidosis_is_unresolved() -> None:
    assert metabolic_findings_unresolved([_lab(0, "K", 6.6)])
    assert metabolic_findings_unresolved([_lab(0, "CO2", 9.0)])
    assert not metabolic_findings_unresolved([_lab(0, "K", 5.4), _lab(0, "CO2", 18.0)])
    assert not metabolic_findings_unresolved([])


def test_only_the_latest_result_counts() -> None:
    assert not metabolic_findings_unresolved([_lab(0, "K", 7.0), _lab(2, "K", 5.1)])
    assert metabolic_findings_unresolved([_lab(0, "K", 5.1), _lab(2, "K", 6.2)])
    assert not metabolic_findings_unresolved([_lab(0, "CO2", 8.0), _lab(1, "CO2", 15.0)])


def test_the_thresholds_are_the_rules() -> None:
    rules = aki_response_rules()
    assert rules.unresolved_total_co2_mmol_l == 10.0
    assert metabolic_findings_unresolved([_lab(0, "CO2", rules.unresolved_total_co2_mmol_l)])
    assert not metabolic_findings_unresolved([_lab(0, "CO2", rules.unresolved_total_co2_mmol_l + 0.5)])


def test_the_gate_defers_discharge_and_extends_the_stay_for_them() -> None:
    labs = [_lab(0, "Creatinine", 0.9), _lab(1, "Creatinine", 0.9), _lab(1, "K", 6.4)]
    course = aki_course(labs)
    assert not course.not_improving  # the kidneys alone would let the patient go
    assert discharge_findings_unresolved(course, [], labs)
    assert discharge_extension_days(course, [], labs) == aki_response_rules().max_extension_days
    assert not discharge_findings_unresolved(course, [], [_lab(1, "K", 4.9)])
    assert discharge_extension_days(course, [], [_lab(1, "K", 4.9)]) == 0


def test_records_form_matches_the_objects() -> None:
    records = [
        {"result_datetime": (_T0).isoformat(), "lab_name": "K", "value": 6.5},
    ]
    assert discharge_findings_unresolved_from_records(records, [])


def _final(patient, lab: str) -> float | None:
    rows = sorted(
        (r.result_datetime, float(r.value))
        for r in patient.lab_results
        if r.lab_name == lab and isinstance(r.value, (int, float))
    )
    return rows[-1][1] if rows else None


def test_no_stay_is_discharged_home_with_the_potassium_or_acidosis_of_unrecovered_aki(monkeypatch) -> None:
    # Without renal replacement (Issue #3830, tested separately) these stays reach the cap unresolved.
    monkeypatch.setattr("clinosim.simulator.daily_loop.renal_replacement_due", lambda *a, **k: False)
    from clinosim.codes.hl7_encounter import DischargeDisposition
    from clinosim.simulator import run_forced
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    unresolved = 0
    for archetype in ("treatment_resistant", "plateau_then_recovery"):
        scenario = ForcedScenario(disease_id="acute_kidney_injury", count=4, severity="severe", archetype=archetype)
        for patient in run_forced(scenario, SimulatorConfig(random_seed=42, country="JP")).patients:
            enc = patient.encounters[0]
            if enc.discharge_disposition == DischargeDisposition.EXP:
                continue
            potassium, co2 = _final(patient, "K"), _final(patient, "CO2")
            bad = (potassium is not None and potassium >= 6.0) or (co2 is not None and co2 <= 10.0)
            if bad:
                unresolved += 1
                assert enc.discharge_disposition == DischargeDisposition.SNF, (potassium, co2)
    assert unresolved > 0  # the scenario does reach the cap unresolved: the check is not vacuous


def test_the_discharge_instruction_names_the_unresolved_metabolic_findings_only() -> None:
    from types import SimpleNamespace

    from clinosim.modules.document.narrative.renderers._resolvers import resolve_discharge_instructions

    def ctx(k: float):
        return SimpleNamespace(
            patient=SimpleNamespace(sex="M", smoking_status="never", alcohol_use="none", chronic_conditions=[]),
            disease_protocol=None,
            diagnoses=[],
            discharge_medications=[],
            lab_results=[{"result_datetime": _T0.isoformat(), "lab_name": "K", "value": k}],
            vitals=[],
            target_lang="en",
            locale="us",
        )

    entry = resolve_discharge_instructions(ctx(6.6)).get("metabolic_followup", {})
    assert "potassium" in entry["en"] and "カリウム" in entry["ja"]
    assert "metabolic_followup" not in resolve_discharge_instructions(ctx(4.8))
