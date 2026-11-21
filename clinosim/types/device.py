"""Device use records (AD-55 Module: device)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeviceRecord:
    """One device placement during a patient encounter.

    Stored as list[DeviceRecord] under CIFPatientRecord.extensions["device"].
    ``placement_date`` is the date of the placing event (insertion procedure,
    catheter order, else the ICU transfer day) and ``removal_date`` the day its
    indication ended or the discharge date (Issue #3516).
    Phase 2 hai enricher consumes this to compute line-days for
    CLABSI/CAUTI/VAP onset sampling.
    """

    device_id: str
    encounter_id: str
    device_type: str
    snomed_code: str
    placement_date: str
    removal_date: str | None
    placement_indication: str
    # ``icu_stay`` for a device of an ICU stay (devices.yaml criteria),
    # ``insertion`` for a catheter placed by an insertion procedure or a
    # catheter order of a stay with no ICU device of that type (Issue #3516). Only
    # ``icu_stay`` devices carry the NHSN device-associated infection risk.
    origin: str = "icu_stay"
    # The indication (reference_data/device_removal.yaml) whose end set
    # ``removal_date``; ``""`` when the device stays until discharge.
    removal_indication: str = ""
