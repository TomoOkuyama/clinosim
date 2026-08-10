"""Population-sampling defaults and fallback thresholds (Issue #637).

The population engine in ``clinosim/modules/population/engine.py``
samples each synthetic person's physiology (BMI, height), lifestyle
(smoking, alcohol), and healthcare-access parameters (care-seeking
threshold) from the demographics YAML. When a YAML entry is missing
or a category-comparison cutoff is not locale-overridable, the engine
falls back to a set of previously-inline scalars — lifted here per
policy §5.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. Every fallback here
is invoked through the exact same ``rng.normal`` / ``rng.choice`` /
``rng.random`` code path with identical arguments, so the constant
substitution is bit-identical at the pinned seed.
"""

from __future__ import annotations

__all__ = [
    "ALCOHOL_FALLBACK_LABELS",
    "ALCOHOL_FALLBACK_PROBS",
    "BMI_CLAMP_DEFAULT",
    "BMI_MEAN_FEMALE_DEFAULT",
    "BMI_MEAN_MALE_DEFAULT",
    "BMI_OBESE_THRESHOLD",
    "BMI_OVERWEIGHT_THRESHOLD",
    "BMI_STD_DEFAULT",
    "CARE_SEEKING_CLAMP_MAX",
    "CARE_SEEKING_CLAMP_MIN",
    "CARE_SEEKING_THRESHOLD_MEAN_DEFAULT",
    "CARE_SEEKING_THRESHOLD_SD_DEFAULT",
    "HEIGHT_MEAN_FEMALE_CM_DEFAULT",
    "HEIGHT_MEAN_MALE_CM_DEFAULT",
    "HEIGHT_SHRINKAGE_AGE_THRESHOLD",
    "HEIGHT_SHRINKAGE_PER_DECADE_CM_DEFAULT",
    "HEIGHT_STD_CM_DEFAULT",
    "MOBILE_PHONE_MIN_AGE",
    "SMOKING_FALLBACK_LABELS",
    "SMOKING_FALLBACK_PROBS",
]


# ---------------------------------------------------------------------------
# BMI physiology defaults (used only when demographics YAML omits
# ``physiology.bmi.<sex>``)
# ---------------------------------------------------------------------------

BMI_MEAN_MALE_DEFAULT: float = 23.5
"""Fallback mean BMI (kg/m²) for adult males when the demographics YAML
does not provide ``physiology.bmi.male.mean``.

23.5 sits at the midpoint of the US (~28) / JP (~23) adult male means;
locale YAMLs override it, so this default only fires for unfamiliar
locales or partial YAML fixtures."""

BMI_MEAN_FEMALE_DEFAULT: float = 22.0
"""Fallback mean BMI (kg/m²) for adult females when the demographics YAML
does not provide ``physiology.bmi.female.mean``.

22.0 sits at the midpoint of the US (~27) / JP (~21) adult female means;
same override contract as ``BMI_MEAN_MALE_DEFAULT``."""

BMI_STD_DEFAULT: float = 3.5
"""Fallback BMI standard deviation (kg/m²) applied to both sexes when
demographics YAML does not provide ``physiology.bmi.<sex>.std``.

3.5 is a broadly-typical adult population SD (roughly matches NHANES
and Japanese 特定健診 aggregate distributions)."""

BMI_CLAMP_DEFAULT: tuple[float, float] = (15.0, 45.0)
"""Fallback (min, max) clamp applied to sampled BMI values when
demographics YAML does not provide ``physiology.bmi.clamp``.

15 kg/m² is well below any plausible healthy adult BMI; 45 kg/m² is
above class-III obesity — the clamp exists purely to reject extreme
tails from the normal distribution rather than as a clinical cutoff."""


# ---------------------------------------------------------------------------
# Height physiology defaults (used only when demographics YAML omits
# ``physiology.height_cm.<sex>``)
# ---------------------------------------------------------------------------

HEIGHT_MEAN_MALE_CM_DEFAULT: float = 170.0
"""Fallback mean adult male height (cm) when demographics YAML does not
provide ``physiology.height_cm.male.mean``.

170 cm is a rough US/JP midpoint for adult males; both locale YAMLs
override it."""

HEIGHT_MEAN_FEMALE_CM_DEFAULT: float = 157.5
"""Fallback mean adult female height (cm) when demographics YAML does
not provide ``physiology.height_cm.female.mean``.

157.5 cm is a rough US/JP midpoint for adult females; both locale YAMLs
override it."""

HEIGHT_STD_CM_DEFAULT: float = 5.5
"""Fallback height standard deviation (cm) applied to both sexes when
demographics YAML does not provide ``physiology.height_cm.<sex>.std``.

5.5 cm approximates the population SD for adult height across most
national datasets (NHANES ~6-7 cm, Japanese aggregate ~5-6 cm)."""

HEIGHT_SHRINKAGE_PER_DECADE_CM_DEFAULT: float = 0.5
"""Fallback age-related height shrinkage (cm per decade past
``HEIGHT_SHRINKAGE_AGE_THRESHOLD``) when demographics YAML does not
provide ``physiology.height_cm.shrinkage_per_decade_after_60``.

0.5 cm/decade is at the low end of published age-related stature-loss
estimates (typical range 0.5-1.0 cm/decade after age 60 in
osteoporosis-adjusted cohorts) — chosen to avoid over-shrinking
synthetic elderly patients when the locale YAML is incomplete."""

HEIGHT_SHRINKAGE_AGE_THRESHOLD: int = 60
"""Age (years) at which the height-shrinkage penalty starts applying.

Empirical tuning for the synthetic simulator: matches the
``shrinkage_per_decade_after_60`` YAML key name (age 60 is a commonly
cited inflection point for age-related vertebral height loss)."""


# ---------------------------------------------------------------------------
# BMI category thresholds
# ---------------------------------------------------------------------------

BMI_OVERWEIGHT_THRESHOLD: float = 25.0
"""BMI (kg/m²) at or above which a person is classified as ``overweight``
for lifestyle-risk-multiplier lookup.

25 kg/m² is the WHO overweight cutoff (JP-specific 特定保健指導 uses a
lower 25 as well, so no locale variance)."""

BMI_OBESE_THRESHOLD: float = 30.0
"""BMI (kg/m²) at or above which a person is classified as ``obese``
for lifestyle-risk-multiplier lookup.

30 kg/m² is the WHO obesity cutoff. JP's 特定保健指導 uses BMI ≥ 25 as
"肥満" but the simulator's risk-multiplier YAML keys (``overweight`` /
``obese``) follow the WHO/US convention; the higher 30 threshold
therefore fires the ``obese`` multiplier only on the truly-obese
subset regardless of locale."""


# ---------------------------------------------------------------------------
# Lifestyle fallback distributions (used when demographics YAML omits
# ``lifestyle_distribution.smoking.<sex>`` / ``.alcohol.<sex>``)
# ---------------------------------------------------------------------------

SMOKING_FALLBACK_LABELS: tuple[str, str, str] = ("never", "former", "current")
"""Smoking-status labels sampled when the YAML sex-specific distribution
is missing.

Matches the ``smoking`` risk-multiplier keys expected in
``lifestyle_risk_multipliers.smoking.<label>``."""

SMOKING_FALLBACK_PROBS: tuple[float, float, float] = (0.55, 0.30, 0.15)
"""Fallback probability weights for smoking-status labels.

Empirical tuning for the synthetic simulator: roughly matches JP/US
adult combined never / former / current rates when averaged across
sexes; locale-aware distributions in ``lifestyle_distribution.smoking``
override this fallback."""

ALCOHOL_FALLBACK_LABELS: tuple[str, str, str] = ("none", "social", "heavy")
"""Alcohol-use labels sampled when the YAML sex-specific distribution is
missing.

Matches the labels used in ``lifestyle_distribution.alcohol.<sex>``."""

ALCOHOL_FALLBACK_PROBS: tuple[float, float, float] = (0.60, 0.30, 0.10)
"""Fallback probability weights for alcohol-use labels.

Empirical tuning for the synthetic simulator: represents a broad adult
none-dominant / social-drinker / heavy-drinker mix; locale YAMLs
override for JP/US-specific rates."""


# ---------------------------------------------------------------------------
# Care-seeking behavior sampling
# ---------------------------------------------------------------------------

CARE_SEEKING_THRESHOLD_MEAN_DEFAULT: float = 0.30
"""Fallback mean of the per-person care-seeking severity threshold when
demographics YAML does not provide ``care_seeking.threshold_mean``.

Lower values → more willing to seek care. 0.30 is the US baseline
convention documented alongside the JP override (~0.20 reflecting 健診
culture)."""

CARE_SEEKING_THRESHOLD_SD_DEFAULT: float = 0.12
"""Fallback standard deviation of the per-person care-seeking severity
threshold when demographics YAML does not provide
``care_seeking.threshold_sd``.

0.12 keeps ~95% of sampled thresholds within ±0.24 of the mean, giving
a plausible spread of "avoiders" and "eager seekers" around either
locale mean."""

CARE_SEEKING_CLAMP_MIN: float = 0.05
"""Minimum allowed value for a sampled care-seeking threshold.

Empirical tuning for the synthetic simulator: 0.05 prevents the
distribution's left tail from producing patients who hospitalize for
essentially any severity (which would produce implausible ED
volumes)."""

CARE_SEEKING_CLAMP_MAX: float = 0.90
"""Maximum allowed value for a sampled care-seeking threshold.

Empirical tuning for the synthetic simulator: 0.90 prevents the
distribution's right tail from producing patients who never seek care
even under extreme severity (which would silently drop otherwise-valid
disease events)."""


# ---------------------------------------------------------------------------
# Communication attributes
# ---------------------------------------------------------------------------

MOBILE_PHONE_MIN_AGE: int = 15
"""Age (years) at which a synthetic person is assigned a mobile phone
number.

Empirical tuning for the synthetic simulator: 15 approximates the
middle-of-high-school threshold when personal mobile ownership becomes
near-universal in both US and JP cohorts. Children under this age get
an empty ``phone_mobile`` field and are reachable only via the shared
household landline."""
