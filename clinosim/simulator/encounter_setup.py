"""Shared steps for building and finishing a simulated encounter.

Every encounter kind (ED, outpatient, perinatal, unknown condition,
inpatient) ends the same way: the encounter's orders are tied to it, its
admit source / discharge disposition / priority are set, the attending
physician of an ED visit or a stay also admits and discharges, and a ``ClinicalDiagnosis`` is
written in the country's diagnosis code system. Procedures performed in
the encounter lie inside its period: a clinic visit lasts until its last
procedure ends, while a stay with a fixed end holds its procedures within it.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from clinosim.codes import system_key_for
from clinosim.types.clinical import ClinicalDiagnosis
from clinosim.types.encounter import Encounter, EncounterType, Order
from clinosim.types.procedure import ProcedureRecord

# Visits that admit and discharge nobody (Issue #3691).
_AMBULATORY_TYPES = frozenset({EncounterType.OUTPATIENT, EncounterType.PRENATAL_VISIT})


def attach_orders(orders: Iterable[Order], encounter: Encounter) -> None:
    """Give every order that has no encounter yet this encounter's id."""
    for o in orders:
        if not o.encounter_id:
            o.encounter_id = encounter.encounter_id


def finalize_encounter(encounter: Encounter, *, admit_source: str, disposition: str, priority: str) -> None:
    """Set the route fields; for an ED visit or a stay the attending physician
    also admits and discharges. An ambulatory visit (clinic, check-up,
    vaccination, prenatal visit) admits and discharges nobody (Issue #3691)."""
    encounter.admit_source = admit_source
    encounter.discharge_disposition = disposition
    encounter.priority = priority
    if encounter.encounter_type not in _AMBULATORY_TYPES:
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


def extend_visit_to_procedures(encounter: Encounter, procedures: Iterable[ProcedureRecord]) -> None:
    """A visit lasts at least until the last of its procedures ends."""
    if encounter.discharge_datetime is None:
        return
    for p in procedures:
        if p.encounter_id == encounter.encounter_id and p.end_datetime > encounter.discharge_datetime:
            encounter.discharge_datetime = p.end_datetime


def fit_procedures_in_stay(procedures: Iterable[ProcedureRecord], start: datetime, end: datetime | None) -> None:
    """Hold each procedure inside the stay ``[start, end]`` (``end`` None: still in progress).

    A procedure that starts before ``start`` moves to ``start``; one that ends
    after ``end`` moves earlier to finish at ``end``, never before ``start``,
    and is shortened only when the stay is shorter than the procedure.
    """
    for p in procedures:
        length = p.end_datetime - p.start_datetime
        if p.start_datetime < start:
            p.start_datetime, p.end_datetime = start, start + length
        if end is not None and p.end_datetime > end:
            p.start_datetime, p.end_datetime = max(start, end - length), end
            p.duration_minutes = int((p.end_datetime - p.start_datetime).total_seconds() // 60)


_ECHO_PROCEDURE = "echocardiography"
_HEART_SNOMED = "80891009"  # body_sites.yaml: heart structure


def _is_echo_order(order: Order) -> bool:
    """A transthoracic echocardiogram imaging order (modality and site of the
    order, or inferred from its name)."""
    from clinosim.modules.imaging.inference import infer_imaging_metadata
    from clinosim.types.encounter import OrderType

    if order.order_type != OrderType.IMAGING:
        return False
    meta = infer_imaging_metadata(order.display_name or "")
    modality = order.imaging_modality or (meta or {}).get("modality", "")
    site = order.imaging_body_site_code or (meta or {}).get("body_site_snomed", "")
    name = (order.display_name or "").lower()
    return (modality, site) == ("US", _HEART_SNOMED) and "transesophageal" not in name


def align_echo_procedures_to_imaging(procedures: Iterable[ProcedureRecord], orders: Iterable[Order]) -> None:
    """Give an echocardiography procedure the time of the echo imaging study
    it is the act of (Issue #3451): the i-th echo procedure of an encounter
    starts when that encounter's i-th echo imaging order does, keeping its
    duration. A procedure without an imaging order keeps its own time."""
    by_enc: dict[str, list[datetime]] = {}
    for o in sorted(orders, key=lambda x: x.ordered_datetime):
        if _is_echo_order(o):
            by_enc.setdefault(o.encounter_id, []).append(o.ordered_datetime)
    taken: dict[str, int] = {}
    for p in sorted((p for p in procedures if p.procedure_type == _ECHO_PROCEDURE), key=lambda x: x.start_datetime):
        times = by_enc.get(p.encounter_id, [])
        i = taken.get(p.encounter_id, 0)
        if i >= len(times):
            continue
        taken[p.encounter_id] = i + 1
        length = p.end_datetime - p.start_datetime
        p.start_datetime, p.end_datetime = times[i], times[i] + length
