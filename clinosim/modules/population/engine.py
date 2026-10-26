"""Population engine — v0.1-beta: catchment area generation + life events.

Generates a lightweight population registry (Layer 1), runs monthly life events,
and produces care-seeking decisions that trigger hospital encounters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from clinosim.modules._shared import normalize_probabilities
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.disease.severity import sample_severity
from clinosim.modules.population._chronic import (
    ChronicConditionSpec as ChronicConditionSpec,
)
from clinosim.modules.population._demographics import (
    _care_seeking_threshold_mean as _care_seeking_threshold_mean,
)
from clinosim.modules.population._demographics import (
    _derive_ethnicity as _derive_ethnicity,
)
from clinosim.modules.population._demographics import (
    _derive_race as _derive_race,
)
from clinosim.modules.population._demographics import (
    _derive_rh_factor as _derive_rh_factor,
)
from clinosim.modules.population._demographics import (
    _disease_monthly_rate_from_locale as _disease_monthly_rate_from_locale,
)
from clinosim.modules.population._demographics import (
    _load_demographics as _load_demographics,
)
from clinosim.modules.population._demographics import (
    _parse_age_distribution as _parse_age_distribution,
)
from clinosim.modules.population._demographics import (
    _sample_age_band as _sample_age_band,
)
from clinosim.modules.population._demographics import (
    _sample_blood_type as _sample_blood_type,
)
from clinosim.modules.population._demographics import (
    _sex_ratio_male_probability as _sex_ratio_male_probability,
)
from clinosim.modules.population._identity import (
    _generate_household_address as _generate_household_address,
)
from clinosim.modules.population._identity import (
    _generate_phone as _generate_phone,
)
from clinosim.modules.population._identity import (
    _load_name_data as _load_name_data,
)
from clinosim.modules.population._identity import (
    _sample_given_name as _sample_given_name,
)
from clinosim.modules.population._identity import (
    _sample_occupation as _sample_occupation,
)
from clinosim.modules.population._chemo import (
    _chemo_cycle_events as _chemo_cycle_events,
)
from clinosim.modules.population._chemo import (
    pick_active_chemo_regimen as pick_active_chemo_regimen,
)
from clinosim.modules.population._identity import (
    _sample_surname as _sample_surname,
)
from clinosim.modules.population._pregnancy import (
    _PERINATAL_STAGE_COUNTERS as _PERINATAL_STAGE_COUNTERS,
)
from clinosim.modules.population._pregnancy import (
    _PREGNANCY_ELIGIBLE_MAX_AGE as _PREGNANCY_ELIGIBLE_MAX_AGE,
)
from clinosim.modules.population._pregnancy import (
    _PREGNANCY_ELIGIBLE_MIN_AGE as _PREGNANCY_ELIGIBLE_MIN_AGE,
)
from clinosim.modules.population._pregnancy import (
    _annual_conception_rate as _annual_conception_rate,
)
from clinosim.modules.population._pregnancy import (
    _perinatal_stage_incr as _perinatal_stage_incr,
)
from clinosim.modules.population._pregnancy import (
    _pregnancy_lifecycle_events as _pregnancy_lifecycle_events,
)
from clinosim.modules.population._chronic import (
    _bmi_category_probabilities as _bmi_category_probabilities,
)
from clinosim.modules.population._chronic import (
    _expected_comorbidity_multiplier as _expected_comorbidity_multiplier,
)
from clinosim.modules.population._chronic import (
    _expected_lifestyle_multiplier as _expected_lifestyle_multiplier,
)
from clinosim.modules.population._chronic import (
    _parse_chronic_prevalence as _parse_chronic_prevalence,
)
from clinosim.modules.population._chronic import (
    _smoking_status_probabilities as _smoking_status_probabilities,
)
from clinosim.modules.population._chronic import (
    _target_prev_at_age_legacy as _target_prev_at_age_legacy,
)
from clinosim.modules.population._household_thresholds import (
    AVG_HOUSEHOLD_SIZE_DEFAULT,
    DOB_DAY_MAX_EXCLUSIVE,
    DOB_DAY_MIN,
    HOUSEHOLD_LANDLINE_PROBABILITY_DEFAULT,
    HOUSEHOLD_SIZE_WEIGHTED_CHOICES,
    WIFE_KEEPS_MAIDEN_PROBABILITY_DEFAULT,
)
from clinosim.modules.population._pediatric_anthropometry import (
    pediatric_bmi_params as _peds_bmi_params,
)
from clinosim.modules.population._pediatric_anthropometry import (
    pediatric_upper_age as _peds_upper_age,
)
from clinosim.modules.population._population_thresholds import (
    ALCOHOL_FALLBACK_LABELS,
    ALCOHOL_FALLBACK_PROBS,
    BMI_CLAMP_DEFAULT,
    BMI_MEAN_FEMALE_DEFAULT,
    BMI_MEAN_MALE_DEFAULT,
    BMI_MORBID_OBESITY_THRESHOLD,
    BMI_OBESE_THRESHOLD,
    BMI_OVERWEIGHT_THRESHOLD,
    BMI_STD_DEFAULT,
    CARE_SEEKING_CLAMP_MAX,
    CARE_SEEKING_CLAMP_MIN,
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
    COLONOSCOPY_MAX_AGE,
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
    HEALTH_SCREENING_MAX_AGE,
    HEALTH_SCREENING_MIN_AGE,
    HEALTH_SCREENING_MONTH_END_EXCLUSIVE,
    HEALTH_SCREENING_MONTH_START,
    LEGAL_ADULT_AGE,
    MAMMOGRAPHY_MAX_AGE,
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
from clinosim.types.population import (
    HospitalizationSummary,
    LifeEvent,
    PersonRecord,
)

__all__ = [
    "CARE_SEEKING_CLAMP_MAX",
    "CARE_SEEKING_CLAMP_MIN",
    "CARE_SEEKING_THRESHOLD_SD_DEFAULT",
    "HospitalizationSummary",
    "LifeEvent",
    "PersonRecord",
]

# META #957 Incr 1: ICD codes that appear in demographics ``chronic_prevalence``
# yaml for RNG-cursor placement but that represent time-boxed states rather
# than truly chronic diseases. Their Bernoulli draw in the chronic sampling
# loop is CONSUMED (to preserve cursor byte-identity for all codes iterated
# after them) but the code is NOT appended to ``PersonRecord.chronic_conditions``.
#
# - Z34 (encounter for supervision of normal pregnancy): tracked as an
#   OPEN ``TemporalStatePeriod`` on ``person.state_periods`` while the
#   pregnancy is active; the pregnancy-lifecycle generator handles it.
# - Z37 (outcome of delivery): derived by the FHIR emit adapter from
#   ``state_history("pregnancy")`` entries with ``outcome="delivered"``.
#   This replaces the pre-Incr-1 s95-z37 "chronic proxy" past-birth
#   marker, upgrading it from an independently-sampled Bernoulli to a
#   biology-consistent record of the woman's actual delivered
#   pregnancies (one Z37 problem-list-item per delivered period).
_STATE_PERIOD_CHRONIC_CODES = frozenset({"Z34", "Z37"})


@dataclass
class Household:
    household_id: str
    members: list[PersonRecord] = field(default_factory=list)
    region: str = "urban"
    # Issue #1581 — intra-household latent for identity-timeline sampling.
    # `assign_identities` stamps this on each household from a shared
    # `rng.standard_normal()` draw so later per-person entry points (e.g.
    # when a newborn joins the household mid-sim) can re-use the SAME
    # latent and preserve the intra-household card-holding correlation
    # the batch pass established. ``None`` means ``assign_identities``
    # has not run yet for this household (e.g. test fixture that bypasses
    # the enricher) — the per-person entry falls back to a 0.0 latent
    # (no correlation).
    identity_latent: float | None = None


@dataclass
class PopulationRegistry:
    households: list[Household] = field(default_factory=list)
    persons: dict[str, PersonRecord] = field(default_factory=dict)
    # Snapshot of person_ids present at the end of initial population
    # generation (Issue #1564 Phase 1). Any pid in `.persons` that is not
    # in this set was added mid-simulation (e.g. a newborn registered by
    # `clinosim.modules.population.newborn.register_newborn`). Downstream
    # code uses this to iterate initial persons under their original RNG
    # spawn shape (preserving byte-identity) and treat added persons as a
    # separate stream with their own derived sub-seeds.
    initial_person_ids: set[str] = field(default_factory=set)

    def get_person(self, person_id: str) -> PersonRecord | None:
        return self.persons.get(person_id)

    @property
    def total_persons(self) -> int:
        return len(self.persons)


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
            # Issue #1774: age-0 initial-cohort patients had DOB sampled in
            # ``base_year`` with random month/day, so ~50 % landed with DOB
            # after sim-start (Jan 1 of base_year) — semantically wrong
            # (they are "cohort members at sim-start", not future
            # perinatal-event newborns), and the downstream filter
            # ``pid.endswith("-BABY")`` systematically missed these 120 /
            # p=10k patients because their id was ``POP-NNNNNN`` (initial-
            # cohort pattern) not ``POP-NNNNNN-BABY`` (perinatal pattern).
            # Fix: for age==0, shift DOB year back one so DOB is always in
            # ``base_year - 1`` — the baby is unambiguously already born at
            # sim-start, which matches real-cohort snapshot semantics.
            # RNG-neutral: same two draws (month + day) regardless of age.
            _dob_year = base_year - age - 1 if age == 0 else base_year - age
            dob = date(
                _dob_year,
                int(rng.integers(RANDOM_MONTH_MIN, RANDOM_MONTH_MAX_EXCLUSIVE)),
                int(rng.integers(DOB_DAY_MIN, DOB_DAY_MAX_EXCLUSIVE)),
            )
            blood_type = _sample_blood_type(demo, rng)

            # BMI and height from physiology section
            phys = demo.get("physiology") or {}
            bmi_cfg = phys.get("bmi") or {}
            ht_cfg = phys.get("height_cm") or {}
            sex_key = "male" if sex == "M" else "female"

            # Pediatric branch (age < adult_path_min_age_years): sample
            # BMI from the growth-chart median at this age / sex instead
            # of the adult-only distribution. Pre-fix a 4-year-old would
            # inherit the adult mean (~26) and the activator then paired
            # it with an adult height, giving a stored weight ~75 kg —
            # physically impossible. One rng.normal draw either way, so
            # the master-stream shape is preserved.
            peds_bmi = _peds_bmi_params(country, sex, age) if age < _peds_upper_age() else None
            if peds_bmi is not None:
                bmi_mean = peds_bmi["mean"]
                bmi_std = peds_bmi["std"]
                bmi_clamp = bmi_cfg.get("clamp", BMI_CLAMP_DEFAULT)
            else:
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
                        # META #957 Incr 1: Z34 (encounter for supervision of
                        # normal pregnancy) and Z37 (outcome of delivery) are
                        # temporal-state markers, not chronic conditions.
                        # The Bernoulli draw is CONSUMED to preserve the rng
                        # cursor byte-identity for non-obstetric codes iterated
                        # after these entries; the append is skipped so no
                        # problem-list-item is emitted from chronic_conditions.
                        # Pregnancy state lives in ``person.state_periods`` via
                        # the pregnancy-lifecycle generator; Z37 past-birth
                        # marker is derived from state_history in the FHIR
                        # emit adapter.
                        if code in _STATE_PERIOD_CHRONIC_CODES:
                            continue
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
                    if code in _STATE_PERIOD_CHRONIC_CODES:
                        continue  # temporal-state markers — see primary loop
                    conditions.append(code)

            # Clinical-coherence mutex: F33 (recurrent depressive disorder)
            # subsumes F32 (depressive episode, single) per ICD-10-CM
            # §F30-F39. Both are drawn independently in the prevalence
            # loop above (``F32`` ~10-13 %, ``F33`` ~3-4 % in US) so a
            # non-trivial fraction of adults land with both. The mutex is
            # applied AFTER both Bernoulli draws so the RNG cursor is
            # byte-identical to the pre-mutex path — only the resulting
            # ``conditions`` list is filtered, not the random stream.
            # See ``clinosim/modules/population/condition_mutex.py``.
            from clinosim.modules.population.condition_mutex import (
                apply_depression_mutex,
            )

            apply_depression_mutex(conditions)

            # Issue #1126 (F-1 Obesity): BMI-derived Condition insertion.
            # Rationale: E66 has ~100 % clinical correlation with BMI ≥ 30 per
            # ICD-10-CM diagnostic criteria. Sampling E66 independently from a
            # prevalence YAML would produce nonsensical combinations (BMI-42
            # patient without E66, or BMI-22 patient with E66). Instead derive
            # deterministically from the already-generated BMI. RNG-neutral:
            # no rng draw here, only a threshold check. Inserted AFTER the
            # ``chronic_prevalence`` + ``augment_sex_bands`` loops so the
            # marginal-preserving rescale (which uses E[compound] over
            # chronic_prevalence codes only) is not perturbed.
            # See META #1137 for design authority.
            #
            # Issue #1284: age-gate the E66 dispatch. Adult BMI thresholds
            # (25/30/40) are not the correct pediatric coding practice —
            # ICD-10-CM pairs pediatric obesity with `Z68.51`–`Z68.54`
            # (BMI-for-age percentile) rather than the adult-oriented E66
            # cascade, and the underlying BMI sampler currently emits
            # adult-scaled values for all ages (a p=10k s=354 audit
            # counted 15 toddlers aged 2-5 with E66.01 "morbid obesity",
            # 52 US pediatric patients with any E66.01, and 881 US
            # pediatric patients with any E66 code). Skip the E66
            # dispatch entirely below :data:`LEGAL_ADULT_AGE` (=20 — the
            # existing adult-boundary constant already used for the
            # lifestyle-attribute gates above). A future follow-up in
            # the metabolic/ module (META #1137) can layer proper
            # `Z68.5x` BMI-for-age emission plus CDC-percentile BMI
            # sampling on top; this change is the scope-disciplined bug
            # fix that eliminates the physiologically-impossible peds
            # E66.01 rows.
            if age >= LEGAL_ADULT_AGE:
                if bmi >= BMI_MORBID_OBESITY_THRESHOLD:
                    conditions.append("E66.01")  # Morbid (severe) obesity, BMI ≥ 40
                elif bmi >= BMI_OBESE_THRESHOLD:
                    conditions.append("E66.9")  # Obesity, unspecified, BMI ≥ 30
                elif bmi >= BMI_OVERWEIGHT_THRESHOLD:
                    # Issue #1272: complete the 3-band ICD-10-CM E66 dispatch.
                    # BMI 25.0-29.9 is the overweight band (~30 % of US adults,
                    # ~20 % of JP adults). Pre-#1272 no ICD Condition was emitted
                    # for this band, so downstream analytics keying on E66.3
                    # saw an empty cohort even though the BMI Observation
                    # itself was correctly emitted. Same 3-band split #1126
                    # declared in the metabolic-cluster scope (see META #1137).
                    conditions.append("E66.3")  # Overweight, BMI 25-29.9

            # Issue #1134 (Substance Use): SDOH-derived Condition insertion.
            # Rationale: ``smoking_status`` / ``alcohol_use`` are already
            # sampled attributes on PersonRecord (SDOH social-history
            # Observation codes). Cross-resource consistency requires that
            # patients labeled ``current`` smoker or ``heavy`` drinker also
            # carry an ICD chronic Condition (F17.210 nicotine dependence /
            # F10.20 alcohol dependence uncomplicated). Analytics that
            # filter Conditions for smoking-related risk were previously
            # blind to the SDOH-encoded classification.
            # Deterministic (derives from already-sampled attributes), no
            # rng draw → RNG-neutral. Same insertion phase as E66 (after
            # chronic loops, before care-seeking threshold).
            # See META #1137 for design authority.
            if smoking_status == "current":
                conditions.append("F17.210")  # Nicotine dependence, cigarettes, uncomplicated
            if alcohol_use == "heavy":
                conditions.append("F10.20")  # Alcohol dependence, uncomplicated

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
                # Issue #1581 — race / ethnicity derived from a stable
                # hash of person_id so this field addition is RNG-
                # neutral (no master-stream shift). The activator still
                # falls back to its original per-call sampling for test
                # fixtures that bypass the initial cohort generator.
                race=_derive_race(pid, demo),
                ethnicity=_derive_ethnicity(pid, demo),
            )
            # Issue #1581 Phase C.3 — sample single-gene carrier
            # status for every catalogued disease. RNG-neutral (SHA
            # of person_id + disease code), so this field addition
            # does not shift any existing master stream. Affected
            # persons get the ICD code appended to chronic_conditions.
            from clinosim.locale.loader import load_single_gene_diseases
            from clinosim.modules.population.single_gene_inheritance import (
                apply_initial_carrier_sampling,
            )

            _sgd_catalog = (load_single_gene_diseases() or {}).get("single_gene_diseases") or {}
            if _sgd_catalog:
                _sgd_affected = apply_initial_carrier_sampling(person, _sgd_catalog)
                for _affected_code in _sgd_affected:
                    if _affected_code not in person.chronic_conditions:
                        person.chronic_conditions.append(_affected_code)
            # Phase 1 longitudinal subsystem (Issue #1695) — seed each
            # person's longitudinal_history at the sim-start year so
            # per-encounter emit (physiology / activator) can read via
            # ``state_at`` from year 1 onward. Non-DM persons get an
            # empty snapshot (scope gate drops the HbA1c attribute);
            # Phase 2 / 3 attributes populate additional continuous
            # latents / stages / events here when they land.
            from clinosim.modules.longitudinal.engine import initial_snapshot
            from clinosim.modules.population.aging import aging_sub_seed

            _ls_rng = np.random.default_rng(aging_sub_seed(person.person_id, base_year, "longitudinal:init"))
            initial_snapshot(person, year=base_year, init_rng=_ls_rng)
            # Phase 3 longitudinal (Issue #1705): seed the per-person
            # BMI drift chain from the just-generated Layer-1 bmi value
            # so the sim-start snapshot's continuous["bmi"] matches
            # person.bmi exactly, instead of resampling from the yaml's
            # dummy initial distribution. Only adults participate in
            # BMI drift (yaml's requires_age_band: [18, 120]).
            if person.longitudinal_history and person.age >= 18:
                person.longitudinal_history[-1].continuous["bmi"] = float(person.bmi)
            hh.members.append(person)
            registry.persons[pid] = person

        registry.households.append(hh)

    # Issue #1564 Phase 1: snapshot the initial person set so persons
    # added mid-simulation (e.g. newborns from `register_newborn`) can be
    # distinguished from the initial cohort. Deterministic — same pids as
    # we just inserted into `registry.persons`.
    registry.initial_person_ids = set(registry.persons.keys())

    return registry


def generate_monthly_events(
    registry: PopulationRegistry,
    year: int,
    month: int,
    rng: np.random.Generator,
    country: str = "US",
    demo: dict | None = None,
) -> list[LifeEvent]:
    """Generate life events for one month across the population. All Phase 1 diseases.

    Iterates every person in the registry. Newborns registered mid-sim
    (perinatal delivery handler → ``register_newborn``) are picked up
    on the NEXT month's call automatically once Issue #1596 Step 2
    collapsed generation + dispatch into the same per-month loop — no
    ``person_filter`` kwarg is required (Step 4 removed it).
    """
    events: list[LifeEvent] = []
    event_date = date(year, month, EVENT_MID_OF_MONTH_DAY)

    # Load country-specific epidemiology from locale
    if demo is None:
        demo = _load_demographics(country)
    incidence = demo.get("disease_incidence", {})
    seasonal = demo.get("seasonal_modifiers", {})
    risk_mults = demo.get("disease_risk_multipliers", {})

    # Perf (2026-10-18): the per-call ``sorted(age_rates.items(), key=int)``
    # inside ``_disease_monthly_rate_from_locale`` cost 12s cumulative on
    # a p=2000 5-year profile (3.2M calls × ~5µs sort of a 5-10 entry
    # dict). Pre-sort once per disease here, outside the N_persons loop,
    # so the per-call cost drops to a linear walk over an immutable list
    # of ``(int age_lo, float base_rate)`` tuples.
    sorted_age_rates_by_disease: dict[str, list[tuple[int, float]]] = {}
    for _d_id, _d_spec in incidence.items():
        _ar = _d_spec.get("age_rates", _d_spec.get("age_rates_among_hf", {}))
        if _ar:
            sorted_age_rates_by_disease[_d_id] = sorted(
                ((int(k), float(v)) for k, v in _ar.items()),
                key=lambda x: x[0],
            )

    for person in registry.persons.values():
        # C11g-3: honor natural death date_of_death alongside in-hospital
        # is_alive boolean — the acute disease event date is exactly
        # ``event_date`` for this month, so we can filter precisely.
        # Persons dying in a prior month never fire further events;
        # persons dying later this month/next fire correctly through
        # event_date threshold.
        if not person.is_alive or not person.is_alive_at(event_date):
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
            sorted_age_rates = sorted_age_rates_by_disease.get(disease_id)
            if not sorted_age_rates:
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
                sorted_age_rates,
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

        # Issue #1189 F3 follow-up (S104 verify): age caps use age-at-year,
        # not the static sim-start `person.age`. Without this, a person aging
        # past the cap during a multi-year sim still received one boundary-
        # year screening (age 75 mammography, age 90 annual physical). Falls
        # back to static age when `date_of_birth` is missing.
        _dob = getattr(person, "date_of_birth", None)
        _age_at_year = (int(year) - int(_dob.year)) if _dob is not None and hasattr(_dob, "year") else int(person.age)

        # --- Pediatric encounters (Issue #760) ---
        # Placed BEFORE the `if not conditions_with_spec: continue` gate so
        # pediatric patients (who typically carry no chronic conditions in
        # `followup_data`) still receive their well-child / immunization
        # visits. Byte-diff neutral when the schedule is empty (foundation
        # pass 1 invariant, still exercised by
        # test_empty_schedule_returns_no_events_and_does_not_consume_rng).
        from clinosim.modules.pediatric.calendar import generate_pediatric_events

        events.extend(generate_pediatric_events(person, year, prng))

        # --- Pregnancy lifecycle (META #957 Incr 1) ---
        # Placed BEFORE the `if not conditions_with_spec: continue` gate,
        # for the same reason as pediatric encounters above: healthy
        # childbearing-age women typically have no chronic conditions in
        # ``followup_data`` (Z34 is no longer in ``chronic_conditions``
        # after the Incr-1 refactor), so gating on ``conditions_with_spec``
        # would silently skip every non-comorbid pregnancy. The generator
        # uses a per-(patient, year) sub-RNG so it does not shift the
        # calendar's shared ``prng`` — non-obstetric calendars stay
        # byte-identical.
        events.extend(_pregnancy_lifecycle_events(person, year, country))

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

        # --- Annual health screening (age 40-89, S14 upper cap) ---
        # RNG-neutral gate: consume the two prng.integers draws for
        # anyone at or above the lower age gate so populations below
        # the cap byte-shape is unchanged; only skip the append when
        # age > MAX. Above ~90, ADL dependency + comorbidity load make
        # routine asymptomatic screening low-yield (Issue #1189 F3
        # sibling).
        if _age_at_year >= HEALTH_SCREENING_MIN_AGE:
            screening_month = int(prng.integers(HEALTH_SCREENING_MONTH_START, HEALTH_SCREENING_MONTH_END_EXCLUSIVE))
            screening_day = int(prng.integers(EVENT_RANDOM_DAY_MIN, EVENT_RANDOM_DAY_MAX_EXCLUSIVE))
            if _age_at_year <= HEALTH_SCREENING_MAX_AGE:
                screening_date = date(year, screening_month, screening_day)
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
        # RNG-neutral upper-age cap (S14): keep the prng.random() draw for
        # any age >= COLONOSCOPY_MIN_AGE so RNG shape is unchanged for
        # populations below the cap; drop the emit when age > MAX.
        _colonoscopy_roll = prng.random() if _age_at_year >= COLONOSCOPY_MIN_AGE else None
        if (
            COLONOSCOPY_MIN_AGE <= _age_at_year <= COLONOSCOPY_MAX_AGE
            and _colonoscopy_roll is not None
            and _colonoscopy_roll < COLONOSCOPY_PROBABILITY
        ):
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
        # RNG-neutral upper-age cap (S14): keep the prng.random() draw for
        # any eligible-sex person >= MAMMOGRAPHY_MIN_AGE so RNG shape is
        # unchanged for populations below the cap; drop emit when > MAX.
        _mammography_roll = prng.random() if (person.sex == "F" and _age_at_year >= MAMMOGRAPHY_MIN_AGE) else None
        if (
            person.sex == "F"
            and MAMMOGRAPHY_MIN_AGE <= _age_at_year <= MAMMOGRAPHY_MAX_AGE
            and _mammography_roll is not None
            and _mammography_roll < MAMMOGRAPHY_PROBABILITY
        ):
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

        # --- Pregnancy lifecycle handled above ---
        # (moved BEFORE the chronic-condition gate — see the placement
        # note near the pediatric-encounter block.)

        # --- Chemotherapy cycle visits (Issue #957 Tier-3-A) ---
        # For chronic-carrier patients of cancer codes with an assigned
        # cycle-based regimen (FOLFOX q14d, CarboPem q21d, Trastuzumab q3w,
        # LHRH q28d), emit chemo_visit events at the regimen's cycle
        # cadence. Selection is per-patient deterministic (sub-RNG keyed
        # off patient_id + salt) so it is RNG-shape neutral against the
        # calendar's ``prng`` — pre-existing patients' non-chemo events
        # are byte-identical whether this block runs or not.
        events.extend(_chemo_cycle_events(person, year))

    # Issue #1116: flush per-year perinatal stage counters so a `grep
    # perinatal_yearly_stage_counts` over simulator.log surfaces where
    # the delivery-rate gap opens (conception_bernoulli_attempted vs
    # delivery_emitted_this_year across the sim window).
    if _PERINATAL_STAGE_COUNTERS:
        from clinosim.simulator import log as sim_log

        sim_log.info("perinatal", "yearly_stage_counts", year=year, country=country, **_PERINATAL_STAGE_COUNTERS)
        _PERINATAL_STAGE_COUNTERS.clear()

    return events
