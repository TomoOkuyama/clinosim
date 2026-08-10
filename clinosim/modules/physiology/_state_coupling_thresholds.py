"""State-variable coupling-rule thresholds (Issue #637).

Companion to :mod:`clinosim.modules.physiology._coupling_coefficients`
(which covers per-chronic-condition state-initialization coefficients):
this file lifts the previously-inline scalars from
:func:`clinosim.modules.physiology.engine.apply_coupling_rules`, which
runs each simulation day to enforce the physiological couplings between
state variables (perfusion depends on cardiac + volume; renal depends
on perfusion; pH depends on renal + perfusion; coagulation worsens
with severe inflammation and hepatic dysfunction; anemia tracks chronic
inflammation; hypernatremia tracks dehydration).

Every constant reflects a coupling coefficient in a physiology formula
— clinically motivated but empirical in exact magnitude.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any state trajectory. The couplings are
deterministic algebra (no RNG), so byte-identity at the pinned seed
is guaranteed as long as arithmetic order is preserved.
"""

from __future__ import annotations

__all__ = [
    "COAG_DIC_INFLAMMATION_SCALE",
    "COAG_DIC_INFLAMMATION_THRESHOLD",
    "COAG_HEPATIC_DYSFUNCTION_SCALE",
    "COAG_HEPATIC_DYSFUNCTION_THRESHOLD",
    "COUPLING_ANEMIA_ACTIVE_MIN",
    "COUPLING_ANEMIA_INFLAMMATION_RESOLVING_THRESHOLD",
    "COUPLING_ANEMIA_INFLAMMATION_THRESHOLD",
    "COUPLING_ANEMIA_INFLAMMATION_SCALE",
    "COUPLING_ANEMIA_RECOVERY_RATE",
    "HYPERNATREMIA_SODIUM_SCALE",
    "PH_COMBINED_ACID_SCALE",
    "PH_LACTIC_ACID_PERFUSION_SCALE",
    "PH_LACTIC_ACID_PERFUSION_THRESHOLD",
    "PH_RENAL_ACID_RENAL_SCALE",
    "PH_RENAL_ACID_RENAL_THRESHOLD",
    "PERFUSION_CARDIAC_BASE_OFFSET",
    "PERFUSION_CARDIAC_SCALE",
    "PRERENAL_HIT_PERFUSION_SCALE",
    "PRERENAL_HIT_PERFUSION_THRESHOLD",
    "RENAL_FUNCTION_FLOOR",
    "VOLUME_HYPERVOLEMIA_CARDIAC_DYSFUNCTION_THRESHOLD",
    "VOLUME_HYPERVOLEMIA_PERFUSION_PENALTY",
    "VOLUME_HYPERVOLEMIA_THRESHOLD",
    "VOLUME_HYPOVOLEMIA_PERFUSION_SCALE",
    "VOLUME_HYPOVOLEMIA_THRESHOLD",
]


# ---------------------------------------------------------------------------
# Volume → perfusion coupling
# ---------------------------------------------------------------------------

VOLUME_HYPOVOLEMIA_THRESHOLD: float = -0.5
"""``volume_status`` at or below (strictly below) which hypovolemia
starts penalizing perfusion linearly."""

VOLUME_HYPOVOLEMIA_PERFUSION_SCALE: float = 0.3
"""Scaling factor for the hypovolemia perfusion penalty
(``volume_effect = volume_status * scale``, which is negative when
volume_status is negative)."""

VOLUME_HYPERVOLEMIA_THRESHOLD: float = 0.5
"""``volume_status`` strictly above which the hypervolemia + cardiac-
dysfunction combined penalty may fire."""

VOLUME_HYPERVOLEMIA_CARDIAC_DYSFUNCTION_THRESHOLD: float = 0.5
"""``cardiac_function`` strictly below which the hypervolemia perfusion
penalty fires (only when volume is also above
:data:`VOLUME_HYPERVOLEMIA_THRESHOLD`).

Empirical tuning for the synthetic simulator: models the CHF exacerbation
scenario — a good heart can handle fluid overload, but a struggling
heart + volume overload = pulmonary edema + poor forward flow."""

VOLUME_HYPERVOLEMIA_PERFUSION_PENALTY: float = -0.1
"""Fixed perfusion penalty (negative offset) applied when both
hypervolemia and cardiac dysfunction are present."""


# ---------------------------------------------------------------------------
# Cardiac + volume → perfusion baseline formula
# ---------------------------------------------------------------------------

PERFUSION_CARDIAC_SCALE: float = 0.8
"""Cardiac-function → perfusion scaling factor.

``perfusion = clamp(cardiac_function * PERFUSION_CARDIAC_SCALE +
PERFUSION_CARDIAC_BASE_OFFSET + volume_effect, 0, 1)``."""

PERFUSION_CARDIAC_BASE_OFFSET: float = 0.2
"""Additive baseline offset in the perfusion formula.

Empirical tuning for the synthetic simulator: 0.8 + 0.2 = 1.0 at
``cardiac_function == 1.0`` with no volume effect — patients with
normal cardiac function have baseline perfusion at the ceiling."""


# ---------------------------------------------------------------------------
# Perfusion → renal (pre-renal AKI) coupling
# ---------------------------------------------------------------------------

PRERENAL_HIT_PERFUSION_THRESHOLD: float = 0.5
"""``perfusion_status`` strictly below which pre-renal renal decline
begins accumulating."""

PRERENAL_HIT_PERFUSION_SCALE: float = 0.3
"""Scaling factor for the pre-renal hit:
``hit = (0.5 - perfusion) * scale``."""

RENAL_FUNCTION_FLOOR: float = 0.05
"""Minimum ``renal_function`` value after applying pre-renal hits.

Empirical tuning for the synthetic simulator: 0.05 (5 %) prevents
pre-renal decline from producing zero renal function in a single day,
even in extreme shock — matches the observation that acute kidney
injury still preserves some baseline nephron activity."""


# ---------------------------------------------------------------------------
# Renal + perfusion → pH coupling (metabolic acidosis)
# ---------------------------------------------------------------------------

PH_RENAL_ACID_RENAL_THRESHOLD: float = 0.3
"""``renal_function`` strictly below which renal-origin acid retention
starts contributing to the pH shift."""

PH_RENAL_ACID_RENAL_SCALE: float = 0.5
"""Scaling factor for renal-origin acid retention:
``renal_acid = -(0.3 - renal) * scale``.

Empirical tuning for the synthetic simulator: at renal_function = 0
(anuric), renal_acid = -0.3 * 0.5 = -0.15, which after the combined
scale gives -0.015 pH shift/day — a plausible metabolic acidosis
accumulation rate."""

PH_LACTIC_ACID_PERFUSION_THRESHOLD: float = 0.4
"""``perfusion_status`` strictly below which lactic acidosis begins
contributing to the pH shift."""

PH_LACTIC_ACID_PERFUSION_SCALE: float = 0.6
"""Scaling factor for lactic-acidosis pH contribution:
``lactic_acid = -(0.4 - perfusion) * scale``."""

PH_COMBINED_ACID_SCALE: float = 0.1
"""Combined pH-shift dampening factor.

``ph_shift = (renal_acid + lactic_acid) * PH_COMBINED_ACID_SCALE``

Empirical tuning for the synthetic simulator: 0.1 caps the daily pH
drift to plausible values (max ~0.03/day at extreme physiology)."""


# ---------------------------------------------------------------------------
# Inflammation + hepatic → coagulation coupling
# ---------------------------------------------------------------------------

COAG_DIC_INFLAMMATION_THRESHOLD: float = 0.7
"""``inflammation_level`` strictly above which DIC-like coagulopathy
begins accumulating."""

COAG_DIC_INFLAMMATION_SCALE: float = 0.15
"""Scaling factor for DIC-like coagulopathy accumulation:
``dic = (inflammation - 0.7) * scale``.

Empirical tuning for the synthetic simulator: matches the sepsis-DIC
progression seen in severe sepsis patients (inflammation → cytokine
storm → coagulation cascade activation)."""

COAG_HEPATIC_DYSFUNCTION_THRESHOLD: float = 0.4
"""``hepatic_function`` strictly below which hepatic-origin
coagulopathy begins accumulating (deficient clotting-factor synthesis)."""

COAG_HEPATIC_DYSFUNCTION_SCALE: float = 0.1
"""Scaling factor for hepatic-origin coagulopathy:
``coagulation += (0.4 - hepatic_function) * scale``."""


# ---------------------------------------------------------------------------
# Inflammation → anemia coupling (chronic anemia of inflammation)
# ---------------------------------------------------------------------------

COUPLING_ANEMIA_INFLAMMATION_THRESHOLD: float = 0.5
"""``inflammation_level`` strictly above which chronic inflammation
starts producing anemia."""

COUPLING_ANEMIA_INFLAMMATION_SCALE: float = 0.005
"""Slow scaling factor for anemia-of-chronic-inflammation
accumulation: ``anemia += (inflammation - 0.5) * scale``.

Empirical tuning for the synthetic simulator: 0.005/day is
deliberately slow — anemia of chronic inflammation takes weeks to
manifest, so per-day accumulation must be small."""

COUPLING_ANEMIA_INFLAMMATION_RESOLVING_THRESHOLD: float = 0.2
"""``inflammation_level`` strictly below which resolving inflammation
allows bone-marrow anemia to recover (paired with the active-anemia
guard below)."""

COUPLING_ANEMIA_ACTIVE_MIN: float = 0.05
"""``anemia_level`` strictly above which the recovery branch fires —
skips the recovery step when anemia is already at its baseline."""

COUPLING_ANEMIA_RECOVERY_RATE: float = 0.005
"""Per-day anemia-recovery rate applied when inflammation resolves
(the negative side of :data:`COUPLING_ANEMIA_INFLAMMATION_SCALE`)."""


# ---------------------------------------------------------------------------
# Volume → sodium coupling (hypernatremia in dehydration)
# ---------------------------------------------------------------------------

HYPERNATREMIA_SODIUM_SCALE: float = 1.2
"""Scaling factor for volume-driven sodium shifts:
``sodium_shift = (|volume| - |HYPERNATREMIA_THRESHOLD|) * scale``.

The ``HYPERNATREMIA_THRESHOLD`` constant itself is imported from
``clinosim.modules.physiology.dehydration_thresholds`` — this file
covers only the coupling scale."""
