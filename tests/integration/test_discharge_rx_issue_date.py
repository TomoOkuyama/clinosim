"""Regression guard for Issue #466: inpatient discharge prescription's
`issue_date` must equal the encounter's `discharge_datetime`, not the
admission time.

Pre-fix behavior: `_build_discharge_rx` ran before `planned_discharge` was
computed, so the CIF stored `admission_time` as `issue_date`. Every
inpatient discharge_prescription in a JP p=300 seed=42 cohort was 7-15 days
too early. The FHIR adapter carried a workaround
(`fhir_r4_adapter.py::_bb_discharge_medication_requests` overrode
`authoredOn` for inpatient), which this fix retires.

Guards two invariants:

  1. **Inpatient**: `discharge_prescription.issue_date == discharge_datetime`
     (the backfill assignment fires).
  2. **Outpatient / ED**: `discharge_prescription.issue_date` is unchanged
     — should still equal the visit start (`admission_datetime`), since the
     backfill runs only on the completed-inpatient branch of
     `_simulate_patient`.
"""

from __future__ import annotations

import pytest

from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig
from clinosim.types.encounter import EncounterType


def _run_cohort(country: str = "JP") -> list:
    """Deterministic small cohort. Size chosen to reliably produce both
    inpatient (with discharge_rx) and outpatient encounters."""
    config = SimulatorConfig(
        country=country,
        population_size=200,
        random_seed=42,
        start_date="2025-01-01",
        snapshot_date="2026-01-01",
    )
    return run_beta(config).patients


@pytest.mark.integration
def test_inpatient_discharge_rx_issue_date_equals_discharge_datetime():
    """Every completed inpatient encounter with a discharge_prescription
    must carry `issue_date == encounter.discharge_datetime`."""
    records = _run_cohort()

    offenders = []
    checked = 0
    for r in records:
        if not r.encounters:
            continue
        enc = r.encounters[0]
        if enc.encounter_type != EncounterType.INPATIENT:
            continue
        if r.discharge_prescription is None:
            continue
        if enc.discharge_datetime is None:
            continue  # snapshot-truncated (in-progress) — no discharge_rx expected either
        checked += 1
        if r.discharge_prescription.issue_date != enc.discharge_datetime:
            offenders.append(
                (
                    r.patient_id,
                    r.discharge_prescription.issue_date,
                    enc.discharge_datetime,
                    enc.admission_datetime,
                )
            )

    assert checked > 0, "cohort produced no inpatient discharge prescriptions — test is not exercising the code path"
    assert not offenders, (
        f"{len(offenders)}/{checked} inpatient discharge_prescription.issue_date != discharge_datetime "
        f"(Issue #466 regression). Examples: {offenders[:3]}"
    )


@pytest.mark.integration
def test_outpatient_discharge_rx_issue_date_still_matches_visit_start():
    """The Issue #466 fix must NOT touch outpatient/ED behavior. Their
    `issue_date` is the visit start (== admission_datetime), because the
    backfill only fires on the completed-inpatient branch."""
    records = _run_cohort()

    offenders = []
    checked = 0
    for r in records:
        if not r.encounters:
            continue
        enc = r.encounters[0]
        if enc.encounter_type in (EncounterType.INPATIENT, EncounterType.ICU, EncounterType.REHAB_INPATIENT):
            continue
        if r.discharge_prescription is None:
            continue
        checked += 1
        if r.discharge_prescription.issue_date != enc.admission_datetime:
            offenders.append(
                (
                    r.patient_id,
                    str(enc.encounter_type),
                    r.discharge_prescription.issue_date,
                    enc.admission_datetime,
                )
            )

    # No assertion on `checked > 0` here — outpatient/ED discharge_prescription
    # emission is subject to Issue #445; on some cohorts none appear.
    assert not offenders, (
        f"{len(offenders)}/{checked} outpatient discharge_prescription.issue_date shifted from visit start "
        f"(Issue #466 fix over-reached into outpatient path). Examples: {offenders[:3]}"
    )
