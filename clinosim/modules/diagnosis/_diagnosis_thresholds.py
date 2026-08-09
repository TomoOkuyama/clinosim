"""Diagnostic-reasoning thresholds for the Bayesian differential engine
(Issue #637).

The differential-diagnosis engine in ``engine.py`` uses three families
of scalar thresholds when maintaining and progressing a candidate
probability distribution. This module lifts them out of the inline
literals in ``engine.py`` per policy §5 — each threshold gets a name
and a docstring citing its clinical / algorithmic role so the
diagnostic-reasoning tuning surface is grep-able.

Family 1 — **Working- and confirmed-diagnosis probability cutoffs**.
The engine sets ``diff.working_diagnosis`` when the top candidate's
posterior exceeds :data:`WORKING_DIAGNOSIS_MIN_PROB`, and elevates
that to ``diff.confirmed`` when it exceeds
:data:`DEFAULT_CONFIRMATION_THRESHOLD` (also the default for the
``confirmation_threshold`` parameter of ``update_differential``).

Family 2 — **Age-based prior adjustments**. Elderly patients
(``age >= ELDERLY_HF_PRIOR_AGE_THRESHOLD``) get a
:data:`ELDERLY_HF_PRIOR_MULTIPLIER` bump on the heart-failure prior
before the initial differential is normalized. Documents an
epidemiologic reality (HF prevalence rises sharply with age) that
would otherwise be invisible to a reader of ``initialize_differential``.

Family 3 — **Neutral fallbacks for missing LR entries**. When a
finding's LR table is missing an entry for a candidate disease (either
the finding does not discriminate that disease or the LR was never
authored), the engine multiplies the candidate's posterior by
:data:`NEUTRAL_LIKELIHOOD_RATIO` (== 1.0) so the finding has no
Bayesian effect. Extracting the constant makes the neutrality
explicit — an inline ``1.0`` reads like a mistake.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any Bayesian update. Every ``candidate
.probability *= lr`` and ``candidate.probability > 0.5`` retains
its exact arithmetic; no RNG is involved in this module.
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_CONFIRMATION_THRESHOLD",
    "ELDERLY_HF_PRIOR_AGE_THRESHOLD",
    "ELDERLY_HF_PRIOR_MULTIPLIER",
    "NEUTRAL_LIKELIHOOD_RATIO",
    "WORKING_DIAGNOSIS_MIN_PROB",
]


# ---------------------------------------------------------------------------
# Working- and confirmed-diagnosis probability cutoffs
# ---------------------------------------------------------------------------

WORKING_DIAGNOSIS_MIN_PROB: float = 0.5
"""Minimum posterior probability for the top candidate to become the
``diff.working_diagnosis`` (the "presumptive" diagnosis the treatment
pathway acts on, distinct from the confirmed one).

The 0.5 cutoff is the standard "more likely than not" threshold used
in clinical reasoning — below it there is genuine equipoise between
the top candidate and its rivals and the working-diagnosis slot is
left empty (the caller falls back to symptom-directed empirical
management)."""

DEFAULT_CONFIRMATION_THRESHOLD: float = 0.90
"""Default posterior probability at which ``update_differential``
promotes the top candidate to ``diff.confirmed = True``.

0.90 approximates the clinical practice of accepting a "confirmed"
diagnosis when the differential probability is high enough that
further diagnostic workup would not change management. Callers can
override via the ``confirmation_threshold`` parameter."""


# ---------------------------------------------------------------------------
# Age-based prior adjustments
# ---------------------------------------------------------------------------

ELDERLY_HF_PRIOR_AGE_THRESHOLD: int = 75
"""Age (years) at or above which the heart-failure prior is boosted
in ``initialize_differential``.

Reflects the well-established epidemiologic pattern that HF
prevalence rises sharply from the 8th decade onward (Framingham HF
incidence data). Patients under this threshold get the base prior
from the differential list; at or above, the prior is multiplied by
:data:`ELDERLY_HF_PRIOR_MULTIPLIER`."""

ELDERLY_HF_PRIOR_MULTIPLIER: float = 1.5
"""Multiplier applied to the heart-failure prior for patients at or
above :data:`ELDERLY_HF_PRIOR_AGE_THRESHOLD`.

Empirical tuning for the synthetic simulator: 1.5× shifts the initial
differential toward HF for elderly cohorts without dominating the
distribution outright. Applied before normalization, so the exact
weight in the final distribution depends on how many other
candidates the differential carries."""


# ---------------------------------------------------------------------------
# Neutral LR fallback
# ---------------------------------------------------------------------------

NEUTRAL_LIKELIHOOD_RATIO: float = 1.0
"""Likelihood ratio applied when a finding's LR table has no entry
for a given candidate disease.

Multiplication by 1.0 leaves the posterior unchanged — the finding
carries no Bayesian information for this disease. The named constant
makes the neutrality explicit (an inline ``1.0`` in a Bayesian
multiplication reads like a bug or placeholder)."""
