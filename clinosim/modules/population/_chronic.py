"""Chronic-condition prevalence math cluster.

Extracted verbatim from ``clinosim/modules/population/engine.py`` as
step C3a of the full-review Phase C engine split (CRITICAL C3).
Behavior is byte-identical — ``engine.py`` re-exports these names so
every call site stays intact.

This module carries no RNG consumption of its own; it computes
expected-value multipliers that the sampling loop in
``generate_population`` consumes via plain function calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from clinosim.modules.population._population_thresholds import (
    BMI_MEAN_FEMALE_DEFAULT,
    BMI_MEAN_MALE_DEFAULT,
    BMI_OBESE_THRESHOLD,
    BMI_OVERWEIGHT_THRESHOLD,
    BMI_STD_DEFAULT,
    SMOKING_FALLBACK_LABELS,
    SMOKING_FALLBACK_PROBS,
)
from clinosim.modules.population._population_workflow_thresholds import LEGAL_ADULT_AGE


@dataclass(frozen=True)
class ChronicConditionSpec:
    """Target marginal prevalence of a chronic condition by (age, sex).

    Two YAML schemas are supported (see ``_parse_chronic_prevalence``):

    * Legacy flat form: ``{sex: "F", "40-59": 0.015, "60-99": 0.030}`` —
      one set of age bands + one hard sex filter (``sex`` may be
      ``"M"``, ``"F"``, or ``""`` for sex-neutral). Used for strictly
      single-sex codes (N40 BPH, N70 salpingitis, Z34 pregnancy, C61
      prostate) and for sex-neutral codes.

    * ``by_sex`` form: ``{by_sex: {F: {bands}, M: {bands}}}`` — the
      parser normalises this into the flat form by treating the FIRST
      sex key as the primary (goes to ``sex`` / ``age_ranges``) and
      every remaining sex key as an augmentation (goes to
      ``augment_sex_bands``). This lets the sampling loop use the
      master RNG for the primary sex (byte-identical to the pre-#957
      flat-form behaviour) and a per-patient sub-RNG for the
      augmentation, so cross-patient cascades don't happen when a
      new sex is activated on a previously-single-sex code (Issue
      #957 C50 breast cancer: female was primary pre-#957; male at
      ~1 % of C50 total activates via ``augment_sex_bands``).

    ``prevalence_at`` returns the primary-sex prevalence only —
    augmentation is sampled by a separate sub-RNG path in
    ``generate_population`` (see the sampling loop) so ``prevalence_at``
    stays a pure master-RNG-side query.
    """

    age_ranges: dict[tuple[int, int], float]
    sex: str
    augment_sex_bands: dict[str, dict[tuple[int, int], float]] = field(default_factory=dict)
    # Issue #2140: drawn from a per-(patient, code) sub-RNG instead of the
    # master stream, so adding the code leaves every other condition of
    # every resident byte-identical (YAML ``rng_isolated: true``).
    rng_isolated: bool = False

    def augment_prevalence_at(self, age: int, sex: str) -> float:
        """Return the augmentation-sex target marginal prevalence at
        (age, sex), or 0.0 if none. Sampled by a per-patient sub-RNG
        (NOT the master RNG) so cross-patient cascades don't happen
        when a new sex is activated on a previously-single-sex code.
        """
        bands = self.augment_sex_bands.get(sex, {})
        for (lo, hi), prev in bands.items():
            if lo <= age <= hi:
                return prev
        return 0.0


def _bmi_category_probabilities(demo: dict, sex_key: str) -> dict[str, float]:
    """Return P(bmi_cat) for cats {'normal', 'overweight', 'obese'} given the
    physiology.bmi distribution and lifestyle_risk_multipliers.bmi.thresholds
    in ``demo``. Uses analytical Normal CDF on (mean, std); clamp effects are
    negligible for typical BMI parameter ranges. Falls back to yaml-declared
    thresholds; no thresholds hardcoded here."""
    from math import erf, sqrt

    phys = (demo.get("physiology") or {}).get("bmi") or {}
    lm_bmi = (demo.get("lifestyle_risk_multipliers") or {}).get("bmi") or {}
    thresholds = lm_bmi.get("thresholds") or {
        "overweight": BMI_OVERWEIGHT_THRESHOLD,
        "obese": BMI_OBESE_THRESHOLD,
    }
    mean = float(
        (phys.get(sex_key) or {}).get("mean", BMI_MEAN_MALE_DEFAULT if sex_key == "male" else BMI_MEAN_FEMALE_DEFAULT)
    )
    std = float((phys.get(sex_key) or {}).get("std", BMI_STD_DEFAULT))
    if std <= 0.0:
        if mean >= thresholds.get("obese", BMI_OBESE_THRESHOLD):
            return {"normal": 0.0, "overweight": 0.0, "obese": 1.0}
        if mean >= thresholds.get("overweight", BMI_OVERWEIGHT_THRESHOLD):
            return {"normal": 0.0, "overweight": 1.0, "obese": 0.0}
        return {"normal": 1.0, "overweight": 0.0, "obese": 0.0}

    def _cdf(x: float) -> float:
        return 0.5 * (1.0 + erf((x - mean) / (std * sqrt(2.0))))

    p_lt_ow = _cdf(float(thresholds.get("overweight", BMI_OVERWEIGHT_THRESHOLD)))
    p_lt_ob = _cdf(float(thresholds.get("obese", BMI_OBESE_THRESHOLD)))
    return {
        "normal": max(0.0, p_lt_ow),
        "overweight": max(0.0, p_lt_ob - p_lt_ow),
        "obese": max(0.0, 1.0 - p_lt_ob),
    }


def _smoking_status_probabilities(demo: dict, sex_key: str, age: int) -> dict[str, float]:
    """Return P(smoking_status) for ``sex_key`` at ``age``. Minors
    (age < LEGAL_ADULT_AGE) always resolve to smoking='never' because the
    person loop overrides post-sampling. When the yaml smoking distribution
    is missing, the module-level SMOKING_FALLBACK constants apply."""
    if age < LEGAL_ADULT_AGE:
        return {"never": 1.0, "former": 0.0, "current": 0.0}
    lifestyle = demo.get("lifestyle_distribution") or {}
    dist = (lifestyle.get("smoking") or {}).get(sex_key)
    if not dist:
        return dict(zip(SMOKING_FALLBACK_LABELS, SMOKING_FALLBACK_PROBS, strict=False))
    total = sum(float(v) for v in dist.values())
    if total <= 0:
        return dict(zip(SMOKING_FALLBACK_LABELS, SMOKING_FALLBACK_PROBS, strict=False))
    return {k: float(v) / total for k, v in dist.items()}


def _expected_lifestyle_multiplier(demo: dict, code: str, sex_key: str, age: int) -> float:
    """E[lifestyle multiplier for ``code``] across the population BMI × smoking
    distribution at ``(sex_key, age)``. Composed as E[BMI_mult] × E[smoking_mult]
    under the independence assumption that BMI and smoking category assignments
    are independent in the population loop (which they are — separate rng draws
    from different demo distributions)."""
    lm = demo.get("lifestyle_risk_multipliers") or {}
    bmi_cfg = lm.get("bmi") or {}
    smoking_cfg = lm.get("smoking") or {}

    e_bmi = 1.0
    if any(bmi_cfg.get(cat) for cat in ("normal", "overweight", "obese")):
        bmi_probs = _bmi_category_probabilities(demo, sex_key)
        e_bmi = 0.0
        for cat, p in bmi_probs.items():
            m = float((bmi_cfg.get(cat) or {}).get(code, 1.0))
            e_bmi += p * m

    e_smoking = 1.0
    if any(smoking_cfg.get(status) for status in ("never", "former", "current")):
        smoking_probs = _smoking_status_probabilities(demo, sex_key, age)
        e_smoking = 0.0
        for status, p in smoking_probs.items():
            m = float((smoking_cfg.get(status) or {}).get(code, 1.0))
            e_smoking += p * m
    return e_bmi * e_smoking


def _expected_comorbidity_multiplier(
    chronic_data: dict[str, ChronicConditionSpec],
    current_code: str,
    age: int,
    sex: str,
    comorbidity_cfg: dict,
) -> float:
    """E[comorbidity correlation multiplier for ``current_code``] given the
    target marginal prevalences of prior-in-iteration-order chronic codes.

    For each prior_code C' with target marginal P_{C'} in this (age, sex)
    band and multiplier m_{C' → current_code}:
        E[factor_{C'}] = 1 + P_{C'} * (m - 1)
    The compound = Π E[factor_{C'}] over C' preceding current_code in
    ``chronic_data`` iteration order (which mirrors the yaml order of
    ``chronic_prevalence``). This is the population-average multiplier a
    fresh sampling draw for ``current_code`` will experience.
    """
    compound = 1.0
    for prior_code, prior_spec in chronic_data.items():
        if prior_code == current_code:
            break
        if prior_spec.sex and prior_spec.sex != sex:
            continue
        m = float((comorbidity_cfg.get(prior_code) or {}).get(current_code, 1.0))
        if m == 1.0:
            continue
        p_prior = _target_prev_at_age_legacy(prior_spec, age)
        if p_prior <= 0.0:
            continue
        compound *= 1.0 + p_prior * (m - 1.0)
    return compound


def _target_prev_at_age_legacy(spec: ChronicConditionSpec, age: int) -> float:
    """Primary-sex flat-band lookup for the pre-#957 comorbidity math.
    Ignores ``augment_sex_bands`` (augmentation contributes to marginal
    but its cross-code comorbidity coupling is negligible at ~1 % of
    total; leaving it out of the compound multiplier keeps the
    primary-sex marginal-rescale math byte-identical to master)."""
    for (lo, hi), prev in spec.age_ranges.items():
        if lo <= age <= hi:
            return prev
    return 0.0


def _parse_chronic_prevalence(demo: dict) -> dict[str, ChronicConditionSpec]:
    """Parse chronic_prevalence from demographics YAML into structured dict.

    Two schemas are accepted (see ``ChronicConditionSpec``):

    * Legacy flat: ``{sex: F, "40-59": 0.015, "60-99": 0.030}`` — single
      set of age bands + optional ``sex`` hard filter. Used for
      strictly single-sex codes and for sex-neutral codes.
    * ``by_sex``: ``{by_sex: {F: {bands}, M: {bands}}}`` — the FIRST
      sex key is normalised into the flat-form primary (``sex`` /
      ``age_ranges``); every remaining sex key becomes an entry in
      ``augment_sex_bands``. This lets the primary-sex sampling stay
      byte-identical to the pre-#957 master-RNG path while the
      augmentation runs on a per-patient sub-RNG so activating a new
      sex on a previously-single-sex code does not cascade across
      patients. ``sex`` / flat bands MUST NOT be mixed with ``by_sex``.

    Each ``by_sex`` inner sex block has the same age-range key format as
    the legacy flat form (``"lo-hi": prevalence``).
    """
    raw = demo.get("chronic_prevalence", {})
    result: dict[str, ChronicConditionSpec] = {}
    for code, entry in raw.items():
        if not isinstance(entry, dict):
            continue

        by_sex_raw = entry.get("by_sex")
        if isinstance(by_sex_raw, dict):
            extra_keys = [k for k in entry.keys() if k != "by_sex"]
            if extra_keys:
                raise ValueError(
                    f"chronic_prevalence[{code!r}]: 'by_sex' schema cannot be mixed "
                    f"with legacy keys {extra_keys!r}; pick one form."
                )
            primary_sex = ""
            primary_bands: dict[tuple[int, int], float] = {}
            augment: dict[str, dict[tuple[int, int], float]] = {}
            for i, (sex_key, bands_raw) in enumerate(by_sex_raw.items()):
                sex_norm = str(sex_key).upper()
                if sex_norm not in ("M", "F"):
                    raise ValueError(
                        f"chronic_prevalence[{code!r}].by_sex: sex key must be 'M' or 'F', got {sex_key!r}"
                    )
                bands: dict[tuple[int, int], float] = {}
                for range_key, prev in (bands_raw or {}).items():
                    lo, hi = str(range_key).split("-")
                    bands[(int(lo), int(hi))] = float(prev)
                if i == 0:
                    primary_sex = sex_norm
                    primary_bands = bands
                else:
                    augment[sex_norm] = bands
            result[code] = ChronicConditionSpec(age_ranges=primary_bands, sex=primary_sex, augment_sex_bands=augment)
            continue

        sex_filter = str(entry.get("sex", ""))
        age_ranges: dict[tuple[int, int], float] = {}
        for key, prev in entry.items():
            if key in ("sex", "rng_isolated"):
                continue
            lo, hi = str(key).split("-")
            age_ranges[(int(lo), int(hi))] = float(prev)
        result[code] = ChronicConditionSpec(
            age_ranges=age_ranges, sex=sex_filter, rng_isolated=bool(entry.get("rng_isolated", False))
        )
    return result
