"""An outpatient visit's prescription and procedure lines list every item (Issue #3475).

The lines are the record of what was prescribed / done at the visit, so a hard
cap silently dropped item 9+ of a prescription and item 7+ of the procedures.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
    _compose_today_prescription_line,
    _compose_today_procedures_line,
)
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _ctx(meds: list[dict], procs: list[dict]) -> NarrativeContext:
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
        procedures=procs,
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang="en",
        locale="us",
        orders=[],
        discharge_medications=meds,
    )


@pytest.mark.parametrize("n", [9, 12])
def test_every_prescribed_item_is_listed(n: int) -> None:
    names = [f"Drugname{i:02d}" for i in range(n)]
    meds = [{"drug_name": nm, "dose": "5mg"} for nm in names]
    text = _compose_today_prescription_line(_ctx(meds, []))
    for nm in names:
        assert nm in text, (nm, text)


@pytest.mark.parametrize("n", [7, 10])
def test_every_procedure_is_listed(n: int) -> None:
    names = [f"Procedure{i:02d}" for i in range(n)]
    procs = [{"procedure_name": nm} for nm in names]
    text = _compose_today_procedures_line(_ctx([], procs))
    for nm in names:
        assert nm in text, (nm, text)
