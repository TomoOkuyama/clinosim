"""The ED note of an admitted patient is written from the ED visit (Issue #2856).

For a via-ED admission the ED note is rendered on the inpatient record, so
its encounter is the stay. Its disposition must say "admitted" (not the
stay's home / expired outcome) and it may quote only results available
before the ED departure (the admission time).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.ed_note import (
    build_ed_disposition,
    build_ed_workup,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2024, 6, 14, 13, 14)


def _stay(disposition: str) -> SimpleNamespace:
    return SimpleNamespace(
        encounter_id="ENC-1",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=_ADMIT,
        chief_complaint="Fever, cough, dyspnea",
        chief_complaint_ja="",
        severity="severe",
        discharge_disposition=disposition,
    )


def _ctx(encounter: SimpleNamespace, labs: list | None = None) -> NarrativeContext:
    return NarrativeContext(
        patient=PatientProfile(patient_id="PT-1"),
        encounter=encounter,
        encounter_type=encounter.encounter_type,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="severe",
        day_index=0,
        los_days=3,
        vitals=[],
        lab_results=labs or [],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ED_NOTE,
        target_lang="en",
        locale="us",
        orders=[],
    )


@pytest.mark.parametrize("disposition", ["home", "exp"])
def test_admitted_ed_note_says_admitted_whatever_the_stay_outcome(disposition: str) -> None:
    text, _ = build_ed_disposition(TemplateNarrativeGenerator(), _ctx(_stay(disposition)))
    assert text.startswith("Admitted"), text
    assert "Discharged home" not in text and "Died in the ED" not in text


def test_admitted_ed_note_quotes_only_results_before_departure() -> None:
    before = SimpleNamespace(
        lab_name="WBC", value=15000, unit="/uL", flag="H", result_datetime=datetime(2024, 6, 14, 12, 0)
    )
    after = SimpleNamespace(
        lab_name="CRP", value=93.3, unit="mg/L", flag="H", result_datetime=datetime(2024, 6, 14, 15, 0)
    )
    text, _ = build_ed_workup(TemplateNarrativeGenerator(), _ctx(_stay("exp"), [before, after]))
    assert "15000" in text
    assert "93.3" not in text
