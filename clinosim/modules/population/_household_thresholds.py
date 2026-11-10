"""Household-composition and address defaults (Issue #637).

Completes the ``clinosim/modules/population/engine.py`` extraction
started by PR #679 (demographic sampling defaults) and PR #684
(monthly-event + healthcare-calendar workflow thresholds). This file
covers the residual household-setup defaults used in
``generate_population`` and the address-generation helpers.

Every scalar here fires only when the ``demographics.yaml`` /
``naming.yaml`` / ``address.yaml`` locale files omit the corresponding
key, so the constants are fallbacks rather than authoritative values.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.random`` /
``rng.choice`` / ``rng.integers`` consume identical bytes whether the
arguments come from literals or module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "AVG_HOUSEHOLD_SIZE_DEFAULT",
    "BLOOD_TYPE_DEFAULT_DISTRIBUTION",
    "HOUSEHOLD_LANDLINE_PROBABILITY_DEFAULT",
    "HOUSEHOLD_SIZE_WEIGHTED_CHOICES",
    "SEX_RATIO_MALE_DEFAULT",
    "WIFE_KEEPS_MAIDEN_PROBABILITY_DEFAULT",
]


# ---------------------------------------------------------------------------
# Household composition
# ---------------------------------------------------------------------------

AVG_HOUSEHOLD_SIZE_DEFAULT: float = 2.5
"""Fallback average household size when ``demographics.yaml`` does not
provide ``average_household_size``.

2.5 approximates the OECD adult-household average (US 2.5, JP 2.3,
UK 2.4); the value drives the ``n_households = size / avg`` bulk sizing
in ``generate_population``."""

HOUSEHOLD_LANDLINE_PROBABILITY_DEFAULT: float = 0.5
"""Fallback probability that a household has a landline when
``addresses.yaml`` does not provide
``contact_rules.household_has_landline_probability``.

Empirical tuning for the synthetic simulator: 50% approximates the
mid-2020s US mixed-generation household landline penetration; JP
locale YAML overrides with a higher value reflecting stronger
landline persistence."""

HOUSEHOLD_SIZE_WEIGHTED_CHOICES: tuple[int, int, int, int, int, int] = (1, 2, 2, 3, 3, 4)
"""Weighted-choice pool for household member counts, sampled uniformly
by ``rng.choice`` (no explicit weights — the doubled 2/3 entries act
as the weighting).

Empirical tuning for the synthetic simulator: (1, 2, 2, 3, 3, 4)
gives probabilities 1/6, 2/6, 2/6, 1/6 for sizes 1, 2, 3, 4
respectively — approximating US / JP household-size distributions
(single & couple dominant, small family common, larger family rare).
The observed mean (1+2+2+3+3+4)/6 = 2.5 also matches
:data:`AVG_HOUSEHOLD_SIZE_DEFAULT`."""


# ---------------------------------------------------------------------------
# Demographic proportions
# ---------------------------------------------------------------------------

SEX_RATIO_MALE_DEFAULT: float = 0.49
"""Fallback male proportion when ``demographics.yaml`` does not provide
``sex_ratio.male``.

49% male / 51% female matches the observed adult-population sex ratio
in both US and JP national statistics (slight female skew driven by
older-cohort mortality differences)."""

WIFE_KEEPS_MAIDEN_PROBABILITY_DEFAULT: float = 0.20
"""Fallback probability that a spouse (member index 1, sex F) keeps
their maiden surname when the naming rule is ``mostly_shared``, if
``naming.yaml`` does not provide ``wife_keeps_maiden_probability``.

Empirical tuning for the synthetic simulator: 20% approximates the
US married-women-keep-maiden-name rate; JP locale overrides via
the ``shared`` naming rule (Japanese law until recently required
shared surnames)."""


# ---------------------------------------------------------------------------
# Blood type sampling fallback
# ---------------------------------------------------------------------------

BLOOD_TYPE_DEFAULT_DISTRIBUTION: dict[str, float] = {
    "O": 0.44,
    "A": 0.42,
    "B": 0.10,
    "AB": 0.04,
}
"""Fallback ABO blood-type probability distribution when
``demographics.yaml`` does not provide ``blood_type``.

Values approximate US Caucasian-population blood-type frequencies
(O ~44%, A ~42%, B ~10%, AB ~4%). JP locale overrides with a
different distribution (roughly O ~30%, A ~40%, B ~20%, AB ~10%
in the Japanese reference cohort) — this default fires only for
locales without a YAML entry."""


# ---------------------------------------------------------------------------
# Date-of-birth day-of-month generation
# ---------------------------------------------------------------------------
