"""Unit tests for clinosim.types.triage(Tier 1 #3 α-min-2 PR1)."""

from __future__ import annotations

from datetime import datetime

from clinosim.types.triage import TriageData


def test_triage_data_defaults():
    t = TriageData()
    assert t.level == ""
    assert t.level_system == ""
    assert t.arrival_mode == ""
    assert t.triage_time is None
    assert t.acuity_score is None
    assert t.chief_complaint_summary == ""


def test_triage_data_jtas_payload():
    t = TriageData(
        level="3",
        level_system="JTAS",
        arrival_mode="walk-in",
        triage_time=datetime(2026, 7, 1, 10, 15),
        acuity_score=60.0,
        chief_complaint_summary="腹痛",
    )
    assert t.level == "3"
    assert t.level_system == "JTAS"
    assert t.arrival_mode == "walk-in"
    assert t.chief_complaint_summary == "腹痛"


def test_triage_data_esi_payload():
    t = TriageData(level="3", level_system="ESI", arrival_mode="ambulance")
    assert t.level_system == "ESI"


def test_document_type_alpha2_enum_values():
    from clinosim.types.document import DocumentType

    assert DocumentType.ADMISSION_NURSING_ASSESSMENT.value == "admission_nursing_assessment"
    assert DocumentType.NURSING_SHIFT_NOTE.value == "nursing_shift_note"
    assert DocumentType.NURSING_DISCHARGE_SUMMARY.value == "nursing_discharge_summary"
    assert DocumentType.OUTPATIENT_SOAP.value == "outpatient_soap"
    assert DocumentType.ED_NOTE.value == "ed_note"
    assert DocumentType.ED_TRIAGE_NOTE.value == "ed_triage_note"


def test_encounter_alpha2_fields():
    from clinosim.types.encounter import Encounter

    e = Encounter()
    assert e.primary_nurse_id == ""
    assert e.triage_data is None
