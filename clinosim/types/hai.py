"""Hospital-acquired infection events (AD-55 Module: hai)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HAIEvent:
    """One HAI onset detected during an ICU encounter.

    Stored as list[HAIEvent] under CIFPatientRecord.extensions["hai"].
    Onset sampled probabilistically from CDC NHSN per-line-day risk
    rates against PR-A device line-days. A corresponding
    MicrobiologyResult is appended to record.microbiology to satisfy
    the CDC culture-confirmation criterion (emitted by the existing
    _fhir_microbiology.py builder).
    """

    hai_id: str
    encounter_id: str
    hai_type: str
    source_device_id: str
    icd10_code: str
    snomed_code: str
    onset_date: str
    organism_snomed: str
    culture_specimen_id: str
