"""Issue #3397: the ED physician note is authored at the end of the ED visit
and states only what was ordered, resulted and done by then."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_ed_workup
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType
from tests.unit.modules.document.narrative.test_ed_note_content_3244 import _ctx, _imaging_order, _study

pytestmark = pytest.mark.unit

_GEN = TemplateNarrativeGenerator()
_ARRIVAL = datetime(2025, 11, 20, 18, 35)
_DEPARTURE = _ARRIVAL + timedelta(hours=3)


def _at(hours: float) -> str:
    return (_ARRIVAL + timedelta(hours=hours)).isoformat()


def _lab(name: str, value: float, ordered: float, resulted: float) -> dict:
    return {
        "order_id": f"L-{name}",
        "encounter_id": "ENC-1",
        "order_type": "lab",
        "display_name": name,
        "ordered_datetime": _at(ordered),
        "result": {"lab_name": name, "value": value, "unit": "mg/dL", "flag": "H", "result_datetime": _at(resulted)},
    }


def _med(name: str, ordered: float) -> dict:
    return {
        "order_id": f"M-{name}",
        "encounter_id": "ENC-1",
        "order_type": "medication",
        "display_name": name,
        "ordered_datetime": _at(ordered),
    }


def _workup(**over) -> str:
    ctx = _ctx("low_back_pain", "en", **over)
    ctx.authored_datetime = _DEPARTURE
    return build_ed_workup(_GEN, ctx)[0]


def test_the_ed_note_spec_is_authored_at_the_end_of_the_visit() -> None:
    specs = load_document_type_specs()
    assert specs[DocumentType.ED_NOTE].authored_at == "period_end"
    assert specs[DocumentType.ED_TRIAGE_NOTE].authored_at == "admission"
    assert specs[DocumentType.OUTPATIENT_SOAP].authored_at == "admission"


def test_a_result_reported_after_the_note_is_not_quoted() -> None:
    text = _workup(orders=[_lab("Creatinine", 5.19, 0.2, 1.0), _lab("Troponin", 9.99, 0.3, 5.0)])
    assert "5.19" in text
    assert "9.99" not in text, text


def test_an_imaging_report_issued_after_the_note_is_not_quoted() -> None:
    study = _study("O1", "Late finding.", "後の所見。")
    study.report.issued_datetime = _at(6)
    text = _workup(orders=[_imaging_order("O1", "Lumbar_Xray")], imaging_studies=[study])
    assert "Late finding" not in text, text


def test_an_order_placed_after_the_note_is_not_listed() -> None:
    text = _workup(orders=[_med("Ibuprofen", 1.0), _med("Ondansetron", 5.0)])
    assert "Ibuprofen" in text
    assert "Ondansetron" not in text, text


def test_a_procedure_started_after_the_note_is_not_listed() -> None:
    procs = [
        {"procedure_name": "Splint application", "start_datetime": _at(1)},
        {"procedure_name": "Inpatient line placement", "start_datetime": _at(8)},
    ]
    text = _workup(procedures=procs)
    assert "Splint application" in text
    assert "Inpatient line" not in text, text


def test_a_flagged_result_after_the_note_is_not_listed_as_abnormal() -> None:
    labs = [
        {"lab_name": "Potassium", "value": 6.8, "unit": "mmol/L", "flag": "H", "result_datetime": _at(9)},
        {"lab_name": "Sodium", "value": 150, "unit": "mmol/L", "flag": "H", "result_datetime": _at(1)},
    ]
    text = _workup(lab_results=labs)
    assert "sodium 150" in text
    assert "6.8" not in text, text


def test_an_admitted_ed_set_is_the_initial_order_set_placed_in_the_ed() -> None:
    """A via-ED admission's ED set is the initial order set placed in the ED
    period (Issue #3242, #3434): the stay's later orders and an initial order
    timed after the note are not listed."""
    initial = dict(_med("Aspirin", 1.0), order_set="admission_initial")
    late_initial = dict(_med("Oxygen", 4.0), order_set="admission_initial")
    ward = dict(_med("Heparin", 1.5), order_set="daily")
    ctx = _ctx("low_back_pain", "en", orders=[initial, late_initial, ward])
    ctx.encounter.encounter_type.value = "inpatient"
    ctx.encounter.admission_datetime = _DEPARTURE
    ctx.authored_datetime = _DEPARTURE
    text = build_ed_workup(_GEN, ctx)[0]
    assert "Aspirin" in text, text
    assert "Heparin" not in text and "Oxygen" not in text, text
