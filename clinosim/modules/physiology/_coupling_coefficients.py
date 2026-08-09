"""Chronic-condition → physiology-state coupling coefficients (Issue #637 PR-B).

Every chronic condition mapped in ``initialize_state`` (engine.py) applies a
severity-scaled multiplicative or additive shift to one or more baseline
physiology-state axes (``renal_function`` / ``cardiac_function`` /
``hepatic_function`` / ``ph_status`` / ``sodium_status`` / ``coagulation_status``
/ ``anemia_level`` / ``volume_status``). The coefficients below are the
tuning knobs the modeler picked so that a patient with a given ICD-10 code
at severity ``s`` lands in a clinically defensible neighbourhood on those
axes at admission time — they are NOT drawn from any single clinical
guideline. The docstring on each constant records the axis it shifts, the
formula, and the clinical rationale (or the honest label of "empirical
tuning for the synthetic simulator" per §5).

Grouping convention: coefficients are grouped by ICD-10 root — one section
per chronic-condition family ``initialize_state`` handles today. Adding a
new chronic-condition branch to ``initialize_state`` requires a matching
section here plus an update to the ``__all__`` block below.

All values are floats in the closed interval ``[0.0, 1.0]`` (or a
severity-threshold in the same interval); no clinical constant here is a
count / integer / seed. The rare special cases (e.g. the fixed 0.15
anemia bump for severe CKD) are documented in-line on their constant.

Byte-diff verification: replacing each inline literal in
``initialize_state`` with the matching constant here MUST NOT change any
numeric output. Reordering, renaming, or adjusting the constants requires
a fresh golden-cohort byte-diff (Issue #637 acceptance criterion).
"""

from __future__ import annotations

__all__ = [
    # N18 CKD
    "CKD_RENAL_COUPLING",
    "CKD_SEVERE_THRESHOLD",
    "CKD_SEVERE_ANEMIA_BUMP",
    "CKD_SEVERE_PH_COUPLING",
    # I50 Heart failure
    "HF_CARDIAC_COUPLING",
    "HF_SEVERE_THRESHOLD",
    "HF_SEVERE_VOLUME_COUPLING",
    "HF_SODIUM_COUPLING",
    # K74 Cirrhosis
    "CIRRHOSIS_HEPATIC_COUPLING",
    "CIRRHOSIS_COAGULATION_COUPLING",
    "CIRRHOSIS_SODIUM_COUPLING",
    # J44 COPD
    "COPD_PH_COUPLING",
    # I25 Ischemic heart disease
    "IHD_CARDIAC_COUPLING",
    # I48 Atrial fibrillation
    "AFIB_CARDIAC_COUPLING",
    # J45 Asthma
    "ASTHMA_PH_COUPLING",
]


# ---------------------------------------------------------------------------
# N18: Chronic kidney disease
# ---------------------------------------------------------------------------

CKD_RENAL_COUPLING: float = 0.9
"""Multiplicative renal-function shift per unit severity for CKD (N18).

``renal_function *= 1.0 - severity_score * CKD_RENAL_COUPLING``.

The 0.9 coefficient (not 0.5) is deliberate: ``severity_score`` tracks the
sampled KDIGO G1-G5 stage (see ``modules/patient/activator.py``), so severe
stages (G4 / G5, ``s >= 0.7``) must be able to push ``renal_function`` down
near its 0.05 floor. A 0.5 coefficient could only ever halve
``renal_reserve``, capping generated serum creatinine at a G3-equivalent
level regardless of the sampled stage (2026-06-20 realism audit finding).
"""

CKD_SEVERE_THRESHOLD: float = 0.5
"""Severity-score cutoff above which secondary CKD effects fire (anemia
of chronic kidney disease + metabolic acidosis).

Empirical tuning for the synthetic simulator: aligned to the clinical
observation that anemia of CKD and mild metabolic acidosis start becoming
prevalent at KDIGO G3b (eGFR < 45), which the activator maps to severity
scores in the upper half of the ``[0, 1]`` range.
"""

CKD_SEVERE_ANEMIA_BUMP: float = 0.15
"""Fixed additive lift to ``anemia_level`` for severe CKD (``s > 0.5``).

``anemia_level += CKD_SEVERE_ANEMIA_BUMP``. Constant (not
severity-scaled) because it represents the anemia-of-CKD prevalence
"kick-in" once erythropoietin production falls off in G3b+ disease.
Empirical tuning to keep post-lift Hb values in the mild-moderate anemia
band on downstream CBC derivation.
"""

CKD_SEVERE_PH_COUPLING: float = 0.1
"""Severity-scaled ``ph_status`` shift for severe CKD (``s > 0.5``).

``ph_status -= severity_score * CKD_SEVERE_PH_COUPLING``. Reflects
metabolic acidosis from impaired H+ / HCO3- excretion; small coefficient
because the resulting acidosis is chronic and compensated in most stable
CKD outpatients (KDIGO 2012 § 3, "acid-base balance").
"""


# ---------------------------------------------------------------------------
# I50: Heart failure (systolic or preserved EF; CIF does not distinguish)
# ---------------------------------------------------------------------------

HF_CARDIAC_COUPLING: float = 0.4
"""Multiplicative cardiac-function shift per unit severity for heart failure.

``cardiac_function *= 1.0 - severity_score * HF_CARDIAC_COUPLING``.
Empirical tuning to hit clinically-plausible EF proxies across the severity
range: mild HF (``s ~= 0.3``) → ~88 % of baseline cardiac reserve; severe
HF (``s ~= 0.8``) → ~68 %. Downstream this drives BNP / NT-proBNP,
perfusion, and lactate.
"""

HF_SEVERE_THRESHOLD: float = 0.3
"""Severity-score cutoff above which HF starts driving volume overload
(``volume_status`` positive shift).

Empirical: below this cutoff the patient sits in a compensated state
(diuretic-managed); above it the model routes them into fluid overload
territory that shows up as elevated venous pressure and dilutional
hyponatremia at the labs.
"""

HF_SEVERE_VOLUME_COUPLING: float = 0.3
"""Severity-scaled ``volume_status`` shift for severe HF (``s > 0.3``).

``volume_status += severity_score * HF_SEVERE_VOLUME_COUPLING``. Same
numerical value as the severity threshold above, but a distinct semantic
role — do not collapse them into one symbol.
"""

HF_SODIUM_COUPLING: float = 0.30
"""Severity-scaled ``sodium_status`` shift for HF (dilutional hyponatremia).

``sodium_status -= severity_score * HF_SODIUM_COUPLING``. Reflects the
low-Na state seen in advanced HF from ADH-mediated free-water retention;
paired with ``CIRRHOSIS_SODIUM_COUPLING`` below (both drive the same axis
but from different mechanisms).
"""


# ---------------------------------------------------------------------------
# K74: Hepatic cirrhosis
# ---------------------------------------------------------------------------

CIRRHOSIS_HEPATIC_COUPLING: float = 0.5
"""Multiplicative hepatic-function shift per unit severity for cirrhosis.

``hepatic_function *= 1.0 - severity_score * CIRRHOSIS_HEPATIC_COUPLING``.
Empirical: sits between the CKD-renal (0.9) and HF-cardiac (0.4)
coefficients — cirrhosis reserves fall off more slowly than nephron loss
but faster than compensated cardiomyopathy on this simulator's scale.
Downstream drives INR (via hepatic synthetic function), albumin, and
bilirubin.
"""

CIRRHOSIS_COAGULATION_COUPLING: float = 0.2
"""Severity-scaled coagulation-status shift for cirrhosis.

``coagulation_status += severity_score * CIRRHOSIS_COAGULATION_COUPLING``.
Reflects the reduced synthesis of coagulation factors II / VII / IX / X
in advanced cirrhosis; small coefficient because the model uses
``coagulation_status`` as a normalized 0..1 proxy that couples multiple
axes downstream (INR, platelets, DIC risk).
"""

CIRRHOSIS_SODIUM_COUPLING: float = 0.40
"""Severity-scaled ``sodium_status`` shift for cirrhosis (dilutional
hyponatremia).

``sodium_status -= severity_score * CIRRHOSIS_SODIUM_COUPLING``. Larger
than the HF coefficient because portal hypertension + splanchnic
vasodilation → non-osmotic ADH release is a more predictable path to
hyponatremia than the HF mechanism at matched severity.
"""


# ---------------------------------------------------------------------------
# J44: Chronic obstructive pulmonary disease
# ---------------------------------------------------------------------------

COPD_PH_COUPLING: float = 0.05
"""Severity-scaled ``ph_status`` shift for COPD (chronic CO2 retention).

``ph_status -= severity_score * COPD_PH_COUPLING``. Small because most
COPD patients are metabolically compensated (elevated HCO3-); acute
exacerbations that acutely lower pH are handled separately in the
disease-course engine, not at initialization.
"""


# ---------------------------------------------------------------------------
# I25: Ischemic heart disease
# ---------------------------------------------------------------------------

IHD_CARDIAC_COUPLING: float = 0.2
"""Multiplicative cardiac-function shift per unit severity for IHD (I25).

``cardiac_function *= 1.0 - severity_score * IHD_CARDIAC_COUPLING``.
Lower than the HF coefficient because stable ischemic disease alone
(without an HF diagnosis) reduces reserve less than symptomatic HF at
matched severity.
"""


# ---------------------------------------------------------------------------
# I48: Atrial fibrillation
# ---------------------------------------------------------------------------

AFIB_CARDIAC_COUPLING: float = 0.1
"""Multiplicative cardiac-function shift per unit severity for AF (I48).

``cardiac_function *= 1.0 - severity_score * AFIB_CARDIAC_COUPLING``.
Smallest of the cardiac coefficients because rate-controlled paroxysmal
or persistent AF alone (no HF, no valve disease) has minimal impact on
resting cardiac output. The model captures the residual reserve loss
without conflating it with HF.
"""


# ---------------------------------------------------------------------------
# J45: Asthma
# ---------------------------------------------------------------------------

ASTHMA_PH_COUPLING: float = 0.02
"""Severity-scaled ``ph_status`` shift for asthma.

``ph_status -= severity_score * ASTHMA_PH_COUPLING``. Very small because
most stable asthma patients are eucapnic between exacerbations; the
downstream ``respiratory_fraction = 1.0`` assignment carries the
respiratory-axis effect, this coefficient just adds the residual mild
metabolic drift the physiology model expects.
"""
