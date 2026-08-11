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
    "DOB_DAY_MAX_EXCLUSIVE",
    "DOB_DAY_MIN",
    "HOUSEHOLD_LANDLINE_PROBABILITY_DEFAULT",
    "HOUSEHOLD_SIZE_WEIGHTED_CHOICES",
    "JP_ADDRESS_APARTMENT_PROBABILITY_DEFAULT",
    "JP_ADDRESS_APARTMENT_ROOM_MAX_EXCLUSIVE",
    "JP_ADDRESS_APARTMENT_ROOM_MIN",
    "JP_ADDRESS_BANCHI_MAX_EXCLUSIVE",
    "JP_ADDRESS_BANCHI_MIN",
    "JP_ADDRESS_CHOME_MAX_EXCLUSIVE",
    "JP_ADDRESS_CHOME_MIN",
    "JP_ADDRESS_GO_MAX_EXCLUSIVE",
    "JP_ADDRESS_GO_MIN",
    "JP_PHONE_LANDLINE_NON_TOKYO_EXCHANGE_MAX_EXCLUSIVE",
    "JP_PHONE_LANDLINE_NON_TOKYO_EXCHANGE_MIN",
    "PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE",
    "PHONE_4DIGIT_BLOCK_MIN",
    "SEX_RATIO_MALE_DEFAULT",
    "US_ADDRESS_APARTMENT_NUMBER_MAX_EXCLUSIVE",
    "US_ADDRESS_APARTMENT_NUMBER_MIN",
    "US_ADDRESS_APARTMENT_PROBABILITY_DEFAULT",
    "US_ADDRESS_STREET_NUMBER_MAX_EXCLUSIVE",
    "US_ADDRESS_STREET_NUMBER_MIN",
    "US_PHONE_EXCHANGE_MAX_EXCLUSIVE",
    "US_PHONE_EXCHANGE_MIN",
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
# JP address generation ranges
# ---------------------------------------------------------------------------

JP_ADDRESS_CHOME_MIN: int = 1
"""Minimum 丁目 (chome, ward-block) number sampled by ``rng.integers``."""

JP_ADDRESS_CHOME_MAX_EXCLUSIVE: int = 6
"""Exclusive maximum 丁目 number — samples 1-5.

Empirical tuning for the synthetic simulator: most Japanese city wards
are subdivided into 1-5 chome; larger cities go higher but the 1-5
range captures the typical middle-density urban address."""

JP_ADDRESS_BANCHI_MIN: int = 1
"""Minimum 番地 (banchi, block) number sampled by ``rng.integers``."""

JP_ADDRESS_BANCHI_MAX_EXCLUSIVE: int = 30
"""Exclusive maximum 番地 number — samples 1-29.

Empirical tuning for the synthetic simulator: 1-29 covers typical
Japanese block numbering (larger blocks would go higher, but 30 is a
reasonable cap for the ordinary residential density modeled here)."""

JP_ADDRESS_GO_MIN: int = 1
"""Minimum 号 (go, building) number sampled by ``rng.integers``."""

JP_ADDRESS_GO_MAX_EXCLUSIVE: int = 15
"""Exclusive maximum 号 number — samples 1-14.

Empirical tuning for the synthetic simulator: 1-14 covers typical
building numbering within a 番地; the smaller range vs banchi reflects
the finer subdivision at this level."""

JP_ADDRESS_APARTMENT_PROBABILITY_DEFAULT: float = 0.6
"""Fallback probability that a JP address includes an apartment /
マンション suffix when ``addresses.yaml`` does not provide
``apartment_probability``.

Empirical tuning for the synthetic simulator: 60% reflects the
urban-Japan apartment/マンション prevalence — the majority of urban
residents live in multi-unit dwellings."""


# ---------------------------------------------------------------------------
# US address generation ranges
# ---------------------------------------------------------------------------

US_ADDRESS_STREET_NUMBER_MIN: int = 1
"""Minimum US street number sampled by ``rng.integers``."""

US_ADDRESS_STREET_NUMBER_MAX_EXCLUSIVE: int = 500
"""Exclusive maximum US street number — samples 1-499.

Empirical tuning for the synthetic simulator: 1-499 covers small-town
and suburban residential address ranges; larger urban addresses can
exceed this, but the range is representative of typical mixed-density
US neighborhoods."""

US_ADDRESS_APARTMENT_PROBABILITY_DEFAULT: float = 0.35
"""Fallback probability that a US address includes an apartment number
when ``addresses.yaml`` does not provide ``apartment_probability``.

Empirical tuning for the synthetic simulator: 35% reflects the US
apartment-vs-single-family prevalence — lower than JP (60%) because
US residential mix leans more single-family."""

US_ADDRESS_APARTMENT_NUMBER_MIN: int = 1
"""Minimum US apartment number sampled by ``rng.integers``."""

US_ADDRESS_APARTMENT_NUMBER_MAX_EXCLUSIVE: int = 13
"""Exclusive maximum US apartment number — samples 1-12.

Empirical tuning for the synthetic simulator: 1-12 covers small
multi-unit dwellings (duplex through small apartment building);
larger apartment complexes would extend this range but 12 is a
reasonable cap for the typical density modeled."""


# ---------------------------------------------------------------------------
# Date-of-birth day-of-month generation
# ---------------------------------------------------------------------------

DOB_DAY_MIN: int = 1
"""Inclusive lower bound of the DOB day-of-month draw in
:func:`clinosim.modules.population.engine.generate_population`."""

DOB_DAY_MAX_EXCLUSIVE: int = 29
"""Exclusive upper bound of the DOB day-of-month draw. Combined with
:data:`DOB_DAY_MIN` yields days 1-28 — deliberately capped at 28 so a
February birthdate never trips ``ValueError: day is out of range for
month`` even in a non-leap year."""


# ---------------------------------------------------------------------------
# JP address apartment room numbers (floor.room concatenation)
# ---------------------------------------------------------------------------

JP_ADDRESS_APARTMENT_ROOM_MIN: int = 101
"""Inclusive lower bound of the JP apartment room-number draw.

The synthetic room number is a floor-then-room concatenation
(``101`` = 1st floor room 01), so the min 101 yields 1F rooms.
Empirical tuning for the synthetic simulator."""

JP_ADDRESS_APARTMENT_ROOM_MAX_EXCLUSIVE: int = 1205
"""Exclusive upper bound of the JP apartment room-number draw —
yields rooms up through 12F room 04. Skips the top-of-building
digits to keep the generated addresses inside a plausible mid-rise
apartment layout."""


# ---------------------------------------------------------------------------
# Phone-number 4-digit block + exchange ranges (shared across JP + US)
# ---------------------------------------------------------------------------

PHONE_4DIGIT_BLOCK_MIN: int = 1000
"""Inclusive lower bound of a 4-digit phone-number block draw. Shared
across JP mobile (090-XXXX-YYYY), JP landline 03 (03-XXXX-YYYY), JP
landline non-Tokyo line portion, and US phone line portion."""

PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE: int = 9999
"""Exclusive upper bound of a 4-digit phone-number block draw
(``rng.integers`` treats ``high`` as exclusive) — yields 1000-9998."""

JP_PHONE_LANDLINE_NON_TOKYO_EXCHANGE_MIN: int = 100
"""Inclusive lower bound of the JP non-Tokyo landline exchange
(``0XX-XXX-YYYY`` format, where the middle 3 digits are the
exchange). 100 is the NTT-allocated minimum for regional exchanges."""

JP_PHONE_LANDLINE_NON_TOKYO_EXCHANGE_MAX_EXCLUSIVE: int = 999
"""Exclusive upper bound of the JP non-Tokyo landline exchange."""

US_PHONE_EXCHANGE_MIN: int = 200
"""Inclusive lower bound of the US phone-number 3-digit exchange /
NPA middle portion. 200 is the NANP-allocated minimum (exchanges
never start with 0 or 1)."""

US_PHONE_EXCHANGE_MAX_EXCLUSIVE: int = 999
"""Exclusive upper bound of the US phone-number exchange."""
