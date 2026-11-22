"""Issue #3559: the ED note of an admitted patient names a drug once and marks
an unresulted test as pending."""

from __future__ import annotations

from datetime import timedelta

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_ed_workup
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.triage.engine import admitted_ed_stay
from tests.unit.modules.document.narrative.test_ed_note_content_3244 import _ctx
from tests.unit.modules.document.narrative.test_ed_note_mar_3467 import _ADMISSION, _ED_START, _order

pytestmark = pytest.mark.unit

_GEN = TemplateNarrativeGenerator()
_SET = "admission_initial"


def _lab(name: str, when, result_at=None) -> dict:
    order = {
        "order_id": f"L-{name}",
        "encounter_id": "ENC-1",
        "order_type": "lab",
        "display_name": name,
        "ordered_datetime": when.isoformat(),
        "order_set": _SET,
    }
    if result_at is not None:
        order["result"] = {
            "lab_name": name,
            "value": 1.5,
            "unit": "mg/dL",
            "result_datetime": result_at.isoformat(),
        }
    return order


def _workup(lang: str, orders: list) -> str:
    ctx = _ctx("low_back_pain", lang, orders=orders, medications=[])
    ctx.encounter.encounter_type.value = "inpatient"
    ctx.encounter.admission_datetime = _ADMISSION
    ctx.authored_datetime = _ADMISSION
    return build_ed_workup(_GEN, ctx)[0]


@pytest.mark.parametrize("lang,term", [("en", "Prednisolone"), ("ja", "プレドニゾロン")])
def test_a_bare_drug_and_its_order_set_line_are_listed_once_with_the_sig(lang: str, term: str) -> None:
    t0 = _ED_START + timedelta(minutes=10)
    text = _workup(
        lang,
        [
            _order("Prednisolone", t0, _SET),
            _order("steroid: Prednisolone 40mg PO daily x5 days", t0 + timedelta(minutes=9), _SET),
        ],
    )
    assert text.count(term) == 1, text
    assert "40mg" in text, text


def test_a_drug_in_the_medication_and_the_procedure_list_is_listed_once() -> None:
    t0 = _ED_START + timedelta(minutes=10)
    proc = {**_order("bronchodilator: Salbutamol 2.5mg nebulizer q4h", t0, _SET), "order_type": "procedure"}
    text = _workup("en", [_order("Albuterol", t0, _SET), proc])
    assert text.count("Salbutamol") + text.count("Albuterol") == 1, text
    assert "nebulizer" in text, text


@pytest.mark.parametrize("lang,mark", [("en", "CRP pending"), ("ja", "CRP 結果待ち")])
def test_a_test_resulted_after_the_departure_is_marked_pending(lang: str, mark: str) -> None:
    t0 = _ED_START + timedelta(minutes=10)
    text = _workup(lang, [_lab("CRP", t0, _ADMISSION + timedelta(hours=8)), _lab("Creatinine", t0, t0)])
    assert mark in text, text
    assert "reatinine 1.5" in text or "クレアチニン 1.5" in text, text


def test_a_test_with_a_result_is_not_marked_pending() -> None:
    t0 = _ED_START + timedelta(minutes=10)
    text = _workup("en", [_lab("Creatinine", t0, t0)])
    assert "pending" not in text, text
    _ = admitted_ed_stay
