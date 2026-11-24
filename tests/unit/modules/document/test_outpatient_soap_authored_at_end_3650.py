"""Issue #3650: an outpatient SOAP is authored when the visit ends, so the
as-of gate lets the visit's own vitals through."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.locale.loader import load_ambulatory_visit_length
from clinosim.modules.document.engine import document_enricher
from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import build_outpatient_objective
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.simulator._outpatient_thresholds import OUTPATIENT_VITALS_OFFSET_MIN
from clinosim.types.document import DocumentType
from tests.unit.modules.document.narrative.test_visit_reason_soap_3249 import _record
from tests.unit.modules.document.test_engine import ADMISSION_DT, _make_ctx, _make_record
from tests.unit.modules.document.test_engine_alpha2 import _make_encounter

pytestmark = pytest.mark.unit


def _soap(encounter) -> object:
    record = _make_record(encounter)
    document_enricher(_make_ctx(record))
    return next(d for d in record.documents if d.task_type == "outpatient_soap")


def test_outpatient_soap_is_authored_at_the_visit_end() -> None:
    end = ADMISSION_DT + timedelta(minutes=20)
    soap = _soap(_make_encounter(enc_type="outpatient", admission_dt=ADMISSION_DT, discharge_dt=end))
    assert soap.authored_datetime == end.isoformat() and soap.period_end == end.isoformat()
    assert soap.period_start == ADMISSION_DT.isoformat()


def test_the_visit_is_longer_than_the_vitals_offset() -> None:
    """The premise: the vitals are taken inside the visit, so the end gate admits them."""
    for country in ("US", "JP"):
        cfg = load_ambulatory_visit_length(country)
        shortest = min(b["min"] for b in cfg["visit_types"].values())
        assert shortest >= OUTPATIENT_VITALS_OFFSET_MIN  # a vital set at the end is still "recorded by" it


@pytest.mark.parametrize("country", ["US", "JP"])
def test_objective_states_the_visit_vitals_when_authored_at_the_end(country: str) -> None:
    start = datetime(2026, 3, 2, 10, 0)
    vitals = [
        {
            "timestamp": (start + timedelta(minutes=OUTPATIENT_VITALS_OFFSET_MIN)).isoformat(),
            "systolic_bp": 126,
            "diastolic_bp": 69,
            "heart_rate": 70,
        }
    ]
    record = _record(country=country, visit_type="chronic_followup", condition="I10", dx="I10", chronic=["I10"])
    record["vital_signs"] = vitals
    gen = TemplateNarrativeGenerator()

    ctx = build_narrative_context(record, record["encounters"][0], DocumentType.OUTPATIENT_SOAP, 0, country)
    ctx.authored_datetime = start  # authored at the arrival (the old behaviour)
    assert "126/69" not in build_outpatient_objective(gen, ctx)[0]
    ctx.authored_datetime = start + timedelta(minutes=15)  # authored at the visit end
    assert "126/69" in build_outpatient_objective(gen, ctx)[0]
