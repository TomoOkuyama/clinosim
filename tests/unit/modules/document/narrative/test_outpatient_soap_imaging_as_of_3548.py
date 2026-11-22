"""Issue #3548: an outpatient SOAP quotes only what existed when it was
authored: an imaging read issued after the note, a vital-sign set measured
after it and an observation after a dose given after it are not stated."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.document.narrative._as_of import latest_recorded_by
from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
    build_outpatient_objective,
    build_outpatient_plan,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType
from tests.unit.modules.document.narrative.test_visit_reason_soap_3249 import _ENC, _record

pytestmark = pytest.mark.unit

_AUTHORED = datetime(2026, 3, 2, 10, 0)
_ORDER = {
    "order_id": "ORD-IMG-1",
    "encounter_id": _ENC,
    "order_type": "imaging",
    "display_name": "Chest_Xray",
    "ordered_datetime": "2026-03-02T10:10:00",
}


def _study(issued: str) -> dict:
    return {
        "encounter_id": _ENC,
        "order_id": "ORD-IMG-1",
        "report": {"impression_text": "No acute cardiopulmonary abnormality.", "issued_datetime": issued},
    }


def _ctx(country: str, *, studies: list[dict], orders: list[dict], vitals: list[dict] | None = None, **kw):
    record = _record(
        country=country, visit_type="health_screening", condition="annual_health_checkup", dx="Z00.0", chronic=[], **kw
    )
    record["orders"] = orders
    record["extensions"] = {"imaging": studies}
    if vitals is not None:
        record["vital_signs"] = vitals
    ctx = build_narrative_context(record, record["encounters"][0], DocumentType.OUTPATIENT_SOAP, 0, country)
    ctx.authored_datetime = _AUTHORED
    return ctx


@pytest.mark.parametrize(("country", "pending"), [("US", "read pending"), ("JP", "読影結果待ち")])
def test_unreported_study_is_pending_not_read(country, pending):
    ctx = _ctx(country, studies=[_study("2026-03-02T11:00:00")], orders=[_ORDER])
    text = build_outpatient_objective(TemplateNarrativeGenerator(), ctx)[0]
    assert pending in text
    assert "No acute cardiopulmonary" not in text and "急性期異常" not in text


@pytest.mark.parametrize("country", ["US", "JP"])
def test_order_without_any_study_is_pending(country):
    ctx = _ctx(country, studies=[], orders=[_ORDER])
    text = build_outpatient_objective(TemplateNarrativeGenerator(), ctx)[0]
    assert "read pending" in text or "読影結果待ち" in text


def test_report_issued_before_the_note_is_quoted():
    ctx = _ctx("US", studies=[_study("2026-03-02T09:30:00")], orders=[_ORDER])
    text = build_outpatient_objective(TemplateNarrativeGenerator(), ctx)[0]
    assert "No acute cardiopulmonary abnormality" in text
    assert "read pending" not in text


@pytest.mark.parametrize(("country", "bp_text"), [("US", "BP 126/69"), ("JP", "126/69")])
def test_vitals_measured_after_the_note_are_not_quoted(country, bp_text):
    late = {"timestamp": "2026-03-02T10:05:00", "systolic_bp": 126, "diastolic_bp": 69, "heart_rate": 70}
    early = {"timestamp": "2026-03-02T09:50:00", "systolic_bp": 118, "diastolic_bp": 72, "heart_rate": 68}
    gen = TemplateNarrativeGenerator()
    only_late = build_outpatient_objective(gen, _ctx(country, studies=[], orders=[], vitals=[late]))[0]
    assert "126/69" not in only_late
    both = build_outpatient_objective(gen, _ctx(country, studies=[], orders=[], vitals=[late, early]))[0]
    assert "118/72" in both and "126/69" not in both


def test_latest_recorded_by_helper():
    rows = [{"timestamp": "2026-03-02T09:00:00", "v": 1}, {"timestamp": "2026-03-02T09:40:00", "v": 2}]
    assert latest_recorded_by(rows + [{"timestamp": "2026-03-02T10:05:00", "v": 3}], _AUTHORED)["v"] == 2
    assert latest_recorded_by([{"timestamp": "2026-03-02T10:05:00"}], _AUTHORED) is None
    assert latest_recorded_by(rows, None)["v"] == 2


@pytest.mark.parametrize(("country", "marker"), [("US", "immediate reaction"), ("JP", "即時型反応なし")])
def test_observation_after_a_date_only_dose_is_not_written(country, marker):
    imm = {"vaccine_cvx": "141", "occurrence_date": "2026-03-02", "encounter_id": _ENC, "status": "completed"}
    record = _record(
        country=country,
        visit_type="vaccination",
        condition="flu_vaccination",
        dx="Z23",
        chronic=[],
        immunizations=[imm],
    )
    ctx = build_narrative_context(record, record["encounters"][0], DocumentType.OUTPATIENT_SOAP, 0, country)
    ctx.authored_datetime = _AUTHORED
    gen = TemplateNarrativeGenerator()
    assert marker not in build_outpatient_plan(gen, ctx)[0]
    ctx.authored_datetime = None
    assert marker in build_outpatient_plan(gen, ctx)[0]
