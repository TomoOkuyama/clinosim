"""Population engine — v0.1-beta: catchment area generation + life events.

Generates a lightweight population registry (Layer 1), runs monthly life events,
and produces care-seeking decisions that trigger hospital encounters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from clinosim.modules._shared import is_jp, normalize_probabilities
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.disease.severity import sample_severity
from clinosim.modules.population._household_thresholds import (
    AVG_HOUSEHOLD_SIZE_DEFAULT,
    BLOOD_TYPE_DEFAULT_DISTRIBUTION,
    DOB_DAY_MAX_EXCLUSIVE,
    DOB_DAY_MIN,
    HOUSEHOLD_LANDLINE_PROBABILITY_DEFAULT,
    HOUSEHOLD_SIZE_WEIGHTED_CHOICES,
    JP_ADDRESS_APARTMENT_PROBABILITY_DEFAULT,
    JP_ADDRESS_APARTMENT_ROOM_MAX_EXCLUSIVE,
    JP_ADDRESS_APARTMENT_ROOM_MIN,
    JP_ADDRESS_BANCHI_MAX_EXCLUSIVE,
    JP_ADDRESS_BANCHI_MIN,
    JP_ADDRESS_CHOME_MAX_EXCLUSIVE,
    JP_ADDRESS_CHOME_MIN,
    JP_ADDRESS_GO_MAX_EXCLUSIVE,
    JP_ADDRESS_GO_MIN,
    JP_PHONE_LANDLINE_NON_TOKYO_EXCHANGE_MAX_EXCLUSIVE,
    JP_PHONE_LANDLINE_NON_TOKYO_EXCHANGE_MIN,
    PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE,
    PHONE_4DIGIT_BLOCK_MIN,
    SEX_RATIO_MALE_DEFAULT,
    US_ADDRESS_APARTMENT_NUMBER_MAX_EXCLUSIVE,
    US_ADDRESS_APARTMENT_NUMBER_MIN,
    US_ADDRESS_APARTMENT_PROBABILITY_DEFAULT,
    US_ADDRESS_STREET_NUMBER_MAX_EXCLUSIVE,
    US_ADDRESS_STREET_NUMBER_MIN,
    US_PHONE_EXCHANGE_MAX_EXCLUSIVE,
    US_PHONE_EXCHANGE_MIN,
    WIFE_KEEPS_MAIDEN_PROBABILITY_DEFAULT,
)
from clinosim.modules.population._population_thresholds import (
    ALCOHOL_FALLBACK_LABELS,
    ALCOHOL_FALLBACK_PROBS,
    BMI_CLAMP_DEFAULT,
    BMI_MEAN_FEMALE_DEFAULT,
    BMI_MEAN_MALE_DEFAULT,
    BMI_OBESE_THRESHOLD,
    BMI_OVERWEIGHT_THRESHOLD,
    BMI_STD_DEFAULT,
    CARE_SEEKING_CLAMP_MAX,
    CARE_SEEKING_CLAMP_MIN,
    CARE_SEEKING_THRESHOLD_MEAN_DEFAULT,
    CARE_SEEKING_THRESHOLD_SD_DEFAULT,
    HEIGHT_MEAN_FEMALE_CM_DEFAULT,
    HEIGHT_MEAN_MALE_CM_DEFAULT,
    HEIGHT_SHRINKAGE_AGE_THRESHOLD,
    HEIGHT_SHRINKAGE_PER_DECADE_CM_DEFAULT,
    HEIGHT_STD_CM_DEFAULT,
    MOBILE_PHONE_MIN_AGE,
    SMOKING_FALLBACK_LABELS,
    SMOKING_FALLBACK_PROBS,
)
from clinosim.modules.population._population_workflow_thresholds import (
    CHRONIC_VISIT_INITIAL_MONTH_CAP_EXCLUSIVE,
    CHRONIC_VISITS_MAX_PER_YEAR,
    COLONOSCOPY_MIN_AGE,
    COLONOSCOPY_PROBABILITY,
    DIABETIC_RETINOPATHY_ICD10_CODE,
    DIABETIC_RETINOPATHY_PROBABILITY,
    EVENT_DAY_JITTER_END_EXCLUSIVE,
    EVENT_DAY_JITTER_START,
    EVENT_MID_OF_MONTH_DAY,
    EVENT_RANDOM_DAY_MAX_EXCLUSIVE,
    EVENT_RANDOM_DAY_MIN,
    FLU_VAX_ADULT_AGE_THRESHOLD,
    FLU_VAX_COMORBIDITY_MIN,
    FLU_VAX_MONTHS,
    FLU_VAX_PROBABILITY,
    HEALTH_SCREENING_MIN_AGE,
    HEALTH_SCREENING_MONTH_END_EXCLUSIVE,
    HEALTH_SCREENING_MONTH_START,
    LEGAL_ADULT_AGE,
    MAMMOGRAPHY_MIN_AGE,
    MAMMOGRAPHY_PROBABILITY,
    MIXED_CONDITIONS_MIN_AGE_DEFAULT,
    MIXED_CONDITIONS_MIN_CHRONIC_DEFAULT,
    MIXED_CONDITIONS_PROBABILITY_DEFAULT,
    OCCUPATION_MISMATCH_FALLBACK_MULTIPLIER,
    PRIOR_HOSPITALIZATION_RECURRENCE_MULTIPLIER,
    RANDOM_MONTH_MAX_EXCLUSIVE,
    RANDOM_MONTH_MIN,
    UNKNOWN_CONDITION_AGE_FACTOR_DEFAULT,
    UNKNOWN_CONDITION_BASE_RATE_DEFAULT,
    UNKNOWN_CONDITION_MIN_AGE_DEFAULT,
    UNKNOWN_CONDITION_PATTERNS_FALLBACK,
    UNKNOWN_CONDITION_SEVERITY_BETA_ALPHA,
    UNKNOWN_CONDITION_SEVERITY_BETA_BETA,
)
from clinosim.seeding import chronic_augment_sex_seed
from clinosim.types.population import HospitalizationSummary, LifeEvent, PersonRecord

__all__ = ["HospitalizationSummary", "PersonRecord", "LifeEvent"]


@dataclass
class Household:
    household_id: str
    members: list[PersonRecord] = field(default_factory=list)
    region: str = "urban"


@dataclass
class PopulationRegistry:
    households: list[Household] = field(default_factory=list)
    persons: dict[str, PersonRecord] = field(default_factory=dict)

    def get_person(self, person_id: str) -> PersonRecord | None:
        return self.persons.get(person_id)

    @property
    def total_persons(self) -> int:
        return len(self.persons)


def _load_demographics(country: str) -> dict:
    """Load demographic data from locale."""
    from clinosim.locale.loader import load_demographics

    return load_demographics(country)


def _parse_age_distribution(demo: dict) -> tuple[list[tuple[int, int]], list[float]]:
    """Parse age_distribution from demographics YAML into bands and probs."""
    raw = demo.get("age_distribution", {})
    bands: list[tuple[int, int]] = []
    probs: list[float] = []
    for key, val in raw.items():
        lo, hi = key.split("-")
        bands.append((int(lo), int(hi)))
        probs.append(float(val))
    return bands, probs


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
    sex: str  # "M", "F", or "" (any) — primary-sex filter
    augment_sex_bands: dict[str, dict[tuple[int, int], float]] = field(default_factory=dict)

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
        # Degenerate distribution: every sample equals mean.
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

        # Legacy flat form.
        sex_filter = str(entry.get("sex", ""))
        age_ranges: dict[tuple[int, int], float] = {}
        for key, prev in entry.items():
            if key == "sex":
                continue
            lo, hi = str(key).split("-")
            age_ranges[(int(lo), int(hi))] = float(prev)
        result[code] = ChronicConditionSpec(age_ranges=age_ranges, sex=sex_filter)
    return result


def generate_population(
    size: int,
    country: str,
    rng: np.random.Generator,
    base_year: int = 2024,
    demo: dict | None = None,
) -> PopulationRegistry:
    """Generate a catchment area population with households."""
    registry = PopulationRegistry()
    if demo is None:
        demo = _load_demographics(country)
    avg_household_size = demo.get("average_household_size", AVG_HOUSEHOLD_SIZE_DEFAULT)
    n_households = int(size / avg_household_size)
    chronic_data = _parse_chronic_prevalence(demo)

    # Load name data and naming rules
    name_data = _load_name_data(country)
    from clinosim.locale.loader import load_addresses, load_naming_rules

    naming_rules = load_naming_rules(country)
    surname_rule = naming_rules.get("household_surname_rule", "shared")
    addr_data = load_addresses(country)

    person_count = 0
    for h_idx in range(n_households):
        hh_id = f"HH-{h_idx + 1:06d}"
        hh = Household(household_id=hh_id)

        # Generate household address (shared by all members)
        hh_addr = _generate_household_address(addr_data, rng)
        hh_phone_home = _generate_phone(addr_data, "landline", rng)
        has_landline = rng.random() < addr_data.get("contact_rules", {}).get(
            "household_has_landline_probability", HOUSEHOLD_LANDLINE_PROBABILITY_DEFAULT
        )

        # Household family name — rule depends on country
        # "shared": all members share one surname (JP, CN traditional)
        # "mostly_shared": most share, but wife may keep maiden (~20% US)
        # "not_shared": each person has own surname (KR, ES)
        household_surname = _sample_surname(name_data, rng)

        # Household size: 1-4 (weighted)
        hh_size = int(rng.choice(HOUSEHOLD_SIZE_WEIGHTED_CHOICES))

        for m_idx in range(hh_size):
            if person_count >= size:
                break

            person_count += 1
            pid = f"POP-{person_count:06d}"

            # Age from distribution
            age_band = _sample_age_band(demo, rng)
            age = int(rng.integers(age_band[0], age_band[1] + 1))

            # Sex ratio from YAML — supports optional age-conditional band
            # lookup so cohorts can reproduce the elderly-female skew produced
            # by female longevity (Issue #741). When the demographics YAML
            # omits `sex_ratio.age_conditional`, this collapses to the
            # existing single-probability behaviour (RNG-shape neutral).
            male_prob = _sex_ratio_male_probability(demo, age)
            sex = "M" if rng.random() < male_prob else "F"
            dob = date(
                base_year - age,
                int(rng.integers(RANDOM_MONTH_MIN, RANDOM_MONTH_MAX_EXCLUSIVE)),
                int(rng.integers(DOB_DAY_MIN, DOB_DAY_MAX_EXCLUSIVE)),
            )
            blood_type = _sample_blood_type(demo, rng)

            # BMI and height from physiology section
            phys = demo.get("physiology") or {}
            bmi_cfg = phys.get("bmi") or {}
            ht_cfg = phys.get("height_cm") or {}
            sex_key = "male" if sex == "M" else "female"

            bmi_mean = (bmi_cfg.get(sex_key) or {}).get(
                "mean", BMI_MEAN_MALE_DEFAULT if sex == "M" else BMI_MEAN_FEMALE_DEFAULT
            )
            bmi_std = (bmi_cfg.get(sex_key) or {}).get("std", BMI_STD_DEFAULT)
            bmi_clamp = bmi_cfg.get("clamp", BMI_CLAMP_DEFAULT)
            bmi = float(np.clip(rng.normal(bmi_mean, bmi_std), bmi_clamp[0], bmi_clamp[1]))

            ht_mean = (ht_cfg.get(sex_key) or {}).get(
                "mean", HEIGHT_MEAN_MALE_CM_DEFAULT if sex == "M" else HEIGHT_MEAN_FEMALE_CM_DEFAULT
            )
            ht_std = (ht_cfg.get(sex_key) or {}).get("std", HEIGHT_STD_CM_DEFAULT)
            shrink = ht_cfg.get("shrinkage_per_decade_after_60", HEIGHT_SHRINKAGE_PER_DECADE_CM_DEFAULT)
            height = float(rng.normal(ht_mean, ht_std))
            if age > HEIGHT_SHRINKAGE_AGE_THRESHOLD:
                height -= (age - HEIGHT_SHRINKAGE_AGE_THRESHOLD) / 10 * shrink

            # Lifestyle: smoking and alcohol (sex-specific distributions).
            #
            # 未成年 override: `rng.choice` は age に関係なく必ず consume する
            # (RNG cursor 保持 = memoize/F4 determinism を破らない)、その上で
            # サンプル結果を捨てて minors (age < LEGAL_ADULT_AGE) は
            # smoking="never" / alcohol="none" に上書き。JP 法定年齢 20+ = 飲
            # 酒・喫煙可能。米国は 21 だが、population module 全体 (occupation
            # 判定等) が 20+ を成人閾値としているので JP/US 共通 20 で運用。
            #
            # Issue #360 G7 で reverted された「sampling 自体を skip」は
            # RNG cursor を shift させて F4 memoize を破ったが、今回の
            # 「consume してから override」は cursor が variant-invariant なの
            # で cold vs cache-hit も byte-identical に保たれる。
            lifestyle = demo.get("lifestyle_distribution") or {}
            smoking_dist = (lifestyle.get("smoking") or {}).get(sex_key, {})
            if smoking_dist:
                sk = list(smoking_dist.keys())
                sp = normalize_probabilities([smoking_dist[k] for k in sk], fallback="raise")
                smoking_status = str(rng.choice(sk, p=sp))
            else:
                smoking_status = str(rng.choice(SMOKING_FALLBACK_LABELS, p=SMOKING_FALLBACK_PROBS))
            if age < LEGAL_ADULT_AGE:
                smoking_status = "never"

            alcohol_dist = (lifestyle.get("alcohol") or {}).get(sex_key, {})
            if alcohol_dist:
                ak = list(alcohol_dist.keys())
                ap = normalize_probabilities([alcohol_dist[k] for k in ak], fallback="raise")
                alcohol_use = str(rng.choice(ak, p=ap))
            else:
                alcohol_use = str(rng.choice(ALCOHOL_FALLBACK_LABELS, p=ALCOHOL_FALLBACK_PROBS))
            if age < LEGAL_ADULT_AGE:
                alcohol_use = "none"

            # Given name (sex-appropriate)
            given = _sample_given_name(name_data, sex, rng)

            # Family name — apply household surname rule
            if surname_rule == "shared":
                # All members share household surname (JP)
                member_surname = household_surname
            elif surname_rule == "mostly_shared":
                # First member sets surname; spouse may keep maiden with some probability
                maiden_prob = naming_rules.get("wife_keeps_maiden_probability", WIFE_KEEPS_MAIDEN_PROBABILITY_DEFAULT)
                if m_idx == 0:
                    member_surname = household_surname
                elif m_idx == 1 and sex == "F" and rng.random() < maiden_prob:
                    # Spouse keeps maiden name
                    member_surname = _sample_surname(name_data, rng)
                else:
                    member_surname = household_surname
            elif surname_rule == "not_shared":
                # Each person has own surname (KR, ES)
                if m_idx == 0:
                    member_surname = household_surname
                else:
                    member_surname = _sample_surname(name_data, rng)
            else:
                member_surname = household_surname

            # Build accumulated multipliers from comorbidity correlations and lifestyle
            comorbidity_cfg = demo.get("comorbidity_correlations") or {}
            lifestyle_mults = demo.get("lifestyle_risk_multipliers") or {}
            bmi_cfg_lm = lifestyle_mults.get("bmi") or {}
            bmi_thresholds = bmi_cfg_lm.get("thresholds") or {
                "overweight": BMI_OVERWEIGHT_THRESHOLD,
                "obese": BMI_OBESE_THRESHOLD,
            }
            smoking_cfg_lm = lifestyle_mults.get("smoking") or {}

            bmi_cat: str | None = None
            if bmi >= bmi_thresholds.get("obese", BMI_OBESE_THRESHOLD):
                bmi_cat = "obese"
            elif bmi >= bmi_thresholds.get("overweight", BMI_OVERWEIGHT_THRESHOLD):
                bmi_cat = "overweight"

            # base_prev in yaml is the TARGET MARGINAL prevalence in the emitted
            # cohort (B-3). Rescale by the population-expected compound
            # multiplier so per-patient sampling preserves that marginal while
            # comorbidity + lifestyle multipliers still shape WHICH patients
            # get the condition. See population/README.md
            # "Marginal-preserving prevalence".
            sex_key = "male" if sex == "M" else "female"
            conditions: list[str] = []
            for code, spec in chronic_data.items():
                if spec.sex and spec.sex != sex:
                    continue  # e.g., BPH (N40) is male-only
                for (lo, hi), base_prev in spec.age_ranges.items():
                    if not (lo <= age <= hi):
                        continue
                    # Comorbidity correlation multiplier (from already-sampled conditions)
                    corr_mult = 1.0
                    for existing_code in conditions:
                        corr_mult *= (comorbidity_cfg.get(existing_code) or {}).get(code, 1.0)
                    # Lifestyle multipliers (per-patient realized values)
                    life_mult = 1.0
                    if bmi_cat:
                        life_mult *= (bmi_cfg_lm.get(bmi_cat) or {}).get(code, 1.0)
                    life_mult *= (smoking_cfg_lm.get(smoking_status) or {}).get(code, 1.0)
                    # Population-expected compound multiplier over (age, sex)
                    e_corr = _expected_comorbidity_multiplier(chronic_data, code, age, sex, comorbidity_cfg)
                    e_life = _expected_lifestyle_multiplier(demo, code, sex_key, age)
                    e_compound = e_corr * e_life
                    # Rescale base so E[per-patient prob] ≈ base_prev (the target
                    # marginal). Guard against pathological zero.
                    scaled_base = base_prev / e_compound if e_compound > 0.0 else base_prev
                    final_prev = min(1.0, scaled_base * corr_mult * life_mult)
                    if rng.random() < final_prev:
                        conditions.append(code)

            # Issue #957 augment_sex_bands: opposite-sex activation for a
            # previously-single-sex code (currently only C50 male ~1 % of
            # total). Sampled on a per-(patient, code) sub-RNG so the
            # master ``rng`` cursor is byte-identical to the pre-#957
            # path — cross-patient cascade cannot happen when an
            # augmentation is added or its probability tuned.
            for code, spec in chronic_data.items():
                aug_base = spec.augment_prevalence_at(age, sex)
                if aug_base <= 0.0:
                    continue
                if code in conditions:
                    continue  # already assigned via primary path (defensive)
                aug_rng = np.random.default_rng(
                    chronic_augment_sex_seed(pid, code)  # per-(patient, code) sub-seed
                )
                # Lifestyle + comorbidity multipliers use the same math as
                # the primary path; the only isolation change is the RNG
                # source.
                corr_mult = 1.0
                for existing_code in conditions:
                    corr_mult *= (comorbidity_cfg.get(existing_code) or {}).get(code, 1.0)
                life_mult = 1.0
                if bmi_cat:
                    life_mult *= (bmi_cfg_lm.get(bmi_cat) or {}).get(code, 1.0)
                life_mult *= (smoking_cfg_lm.get(smoking_status) or {}).get(code, 1.0)
                e_corr = _expected_comorbidity_multiplier(chronic_data, code, age, sex, comorbidity_cfg)
                e_life = _expected_lifestyle_multiplier(demo, code, sex_key, age)
                e_compound = e_corr * e_life
                scaled_base = aug_base / e_compound if e_compound > 0.0 else aug_base
                final_prev = min(1.0, scaled_base * corr_mult * life_mult)
                if aug_rng.random() < final_prev:
                    conditions.append(code)

            # Care seeking threshold (JP: lower = more willing)
            # RM-7e: care-seeking threshold from locale
            # (JP: 20% reflects 健診 culture; US: 30% baseline).
            # Issue #922 (session 91): the mean is now age-conditional so
            # the flat threshold is not artificially over-passing pediatric
            # well-child + immunization visits into the emitted cohort.
            # RNG-shape neutral — one `rng.normal(mean, sd)` call per person
            # regardless of which band matches.
            _cs = demo.get("care_seeking") or {}
            _cs_mean = _care_seeking_threshold_mean(demo, age)
            _cs_sd = float(_cs.get("threshold_sd", CARE_SEEKING_THRESHOLD_SD_DEFAULT))
            threshold = float(rng.normal(_cs_mean, _cs_sd))
            threshold = max(CARE_SEEKING_CLAMP_MIN, min(CARE_SEEKING_CLAMP_MAX, threshold))

            # Phone: generate mobile for adults
            mobile = _generate_phone(addr_data, "mobile", rng) if age >= MOBILE_PHONE_MIN_AGE else ""

            person = PersonRecord(
                person_id=pid,
                household_id=hh_id,
                age=age,
                sex=sex,
                date_of_birth=dob,
                family_name=member_surname.get("kanji", member_surname.get("name", "")),
                given_name=given.get("kanji", given.get("name", "")),
                phonetic=f"{member_surname.get('kana', '')} {given.get('kana', '')}".strip() or None,
                blood_type=blood_type,
                rh_factor=_derive_rh_factor(pid, country),
                postal_code=hh_addr.get("postal_code", ""),
                state=hh_addr.get("state", ""),
                city=hh_addr.get("city", ""),
                address_line=hh_addr.get("line", ""),
                phone_home=hh_phone_home if has_landline else "",
                phone_mobile=mobile if age >= MOBILE_PHONE_MIN_AGE else "",
                chronic_conditions=conditions,
                occupation=_sample_occupation(demo, age, sex, rng),
                bmi=bmi,
                smoking_status=smoking_status,
                alcohol_use=alcohol_use,
                care_seeking_threshold=threshold,
            )
            hh.members.append(person)
            registry.persons[pid] = person

        registry.households.append(hh)

    return registry


def generate_monthly_events(
    registry: PopulationRegistry,
    year: int,
    month: int,
    rng: np.random.Generator,
    country: str = "US",
    demo: dict | None = None,
) -> list[LifeEvent]:
    """Generate life events for one month across the population. All Phase 1 diseases."""
    events: list[LifeEvent] = []
    event_date = date(year, month, EVENT_MID_OF_MONTH_DAY)

    # Load country-specific epidemiology from locale
    if demo is None:
        demo = _load_demographics(country)
    incidence = demo.get("disease_incidence", {})
    seasonal = demo.get("seasonal_modifiers", {})
    risk_mults = demo.get("disease_risk_multipliers", {})

    for person in registry.persons.values():
        if not person.is_alive:
            continue

        # Lifestyle risk multiplier prep — computed once per person, outside per-disease loop
        lifestyle_lm = demo.get("lifestyle_risk_multipliers") or {}
        smoking_lm = lifestyle_lm.get("smoking") or {}
        bmi_lm_cfg = lifestyle_lm.get("bmi") or {}
        bmi_thresh_lm = bmi_lm_cfg.get("thresholds") or {
            "overweight": BMI_OVERWEIGHT_THRESHOLD,
            "obese": BMI_OBESE_THRESHOLD,
        }

        bmi_cat_lm: str | None = None
        if person.bmi >= float(bmi_thresh_lm.get("obese", BMI_OBESE_THRESHOLD)):
            bmi_cat_lm = "obese"
        elif person.bmi >= float(bmi_thresh_lm.get("overweight", BMI_OVERWEIGHT_THRESHOLD)):
            bmi_cat_lm = "overweight"

        # --- Data-driven disease event generation ---
        for disease_id, disease_spec in incidence.items():
            age_rates = disease_spec.get("age_rates", disease_spec.get("age_rates_among_hf", {}))
            if not age_rates:
                continue

            # Prerequisite check (e.g., HF exacerbation requires I50)
            prereq = disease_spec.get("prerequisite_condition")
            if prereq and prereq not in person.chronic_conditions:
                continue

            sex_ratio = disease_spec.get("sex_ratio_female", 1.0)
            disease_seasonal = seasonal.get(disease_id, {})
            disease_risk = risk_mults.get(disease_id, {})

            rate = _disease_monthly_rate_from_locale(
                person,
                month,
                age_rates,
                sex_ratio,
                disease_seasonal,
                disease_risk,
            )

            # Prior hospitalization for the same disease increases recurrence risk
            if hasattr(person, "hospitalization_history"):
                prior_same = [h for h in person.hospitalization_history if h.disease_id == disease_id]
                if prior_same:
                    rate *= PRIOR_HOSPITALIZATION_RECURRENCE_MULTIPLIER

            # Occupation-based risk multiplier (work-related injuries etc.)
            occ_mults = demo.get("occupation_risk_multipliers", {}).get(disease_id, {})
            if occ_mults and hasattr(person, "occupation"):
                # Default 0.2 for non-matching occupations: some residual risk
                # (e.g., office worker helping in warehouse, domestic accident)
                occ_mult = occ_mults.get(person.occupation, OCCUPATION_MISMATCH_FALLBACK_MULTIPLIER)
                rate *= float(occ_mult)

            # Lifestyle risk multipliers (smoking + BMI) — per-disease application
            smoking_mult_lm = float((smoking_lm.get(person.smoking_status) or {}).get(disease_id, 1.0))
            bmi_mult_lm = float((bmi_lm_cfg.get(bmi_cat_lm) or {}).get(disease_id, 1.0)) if bmi_cat_lm else 1.0
            rate *= smoking_mult_lm * bmi_mult_lm

            if rng.random() >= rate:
                continue

            # Severity from the disease-YAML distribution × comorbidity modifiers
            # (FP-SEV-MODEL, c2). The continuous score feeds the hospitalization gate
            # below and re-derives the same category via category_from_score.
            _category, severity = sample_severity(load_disease_protocol(disease_id), person, rng)

            # Hospitalization decision
            event_type = disease_spec.get("event_type", "acute_disease_onset")
            if disease_spec.get("always_hospitalize"):
                requires_hospital = True
            else:
                threshold = person.care_seeking_threshold
                # Age-based threshold modifier
                age_mods = disease_spec.get("hospitalization_threshold_modifier_by_age", {})
                if age_mods:
                    for age_str in sorted(age_mods.keys(), key=int, reverse=True):
                        if person.age >= int(age_str):
                            threshold *= float(age_mods[age_str])
                            break
                # Flat modifier
                flat_mod = disease_spec.get("hospitalization_threshold_modifier")
                if flat_mod is not None:
                    threshold *= float(flat_mod)
                requires_hospital = severity > threshold

            events.append(
                LifeEvent(
                    person_id=person.person_id,
                    event_type=event_type,
                    timestamp=event_date
                    + timedelta(days=int(rng.integers(EVENT_DAY_JITTER_START, EVENT_DAY_JITTER_END_EXCLUSIVE))),
                    severity=severity,
                    disease_id=disease_id,
                    requires_hospital=requires_hospital,
                    condition_type="known_disease",
                )
            )

        # --- Unknown-cause conditions ---
        unknown_cfg = demo.get("unknown_conditions", {})
        unknown_min_age = unknown_cfg.get("min_age", UNKNOWN_CONDITION_MIN_AGE_DEFAULT)
        unknown_base_rate = unknown_cfg.get("base_rate", UNKNOWN_CONDITION_BASE_RATE_DEFAULT)
        unknown_age_factor = unknown_cfg.get("age_factor", UNKNOWN_CONDITION_AGE_FACTOR_DEFAULT)
        unknown_patterns = unknown_cfg.get("patterns", UNKNOWN_CONDITION_PATTERNS_FALLBACK)
        if person.age >= unknown_min_age:
            unknown_rate = unknown_base_rate * (1.0 + (person.age - unknown_min_age) * unknown_age_factor)
            if rng.random() < unknown_rate:
                pattern = str(rng.choice(unknown_patterns))
                unk_severity = float(
                    rng.beta(UNKNOWN_CONDITION_SEVERITY_BETA_ALPHA, UNKNOWN_CONDITION_SEVERITY_BETA_BETA)
                )
                events.append(
                    LifeEvent(
                        person_id=person.person_id,
                        event_type="unknown_condition",
                        timestamp=event_date
                        + timedelta(days=int(rng.integers(EVENT_DAY_JITTER_START, EVENT_DAY_JITTER_END_EXCLUSIVE))),
                        severity=unk_severity,
                        disease_id=f"unknown_{pattern}",
                        requires_hospital=unk_severity > person.care_seeking_threshold,
                        condition_type="unknown",
                    )
                )

    # --- Post-processing: upgrade some known_disease events to mixed ---
    mixed_cfg = demo.get("mixed_conditions", {})
    mixed_min_age = mixed_cfg.get("min_age", MIXED_CONDITIONS_MIN_AGE_DEFAULT)
    mixed_min_chronic = mixed_cfg.get("min_chronic_conditions", MIXED_CONDITIONS_MIN_CHRONIC_DEFAULT)
    mixed_probability = mixed_cfg.get("probability", MIXED_CONDITIONS_PROBABILITY_DEFAULT)
    for event in events:
        if event.condition_type == "known_disease" and event.requires_hospital:
            evt_person = registry.persons.get(event.person_id)
            if (
                evt_person
                and evt_person.age >= mixed_min_age
                and len(evt_person.chronic_conditions) >= mixed_min_chronic
            ):
                if rng.random() < mixed_probability:
                    event.condition_type = "mixed"

    return events


def _disease_monthly_rate_from_locale(
    person: PersonRecord,
    month: int,
    age_rates: dict,
    sex_ratio_female: float,
    seasonal: dict,
    risk_multipliers: dict,
) -> float:
    """Calculate monthly disease rate from locale epidemiology data."""
    # Find age-appropriate incidence rate
    rate = 0.0
    for age_str, r in sorted(age_rates.items(), key=lambda x: int(x[0])):
        if person.age >= int(age_str):
            rate = float(r)
    # Sex adjustment
    if person.sex == "F":
        rate *= sex_ratio_female
    # Annual to monthly
    monthly = (rate / 100_000) / 12
    # Seasonal
    seasonal_mod = seasonal.get(month, seasonal.get(str(month), 1.0))
    monthly *= float(seasonal_mod)
    # Risk multipliers from chronic conditions
    for code, mult in risk_multipliers.items():
        if code in person.chronic_conditions:
            monthly *= float(mult)
    return monthly


def _sample_age_band(demo: dict, rng: np.random.Generator) -> tuple[int, int]:
    bands, probs = _parse_age_distribution(demo)
    idx = int(rng.choice(len(bands), p=normalize_probabilities(probs, fallback="raise")))
    return bands[idx]


def _sex_ratio_male_probability(demo: dict, age: int) -> float:
    """Return P(male) for a person of the given age, per the demographics YAML.

    Lookup order (Issue #741):
      1. ``sex_ratio.age_conditional[<band>]`` where <band> covers ``age``
      2. ``sex_ratio.male`` (top-level fallback)
      3. ``SEX_RATIO_MALE_DEFAULT`` (constant)

    Bands are inclusive ranges declared as ``"lo-hi"`` strings. The block
    is optional; locales that omit it collapse to the single-probability
    behaviour (RNG-shape neutral — the caller still issues one
    ``rng.random()`` per person regardless of which branch resolves).
    """
    sr = demo.get("sex_ratio") or {}
    age_cond = sr.get("age_conditional") or {}
    for band_str, prob in age_cond.items():
        lo_s, hi_s = str(band_str).split("-")
        if int(lo_s) <= age <= int(hi_s):
            return float(prob)
    return float(sr.get("male", SEX_RATIO_MALE_DEFAULT))


def _care_seeking_threshold_mean(demo: dict, age: int) -> float:
    """Return the care-seeking severity-threshold mean for a person of the given age.

    Lookup order (Issue #922):
      1. ``care_seeking.age_conditional[<band>]`` where <band> covers ``age``
         (bands are inclusive ``"lo-hi"`` strings; the ``"lo+"`` shorthand
         is also accepted for readability of open-ended elderly bands)
      2. ``care_seeking.threshold_mean`` (top-level fallback — the
         pre-Issue-#922 behaviour)
      3. ``CARE_SEEKING_THRESHOLD_MEAN_DEFAULT`` (constant)

    RNG-shape neutral — the caller still issues one ``rng.normal(mean, sd)``
    per person regardless of which branch resolves; only the ``mean``
    argument changes, so the RNG cursor advances identically for every
    seed.
    """
    cs = demo.get("care_seeking") or {}
    age_cond = cs.get("age_conditional") or {}
    for band_str, val in age_cond.items():
        raw = str(band_str)
        if raw.endswith("+"):
            lo_s = raw[:-1]
            if age >= int(lo_s):
                return float(val)
            continue
        lo_s, hi_s = raw.split("-")
        if int(lo_s) <= age <= int(hi_s):
            return float(val)
    return float(cs.get("threshold_mean", CARE_SEEKING_THRESHOLD_MEAN_DEFAULT))


# RhD prevalence — Rh-positive fraction by country. Derived via a stable
# hash of person_id (not the master RNG) so adding this field does not
# shift downstream RNG cursor and existing memoize snapshots stay valid.
# Real-world prevalence: JP ≈ 99.5% Rh-positive (Rh-negative is a
# clinically relevant rarity requiring anti-D IgG on pregnancy /
# transfusion). US ≈ 85% Rh-positive (higher Rh- fraction due to European
# ancestry mix). WHO / JP 日赤 published figures.
_RH_POSITIVE_FRACTION: dict[str, float] = {
    "JP": 0.995,
    "US": 0.85,
}


def _derive_rh_factor(person_id: str, country: str) -> str:
    """Return "+" (RhD positive) or "-" (negative), derived from a stable
    hash of ``person_id`` so the choice is deterministic per person AND
    does not consume the master RNG (memoize / F4 byte-identical guarantee
    preserved when this field was added post-facto).

    Country selects the Rh-positive fraction: JP 99.5%, US 85%.
    Unknown countries fall through to JP default (conservative — Rh-
    negative is the clinically-actionable state; over-emitting Rh+ is
    a lower-cost failure mode for a synthetic dataset).
    """
    import hashlib

    frac = _RH_POSITIVE_FRACTION.get("US" if country.upper() == "US" else "JP", 0.995)
    # 16-bit deterministic quantile from a stable hash. Salt with "rh"
    # so this derivation is independent from any other person_id-hashed
    # value future code might add.
    h = hashlib.sha256(f"{person_id}|rh".encode()).digest()
    quantile = int.from_bytes(h[:2], "big") / 65535.0
    return "+" if quantile < frac else "-"


def _sample_blood_type(demo: dict, rng: np.random.Generator) -> str:
    """Sample blood type using weighted probability from demographics.

    Routes YAML-sourced weights through normalize_probabilities(fallback="raise")
    to handle floating-point summation artifacts (e.g., 0.40+0.30+0.20+0.10
    sums to 0.9999999999999999 in float64, not exactly 1.0).
    """
    bt = demo.get("blood_type", BLOOD_TYPE_DEFAULT_DISTRIBUTION)
    keys = list(bt.keys())
    weights = normalize_probabilities([bt[k] for k in keys], fallback="raise")
    idx = int(rng.choice(len(keys), p=weights))
    return keys[idx]


def _load_name_data(country: str) -> dict:
    """Load name data from locale module."""
    from clinosim.locale.loader import load_names

    return load_names(country)


def _sample_surname(name_data: dict, rng: np.random.Generator) -> dict:
    """Sample a surname using weighted probability."""
    surnames = name_data.get("surnames", [])
    weights = normalize_probabilities([s["weight"] for s in surnames], fallback="raise")
    idx = int(rng.choice(len(surnames), p=weights))
    return surnames[idx]


def _sample_occupation(demo: dict, age: int, sex: str, rng: np.random.Generator) -> str:
    """Sample occupation category from demographics occupation_distribution.

    Issue #360 G7 (iris4h-ai 2026-07-22): the pre-fix helper collapsed
    every age ≤ ``student_max_age`` (default 14) to the single label
    ``"student"``. A 2-year-old rendered as "学生 / student" on JP UI
    is clinically nonsensical — iris4h-ai's Clinical Cockpit flagged
    the ``POP-000004 (2歳)`` example as untrusted. Split by
    developmental stage so the emitted occupation reads correctly on
    both US and JP charts.

    Age brackets (Japanese 学制 & US convention aligned):
      < 3:      "infant"                (乳児)
      3-5:      "preschool"             (未就学児)
      6-11:     "elementary_student"    (小学生)
      12-14:    "middle_school_student" (中学生)
      15-17:    "high_school_student"   (高校生)
      18-21:    existing student/working split
      22-64:    existing working-age distribution
      65+:      "retired"
    """
    occ_cfg = demo.get("occupation_distribution") or {}
    thresholds = occ_cfg.get("age_thresholds") or {}
    student_max = int(thresholds.get("student_max_age", 14))
    young_max = int(thresholds.get("young_adult_max_age", 21))
    young_prob = float(thresholds.get("young_adult_student_prob", 0.70))
    retirement = int(thresholds.get("retirement_min_age", 65))

    # Issue #360 G7 developmental-stage brackets: split the pre-fix
    # ``student_max`` (default 14) bucket into infant / preschool /
    # elementary / middle-school so a 2-year-old no longer emits as
    # ``student`` on JP charts. The upper boundary matches the pre-fix
    # ``age <= student_max`` gate exactly — no RNG state shift for
    # older ages (F4 memoize test guards against cross-cursor drift).
    if age <= student_max:
        if age < 3:
            return "infant"
        if age < 6:
            return "preschool"
        if age < 12:
            return "elementary_student"
        return "middle_school_student"
    if age >= retirement:
        return "retired"
    dist = occ_cfg.get("working_age") or {}
    if not dist:
        return "other"
    if age <= young_max and rng.random() < young_prob:
        return "student"
    keys = list(dist.keys())
    weights = normalize_probabilities([dist[k] for k in keys], fallback="raise")
    return str(rng.choice(keys, p=weights))


def _sample_given_name(name_data: dict, sex: str, rng: np.random.Generator) -> dict:
    """Sample a given name appropriate for sex."""
    key = "given_names_male" if sex == "M" else "given_names_female"
    names = name_data.get(key, [])
    weights = normalize_probabilities([n["weight"] for n in names], fallback="raise")
    idx = int(rng.choice(len(names), p=weights))
    return names[idx]


def generate_healthcare_calendar(
    registry: PopulationRegistry,
    year: int,
    country: str,
    rng: np.random.Generator,
) -> list[LifeEvent]:
    """Generate a year's healthcare calendar for ALL population members.

    This includes:
    - Chronic disease management visits (for everyone with chronic conditions)
    - Annual health screening (age 40+)
    - ED visits (non-admitted, from demographics config)

    Acute disease events are generated separately by generate_monthly_events().
    """
    events: list[LifeEvent] = []

    # Load follow-up schedules
    from clinosim.locale.loader import load_chronic_followup

    followup_data = load_chronic_followup()

    # F1: spawn one independent child generator per person instead
    # of consuming a single shared stream sequentially across the whole
    # population. Each person's own draw *count* varies with their own
    # age/sex/chronic_conditions (e.g. whether the flu-vaccination /
    # colonoscopy / mammography branches below draw at all), so with a single
    # shared stream, any change to ONE person's state shifts every
    # later-iterated person's stream position — cascading a change for one
    # patient into completely unrelated patients' calendar schedules. This
    # is the same AD-16 defect class the F1 phase-rng work fixes in
    # engine.py's own phases, just living one level deeper inside this
    # function. `Generator.spawn(n)` allocates independent, position-keyed
    # child streams up front (verified independent of how many draws the
    # parent made before spawning), so each person's calendar is stable
    # regardless of what happens to anyone else. Iteration order over
    # `registry.persons` is itself already stable and cursor-independent
    # (population generation doesn't depend on snapshot_date), so per-
    # position spawning is sufficient for cross-cursor determinism.
    persons = list(registry.persons.values())
    person_rngs = rng.spawn(len(persons)) if persons else []

    for person, prng in zip(persons, person_rngs):
        if not person.is_alive:
            continue

        # --- Pediatric encounters (Issue #760) ---
        # Placed BEFORE the `if not conditions_with_spec: continue` gate so
        # pediatric patients (who typically carry no chronic conditions in
        # `followup_data`) still receive their well-child / immunization
        # visits. Byte-diff neutral when the schedule is empty (foundation
        # pass 1 invariant, still exercised by
        # test_empty_schedule_returns_no_events_and_does_not_consume_rng).
        from clinosim.modules.pediatric.calendar import generate_pediatric_events

        events.extend(generate_pediatric_events(person, year, prng))

        # --- Chronic disease visits ---
        # Group conditions into combined visits (real patients see one doctor
        # for multiple conditions in a single visit)
        conditions_with_spec: list[tuple[str, dict]] = [
            (code, spec_) for code in person.chronic_conditions if (spec_ := followup_data.get(code)) is not None
        ]
        if not conditions_with_spec:
            continue

        # Use shortest interval as visit frequency (covers all conditions)
        shortest_interval = min(spec.get("follow_up_interval_months", 3) for _, spec in conditions_with_spec)
        # Cap: max 6 visits/year for chronic management
        max_visits = min(12 // shortest_interval, CHRONIC_VISITS_MAX_PER_YEAR)
        primary_code = conditions_with_spec[0][0]  # main condition for the visit

        month = int(prng.integers(1, min(shortest_interval + 1, CHRONIC_VISIT_INITIAL_MONTH_CAP_EXCLUSIVE)))
        visit_count = 0
        while month <= 12 and visit_count < max_visits:
            visit_date = date(year, month, int(prng.integers(EVENT_RANDOM_DAY_MIN, EVENT_RANDOM_DAY_MAX_EXCLUSIVE)))
            events.append(
                LifeEvent(
                    person_id=person.person_id,
                    event_type="chronic_visit",
                    timestamp=visit_date,
                    severity=0.0,
                    condition_type="chronic_followup",
                    disease_id=primary_code,
                    encounter_type="outpatient",
                    protocol_source=f"chronic_followup:{primary_code}",
                )
            )
            month += shortest_interval
            visit_count += 1

        # --- Annual health screening (age 40+) ---
        if person.age >= HEALTH_SCREENING_MIN_AGE:
            screening_month = int(prng.integers(HEALTH_SCREENING_MONTH_START, HEALTH_SCREENING_MONTH_END_EXCLUSIVE))
            screening_date = date(
                year, screening_month, int(prng.integers(EVENT_RANDOM_DAY_MIN, EVENT_RANDOM_DAY_MAX_EXCLUSIVE))
            )
            events.append(
                LifeEvent(
                    person_id=person.person_id,
                    event_type="health_screening",
                    timestamp=screening_date,
                    severity=0.0,
                    condition_type="screening",
                    disease_id="annual_health_screening",
                    encounter_type="outpatient",
                    protocol_source="screening:annual",
                )
            )

        # --- Flu vaccination (age 65+ or chronic conditions, Oct-Dec) ---
        if person.age >= FLU_VAX_ADULT_AGE_THRESHOLD or len(person.chronic_conditions) >= FLU_VAX_COMORBIDITY_MIN:
            if prng.random() < FLU_VAX_PROBABILITY:
                vax_month = int(prng.choice(FLU_VAX_MONTHS))
                events.append(
                    LifeEvent(
                        person_id=person.person_id,
                        event_type="chronic_visit",
                        timestamp=date(
                            year, vax_month, int(prng.integers(EVENT_RANDOM_DAY_MIN, EVENT_RANDOM_DAY_MAX_EXCLUSIVE))
                        ),
                        severity=0.0,
                        condition_type="screening",
                        disease_id="flu_vaccination",
                        encounter_type="outpatient",
                        protocol_source="encounter:flu_vaccination",
                    )
                )

        # --- Colonoscopy screening (age 50+, every 10 years → ~10% per year) ---
        if person.age >= COLONOSCOPY_MIN_AGE and prng.random() < COLONOSCOPY_PROBABILITY:
            events.append(
                LifeEvent(
                    person_id=person.person_id,
                    event_type="health_screening",
                    timestamp=date(
                        year,
                        int(prng.integers(RANDOM_MONTH_MIN, RANDOM_MONTH_MAX_EXCLUSIVE)),
                        int(prng.integers(EVENT_RANDOM_DAY_MIN, EVENT_RANDOM_DAY_MAX_EXCLUSIVE)),
                    ),
                    severity=0.0,
                    condition_type="screening",
                    disease_id="colonoscopy_screening",
                    encounter_type="outpatient",
                    protocol_source="encounter:colonoscopy_screening",
                )
            )

        # --- Mammography screening (women 40+, annual → ~60% participation) ---
        if person.sex == "F" and person.age >= MAMMOGRAPHY_MIN_AGE and prng.random() < MAMMOGRAPHY_PROBABILITY:
            events.append(
                LifeEvent(
                    person_id=person.person_id,
                    event_type="health_screening",
                    timestamp=date(
                        year,
                        int(prng.integers(RANDOM_MONTH_MIN, RANDOM_MONTH_MAX_EXCLUSIVE)),
                        int(prng.integers(EVENT_RANDOM_DAY_MIN, EVENT_RANDOM_DAY_MAX_EXCLUSIVE)),
                    ),
                    severity=0.0,
                    condition_type="screening",
                    disease_id="mammography_screening",
                    encounter_type="outpatient",
                    protocol_source="encounter:mammography_screening",
                )
            )

        # --- Diabetic retinopathy screening (DM patients, annual) ---
        if (
            DIABETIC_RETINOPATHY_ICD10_CODE in person.chronic_conditions
            and prng.random() < DIABETIC_RETINOPATHY_PROBABILITY
        ):
            events.append(
                LifeEvent(
                    person_id=person.person_id,
                    event_type="chronic_visit",
                    timestamp=date(
                        year,
                        int(prng.integers(RANDOM_MONTH_MIN, RANDOM_MONTH_MAX_EXCLUSIVE)),
                        int(prng.integers(EVENT_RANDOM_DAY_MIN, EVENT_RANDOM_DAY_MAX_EXCLUSIVE)),
                    ),
                    severity=0.0,
                    condition_type="screening",
                    disease_id="diabetic_retinopathy_screening",
                    encounter_type="outpatient",
                    protocol_source="encounter:diabetic_retinopathy_screening",
                )
            )

<<<<<<< HEAD
        # --- Perinatal delivery encounter (Issue #957 Tier-3-B) ---
        # For Z34-carrying women (chronic marker "actively pregnant during
        # sim window"), emit one delivery IMP encounter per year at a
        # scheduled month within the config-declared window. The scheduler
        # uses a per-(patient, year) sub-RNG so the calendar's shared
        # ``prng`` is NOT consumed — pre-existing calendar streams are
        # byte-identical whether the delivery scheduler runs or not.
        events.extend(_perinatal_delivery_events(person, year))

    return events


def _perinatal_delivery_events(person: PersonRecord, year: int) -> list[LifeEvent]:
    """Emit the perinatal event chain for a Z34-carrying pregnant woman:
    one ``delivery`` event + two ``postpartum`` outpatient follow-ups.

    RNG-neutrality contract: consumes ZERO calls on the caller's
    ``prng`` — the delivery month/day + postpartum jitter draws all
    use ``perinatal_delivery_seed(person_id, year)`` (sibling of
    ``chemotherapy_regimen_seed``). Adding this scheduler does NOT
    shift any pre-existing calendar event for any patient.

    Slice-2 semantics (Issue #957 Tier-3-B follow-up):
      * ``delivery`` — mother's IMP admission + newborn Patient chain
        (see ``simulator/perinatal.py::simulate_delivery_encounter``).
      * ``chronic_visit`` × 2 with ``condition_type="postpartum"`` —
        AMB obstetric follow-ups at ~1 week and ~4 weeks post-discharge
        (JSOG / ACOG standard postpartum care intervals). Fired as
        ``chronic_visit`` events so they route through the existing
        outpatient dispatch with a postpartum ``visit_reason``.

    Postpartum-visit month/day placement respects year boundaries:
    if the delivery falls in December, the postpartum visits are
    clamped to Dec 31 (they would otherwise land in the next sim
    year, out of scope for this cohort year). Downstream snapshot
    clamping in ``run_beta`` further clips events past the
    ``--end`` cursor.
    """
    if "Z34" not in person.chronic_conditions:
        return []
    from clinosim.locale.loader import load_perinatal_config
    from clinosim.seeding import perinatal_delivery_seed

    cfg = load_perinatal_config()
    sched = cfg.get("scheduling") or {}
    m_lo, m_hi = sched.get("delivery_month_range") or [4, 10]
    m_lo = int(m_lo)
    m_hi = int(m_hi)
    if m_lo < 1 or m_hi > 12 or m_lo > m_hi:
        return []
    rng = np.random.default_rng(perinatal_delivery_seed(person.person_id, year))
    delivery_month = int(rng.integers(m_lo, m_hi + 1))
    delivery_day = int(rng.integers(EVENT_RANDOM_DAY_MIN, EVENT_RANDOM_DAY_MAX_EXCLUSIVE))
    delivery_date = date(year, delivery_month, delivery_day)

    # Pregnancy outcome resolution — a Z34 pregnancy may end in abortion
    # (spontaneous or induced, age-gated) instead of delivery. Consumes
    # its OWN per-(mother, year) sub-RNG (isolated from the delivery-
    # date draw) so tuning abortion rates does not shift delivery day.
    from clinosim.simulator.perinatal import resolve_pregnancy_outcome

    outcome, discharge_dx = resolve_pregnancy_outcome(person.person_id, person.age, year)
    if outcome == "abortion":
        return [
            LifeEvent(
                person_id=person.person_id,
                event_type="abortion",
                timestamp=delivery_date,  # reuse the scheduled date for the abortion encounter
                severity=0.0,
                condition_type="pregnancy_termination",
                disease_id=discharge_dx,  # O03.9 or O04.5
                encounter_type="outpatient",
                protocol_source="perinatal:abortion",
            )
        ]

    events: list[LifeEvent] = [
        LifeEvent(
            person_id=person.person_id,
            event_type="delivery",
            timestamp=delivery_date,
            severity=0.0,
            condition_type="perinatal_delivery",
            disease_id="Z34",
            encounter_type="inpatient",
            protocol_source="perinatal:delivery",
        )
    ]

    # Postpartum follow-ups: ~1 week (jittered 5-10 d) and ~4 week
    # (jittered 21-35 d) post-discharge. Fired via chronic_visit so
    # they hit the standard outpatient dispatch; disease_id "Z39"
    # ("encounter for maternal postpartum care") is the WHO ICD-10
    # postpartum-care code and displays correctly in the ICD registry.
    postpartum_offsets_days = (7, 28)
    for offset in postpartum_offsets_days:
        pp_dt = delivery_date + timedelta(days=offset)
        # Year-boundary clamp: keep the event inside the calendar's
        # sim year to avoid emitting into unrelated cohorts.
        if pp_dt.year != year:
            pp_dt = date(year, 12, 31)
        events.append(
            LifeEvent(
                person_id=person.person_id,
                event_type="chronic_visit",
                timestamp=pp_dt,
                severity=0.0,
                condition_type="postpartum",
                disease_id="Z39",  # WHO ICD-10 encounter for postpartum care
                encounter_type="outpatient",
                protocol_source="perinatal:postpartum",
            )
        )
=======
        # --- Chemotherapy cycle visits (Issue #957 Tier-3-A) ---
        # For chronic-carrier patients of cancer codes with an assigned
        # cycle-based regimen (FOLFOX q14d, CarboPem q21d, Trastuzumab q3w,
        # LHRH q28d), emit chemo_visit events at the regimen's cycle
        # cadence. Selection is per-patient deterministic (sub-RNG keyed
        # off patient_id + salt) so it is RNG-shape neutral against the
        # calendar's ``prng`` — pre-existing patients' non-chemo events
        # are byte-identical whether this block runs or not.
        events.extend(_chemo_cycle_events(person, year))

>>>>>>> 3e7ebcd499 (feat(oncology): chemotherapy cycle scheduling (Tier-3-A slice 1) — partial #957)
    return events


def _chemo_cycle_events(person: PersonRecord, year: int) -> list[LifeEvent]:
    """Emit chemo_visit LifeEvents for one person's active chemo regimen(s).

    RNG-neutrality contract: consumes ZERO calls on the caller's ``prng`` —
    every random draw uses ``chemotherapy_regimen_seed(person_id, cancer_code)``
    (a per-patient / per-cancer-code deterministic sub-RNG, sibling of
    the RT-Procedure emit pattern). YAML edits to ``chemo_regimens.yaml``
    therefore never cascade into unrelated patients' calendar streams.

    Design (slice-1): one regimen per cancer code; the assignment table
    is a simple Bernoulli draw against the code's ``probability``. If
    the draw succeeds, the patient carries that regimen for the whole
    year and cycles fire at the regimen's ``cycle_interval_days``
    starting from a random Day-1 offset in the first cycle window,
    capped by ``course_cycles`` (per-year cap = min(course_cycles,
    365 / cycle_interval_days)).
    """
    from clinosim.locale.loader import load_chemo_regimens
    from clinosim.seeding import chemotherapy_regimen_seed

    data = load_chemo_regimens()
    regimens = data.get("regimens") or {}
    by_cancer = data.get("by_cancer") or {}
    if not regimens or not by_cancer:
        return []

    out: list[LifeEvent] = []
    for cancer_code in person.chronic_conditions:
        assignments = by_cancer.get(cancer_code) or []
        if not assignments:
            continue
        chemo_rng = np.random.default_rng(chemotherapy_regimen_seed(person.person_id, cancer_code))
        # Bernoulli assignment: draw once, iterate the ranked list until a
        # probability envelope matches. Residual mass = "no active regimen".
        u = float(chemo_rng.random())
        picked_name = ""
        cumulative = 0.0
        for entry in assignments:
            cumulative += float(entry.get("probability", 0.0) or 0.0)
            if u < cumulative:
                picked_name = str(entry.get("regimen") or "")
                break
        if not picked_name or picked_name not in regimens:
            continue
        regimen = regimens[picked_name]
        interval = int(regimen.get("cycle_interval_days") or 0)
        if interval <= 0:
            continue
        course_cycles = int(regimen.get("course_cycles") or 0) or (365 // interval)
        max_cycles_this_year = min(course_cycles, max(1, 365 // interval))
        # Day-1 offset within the first cycle window
        day_offset = int(chemo_rng.integers(1, interval + 1))
        cycle_start = date(year, 1, 1) + timedelta(days=day_offset - 1)
        for cycle_idx in range(max_cycles_this_year):
            visit_day = cycle_start + timedelta(days=interval * cycle_idx)
            if visit_day.year != year:
                break
            out.append(
                LifeEvent(
                    person_id=person.person_id,
                    event_type="chemo_visit",
                    timestamp=visit_day,
                    severity=0.0,
                    condition_type="chemo_infusion",
                    disease_id=cancer_code,
                    encounter_type="outpatient",
                    protocol_source=f"chemo_regimens:{picked_name}",
                )
            )
    return out


def _generate_household_address(addr_data: dict, rng: np.random.Generator) -> dict:
    """Generate a household address from locale address data."""
    cities = addr_data.get("cities", [])
    if not cities:
        return {"postal_code": "", "state": "", "city": "", "line": ""}

    probs = normalize_probabilities([c.get("weight", 1) for c in cities], fallback="raise")
    city_data = cities[int(rng.choice(len(cities), p=probs))]

    city = city_data.get("city", "")
    state = city_data.get("prefecture", addr_data.get("state", ""))
    zips = city_data.get("zips", ["00000"])
    postal_code = str(rng.choice(zips))

    country = addr_data.get("country", "US")
    if is_jp(country):
        towns = addr_data.get("towns", ["本町"])
        town = str(rng.choice(towns))
        chome = int(rng.integers(JP_ADDRESS_CHOME_MIN, JP_ADDRESS_CHOME_MAX_EXCLUSIVE))
        banchi = int(rng.integers(JP_ADDRESS_BANCHI_MIN, JP_ADDRESS_BANCHI_MAX_EXCLUSIVE))
        go = int(rng.integers(JP_ADDRESS_GO_MIN, JP_ADDRESS_GO_MAX_EXCLUSIVE))
        line = f"{town}{chome}丁目{banchi}-{go}"
        if rng.random() < addr_data.get("apartment_probability", JP_ADDRESS_APARTMENT_PROBABILITY_DEFAULT):
            apt_names = addr_data.get("apartment_names", ["マンション"])
            apt = str(rng.choice(apt_names))
            room = int(rng.integers(JP_ADDRESS_APARTMENT_ROOM_MIN, JP_ADDRESS_APARTMENT_ROOM_MAX_EXCLUSIVE))
            line += f" {apt}{room}"
    else:
        streets = addr_data.get("street_names", ["Main St"])
        street = str(rng.choice(streets))
        num = int(rng.integers(US_ADDRESS_STREET_NUMBER_MIN, US_ADDRESS_STREET_NUMBER_MAX_EXCLUSIVE))
        line = f"{num} {street}"
        if rng.random() < addr_data.get("apartment_probability", US_ADDRESS_APARTMENT_PROBABILITY_DEFAULT):
            apt_num = int(rng.integers(US_ADDRESS_APARTMENT_NUMBER_MIN, US_ADDRESS_APARTMENT_NUMBER_MAX_EXCLUSIVE))
            line += f", Apt {apt_num}"

    return {"postal_code": postal_code, "state": state, "city": city, "line": line}


def _generate_phone(addr_data: dict, phone_type: str, rng: np.random.Generator) -> str:
    """Generate a phone number from locale phone patterns."""
    phone_cfg = addr_data.get("phone", {})
    country = addr_data.get("country", "US")

    if is_jp(country):
        if phone_type == "mobile":
            prefixes = phone_cfg.get("mobile_prefix", ["090"])
            prefix = str(rng.choice(prefixes))
            mid = f"{int(rng.integers(PHONE_4DIGIT_BLOCK_MIN, PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE)):04d}"
            last = f"{int(rng.integers(PHONE_4DIGIT_BLOCK_MIN, PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE)):04d}"
            return f"{prefix}-{mid}-{last}"
        else:
            areas = phone_cfg.get("area_codes_landline", ["03"])
            area = str(rng.choice(areas))
            if area == "03":
                exchange = f"{int(rng.integers(PHONE_4DIGIT_BLOCK_MIN, PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE)):04d}"
                number = f"{int(rng.integers(PHONE_4DIGIT_BLOCK_MIN, PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE)):04d}"
                return f"{area}-{exchange}-{number}"
            else:
                exchange_int = int(
                    rng.integers(
                        JP_PHONE_LANDLINE_NON_TOKYO_EXCHANGE_MIN,
                        JP_PHONE_LANDLINE_NON_TOKYO_EXCHANGE_MAX_EXCLUSIVE,
                    )
                )
                exchange = f"{exchange_int:03d}"
                number = f"{int(rng.integers(PHONE_4DIGIT_BLOCK_MIN, PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE)):04d}"
                return f"{area}-{exchange}-{number}"
    else:
        if phone_type == "mobile":
            areas = phone_cfg.get("mobile_prefix", ["617"])
        else:
            areas = phone_cfg.get("area_codes", ["617"])
        area = str(rng.choice(areas))
        exchange = f"{int(rng.integers(US_PHONE_EXCHANGE_MIN, US_PHONE_EXCHANGE_MAX_EXCLUSIVE)):03d}"
        number = f"{int(rng.integers(PHONE_4DIGIT_BLOCK_MIN, PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE)):04d}"
        return f"({area}) {exchange}-{number}"
