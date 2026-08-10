"""Narrow-target antibiotic dose + frequency defaults (Issue #637).

``clinosim/modules/antibiotic/enricher.py::_narrow_dose_frequency``
returns a default (dose_string, frequency) pair for each drug that can
be picked as a narrow-therapy target during PR3b-3 Pass 2. The table
is lifted here per policy §5 so a maintainer can update the per-drug
regimen defaults without editing the enricher flow.

**Scope caveat (per the enricher's PR3b-1 docstring)**: this table is
intentionally simplified and does not perform renal-function (eGFR) or
weight-based dose adjustment. A future PR is expected to replace this
lookup with a per-patient dose calculator; until then these defaults
reflect the standard adult IV dosing conventions cited alongside each
entry. Frequencies match ``hai_empirical.yaml`` conventions
(``q<hours>h`` shorthand — e.g. ``q12h`` = every 12 hours).
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_NARROW_REGIMEN",
    "NARROW_DOSE_DEFAULTS",
]


NARROW_DOSE_DEFAULTS: dict[str, tuple[str, str]] = {
    # Vancomycin — 15-20 mg/kg q8-12h; 1 g q12h approximates the mid-range
    # empirical starting dose for a normal-renal-function adult before TDM
    # trough adjustment.
    "vancomycin": ("1g", "q12h"),
    # Cefazolin — 1-2 g q8h is the IDSA-standard MSSA / surgical-prophylaxis
    # regimen; 1 g q8h reflects the lower-weight adult default.
    "cefazolin": ("1g", "q8h"),
    # Ceftriaxone — 1-2 g q24h once-daily dosing for uncomplicated adult
    # infections; 1 g q24h is the standard non-CNS starting regimen.
    "ceftriaxone": ("1g", "q24h"),
    # Cefepime — 1-2 g q8-12h for gram-negative coverage; 1 g q8h is the
    # standard non-neutropenic regimen.
    "cefepime": ("1g", "q8h"),
    # Piperacillin-tazobactam — 3.375 g q6h is the FDA-labeled adult IV
    # dose for most indications (higher 4.5 g q6h reserved for extended-
    # infusion / nosocomial pneumonia).
    "piperacillin_tazobactam": ("3.375g", "q6h"),
    # Meropenem — 1 g q8h is the IDSA-standard adult regimen for
    # complicated intra-abdominal / UTI infections (higher 2 g q8h
    # reserved for meningitis, not routinely narrowed to).
    "meropenem": ("1g", "q8h"),
    # Ciprofloxacin — 400 mg q12h is the standard IV adult dose for
    # susceptible gram-negatives.
    "ciprofloxacin": ("400mg", "q12h"),
    # TMP-SMX — 160 mg (TMP component) q12h is the standard non-PJP
    # treatment dose (5 mg/kg BID); the drug label refers to the TMP
    # component so 160 mg TMP ≈ 800 mg SMX per dose.
    "trimethoprim_sulfamethoxazole": ("160mg", "q12h"),
    # Ampicillin — 1-2 g q4-6h; 2 g q6h is the standard adult IV regimen
    # for endocarditis / bacteremia.
    "ampicillin": ("2g", "q6h"),
    # Gentamicin — 3-5 mg/kg/day divided q8h (traditional) or single
    # daily 5-7 mg/kg (extended-interval). 80 mg q8h approximates the
    # traditional adult starting dose before serum-level titration.
    "gentamicin": ("80mg", "q8h"),
}
"""Standard adult IV narrow-therapy regimen for each drug key.

Every entry is (dose_string, frequency_token). Values reference IDSA
adult IV dosing conventions; per-patient / per-organism refinement
(eGFR-adjusted dosing, weight-based dosing, extended-infusion) is a
future-PR expansion of this table."""


DEFAULT_NARROW_REGIMEN: tuple[str, str] = ("1g", "q12h")
"""Fallback (dose, frequency) returned when a requested drug_key is
absent from :data:`NARROW_DOSE_DEFAULTS`.

Empirical tuning for the synthetic simulator: (1 g, q12h) is a
reasonable middle-of-the-road IV adult regimen — matches vancomycin,
which is the most commonly cited empirical anchor. Any drug new
enough to hit this fallback should be added to the table above rather
than left to inherit the vancomycin defaults."""
