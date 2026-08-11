"""Vital-signs derivation formula constants (Issue #637).

Extracts the previously-inline scalars from
:func:`clinosim.modules.physiology.engine.derive_vital_signs` per
policy §5. Companion to the ``derive_lab_values`` extraction series
(C2a/C2b/C2c/C2d in ``_lab_derivation_thresholds.py``).

The two module-level constants that already lived in engine.py
(``DISTRIBUTIVE_THRESHOLD`` and ``DISTRIBUTIVE_SBP_COEFF``) are moved
here too — they described distributive-shock hypotension, which sits
squarely in vital-signs derivation and belongs in the per-topic file.

Byte-diff verification: the vital-signs formulas are deterministic
algebra (no RNG). Byte-identity at the pinned seed is guaranteed as
long as arithmetic order is preserved, which the constant substitution
does exactly.
"""

from __future__ import annotations

__all__ = [
    "BP_DBP_CLAMP_MAX",
    "BP_DBP_CLAMP_MIN",
    "BP_DBP_DISTRIBUTIVE_RATIO",
    "BP_DBP_PERFUSION_SCALE",
    "BP_DBP_VOLUME_SCALE",
    "BP_SBP_CLAMP_MAX",
    "BP_SBP_CLAMP_MIN",
    "BP_SBP_PERFUSION_SCALE",
    "BP_SBP_VOLUME_SCALE",
    "DISTRIBUTIVE_SBP_COEFF",
    "DISTRIBUTIVE_THRESHOLD",
    "HR_ANEMIA_SCALE",
    "HR_CLAMP_MAX",
    "HR_CLAMP_MIN",
    "HR_FEVER_REFERENCE_TEMP_C",
    "HR_PERFUSION_SCALE",
    "HR_TEMPERATURE_SCALE",
    "OBSERVED_SPO2_CLAMP_MAX",
    "OBSERVED_SPO2_CLAMP_MIN",
    "OBSERVED_TEMPERATURE_NOISE_SD",
    "OBSERVED_VITALS_NOISE_SD_DEFAULT",
    "RR_CLAMP_MAX",
    "RR_CLAMP_MIN",
    "RR_INFLAMMATION_SCALE",
    "RR_PH_ACIDOSIS_SCALE",
    "RR_VOLUME_OVERLOAD_SCALE",
    "RR_VOLUME_OVERLOAD_THRESHOLD",
    "SPO2_CLAMP_MAX",
    "SPO2_CLAMP_MIN",
    "SPO2_INFLAMMATION_SCALE",
    "SPO2_INFLAMMATION_THRESHOLD",
    "SPO2_VOLUME_OVERLOAD_SCALE",
    "SPO2_VOLUME_OVERLOAD_THRESHOLD",
    "TEMPERATURE_CIRCADIAN_HOUR_OFFSET",
    "TEMPERATURE_CIRCADIAN_HOUR_PERIOD",
    "TEMPERATURE_CIRCADIAN_SCALE",
    "TEMPERATURE_CLAMP_MAX",
    "TEMPERATURE_CLAMP_MIN",
    "TEMPERATURE_INFLAMMATION_SCALE",
]


# ---------------------------------------------------------------------------
# Temperature — inflammation lift + circadian variation
# ---------------------------------------------------------------------------

TEMPERATURE_INFLAMMATION_SCALE: float = 3.0
"""°C rise per unit inflammation — at inflammation = 1.0, temperature
lifts by 3°C (37 → 40°C, matching severe febrile response)."""

TEMPERATURE_CIRCADIAN_SCALE: float = 0.3
"""Amplitude (°C) of the circadian temperature variation — matches the
observed 0.5-1.0 °C diurnal range with a 0.3 °C half-amplitude."""

TEMPERATURE_CIRCADIAN_HOUR_OFFSET: int = 4
"""Hour of the day used as the cosine offset in the circadian formula
— places the temperature nadir at ~04:00 (matches the classic
morning-low, afternoon-high circadian pattern)."""

TEMPERATURE_CIRCADIAN_HOUR_PERIOD: int = 12
"""Hour period used as the divisor in the circadian cosine
(``(hour - offset) * π / period``) — 12-hour period matches the
diurnal cycle."""

TEMPERATURE_CLAMP_MIN: float = 35.0
"""Physiologic minimum core temperature (°C) — matches severe
hypothermia floor."""

TEMPERATURE_CLAMP_MAX: float = 42.0
"""Physiologic maximum core temperature (°C) — matches severe
hyperthermia ceiling (heat stroke)."""


# ---------------------------------------------------------------------------
# Heart rate — fever + hypoperfusion + anemia
# ---------------------------------------------------------------------------

HR_FEVER_REFERENCE_TEMP_C: float = 37.0
"""Reference temperature (°C) above which fever-driven tachycardia
starts contributing to heart rate."""

HR_TEMPERATURE_SCALE: int = 10
"""HR lift (bpm per °C above :data:`HR_FEVER_REFERENCE_TEMP_C`).

Empirical tuning for the synthetic simulator: 10 bpm per °C matches
the well-known clinical rule ("~8-10 bpm per °C of fever")."""

HR_PERFUSION_SCALE: int = 40
"""HR lift (bpm per unit ``(1 - perfusion_status)``).

Empirical tuning for the synthetic simulator: 40 bpm at complete
perfusion collapse — matches compensatory tachycardia in septic /
cardiogenic shock."""

HR_ANEMIA_SCALE: int = 15
"""HR lift (bpm per unit ``anemia_level``).

Empirical tuning for the synthetic simulator: 15 bpm at severe anemia
matches the anemia-tachycardia compensatory response."""

HR_CLAMP_MIN: int = 40
"""Physiologic minimum HR (bpm) — matches severe bradycardia floor."""

HR_CLAMP_MAX: int = 180
"""Physiologic maximum HR (bpm) — matches SVT / severe compensatory-
tachycardia ceiling."""


# ---------------------------------------------------------------------------
# Blood pressure — SBP + DBP + distributive-shock overlay
# ---------------------------------------------------------------------------

BP_SBP_VOLUME_SCALE: int = 15
"""SBP lift (mmHg per unit ``volume_status``) — hypervolemia raises
BP, hypovolemia lowers it."""

BP_SBP_PERFUSION_SCALE: int = 40
"""SBP drop (mmHg per unit ``(1 - perfusion_status)``) — matches
cardiogenic-shock BP collapse."""

BP_SBP_CLAMP_MIN: int = 60
"""Physiologic minimum SBP (mmHg) — matches severe hypotension floor
where cardiac output is grossly inadequate."""

BP_SBP_CLAMP_MAX: int = 220
"""Physiologic maximum SBP (mmHg) — matches hypertensive-urgency
ceiling."""

BP_DBP_VOLUME_SCALE: int = 8
"""DBP lift (mmHg per unit ``volume_status``) — smaller than SBP scale
because DBP is less sensitive to volume."""

BP_DBP_PERFUSION_SCALE: int = 20
"""DBP drop (mmHg per unit ``(1 - perfusion_status)``) — smaller
than SBP scale, matching the observed hypoperfusion pulse-pressure
narrowing."""

BP_DBP_DISTRIBUTIVE_RATIO: float = 0.6
"""Ratio of DBP-to-SBP distributive-shock drop.

Empirical tuning for the synthetic simulator: 0.6 matches the
well-documented observation that vasodilatory shock lowers DBP
proportionally less than SBP (wide pulse pressure of early sepsis)."""

BP_DBP_CLAMP_MIN: int = 30
"""Physiologic minimum DBP (mmHg)."""

BP_DBP_CLAMP_MAX: int = 130
"""Physiologic maximum DBP (mmHg)."""

DISTRIBUTIVE_THRESHOLD: float = 0.7
"""``inflammation_level`` strictly above which distributive
(vasodilatory) shock hypotension begins contributing to the
displayed BP.

Applied at vitals-derivation only (does NOT mutate perfusion_status)
so it does not affect the master-RNG cascade downstream. Preserved
from engine.py's pre-extraction module-level constant."""

DISTRIBUTIVE_SBP_COEFF: float = 60.0
"""SBP drop (mmHg per unit ``inflammation`` above
:data:`DISTRIBUTIVE_THRESHOLD`).

Calibrated by generation audit against the "sepsis SBP<90" target
(~15-25% of septic cohort). Preserved from engine.py's pre-extraction
module-level constant."""


# ---------------------------------------------------------------------------
# Respiratory rate — acidosis + inflammation + volume overload
# ---------------------------------------------------------------------------

RR_PH_ACIDOSIS_SCALE: int = 10
"""RR lift (breaths/min per unit acidosis; ``max(0, -ph_status)``).

Empirical tuning for the synthetic simulator: 10 breaths/min at
extreme acidosis models Kussmaul-pattern compensatory
hyperventilation."""

RR_INFLAMMATION_SCALE: int = 4
"""RR lift (breaths/min per unit inflammation) — matches sepsis-
associated tachypnea."""

RR_VOLUME_OVERLOAD_THRESHOLD: float = 0.5
"""``volume_status`` strictly above which volume-overload tachypnea
begins contributing (pulmonary congestion → work of breathing)."""

RR_VOLUME_OVERLOAD_SCALE: int = 8
"""RR lift (breaths/min per unit volume above
:data:`RR_VOLUME_OVERLOAD_THRESHOLD`) — matches CHF-associated
tachypnea."""

RR_CLAMP_MIN: int = 8
"""Physiologic minimum RR (breaths/min) — matches severe respiratory
depression floor."""

RR_CLAMP_MAX: int = 45
"""Physiologic maximum RR (breaths/min) — matches severe
distress ceiling before mechanical ventilation is initiated."""


# ---------------------------------------------------------------------------
# SpO2 — inflammation (pulmonary involvement) + volume overload
# ---------------------------------------------------------------------------

SPO2_INFLAMMATION_THRESHOLD: float = 0.3
"""``inflammation_level`` strictly above which pulmonary involvement
begins depressing SpO2 (until a dedicated respiratory / oxygenation
state variable exists — AD-57 follow-up)."""

SPO2_INFLAMMATION_SCALE: int = 10
"""SpO2 drop (percentage points per unit inflammation above
:data:`SPO2_INFLAMMATION_THRESHOLD`)."""

SPO2_VOLUME_OVERLOAD_THRESHOLD: float = 0.3
"""``volume_status`` strictly above which pulmonary congestion begins
depressing SpO2 (pulmonary edema physiology)."""

SPO2_VOLUME_OVERLOAD_SCALE: int = 5
"""SpO2 drop (percentage points per unit volume above
:data:`SPO2_VOLUME_OVERLOAD_THRESHOLD`)."""

SPO2_CLAMP_MIN: int = 60
"""Physiologic minimum SpO2 (%) — matches severe hypoxemia floor
requiring immediate intervention."""

SPO2_CLAMP_MAX: int = 100
"""Physiologic maximum SpO2 (%) — saturation cannot exceed 100%."""


# ---------------------------------------------------------------------------
# Observed-vitals measurement noise + SpO2 physiologic re-clamp
# (``derive_observed_vitals`` — device / observer variation on top of the
# hidden physiologic state)
# ---------------------------------------------------------------------------

OBSERVED_TEMPERATURE_NOISE_SD: float = 0.5
"""Measurement noise SD (°C) applied to observed temperature — the
smaller noise reflects the higher precision of clinical thermometry
vs cuff-based BP or manual RR counting.

Empirical tuning for the synthetic simulator."""

OBSERVED_VITALS_NOISE_SD_DEFAULT: float = 2.0
"""Measurement noise SD applied to observed BP / HR / RR / SpO2 —
larger than the temperature SD because cuff-BP, palpated HR, and
counted RR carry more observer-driven variance.

Units are per-vital: mmHg for BP, bpm for HR, breaths/min for RR,
% for SpO2. Empirical tuning for the synthetic simulator."""

OBSERVED_SPO2_CLAMP_MIN: float = 60.0
"""Physiologic SpO2 (%) lower re-clamp applied AFTER the observation
noise draw — real pulse oximeters saturate around 60% (values below
are non-clinical / device-artifact territory)."""

OBSERVED_SPO2_CLAMP_MAX: float = 100.0
"""Physiologic SpO2 (%) upper re-clamp applied AFTER the observation
noise draw — SpO2 cannot exceed 100% by definition."""
