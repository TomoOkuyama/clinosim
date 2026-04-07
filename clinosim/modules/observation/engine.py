"""Observation engine — v0.1-alpha: Layer 3 noise, missingness, rounding.

Applies realistic variability to physiology-derived lab values.
Three sources: biological variation (CVi), pre-analytical, analytical (CVa).
"""

from __future__ import annotations

import numpy as np

# Biological variation (within-individual CV, Ricos et al.)
BIOLOGICAL_CV: dict[str, float] = {
    "Na": 0.006, "K": 0.046, "Cl": 0.012, "Ca": 0.019,
    "Creatinine": 0.056, "BUN": 0.121, "Glucose": 0.056,
    "AST": 0.120, "ALT": 0.195, "ALP": 0.068, "GGT": 0.138,
    "T_Bil": 0.213, "Albumin": 0.032, "TP": 0.028,
    "LDH": 0.083, "CK": 0.226,
    "WBC": 0.110, "Hb": 0.029, "Hct": 0.029, "Plt": 0.094,
    "CRP": 0.423, "PCT": 0.30, "BNP": 0.40, "Troponin": 0.14,
    "Lactate": 0.278, "pH": 0.002, "HCO3": 0.040, "pCO2": 0.046,
    "eGFR": 0.056, "PT_INR": 0.040,
}

# Analytical variation (instrument imprecision)
ANALYTICAL_CV: dict[str, float] = {
    "Na": 0.008, "K": 0.015, "Cl": 0.008, "Ca": 0.015,
    "Creatinine": 0.030, "BUN": 0.030, "Glucose": 0.020,
    "AST": 0.050, "ALT": 0.050, "ALP": 0.040, "GGT": 0.050,
    "T_Bil": 0.040, "Albumin": 0.025, "TP": 0.015,
    "LDH": 0.035, "CK": 0.040,
    "WBC": 0.025, "Hb": 0.015, "Hct": 0.015, "Plt": 0.035,
    "CRP": 0.050, "PCT": 0.080, "BNP": 0.070, "Troponin": 0.080,
    "Lactate": 0.040, "pH": 0.001, "HCO3": 0.025, "pCO2": 0.025,
    "eGFR": 0.030, "PT_INR": 0.035,
}

# Reporting precision (number of decimal places)
PRECISION: dict[str, int] = {
    "Na": 0, "K": 1, "Cl": 0, "Ca": 1,
    "Creatinine": 2, "BUN": 1, "Glucose": 0, "eGFR": 0,
    "AST": 0, "ALT": 0, "ALP": 0, "GGT": 0, "T_Bil": 1, "Albumin": 1, "TP": 1,
    "LDH": 0, "CK": 0,
    "WBC": 0, "Hb": 1, "Hct": 1, "Plt": 0,  # Plt reported as integer (10^3/uL)
    "CRP": 1, "PCT": 2, "BNP": 1, "Troponin": 3,
    "Lactate": 1, "pH": 2, "HCO3": 1, "pCO2": 1,
    "PT_INR": 1,
    "HbA1c": 1, "ESR": 0,
    "LDL": 0, "HDL": 0, "TG": 0, "TC": 0,
    "Na": 0, "Fibrinogen": 0,
    "D_dimer": 2,
    "Amylase": 0, "Lipase": 0,
    "TSH": 2,
    "Cortisol": 1,
}


# Standard units for lab results — UCUM (http://unitsofmeasure.org)
# References: https://ucum.org/, FHIR R4 Observation requires UCUM
LAB_UNITS: dict[str, str] = {
    "Na": "mmol/L", "K": "mmol/L", "Cl": "mmol/L", "Ca": "mg/dL",
    "Creatinine": "mg/dL", "BUN": "mg/dL", "Glucose": "mg/dL",
    "eGFR": "mL/min/{1.73_m2}",  # UCUM annotation for body surface area
    "AST": "U/L", "ALT": "U/L", "ALP": "U/L", "GGT": "U/L",
    "T_Bil": "mg/dL", "Albumin": "g/dL", "TP": "g/dL",
    "LDH": "U/L", "CK": "U/L",
    "WBC": "/uL",         # Cell count per microliter (e.g. 7500)
    "Hb": "g/dL", "Hct": "%",
    "Plt": "10*3/uL",     # UCUM (was "x10^3/uL")
    "CRP": "mg/L", "PCT": "ng/mL", "BNP": "pg/mL", "Troponin": "ng/mL",
    "Lactate": "mmol/L", "pH": "[pH]", "HCO3": "mmol/L", "pCO2": "mm[Hg]",
    "pO2": "mm[Hg]",
    "PT_INR": "{INR}", "Fibrinogen": "mg/dL", "D_dimer": "ug/mL",
    "TSH": "m[IU]/L", "SpO2": "%",
    "HbA1c": "%", "ESR": "mm/h",
    "Urinalysis": "{qualitative}", "Urine_culture": "{qualitative}",
    "Rapid_Strep": "{qualitative}", "Tetanus_status": "{qualitative}",
    "LDL": "mg/dL", "HDL": "mg/dL", "TG": "mg/dL", "TC": "mg/dL",
    "Amylase": "U/L", "Lipase": "U/L",
    "Cortisol": "ug/dL",
    "BNP": "pg/mL",
}


def get_lab_unit(lab_name: str) -> str:
    """Get the standard unit for a lab test."""
    return LAB_UNITS.get(lab_name, "")


def apply_realistic_variability(
    lab_name: str,
    true_value: float,
    rng: np.random.Generator,
) -> float:
    """Apply 3-layer variability model to a physiology-derived lab value."""
    if true_value <= 0:
        return 0.0

    cvi = BIOLOGICAL_CV.get(lab_name, 0.05)
    cva = ANALYTICAL_CV.get(lab_name, 0.03)

    bio_noise = rng.normal(0, true_value * cvi)
    analytical_noise = rng.normal(0, true_value * cva)

    observed = true_value + bio_noise + analytical_noise
    return max(0.0, observed)


def round_to_precision(lab_name: str, value: float) -> float:
    """Round lab value to clinically reported precision."""
    decimals = PRECISION.get(lab_name, 1)
    return round(value, decimals)


_QUALITATIVE_TESTS = {"Urinalysis", "Urine_culture", "Rapid_Strep", "Tetanus_status"}


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
    """Return categorical result for qualitative tests."""
    if lab_name == "Urinalysis":
        # Common qualitative urinalysis dipstick result
        return str(rng.choice(
            ["Normal", "Trace protein", "1+ protein", "Trace blood", "1+ leukocytes", "Glucose 1+"],
            p=[0.55, 0.10, 0.05, 0.10, 0.15, 0.05],
        ))
    if lab_name == "Urine_culture":
        return str(rng.choice(
            ["No growth", "Mixed flora (contaminated)", "E. coli >100,000 CFU/mL", "Klebsiella >100,000 CFU/mL"],
            p=[0.55, 0.20, 0.20, 0.05],
        ))
    if lab_name == "Rapid_Strep":
        return str(rng.choice(["Negative", "Positive"], p=[0.85, 0.15]))
    if lab_name == "Tetanus_status":
        return str(rng.choice(["Up to date", "Unknown", "Last >10 years ago"], p=[0.55, 0.30, 0.15]))
    return "Negative"


def determine_flag(
    lab_name: str,
    value: float,
    sex: str = "F",
    reference_ranges: dict | None = None,
) -> str | None:
    """Determine H/L/critical flag for a lab value."""
    # Default reference ranges (adult)
    defaults: dict[str, dict[str, tuple[float, float]]] = {
        "CRP": {"all": (0, 3)},
        "WBC": {"all": (3500, 9500)},
        "Hb": {"M": (13.5, 17.5), "F": (11.5, 15.5)},
        "Plt": {"all": (150, 400)},
        "Creatinine": {"M": (0.6, 1.1), "F": (0.4, 0.8)},
        "BUN": {"all": (8, 20)},
        "Na": {"all": (136, 145)},
        "K": {"all": (3.5, 5.0)},
        "Glucose": {"all": (70, 110)},
        "Albumin": {"all": (3.5, 5.0)},
        "AST": {"all": (10, 35)},
        "ALT": {"all": (5, 40)},
        "Lactate": {"all": (0.5, 2.0)},
        "pH": {"all": (7.35, 7.45)},
        "PCT": {"all": (0, 0.05)},
    }

    ranges = reference_ranges or defaults
    range_entry = ranges.get(lab_name)
    if not range_entry:
        return None

    low, high = range_entry.get(sex, range_entry.get("all", (0, 9999)))

    # Panic values
    panic: dict[str, tuple[float | None, float | None]] = {
        "K": (2.5, 6.5),
        "Hb": (7.0, None),  # critical low only (Hb < 7.0 = critical)
        "Glucose": (40, 500),
        "Na": (120, 160),
        "pH": (7.1, 7.6),
    }
    if lab_name in panic:
        p_lo, p_hi = panic[lab_name]
        if p_lo is not None and value < p_lo:
            return "critical"
        if p_hi is not None and value > p_hi:
            return "critical"

    if value < low:
        return "L"
    if value > high:
        return "H"
    return None
