"""Issue #3270: the nursing discharge summary states "discharge criteria met"
only for a discharge home; a patient still not safe for home at the end of
the stay is recorded as going to a facility for continued care."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.nursing import build_nursing_admission_status
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _ctx(disposition: str, lang: str) -> NarrativeContext:
    encounter = SimpleNamespace(
        encounter_id="enc-3270",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2025, 12, 4, 10, 0),
        discharge_datetime=datetime(2025, 12, 10, 10, 28),
        discharge_disposition=disposition,
        chief_complaint="chest pain",
    )
    return NarrativeContext(
        patient=PatientProfile(patient_id="pt-3270"),
        encounter=encounter,
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=SimpleNamespace(disease_id="acute_mi"),
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="severe",
        day_index=5,
        los_days=6,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.NURSING_DISCHARGE_SUMMARY,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


@pytest.mark.parametrize(
    ("lang", "met"),
    [("en", "Discharge criteria met"), ("ja", "退院基準を満たし退院となった")],
)
def test_home_discharge_states_criteria_met(lang: str, met: str) -> None:
    text, _ = build_nursing_admission_status(None, _ctx("home", lang))  # type: ignore[arg-type]
    assert met in text


@pytest.mark.parametrize(
    ("lang", "met", "expected"),
    [
        ("en", "Discharge criteria met", "Not yet safe for home; discharged to skilled nursing facility"),
        ("ja", "退院基準を満たし退院となった", "継続加療目的に施設退院となった"),
    ],
)
def test_facility_discharge_does_not_state_criteria_met(lang: str, met: str, expected: str) -> None:
    text, facts = build_nursing_admission_status(None, _ctx("snf", lang))  # type: ignore[arg-type]
    assert met not in text
    assert expected in text
    assert "encounter.discharge_disposition" in facts
