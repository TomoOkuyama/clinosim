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

import hashlib
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import is_jp
from clinosim.types.encounter import MedicationAdministration, VitalSignRecord

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


def build_newborn_shift_vitals(record: Any) -> list[VitalSignRecord]:
    """Shift-cadence vital signs for a newborn's birth admission (#1252 N3).

    The observation module's vitals engine derives per-day vitals from
    `physiological_states` + `baseline_vitals`. Healthy Z38.0 newborns
    have no physiology trajectory (nothing to perturb → engine emits
    nothing), so a real neonatal chart's shift-cadence T / HR / RR /
    SpO2 series is silently missing. This helper closes the gap.

    Emits one `VitalSignRecord` at admission (t=0) and one at each
    subsequent shift boundary (`newborn_screening.yaml::shift_vitals
    .shift_hours`, default night 00:00 / day 08:00 / evening 16:00)
    across the birth admission LOS. Values are the newborn's own
    `baseline_vitals` verbatim — deterministic, no RNG. Jitter /
    physiology-driven perturbation is a follow-up once the neonatal
    physiology model lands.

    Returns an empty list on non-newborn records (defensive; the
    enricher already gates).
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

    patient = _get(record, "patient", None)
    if patient is None:
        return []
    bv = _get(patient, "baseline_vitals", None)
    if bv is None:
        return []

    cfg = load_newborn_config().get("shift_vitals") or {}
    shift_hours = list(cfg.get("shift_hours") or [0, 8, 16])
    if not shift_hours:
        return []
    shift_hours_sorted = sorted(int(h) for h in shift_hours if 0 <= int(h) <= 23)

    # Enumerate every shift boundary from admission through discharge,
    # plus the admission timestamp itself (real charts always record a
    # vital set on arrival, regardless of shift).
    boundaries: list[datetime] = [admit_dt]
    day = datetime(admit_dt.year, admit_dt.month, admit_dt.day)
    end = discharge_dt if isinstance(discharge_dt, datetime) else admit_dt + timedelta(days=1)
    cursor = day
    while cursor <= end:
        for h in shift_hours_sorted:
            t = cursor.replace(hour=h, minute=0, second=0, microsecond=0)
            if t <= admit_dt or t > end:
                continue
            boundaries.append(t)
        cursor += timedelta(days=1)
    boundaries.sort()

    temperature = float(_get(bv, "temperature", 36.7) or 36.7)
    heart_rate = int(_get(bv, "heart_rate", 130) or 130)
    systolic_bp = int(_get(bv, "systolic_bp", 68) or 68)
    diastolic_bp = int(_get(bv, "diastolic_bp", 40) or 40)
    respiratory_rate = int(_get(bv, "respiratory_rate", 40) or 40)
    spo2 = float(_get(bv, "spo2", 97) or 97)

    return [
        VitalSignRecord(
            timestamp=ts,
            temperature_celsius=temperature,
            heart_rate=heart_rate,
            systolic_bp=systolic_bp,
            diastolic_bp=diastolic_bp,
            respiratory_rate=respiratory_rate,
            spo2=spo2,
            data_source="manual",
        )
        for ts in boundaries
    ]


def build_apgar_scores(record: Any) -> list[dict[str, Any]]:
    """Apgar score at 1 min + 5 min for a newborn's birth admission (#1252 N4).

    Standard neonatal resuscitation assessment (Virginia Apgar, 1953).
    Each of five components (color / heart rate / reflex / muscle tone /
    respiration) scores 0-2; total 0-10.

    Weighted sample from `newborn_screening.yaml::apgar
    .minute_{1,5}_score_weights` using a fresh sub-seed keyed on the
    newborn's `patient_id` — RNG-neutral against every other draw.

    Returns a list of `{"minute": 1 | 5, "score": 0..10, "timestamp": datetime}`
    dicts. The FHIR emit layer walks this and renders LOINC 9271-8
    (1-min) / 9274-2 (5-min) Observation resources.

    Empty list for non-newborn records (defensive; the enricher gates).
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
    patient = _get(record, "patient", None)
    pid = str(_get(patient, "patient_id", "") or "") if patient is not None else ""
    if not pid:
        return []

    cfg = load_newborn_config().get("apgar") or {}
    m1_weights = cfg.get("minute_1_score_weights") or {}
    m5_weights = cfg.get("minute_5_score_weights") or {}
    if not m1_weights or not m5_weights:
        return []

    def _sample(weights: dict, salt: str) -> int:
        # Fresh sub-seed keyed on pid + salt — deterministic + isolated.
        sub = int(hashlib.sha256(f"newborn-apgar|{pid}|{salt}".encode()).hexdigest(), 16) % (2**32)
        rng = np.random.default_rng(sub)
        scores = list(weights.keys())
        raw = np.array([float(weights[s]) for s in scores], dtype=float)
        total = float(raw.sum())
        if total <= 0:
            return int(scores[0])
        probs = raw / total
        idx = int(rng.choice(len(scores), p=probs))
        return int(scores[idx])

    return [
        {"minute": 1, "score": _sample(m1_weights, "min1"), "timestamp": admit_dt + timedelta(minutes=1)},
        {"minute": 5, "score": _sample(m5_weights, "min5"), "timestamp": admit_dt + timedelta(minutes=5)},
    ]
