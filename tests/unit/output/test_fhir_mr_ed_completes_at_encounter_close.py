"""C7a / Issue #1099: ED-course MedicationRequests must transition to
``status=completed`` at ED encounter close.

Pre-C7a the FHIR emit layer only completed ``encounter_type=="outpatient"``
and episodic ``encounter_type=="inpatient"`` Orders. Anything ordered at
an emergency encounter stayed ``status="active"`` forever, so a PRN
Ketorolac / Ibuprofen from an ED visit still appeared as an active
medication on that patient's chart months later — feeding false
"active" flags into cross-encounter drug-safety analysis and creating
spurious contraindicated pairs (89 % of the #1087 residual on the
session-100 p=10k cohort).

The ED-course Rx pattern is: patient presents to ED, receives IV
ketorolac / IM ibuprofen for pain, discharged home a few hours later.
No real EHR keeps that MR as ``active`` — it is a single-encounter
administration whose active-state semantically ends at ED discharge.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.medications.medications import (
    _build_medication_request,
)


def _order(
    drug: str = "Ketorolac",
    encounter_id: str = "ENC-ED-1",
    intent: str = "acute",
    clinical_intent: str = "ED treatment: acute pain",
    order_id: str = "ORD-ENC-ED-1-ED-T1",
) -> dict:
    return {
        "order_id": order_id,
        "encounter_id": encounter_id,
        "patient_id": "PT-1",
        "order_type": "medication",
        "order_code": "",
        "display_name": drug,
        "urgency": "urgent",
        "clinical_intent": clinical_intent,
        "clinical_intent_ja": "",
        "ordered_datetime": "2026-06-14T21:00:00Z",
        "ordered_by": "DR-ED-1",
        "status": "placed",
        "medication_intent": intent,
        "route": "IV",
        "notes": [],
        "dose_quantity": 30.0,
        "dose_unit": "mg",
        "frequency": "",
        "frequency_per_day": None,
        "duration_days": None,
    }


def test_ed_course_nsaid_status_completed() -> None:
    """The canonical residual pattern: ED Ketorolac must complete, not
    stay active."""
    order = _order(drug="Ketorolac")
    mr = _build_medication_request(
        order,
        patient_id="PT-1",
        country="us",
        encounter_id="ENC-ED-1",
        primary_dx_code="M79.1",
        encounter_type="emergency",
    )
    assert mr["status"] == "completed", (
        f"ED-course Ketorolac must complete at encounter close, got status={mr['status']!r}"
    )


def test_ed_course_ibuprofen_status_completed() -> None:
    order = _order(drug="Ibuprofen", order_id="ORD-ENC-ED-1-ED-T2")
    mr = _build_medication_request(
        order,
        patient_id="PT-1",
        country="us",
        encounter_id="ENC-ED-1",
        primary_dx_code="R51",
        encounter_type="emergency",
    )
    assert mr["status"] == "completed", (
        f"ED-course Ibuprofen must complete at encounter close, got status={mr['status']!r}"
    )


def test_ed_home_medication_stays_active() -> None:
    """A patient's chronic aspirin recorded during ED intake (marked as
    ``home medication``) must NOT complete — they are still taking it."""
    order = _order(
        drug="Aspirin",
        clinical_intent="Home medication (continue): Aspirin 81mg",
        order_id="ORD-ENC-ED-1-HOME-01",
    )
    mr = _build_medication_request(
        order,
        patient_id="PT-1",
        country="us",
        encounter_id="ENC-ED-1",
        primary_dx_code="R07.9",
        encounter_type="emergency",
    )
    assert mr["status"] == "active", (
        f"ED-recorded home Aspirin must stay active (patient is still on it), got status={mr['status']!r}"
    )


def test_inpatient_home_medication_stays_active() -> None:
    """Regression: pre-C7a behavior for home-med on inpatient must not
    change — chronic aspirin during IMP stays active."""
    order = _order(
        drug="Aspirin",
        encounter_id="ENC-IMP-1",
        clinical_intent="Home medication (continue): Aspirin 81mg",
        order_id="ORD-ENC-IMP-1-HOME-01",
    )
    mr = _build_medication_request(
        order,
        patient_id="PT-1",
        country="us",
        encounter_id="ENC-IMP-1",
        primary_dx_code="J18.1",
        encounter_type="inpatient",
    )
    assert mr["status"] == "active"


def test_inpatient_episodic_medication_still_completes() -> None:
    """Regression: pre-C7a behavior for episodic IMP med must not change."""
    order = _order(
        drug="Ceftriaxone",
        encounter_id="ENC-IMP-1",
        clinical_intent="Antibiotic (STAT): Ceftriaxone",
        order_id="ORD-ENC-IMP-1-ABX-01",
    )
    mr = _build_medication_request(
        order,
        patient_id="PT-1",
        country="us",
        encounter_id="ENC-IMP-1",
        primary_dx_code="J18.1",
        encounter_type="inpatient",
    )
    assert mr["status"] == "completed"
