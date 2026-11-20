"""Issue #3396: an outpatient SOAP states only the results reported by its
authored time; the tests drawn that day and not yet resulted are worded as
pending."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.document.narrative._as_of import results_after, results_known_at
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
    build_outpatient_assessment,
    build_outpatient_objective,
    build_outpatient_plan,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from tests.unit.modules.document.narrative.test_outpatient_soap_results_3231 import _ctx, _lab

pytestmark = pytest.mark.unit

_AUTHORED = datetime(2026, 3, 2, 10, 0)
_BEFORE = "2026-03-02T09:30:00"
_AFTER = "2026-03-02T12:00:00"


def _soap(ctx) -> dict[str, str]:
    gen = TemplateNarrativeGenerator()
    return {
        "O": build_outpatient_objective(gen, ctx)[0],
        "A": build_outpatient_assessment(gen, ctx)[0],
        "P": build_outpatient_plan(gen, ctx)[0],
    }


def _authored(country: str, chronic, labs, **kw):
    ctx = _ctx(country, chronic, labs, **kw)
    ctx.authored_datetime = _AUTHORED
    return ctx


def test_helpers_split_the_labs_at_the_authored_time():
    labs = [_lab("ALT", 1, at=_BEFORE), _lab("AST", 2, at=_AFTER), {"lab_name": "CK", "value": 3}]
    assert [x["lab_name"] for x in results_known_at(labs, _AUTHORED)] == ["ALT", "CK"]
    assert [x["lab_name"] for x in results_after(labs, _AUTHORED)] == ["AST"]
    assert results_known_at(labs, None) == labs and results_after(labs, None) == []


@pytest.mark.parametrize("country", ["US", "JP"])
def test_flagged_result_after_the_note_is_pending_not_quoted(country):
    labs = [_lab("T_Bil", 5.3, "mg/dL", "H", at=_AFTER), _lab("ALT", 162, "U/L", "H", at=_AFTER)]
    s = _soap(_authored(country, [{"code": "I10"}], labs))
    for part in ("A", "O", "P"):
        assert "5.3" not in s[part] and "162" not in s[part], s[part]
    assert ("results pending" in s["O"]) or ("結果待ち" in s["O"]), s["O"]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_flagged_result_at_or_before_the_note_is_quoted(country):
    labs = [_lab("T_Bil", 5.3, "mg/dL", "H", at=_BEFORE)]
    s = _soap(_authored(country, [{"code": "I10"}], labs))
    assert "5.3" in s["O"] and "5.3" in s["A"]
    assert "results pending" not in s["O"] and "結果待ち" not in s["O"]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_screening_score_after_the_note_is_not_quoted(country):
    labs = [_lab("PHQ-9", 9, "{score}", at=_AFTER), _lab("C-SSRS", 1, "{score}", at=_AFTER)]
    s = _soap(_authored(country, [{"code": "F32.9"}], labs))
    for part in ("A", "O", "P"):
        assert "PHQ-9 9" not in s[part] and "C-SSRS 1" not in s[part], s[part]
    assert "safety plan" not in s["P"] and "安全計画" not in s["P"]


def test_chronic_hba1c_falls_back_to_the_prior_result_with_its_date():
    today = [_lab("HbA1c", 9.9, "%", "H", at=_AFTER)]
    prior = [_lab("HbA1c", 7.1, "%", at="2025-12-01T09:00:00")]
    ctx = _authored("US", [{"code": "E11.9"}], today, prior=prior)
    s = _soap(ctx)
    assert "9.9" not in s["A"] + s["O"] + s["P"]
    assert "7.1" in s["A"] and "2025-12-01" in s["A"]
    assert "HbA1c" in s["O"] and "results pending" in s["O"]
    known = _authored("US", [{"code": "E11.9"}], [_lab("HbA1c", 9.9, "%", "H", at=_BEFORE)], prior=prior)
    assert "9.9" in _soap(known)["A"]


def test_no_authored_time_keeps_every_result():
    ctx = _ctx("US", [{"code": "I10"}], [_lab("T_Bil", 5.3, "mg/dL", "H", at=_AFTER)])
    assert "5.3" in _soap(ctx)["O"]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_visit_reason_follow_up_labs_are_clipped(country):
    ctx = _authored(country, [{"code": "I10"}], [_lab("Creatinine", 1.8, "mg/dL", "H", at=_AFTER)])
    ctx.visit_type = "post_discharge"
    s = _soap(ctx)
    assert "1.8" not in s["O"] + s["A"] + s["P"]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_stage_restated_from_a_pending_result_is_not_stated(country):
    from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
        build_past_medical_history,
    )

    chronic = [{"code": "E11.9", "stage": "HbA1c 5.9%"}]
    pending = _authored(country, chronic, [_lab("HbA1c", 5.9, "%", at=_AFTER)])
    s = _soap(pending)
    text = s["A"] + build_past_medical_history(TemplateNarrativeGenerator(), pending)[0]
    assert "5.9" not in text, text
    known = _authored(country, chronic, [_lab("HbA1c", 5.9, "%", at=_BEFORE)])
    assert "5.9" in _soap(known)["A"] + build_past_medical_history(TemplateNarrativeGenerator(), known)[0]
