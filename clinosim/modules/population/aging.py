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
* :func:`_disease_progression` — stage advancement (CKD G1→G5,
  COPD GOLD I→IV, diabetes compensated→decompensated). Stub.
* :func:`_allergy_drift` — childhood food-allergy resolution (flips
  ``clinical_status`` to ``resolved`` under the childhood resolution
  rate from ``allergens.yaml:aging``) and late-onset drug-sensitivity
  emergence (adds a new medication allergy with ``onset_date`` set).
* :func:`_condition_reactive_mortality` — replace ``natural_death``'s
  single pre-sampled date with a lazy per-year Bernoulli that factors
  the person's current condition load. Stub.

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

from clinosim.locale.loader import load_demographics
from clinosim.modules.allergy.engine import load_allergen_config
from clinosim.types.population import PersonRecord

__all__ = [
    "advance_population",
    "aging_sub_seed",
]


_AGING_SEED_SALT = "clinosim:aging:v1"
_MIN_INCIDENCE_AGE = 18  # Adult-chronic incidence only; pediatric is handled by pediatric calendar.


def aging_sub_seed(person_id: str, year: int, pass_name: str) -> int:
    """Deterministic 32-bit sub-seed for one person × year × aging pass.

    Derived from ``(person_id, year, pass_name)`` so every pass gets an
    isolated stream — a change inside ``_disease_progression`` cannot
    shift ``_annual_chronic_onset`` draws for the same person, and a
    change for one person cannot shift anyone else's streams.
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
        if prng.random() < rate:
            person.chronic_conditions.append(code)


# ---------------------------------------------------------------------------
# Stubs (Phase 2 follow-up PRs attach behaviour)
# ---------------------------------------------------------------------------


def _disease_progression(
    person: PersonRecord,
    year: int,
    prng: np.random.Generator,
    incidence_table: dict[str, _ChronicIncidenceSpec],
) -> None:
    """Per-person annual disease-stage advancement (Phase 2 stub).

    Future contract: use existing physiology state where it exists;
    otherwise YAML-driven annual transition matrices to advance
    CKD stage, COPD GOLD stage, diabetes compensation, dementia
    progression. No-op in this PR.
    """


def _allergy_drift(
    person: PersonRecord,
    year: int,
    prng: np.random.Generator,
    incidence_table: dict[str, _ChronicIncidenceSpec],
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


def _condition_reactive_mortality(
    person: PersonRecord,
    year: int,
    prng: np.random.Generator,
    incidence_table: dict[str, _ChronicIncidenceSpec],
) -> None:
    """Per-person annual condition-reactive mortality draw (Phase 2 stub).

    Future contract: replace the ``natural_death`` enricher's single
    pre-sampled ``date_of_death`` with a lazy per-year Bernoulli that
    factors the person's current condition load. Keeps actuarial ``qx``
    as the baseline multiplier. No-op in this PR.
    """


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
    """
    from clinosim.modules.population.engine import PopulationRegistry

    assert isinstance(registry, PopulationRegistry), "advance_population: registry must be a PopulationRegistry"

    incidence_table = _load_annual_incidence_for_locale(locale)

    for person in registry.persons.values():
        if not person.is_alive:
            continue
        for pass_fn in (
            _annual_chronic_onset,
            _disease_progression,
            _allergy_drift,
            _condition_reactive_mortality,
        ):
            pass_rng = np.random.default_rng(aging_sub_seed(person.person_id, year, pass_fn.__name__))
            pass_fn(person, year, pass_rng, incidence_table)
