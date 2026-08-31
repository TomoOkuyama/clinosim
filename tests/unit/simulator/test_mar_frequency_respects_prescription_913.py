"""Issue #913: MedicationAdministration must honour parent MedicationRequest
``dosageInstruction.timing.repeat.frequency``.

Pre-fix the MAR generator used a hardcoded drug-name dispatch and defaulted
to TID (3/day) for oral drugs regardless of the prescription frequency —
so a 1/day amlodipine order emitted 3 admins/day (audit v0.5.0: 60.3 %
over-admin, 3× on-chart over-dose fingerprint).

Post-fix ``_admin_hours_from_frequency`` maps
``order.frequency_per_day`` (parsed the same way MR emit derives
``timing.repeat.frequency`` — via ``parse_dose_string``) to the MAR admin
slots. Drug-name dispatch remains only as a fallback for orders whose
frequency the enricher could not parse.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from clinosim.simulator.medication_pipeline import (
    _admin_hours_from_frequency,
    _generate_mar,
)
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.patient import PatientProfile


class _StubRoster:
    def __init__(self) -> None:
        self.members: list = []

    def get_by_role(self, role: str, department: str | None = None) -> list:
        return []


def _rng() -> np.random.Generator:
    return np.random.default_rng(42)


def _order(order_id: str, drug: str, freq_per_day: int | None) -> Order:
    o = Order(
        order_id=order_id,
        encounter_id="ENC-913",
        patient_id="POP-913",
        order_type=OrderType.MEDICATION,
        order_code="",
        display_name=drug,
        urgency="routine",
        clinical_intent="",
        ordered_datetime=datetime(2026, 6, 30, 5, 0),
        ordered_by="DR-1",
        status=OrderStatus.PLACED,
        route="PO",
        frequency="",
        frequency_per_day=freq_per_day,
    )
    return o


# === Frequency → hours mapping contract ===


def test_admin_hours_from_frequency_common_bands() -> None:
    assert _admin_hours_from_frequency(1) == [8]
    assert _admin_hours_from_frequency(2) == [8, 20]
    assert _admin_hours_from_frequency(3) == [8, 14, 20]
    assert _admin_hours_from_frequency(4) == [0, 6, 12, 18]
    assert _admin_hours_from_frequency(6) == [0, 4, 8, 12, 16, 20]
    assert _admin_hours_from_frequency(8) == [0, 3, 6, 9, 12, 15, 18, 21]


def test_admin_hours_from_frequency_continuous_capped_to_q4h() -> None:
    """Continuous infusions (freq ≥ 12) are represented as q4h (6/day)
    MAR entries — a data-volume compromise for realism."""
    for freq in [12, 18, 24]:
        assert _admin_hours_from_frequency(freq) == [0, 4, 8, 12, 16, 20]


def test_admin_hours_from_frequency_zero_falls_back_to_tid() -> None:
    assert _admin_hours_from_frequency(0) == [8, 14, 20]


# === End-to-end MAR emit contract ===


def test_issue_913_amlodipine_1_per_day_emits_1_admin() -> None:
    """Audit v0.5.0: amlodipine 1/day emitted 3 admins/day. Post-fix must
    emit exactly 1."""
    admission_time = datetime(2026, 6, 30, 0, 0)
    order = _order("ORD-AML", "アムロジピン 5mg", 1)
    mars = _generate_mar(
        PatientProfile(patient_id="POP-913"),
        [order],
        day=0,
        admission_time=admission_time,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=_rng(),
    )
    assert len(mars) == 1, f"Amlodipine 1/day must emit 1 admin, got {len(mars)}"


def test_issue_913_bid_med_emits_2_admins() -> None:
    admission_time = datetime(2026, 6, 30, 0, 0)
    order = _order("ORD-BID", "Med BID", 2)
    mars = _generate_mar(
        PatientProfile(patient_id="POP-913"),
        [order],
        day=0,
        admission_time=admission_time,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=_rng(),
    )
    assert len(mars) == 2


def test_issue_913_q6h_med_emits_4_admins() -> None:
    admission_time = datetime(2026, 6, 30, 0, 0)
    order = _order("ORD-Q6", "Med Q6H", 4)
    mars = _generate_mar(
        PatientProfile(patient_id="POP-913"),
        [order],
        day=0,
        admission_time=admission_time,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=_rng(),
    )
    assert len(mars) == 4


def test_issue_913_continuous_infusion_emits_capped_admins() -> None:
    """Audit v0.5.0: norepinephrine 24/day emitted ~3/day (severe under-
    admin). Post-fix must emit 6/day (q4h nurse-observation cap)."""
    admission_time = datetime(2026, 6, 30, 0, 0)
    order = _order("ORD-DRIP", "ノルエピネフリン drip", 24)
    mars = _generate_mar(
        PatientProfile(patient_id="POP-913"),
        [order],
        day=0,
        admission_time=admission_time,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=_rng(),
    )
    assert len(mars) == 6, f"continuous infusion capped at q4h (6/day), got {len(mars)}"


def test_issue_913_no_frequency_falls_back_to_drug_name_dispatch() -> None:
    """Orders whose enricher could not parse frequency (e.g. antibiotics
    like "Meropenem 1g" whose display_name doesn't declare a schedule)
    still route through the legacy drug-name dispatch — must remain q8h
    (3/day) for Meropenem."""
    admission_time = datetime(2026, 6, 30, 0, 0)
    order = _order("ORD-MERO", "Meropenem 1g", None)
    order.route = "IV"
    mars = _generate_mar(
        PatientProfile(patient_id="POP-913"),
        [order],
        day=0,
        admission_time=admission_time,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=_rng(),
    )
    # Meropenem is in q8h_drugs list → 3 admins/day
    assert len(mars) == 3
