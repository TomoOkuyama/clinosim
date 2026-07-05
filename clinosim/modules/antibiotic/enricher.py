"""Antibiotic enricher (PR3b-1, POST_ENCOUNTER stage, order=85).

Always-on (AD-55 near-essential clinical cascade Module). Consumes
extensions["hai"] from PR-B. For each HAIEvent whose onset is on/before
the snapshot date (AD-32 future-onset skip), materializes the IDSA
empirical regimen as:
  - 1 Order(MEDICATION) per drug, appended to record.orders, so the
    existing _fhir_medications.py builder emits MedicationRequest.
  - N MedicationAdministration per regimen, appended to
    record.medication_administrations, so the same builder emits MAR.
  - 1 AntibioticRegimen per drug, appended to
    record.extensions["antibiotic"], for PR3b-2/3/4 consumption.

AD-32 future-onset skip rationale: inpatient.py:464-490 runs AD-32
HAI/microbiology truncation AFTER POST_ENCOUNTER stage completes. If
this enricher emits Order+MAR for a future-onset HAI event, the
truncation drops the HAI event but leaves the orphan Order — a CIF
data quality defect. The enricher pre-skips future-onset events.
"""
from __future__ import annotations

from datetime import datetime

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import get_or_create_container, set_attr_or_key as _set
from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS
from clinosim.modules.antibiotic.engine import (
    ABX_NARROW_SUFFIX,
    ABX_ORDER_ID_PREFIX,
    ABX_ORDER_REQ_PREFIX,
    ABX_REGIMEN_ID_PREFIX,
    NarrowOutcome,
    _drug_slug,
    build_regimens,
    generate_mar_doses,
    load_narrow_ladder,
    narrow_duration_days,
    narrow_outcome,
    select_narrow_target,
)
from clinosim.types.antibiotic import AntibioticRegimen
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.hai import HAIEvent


_ORDER_HOUR = 8  # empirical = "AM round" same day as onset


_DEFAULT_SNAPSHOT_FALLBACK = "2099-12-31"


def _resolve_snapshot(cfg) -> datetime:
    """Return the simulation snapshot datetime (AD-32).

    PR-93 adversarial review fix: guard against empty / malformed
    ``time_range``. Previously ``time_range=()`` would raise IndexError
    on ``[-1]``; now falls back to the hardcoded 2099-12-31 sentinel
    (matching the no-time_range default behaviour).
    """
    snap = _get(cfg, "snapshot_date", None)
    if snap:
        return datetime.fromisoformat(snap)
    time_range = _get(cfg, "time_range", None) or ()
    if isinstance(time_range, (list, tuple)) and time_range:
        end = time_range[-1]
    else:
        end = _DEFAULT_SNAPSHOT_FALLBACK
    try:
        return datetime.fromisoformat(end)
    except (TypeError, ValueError):
        return datetime.fromisoformat(_DEFAULT_SNAPSHOT_FALLBACK)


def enrich_antibiotic(ctx) -> None:
    """POST_ENCOUNTER stage entry point — see module docstring."""
    snapshot = _resolve_snapshot(ctx.config)
    snapshot_date = snapshot.date()
    for rec in ctx.records:
        ext = _get(rec, "extensions", {}) or {}
        hai_events: list[HAIEvent] = list(ext.get("hai", []) or [])
        if not hai_events:
            continue
        regimens_out = []
        for ev in hai_events:
            try:
                onset_date = datetime.fromisoformat(ev.onset_date).date()
            except (TypeError, ValueError):
                continue
            if onset_date > snapshot_date:
                # AD-32 defensive skip: future-onset HAI gets truncated
                # by inpatient.py:464-490 AFTER POST_ENCOUNTER. Pre-skip
                # here to prevent orphan Order/MAR.
                continue
            start_dt = datetime.fromisoformat(ev.onset_date).replace(hour=_ORDER_HOUR)
            for regimen in build_regimens(ev, start_datetime=start_dt):
                order_id = f"{ABX_ORDER_REQ_PREFIX}{regimen.regimen_id}"
                order = Order(
                    order_id=order_id,
                    encounter_id=regimen.encounter_id,
                    patient_id=_get(_get(rec, "patient", None), "patient_id", ""),
                    order_type=OrderType.MEDICATION,
                    display_name=ANTIBIOTIC_DRUGS.get(regimen.drug_key, {}).get(
                        "name", regimen.drug_key
                    ),
                    ordered_datetime=regimen.start_datetime,
                    status=OrderStatus.ACCEPTED,
                    dose_unit=regimen.dose,
                    frequency=regimen.frequency,
                    route=regimen.route,
                    duration_days=regimen.duration_days,
                    reason_condition=regimen.hai_event_id,
                )
                get_or_create_container(rec, "orders", list).append(order)
                mars = generate_mar_doses(regimen, snapshot_datetime=snapshot,
                                          order_id=order_id)
                get_or_create_container(rec, "medication_administrations", list).extend(mars)
                regimens_out.append(regimen)
        if regimens_out:
            ext = get_or_create_container(rec, "extensions", dict)
            get_or_create_container(ext, "antibiotic", list).extend(regimens_out)
        # PR3b-3 Pass 2: narrow / de-escalation
        _apply_pass2(rec, snapshot)


# ---------------------------------------------------------------------------
# PR3b-3 Pass 2 helpers
# ---------------------------------------------------------------------------


def _truncate_mar(record, regimen: AntibioticRegimen) -> None:
    """Drop MAR entries for this regimen scheduled after discontinuation_datetime.
    Identifies regimen's MAR by matching order_id = f'req-{regimen.regimen_id}'."""
    if regimen.discontinuation_datetime is None:
        return
    order_id = f"req-{regimen.regimen_id}"
    mars = _get(record, "medication_administrations", [])
    kept = [m for m in mars if not (
        m.order_id == order_id
        and m.scheduled_datetime > regimen.discontinuation_datetime
    )]
    _set(record, "medication_administrations", kept)


def _mark_order_stopped(record, regimen: AntibioticRegimen) -> None:
    """Set the matching Order.status to OrderStatus.STOPPED."""
    order_id = f"req-{regimen.regimen_id}"
    orders = _get(record, "orders", [])
    for o in orders:
        if o.order_id == order_id:
            o.status = OrderStatus.STOPPED
            return


def _narrow_dose_frequency(drug_key: str) -> tuple[str, str]:
    """Default narrow-target dose + frequency. Simplified per PR3b-1 (no eGFR
    adjustment; future PR). Frequencies match hai_empirical.yaml conventions."""
    table = {
        "vancomycin":                    ("1g",     "q12h"),
        "cefazolin":                     ("1g",     "q8h"),
        "ceftriaxone":                   ("1g",     "q24h"),
        "cefepime":                      ("1g",     "q8h"),
        "piperacillin_tazobactam":       ("3.375g", "q6h"),
        "meropenem":                     ("1g",     "q8h"),
        "ciprofloxacin":                 ("400mg",  "q12h"),
        "trimethoprim_sulfamethoxazole": ("160mg",  "q12h"),
        "ampicillin":                    ("2g",     "q6h"),
        "gentamicin":                    ("80mg",   "q8h"),
    }
    return table.get(drug_key, ("1g", "q12h"))


def _apply_pass2(rec, snapshot: datetime) -> None:
    """PR3b-3 Pass 2: walk extensions['antibiotic'] empirical regimens, look
    up the HAI culture via MicrobiologyResult.hai_event_id, pick narrow target
    via ladder, dispatch one of the three outcomes (spec §2.4)."""
    ladder = load_narrow_ladder()
    ext = _get(rec, "extensions", {}) or {}
    regimens: list[AntibioticRegimen] = list(ext.get("antibiotic", []) or [])
    if not regimens:
        return
    micro_list = _get(rec, "microbiology", []) or []

    # Group empirical regimens by hai_event_id
    by_event: dict[str, list[AntibioticRegimen]] = {}
    for r in regimens:
        if r.intent != "empirical":
            continue
        by_event.setdefault(r.hai_event_id, []).append(r)

    hai_events = ext.get("hai", []) or []
    hai_by_id = {ev.hai_id: ev for ev in hai_events}

    new_regimens: list[AntibioticRegimen] = []
    for hai_id, empirical_regimens in by_event.items():
        ev = hai_by_id.get(hai_id)
        if ev is None:
            continue  # defensive: hai event vanished (should not happen)
        micro = next(
            (m for m in micro_list if m.hai_event_id == hai_id),
            None,
        )
        if micro is None or micro.reported_datetime is None:
            continue
        if micro.reported_datetime > snapshot:
            continue  # AD-32: report not available by snapshot

        target = select_narrow_target(
            micro.susceptibilities,
            ladder.get(ev.hai_type, {}).get(ev.organism_snomed, []),
        )
        outcome = narrow_outcome(target, empirical_regimens)

        if outcome == NarrowOutcome.NO_CHANGE:
            continue

        reported = micro.reported_datetime
        if outcome == NarrowOutcome.ELIMINATION:
            for r in empirical_regimens:
                if r.drug_key == target:
                    continue  # keep target unchanged
                r.discontinuation_datetime = reported
                _truncate_mar(rec, r)
                _mark_order_stopped(rec, r)

        elif outcome == NarrowOutcome.SWITCH:
            # Discontinue every empirical regimen, then build new narrowed regimen
            for r in empirical_regimens:
                r.discontinuation_datetime = reported
                _truncate_mar(rec, r)
                _mark_order_stopped(rec, r)
            template = empirical_regimens[0]
            narrow_dur = narrow_duration_days(
                template.start_datetime, reported, template.duration_days
            )
            narrow_dose, narrow_freq = _narrow_dose_frequency(target)
            slug = _drug_slug(target)
            new_regimen = AntibioticRegimen(
                regimen_id=f"{ABX_REGIMEN_ID_PREFIX}{hai_id}-{slug}{ABX_NARROW_SUFFIX}",
                hai_event_id=hai_id,
                encounter_id=template.encounter_id,
                drug_key=target,
                dose=narrow_dose,
                route="IV",
                frequency=narrow_freq,
                start_datetime=reported,
                duration_days=narrow_dur,
                intent="narrowed",
            )
            new_regimens.append(new_regimen)
            order_id = f"{ABX_ORDER_REQ_PREFIX}{new_regimen.regimen_id}"
            order = Order(
                order_id=order_id,
                encounter_id=template.encounter_id,
                patient_id=_get(_get(rec, "patient", None), "patient_id", ""),
                order_type=OrderType.MEDICATION,
                display_name=ANTIBIOTIC_DRUGS.get(target, {}).get("name", target),
                ordered_datetime=reported,
                status=OrderStatus.ACCEPTED,
                dose_unit=narrow_dose,
                frequency=narrow_freq,
                route="IV",
                duration_days=narrow_dur,
                reason_condition=hai_id,
            )
            get_or_create_container(rec, "orders", list).append(order)
            mars = generate_mar_doses(new_regimen, snapshot_datetime=snapshot, order_id=order_id)
            get_or_create_container(rec, "medication_administrations", list).extend(mars)

    if new_regimens:
        ext = get_or_create_container(rec, "extensions", dict)
        get_or_create_container(ext, "antibiotic", list).extend(new_regimens)
