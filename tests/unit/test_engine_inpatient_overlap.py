"""Tests for the in-hospital complication merge (Issue #848).

When a new life event fires for a patient who is already admitted for
an earlier event, the dispatch loop must NOT open a second concurrent
inpatient encounter. Instead the disease id is merged into the active
encounter as an in-hospital complication:

- appended to ``complications_occurred``
- added to ``condition_event.ground_truth_diseases`` (dedup)
- ``condition_event.condition_type`` promoted from single-condition
  labels to ``"mixed"``
- a ``working_diagnoses`` entry is added with the intra-admission
  onset day + timestamp so downstream FHIR emit can render the
  complication as a secondary Condition timestamped at onset, not at
  admission
"""

from __future__ import annotations

from datetime import datetime

from clinosim.simulator.engine import (
    _find_active_inpatient_record,
    _merge_disease_into_active_encounter,
)
from clinosim.types.clinical import ClinicalDiagnosis, ConditionEvent
from clinosim.types.encounter import Encounter, EncounterStatus, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile


def _make_patient(pid: str) -> PatientProfile:
    return PatientProfile(patient_id=pid)


def _make_inpatient_record(
    pid: str,
    admit: datetime,
    discharge: datetime | None,
    primary_disease: str = "acute_pancreatitis",
) -> CIFPatientRecord:
    enc = Encounter(
        encounter_id=f"ENC-{pid}-1",
        patient_id=pid,
        episode_id=f"EP-{pid}-1",
        encounter_type=EncounterType.INPATIENT,
        status=EncounterStatus.COMPLETED if discharge else EncounterStatus.IN_PROGRESS,
        department_id="gastroenterology",
        attending_physician_id="DR-GI-001",
        admission_datetime=admit,
        discharge_datetime=discharge,
        chief_complaint="Severe epigastric pain",
    )
    return CIFPatientRecord(
        patient=_make_patient(pid),
        encounters=[enc],
        orders=[],
        vital_signs=[],
        lab_results=[],
        procedures=[],
        rehab_sessions=[],
        documents=[],
        medication_administrations=[],
        intake_output_records=[],
        adl_assessments=[],
        nursing_risk_assessments=[],
        immunizations=[],
        family_history=[],
        code_status=[],
        care_level=[],
        microbiology=[],
        discharge_prescription=[],
        condition_event=ConditionEvent(
            condition_id=f"COND-{pid}-1",
            condition_type="known_disease",
            ground_truth_diseases=[primary_disease],
            presenting_symptoms=[],
        ),
        clinical_diagnosis=ClinicalDiagnosis(
            admission_diagnosis_code="K85.9",
            admission_diagnosis_system="icd-10-mhlw",
            working_diagnoses=[],
            discharge_diagnosis_code="K85.9",
            discharge_diagnosis_system="icd-10-mhlw",
            diagnosis_correct=True,
            missed_diagnoses=[],
            overcalled_diagnoses=[],
        ),
        complications_occurred=[],
    )


def test_find_active_returns_none_when_no_records():
    assert _find_active_inpatient_record([], "POP-X", datetime(2026, 1, 1)) is None


def test_find_active_returns_none_when_patient_admitted_after_event_time():
    rec = _make_inpatient_record("POP-1", datetime(2026, 3, 10, 9), datetime(2026, 3, 25, 12))
    assert _find_active_inpatient_record([rec], "POP-1", datetime(2026, 3, 5, 12)) is None


def test_find_active_returns_none_when_patient_already_discharged():
    rec = _make_inpatient_record("POP-1", datetime(2026, 3, 10, 9), datetime(2026, 3, 20, 12))
    assert _find_active_inpatient_record([rec], "POP-1", datetime(2026, 3, 25, 12)) is None


def test_find_active_returns_record_when_currently_admitted():
    rec = _make_inpatient_record("POP-1", datetime(2026, 3, 10, 9), datetime(2026, 3, 25, 12))
    found = _find_active_inpatient_record([rec], "POP-1", datetime(2026, 3, 15, 12))
    assert found is rec


def test_find_active_returns_record_when_still_admitted_at_snapshot():
    """discharge_datetime is None → patient still admitted → active."""
    rec = _make_inpatient_record("POP-1", datetime(2026, 3, 10, 9), None)
    found = _find_active_inpatient_record([rec], "POP-1", datetime(2026, 4, 15, 12))
    assert found is rec


def test_find_active_ignores_other_patients():
    rec = _make_inpatient_record("POP-1", datetime(2026, 3, 10, 9), datetime(2026, 3, 25, 12))
    assert _find_active_inpatient_record([rec], "POP-2", datetime(2026, 3, 15, 12)) is None


def test_find_active_ignores_outpatient_records():
    rec = _make_inpatient_record("POP-1", datetime(2026, 3, 10, 9), datetime(2026, 3, 25, 12))
    rec.encounters[0].encounter_type = EncounterType.OUTPATIENT
    assert _find_active_inpatient_record([rec], "POP-1", datetime(2026, 3, 15, 12)) is None


def test_find_active_picks_most_recent_when_multiple():
    """Should not happen in practice (fix should prevent it) but be defensive."""
    rec_early = _make_inpatient_record("POP-1", datetime(2026, 3, 1, 9), datetime(2026, 4, 1, 12))
    rec_late = _make_inpatient_record("POP-1", datetime(2026, 3, 20, 9), datetime(2026, 4, 15, 12))
    rec_late.encounters[0].encounter_id = "ENC-POP-1-2"
    found = _find_active_inpatient_record([rec_early, rec_late], "POP-1", datetime(2026, 3, 25, 12))
    assert found is rec_late


def test_merge_appends_to_complications_occurred():
    rec = _make_inpatient_record("POP-1", datetime(2026, 3, 10, 9), datetime(2026, 3, 25, 12))
    _merge_disease_into_active_encounter(rec, "acute_myocardial_infarction", datetime(2026, 3, 15, 12))
    assert rec.complications_occurred == ["acute_myocardial_infarction"]


def test_merge_is_idempotent_on_complications():
    rec = _make_inpatient_record("POP-1", datetime(2026, 3, 10, 9), datetime(2026, 3, 25, 12))
    _merge_disease_into_active_encounter(rec, "acute_myocardial_infarction", datetime(2026, 3, 15, 12))
    _merge_disease_into_active_encounter(rec, "acute_myocardial_infarction", datetime(2026, 3, 18, 12))
    assert rec.complications_occurred == ["acute_myocardial_infarction"]


def test_merge_promotes_condition_type_to_mixed():
    rec = _make_inpatient_record("POP-1", datetime(2026, 3, 10, 9), datetime(2026, 3, 25, 12))
    assert rec.condition_event.condition_type == "known_disease"
    _merge_disease_into_active_encounter(rec, "acute_myocardial_infarction", datetime(2026, 3, 15, 12))
    assert rec.condition_event.condition_type == "mixed"


def test_merge_appends_to_ground_truth_diseases():
    rec = _make_inpatient_record("POP-1", datetime(2026, 3, 10, 9), datetime(2026, 3, 25, 12))
    _merge_disease_into_active_encounter(rec, "acute_myocardial_infarction", datetime(2026, 3, 15, 12))
    assert "acute_pancreatitis" in rec.condition_event.ground_truth_diseases
    assert "acute_myocardial_infarction" in rec.condition_event.ground_truth_diseases


def test_merge_appends_working_diagnosis_with_onset_day():
    rec = _make_inpatient_record("POP-1", datetime(2026, 3, 10, 9), datetime(2026, 3, 25, 12))
    _merge_disease_into_active_encounter(rec, "acute_myocardial_infarction", datetime(2026, 3, 15, 12))
    wds = rec.clinical_diagnosis.working_diagnoses
    assert len(wds) == 1
    wd = wds[0]
    assert wd["disease_id"] == "acute_myocardial_infarction"
    assert wd["onset_day"] == 5
    assert wd["source"] == "in_hospital_complication"
    assert wd["onset_datetime"].startswith("2026-03-15")


def test_merge_does_not_overwrite_condition_type_if_already_mixed():
    rec = _make_inpatient_record("POP-1", datetime(2026, 3, 10, 9), datetime(2026, 3, 25, 12))
    rec.condition_event.condition_type = "mixed"
    _merge_disease_into_active_encounter(rec, "acute_myocardial_infarction", datetime(2026, 3, 15, 12))
    assert rec.condition_event.condition_type == "mixed"


def test_merge_records_zero_onset_day_when_event_on_admit_day():
    rec = _make_inpatient_record("POP-1", datetime(2026, 3, 10, 9), datetime(2026, 3, 25, 12))
    _merge_disease_into_active_encounter(rec, "acute_myocardial_infarction", datetime(2026, 3, 10, 14))
    wd = rec.clinical_diagnosis.working_diagnoses[0]
    assert wd["onset_day"] == 0


def test_merge_clamps_negative_onset_day_to_zero():
    """When a readmission (early) merges into a later life-event encounter,
    event_time < admit_dt → onset_day would be negative. Clamp to 0."""
    rec = _make_inpatient_record("POP-1", datetime(2026, 6, 23, 12), datetime(2026, 7, 9, 12))
    _merge_disease_into_active_encounter(rec, "heart_failure_exacerbation", datetime(2026, 6, 17, 12))
    wd = rec.clinical_diagnosis.working_diagnoses[0]
    assert wd["onset_day"] == 0


# --- Period-overlap helper (readmission dispatch gate) ---


def test_find_overlapping_returns_none_when_no_records():
    from clinosim.simulator.engine import _find_overlapping_inpatient_record

    assert _find_overlapping_inpatient_record([], "POP-X", datetime(2026, 1, 1)) is None


def test_find_overlapping_detects_future_admission():
    """Readmission scheduled for 6/17 overlaps a life-event admission starting 6/23."""
    from clinosim.simulator.engine import _find_overlapping_inpatient_record

    later_rec = _make_inpatient_record("POP-1", datetime(2026, 6, 23, 12), datetime(2026, 7, 9, 12))
    found = _find_overlapping_inpatient_record([later_rec], "POP-1", datetime(2026, 6, 17, 12))
    assert found is later_rec


def test_find_overlapping_ignores_admission_far_after_window():
    """An admission 60 days after event_time (> 30-day default window) does not overlap."""
    from clinosim.simulator.engine import _find_overlapping_inpatient_record

    far_rec = _make_inpatient_record("POP-1", datetime(2026, 8, 20, 12), datetime(2026, 9, 5, 12))
    assert _find_overlapping_inpatient_record([far_rec], "POP-1", datetime(2026, 6, 17, 12)) is None


def test_find_overlapping_ignores_ended_admission():
    """An admission that discharged before event_time does not overlap."""
    from clinosim.simulator.engine import _find_overlapping_inpatient_record

    past_rec = _make_inpatient_record("POP-1", datetime(2026, 5, 1, 12), datetime(2026, 5, 20, 12))
    assert _find_overlapping_inpatient_record([past_rec], "POP-1", datetime(2026, 6, 17, 12)) is None


def test_find_overlapping_returns_earliest_when_multiple():
    """Merge into the earlier stay so the disease is attached to the primary
    admission rather than a subsequent one."""
    from clinosim.simulator.engine import _find_overlapping_inpatient_record

    rec_early = _make_inpatient_record("POP-1", datetime(2026, 6, 20, 12), datetime(2026, 7, 10, 12))
    rec_late = _make_inpatient_record("POP-1", datetime(2026, 6, 25, 12), datetime(2026, 7, 15, 12))
    rec_late.encounters[0].encounter_id = "ENC-POP-1-2"
    found = _find_overlapping_inpatient_record([rec_early, rec_late], "POP-1", datetime(2026, 6, 17, 12))
    assert found is rec_early


# --- Post-hoc actual-period overlap verifier (Issue #1430) ---
#
# The pre-dispatch gates (``_find_active_inpatient_record`` +
# ``_find_overlapping_inpatient_record``) key off ``event_time =
# datetime(year, month, day, 12, 0)`` because the life-event stream is
# date-precision. The actual admit hour is not decided until
# ``_simulate_patient`` runs, so both gates can miss overlaps at the
# hour level. ``_verify_no_actual_overlap`` runs after simulation with
# the real ``admission_datetime`` / ``discharge_datetime`` on the new
# record and closes the residual gap.


def test_verify_no_actual_overlap_returns_none_when_no_prior_records():
    from clinosim.simulator.engine import _verify_no_actual_overlap

    new_rec = _make_inpatient_record("POP-1", datetime(2026, 2, 7, 18, 3), datetime(2026, 2, 12, 12, 3))
    assert _verify_no_actual_overlap([], new_rec) is None


def test_verify_detects_us_same_day_two_late_admits():
    """Reproduces the US p=10000 s=359 case: two same-day life events for
    one person, both landing after noon. The pre-dispatch gate at
    date+noon sees the first record as ``admission (18:03) > noon``, so
    the second record's noon check is passed, but at simulate time it
    lands at 19:46 — a concurrent stay the noon gate could never catch.
    """
    from clinosim.simulator.engine import _verify_no_actual_overlap

    prior = _make_inpatient_record("POP-1", datetime(2026, 2, 7, 18, 3), datetime(2026, 2, 12, 12, 3))
    new_rec = _make_inpatient_record(
        "POP-1", datetime(2026, 2, 7, 19, 46), datetime(2026, 2, 11, 13, 46), primary_disease="acute_mi"
    )
    new_rec.encounters[0].encounter_id = "ENC-POP-1-2"
    found = _verify_no_actual_overlap([prior], new_rec)
    assert found is prior


def test_verify_detects_readmit_before_prior_discharge():
    """Reproduces the JP p=10000 s=359 case: prior stay discharges at
    10:37, readmission's noon gate sees ``rec_end (10:37) <= noon`` and
    skips it. Readmission simulates and lands at 06:12 — before the
    prior discharge, i.e. a time-machine violation.
    """
    from clinosim.simulator.engine import _verify_no_actual_overlap

    prior = _make_inpatient_record("POP-2", datetime(2026, 7, 22, 0, 37), datetime(2026, 8, 16, 10, 37))
    new_rec = _make_inpatient_record(
        "POP-2", datetime(2026, 8, 16, 6, 12), datetime(2026, 9, 4, 11, 12), primary_disease="heart_failure"
    )
    new_rec.encounters[0].encounter_id = "ENC-POP-2-2"
    found = _verify_no_actual_overlap([prior], new_rec)
    assert found is prior


def test_verify_returns_none_when_periods_are_disjoint():
    """No overlap → returns None. Prior ends 12:03 on 2/12, new starts
    12:04 on 2/12 → no intersection under half-open interval semantics."""
    from clinosim.simulator.engine import _verify_no_actual_overlap

    prior = _make_inpatient_record("POP-1", datetime(2026, 2, 7, 18, 3), datetime(2026, 2, 12, 12, 3))
    new_rec = _make_inpatient_record(
        "POP-1", datetime(2026, 2, 12, 12, 4), datetime(2026, 2, 15, 10, 0), primary_disease="acute_mi"
    )
    new_rec.encounters[0].encounter_id = "ENC-POP-1-2"
    assert _verify_no_actual_overlap([prior], new_rec) is None


def test_verify_ignores_other_patients():
    from clinosim.simulator.engine import _verify_no_actual_overlap

    prior = _make_inpatient_record("POP-99", datetime(2026, 2, 7, 18, 3), datetime(2026, 2, 12, 12, 3))
    new_rec = _make_inpatient_record("POP-1", datetime(2026, 2, 7, 19, 46), datetime(2026, 2, 11, 13, 46))
    assert _verify_no_actual_overlap([prior], new_rec) is None


def test_verify_ignores_outpatient_records():
    from clinosim.simulator.engine import _verify_no_actual_overlap

    prior = _make_inpatient_record("POP-1", datetime(2026, 2, 7, 18, 3), datetime(2026, 2, 12, 12, 3))
    prior.encounters[0].encounter_type = EncounterType.OUTPATIENT
    new_rec = _make_inpatient_record("POP-1", datetime(2026, 2, 7, 19, 46), datetime(2026, 2, 11, 13, 46))
    new_rec.encounters[0].encounter_id = "ENC-POP-1-2"
    assert _verify_no_actual_overlap([prior], new_rec) is None


def test_verify_ignores_self_reference():
    """Defensive: even if the new record were somehow already in the list
    it must not match itself as its own overlap."""
    from clinosim.simulator.engine import _verify_no_actual_overlap

    new_rec = _make_inpatient_record("POP-1", datetime(2026, 2, 7, 18, 3), datetime(2026, 2, 12, 12, 3))
    assert _verify_no_actual_overlap([new_rec], new_rec) is None


def test_verify_returns_earliest_when_multiple_overlap():
    """When more than one prior record overlaps, return the earliest so
    the disease merges into the primary stay (matches the pre-dispatch
    gate's behavior)."""
    from clinosim.simulator.engine import _verify_no_actual_overlap

    early = _make_inpatient_record("POP-1", datetime(2026, 2, 7, 10, 0), datetime(2026, 2, 20, 10, 0))
    late = _make_inpatient_record(
        "POP-1", datetime(2026, 2, 10, 12, 0), datetime(2026, 2, 15, 12, 0), primary_disease="secondary_dx"
    )
    late.encounters[0].encounter_id = "ENC-POP-1-2"
    new_rec = _make_inpatient_record(
        "POP-1", datetime(2026, 2, 12, 6, 0), datetime(2026, 2, 18, 12, 0), primary_disease="tertiary_dx"
    )
    new_rec.encounters[0].encounter_id = "ENC-POP-1-3"
    found = _verify_no_actual_overlap([early, late], new_rec)
    assert found is early


def test_verify_new_stay_still_admitted_treats_as_infinite():
    """A new record with discharge_datetime=None (still admitted at
    snapshot) must be treated as extending to +inf, so any prior stay
    whose end is after the new admit still overlaps."""
    from clinosim.simulator.engine import _verify_no_actual_overlap

    prior = _make_inpatient_record("POP-1", datetime(2026, 2, 7, 18, 3), datetime(2026, 2, 20, 12, 0))
    new_rec = _make_inpatient_record("POP-1", datetime(2026, 2, 15, 6, 0), None, primary_disease="acute_mi")
    new_rec.encounters[0].encounter_id = "ENC-POP-1-2"
    found = _verify_no_actual_overlap([prior], new_rec)
    assert found is prior


def test_verify_prior_still_admitted_treats_as_infinite():
    """A prior record still admitted at snapshot (discharge_datetime=None)
    must be treated as +inf, so any subsequent same-patient stay
    overlaps."""
    from clinosim.simulator.engine import _verify_no_actual_overlap

    prior = _make_inpatient_record("POP-1", datetime(2026, 2, 7, 18, 3), None)
    new_rec = _make_inpatient_record(
        "POP-1", datetime(2026, 3, 1, 6, 0), datetime(2026, 3, 10, 12, 0), primary_disease="acute_mi"
    )
    new_rec.encounters[0].encounter_id = "ENC-POP-1-2"
    found = _verify_no_actual_overlap([prior], new_rec)
    assert found is prior
