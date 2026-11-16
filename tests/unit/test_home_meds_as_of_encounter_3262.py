"""Issue #3262: the HPI's regular-medication sentence names the medications
the patient took when the encounter began — the record's
``home_medications_at_admission`` snapshot — not the patient's list at the
end of the simulation. ED and outpatient records carry the snapshot too."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers.section_builders.hpi import build_hpi
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.patient.medication_timeline import medications_at_encounter, note_encounter_medications
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import StaffRoster, generate_roster
from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.document import DocumentType
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import HomeMedication, PatientProfile

pytestmark = pytest.mark.unit

_METFORMIN = {"drug_name": "Metformin", "drug_name_ja": "メトホルミン", "route": "PO", "dose": "500mg"}
_GLARGINE = {"drug_name": "Insulin glargine", "drug_name_ja": "インスリングラルギン", "route": "SC", "dose": "10U"}


def _record(encounter_type: str, at_start: list[dict] | None, current: list[dict]) -> dict:
    record: dict = {
        "patient": {
            "patient_id": "POP-3262",
            "age": 64,
            "sex": "M",
            "current_medications": current,
            "chronic_conditions": [{"code": "E11"}],
        },
        "encounters": [
            {
                "encounter_id": "ENC-3262",
                "encounter_type": encounter_type,
                "admission_datetime": "2026-06-21T10:00:00",
                "chief_complaint": "倦怠感",
            }
        ],
    }
    if at_start is not None:
        record["home_medications_at_admission"] = at_start
    return record


def _hpi(record: dict, doc_type: DocumentType) -> tuple[str, list[str]]:
    ctx = build_narrative_context(record, record["encounters"][0], doc_type, 0, "JP")
    if doc_type == DocumentType.ED_NOTE:
        ctx.encounter_protocol = load_encounter_condition("renal_colic")
    return build_hpi(TemplateNarrativeGenerator(), ctx)


@pytest.mark.parametrize(
    ("encounter_type", "doc_type"),
    [("inpatient", DocumentType.ADMISSION_HP), ("emergency", DocumentType.ED_NOTE)],
)
def test_the_hpi_names_only_the_medications_taken_when_the_encounter_began(
    encounter_type: str, doc_type: DocumentType
) -> None:
    # Insulin glargine was first prescribed at this stay's discharge.
    text, facts = _hpi(_record(encounter_type, [_METFORMIN], current=[_GLARGINE, _METFORMIN]), doc_type)
    assert "メトホルミン" in text
    assert "インスリングラルギン" not in text
    assert "ctx.patient.current_medications" not in facts
    if doc_type == DocumentType.ED_NOTE:
        assert "疝痛" in text  # the ED note template branch


def test_no_medications_when_the_encounter_began_omits_the_sentence() -> None:
    text, _ = _hpi(_record("inpatient", [], current=[_GLARGINE]), DocumentType.ADMISSION_HP)
    assert "インスリングラルギン" not in text
    assert "常用薬" not in text


def test_a_record_without_the_snapshot_falls_back_to_the_patient_list() -> None:
    text, _ = _hpi(_record("inpatient", None, current=[_METFORMIN]), DocumentType.ADMISSION_HP)
    assert "メトホルミン" in text


# --- simulator: the snapshot on ED and outpatient records -------------------

_AMLODIPINE = HomeMedication(drug_name="Amlodipine", dose="5mg", frequency="daily")
_ATORVASTATIN = HomeMedication(drug_name="Atorvastatin", dose="10mg", frequency="daily")


def _noted_stay(patient: PatientProfile, start: str, end: str, after: list[HomeMedication]) -> None:
    """A stay simulated whole at its start: the patient's live list already
    holds the discharge medications ``after``."""
    patient.current_medications = list(after)
    enc = Encounter(
        encounter_id=f"ENC-{start}",
        patient_id=patient.patient_id,
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime.fromisoformat(start),
        discharge_datetime=datetime.fromisoformat(end),
    )
    note_encounter_medications(CIFPatientRecord(patient=patient, encounters=[enc]))


def test_the_live_list_is_the_list_when_no_later_encounter_was_simulated() -> None:
    patient = PatientProfile(patient_id="P1", age=60, sex="M", current_medications=[_AMLODIPINE])
    patient.visit_ledger.medications_at_activation = ()
    _noted_stay(patient, "2026-03-01T10:00:00", "2026-03-05T10:00:00", [_AMLODIPINE, _ATORVASTATIN])
    # A change after the last encounter (e.g. the longitudinal engine) is kept.
    patient.current_medications = [_ATORVASTATIN]
    assert medications_at_encounter(patient, datetime(2026, 4, 1, 9)) == [_ATORVASTATIN]


def test_a_visit_inside_an_already_simulated_stay_reads_the_list_before_it() -> None:
    patient = PatientProfile(patient_id="P1", age=60, sex="M", current_medications=[_AMLODIPINE])
    patient.visit_ledger.medications_at_activation = (_AMLODIPINE,)
    _noted_stay(patient, "2026-03-01T10:00:00", "2026-03-20T10:00:00", [_AMLODIPINE, _ATORVASTATIN])
    assert medications_at_encounter(patient, datetime(2026, 3, 10, 9)) == [_AMLODIPINE]


def _patient(country: str = "US") -> PatientProfile:
    rng = determinism.default_rng(3)
    person = PersonRecord(
        person_id="T-3262", household_id="H-1", age=60, sex="M", date_of_birth=datetime(1966, 1, 1).date()
    )
    patient = activate_patient(person, rng, load_demographics(country))
    patient.current_medications = [_AMLODIPINE]
    return patient


def test_an_ed_record_carries_the_medications_at_arrival() -> None:
    patient = _patient()
    rng = determinism.default_rng(3)
    record = _simulate_ed_visit(
        patient,
        load_encounter_condition("renal_colic"),
        datetime(2026, 6, 1, 14, 0),
        generate_roster("medium", "US", rng),
        rng,
        country="US",
        force_severity="mild",
    )
    assert record.home_medications_at_admission == [_AMLODIPINE]
    assert record.home_medications_at_admission is not patient.current_medications


def test_an_outpatient_record_carries_the_medications_at_the_visit() -> None:
    patient = _patient()
    record = _simulate_outpatient_visit(
        patient,
        "chronic_followup",
        datetime(2026, 5, 1, 10, 0),
        StaffRoster(),
        np.random.default_rng(0),
        chronic_code="I10",
        country="US",
    )
    assert record.home_medications_at_admission == [_AMLODIPINE]
    assert record.home_medications_at_admission is not patient.current_medications
