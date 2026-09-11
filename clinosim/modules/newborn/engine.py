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
from clinosim.types.procedure import ProcedureRecord

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


def build_hearing_screen_procedure(record: Any) -> ProcedureRecord | None:
    """AABR hearing screen `ProcedureRecord` for a newborn's birth admission
    (#1252 N5).

    Universal newborn hearing screening — JP 厚生労働省 新生児聴覚検査事業 /
    US EHDI Act, ~95-98 % coverage in modern hospitals. Fires during the
    birth admission (median day 1 per `newborn_screening.yaml
    ::hearing_screen.hours_after_admission`). Result sampled from the
    yaml distribution using a fresh sub-seed keyed on `patient_id`
    (RNG-neutral against every other draw). Real-world well-newborn
    cohort: ~97 % pass, ~3 % refer.

    Returns `None` for non-newborn records or when the screen would land
    past discharge.
    """
    if not is_newborn_birth_record(record):
        return None
    encounters = _get(record, "encounters", []) or []
    if not encounters:
        return None
    birth_enc = encounters[0]
    admit_dt = _get(birth_enc, "admission_datetime", None)
    if not isinstance(admit_dt, datetime):
        return None
    discharge_dt = _get(birth_enc, "discharge_datetime", None)
    patient = _get(record, "patient", None)
    pid = str(_get(patient, "patient_id", "") or "") if patient is not None else ""
    if not pid:
        return None

    cfg = load_newborn_config().get("hearing_screen") or {}
    if not cfg:
        return None
    hours = int(cfg.get("hours_after_admission", 24) or 24)
    sched = admit_dt + timedelta(hours=hours)
    if isinstance(discharge_dt, datetime) and sched > discharge_dt:
        return None
    result_weights = cfg.get("result_weights") or {"pass": 0.97, "refer": 0.03}

    sub = int(hashlib.sha256(f"newborn-hearing-screen|{pid}".encode()).hexdigest(), 16) % (2**32)
    rng = np.random.default_rng(sub)
    outcomes = list(result_weights.keys())
    raw = np.array([float(result_weights[k]) for k in outcomes], dtype=float)
    probs = raw / raw.sum()
    outcome_key = str(outcomes[int(rng.choice(len(outcomes), p=probs))])

    outcome_code = str(cfg.get("outcome_pass" if outcome_key == "pass" else "outcome_refer") or "")
    proc_code = str(cfg.get("procedure_code") or "232717001")  # SNOMED AABR screening
    category_code = str(cfg.get("category_code") or "103693007")  # diagnostic procedure

    enc_id = str(_get(birth_enc, "encounter_id", "") or "")
    proc_id = f"PROC-{pid}-HEARING-SCREEN"

    return ProcedureRecord(
        procedure_id=proc_id,
        patient_id=pid,
        encounter_id=enc_id,
        procedure_type="hearing_screen_aabr",
        procedure_code=proc_code,
        start_datetime=sched,
        end_datetime=sched + timedelta(minutes=15),
        duration_minutes=15,
        category_code=category_code,
        outcome_code=outcome_code,
    )


def build_metabolic_screen_procedure(record: Any, country: str) -> ProcedureRecord | None:
    """Tandem-MS newborn metabolic screening `ProcedureRecord` (#1252 N6).

    Universal newborn metabolic mass-screening — heel-stick capillary
    blood collected during the birth admission, tested for a panel of
    20+ inborn errors of metabolism. Detection rate ~0.1-0.3 %;
    ~99.7 % pass in real well-newborn cohorts. Locale differs only in
    the scheduled day of collection (JP day 4 before a 5-day discharge;
    US day 1 24 h post-birth before a 2-day discharge — #1263). The
    SNOMED procedure code and result distribution are locale-invariant.

    This PR (N6) emits only the `Procedure` event for the collection.
    `ServiceRequest` (screening order) + `Specimen` (heel-stick blood)
    + `DiagnosticReport` (per-analyte results) are deliberately deferred
    to a follow-up — the Procedure alone gives evidence "the screening
    was performed with outcome X".

    Sampled via a fresh sub-seed keyed on `patient_id`. Skipped when
    the target day falls past discharge (defensive; applies to LOS <
    schedule_day edge cases).
    """
    if not is_newborn_birth_record(record):
        return None
    encounters = _get(record, "encounters", []) or []
    if not encounters:
        return None
    birth_enc = encounters[0]
    admit_dt = _get(birth_enc, "admission_datetime", None)
    if not isinstance(admit_dt, datetime):
        return None
    discharge_dt = _get(birth_enc, "discharge_datetime", None)
    patient = _get(record, "patient", None)
    pid = str(_get(patient, "patient_id", "") or "") if patient is not None else ""
    if not pid:
        return None

    cfg = load_newborn_config().get("metabolic_screen") or {}
    if not cfg:
        return None
    sched_cfg = cfg.get("schedule_day", 4)
    locale_key = "jp" if is_jp(country) else "us"
    if isinstance(sched_cfg, dict):
        schedule_day = int(sched_cfg.get(locale_key, sched_cfg.get("jp", 4)) or 4)
    else:
        schedule_day = int(sched_cfg or 4)
    # Collection at 10:00 on day N (mimicking morning-round cadence).
    day_dt = datetime(admit_dt.year, admit_dt.month, admit_dt.day, 10, 0)
    sched = day_dt + timedelta(days=schedule_day)
    if sched <= admit_dt:
        # Same-day birth: shift into afternoon so it does not tie the admit ts.
        sched = admit_dt + timedelta(hours=4)
    if isinstance(discharge_dt, datetime) and sched > discharge_dt:
        return None
    result_weights = cfg.get("result_weights") or {"pass": 0.997, "refer": 0.003}

    sub = int(hashlib.sha256(f"newborn-metabolic-screen|{pid}".encode()).hexdigest(), 16) % (2**32)
    rng = np.random.default_rng(sub)
    outcomes = list(result_weights.keys())
    raw = np.array([float(result_weights[k]) for k in outcomes], dtype=float)
    probs = raw / raw.sum()
    outcome_key = str(outcomes[int(rng.choice(len(outcomes), p=probs))])

    outcome_code = str(cfg.get("outcome_pass" if outcome_key == "pass" else "outcome_refer") or "")
    proc_code = str(cfg.get("procedure_code") or "405058008")  # SNOMED neonatal screening
    category_code = str(cfg.get("category_code") or "103693007")  # diagnostic procedure

    enc_id = str(_get(birth_enc, "encounter_id", "") or "")
    proc_id = f"PROC-{pid}-METABOLIC-SCREEN"

    return ProcedureRecord(
        procedure_id=proc_id,
        patient_id=pid,
        encounter_id=enc_id,
        procedure_type="metabolic_screen_tandem_ms",
        procedure_code=proc_code,
        start_datetime=sched,
        end_datetime=sched + timedelta(minutes=5),
        duration_minutes=5,
        category_code=category_code,
        outcome_code=outcome_code,
    )


def build_bilirubin_observations(record: Any) -> list[dict[str, Any]]:
    """Transcutaneous bilirubin (TcB) daily readings across the birth
    admission (#1252 N7).

    LOINC 58941-6. One reading per scheduled day (per
    `newborn_screening.yaml::bilirubin.schedule_days`, default day
    1 / 2 / 3), sampled from a normal distribution keyed on
    `patient_id`. Skipped for days that fall past discharge.

    Returns a list of `{"day": N, "timestamp": dt, "value_mg_dl": float,
    "loinc": "58941-6"}` dicts. The FHIR emit layer walks this list.
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
    pid = str(_get(patient, "patient_id", "") or "") if patient is not None else ""
    if not pid:
        return []

    cfg = load_newborn_config().get("bilirubin") or {}
    schedule_days = list(cfg.get("schedule_days") or [1, 2, 3])
    hour_of_day = int(cfg.get("hour_of_day", 10) or 10)
    mean_by_day = cfg.get("mean_by_day") or {}
    std_by_day = cfg.get("std_by_day") or {}
    clamp_min = float(cfg.get("clamp_min", 2.0) or 2.0)
    clamp_max = float(cfg.get("clamp_max", 20.0) or 20.0)
    loinc = str(cfg.get("loinc") or "58941-6")

    day_base = datetime(admit_dt.year, admit_dt.month, admit_dt.day, hour_of_day, 0)
    out: list[dict[str, Any]] = []
    for day in schedule_days:
        try:
            d = int(day)
        except (TypeError, ValueError):
            continue
        ts = day_base + timedelta(days=d)
        if ts <= admit_dt:
            continue
        if isinstance(discharge_dt, datetime) and ts > discharge_dt:
            continue
        mean = float((mean_by_day or {}).get(d) or (mean_by_day or {}).get(str(d)) or 6.0 + d * 2.0)
        std = float((std_by_day or {}).get(d) or (std_by_day or {}).get(str(d)) or 2.0)
        sub = int(hashlib.sha256(f"newborn-bilirubin|{pid}|{d}".encode()).hexdigest(), 16) % (2**32)
        rng = np.random.default_rng(sub)
        value = float(rng.normal(mean, std))
        value = max(clamp_min, min(clamp_max, value))
        out.append({"day": d, "timestamp": ts, "value_mg_dl": round(value, 1), "loinc": loinc})
    return out


def build_cchd_pulse_ox(record: Any) -> list[dict[str, Any]]:
    """CCHD (Critical Congenital Heart Disease) pulse-oximetry screen
    (#1252 N7).

    Right-hand + one-foot SpO2 at ≥ 24 h post-birth. LOINC 59408-5
    with body-site distinction encoded in the emit layer. Well-newborn
    cohort: both readings ~97 %, ~99.9 % pass. Skipped when the 24 h
    slot falls past discharge (defensive).

    Returns a list of `{"site": "right_hand" | "foot", "timestamp": dt,
    "value_pct": int, "loinc": "59408-5"}` dicts. The FHIR emit layer
    renders one Observation per body site.
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
    pid = str(_get(patient, "patient_id", "") or "") if patient is not None else ""
    if not pid:
        return []

    cfg = load_newborn_config().get("cchd_pulse_ox") or {}
    hours = int(cfg.get("hours_after_admission", 24) or 24)
    sched = admit_dt + timedelta(hours=hours)
    if isinstance(discharge_dt, datetime) and sched > discharge_dt:
        return []
    loinc = str(cfg.get("loinc") or "59408-5")
    clamp_min = int(cfg.get("clamp_min", 90) or 90)
    clamp_max = int(cfg.get("clamp_max", 100) or 100)

    def _sample(mean: float, std: float, salt: str) -> int:
        sub = int(hashlib.sha256(f"newborn-cchd|{pid}|{salt}".encode()).hexdigest(), 16) % (2**32)
        rng = np.random.default_rng(sub)
        v = int(round(float(rng.normal(mean, std))))
        return max(clamp_min, min(clamp_max, v))

    rh_mean = float(cfg.get("right_hand_spo2_mean", 97) or 97)
    rh_std = float(cfg.get("right_hand_spo2_std", 1) or 1)
    ft_mean = float(cfg.get("foot_spo2_mean", 97) or 97)
    ft_std = float(cfg.get("foot_spo2_std", 1) or 1)
    return [
        {"site": "right_hand", "timestamp": sched, "value_pct": _sample(rh_mean, rh_std, "rh"), "loinc": loinc},
        {"site": "foot", "timestamp": sched, "value_pct": _sample(ft_mean, ft_std, "ft"), "loinc": loinc},
    ]


def build_ophthalmic_prophylaxis(record: Any, country: str) -> list[MedicationAdministration]:
    """Erythromycin ophthalmic prophylaxis at birth (US only) — #1252 N7.

    CDC-recommended for every US newborn (protection against neonatal
    gonococcal ophthalmia). Not JP standard.

    Config in `newborn_screening.yaml::ophthalmic_prophylaxis` — JP
    branch declares `drug_name = ""` which the engine reads as "not
    administered" and returns an empty list.
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
    cfg = (load_newborn_config().get("ophthalmic_prophylaxis") or {}).get("jp" if is_jp(country) else "us") or {}
    drug_name = str(cfg.get("drug_name") or "")
    if not drug_name:
        return []
    dose = str(cfg.get("dose") or "")
    route = str(cfg.get("route") or "OPH")
    within_hours = int(cfg.get("within_hours_of_birth", 1) or 1)
    sched = admit_dt + timedelta(hours=min(within_hours, 24))
    enc_id = str(_get(birth_enc, "encounter_id", "") or "")
    order_id = f"ORD-{enc_id}-OPH-PROPHYLAXIS" if enc_id else "ORD-OPH-PROPHYLAXIS"
    return [
        MedicationAdministration(
            order_id=order_id,
            drug_name=drug_name,
            scheduled_datetime=sched,
            actual_datetime=sched,
            status="given",
            dose=dose,
            route=route,
        )
    ]
