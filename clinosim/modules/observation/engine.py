"""Observation engine — v0.1-alpha: Layer 3 noise, missingness, rounding.

Applies realistic variability to physiology-derived lab values.
Three sources: biological variation (CVi), pre-analytical, analytical (CVa).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from clinosim.modules.observation._variability_defaults import (
    DEFAULT_ANALYTICAL_CV,
    DEFAULT_BIOLOGICAL_CV,
    RAPID_STREP_RESULT_DIST,
    TETANUS_STATUS_RESULT_DIST,
    URINALYSIS_RESULT_DIST,
    URINE_CULTURE_RESULT_DIST,
    URINE_DRUG_SCREEN_RESULT_DIST,
)

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


@lru_cache(maxsize=1)
def _lab_aliases() -> dict[str, str]:
    path = _REF_DIR / "lab_aliases.yaml"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@lru_cache(maxsize=1)
def _lab_panels() -> dict[str, list[str]]:
    path = _REF_DIR / "lab_panels.yaml"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def canonical_lab_name(name: str) -> str:
    """Resolve a protocol lab order name to the canonical analyte (AD-55, data-driven)."""
    return _lab_aliases().get(name, name)


def lab_panel_components(name: str) -> list[str]:
    """Component analytes for a panel order (e.g. ABG → pH/pCO2/pO2/HCO3); [] if scalar."""
    return list(_lab_panels().get(canonical_lab_name(name), []))


# Per-analyte constants live in reference_data/lab_constants.yaml (Issue #2302),
# keyed by canonical lab name; see that file for the sources and units.
_LAB_CONSTANTS: dict[str, dict[str, Any]] = yaml.safe_load(
    (_REF_DIR / "lab_constants.yaml").read_text(encoding="utf-8")
)

BIOLOGICAL_CV: dict[str, float] = dict(_LAB_CONSTANTS["biological_cv"])

ANALYTICAL_CV: dict[str, float] = dict(_LAB_CONSTANTS["analytical_cv"])

PRECISION: dict[str, int] = dict(_LAB_CONSTANTS["precision"])

LAB_UNITS: dict[str, str] = dict(_LAB_CONSTANTS["units"])


PHYSIOLOGIC_LIMITS: dict[str, tuple[float, float]] = {
    lab: (v[0], v[1]) for lab, v in _LAB_CONSTANTS["physiologic_limits"].items()
}


BASELINE_LAB_NORMALS: dict[str, float] = dict(_LAB_CONSTANTS["baseline_normals"])


def get_lab_unit(lab_name: str) -> str:
    """Get the standard unit for a lab test."""
    return LAB_UNITS.get(lab_name, "")


def clamp_to_physiologic_limits(lab_name: str, value: float) -> float:
    """Clip an observed lab value to the analyte's PHYSIOLOGIC_LIMITS band.

    Issue #735: pre-analytical perturbations (measurement noise,
    hemolysis, etc.) can push observed values past life-incompatible
    extremes on top of an already-clamped physiology-derived true value.
    Apply this after any perturbation that scales / adds noise to a lab
    value so a K > 10 mmol/L or CRP > 663 mg/L never reaches downstream
    output. Analytes without an entry in PHYSIOLOGIC_LIMITS are passed
    through, only the negative-value floor is enforced (mirrors the old
    apply_realistic_variability fallback).
    """
    limit = PHYSIOLOGIC_LIMITS.get(lab_name)
    if limit is not None:
        lo, hi = limit
        return float(min(max(value, lo), hi))
    return max(0.0, value)


def apply_realistic_variability(
    lab_name: str,
    true_value: float,
    rng: np.random.Generator,
) -> float:
    """Apply 3-layer variability model to a physiology-derived lab value."""
    if true_value <= 0:
        return 0.0

    cvi = BIOLOGICAL_CV.get(lab_name, DEFAULT_BIOLOGICAL_CV)
    cva = ANALYTICAL_CV.get(lab_name, DEFAULT_ANALYTICAL_CV)

    bio_noise = rng.normal(0, true_value * cvi)
    analytical_noise = rng.normal(0, true_value * cva)

    observed = true_value + bio_noise + analytical_noise
    return clamp_to_physiologic_limits(lab_name, observed)


def round_to_precision(lab_name: str, value: float) -> float:
    """Round lab value to clinically reported precision."""
    decimals = PRECISION.get(lab_name, 1)
    return round(value, decimals)


_QUALITATIVE_TESTS = {"Urinalysis", "Urine_culture", "Rapid_Strep", "Tetanus_status", "Urine_drug_screen"}


def is_qualitative_test(lab_name: str) -> bool:
    """Whether the analyte reports a categorical result (no numeric baseline)."""
    return lab_name in _QUALITATIVE_TESTS


def generate_lab_result(
    lab_name: str,
    true_value: float,
    rng: np.random.Generator,
) -> float | str:
    """Full pipeline: variability + rounding. Returns string for qualitative tests."""
    if lab_name in _QUALITATIVE_TESTS:
        return _generate_qualitative_result(lab_name, rng)
    noisy = apply_realistic_variability(lab_name, true_value, rng)
    return round_to_precision(lab_name, noisy)


def _generate_qualitative_result(lab_name: str, rng: np.random.Generator) -> str:
    """Return categorical result for qualitative tests.

    Distribution vectors (options + weights per test) live in
    ``_variability_defaults.py`` (Issue #637); this function only owns
    the per-test dispatch.
    """
    if lab_name == "Urinalysis":
        return str(rng.choice(URINALYSIS_RESULT_DIST.options, p=URINALYSIS_RESULT_DIST.weights))
    if lab_name == "Urine_culture":
        return str(rng.choice(URINE_CULTURE_RESULT_DIST.options, p=URINE_CULTURE_RESULT_DIST.weights))
    if lab_name == "Rapid_Strep":
        return str(rng.choice(RAPID_STREP_RESULT_DIST.options, p=RAPID_STREP_RESULT_DIST.weights))
    if lab_name == "Urine_drug_screen":
        return str(rng.choice(URINE_DRUG_SCREEN_RESULT_DIST.options, p=URINE_DRUG_SCREEN_RESULT_DIST.weights))
    if lab_name == "Tetanus_status":
        return str(rng.choice(TETANUS_STATUS_RESULT_DIST.options, p=TETANUS_STATUS_RESULT_DIST.weights))
    return "Negative"


_PANIC_THRESHOLDS: dict[str, tuple[float | None, float | None]] = {
    lab: (v[0], v[1]) for lab, v in _LAB_CONSTANTS["panic_thresholds"].items()
}


@lru_cache(maxsize=2)
def _reference_ranges_by_sex(country: str) -> dict[str, dict[str, tuple[float, float]]]:
    """Transform the YAML `ranges: {lab: [{low, high, sex?}]}` shape into a
    `{lab_name: {sex: (low, high)}}` dict that ``determine_flag`` consumes.

    Entries without a ``sex`` field become the ``"all"`` key so the caller can
    look up ``ranges.get(sex, ranges.get("all"))``. Cached per country
    (``maxsize=2`` = JP + US).
    """
    from clinosim.locale.loader import load_reference_ranges

    raw = load_reference_ranges(country) or {}
    ranges_yaml = raw.get("ranges") or {}
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for lab_name, entries in ranges_yaml.items():
        if not isinstance(entries, list):
            continue
        by_sex: dict[str, tuple[float, float]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            low = entry.get("low")
            high = entry.get("high")
            if low is None or high is None:
                continue
            key = entry.get("sex") or "all"
            by_sex[key] = (float(low), float(high))
        if by_sex:
            out[lab_name] = by_sex
    return out


# Drugs whose lab effect needs a loading period when started in hospital:
# warfarin lifts INR only after the vitamin-K-dependent factors deplete
# (loading-dose 3-day rule). Home medications are in effect from day 0.
IN_HOSPITAL_LOADING_DAYS: dict[str, int] = {"warfarin": 3}


def medication_name(med: Any) -> str:
    """Drug name of a home medication, an order or a plain string."""
    if isinstance(med, str):
        return med
    if isinstance(med, dict):
        return str(med.get("drug_name") or med.get("display_name") or "")
    return str(getattr(med, "drug_name", "") or getattr(med, "display_name", "") or "")


def _as_date(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        from datetime import datetime

        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return value.date() if hasattr(value, "date") else None


def medications_in_effect(
    home_medications: Any,
    medication_orders: Any = None,
    admission_date: Any = None,
    current_day: int | None = None,
) -> list[Any]:
    """The medications acting on lab values on ``current_day`` of a stay: the
    home medications plus the catalog id of each in-hospital drug ordered at
    least its loading period ago (:data:`IN_HOSPITAL_LOADING_DAYS`).

    The one "is the patient on drug X" decision (Issue #2293): INR generation,
    result flagging and the FHIR therapeutic reference range all read it, via
    :func:`clinosim.codes.drugs.names_drug` on the returned entries. Orders
    and medications may be objects or dicts; order datetimes may be ISO
    strings. Without orders, admission date or day, only home medications
    count (outpatient and ED paths). ``DISCONTINUE: X`` marker orders are
    not orders to give X and never count.
    """
    from clinosim.codes.drugs import names_drug

    meds = list(home_medications or [])
    if not medication_orders or admission_date is None or current_day is None:
        return meds
    for drug_id, loading_days in IN_HOSPITAL_LOADING_DAYS.items():
        if current_day < loading_days or any(names_drug(medication_name(m), drug_id) for m in meds):
            continue
        for order in medication_orders:
            name = medication_name(order)
            # A "DISCONTINUE: X" marker stops X; it is not an order to give it.
            if name.startswith("DISCONTINUE:") or not names_drug(name, drug_id):
                continue
            ordered = getattr(order, "ordered_datetime", None)
            if ordered is None and isinstance(order, dict):
                ordered = order.get("ordered_datetime")
            ordered_date = _as_date(ordered)
            if ordered_date is None:
                continue
            if current_day - (ordered_date - admission_date).days >= loading_days:
                meds.append(drug_id)
                break
    return meds


def therapeutic_range(
    lab_name: str,
    country: str,
    *,
    medications: Any = None,
    age: int | None = None,
) -> tuple[float, float, str] | None:
    """``(low, high, text)`` of the drug-specific therapeutic range for the
    patient, or ``None`` when no listed drug is taken (Issue #2205).

    Read from ``therapeutic_ranges`` in the locale's reference_range_lab.yaml
    (e.g. INR on warfarin). ``drugs`` are catalog drug ids, matched against
    ``medications`` through the catalog names (Issue #2293); pass
    :func:`medications_in_effect` so a drug started in hospital counts.
    """
    from clinosim.codes.drugs import names_drug
    from clinosim.locale.loader import load_reference_ranges

    rows = ((load_reference_ranges(country) or {}).get("therapeutic_ranges") or {}).get(lab_name) or []
    if not rows or not medications:
        return None
    names = [medication_name(med) for med in medications]
    for row in rows:
        drugs = [str(d) for d in row.get("drugs") or []]
        if not any(names_drug(n, d) for d in drugs for n in names):
            continue
        if row.get("age_min") is not None and (age is None or age < int(row["age_min"])):
            continue
        return float(row["low"]), float(row["high"]), str(row.get("text") or "")
    return None


def determine_flag(
    lab_name: str,
    value: float | str,
    sex: str = "F",
    country: str = "US",
    *,
    medications: Any = None,
    age: int | None = None,
) -> str | None:
    """Determine H/L/critical flag for a lab value.

    Reference ranges are loaded from ``clinosim/locale/<country>/reference_range_lab.yaml``
    (JCCLS 共用基準範囲 for JP; standard US clinical reference for US) so the
    CIF ``flag`` and the FHIR ``Observation.interpretation`` (which reads the
    same YAML via ``_fhir_common.build_reference_range``) agree on every lab
    (Issue #542 single-source-of-truth fix).

    Panic / critical thresholds (:data:`_PANIC_THRESHOLDS`, from
    ``lab_constants.yaml``) are safety-critical absolute cutoffs shared across
    locales.

    Qualitative results (``value: str`` from ``generate_lab_result`` for
    Urinalysis / Rapid_Strep / etc.) return ``None`` (unflagged) — they have
    no numeric range.
    """
    if isinstance(value, str):
        return None

    ranges = _reference_ranges_by_sex(country)
    range_entry = ranges.get(lab_name)
    if not range_entry:
        return None

    low, high = range_entry.get(sex, range_entry.get("all", (0.0, 9999.0)))
    # Issue #2205: a patient on e.g. warfarin is judged against the
    # therapeutic range, so a therapeutic INR is not flagged high.
    therapeutic = therapeutic_range(lab_name, country, medications=medications, age=age)
    if therapeutic is not None:
        low, high = therapeutic[0], therapeutic[1]

    if lab_name in _PANIC_THRESHOLDS:
        p_lo, p_hi = _PANIC_THRESHOLDS[lab_name]
        if p_lo is not None and value < p_lo:
            return "critical"
        if p_hi is not None and value > p_hi:
            return "critical"

    if value < low:
        return "L"
    if value > high:
        return "H"
    return None
