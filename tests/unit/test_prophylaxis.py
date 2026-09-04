"""B6 (#1071): DVT prophylaxis enricher unit tests.

Covers the skip dispatch (therapeutic AC / active bleeding / delivery /
active DVT-PE) and the positive path (normal J18 IMP ≥ 48 h → order).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.prophylaxis.engine import (
    build_dvt_prophylaxis_orders,
    should_skip_dvt_prophylaxis,
)


def _patient(meds: list[str] | None = None) -> SimpleNamespace:
    home_meds = [SimpleNamespace(drug_name=m) for m in (meds or [])]
    return SimpleNamespace(patient_id="PT-1", current_medications=home_meds)


def _encounter(
    los_hours: float,
    encounter_type: str = "inpatient",
    encounter_id: str = "ENC-1",
) -> SimpleNamespace:
    adm = datetime(2026, 1, 1, 9, 0)
    from datetime import timedelta

    dc = adm + timedelta(hours=los_hours)
    return SimpleNamespace(
        encounter_id=encounter_id,
        encounter_type=encounter_type,
        admission_datetime=adm,
        discharge_datetime=dc,
        attending_physician_id="DR-1",
    )


def _record(patient, encounter, dx: str = "") -> SimpleNamespace:
    cd = SimpleNamespace(
        discharge_diagnosis_code=dx,
        admission_diagnosis_code=dx,
    )
    return SimpleNamespace(
        patient=patient,
        encounters=[encounter],
        orders=[],
        clinical_diagnosis=cd,
    )


# ---------------------------------------------------------------------------
# should_skip_dvt_prophylaxis dispatch
# ---------------------------------------------------------------------------


def test_no_skip_on_normal_pneumonia_patient() -> None:
    skip, reason = should_skip_dvt_prophylaxis(
        patient=_patient(["Amlodipine 5mg"]),
        encounter=_encounter(72),
        admission_dx_code="J18.1",
    )
    assert skip is False
    assert reason == ""


def test_skip_on_therapeutic_warfarin() -> None:
    skip, reason = should_skip_dvt_prophylaxis(
        patient=_patient(["Warfarin 3mg PO daily"]),
        encounter=_encounter(72),
        admission_dx_code="I48",
    )
    assert skip is True
    assert reason == "therapeutic_anticoagulant_active"


def test_skip_on_apixaban_home_med() -> None:
    skip, reason = should_skip_dvt_prophylaxis(
        patient=_patient(["Apixaban 5mg PO BID"]),
        encounter=_encounter(72),
        admission_dx_code="J18.1",
    )
    assert skip is True
    assert reason == "therapeutic_anticoagulant_active"


def test_skip_on_intracerebral_hemorrhage() -> None:
    skip, reason = should_skip_dvt_prophylaxis(
        patient=_patient([]),
        encounter=_encounter(72),
        admission_dx_code="I61.0",
    )
    assert skip is True
    assert reason == "active_bleeding_or_hemorrhage"


def test_skip_on_gi_bleed() -> None:
    skip, reason = should_skip_dvt_prophylaxis(
        patient=_patient([]),
        encounter=_encounter(72),
        admission_dx_code="K92.1",
    )
    assert skip is True
    assert reason == "active_bleeding_or_hemorrhage"


def test_skip_on_delivery_admission() -> None:
    skip, reason = should_skip_dvt_prophylaxis(
        patient=_patient([]),
        encounter=_encounter(72),
        admission_dx_code="Z37.0",
    )
    assert skip is True
    assert reason == "perinatal_delivery"


def test_skip_on_active_pulmonary_embolism() -> None:
    skip, reason = should_skip_dvt_prophylaxis(
        patient=_patient([]),
        encounter=_encounter(96),
        admission_dx_code="I26.99",
    )
    assert skip is True
    assert reason == "active_dvt_pe_treatment"


def test_skip_on_active_dvt() -> None:
    skip, reason = should_skip_dvt_prophylaxis(
        patient=_patient([]),
        encounter=_encounter(72),
        admission_dx_code="I80.201",
    )
    assert skip is True
    assert reason == "active_dvt_pe_treatment"


# ---------------------------------------------------------------------------
# build_dvt_prophylaxis_orders end-to-end
# ---------------------------------------------------------------------------


def test_positive_path_emits_enoxaparin_order() -> None:
    record = _record(
        _patient(["Amlodipine 5mg"]),
        _encounter(los_hours=72),
        dx="J18.1",
    )
    orders = build_dvt_prophylaxis_orders(record=record)
    assert len(orders) == 1
    o = orders[0]
    assert o.display_name == "Enoxaparin"
    assert o.dose_quantity == 40.0
    assert o.dose_unit == "mg"
    assert o.route == "SC"
    assert o.frequency == "daily"
    assert "DVT prophylaxis" in o.clinical_intent
    assert "DVT予防" in o.clinical_intent_ja
    assert o.encounter_id == "ENC-1"
    assert o.order_id == "ORD-ENC-1-DVT-01"


def test_short_los_no_order() -> None:
    """LOS < 48 h: no order."""
    record = _record(_patient([]), _encounter(los_hours=24), dx="J18.1")
    assert build_dvt_prophylaxis_orders(record=record) == []


def test_outpatient_encounter_no_order() -> None:
    record = _record(
        _patient([]),
        _encounter(los_hours=72, encounter_type="outpatient"),
        dx="J18.1",
    )
    assert build_dvt_prophylaxis_orders(record=record) == []


def test_therapeutic_ac_patient_no_order() -> None:
    record = _record(
        _patient(["Warfarin 3mg PO daily"]),
        _encounter(los_hours=72),
        dx="J18.1",
    )
    assert build_dvt_prophylaxis_orders(record=record) == []


def test_hemorrhagic_stroke_no_order() -> None:
    record = _record(_patient([]), _encounter(los_hours=120), dx="I61.9")
    assert build_dvt_prophylaxis_orders(record=record) == []


def test_delivery_no_order() -> None:
    record = _record(_patient([]), _encounter(los_hours=48), dx="Z37.0")
    assert build_dvt_prophylaxis_orders(record=record) == []


def test_active_dvt_no_order() -> None:
    """DVT admission — therapeutic anticoag replaces prophylaxis by definition."""
    record = _record(_patient([]), _encounter(los_hours=72), dx="I80.201")
    assert build_dvt_prophylaxis_orders(record=record) == []


def test_deterministic_output() -> None:
    """Same input twice → byte-identical output (no RNG consumption)."""
    record1 = _record(_patient(["Amlodipine 5mg"]), _encounter(los_hours=72), dx="J18.1")
    record2 = _record(_patient(["Amlodipine 5mg"]), _encounter(los_hours=72), dx="J18.1")
    o1 = build_dvt_prophylaxis_orders(record=record1)
    o2 = build_dvt_prophylaxis_orders(record=record2)
    assert o1 == o2


def test_dx_case_insensitive() -> None:
    """ICD prefix match handles lower-case input."""
    record = _record(_patient([]), _encounter(los_hours=72), dx="i61.9")
    assert build_dvt_prophylaxis_orders(record=record) == []


# ---------------------------------------------------------------------------
# Issue #1087 (C1): drug_safety pair gate before auto-issuing Enoxaparin
# ---------------------------------------------------------------------------


def _med_order(name: str, order_id: str = "ORD-CHR-1") -> Any:
    """Build a minimal MEDICATION Order suitable for record.orders."""
    from clinosim.types.encounter import Order, OrderStatus, OrderType

    return Order(
        order_id=order_id,
        encounter_id="ENC-1",
        patient_id="PT-1",
        order_type=OrderType.MEDICATION,
        display_name=name,
        ordered_datetime=datetime(2026, 1, 1, 10, 0),
        status=OrderStatus.PLACED,
    )


def test_skip_on_chronic_aspirin_via_drug_safety() -> None:
    """Patient on chronic aspirin — Enoxaparin would create a
    contraindicated anticoagulant+antiplatelet(+nsaid) pair."""
    skip, reason = should_skip_dvt_prophylaxis(
        patient=_patient(["Aspirin 81mg"]),
        encounter=_encounter(72),
        admission_dx_code="J18.1",
    )
    assert skip is True
    assert reason.startswith("drug_safety_pair:")


def test_skip_on_in_encounter_nsaid_via_drug_safety() -> None:
    """In-encounter NSAID (record.orders) — Enoxaparin still blocked."""
    record = _record(_patient([]), _encounter(los_hours=72), dx="J18.1")
    record.orders = [_med_order("Ibuprofen 400mg", "ORD-INE-1")]
    assert build_dvt_prophylaxis_orders(record=record) == []


def test_skip_on_in_encounter_ketorolac_via_drug_safety() -> None:
    """Ketorolac is a very common IV/IM NSAID — must be classified
    so the drug_safety gate catches it."""
    record = _record(_patient([]), _encounter(los_hours=72), dx="J18.1")
    record.orders = [_med_order("Ketorolac", "ORD-INE-2")]
    assert build_dvt_prophylaxis_orders(record=record) == []


def test_no_skip_on_allowed_chronic_med() -> None:
    """Non-conflicting chronic med (statin) — Enoxaparin still emits."""
    record = _record(
        _patient(["Atorvastatin 40mg"]),
        _encounter(los_hours=72),
        dx="J18.1",
    )
    orders = build_dvt_prophylaxis_orders(record=record)
    assert len(orders) == 1
    assert orders[0].display_name == "Enoxaparin"


def test_therapeutic_ac_still_wins_over_drug_safety_gate() -> None:
    """Therapeutic AC skip (existing rule) still fires and is reported."""
    skip, reason = should_skip_dvt_prophylaxis(
        patient=_patient(["Warfarin 3mg PO daily"]),
        encounter=_encounter(72),
        admission_dx_code="I48",
    )
    assert skip is True
    assert reason == "therapeutic_anticoagulant_active"
