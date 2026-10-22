"""Issue #1759 — the baby snapshot anthropometry pass back-propagated
end-of-sim age / height / weight onto the DELIVERY encounter record,
producing records like `POP-000445-BABY dob=2025-04-16 delivery
encounter 2025-04 → age=3, h=97.0, w=14.7`.

Fix: ``_apply_baby_snapshot_anthropometry`` becomes a no-op when the
record it's writing represents the delivery encounter (admission
within ~1 day of DOB). Later encounters (admission >1 day after DOB)
continue to receive the snapshot-date growth-chart catch-up as before.

Scope: write-time CIF patch only. The in-memory PatientProfile is
unchanged — this patch only prevents the CIF writer from stamping
end-of-sim values onto the delivery record.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.output.cif_writer import _apply_baby_snapshot_anthropometry

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Repro: the delivery encounter record stays age=0 after the pass runs.
# ---------------------------------------------------------------------------


def _newborn_dict(dob_iso: str) -> dict:
    return {
        "patient_id": "POP-000445-BABY",
        "sex": "M",
        "age": 0,
        "date_of_birth": dob_iso,
        "height_cm": 50.0,
        "weight_kg": 3.2,
        "bmi": 12.8,
    }


def test_delivery_encounter_record_preserves_newborn_scalars():
    """DOB and admission on the same day → delivery record. The pass
    must leave the newborn's hardcoded 50/3.2/12.8/age=0 in place even
    when snapshot_date is 3 years later."""
    patient_dict = _newborn_dict("2025-04-16")
    admission = datetime(2025, 4, 16, 10, 0)
    _apply_baby_snapshot_anthropometry(
        patient_dict,
        "2028-12-31",
        "US",
        admission_datetime=admission,
    )
    assert patient_dict["age"] == 0, f"expected age=0 at delivery, got {patient_dict['age']}"
    assert patient_dict["height_cm"] == 50.0
    assert patient_dict["weight_kg"] == 3.2
    assert patient_dict["bmi"] == 12.8


def test_delivery_encounter_within_one_day_still_preserves():
    """Admission one calendar day after DOB (occasional late-evening
    delivery that chart-stamps midnight+1) still counts as the delivery
    record."""
    patient_dict = _newborn_dict("2025-04-16")
    admission = datetime(2025, 4, 17, 2, 30)
    _apply_baby_snapshot_anthropometry(
        patient_dict,
        "2028-12-31",
        "US",
        admission_datetime=admission,
    )
    assert patient_dict["age"] == 0
    assert patient_dict["height_cm"] == 50.0


def test_later_encounter_receives_catchup_as_before():
    """Admission 2 years after DOB → growth-chart p50 at age 2
    (US male h=91, w=13.3). This is the pre-existing behaviour that
    the fix must not regress."""
    patient_dict = _newborn_dict("2024-01-10")
    admission = datetime(2026, 6, 15, 10, 0)
    _apply_baby_snapshot_anthropometry(
        patient_dict,
        "2026-06-15",
        "US",
        admission_datetime=admission,
    )
    assert patient_dict["age"] == 2
    assert patient_dict["height_cm"] == 91.0
    assert patient_dict["weight_kg"] == 13.3


def test_admission_datetime_none_falls_through_to_pre_fix_behaviour():
    """Legacy callers that don't pass ``admission_datetime`` keep the
    pre-#1759 unconditional-catchup semantics (no behaviour change)."""
    patient_dict = _newborn_dict("2024-01-10")
    _apply_baby_snapshot_anthropometry(patient_dict, "2026-06-15", "US")
    # Pre-fix behaviour: unconditional catch-up to snapshot age.
    assert patient_dict["age"] == 2
    assert patient_dict["height_cm"] == 91.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_non_baby_patient_still_untouched():
    """A non-BABY patient id (adult / pre-sim pediatric) continues to
    be a no-op regardless of admission_datetime — the pass's scope was
    always BABY-only."""
    patient_dict = {
        "patient_id": "POP-000445",
        "sex": "M",
        "age": 42,
        "date_of_birth": "1982-04-16",
        "height_cm": 175.0,
        "weight_kg": 70.0,
        "bmi": 22.9,
    }
    _apply_baby_snapshot_anthropometry(
        patient_dict,
        "2026-01-01",
        "US",
        admission_datetime=datetime(2026, 1, 1, 10, 0),
    )
    assert patient_dict["age"] == 42
    assert patient_dict["height_cm"] == 175.0


def test_admission_before_dob_falls_back_to_catchup():
    """Pathological: admission_datetime BEFORE dob (should not happen
    in production). Guard: if admission is before dob, the pass does
    not treat it as the delivery encounter; falls through to the
    standard catch-up path. The catch-up itself exits early when
    ``snap_d < dob_d``, so the net effect is a no-op."""
    patient_dict = _newborn_dict("2025-04-16")
    admission = datetime(2024, 12, 1, 10, 0)
    _apply_baby_snapshot_anthropometry(
        patient_dict,
        "2024-12-01",
        "US",
        admission_datetime=admission,
    )
    # snap_d < dob_d early return in the catch-up body: nothing changes.
    assert patient_dict["age"] == 0
    assert patient_dict["height_cm"] == 50.0


# ---------------------------------------------------------------------------
# Boundary: 2-day-after-DOB falls into the catch-up regime (not delivery).
# This encodes the chosen cutoff; any widening will need an explicit test
# bump.
# ---------------------------------------------------------------------------


def test_admission_two_days_after_dob_is_not_delivery():
    """Admission >1 day after DOB falls into the standard catch-up
    regime. Growth-chart age-0 median (US male: 74 / 9.6)."""
    patient_dict = _newborn_dict("2024-01-10")
    admission = datetime(2024, 1, 12, 10, 0)  # 2 days after dob
    _apply_baby_snapshot_anthropometry(
        patient_dict,
        "2024-01-12",
        "US",
        admission_datetime=admission,
    )
    assert patient_dict["age"] == 0
    assert patient_dict["height_cm"] == 74.0  # growth-chart median kicks in
