"""The home medications in effect on a given day (Issue #3199).

The simulation changes a patient's home medications at encounters (a
discharge prescription, a statin titration or add-on at a monitoring
visit) and at year boundaries (the longitudinal engine), and a record's
patient carries only the list the simulation ends with. The forward loop
therefore notes, after each encounter, the medications the patient takes
from its end on (:func:`note_encounter_medications`), on the visit ledger the
per-year profiles of one person share; the profile first activated notes
the medications it started with (``medications_at_activation``). A reader
that needs the list as of an earlier day — the health-checkup enricher —
calls :func:`medications_on`. No random draws.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o


def _encounter_end(encounter: Any) -> datetime | None:
    end = _o(encounter, "discharge_datetime", None) or _o(encounter, "admission_datetime", None)
    return end if isinstance(end, datetime) else None


def note_encounter_medications(record: Any) -> None:
    """Note on the patient's ledger the medications they take from the end
    of ``record``'s last encounter on."""
    patient = _o(record, "patient", None)
    ledger = _o(patient, "visit_ledger", None)
    ends = [e for e in (_encounter_end(enc) for enc in _o(record, "encounters", None) or []) if e is not None]
    if ledger is None or not ends:
        return
    ledger.medication_timeline.append((max(ends), tuple(_o(patient, "current_medications", None) or [])))


def medications_on(patient: Any, when: datetime) -> list[Any]:
    """The home medications ``patient`` takes at ``when``: those noted after
    the last encounter that ended by then, else those the patient started
    the simulation with; the current list when nothing was noted (a record
    built outside the forward loop)."""
    ledger = _o(patient, "visit_ledger", None)
    timeline = list(getattr(ledger, "medication_timeline", None) or [])
    current = list(_o(patient, "current_medications", None) or [])
    if not timeline:
        return current
    noted = [meds for end, meds in sorted(timeline, key=lambda e: e[0]) if end <= when]
    if noted:
        return list(noted[-1])
    at_activation = getattr(ledger, "medications_at_activation", None)
    return list(at_activation) if at_activation is not None else current
