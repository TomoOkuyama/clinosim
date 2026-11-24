"""The plan line of a drug held during an earlier admission cites that
admission's span, not the discharge date alone, and a Japanese hold reason is
not followed by a second 保留 (Issue #3699)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.modules.document.narrative.context import build_prior_safety_holds
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import build_outpatient_plan
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from tests.unit.modules.document.narrative.test_outpatient_soap_results_3231 import _ctx, _med

pytestmark = pytest.mark.unit

_REASONS = Path(__file__).resolve().parents[5] / "clinosim" / "locale" / "shared" / "medication_hold_reasons.yaml"


def _hold(**extra) -> dict:
    return {
        "drug": "Candesartan",
        "drug_ja": "",
        "reason": "acute kidney injury",
        "reason_ja": "急性腎障害",
        "held_on": "2026-02-20",
        **extra,
    }


def _plan(country: str, hold: dict, *, resumed: bool = True) -> str:
    home = [_med("Hydrochlorothiazide", "25mg")]
    rx = [*home, _med("Candesartan", "8mg")] if resumed else list(home)
    ctx = _ctx(country, [{"code": "I10"}], meds=home, home=home, rx=rx)
    ctx.prior_safety_holds = [hold]
    return build_outpatient_plan(TemplateNarrativeGenerator(), ctx)[0]


def test_en_line_cites_the_admission_span() -> None:
    p = _plan("US", _hold(admitted_on="2026-02-10", discharged_on="2026-02-20"))
    expected = "Candesartan: held during the admission 2026-02-10 to 2026-02-20 (acute kidney injury), "
    assert expected + "resumed on today's prescription." in p


def test_ja_line_cites_the_span_once_and_has_one_hold_word() -> None:
    p = _plan("JP", _hold(admitted_on="2026-02-10", discharged_on="2026-02-20"), resumed=False)
    line = next(x for x in p.split("\n") if "2026-02-10" in x)
    assert "2026-02-10" in line and "2026-02-20" in line and line.count("保留") == 2  # held clause + "continued"
    assert "のため保留" not in line


def test_missing_encounter_falls_back_to_the_single_date() -> None:
    p = _plan("US", _hold())
    assert "Candesartan: held on 2026-02-20 for acute kidney injury, resumed on today's prescription." in p


def test_same_day_admission_uses_the_single_date() -> None:
    p = _plan("US", _hold(admitted_on="2026-02-20", discharged_on="2026-02-20"))
    assert "held on 2026-02-20" in p


def test_build_prior_safety_holds_adds_the_span_of_the_holding_encounter() -> None:
    patient = {
        "safety_skip_log": [
            {
                "event_type": "hold",
                "encounter_id": "E1",
                "candidate_drug": "Candesartan",
                "active_conflict": "AKI",
                "timestamp": "2026-02-20T10:00:00",
            }
        ]
    }
    encounters = [
        {
            "encounter_id": "E1",
            "admission_datetime": "2026-02-10T08:30:00",
            "discharge_datetime": "2026-02-20T10:00:00",
        },
        {"encounter_id": "E2", "admission_datetime": "2026-03-02T10:00:00"},
    ]
    (hold,) = build_prior_safety_holds(patient, {"encounter_id": "E2"}, encounters)
    assert (hold["admitted_on"], hold["discharged_on"], hold["held_on"]) == ("2026-02-10", "2026-02-20", "2026-02-20")
    (bare,) = build_prior_safety_holds(patient, {"encounter_id": "E2"}, [])
    assert bare["admitted_on"] == bare["discharged_on"] == ""


def test_no_japanese_hold_reason_contains_the_hold_word() -> None:
    reasons = yaml.safe_load(_REASONS.read_text(encoding="utf-8"))["reasons"]
    bad = [k for k, v in reasons.items() if "保留" in str(v.get("ja", ""))]
    assert bad == []
