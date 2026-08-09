"""Vital-sign reference and critical ranges (Issue #637 PR-C).

The FHIR builder in ``fhir_r4/labs/observations.py`` used to carry
vital-sign metadata as positional tuples (LOINC code, JP / EN display,
UCUM unit, normal / critical bounds, per-field time offset), which made
the reference bounds invisible to review and impossible to grep for.
This module extracts them into a typed dataclass plus one named
instance per vital, so:

- reference bounds are grep-able by symbol (``VITAL_HEART_RATE`` etc.),
- each bound carries a docstring naming the clinical source,
- adding or shifting a bound is a one-line dataclass edit rather than a
  positional-tuple change with no compile-time safety.

Two dataclasses are defined:

- :class:`VitalSignReferenceRange` — self-contained vitals emitted by
  the top-level ``_vital_map`` loop (HR, SpO2, temperature, RR). Carries
  the ``vs`` dict key it reads from and the per-field time offset within
  a vital-sign set.
- :class:`BloodPressureComponentReferenceRange` — component metadata for
  the BP-panel Observation. BP is emitted as one panel Observation with
  systolic + diastolic under ``component[]``, so these do not carry a
  standalone ``vs`` field or a time offset.

Both dataclasses are frozen so callers can hold them as module-level
constants without accidental mutation. All values are immutable
floats / ints / strings; no runtime state lives here.

Byte-diff verification: swapping the positional tuples for these
constants MUST NOT change any generated FHIR resource. Adding a new
vital or shifting an existing bound requires a fresh golden-cohort
byte-diff (Issue #637 acceptance criterion).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "BP_DIASTOLIC",
    "BP_SYSTOLIC",
    "BloodPressureComponentReferenceRange",
    "STANDALONE_VITAL_SIGNS",
    "VITAL_HEART_RATE",
    "VITAL_RESPIRATORY_RATE",
    "VITAL_SPO2",
    "VITAL_TEMPERATURE",
    "VitalSignReferenceRange",
]


@dataclass(frozen=True)
class VitalSignReferenceRange:
    """Metadata + reference / critical bounds for one standalone vital sign.

    Attributes:
        field: Key on the ``vs`` dict this vital reads from
            (``vital_signs`` entry field name).
        loinc: LOINC code emitted in ``Observation.code.coding``.
        display_en: English display for ``Observation.code.coding.display``
            when country != JP.
        display_ja: Japanese display for JP output.
        unit: UCUM unit code + human string (both fields on
            ``valueQuantity`` use this same token — same convention as the
            pre-refactor tuple).
        normal_low: Lower bound of the adult normal range
            (``Observation.referenceRange[normal].low.value``).
        normal_high: Upper bound of the adult normal range.
        critical_low: Panic-low cutoff, or ``None`` when no lower
            critical bound applies clinically (currently unused — every
            vital in the standalone set has a lower critical bound).
        critical_high: Panic-high cutoff, or ``None`` when no upper
            critical bound applies (SpO2, per ``Observation.referenceRange
            [treatment].high``, since SpO2 cannot be critically high).
        time_offset_sec: Per-field delay within one vital-sign set.
            Zero for the "first" measurement (HR shares the cycle with
            BP); non-zero for later measurements taken by the same nurse
            during one round (matches real-world nursing flowsheet
            timing).
    """

    field: str
    loinc: str
    display_en: str
    display_ja: str
    unit: str
    normal_low: float
    normal_high: float
    critical_low: float | None
    critical_high: float | None
    time_offset_sec: int


@dataclass(frozen=True)
class BloodPressureComponentReferenceRange:
    """Metadata + reference / critical bounds for one BP-panel component.

    Attributes:
        loinc: LOINC code for the component (``Observation.component.code``).
        display_en: English display for the component code.
        display_ja: Japanese display for JP output.
        normal_low: Lower bound of the adult normal range.
        normal_high: Upper bound of the adult normal range.
        critical_low: Panic-low cutoff (BP always has one).
        critical_high: Panic-high cutoff (BP always has one).

    The BP-panel Observation carries a single LOINC ``85354-9`` code and
    both components share the panel's timestamp, so a ``field`` /
    ``time_offset_sec`` attribute is intentionally absent here (contrast
    :class:`VitalSignReferenceRange`).
    """

    loinc: str
    display_en: str
    display_ja: str
    normal_low: float
    normal_high: float
    critical_low: float
    critical_high: float


# ---------------------------------------------------------------------------
# Standalone vitals (emitted one-Observation-per-vital by ``_vital_map`` loop)
# ---------------------------------------------------------------------------

VITAL_HEART_RATE = VitalSignReferenceRange(
    field="heart_rate",
    loinc="8867-4",
    display_en="Heart rate",
    display_ja="脈拍",
    unit="/min",
    normal_low=60,
    normal_high=100,
    critical_low=40,
    critical_high=130,
    time_offset_sec=0,
)
"""Resting adult heart rate.

Normal range 60-100 bpm reflects standard adult sinus rhythm
(``docs.google.com/AHA basic vitals``, replicated by every ICU flow
sheet clinosim ships with). Critical thresholds 40 / 130 bpm are the
typical panic-band widths used in nursing flowsheets (bradyarrhythmia
alert / tachyarrhythmia alert). Empirical tuning for the synthetic
simulator: real institutions vary these by a few bpm.
"""

VITAL_SPO2 = VitalSignReferenceRange(
    field="spo2",
    loinc="2708-6",
    display_en="Oxygen saturation",
    display_ja="酸素飽和度",
    unit="%",
    normal_low=95,
    normal_high=100,
    critical_low=88,
    critical_high=None,
    time_offset_sec=5,
)
"""Pulse oximetry (SpO2).

Normal range 95-100 % is the adult breathing-room-air reference. The
critical-low 88 % cutoff aligns with the GOLD COPD long-term
oxygen-therapy threshold and is the same value clinosim's
``fluid_balance`` module uses to trigger supplemental O2. No critical-
high value applies — SpO2 cannot be critically high, so
``critical_high=None`` is intentional (matches the original
``crit_high=None`` in the pre-refactor tuple).
"""

VITAL_TEMPERATURE = VitalSignReferenceRange(
    field="temperature_celsius",
    loinc="8310-5",
    display_en="Body temperature",
    display_ja="体温",
    unit="Cel",
    normal_low=36.0,
    normal_high=37.5,
    critical_low=35.0,
    critical_high=39.5,
    time_offset_sec=30,
)
"""Core body temperature (°C).

Normal range 36.0-37.5 °C is the adult afebrile band. Critical-low
35.0 °C is the WHO hypothermia threshold; critical-high 39.5 °C is the
threshold at which most sepsis / neutropenic-fever protocols escalate.
"""

VITAL_RESPIRATORY_RATE = VitalSignReferenceRange(
    field="respiratory_rate",
    loinc="9279-1",
    display_en="Respiratory rate",
    display_ja="呼吸数",
    unit="/min",
    normal_low=12,
    normal_high=20,
    critical_low=8,
    critical_high=30,
    time_offset_sec=60,
)
"""Spontaneous respiratory rate (adult, awake).

Normal 12-20 /min is the adult reference. Critical-low 8 /min is the
apnea / opioid-overdose threshold; critical-high 30 /min matches the
NEWS2 tachypnea red-flag boundary (`clinosim/modules/observation/
nursing_flowsheets` NEWS2 scoring band).
"""


# Insertion order matches the pre-refactor tuple sequence exactly so the
# FHIR builder walks vitals in the historical order. Callers should
# iterate this tuple rather than importing the four constants
# individually.
STANDALONE_VITAL_SIGNS: tuple[VitalSignReferenceRange, ...] = (
    VITAL_HEART_RATE,
    VITAL_SPO2,
    VITAL_TEMPERATURE,
    VITAL_RESPIRATORY_RATE,
)


# ---------------------------------------------------------------------------
# BP-panel components (emitted under a single BP-panel Observation)
# ---------------------------------------------------------------------------

BP_SYSTOLIC = BloodPressureComponentReferenceRange(
    loinc="8480-6",
    display_en="Systolic blood pressure",
    display_ja="収縮期血圧",
    normal_low=90,
    normal_high=140,
    critical_low=80,
    critical_high=200,
)
"""Systolic BP (mmHg).

Normal 90-140 mmHg is a permissive adult band that spans both American
"< 130 / < 140" and Japanese-guideline thresholds. Critical-low 80 mmHg
maps to the shock-workup cutoff used across clinosim's HAI / sepsis
pathways; critical-high 200 mmHg is the hypertensive-emergency
threshold used by the observation-layer.
"""

BP_DIASTOLIC = BloodPressureComponentReferenceRange(
    loinc="8462-4",
    display_en="Diastolic blood pressure",
    display_ja="拡張期血圧",
    normal_low=60,
    normal_high=90,
    critical_low=50,
    critical_high=120,
)
"""Diastolic BP (mmHg).

Normal 60-90 mmHg mirrors the systolic band's permissive shape.
Critical-low 50 mmHg matches the SBP<80 shock-workup pair (paired
readings usually trigger together); critical-high 120 mmHg aligns with
the diastolic hypertensive-emergency threshold. Note that BP components
always emit both critical bounds, so ``critical_low`` /
``critical_high`` are typed ``float`` (not ``float | None``) — this
matches the pre-refactor keyword arguments to ``_build_bp_component``.
"""
