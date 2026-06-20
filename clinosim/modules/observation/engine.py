"""Observation engine — v0.1-alpha: Layer 3 noise, missingness, rounding.

Applies realistic variability to physiology-derived lab values.
Three sources: biological variation (CVi), pre-analytical, analytical (CVa).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

_ALIAS_REF = Path(__file__).parent / "reference_data" / "lab_aliases.yaml"
_PANEL_REF = Path(__file__).parent / "reference_data" / "lab_panels.yaml"


@lru_cache(maxsize=1)
def _lab_aliases() -> dict[str, str]:
    if _ALIAS_REF.exists():
        with open(_ALIAS_REF) as f:
            return yaml.safe_load(f) or {}
    return {}


@lru_cache(maxsize=1)
def _lab_panels() -> dict[str, list[str]]:
    if _PANEL_REF.exists():
        with open(_PANEL_REF) as f:
            return yaml.safe_load(f) or {}
    return {}


def canonical_lab_name(name: str) -> str:
    """Resolve a protocol lab order name to the canonical analyte (AD-55, data-driven)."""
    return _lab_aliases().get(name, name)


def lab_panel_components(name: str) -> list[str]:
    """Component analytes for a panel order (e.g. ABG → pH/pCO2/pO2/HCO3); [] if scalar."""
    return list(_lab_panels().get(canonical_lab_name(name), []))


# Biological variation (within-individual CV, Ricos et al.)
BIOLOGICAL_CV: dict[str, float] = {
    "Na": 0.006, "K": 0.046, "Cl": 0.012, "Ca": 0.019,
    "Creatinine": 0.056, "BUN": 0.121, "Glucose": 0.056,
    "AST": 0.120, "ALT": 0.195, "ALP": 0.068, "GGT": 0.138,
    "T_Bil": 0.213, "Albumin": 0.032, "TP": 0.028,
    "LDH": 0.083, "CK": 0.226,
    "WBC": 0.110, "Hb": 0.029, "Hct": 0.029, "Plt": 0.094,
    "CRP": 0.423, "PCT": 0.30, "BNP": 0.40, "Troponin": 0.14,
    "Troponin_I": 0.14, "CK_MB": 0.15,
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
    "Troponin_I": 0.080, "CK_MB": 0.050,
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
    "Troponin_I": 3, "CK_MB": 1,
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
    "Troponin_I": "ng/mL", "CK_MB": "ng/mL",
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


# Absolute physiologic plausibility bounds for the OBSERVED (post-noise) value,
# in the analyte's LAB_UNITS. Set at the edge of human survivability so genuine
# extreme true values pass through untouched; the bounds only clip implausible
# measurement-noise tails (e.g. K 10.5 mmol/L, CRP 663 mg/L) that the multiplicative
# Gaussian noise model can otherwise produce on large true values.
PHYSIOLOGIC_LIMITS: dict[str, tuple[float, float]] = {
    "Na": (100.0, 180.0),       # mmol/L — survivable hypo/hypernatremia extremes
    "K": (2.5, 8.5),            # mmol/L
    "Cl": (70.0, 130.0),        # mmol/L
    "Ca": (4.0, 16.0),          # mg/dL
    "Glucose": (20.0, 1300.0),  # mg/dL — hypoglycemia to HHS
    "Creatinine": (0.1, 25.0),  # mg/dL — up to dialysis-dependent ESRD
    "BUN": (1.0, 250.0),        # mg/dL
    "Lactate": (0.2, 30.0),     # mmol/L
    "CRP": (0.0, 500.0),        # mg/L
    "WBC": (50.0, 200000.0),    # /uL — agranulocytosis to leukemoid reaction
    "Hb": (2.0, 24.0),          # g/dL
    "Hct": (6.0, 72.0),         # %
    "Plt": (1.0, 2000.0),       # 10^3/uL
    "pH": (6.8, 7.8),           # survivable acid-base extremes
    "pCO2": (10.0, 130.0),      # mm[Hg]
    "HCO3": (3.0, 50.0),        # mmol/L
    "Troponin_I": (0.0, 200.0), # ng/mL — massive MI
    "CK_MB": (0.0, 500.0),      # ng/mL
    "BNP": (0.0, 5000.0),       # pg/mL — assay reporting ceiling
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

    # Re-clamp post-noise to analyte-specific physiologic bounds so measurement
    # noise on large true values cannot produce life-incompatible observations.
    limit = PHYSIOLOGIC_LIMITS.get(lab_name)
    if limit is not None:
        lo, hi = limit
        return float(min(max(observed, lo), hi))
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
        "Troponin_I": {"M": (0.0, 0.04), "F": (0.0, 0.03)},  # ng/mL; sex-specific cutoff
        "CK_MB": {"all": (0.0, 5.0)},  # ng/mL
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
