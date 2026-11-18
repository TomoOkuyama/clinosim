"""Make a patient's chronic-condition onsets agree with their encounters (Issue #3263).

A condition is dated when the patient's profile is built (population time, a
yearly aging pass, or the workup of an admission), so a visit made before the
condition first reached the problem list can lie after the condition's onset.
Once the records are complete, the onset of such a condition moves to the day
after the last earlier encounter that did not list it (the condition was first
documented later), capped at the first encounter that lists it. A condition
that no earlier encounter contradicts keeps its onset. Deterministic; draws
nothing.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any


def _encounter_date(record: Any) -> date | None:
    encounters = getattr(record, "encounters", None) or []
    when = getattr(encounters[0], "admission_datetime", None) if encounters else None
    return when.date() if when is not None else None


def reconcile_chronic_onsets(records: Iterable[Any]) -> int:
    """Move contradicted chronic onsets in ``records`` in place; return how many moved."""
    by_patient: dict[str, list[tuple[date, Any]]] = defaultdict(list)
    for record in records:
        when = _encounter_date(record)
        if when is not None:
            by_patient[record.patient.patient_id].append((when, record))
    moved = 0
    for visits in by_patient.values():
        visits.sort(key=lambda v: v[0])
        listed: list[set[str]] = [
            {c.code.split(".")[0] for c in (rec.patient.chronic_conditions or [])} for _, rec in visits
        ]
        first_listed: dict[str, int] = {}
        for i, codes in enumerate(listed):
            for base in codes:
                first_listed.setdefault(base, i)
        # Per base code: the onset after the last visit, before the first
        # listing visit, that did not list it.
        floor: dict[str, date] = {}
        for base, first in first_listed.items():
            for j in range(first - 1, -1, -1):
                if base not in listed[j]:
                    floor[base] = min(visits[j][0] + timedelta(days=1), visits[first][0])
                    break
        for _, rec in visits:
            for cond in rec.patient.chronic_conditions or []:
                bound = floor.get(cond.code.split(".")[0])
                if bound is not None and cond.onset_date is not None and cond.onset_date < bound:
                    cond.onset_date = bound
                    moved += 1
    return moved
