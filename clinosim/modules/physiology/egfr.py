"""Estimated GFR from serum creatinine (Issue #3019).

eGFR is a calculation, not a measurement: laboratories report it from the
serum creatinine, the patient's age and sex (and, for children, height) with
their country's equation. The equations and their coefficients live in
``locale/<cc>/egfr_equation.yaml`` (JP: JSN / Uemura 2014; US: CKD-EPI 2021 /
bedside Schwartz). No randomness.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from clinosim.countries import is_jp
from clinosim.datafiles import load_data_yaml

_LOCALE = Path(__file__).resolve().parents[2] / "locale"


@lru_cache(maxsize=2)
def egfr_equations(country: str) -> dict[str, Any]:
    """The country's ``egfr_equation.yaml`` (adult + pediatric equations)."""
    key = "jp" if is_jp(country) else "us"
    return load_data_yaml(_LOCALE / key / "egfr_equation.yaml") or {}


def _sex(sex: str) -> str:
    return "F" if str(sex or "").upper().startswith("F") else "M"


def _adult(cr: float, age: int, sex: str, eq: dict[str, Any]) -> float:
    if eq["type"] == "jsn":
        value = float(eq["coefficient"]) * cr ** float(eq["creatinine_exponent"]) * age ** float(eq["age_exponent"])
        return value * float(eq["female_factor"]) if sex == "F" else value
    if eq["type"] == "ckd_epi_2021":
        ratio = cr / float(eq["kappa"][sex])
        value = (
            float(eq["coefficient"])
            * min(ratio, 1.0) ** float(eq["alpha"][sex])
            * max(ratio, 1.0) ** float(eq["upper_exponent"])
            * float(eq["age_base"]) ** age
        )
        return value * float(eq["female_factor"]) if sex == "F" else value
    raise ValueError(f"unknown adult eGFR equation {eq['type']!r}")


def _pediatric(cr: float, sex: str, height_cm: float, eq: dict[str, Any]) -> float:
    if eq["type"] == "bedside_schwartz":
        return float(eq["k"]) * height_cm / cr
    if eq["type"] == "uemura":
        x = height_cm / 100.0
        coeffs = [float(c) for c in eq["reference_cr_polynomial"][sex]]
        ref_cr = sum(c * x ** (len(coeffs) - 1 - i) for i, c in enumerate(coeffs))
        return float(eq["scale"]) * ref_cr / cr + float(eq["intercept"])
    raise ValueError(f"unknown pediatric eGFR equation {eq['type']!r}")


def estimated_gfr(creatinine: float, age: int, sex: str, height_cm: float | None, country: str) -> float | None:
    """eGFR (mL/min/1.73m²) of a serum creatinine (mg/dL) with the country's
    equation for the patient's age; ``None`` below the youngest age an
    equation covers (or without the height a pediatric equation needs)."""
    if creatinine is None or creatinine <= 0:
        return None
    eqs = egfr_equations(country)
    adult, pediatric = eqs.get("adult") or {}, eqs.get("pediatric") or {}
    s = _sex(sex)
    if adult and age >= int(adult["min_age"]):
        return _adult(float(creatinine), int(age), s, adult)
    if pediatric and age >= int(pediatric["min_age"]) and height_cm:
        return _pediatric(float(creatinine), s, float(height_cm), pediatric)
    return None
