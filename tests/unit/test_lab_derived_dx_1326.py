"""Issue #1326 — lab-derived AKI Condition emit.

When an inpatient encounter's Creatinine peak crosses KDIGO Stage 3
absolute threshold (>= 4.0 mg/dL), the ``lab_derived_dx`` POST_ENCOUNTER
enricher appends a ``working_diagnoses`` N17.9 entry so downstream
FHIR emit renders a paired Condition on the encounter.

Guardrails covered:
- No emit when Cr peak is below threshold.
- No emit when N17.x already exists on encounter (primary / admission /
  discharge / working / complications_occurred).
- No emit when patient carries CKD stage 4-5 or ESRD baseline (Cr
  above threshold may be steady-state).
- Emit when threshold cleared, no existing AKI, no baseline exclusion.
- RNG-free: repeated calls on the same record are idempotent (only one
  N17.9 gets appended; subsequent runs find an existing entry and skip).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.diagnosis.lab_derived_dx import (
    LAB_DERIVED_AKI_DIAGNOSIS_CODE,
    LAB_DERIVED_AKI_SOURCE_TAG,
    enrich_lab_derived_dx,
)
from clinosim.simulator.enrichers import EnricherContext


def _mk_lab(name: str, value: float, when: datetime) -> Any:
    return SimpleNamespace(lab_name=name, value=value, result_datetime=when)


def _mk_record(
    *,
    encounter_type: str = "inpatient",
    admission: datetime,
    labs: list[Any],
    chronic_codes: tuple[str, ...] = (),
    working_diagnoses: list | None = None,
    admission_dx: str = "",
    discharge_dx: str = "",
    complications: tuple[str, ...] = (),
) -> Any:
    """Minimal CIFPatientRecord duck-type for the enricher's read surface."""
    enc = SimpleNamespace(
        encounter_type=encounter_type,
        admission_datetime=admission,
    )
    patient = SimpleNamespace(
        chronic_conditions=[SimpleNamespace(code=c) for c in chronic_codes],
    )
    cd = SimpleNamespace(
        admission_diagnosis_code=admission_dx,
        discharge_diagnosis_code=discharge_dx,
        working_diagnoses=(list(working_diagnoses) if working_diagnoses is not None else []),
    )
    return SimpleNamespace(
        encounters=[enc],
        patient=patient,
        clinical_diagnosis=cd,
        lab_results=labs,
        complications_occurred=list(complications),
    )


def _mk_ctx(records: list[Any]) -> EnricherContext:
    return EnricherContext(config=SimpleNamespace(country="US"), master_seed=42, records=records)


ADMIT = datetime(2026, 6, 1, 8, 0)
DAY7 = datetime(2026, 6, 8, 6, 0)


def test_peak_cr_above_threshold_emits_n17_working_dx():
    rec = _mk_record(
        admission=ADMIT,
        labs=[
            _mk_lab("Creatinine", 0.8, ADMIT),
            _mk_lab("Creatinine", 1.2, datetime(2026, 6, 4, 6, 0)),
            _mk_lab("Creatinine", 4.26, DAY7),
        ],
    )
    enrich_lab_derived_dx(_mk_ctx([rec]))
    wds = rec.clinical_diagnosis.working_diagnoses
    assert len(wds) == 1
    assert wds[0]["disease_id"] == LAB_DERIVED_AKI_DIAGNOSIS_CODE
    assert wds[0]["source"] == LAB_DERIVED_AKI_SOURCE_TAG
    assert wds[0]["onset_day"] == 7
    assert wds[0]["onset_datetime"] == DAY7.isoformat()


def test_peak_cr_below_threshold_no_emit():
    rec = _mk_record(
        admission=ADMIT,
        labs=[
            _mk_lab("Creatinine", 3.9, DAY7),  # just below 4.0 threshold
        ],
    )
    enrich_lab_derived_dx(_mk_ctx([rec]))
    assert rec.clinical_diagnosis.working_diagnoses == []


def test_existing_n17_admission_dx_suppresses_emit():
    rec = _mk_record(
        admission=ADMIT,
        admission_dx="N17.0",  # already tagged with AKI variant
        labs=[_mk_lab("Creatinine", 5.0, DAY7)],
    )
    enrich_lab_derived_dx(_mk_ctx([rec]))
    assert rec.clinical_diagnosis.working_diagnoses == []


def test_existing_n17_working_dx_suppresses_emit():
    rec = _mk_record(
        admission=ADMIT,
        working_diagnoses=[{"disease_id": "N17.9", "onset_day": 3, "onset_datetime": "", "source": "protocol"}],
        labs=[_mk_lab("Creatinine", 5.0, DAY7)],
    )
    enrich_lab_derived_dx(_mk_ctx([rec]))
    assert len(rec.clinical_diagnosis.working_diagnoses) == 1  # unchanged


def test_acute_kidney_injury_complication_tag_does_not_suppress_emit():
    """The daily-loop complication engine writes only the disease-YAML id
    string ``"acute_kidney_injury"`` to ``complications_occurred``; it does
    NOT populate ``working_diagnoses`` with a paired N17.x entry. The FHIR
    Condition emit path walks ``working_diagnoses`` (not
    ``complications_occurred``), so those mid-admission AKI complications
    never render as Conditions. This enricher fills that gap: when the
    complication tag is present but no explicit N17.x code is anywhere on
    the encounter, we DO append the N17.9 working-diagnoses entry."""
    rec = _mk_record(
        admission=ADMIT,
        complications=("acute_kidney_injury",),
        labs=[_mk_lab("Creatinine", 5.0, DAY7)],
    )
    enrich_lab_derived_dx(_mk_ctx([rec]))
    wds = rec.clinical_diagnosis.working_diagnoses
    assert len(wds) == 1
    assert wds[0]["disease_id"] == "N17.9"


def test_ckd_stage_4_baseline_suppresses_emit():
    rec = _mk_record(
        admission=ADMIT,
        chronic_codes=("N18.4",),  # CKD stage 4 baseline may exceed 4.0
        labs=[_mk_lab("Creatinine", 5.0, DAY7)],
    )
    enrich_lab_derived_dx(_mk_ctx([rec]))
    assert rec.clinical_diagnosis.working_diagnoses == []


def test_ckd_stage_5_baseline_suppresses_emit():
    rec = _mk_record(
        admission=ADMIT,
        chronic_codes=("N18.5",),
        labs=[_mk_lab("Creatinine", 8.0, DAY7)],
    )
    enrich_lab_derived_dx(_mk_ctx([rec]))
    assert rec.clinical_diagnosis.working_diagnoses == []


def test_outpatient_encounter_no_emit():
    rec = _mk_record(
        encounter_type="outpatient",
        admission=ADMIT,
        labs=[_mk_lab("Creatinine", 5.0, DAY7)],
    )
    enrich_lab_derived_dx(_mk_ctx([rec]))
    assert rec.clinical_diagnosis.working_diagnoses == []


def test_idempotent_across_repeated_runs():
    """Running the enricher twice on the same record must not duplicate
    the N17.9 entry — second run sees the first-run's working_diagnoses
    entry and skips."""
    rec = _mk_record(admission=ADMIT, labs=[_mk_lab("Creatinine", 4.26, DAY7)])
    enrich_lab_derived_dx(_mk_ctx([rec]))
    enrich_lab_derived_dx(_mk_ctx([rec]))
    assert len(rec.clinical_diagnosis.working_diagnoses) == 1


def test_non_creatinine_labs_ignored():
    rec = _mk_record(
        admission=ADMIT,
        labs=[
            _mk_lab("BUN", 80.0, DAY7),  # very high BUN, not Cr
            _mk_lab("Glucose", 200, DAY7),
        ],
    )
    enrich_lab_derived_dx(_mk_ctx([rec]))
    assert rec.clinical_diagnosis.working_diagnoses == []
