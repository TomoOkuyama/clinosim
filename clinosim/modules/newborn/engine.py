"""Newborn birth-admission clinical workup — pure event emission (#1252).

Reads `reference_data/newborn_screening.yaml` for locale-specific
protocol parameters and emits the clinical events every real neonatal
chart carries during the birth admission: Vitamin K prophylaxis
(this PR's slice), plus Apgar / hearing screen / metabolic screen /
bilirubin / CCHD SpO2 / ophthalmic prophylaxis in follow-up PRs.

Pure engine — no CIF mutation here; the enricher (enricher.py) walks
records and appends the returned events.

Trigger contract: only fires on records whose ``condition_event
.condition_type == "newborn_birth"`` (set by simulator/perinatal.py at
delivery encounter construction). Any other record is a no-op.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import is_jp
from clinosim.types.encounter import MedicationAdministration

_HERE = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def load_newborn_config() -> dict[str, Any]:
    """Load + cache `newborn_screening.yaml`. Cached singleton."""
    with (_HERE / "reference_data" / "newborn_screening.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def is_newborn_birth_record(record: Any) -> bool:
    """True iff this record represents a newborn's own birth admission
    (perinatal.py sets ``condition_event.condition_type = "newborn_birth"``
    on the newborn-side CIF record). Every clinical-event helper below
    treats this as its firing gate.
    """
    ce = _get(record, "condition_event", None)
    if ce is None:
        return False
    return str(_get(ce, "condition_type", "") or "") == "newborn_birth"


def build_vitamin_k_administrations(
    record: Any,
    country: str,
) -> list[MedicationAdministration]:
    """Vitamin K prophylaxis MedicationAdministrations for a newborn's
    birth admission.

    * JP: Konakion oral syrup 2 mg, days 0 and 7 (schedule per MHLW
      新生児 ビタミン K 欠乏性出血症予防). Only doses whose scheduled
      day falls within the birth-admission LOS are emitted here —
      the 1-month post-discharge dose is not part of this PR's scope.
    * US: Vitamin K1 1 mg IM once, within 6 h of birth (AAP guideline).

    Returns an empty list for non-newborn-birth records (defensive; the
    enricher already gates on `is_newborn_birth_record`).
    """
    if not is_newborn_birth_record(record):
        return []
    encounters = _get(record, "encounters", []) or []
    if not encounters:
        return []
    birth_enc = encounters[0]
    admit_dt = _get(birth_enc, "admission_datetime", None)
    if not isinstance(admit_dt, datetime):
        return []
    discharge_dt = _get(birth_enc, "discharge_datetime", None)

    cfg = (load_newborn_config().get("vitamin_k") or {}).get("jp" if is_jp(country) else "us") or {}
    if not cfg:
        return []
    schedule_days = list(cfg.get("schedule_days") or [])
    drug_name = str(cfg.get("drug_name") or "")
    dose = str(cfg.get("dose") or "")
    route = str(cfg.get("route") or "")
    within_hours = int(cfg.get("within_hours_of_birth") or 24)
    if not schedule_days or not drug_name:
        return []

    # Encounter identifier for the MAR order_id — matches the pattern
    # used elsewhere in the codebase (see antibiotic engine).
    enc_id = str(_get(birth_enc, "encounter_id", "") or "")
    order_id = f"ORD-{enc_id}-VITK" if enc_id else "ORD-VITK"

    out: list[MedicationAdministration] = []
    for i, day_offset in enumerate(schedule_days):
        # Dose 1 lands `within_hours_of_birth` after admission (a
        # realistic 6-24 h window depending on locale); later doses land
        # at 10:00 on their scheduled day (mimicking the nursing round
        # cadence used elsewhere in the sim).
        if i == 0:
            hours_offset = min(int(within_hours), 24)
            sched = admit_dt + timedelta(hours=hours_offset)
        else:
            sched = datetime(admit_dt.year, admit_dt.month, admit_dt.day, 10, 0) + timedelta(days=int(day_offset))
        # Skip doses that fall past discharge.
        if isinstance(discharge_dt, datetime) and sched > discharge_dt:
            continue
        out.append(
            MedicationAdministration(
                order_id=order_id,
                drug_name=drug_name,
                scheduled_datetime=sched,
                actual_datetime=sched,
                status="given",
                dose=dose,
                route=route,
            )
        )
    return out
