"""Shared steps for building and finishing a simulated encounter.

Every encounter kind (ED, outpatient, perinatal, unknown condition,
inpatient) ends the same way: the encounter's orders are tied to it, its
admit source / discharge disposition / priority are set, the attending
physician also admits and discharges, and a ``ClinicalDiagnosis`` is
written in the country's diagnosis code system.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from clinosim.codes import system_key_for
from clinosim.types.clinical import ClinicalDiagnosis
from clinosim.types.encounter import Encounter, Order


def attach_orders(orders: Iterable[Order], encounter: Encounter) -> None:
    """Give every order that has no encounter yet this encounter's id."""
    for o in orders:
        if not o.encounter_id:
            o.encounter_id = encounter.encounter_id


def finalize_encounter(encounter: Encounter, *, admit_source: str, disposition: str, priority: str) -> None:
    """Set the route fields and let the attending physician admit and discharge."""
    encounter.admit_source = admit_source
    encounter.discharge_disposition = disposition
    encounter.priority = priority
    encounter.admitting_physician_id = encounter.attending_physician_id
    encounter.discharging_physician_id = encounter.attending_physician_id


def encounter_diagnosis(
    admission_code: str, country: str, *, discharge_code: str | None = None, **fields: Any
) -> ClinicalDiagnosis:
    """A ``ClinicalDiagnosis`` coded in ``country``'s diagnosis system.

    The discharge code defaults to the admission code (a single-diagnosis
    encounter); ``fields`` carries the remaining ``ClinicalDiagnosis`` fields.
    """
    system = system_key_for("diagnosis", country)
    return ClinicalDiagnosis(
        admission_diagnosis_code=admission_code,
        admission_diagnosis_system=system,
        discharge_diagnosis_code=admission_code if discharge_code is None else discharge_code,
        discharge_diagnosis_system=system,
        **fields,
    )
