"""Renewals end the previous prescription (Issue #2610).

Each outpatient follow-up and each discharge writes a take-home prescription
(``record.discharge_prescription``) in its own record, so the FHIR output had
one ``active`` MedicationRequest per visit for the same chronic drug and none
of them ever ended. ``prescription_closures`` walks a patient's prescriptions
in issue order, as of the export's snapshot date, and per drug:

* an earlier prescription renewed by a later one ends on the renewal date
  (``status: completed``), and the renewal records it (``prior_rx``, emitted as
  ``MedicationRequest.priorPrescription``);
* the last prescription ends when its supply (``duration_days``) runs out
  before the end of the run, or ``stopped`` at the patient's death;
* a prescription still in supply at the end of the run stays active.

The result depends on the snapshot date (a prescription active at one
snapshot is completed at a later one), so it is computed at FHIR export time
from the CIF and never written into it: the CIF of a shared window stays
identical across snapshots. Items are numbered as the FHIR emitter numbers
them (blank drug names skipped), so ``prior_rx`` resolves to the emitted
request id. RNG-free.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from clinosim.codes.drugs import drug_ref
from clinosim.modules._shared import get_attr_or_key as _get


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _entries(record: Any) -> list[tuple[date, int, dict, dict]]:
    rx = _get(record, "discharge_prescription", None)
    encs = _get(record, "encounters", None) or []
    if rx is None or not encs:
        return []
    issued = _day(_get(rx, "issue_date", None)) or _day(_get(encs[0], "discharge_datetime", None))
    if issued is None:
        return []
    ref = {
        "encounter_id": str(_get(encs[0], "encounter_id", "") or ""),
        "encounter_type": str(
            getattr(_get(encs[0], "encounter_type", ""), "value", _get(encs[0], "encounter_type", ""))
        ),
    }
    out = []
    seq = 0
    for item in _get(rx, "items", None) or []:
        if not isinstance(item, dict) or not str(item.get("drug_name", "") or "").strip():
            continue
        seq += 1
        out.append((issued, seq, item, {**ref, "seq": seq}))
    return out


Closure = dict[str, Any]


def prescription_closures(records: Iterable[Any], run_end: date | None) -> dict[tuple[str, int], Closure]:
    """``{(encounter_id, seq): {status?, end_date?, prior_rx?}}`` for every
    take-home prescription item that is closed or renews an earlier one."""
    out: dict[tuple[str, int], Closure] = defaultdict(dict)
    by_patient: dict[str, list[tuple[date, int, dict, dict, Any]]] = defaultdict(list)
    for record in records:
        patient = _get(record, "patient", None)
        pid = str(_get(patient, "patient_id", "") or "")
        if not pid:
            continue
        for issued, seq, item, ref in _entries(record):
            by_patient[pid].append((issued, seq, item, ref, patient))
    all_copies: list[dict[tuple[str, str], list[tuple[str, int]]]] = []
    for entries in by_patient.values():
        by_drug: dict[str, list[tuple[date, int, dict, dict, Any]]] = defaultdict(list)
        # One link per drug per prescription: a drug listed twice in one
        # prescription is emitted once (exact-duplicate de-duplication), so
        # the later copy shares the first copy's closure and is never a link.
        copies: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
        for entry in entries:
            name = str(entry[2].get("drug_name", ""))
            drug = drug_ref(name) or name.strip().lower()
            enc_key = (entry[3]["encounter_id"], drug)
            copies[enc_key].append((entry[3]["encounter_id"], entry[1]))
            if len(copies[enc_key]) == 1:
                by_drug[drug].append(entry)
        all_copies.append(copies)
        for chain in by_drug.values():
            chain.sort(key=lambda e: (e[0], e[3]["encounter_id"], e[1]))
            for (issued, seq, item, ref, patient), nxt in zip(chain, [*chain[1:], None]):
                key = (ref["encounter_id"], seq)
                if nxt is not None:
                    out[key].update(status="completed", end_date=nxt[0].isoformat())
                    out[(nxt[3]["encounter_id"], nxt[1])]["prior_rx"] = dict(ref)
                    continue
                out[key].update(_close_by_supply(item, issued, patient, run_end))
    for keys in (k for per_patient in all_copies for k in per_patient.values()):
        first = out.get(keys[0])
        for dup in keys[1:]:
            if first:
                out[dup] = {k: v for k, v in first.items() if k != "prior_rx"}
    return {k: v for k, v in out.items() if v}


def _close_by_supply(item: dict, issued: date, patient: Any, run_end: date | None) -> Closure:
    days = item.get("duration_days")
    dod = _day(_get(patient, "date_of_death", None))
    supply_end = issued + timedelta(days=int(days)) if isinstance(days, int) and days > 0 else None
    if dod is not None and dod >= issued and (supply_end is None or dod < supply_end):
        return {"status": "stopped", "end_date": dod.isoformat()}
    if supply_end is not None and run_end is not None and supply_end <= run_end:
        return {"status": "completed", "end_date": supply_end.isoformat()}
    return {}
