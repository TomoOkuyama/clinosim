"""Annual population-aging hook (Issue #1564 Phase 2).

Called by the engine at the top of each simulated year. Walks every
alive person in the registry and lets per-person "aging passes" update
their state before the year's events are generated:

* :func:`_annual_chronic_onset` — age × sex incidence of newly acquired
  chronic conditions. Band-diff derivation from the locale's existing
  ``chronic_prevalence`` yaml: per-year incidence rate during band
  ``[lo, hi]`` is derived from the point-prevalence of the next age
  band so that a person who ages across the whole band accumulates
  (P_next − P_this) new onset probability. Marginal-preserving by
  construction: single source of truth stays
  ``locale/*/demographics.yaml:chronic_prevalence``.
* Stage progression — Phase 2 of the longitudinal subsystem (Issue
  #1696) retired the former ``_disease_progression`` aging pass and
  moved CKD / COPD / heart-failure / IHD / dementia / liver / Parkinson
  / AF / MS / stroke-sequela stage advancement into the Markov
  pattern under ``clinosim.modules.longitudinal.engine`` + the yamls
  at ``locale/shared/longitudinal/stage/*.yaml``. The engine's
  ``advance_one_year`` is called from ``advance_population`` after
  the aging passes finalise chronic_conditions for the year, with
  ``_comorbidity_multiplier`` threaded as ``multiplier_fn`` so
  comorbidity-interaction rules still compose.
* :func:`_allergy_drift` — childhood food-allergy resolution (flips
  ``clinical_status`` to ``resolved`` under the childhood resolution
  rate from ``allergens.yaml:aging``) and late-onset drug-sensitivity
  emergence (adds a new medication allergy with ``onset_date`` set).
* :func:`_condition_reactive_mortality` — adds a per-year excess
  mortality Bernoulli layered on top of the baseline qx. SMR is
  the geometric mean of per-ICD multipliers from
  ``locale/shared/condition_mortality_smr.yaml``; ``excess_qx =
  qx_baseline * (SMR - 1)`` is capped by ``max_excess_qx_per_year``
  (default 0.15). A hit overrides ``date_of_death`` ONLY when it
  moves earlier — the baseline ``natural_death`` enricher's
  pre-sampled date is respected unless condition load would kill
  the person sooner.

Determinism contract:

* Each pass receives a per-(person, year, pass_name) sub-RNG derived
  deterministically from ``(person_id, year, pass_name)`` — no shared
  stream between passes or between persons. This isolates each pass's
  draws so adding behaviour to one pass does not cascade into unrelated
  cohort output.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from clinosim.locale.loader import load_actuarial_life_table, load_condition_mortality_smr, load_demographics
from clinosim.modules.allergy.engine import load_allergen_config
from clinosim.types.population import PersonRecord

__all__ = [
    "advance_population",
    "aging_sub_seed",
]


_AGING_SEED_SALT = "clinosim:aging:v1"
_MIN_INCIDENCE_AGE = 18  # Adult-chronic incidence only; pediatric is handled by pediatric calendar.
# Codes that appear in `chronic_prevalence` yaml but are RNG-cursor
# placeholders only — pregnancy-lifecycle lives in `state_periods`,
# not in `chronic_conditions`. Mirrors
# `clinosim.modules.population.engine._STATE_PERIOD_CHRONIC_CODES`.
# `_annual_chronic_onset` must NOT append these to a person's
# chronic_conditions mid-sim, same way `generate_population` skips
# them at initial sampling.
_STATE_PERIOD_ONSET_SKIP_CODES = frozenset({"Z34", "Z37"})


def aging_sub_seed(person_id: str, year: int, pass_name: str) -> int:
    """Deterministic 32-bit sub-seed for one person × year × aging pass.

    Derived from ``(person_id, year, pass_name)`` so every pass gets an
    isolated stream — a change inside one pass (or inside the Phase 2
    longitudinal engine) cannot shift ``_annual_chronic_onset`` draws
    for the same person, and a change for one person cannot shift
    anyone else's streams.
    """
    key = f"{_AGING_SEED_SALT}|{person_id}|{year}|{pass_name}"
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % (2**32)


# ---------------------------------------------------------------------------
# Annual chronic-condition onset
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ChronicIncidenceSpec:
    """Per-ICD annual incidence table derived from locale prevalence yaml.

    ``bands`` maps each age-band ``(lo, hi)`` to a per-year Bernoulli
    probability for a person in that band who does NOT yet have the
    condition. Derivation is band-diff: for the FROM band, the
    susceptible fraction ``(1 - P_this)`` must become ``(1 - P_next)``
    over the band width, which gives
    ``λ = 1 - ((1 - P_next) / (1 - P_this)) ** (1 / width)``.
    For the last band (or when the next band's prevalence is not
    higher), ``λ = 0`` — the person's prevalence is already at the
    terminal target.
    """

    sex: str  # "M", "F", or "" (any)
    bands: dict[tuple[int, int], float]  # (lo, hi) → per-year Bernoulli λ

    def rate_at(self, age: int) -> float:
        for (lo, hi), rate in self.bands.items():
            if lo <= age <= hi:
                return rate
        return 0.0


def _derive_annual_incidence_from_prevalence(
    age_prevalence: dict[tuple[int, int], float],
) -> dict[tuple[int, int], float]:
    """Band-diff derivation of per-year onset rate for a chronic
    condition whose point-prevalence by age band is ``age_prevalence``.

    Model: within a band ``[lo, hi]`` the point prevalence is flat at
    ``P_this``; between consecutive bands the prevalence steps up to
    ``P_next``. To spread that step over the FROM band so a person
    ages continuously, solve for the per-year Bernoulli λ that takes
    the susceptible fraction ``(1 - P_this)`` to ``(1 - P_next)`` over
    the band width:
        (1 - λ) ** width = (1 - P_next) / (1 - P_this)
        λ = 1 - ((1 - P_next) / (1 - P_this)) ** (1 / width)

    For the LAST (highest) band, λ = 0 — a person already in the
    terminal band has accumulated the full target prevalence.
    When ``P_next <= P_this`` (unusual; a band step down due to e.g.
    survivorship), λ = 0.
    """
    sorted_bands = sorted(age_prevalence.items(), key=lambda kv: kv[0][0])
    out: dict[tuple[int, int], float] = {}
    for i, ((lo, hi), p_this) in enumerate(sorted_bands):
        if i + 1 >= len(sorted_bands):
            # Last band: no next prevalence to climb toward.
            out[(lo, hi)] = 0.0
            continue
        _, p_next = sorted_bands[i + 1]
        if p_next <= p_this or p_this >= 1.0:
            out[(lo, hi)] = 0.0
            continue
        width = max(1, hi - lo + 1)
        ratio = (1.0 - p_next) / (1.0 - p_this)
        # ratio ∈ (0, 1); clamp numerically.
        ratio = max(1e-12, min(1.0, ratio))
        lam = 1.0 - ratio ** (1.0 / width)
        out[(lo, hi)] = max(0.0, min(1.0, lam))
    return out


@lru_cache(maxsize=8)
def _load_annual_incidence_for_locale(country: str) -> dict[str, _ChronicIncidenceSpec]:
    """Build the annual-incidence table for every ICD declared in
    ``locale/{country}/demographics.yaml:chronic_prevalence``.

    Reads the SAME source of truth as initial-cohort sampling (no
    duplicate yaml). Supports the legacy flat schema and the ``by_sex``
    schema; for ``by_sex`` codes only the primary-sex bands are used
    (augment-sex onset is a Phase 3 concern, kept narrow here).
    """
    demo = load_demographics(country)
    raw = demo.get("chronic_prevalence") or {}
    out: dict[str, _ChronicIncidenceSpec] = {}
    for code, entry in raw.items():
        if not isinstance(entry, dict):
            continue

        by_sex_raw = entry.get("by_sex")
        if isinstance(by_sex_raw, dict):
            # Pick the first sex key as primary (same convention as
            # engine._parse_chronic_prevalence).
            first_sex = next(iter(by_sex_raw.keys()), None)
            if first_sex is None:
                continue
            bands_raw = by_sex_raw.get(first_sex) or {}
            sex_filter = str(first_sex).upper()
        else:
            sex_filter = str(entry.get("sex", ""))
            bands_raw = {k: v for k, v in entry.items() if k != "sex"}

        age_prev: dict[tuple[int, int], float] = {}
        for range_key, prev in bands_raw.items():
            lo_str, hi_str = str(range_key).split("-")
            age_prev[(int(lo_str), int(hi_str))] = float(prev)

        bands = _derive_annual_incidence_from_prevalence(age_prev)
        out[code] = _ChronicIncidenceSpec(sex=sex_filter, bands=bands)
    return out


# ---------------------------------------------------------------------------
# Allergy-drift config loaders
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_aging_allergy_config() -> dict:
    """Return the ``aging:`` block of ``allergens.yaml`` (empty dict
    when the yaml predates this field). Cached singleton."""
    data = load_allergen_config()
    aging = data.get("aging")
    if not isinstance(aging, dict):
        return {}
    return aging


@lru_cache(maxsize=1)
def _load_medication_allergen_entries() -> tuple[dict, ...]:
    """Return the ``allergens.medication`` list from ``allergens.yaml``
    as an immutable tuple of dicts (so ``@lru_cache`` is safe) — used
    by late-onset drug-sensitivity emergence to pick a candidate
    allergen uniformly."""
    data = load_allergen_config()
    meds = ((data.get("allergens") or {}).get("medication")) or []
    return tuple(meds)


def _current_age(person: PersonRecord, year: int) -> int:
    """Approximate age at Jan 1 of ``year`` from ``date_of_birth``.
    Birthday-exact comparison would require a month+day pivot; using
    ``year - dob.year`` for annual aging is both well-defined and
    conservative — a person born on Dec 31 appears to turn one year
    older on Jan 1 instead of Dec 31, acceptable for an annual
    Bernoulli draw."""
    return year - person.date_of_birth.year


def _annual_chronic_onset(
    person: PersonRecord,
    year: int,
    prng: np.random.Generator,
    incidence_table: dict[str, _ChronicIncidenceSpec],
    locale: str = "us",
) -> None:
    """Per-person annual chronic-condition onset.

    For every ICD declared in the locale's ``chronic_prevalence`` yaml:

    * Skip if person is below :data:`_MIN_INCIDENCE_AGE` (adults only;
      pediatric chronic acquisition is out of scope here).
    * Skip if the condition is sex-locked and the person's sex does
      not match.
    * Skip if the person already has the condition.
    * Draw ``prng.random() < λ(age_band)``; on hit, append the ICD
      code to ``person.chronic_conditions``.

    All draws come from the pass-isolated ``prng`` so adding or
    reshuffling ICDs here cannot cascade into other passes or other
    persons.
    """
    age = _current_age(person, year)
    if age < _MIN_INCIDENCE_AGE:
        return
    existing = set(person.chronic_conditions)
    for code, spec in incidence_table.items():
        if code in existing:
            continue
        if spec.sex and spec.sex != person.sex:
            continue
        rate = spec.rate_at(age)
        if rate <= 0.0:
            # Advance the stream by one draw anyway so adding a new ICD
            # with zero incidence to the yaml never shifts another
            # ICD's draws. Pass-isolated sub-RNG means this is a cheap
            # discipline, not a correctness requirement — the next ICD
            # in iteration order will get a fresh draw regardless.
            continue
        # Issue #1137 — mental-health axis: scale the base onset
        # rate by any applicable comorbidity multiplier
        # (DM / HF / cancer / stroke-sequela → F32 / F33 / F41.1).
        # Zero RNG cost — the multiplier only shifts the Bernoulli
        # threshold, so byte-identity for cohorts without the
        # triggering somatic chronic condition is preserved.
        rate = rate * _mental_health_onset_multiplier(code, person)
        rate = min(1.0, max(0.0, rate))
        if prng.random() < rate:
            # State-period markers (Z34 pregnancy, Z37 outcome-of-
            # delivery) have per-age-band Bernoulli entries in
            # `chronic_prevalence` only to preserve rng cursor
            # byte-identity for codes iterated after them in the
            # initial-cohort sampler — they are NOT real chronic
            # entries. Mirror the initial sampler's skip here so
            # mid-sim aging onset never injects a bogus Z34/Z37 into
            # `person.chronic_conditions`. The pregnancy lifecycle
            # lives in `person.state_periods` (perinatal lifecycle
            # generator); FHIR Z37 past-birth marker is derived from
            # state_history by the FHIR emit adapter.
            if code in _STATE_PERIOD_ONSET_SKIP_CODES:
                continue
            person.chronic_conditions.append(code)


# ---------------------------------------------------------------------------
# Stubs (Phase 2 follow-up PRs attach behaviour)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Disease stage progression (Issue #1572 Phase 2.5 — CKD + COPD, plus HF
# NYHA added as a yaml-pattern-fit extension)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_mental_health_onset_multipliers() -> dict[str, dict]:
    """Return per-target-ICD onset multiplier rules from
    ``mental_health_onset_multipliers.yaml``. Cached singleton.
    Empty dict when the yaml is missing — ``_mental_health_onset_
    multiplier`` returns 1.0 for every lookup so onset behaviour
    is unchanged for cohorts without the triggering comorbidities."""
    from clinosim.locale.loader import load_mental_health_onset_multipliers

    data = load_mental_health_onset_multipliers()
    return data.get("mental_health_onset_multipliers") or {}


def _mental_health_onset_multiplier(code: str, person: PersonRecord) -> float:
    """Compound onset multiplier for mental-health chronic ``code``
    under the person's currently-held somatic comorbidities. Returns
    1.0 (no scaling) when the target has no rule or when no rule
    fires.

    Rule triggers (all applicable rules compound multiplicatively):
        requires_any_chronic -> ANY-match against
                                person.chronic_conditions (exact).
        requires_any_chronic_prefix -> ANY-match via startswith on
                                person.chronic_conditions.
    """
    rules = _load_mental_health_onset_multipliers().get(code)
    if not rules:
        return 1.0
    chronic = person.chronic_conditions or []
    chronic_set = set(chronic)
    out = 1.0
    for _rule_name, rule in rules.items():
        exact = set(rule.get("requires_any_chronic") or ())
        prefix = tuple(rule.get("requires_any_chronic_prefix") or ())
        if exact and (exact & chronic_set):
            out *= float(rule.get("multiplier", 1.0))
            continue
        if prefix and any(c.startswith(p) for c in chronic for p in prefix):
            out *= float(rule.get("multiplier", 1.0))
    return out


@lru_cache(maxsize=1)
def _load_comorbidity_multipliers() -> dict[str, dict]:
    """Return the per-target-ICD comorbidity-interaction rules from
    ``comorbidity_progression_multipliers.yaml``. Cached singleton.
    Empty dict when the yaml is missing — ``_comorbidity_multiplier``
    returns 1.0 for every lookup so pass behaviour is unchanged."""
    from clinosim.locale.loader import load_comorbidity_progression_multipliers

    data = load_comorbidity_progression_multipliers()
    return data.get("comorbidity_progression_multipliers") or {}


def _comorbidity_multiplier(person: PersonRecord, target_icd: str, year: int) -> float:
    """Multiplier for ``target_icd``'s stage-advance probability under
    the comorbidities the person already carries at the start of
    ``year``.

    Reads the previous year's ``glycemic_control`` (if any) to keep
    the computation order-independent of the chronic_conditions
    iteration inside ``_disease_progression``. Multiple applicable
    rules compound multiplicatively.

    Rule triggers (all supplied triggers must match for the rule to
    fire; a trigger key omitted from the yaml does not constrain
    the rule; a rule with NO triggers at all is skipped — otherwise
    it would blanket-apply, almost certainly a yaml bug):

    * ``requires_any_chronic`` — set-intersect against
      ``person.chronic_conditions``.
    * ``requires_smoking_in`` — set-membership on
      ``person.smoking_status`` (``"never"`` / ``"former"`` /
      ``"current"``).
    * ``requires_chronic_stage_in`` — map ``{icd: [stage, ...]}``.
      For every listed ICD the person's current stage from
      ``person.disease_stages[icd]`` must be in the configured
      list. Lets a rule fire only once a *different* chronic
      condition has progressed past a threshold (e.g. steeper
      cardiorenal multiplier when CKD has reached G4+).
    """
    rules = _load_comorbidity_multipliers().get(target_icd)
    if not rules:
        return 1.0
    chronic = set(person.chronic_conditions or [])
    smoking = str(getattr(person, "smoking_status", "") or "")
    # Phase 2 longitudinal (Issue #1696): stage lookup moved from
    # person.disease_stages (retired in Task 11) to the latest-year
    # YearSnapshot.chronic_stages. Pre-year-1 fixtures with empty
    # longitudinal_history return an empty stage map — matching the
    # previous "no stage set yet" behavior.
    stages: dict[str, str] = {}
    for snap in reversed(person.longitudinal_history or []):
        if snap.year <= year - 1:
            stages = dict(snap.chronic_stages)
            break
    # Phase 1 longitudinal migration (Issue #1695): the prior year's
    # glycemic control predictor now reads HbA1c from
    # PersonRecord.longitudinal_history and inverts the Layer-2
    # linearisation hba1c = 6 + (1 - gc) * 6, giving
    # gc = clamp((12 - hba1c) / 6, 0, 1). Fallback 0.7 ≈ moderate
    # control for a person without a longitudinal_history entry yet
    # (test fixtures / pre-engine cohorts).
    gc_prev = 0.7
    for snap in reversed(person.longitudinal_history or []):
        if snap.year > year - 1:
            continue
        hba1c = snap.continuous.get("hba1c")
        if hba1c is not None:
            gc_prev = max(0.0, min(1.0, (12.0 - float(hba1c)) / 6.0))
        break
    out = 1.0
    for _rule_name, rule in rules.items():
        trigger_chronic = set(rule.get("requires_any_chronic") or ())
        if trigger_chronic and not (trigger_chronic & chronic):
            continue
        trigger_smoking = set(rule.get("requires_smoking_in") or ())
        if trigger_smoking and smoking not in trigger_smoking:
            continue
        trigger_stage_map = rule.get("requires_chronic_stage_in") or {}
        stage_ok = True
        for icd, allowed in trigger_stage_map.items():
            if str(stages.get(icd, "")) not in set(allowed):
                stage_ok = False
                break
        if not stage_ok:
            continue
        # At least one trigger must have constrained the rule;
        # otherwise an empty-trigger rule would blanket-apply its
        # multiplier to every person — almost certainly a yaml bug,
        # so skip silently.
        if not (trigger_chronic or trigger_smoking or trigger_stage_map):
            continue
        mult = float(rule.get("default_multiplier", 1.0))
        for tier in rule.get("glycemic_tiers") or ():
            gc_lt = tier.get("gc_lt")
            if gc_lt is not None and gc_prev < float(gc_lt):
                mult = float(tier.get("multiplier", 1.0))
                break
        out *= mult
    return out


def _allergy_drift(
    person: PersonRecord,
    year: int,
    prng: np.random.Generator,
    incidence_table: dict[str, _ChronicIncidenceSpec],
    locale: str = "us",
) -> None:
    """Per-person annual allergy drift.

    Two behaviours, both parametrised by ``allergens.yaml:aging``:

    * **Childhood food-allergy resolution** — for each active food
      allergy on a person whose current age is below
      ``child_age_cutoff``, flip ``clinical_status`` to ``"resolved"``
      with annual probability ``annual_rate_child``. Models the
      well-documented outgrowth of egg / milk / soy allergy by
      adolescence (see yaml citation).
    * **Late-onset drug-sensitivity emergence** — if the person is at
      or above ``adult_age_floor`` and does not already carry a
      medication allergy, draw an annual Bernoulli at the age-tiered
      rate (``annual_rate_elderly`` for ≥ ``elderly_age_floor``, else
      ``annual_rate_adult``). On hit, pick a medication allergen
      uniformly from ``allergens.medication``, build an
      :class:`Allergy` with ``onset_date = date(year, 6, 15)`` and
      append it to ``person.allergies``. If the person previously
      had only an NKA record, that record is removed first — once
      a real allergy exists the NKA assertion is no longer valid.

    If ``person.allergies is None`` (newborn registered mid-sim before
    the allergy enricher runs for them), the pass is skipped —
    newborn allergy initialisation is a separate follow-up concern.
    All draws use the pass-isolated ``prng`` so toggling behaviour
    here cannot cascade into unrelated cohort output.
    """
    from datetime import date as _date

    from clinosim.types.allergy import Allergy, AllergyReaction

    if person.allergies is None:
        return

    cfg = _load_aging_allergy_config()
    if not cfg:
        return
    resolve_cfg = cfg.get("childhood_food_resolution") or {}
    emerge_cfg = cfg.get("late_onset_drug_sensitivity") or {}

    age = _current_age(person, year)

    # 1) Childhood food-allergy resolution.
    child_cutoff = int(resolve_cfg.get("child_age_cutoff", 18))
    if age < child_cutoff:
        rate = float(resolve_cfg.get("annual_rate_child", 0.0))
        if rate > 0.0:
            for allergy in person.allergies:
                if allergy.is_nka:
                    continue
                if allergy.category != "food":
                    continue
                if allergy.clinical_status != "active":
                    continue
                if prng.random() < rate:
                    allergy.clinical_status = "resolved"

    # 2) Late-onset drug sensitivity emergence.
    adult_floor = int(emerge_cfg.get("adult_age_floor", 18))
    if age < adult_floor:
        return
    elderly_floor = int(emerge_cfg.get("elderly_age_floor", 65))
    rate_key = "annual_rate_elderly" if age >= elderly_floor else "annual_rate_adult"
    emerge_rate = float(emerge_cfg.get(rate_key) or 0.0)
    # Issue #1581 Phase C.2: scale the emergence rate by the person's
    # atopic-predisposition multiplier (default 1.0 = no bump, no
    # cascade for initial-cohort persons; raised at register_newborn
    # time when the mother is atopic). Clamp at 1.0 upper bound after
    # scaling because the rate is a Bernoulli probability — a child
    # of two heavily-atopic parents could in theory push the raw rate
    # above 1.0 given a very high multiplier, which the Bernoulli draw
    # must still clip to a valid probability.
    emerge_rate = min(1.0, emerge_rate * float(getattr(person, "atopic_predisposition", 1.0) or 1.0))
    if emerge_rate <= 0.0:
        return
    has_medication_allergy = any(
        (not a.is_nka) and a.category == "medication" and a.clinical_status == "active" for a in person.allergies
    )
    if has_medication_allergy:
        return
    if prng.random() >= emerge_rate:
        return

    med_entries = _load_medication_allergen_entries()
    if not med_entries:
        return
    held_codes = {a.allergen_code for a in person.allergies if not a.is_nka}
    candidates = [e for e in med_entries if e["allergen_code"] not in held_codes]
    if not candidates:
        return
    pick = candidates[int(prng.integers(len(candidates)))]
    reactions = pick.get("common_reactions") or []
    rxn_payload = reactions[0] if reactions else {}
    new_allergy = Allergy(
        allergy_id=f"ALG-{person.person_id}-aging-{year}",
        allergen_code=str(pick["allergen_code"]),
        category="medication",
        criticality=str(pick.get("criticality", "low")),
        verification_status="confirmed",
        clinical_status="active",
        onset_date=_date(year, 6, 15),
        reactions=[
            AllergyReaction(
                manifestation_snomed=str(rxn_payload.get("manifestation_snomed", "")),
                severity=str(rxn_payload.get("severity", "mild")),
            )
        ]
        if rxn_payload
        else [],
        is_nka=False,
    )
    person.allergies[:] = [a for a in person.allergies if not a.is_nka]
    person.allergies.append(new_allergy)


# ---------------------------------------------------------------------------
# Condition-reactive mortality
# ---------------------------------------------------------------------------


# 5-year band lower bounds used by the actuarial YAML (0, 5, 10, …, 95).
_QX_BAND_LOWER_BOUNDS = tuple(range(0, 100, 5))


@lru_cache(maxsize=1)
def _load_condition_smr_table() -> tuple[dict[str, float], str, float]:
    """Return ``(smr_table, combine_method, max_excess_qx)`` from
    ``locale/shared/condition_mortality_smr.yaml``. Cached singleton.
    Returns an empty table + sentinel defaults when the yaml is
    missing — the pass becomes a safe no-op in that case."""
    data = load_condition_mortality_smr()
    raw = data.get("smr_table") or {}
    smr: dict[str, float] = {str(k): float(v) for k, v in raw.items()}
    combine = str(data.get("combine_method") or "geometric_mean")
    cap = float(data.get("max_excess_qx_per_year") or 0.15)
    return smr, combine, cap


def _qx_baseline(country: str, sex: str, age: int) -> float:
    """Lookup baseline qx for (country, sex, age) from the actuarial
    yaml. Mirrors the lookup convention in
    ``clinosim.modules.natural_death.enricher._qx_for`` so the hook's
    excess calculation sits on the same baseline the enricher used."""
    life_table = load_actuarial_life_table()
    country_key = "jp" if country.lower() == "jp" else "us"
    country_block = (life_table.get("annual_mortality_qx") or {}).get(country_key) or {}
    sex_key = "male" if sex == "M" else "female" if sex == "F" else None
    if sex_key is None:
        return 0.0
    band_data = country_block.get(sex_key) or {}
    if not band_data:
        return 0.0
    band = max((b for b in _QX_BAND_LOWER_BOUNDS if b <= age), default=_QX_BAND_LOWER_BOUNDS[-1])
    return float(band_data.get(band, 0.0))


def _combined_smr_for(conditions: list[str], smr_table: dict[str, float], combine_method: str) -> float:
    """Combine per-ICD SMRs into a single multiplier.

    Only codes present in ``smr_table`` contribute. Exact match first,
    then prefix match (e.g. ``N18.3`` matches entry ``N18``). SMRs
    at or below 1.0 are included (they are no-op). Returns 1.0 when
    no code contributes.
    """
    contributions: list[float] = []
    seen: set[str] = set()
    for code in conditions:
        if code in smr_table and code not in seen:
            contributions.append(smr_table[code])
            seen.add(code)
            continue
        # Prefix fallback — try progressively shorter prefixes.
        for i in range(len(code) - 1, 0, -1):
            prefix = code[:i]
            if prefix in smr_table and prefix not in seen:
                contributions.append(smr_table[prefix])
                seen.add(prefix)
                break
    if not contributions:
        return 1.0
    if combine_method == "geometric_mean":
        import math

        return math.exp(sum(math.log(v) for v in contributions) / len(contributions))
    # Fallback: arithmetic mean.
    return sum(contributions) / len(contributions)


def _condition_reactive_mortality(
    person: PersonRecord,
    year: int,
    prng: np.random.Generator,
    incidence_table: dict[str, _ChronicIncidenceSpec],
    locale: str = "us",
) -> None:
    """Per-person annual condition-reactive mortality draw.

    Mechanism:

    1. Combine per-ICD SMRs from ``condition_mortality_smr.yaml``
       into a single multiplier via geometric mean (bounded
       multiplicative). Codes not in the table contribute SMR = 1.
    2. Look up baseline ``qx(country, sex, age)`` from
       ``actuarial_life_table.yaml`` — SAME source as the
       ``natural_death`` enricher so the baseline semantics match.
    3. ``excess_qx = qx * (SMR_combined - 1)``, clamped to
       ``[0, max_excess_qx_per_year]``. The clamp protects advanced-
       age bands where baseline qx is already 15-30 %/yr.
    4. Draw ``prng.random() < excess_qx``; on hit, propose
       ``date(year, 6, 15)``. Override ``person.date_of_death`` ONLY
       when the proposed date is earlier than any existing value —
       the baseline enricher's pre-sampled date is respected unless
       the condition load would kill the person sooner.

    The hook never saves a person from death. It only accelerates
    condition-driven mortality on top of actuarial baseline.
    """
    from datetime import date as _date

    smr_table, combine_method, max_cap = _load_condition_smr_table()
    if not smr_table:
        return
    smr_combined = _combined_smr_for(person.chronic_conditions, smr_table, combine_method)
    if smr_combined <= 1.0:
        return
    age = _current_age(person, year)
    qx = _qx_baseline(locale, person.sex, age)
    if qx <= 0.0:
        return
    excess = qx * (smr_combined - 1.0)
    excess = max(0.0, min(max_cap, excess))
    if excess <= 0.0:
        return
    if prng.random() >= excess:
        return
    proposed = _date(year, 6, 15)
    if person.date_of_death is None or proposed < person.date_of_death:
        person.date_of_death = proposed


# ---------------------------------------------------------------------------
# Stroke → chronic-sequela promotion (Issue #1581 extension — I63 → I69.3)
# ---------------------------------------------------------------------------


def _stroke_sequela_promotion(
    person: PersonRecord,
    year: int,
    prng: np.random.Generator,
    incidence_table: dict[str, _ChronicIncidenceSpec],
    locale: str = "us",
) -> None:
    """Promote past stroke hospitalization(s) to chronic sequela
    condition(s) on ``person.chronic_conditions``:

    * ``cerebral_infarction`` → ``I69.3`` (sequelae of cerebral
      infarction) — ischemic stroke sequela.
    * ``hemorrhagic_stroke`` → ``I69.1`` (sequelae of intracerebral
      haemorrhage) — the ICH subtype is by far the most common
      hemorrhagic stroke etiology (~85 % of hemorrhagic strokes in
      Benjamin 2019 Circ AHA Statistics), so a single catalog
      entry on I69.1 captures the vast majority of survivors.

    Idempotent on both arms. Does not consume RNG itself; mRS
    stage initialisation flows through ``_disease_progression``'s
    ``_INITIAL_STAGE_SAMPLERS["I69"]`` branch on first touch. Both
    sequela ICDs share base code "I69" so they inherit the same
    mRS staging and transition probabilities — a shared etiology-
    agnostic clinical convention (mRS is a functional-outcome
    scale, not an etiology-specific severity grader). Discharge
    mRS distribution differs modestly between ischemic and
    hemorrhagic survivors in the literature; a per-full-code
    sampler is a planned future refinement.

    Clinical rationale: ~70-80 % of stroke survivors have residual
    neurological deficit at 1 year (Benjamin 2019 Circulation AHA
    Heart Disease Statistics). Promoting to a chronic sequela at
    the year boundary following the index stroke encounter captures
    this deficit as a Layer-1 chronic condition and lets the
    standard stage-progression machinery handle year-on-year
    functional decline from recurrent events, cognitive impairment,
    and immobility complications.
    """
    history = person.hospitalization_history or []
    if "I69.3" not in person.chronic_conditions and any(
        getattr(h, "disease_id", "") == "cerebral_infarction" for h in history
    ):
        person.chronic_conditions.append("I69.3")
    if "I69.1" not in person.chronic_conditions and any(
        getattr(h, "disease_id", "") == "hemorrhagic_stroke" for h in history
    ):
        person.chronic_conditions.append("I69.1")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def advance_population(
    registry: object,
    year: int,
    locale: str,
) -> None:
    """Advance the population by one simulated year (Phase 2).

    Called by the engine at the top of each year's iteration, before
    that year's monthly events are generated. Walks every alive person
    and runs the four aging passes with per-(person, year, pass) sub-
    RNGs so each pass stays stream-isolated across runs with the same
    global seed.

    ``registry`` is typed as ``object`` to avoid a cyclic import with
    ``clinosim.modules.population.engine``; the runtime guard narrows
    it. ``locale`` keys into the chronic-incidence table derived from
    ``locale/{locale}/demographics.yaml:chronic_prevalence`` — the
    single source of truth also used by the initial-cohort sampler.

    Newborns registered mid-sim become part of ``registry.persons``
    during the dispatch loop (Issue #1596 Step 2); the next-year
    primary call picks them up naturally so no catch-up filter is
    needed (Issue #1596 Step 3 / Step 4 removed the ``person_filter``
    kwarg that supported the former Phase-B catch-up pass).
    """
    from datetime import date as _date

    from clinosim.modules.population.engine import PopulationRegistry

    assert isinstance(registry, PopulationRegistry), "advance_population: registry must be a PopulationRegistry"

    incidence_table = _load_annual_incidence_for_locale(locale)
    year_start = _date(year, 1, 1)

    for person in registry.persons.values():
        # Issue #1564 Phase 2 (reactive-mortality PR): tighten the
        # alive gate from the `is_alive` flag to point-in-time
        # ``is_alive_at(year_start)``. The ``natural_death`` enricher
        # (POST_POPULATION) sets ``date_of_death`` but does NOT flip
        # ``is_alive``, so persons already dead by this year would
        # otherwise still receive aging passes. The upstream fix is
        # pass-isolated — each person's streams are independent — so
        # this filter does not shift any other person's draws.
        if not person.is_alive_at(year_start):
            continue
        for pass_fn in (
            _annual_chronic_onset,
            _stroke_sequela_promotion,
            _allergy_drift,
            _condition_reactive_mortality,
        ):
            pass_rng = np.random.default_rng(aging_sub_seed(person.person_id, year, pass_fn.__name__))
            pass_fn(person, year, pass_rng, incidence_table, locale=locale)
        # Phase 1 longitudinal subsystem (Issue #1695) — advance the
        # per-year state_history snapshot once the aging passes have
        # finalised chronic_conditions for this year, so a mid-sim
        # scope entry (e.g. new-onset E11 from _annual_chronic_onset)
        # takes effect immediately.
        from clinosim.modules.longitudinal.engine import advance_one_year

        if person.longitudinal_history and person.longitudinal_history[-1].year < year:
            _ls_rng = np.random.default_rng(aging_sub_seed(person.person_id, year, "longitudinal"))
            advance_one_year(
                person,
                year=year,
                year_rng=_ls_rng,
                multiplier_fn=_comorbidity_multiplier,
            )
