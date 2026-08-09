"""Lab-observation variability defaults + qualitative-result distributions
(Issue #637 observation hotspot).

Two families of previously-inline scalars in
``clinosim/modules/observation/engine.py`` are lifted here so they follow
policy §5 (constants must be named, docstring-annotated with purpose /
unit / source, and located in the right place):

1. **CV fallback defaults** — the two floats that
   ``apply_realistic_variability`` used inline as the last-resort CV when
   a lab name is not in the per-analyte ``BIOLOGICAL_CV`` /
   ``ANALYTICAL_CV`` maps. Kept module-scope in ``engine.py`` alongside
   those maps would have worked; extracting them here follows the
   existing per-topic threshold-file convention (``vitals_thresholds.py``
   / ``fluid_balance.py`` / ``oxygenation.py`` / ``pre_analytical.py``
   are all separate files with citation-carrying docstrings).

2. **Qualitative-test result distributions** — the four
   ``rng.choice(options, p=weights)`` call-sites inside
   ``_generate_qualitative_result`` used bare list literals for both the
   option strings and their probability weights. Extracting them to
   frozen dataclass instances makes the distribution shape grep-able by
   symbol and prevents accidental option ↔ weight misalignment (a bare
   list-pair has no compile-time length check).

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. All
``rng.choice(options, p=weights)`` calls continue to receive the exact
same option order + weight vector; numpy's sampling is deterministic
modulo those inputs.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DEFAULT_ANALYTICAL_CV",
    "DEFAULT_BIOLOGICAL_CV",
    "RAPID_STREP_RESULT_DIST",
    "TETANUS_STATUS_RESULT_DIST",
    "URINALYSIS_RESULT_DIST",
    "URINE_CULTURE_RESULT_DIST",
    "QualitativeResultDistribution",
]


# ---------------------------------------------------------------------------
# CV fallbacks — used by apply_realistic_variability when the lab name is
# not present in BIOLOGICAL_CV / ANALYTICAL_CV (both defined in engine.py).
# ---------------------------------------------------------------------------

DEFAULT_BIOLOGICAL_CV: float = 0.05
"""Fallback biological (within-individual) coefficient of variation.

Consumed by ``apply_realistic_variability`` as the last-resort CV when a
lab name is not enumerated in the per-analyte ``BIOLOGICAL_CV`` map.
5 % is a reasonable centre of the published Ricos et al. within-subject
CV distribution across the common general-chemistry / hematology
analytes — most enumerated entries fall in the 1-8 % band, so a
fallback in the middle keeps unknown analytes from getting either
under- or over-estimated noise.
"""

DEFAULT_ANALYTICAL_CV: float = 0.03
"""Fallback analytical (instrument / method) coefficient of variation.

Consumed by ``apply_realistic_variability`` as the last-resort CV when a
lab name is not enumerated in the per-analyte ``ANALYTICAL_CV`` map.
3 % matches the CLSI / ISO 15189 acceptable-performance target for
routine clinical-chemistry assays (electrolytes, general chemistries),
which is the analyte class most likely to hit this fallback in
practice.
"""


# ---------------------------------------------------------------------------
# Qualitative-test result distributions — one per test whose result is a
# categorical string rather than a numeric measurement.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QualitativeResultDistribution:
    """One qualitative test's result options + sampling probabilities.

    ``options`` and ``weights`` are aligned by position and MUST have the
    same length. ``__post_init__`` enforces alignment + weight-sum ==
    1.0 at import time so a typo in either tuple fails loudly rather
    than silently redistributing the cohort.
    """

    options: tuple[str, ...]
    weights: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.options) != len(self.weights):
            raise ValueError(
                f"QualitativeResultDistribution: len(options) ({len(self.options)}) "
                f"!= len(weights) ({len(self.weights)})"
            )
        total = sum(self.weights)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"QualitativeResultDistribution: weights sum to {total}, expected 1.0. "
                f"options={self.options} weights={self.weights}"
            )


URINALYSIS_RESULT_DIST = QualitativeResultDistribution(
    options=(
        "Normal",
        "Trace protein",
        "1+ protein",
        "Trace blood",
        "1+ leukocytes",
        "Glucose 1+",
    ),
    weights=(0.55, 0.10, 0.05, 0.10, 0.15, 0.05),
)
"""Dipstick urinalysis qualitative result distribution.

Empirical tuning for the synthetic simulator: the "Normal" mode at
0.55 reflects that most inpatient / outpatient dipsticks in a general
adult cohort are unremarkable; the mild-protein and mild-leukocyte
tails capture the most common abnormal patterns clinicians actually
see on routine screening. Adjust the mode / tails only alongside a
cohort re-generation."""


URINE_CULTURE_RESULT_DIST = QualitativeResultDistribution(
    options=(
        "No growth",
        "Mixed flora (contaminated)",
        "E. coli >100,000 CFU/mL",
        "Klebsiella >100,000 CFU/mL",
    ),
    weights=(0.55, 0.20, 0.20, 0.05),
)
"""Urine-culture qualitative result distribution.

Empirical tuning: the E. coli-dominant uropathogen distribution +
mixed-flora contamination artefact mirror what a hospital microbiology
lab reports in aggregate for community-onset UTI plus reflex-cultured
asymptomatic bacteriuria specimens. Real institution-specific rates
vary; this vector is chosen to keep downstream microbiology + FHIR
DiagnosticReport paths exercised."""


RAPID_STREP_RESULT_DIST = QualitativeResultDistribution(
    options=("Negative", "Positive"),
    weights=(0.85, 0.15),
)
"""Rapid-strep antigen test qualitative result distribution.

Empirical tuning: the 15 % positivity rate is a reasonable centre for
the adult pharyngitis presentations seen in an urgent-care / ED
context (published rates span 10-25 % depending on season + cohort).
Adjustments here shift downstream antibiotic-prescription patterns."""


TETANUS_STATUS_RESULT_DIST = QualitativeResultDistribution(
    options=("Up to date", "Unknown", "Last >10 years ago"),
    weights=(0.55, 0.30, 0.15),
)
"""Tetanus-immunization status distribution.

Empirical tuning: adult tetanus-vaccination coverage in real
populations sits in the 55-70 % "up-to-date" band with a large
"unknown" tail because self-reported / chart-reviewed status is
frequently missing. This distribution feeds the ED / wound-care
pathway's Tdap-booster decision logic."""
