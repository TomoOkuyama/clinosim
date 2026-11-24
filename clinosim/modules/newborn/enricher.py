"""POST_ENCOUNTER enricher for newborn birth-admission workup (#1252).

Runs after every simulated encounter, gates on the newborn-birth record
(perinatal.py stamps ``condition_event.condition_type = "newborn_birth"``
on the baby-side CIF record) and appends the clinical events this
module owns: Vitamin K prophylaxis (JP oral, US IM) and US erythromycin
ophthalmic prophylaxis as MAR entries, shift vitals, Apgar scores, the
hearing and metabolic screen Procedures (once per newborn), and the
bilirubin / CCHD SpO2 / metabolic-screen workflow data under
``extensions["newborn"]``.

Enricher order (see `clinosim/simulator/enrichers.py`): 92 — placed
before `document` (95) so any downstream document narrative that
references Vitamin K administration has the MAR entry in hand.
"""

from __future__ import annotations

import logging
from typing import Any

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import set_attr_or_key as _set
from clinosim.modules.newborn.engine import (
    build_apgar_scores,
    build_bilirubin_observations,
    build_cchd_pulse_ox,
    build_hearing_screen_procedure,
    build_metabolic_screen_procedure,
    build_metabolic_screen_workflow_data,
    build_newborn_shift_vitals,
    build_ophthalmic_prophylaxis,
    build_vitamin_k_administrations,
    has_perinatal_baseline_emitted,
    is_newborn_birth_record,
    load_newborn_config,
    mark_perinatal_baseline_emitted,
)

logger = logging.getLogger(__name__)


def _set_giving_nurse(mars: list[Any], record: Any, roster: Any) -> None:
    """Name the giving nurse on each birth-admission dose: a nurse of the
    birth encounter's ward, picked stably by the order (no RNG), as for every
    order placed outside the daily loop (medication-lifecycle spec; Issue #2824)."""
    from clinosim.modules.order.placed_order_mar import stable_nurse

    encounters = _get(record, "encounters", []) or []
    enc = encounters[0] if encounters else None
    ward = str(_get(enc, "ward_id", "") or "") if enc is not None else ""
    department = str(_get(enc, "department_id", "") or "") if enc is not None else ""
    for m in mars:
        m.administered_by = stable_nurse(roster, str(m.order_id), ward=ward, department=department)


def _derive_jaundice(record: Any, bilirubin: list[dict[str, Any]]) -> None:
    """P59.9 neonatal jaundice from the measured bilirubin (Issue #3669): a
    baby whose peak reading is at or above
    ``newborn_screening.yaml bilirubin.documentation_threshold_mg_dl`` carries
    P59.9 in ``perinatal_history`` and as a working diagnosis of the birth
    encounter. Idempotent."""
    from clinosim.types.patient import ChronicCondition

    if not bilirubin:
        return
    threshold = float((load_newborn_config().get("bilirubin") or {})["documentation_threshold_mg_dl"])
    if max(float(b["value_mg_dl"]) for b in bilirubin) < threshold:
        return
    patient = _get(record, "patient", None)
    encounters = _get(record, "encounters", []) or []
    diagnosis = _get(record, "clinical_diagnosis", None)
    admitted = _get(encounters[0], "admission_datetime", None) if encounters else None
    if patient is None or diagnosis is None or admitted is None:
        return
    if not any(c.code == "P59.9" for c in patient.perinatal_history):
        patient.perinatal_history.append(ChronicCondition(code="P59.9", onset_date=admitted.date()))
    if not any(d.get("disease_id") == "P59.9" for d in diagnosis.working_diagnoses):
        diagnosis.working_diagnoses.append(
            {"disease_id": "P59.9", "onset_day": 0, "onset_datetime": admitted.isoformat()}
        )


def enrich_newborn(ctx: Any) -> None:
    """POST_ENCOUNTER entrypoint. Iterates `ctx.records`, no-ops on
    non-newborn records, and appends the newborn workup listed in the
    module docstring to newborn records. Schedules come from
    `newborn_screening.yaml`; sampled values (Apgar, screen outcomes,
    bilirubin, SpO2) use per-newborn sha256-keyed sub-RNGs, so the
    master RNG is not consumed.
    """
    records = _get(ctx, "records", None) or []
    country = str(_get(_get(ctx, "config", None), "country", "US") or "US")
    for record in records:
        if not is_newborn_birth_record(record):
            continue
        try:
            new_mars = build_vitamin_k_administrations(record=record, country=country)
            new_vitals = build_newborn_shift_vitals(record=record)
            new_apgar = build_apgar_scores(record=record)
            new_hearing = build_hearing_screen_procedure(record=record)
            new_metabolic = build_metabolic_screen_procedure(record=record, country=country)
            new_metabolic_workflow = build_metabolic_screen_workflow_data(record=record, country=country)
            new_bili = build_bilirubin_observations(record=record)
            new_cchd = build_cchd_pulse_ox(record=record)
            new_oph = build_ophthalmic_prophylaxis(record=record, country=country)
        except Exception:  # pragma: no cover — defensive
            logger.exception("newborn enricher failed on record; continuing")
            continue
        _set_giving_nurse([*new_mars, *new_oph], record, _get(ctx, "roster", None))
        # Issue #1736 — once-per-newborn dedup for the hearing (SNOMED
        # 413083006) + metabolic (SNOMED 428447008) screens. A mother
        # with ≥ 2 deliveries produces two newborn-side CIF records that
        # share ``patient_id = f"{mother_id}-BABY"`` and both carry
        # ``condition_type = "newborn_birth"``; absent dedup, both
        # records emit the baseline screens under the shared ``-BABY``
        # subject, so a FHIR consumer sees the once-per-newborn screens
        # fire twice for the same ``Patient`` resource. The ``build_*``
        # helpers above stay pure (they always compute the Procedure so
        # the determinism / shape unit tests keep working); we only
        # suppress the APPEND here when the tracker already records this
        # ``(patient_id, snomed)`` pair. Mirrors Phase 4d
        # ``baseline_only`` dedup in simulator/outpatient.py (CPAP /
        # polysomnography).
        _pid = str(_get(_get(record, "patient", None), "patient_id", "") or "")
        if new_hearing is not None and _pid:
            if has_perinatal_baseline_emitted(_pid, "413083006"):
                new_hearing = None
            else:
                mark_perinatal_baseline_emitted(_pid, "413083006")
        if new_metabolic is not None and _pid:
            if has_perinatal_baseline_emitted(_pid, "428447008"):
                # Keep the metabolic Procedure AND its sibling
                # ServiceRequest / Specimen / DiagnosticReport workflow
                # stash in lock-step — dropping the Procedure without
                # dropping the workflow would ship SR / Specimen / DR
                # without an accompanying Procedure, which is exactly
                # the kind of split-emit split-brain the by-design
                # registry forbids.
                new_metabolic = None
                new_metabolic_workflow = None
            else:
                mark_perinatal_baseline_emitted(_pid, "428447008")
        _derive_jaundice(record, new_bili)
        if new_bili or new_cchd or new_metabolic_workflow:
            ext = _get(record, "extensions", None)
            if ext is None:
                ext = {}
                _set(record, "extensions", ext)
            nb = ext.setdefault("newborn", {})
            if new_bili:
                nb["bilirubin"] = list(new_bili)
            if new_cchd:
                nb["cchd_pulse_ox"] = list(new_cchd)
            if new_metabolic_workflow:
                # #1252 N6b: stash the ServiceRequest / Specimen /
                # DiagnosticReport payload for the metabolic screen
                # workflow. The three bundle-builders in
                # `clinosim.modules.newborn.fhir_emit` read this to emit
                # the diagnostic-workflow evidence sibling to the
                # existing `Procedure` (which records the physical
                # heel-stick event).
                nb["metabolic_screen"] = dict(new_metabolic_workflow)
        if new_oph:
            existing_mars = _get(record, "medication_administrations", None)
            if existing_mars is None:
                _set(record, "medication_administrations", list(new_oph))
            else:
                existing_mars.extend(new_oph)
        # Issue #2608: the vitamin K and eye prophylaxis are given on an
        # order, so every newborn MAR resolves to a MedicationRequest.
        _add_orders_for_administrations(record, [*(new_mars or []), *(new_oph or [])])
        new_procs = [p for p in (new_hearing, new_metabolic) if p is not None]
        if new_procs:
            existing_procs = _get(record, "procedures", None)
            if existing_procs is None:
                _set(record, "procedures", list(new_procs))
            else:
                existing_procs.extend(new_procs)
        if new_apgar:
            # Store under `extensions["newborn"]["apgar"]`. The FHIR
            # emit path (`_bb_newborn_apgar` in the fhir_r4 adapter)
            # walks this and renders LOINC 9272-6 / 9274-2 Observations.
            ext = _get(record, "extensions", None)
            if ext is None:
                _set(record, "extensions", {"newborn": {"apgar": list(new_apgar)}})
            else:
                nb = ext.setdefault("newborn", {})
                nb["apgar"] = list(new_apgar)
        if new_mars:
            existing_mars = _get(record, "medication_administrations", None)
            if existing_mars is None:
                _set(record, "medication_administrations", list(new_mars))
            else:
                existing_mars.extend(new_mars)
        if new_vitals:
            existing_vs = _get(record, "vital_signs", None)
            if existing_vs is None:
                _set(record, "vital_signs", list(new_vitals))
            else:
                existing_vs.extend(new_vitals)


def _add_orders_for_administrations(record: Any, mars: list[Any]) -> None:
    """Add the standing order behind each newborn prophylaxis MAR (Issue #2608).

    One order per ``order_id``, placed at the birth admission by the birth
    encounter's attending, with the MAR's dose (structured, or the instruction text when it
    has no numeric amount) and route. No RNG.
    """
    from clinosim.modules.order.engine import parse_dose_string
    from clinosim.types.encounter import Order, OrderStatus, OrderType

    encs = _get(record, "encounters", None) or []
    enc = encs[0] if encs else None
    if enc is None or not mars:
        return
    orders = _get(record, "orders", None)
    if orders is None:
        orders = []
        _set(record, "orders", orders)
    have = {str(_get(o, "order_id", "") or "") for o in orders}
    for mar in mars:
        oid = str(_get(mar, "order_id", "") or "")
        if not oid or oid in have:
            continue
        have.add(oid)
        admitted = _get(enc, "admission_datetime", None)
        given = _get(mar, "actual_datetime", None) or _get(mar, "scheduled_datetime", None)
        # Issue #3595: the protocol dose goes through the order dose parser; a
        # dose with no numeric amount ("1 cm ribbon each eye") is kept as the
        # order's dose instruction text.
        dose_str = str(_get(mar, "dose", "") or "")
        parsed = parse_dose_string(dose_str)
        qty = parsed.get("dose_quantity")
        orders.append(
            Order(
                order_id=oid,
                encounter_id=str(_get(enc, "encounter_id", "") or ""),
                patient_id=str(_get(_get(record, "patient", None), "patient_id", "") or ""),
                order_type=OrderType.MEDICATION,
                display_name=str(_get(mar, "drug_name", "") or ""),
                urgency="routine",
                ordered_datetime=admitted or given,
                ordered_by=str(_get(enc, "attending_physician_id", "") or ""),
                status=OrderStatus.PLACED,
                frequency="once",
                frequency_per_day=1,
                route=str(_get(mar, "route", "") or ""),
                dose_quantity=qty,
                dose_unit=str(parsed.get("dose_unit") or "") if qty is not None else "",
                dose_text_en=dose_str if qty is None else "",
                end_datetime=given,
            )
        )
