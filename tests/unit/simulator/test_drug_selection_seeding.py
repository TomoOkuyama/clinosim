"""Sub-RNG helpers for drug selection (Issue #439 P1).

Verifies AD-16 pattern: `chronic_medication_seed(patient_id)` and
`discharge_prescription_seed(patient_id, encounter_id)` produce stable per-entity
sub-seeds that isolate drug-selection RNG streams from the patient-scoped
master RNG (sibling of `panel_specimen_seed` / `individual_lab_seed`).
"""

from __future__ import annotations

from clinosim.seeding import (
    chronic_medication_seed,
    discharge_prescription_seed,
)


def test_chronic_medication_seed_deterministic_for_same_patient():
    a = chronic_medication_seed("POP-000001")
    b = chronic_medication_seed("POP-000001")
    assert a == b


def test_chronic_medication_seed_differs_across_patients():
    a = chronic_medication_seed("POP-000001")
    b = chronic_medication_seed("POP-000002")
    assert a != b, "different patient_id should yield different sub-seed"


def test_chronic_medication_seed_in_uint32_range():
    for pid in ("POP-000001", "POP-000042", "POP-999999"):
        s = chronic_medication_seed(pid)
        assert 0 <= s < 2**32


def test_discharge_prescription_seed_deterministic_for_same_pair():
    a = discharge_prescription_seed("POP-000001", "ENC-A")
    b = discharge_prescription_seed("POP-000001", "ENC-A")
    assert a == b


def test_discharge_prescription_seed_differs_across_encounters_same_patient():
    """Multiple admissions per patient must draw independently."""
    a = discharge_prescription_seed("POP-000001", "ENC-A")
    b = discharge_prescription_seed("POP-000001", "ENC-B")
    assert a != b


def test_discharge_prescription_seed_differs_across_patients_same_encounter_name():
    """Different patients with clashing encounter ids still get different seeds."""
    a = discharge_prescription_seed("POP-000001", "ENC-A")
    b = discharge_prescription_seed("POP-000002", "ENC-A")
    assert a != b


def test_discharge_prescription_seed_isolation_from_chronic():
    """The two helpers use different salts — same patient_id must not collide."""
    chronic = chronic_medication_seed("POP-000001")
    discharge = discharge_prescription_seed("POP-000001", "")
    assert chronic != discharge


def test_discharge_prescription_seed_in_uint32_range():
    for pid, eid in (("POP-000001", "ENC-1"), ("POP-999999", "ENC-XYZ")):
        s = discharge_prescription_seed(pid, eid)
        assert 0 <= s < 2**32
