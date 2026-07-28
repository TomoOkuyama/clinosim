"""A' Phase 1 (Issue #440): patient_cache.current_medications sync invariant.

Observable behavior under test:

    "A drug newly added to a patient's discharge_prescription on encounter N
    appears as a home medication order on encounter N+1."

Master state (pre-A' Phase 1): _deactivate_to_layer1 mutates
``person.current_medications`` (Layer 1 PersonRecord) but has no reference to
the cached ``PatientProfile`` in ``engine.py:patient_cache``. Consumers on
encounter N+1 read ``patient.current_medications`` (the Layer 2 cached
profile, see ``inpatient.py:1416`` in ``_generate_home_medication_orders``)
which is frozen at ``activate_patient`` time — the newly prescribed drug is
silently invisible.

Post-A' state: ``_deactivate_to_layer1`` accepts an optional ``patient_cache``
kwarg. Engine passes it at both call sites (``engine.py:441`` +
``engine.py:525``). After the discharge_prescription is applied to
``person.current_medications``, the cache profile is synced to match. On
encounter N+1 (cache hit), the consumer reads the up-to-date list and the
drug appears as a home medication order.

Test design:
* NOT asserting on ``patient_cache[pid].current_medications`` directly — that
  is the internal state and would tie the test to the current mechanism.
* Instead assert on the OUTPUT of ``_generate_home_medication_orders`` for
  the second encounter, which is the consumer-side observable behavior.
* Encounter 1 uses a synthetic ``CIFPatientRecord`` with a fixed
  ``discharge_prescription`` containing an anticoagulant. This isolates A'
  from the stochasticity of ``_simulate_patient`` and keeps the test fast.
* Precondition sanity check: the patient has NO anticoagulant in the initial
  ``current_medications`` (chronic_conditions=[] → no I48/I26/I82-driven
  anticoag from ``_derive_home_medications``). So any anticoag observed on
  encounter 2 came from the encounter-1 discharge.

Fail mode on master: this test either fails with ``TypeError`` (unknown
kwarg) or, if the kwarg is silently ignored, fails the anticoag-in-orders
assertion.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_demographics
from clinosim.modules.patient.activator import activate_patient
from clinosim.simulator.helpers import _deactivate_to_layer1
from clinosim.simulator.inpatient import _generate_home_medication_orders
from clinosim.types.encounter import (
    Encounter,
    EncounterType,
    PrescriptionRecord,
)
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile
from clinosim.types.population import PersonRecord

ANTICOAG_TERMS = ("warfarin", "apixaban", "rivaroxaban", "edoxaban", "dabigatran")


def _has_anticoag(names: list[str]) -> bool:
    return any(any(term in n.lower() for term in ANTICOAG_TERMS) for n in names)


def _make_person() -> PersonRecord:
    """Person without anticoag-relevant chronic conditions.

    Chronic conditions list is empty so ``_derive_home_medications`` does not
    seed any anticoagulant at activate time (I48 / I26 / I82 would seed one).
    """
    return PersonRecord(
        person_id="TEST-APRIME-001",
        household_id="HH-APRIME-001",
        age=68,
        sex="M",
        date_of_birth=date(1957, 4, 1),
        family_name="Test",
        given_name="Patient",
        chronic_conditions=[],
    )


def _make_encounter(person_id: str, admission: datetime, discharge: datetime) -> Encounter:
    return Encounter(
        encounter_id=f"ENC-{person_id}-01",
        patient_id=person_id,
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=admission,
        discharge_datetime=discharge,
    )


def _synthetic_pe_record(patient: PatientProfile, person_id: str) -> CIFPatientRecord:
    """Encounter 1 record with a fixed anticoag discharge_prescription.

    Bypasses ``_simulate_patient`` so this test measures only the A' sync,
    not the stochastic clinical course. Uses PE (``pulmonary_embolism``) as
    disease_id — its ``discharge_oral`` block is anticoag-mandatory in
    production data, so a real run would also produce this shape.
    """
    admission = datetime(2025, 3, 10, 12, 0)
    discharge = datetime(2025, 3, 15, 12, 0)
    enc = _make_encounter(person_id, admission, discharge)
    rx = PrescriptionRecord(
        prescription_id="RX-TEST-DC",
        patient_id=person_id,
        prescriber_id="ATTEND-01",
        issue_date=discharge,
        items=[
            {
                "drug_name": "Warfarin 3mg",
                "dose": "3mg",
                "route": "PO",
                "duration_days": 90,
            }
        ],
    )
    return CIFPatientRecord(
        patient=patient,
        encounters=[enc],
        discharge_prescription=rx,
    )


@pytest.mark.unit
def test_a_prime_anticoag_from_discharge_appears_as_home_med_next_encounter():
    """E2E behavior: warfarin newly prescribed at encounter 1 discharge must
    show up as a home medication order at encounter 2.

    Sync happens inside ``_deactivate_to_layer1`` via the new ``patient_cache``
    kwarg. The assert is on the consumer side (``_generate_home_medication_orders``
    output), NOT on the cache's internal state.
    """
    rng = np.random.default_rng(42)
    demo = load_demographics("US")
    person = _make_person()

    # Mimic engine.py: cache PatientProfile once
    patient_cache: dict[str, PatientProfile] = {}
    patient_cache[person.person_id] = activate_patient(person, rng, demo)

    # Precondition: no anticoag in initial cached profile
    initial_meds = list(patient_cache[person.person_id].current_medications)
    assert not _has_anticoag(initial_meds), (
        f"precondition failure: cached profile already has anticoag in "
        f"current_medications: {initial_meds}. Test setup is invalid."
    )

    # Encounter 1: synthetic record with warfarin discharge
    record1 = _synthetic_pe_record(patient_cache[person.person_id], person.person_id)

    # A' behavior under test: patient_cache kwarg passed → sync fires
    _deactivate_to_layer1(person, record1, "pulmonary_embolism", patient_cache=patient_cache)

    # Encounter 2 setup: same person, cache hit returns SAME PatientProfile.
    # Simulate the consumer path (`_generate_home_medication_orders`) directly.
    patient_enc2 = patient_cache[person.person_id]
    orders, _monitoring = _generate_home_medication_orders(
        patient_enc2,
        encounter_id="ENC-TEST-APRIME-001-02",
        admission_time=datetime(2025, 6, 10, 12, 0),
        attending_id="ATTEND-01",
        rng=rng,
    )

    order_names = [o.display_name for o in orders]
    assert _has_anticoag(order_names), (
        "A' invariant violation: warfarin newly prescribed at encounter 1 "
        "discharge did not appear as a home medication order at encounter 2. "
        f"Home med order display_names: {order_names}. "
        f"person.current_medications (Layer 1, updated): {person.current_medications}. "
        f"patient_cache profile.current_medications (Layer 2, should be synced): "
        f"{patient_enc2.current_medications}."
    )
