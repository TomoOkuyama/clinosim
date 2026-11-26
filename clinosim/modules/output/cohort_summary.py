"""Cohort summary: patient, condition and encounter statistics of a dataset.

``summary/cohort-summary.json`` sits next to ``cif/``, ``fhir_r4/`` and
``catalog/``. It is computed from the CIF records only (never from the FHIR
export), so every output has it, CIF-only runs included, and it is not part of
CIF: ``cif/metadata.json`` only points at it (``cohort_summary``).

The file is deterministic. It holds no timestamp, every mapping is written with
sorted keys and every list has an explicit order, so two runs on the same CIF
give identical bytes. The fields are specified in
``docs/reference/output-formats.md`` ("Cohort summary").

Rules the counts follow:

* A patient is counted once, whatever the number of CIF records (one file per
  encounter episode) the patient has.
* Age bands are the ``age_distribution`` bands of the country's
  ``locale/<c>/demographics.yaml``, applied to the age on the snapshot date
  (from the date of birth; the stored age when the date of birth is absent).
  An age above the last band falls in the last band.
* Chronic conditions are those of the patient's latest record (the record with
  the latest encounter start), as the FHIR Condition export maps them.
* Principal diagnoses are those of inpatient stays (discharge diagnosis, else
  admission diagnosis), mapped to the country's code system as the FHIR export
  emits them; a patient with several stays of one diagnosis counts once.
* Display names come from the code registry in the cohort's language, then
  English; a code with no registered display has ``display: null``.
"""

from __future__ import annotations

import glob
import json
import os
import statistics
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from clinosim.age_bands import find_age_band_or_last, parse_closed_age_band
from clinosim.codes import display as code_display
from clinosim.codes import get_system_uri, system_key_for
from clinosim.countries import lang_for
from clinosim.locale.loader import load_demographics, map_diagnosis_code

SUMMARY_DIRNAME = "summary"
SUMMARY_FILENAME = "cohort-summary.json"
METADATA_KEY = "cohort_summary"
SCHEMA_VERSION = 1

# CIF encounter_type of a hospital stay and the discharge disposition of a death.
INPATIENT_TYPE = "inpatient"
DEATH_DISPOSITION = "exp"


def _date_part(value: Any) -> str:
    """``YYYY-MM-DD`` of an ISO date or datetime string, "" when absent."""
    return str(value)[:10] if value else ""


def _parse_dt(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _age_on(patient: dict[str, Any], snapshot: str) -> int | None:
    dob = _date_part(patient.get("date_of_birth"))
    snap = _date_part(snapshot)
    if dob and snap:
        try:
            by, bm, bd = (int(x) for x in dob.split("-"))
            sy, sm, sd = (int(x) for x in snap.split("-"))
            return sy - by - ((sm, sd) < (bm, bd))
        except ValueError:
            pass
    age = patient.get("age")
    return int(age) if isinstance(age, (int, float)) else None


def _first_start(record: dict[str, Any]) -> str:
    starts = [str(e.get("admission_datetime") or "") for e in record.get("encounters") or []]
    starts = [s for s in starts if s]
    return min(starts) if starts else ""


def _concept_rows(counts: dict[str, set[str]], system_uri: str, system_key: str, lang: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "code": code,
            "system": system_uri,
            "display": code_display(system_key, code, lang),
            "patients": len(patients),
        }
        for code, patients in counts.items()
    ]
    rows.sort(key=lambda r: (-int(r["patients"]), str(r["code"])))
    return rows


def build_cohort_summary(
    records: Iterable[dict[str, Any]],
    *,
    country: str,
    period_start: str | None,
    period_end: str | None,
    snapshot_date: str | None,
) -> dict[str, Any]:
    """Summary of the CIF record dicts ``records`` (see the module docstring)."""
    lang = lang_for(country)
    snapshot = _date_part(snapshot_date) or _date_part(period_end)
    start, end = _date_part(period_start), _date_part(period_end) or snapshot
    bands = list(load_demographics(country).get("age_distribution", {}))
    bands.sort(key=lambda b: parse_closed_age_band(b)[0])

    patients: dict[str, dict[str, Any]] = {}  # patient_id -> patient of the latest record
    latest_start: dict[str, str] = {}
    principal: dict[str, set[str]] = {}
    in_hospital_deaths: set[str] = set()
    encounter_types: Counter[str] = Counter()
    stays = 0
    los_days: list[float] = []
    stay_deaths = 0

    for record in records:
        patient = record.get("patient") or {}
        pid = str(patient.get("patient_id") or "")
        if not pid:
            continue
        start_key = _first_start(record)
        if pid not in patients or start_key >= latest_start[pid]:
            latest_start[pid] = start_key
            patients[pid] = patient
        dx = record.get("clinical_diagnosis") or {}
        for enc in record.get("encounters") or []:
            etype = str(enc.get("encounter_type") or "unknown")
            encounter_types[etype] += 1
            died = enc.get("discharge_disposition") == DEATH_DISPOSITION
            if died:
                in_hospital_deaths.add(pid)
            if etype != INPATIENT_TYPE:
                continue
            stays += 1
            stay_deaths += died
            adm, dis = _parse_dt(enc.get("admission_datetime")), _parse_dt(enc.get("discharge_datetime"))
            if adm and dis and dis >= adm:
                los_days.append((dis - adm).total_seconds() / 86400.0)
            raw = dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code") or ""
            if raw:
                code = map_diagnosis_code(raw, country, sex=str(patient.get("sex") or ""))
                principal.setdefault(code, set()).add(pid)

    by_sex: Counter[str] = Counter()
    by_band: Counter[str] = Counter()
    chronic: dict[str, set[str]] = {}
    deaths = 0
    for pid, patient in patients.items():
        by_sex[str(patient.get("sex") or "unknown")] += 1
        age = _age_on(patient, snapshot)
        if age is not None and bands:
            by_band[find_age_band_or_last(bands, max(age, 0))] += 1
        for cond in patient.get("chronic_conditions") or []:
            raw = cond.get("code") if isinstance(cond, dict) else None
            if raw:
                code = map_diagnosis_code(raw, country, sex=str(patient.get("sex") or ""))
                chronic.setdefault(code, set()).add(pid)
        died_on = _date_part(patient.get("date_of_death"))
        if died_on and (not start or died_on >= start) and (not end or died_on <= end):
            deaths += 1

    dx_key = system_key_for("diagnosis", country)
    dx_uri = get_system_uri(dx_key)
    los = (
        {"mean": round(statistics.fmean(los_days), 2), "median": round(statistics.median(los_days), 2)}
        if los_days
        else {"mean": None, "median": None}
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "country": country,
        "language": lang,
        "period": {"start": start or None, "end": end or None},
        "snapshot_date": snapshot or None,
        "patients": {
            "total": len(patients),
            "by_sex": dict(sorted(by_sex.items())),
            "by_age_band": [{"band": b, "patients": by_band.get(b, 0)} for b in bands],
            "deaths": {"total": deaths, "in_hospital": len(in_hospital_deaths)},
        },
        "conditions": {
            "chronic": _concept_rows(chronic, dx_uri, dx_key, lang),
            "inpatient_principal_diagnosis": _concept_rows(principal, dx_uri, dx_key, lang),
        },
        "encounters": {
            "total": sum(encounter_types.values()),
            "by_type": dict(sorted(encounter_types.items())),
            "inpatient": {
                "stays": stays,
                "finished_stays": len(los_days),
                "length_of_stay_days": los,
                "in_hospital_deaths": stay_deaths,
            },
        },
    }


def summary_path_for(cif_dir: str) -> str:
    """``summary/cohort-summary.json`` next to the ``cif/`` directory."""
    return os.path.join(os.path.dirname(os.path.abspath(cif_dir)), SUMMARY_DIRNAME, SUMMARY_FILENAME)


def _iter_cif_records(cif_dir: str) -> Iterable[dict[str, Any]]:
    for path in sorted(glob.glob(os.path.join(cif_dir, "structural", "patients", "*.json"))):
        with open(path, encoding="utf-8") as f:
            yield json.load(f)


def write_cohort_summary(cif_dir: str) -> str:
    """Write ``summary/cohort-summary.json`` for the CIF in ``cif_dir`` and point
    ``cif/metadata.json`` at it (``cohort_summary``, relative to the dataset
    root). Returns the summary path."""
    meta_path = os.path.join(cif_dir, "metadata.json")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    summary = build_cohort_summary(
        _iter_cif_records(cif_dir),
        country=str(meta.get("country") or ""),
        period_start=meta.get("simulation_period_start"),
        period_end=meta.get("simulation_period_end"),
        snapshot_date=meta.get("snapshot_date"),
    )
    path = summary_path_for(cif_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    root = os.path.dirname(os.path.abspath(cif_dir))
    meta[METADATA_KEY] = os.path.relpath(path, root).replace(os.sep, "/")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return path
