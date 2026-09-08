"""MedicationRequest.dispenseRequest.expectedSupplyDuration — Issue #1175 partial.

The JP-CLINS eCS pins `MedicationRequest.status = "completed"` via
`patternCode`, which is spec-required and cannot be dropped. That
pin makes every JP MR appear "completed" to naive consumers filtering
`status=active`. The Extension + note at
`post_process/populate.py:_populate_condition_ai_mr_ecs_fields` already
preserves intent for extension-aware consumers.

This partial fix adds a standard-FHIR discoverability channel:
`dispenseRequest.expectedSupplyDuration` for home-med + outpatient
Rx. A consumer computing `authoredOn + supplyDuration *
(1 + numberOfRepeatsAllowed)` can treat the Rx as active while
inside that window, without knowing the clinosim-namespaced
extension.

Concretely: for chronic home-med orders, emits 30 d + 3 refills = ~120
day "active window" — matching the standard JP chronic-Rx cycle.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_request


def _mk_order(**overrides):
    base = {
        "order_id": "ord-1",
        "order_type": "medication",
        "display_name": "Amlodipine 5mg",
        "clinical_intent": "home medication (continue)",
        "ordered_datetime": "2026-01-15T10:00:00",
    }
    base.update(overrides)
    return base


def test_home_medication_gets_default_supply_duration() -> None:
    resource = _build_medication_request(
        _mk_order(),
        patient_id="pt-x",
        country="JP",
        encounter_id="enc-1",
        primary_dx_code="I10",
        encounter_type="outpatient",
        rp_number="1",
        order_in_rp="1",
    )
    disp = resource.get("dispenseRequest") or {}
    supply = disp.get("expectedSupplyDuration") or {}
    assert supply.get("value") == 30
    assert supply.get("unit") == "日"
    assert supply.get("code") == "d"


def test_outpatient_order_without_home_hint_still_gets_default() -> None:
    resource = _build_medication_request(
        _mk_order(clinical_intent="outpatient follow-up"),
        patient_id="pt-x",
        country="JP",
        encounter_id="enc-2",
        primary_dx_code="E11",
        encounter_type="outpatient",
        rp_number="1",
        order_in_rp="1",
    )
    disp = resource.get("dispenseRequest") or {}
    supply = disp.get("expectedSupplyDuration") or {}
    assert supply.get("value") == 30


def test_us_locale_uses_ucum_unit_token() -> None:
    resource = _build_medication_request(
        _mk_order(),
        patient_id="pt-x",
        country="US",
        encounter_id="enc-3",
        primary_dx_code="I10",
        encounter_type="outpatient",
        rp_number="1",
        order_in_rp="1",
    )
    disp = resource.get("dispenseRequest") or {}
    supply = disp.get("expectedSupplyDuration") or {}
    # US locale: `unit` = UCUM Latin token `d`, not Japanese `日`.
    assert supply.get("unit") == "d"
    assert supply.get("code") == "d"


def test_days_supply_from_order_preserved_when_present() -> None:
    resource = _build_medication_request(
        _mk_order(days_supply=90),
        patient_id="pt-x",
        country="JP",
        encounter_id="enc-4",
        primary_dx_code="I10",
        encounter_type="outpatient",
        rp_number="1",
        order_in_rp="1",
    )
    disp = resource.get("dispenseRequest") or {}
    supply = disp.get("expectedSupplyDuration") or {}
    assert supply.get("value") == 90


def test_inpatient_order_not_defaulted() -> None:
    # Inpatient orders end at discharge — no chronic-Rx default should
    # attach a 30-day supply window.
    resource = _build_medication_request(
        _mk_order(clinical_intent="inpatient acute"),
        patient_id="pt-x",
        country="JP",
        encounter_id="enc-5",
        primary_dx_code="I50",
        encounter_type="inpatient",
        rp_number="1",
        order_in_rp="1",
    )
    disp = resource.get("dispenseRequest") or {}
    supply = disp.get("expectedSupplyDuration")
    # No default; the field is absent unless days_supply is explicit.
    assert supply is None
