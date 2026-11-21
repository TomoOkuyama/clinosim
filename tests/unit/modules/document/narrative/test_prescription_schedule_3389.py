"""A prescription line states its route, frequency and days in every renderer (Issue #3389).

``_collect_discharge_medications`` normalizes the schedule to ``route`` /
``rx_frequency`` / ``rx_duration_days``; the discharge summary and the
outpatient SOAP read the raw simulator keys and printed a bare dose.
"""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._prescription_line import prescription_bits
from clinosim.modules.document.narrative.passes import NarrativePass
from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import (
    build_discharge_medications,
)
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
    _compose_today_prescription_line,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_GEN = TemplateNarrativeGenerator()
_RX = {
    "items": [
        {"drug_name": "Amlodipine", "dose": "5mg", "route": "PO", "frequency": "daily", "duration_days": 28},
    ]
}


def _ctx(lang: str, meds: list[dict]) -> NarrativeContext:
    return NarrativeContext(
        patient=PatientProfile(patient_id="PT-1", age=45, sex="M"),
        encounter=SimpleNamespace(encounter_id="ENC-1", admission_datetime=datetime(2025, 1, 1)),
        encounter_type=SimpleNamespace(value="outpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.DISCHARGE_SUMMARY,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        orders=[],
        discharge_medications=meds,
    )


def test_the_collector_keeps_the_route() -> None:
    [med] = NarrativePass._collect_discharge_medications({"discharge_prescription": _RX})
    assert med["route"] == "PO" and med["rx_frequency"] == "daily" and med["rx_duration_days"] == 28


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("en", "Amlodipine 5mg PO daily x28d"), ("ja", "5mg 経口 1日1回 28日分")],
)
def test_discharge_summary_and_soap_state_the_schedule(lang: str, expected: str) -> None:
    meds = NarrativePass._collect_discharge_medications({"discharge_prescription": _RX})
    text, _ = build_discharge_medications(_GEN, _ctx(lang, meds))
    assert expected in text, text
    assert expected in _compose_today_prescription_line(_ctx(lang, meds))


def test_a_cadence_the_dose_already_states_is_not_repeated() -> None:
    med = {"drug_name": "Cefcapene", "dose": "100mg PO TID", "route": "PO", "rx_frequency": "TID"}
    assert prescription_bits(med, "en", drug_name="Cefcapene") == ["100mg PO TID"]
    ja = prescription_bits(med, "ja", drug_name="Cefcapene")
    assert len(ja) == 1 and ja[0].count("1日3回") == 1, ja


def test_raw_simulator_keys_are_still_read_for_an_unnormalized_item() -> None:
    med = {"drug_name": "X", "dose": "1mg", "route": "PO", "frequency": "BID", "duration_days": 7}
    assert prescription_bits(med, "en", drug_name="X") == ["1mg", "PO", "BID", "x7d"]


def test_the_ed_take_home_line_leaves_out_the_route() -> None:
    med = {"drug_name": "X", "dose": "1mg", "route": "PO", "rx_frequency": "BID"}
    assert prescription_bits(med, "en", drug_name="X", show_route=False) == ["1mg", "BID"]


def test_no_builder_reads_a_raw_schedule_key_of_a_discharge_medication() -> None:
    root = Path(__file__).resolve().parents[5] / "clinosim/modules/document/narrative/renderers/section_builders"
    offenders = []
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and node.value in ("days_supply", "duration_days"):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, offenders
