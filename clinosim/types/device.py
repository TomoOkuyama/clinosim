"""Device use records (AD-55 Module: device)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeviceRecord:
    """One device placement during a patient encounter.

    Stored as list[DeviceRecord] under CIFPatientRecord.extensions["device"].
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
