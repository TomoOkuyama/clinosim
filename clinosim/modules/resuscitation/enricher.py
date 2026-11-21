"""POST_RECORDS enricher: the resuscitation attempt of a full-code in-hospital
death (Issue #3483).

Runs after ``code_status`` (order 50), whose tier it reads. A deceased
inpatient / emergency record whose code status is the full-code tier gets a
CPR procedure ending at the discharge (death) time and the epinephrine
doses given during it; a not-for-resuscitation or unknown code status gets
nothing. The duration comes from a per-stay sub-RNG (``resuscitation_seed``);
no other random number is drawn.
"""

from __future__ import annotations

from typing import Any

from clinosim.modules.resuscitation.engine import (
    attempt_minutes,
    attempt_status_code,
    build_cpr_procedure,
    build_epinephrine,
    load_rules,
)


def _enum_value(x: Any) -> str:
    return str(getattr(x, "value", x) or "").lower()


def enrich_resuscitation(ctx: Any) -> None:
    from clinosim.modules.order.placed_order_mar import stable_nurse

    rules = load_rules()
    country = str(getattr(getattr(ctx, "config", None), "country", "") or "US")
    for rec in getattr(ctx, "records", None) or []:
        if not getattr(rec, "deceased", False) or getattr(rec, "code_status", "") != attempt_status_code():
            continue
        enc = (getattr(rec, "encounters", None) or [None])[0]
        if enc is None or _enum_value(getattr(enc, "encounter_type", "")) not in rules.encounter_types:
            continue
        death, admission = getattr(enc, "discharge_datetime", None), getattr(enc, "admission_datetime", None)
        pid = str(getattr(rec.patient, "patient_id", "") or "")
        eid = str(getattr(enc, "encounter_id", "") or "")
        if death is None or admission is None or not pid or not eid:
            continue
        if any(p.procedure_type == rules.procedure.type and p.encounter_id == eid for p in rec.procedures):
            continue
        attending = str(getattr(enc, "attending_physician_id", "") or "")
        minutes = attempt_minutes(pid, eid, admission, death)
        cpr = build_cpr_procedure(pid, eid, death, minutes, country, attending)
        rec.procedures.append(cpr)
        if int(getattr(rec.patient, "age", 0) or 0) < rules.epinephrine.min_age:
            continue
        nurse = stable_nurse(
            getattr(ctx, "roster", None),
            eid,
            ward=str(getattr(enc, "ward_id", "") or ""),
            department=str(getattr(enc, "department_id", "") or ""),
        )
        order, mars = build_epinephrine(pid, eid, cpr.start_datetime, death, orderer_id=attending, nurse_id=nurse)
        rec.orders.append(order)
        rec.medication_administrations.extend(mars)
