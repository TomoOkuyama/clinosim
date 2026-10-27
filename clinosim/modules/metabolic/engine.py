"""Metabolic module engine (Issue #1137 cluster 2).

Four deterministic enrichers that extend ``person.chronic_conditions``:

- ``e66_bmi_enricher`` (axis 1): BMI-derived E66 obesity sub-code.
- ``e88_81_syndrome_enricher`` (axis 2): 4-way AND over BMI + HTN +
  Dyslipidemia + DM collapses onto E88.81 metabolic syndrome.
- ``k76_0_nafld_enricher`` (axis 3): BMI + DM-weighted SHA
  Bernoulli over K76.0 non-alcoholic fatty liver disease.
- ``g47_30_osa_enricher`` (axis 4): BMI + sex-weighted SHA
  Bernoulli over G47.30 obstructive sleep apnea.

All four run at POST_POPULATION, consume no master-stream RNG
(pure derivations for axes 1-2, per-person SHA hash for axes
3-4), so byte-identity is preserved for cohorts without the
thresholds crossed; cohorts in range get the derived code
without disturbing any downstream probability draw.

Clinical basis:
  WHO + CDC BMI classification + ICD-10 2024:
    - BMI < 25        -> no E66 code (within reference range)
    - 25 <= BMI < 30  -> E66.3 Overweight
    - 30 <= BMI < 40  -> E66.9 Obesity, unspecified (Class I + II)
    - BMI >= 40       -> E66.01 Morbid obesity (Class III)

  ICD-10-CM 2024 E88.81 Metabolic syndrome — a billable composite
  diagnosis clinicians document when central obesity co-presents
  with hypertension, dyslipidemia, and diabetes. The clinical
  literature uses several overlapping criteria (NCEP ATP III
  3-of-5, WHO insulin-resistance-plus-two, IDF central-obesity-
  plus-two); this axis adopts the strictest intersection (all four
  required) so false positives are structurally impossible and the
  derived cohort matches the subset most likely to be
  explicitly coded in real EHRs. Future refinement can relax
  toward 3-of-5 once lipid-panel observations are available for
  the dyslipidemia criterion.

  ICD-10-CM K76.0 Fatty (change of) liver, not elsewhere
  classified — the billable code commonly used for NAFLD in
  general-practice EHR data. Prevalence anchors come from the
  Younossi 2016 meta-analysis (JAMA Hepatology) and the NHANES
  2017-2020 ultrasound-defined obese sub-cohort:
    - BMI < 30:         out of scope for this axis (future
                        refinement will add the 25-30 overweight
                        tier at ~25% prevalence).
    - 30 <= BMI < 40:   ~60 % NAFLD prevalence (Younossi obesity
                        cohort midpoint).
    - BMI >= 40:        ~85 % NAFLD prevalence (bariatric
                        pre-op biopsy cohorts).
    - DM co-presence:   +15 % relative uplift on the base
                        probability, capped at 100 %.

  The per-person assignment uses a SHA-256 hash of a module-salted
  person id so the draw is deterministic and RNG-neutral — the
  master simulation stream is never consumed. A follow-up PR will
  tie K76.0 chronic presence to elevated ALT/AST baselines so the
  "lab-conditional" half of the issue scope is also satisfied.

  ICD-10-CM G47.30 Sleep apnea, unspecified — the issue's
  specified billable code for the OSA axis (clinically G47.33
  "Obstructive sleep apnea" is the more precise leaf, but the
  cluster's chosen code is G47.30 and the simulator honors that
  scope). Prevalence anchors come from Peppard 2013 (Am J
  Epidemiol) and the HypnoLaus / Hidalgo cohort studies:

    - BMI tier bands         male     female
      BMI < 25               5 %      2 %
      25 <= BMI < 30         20 %     10 %
      30 <= BMI < 40         50 %     25 %
      BMI >= 40              75 %     45 %

  The ~2× male-vs-female gap is well documented and primarily
  anatomical (upper-airway dimensions, fat-distribution pattern).
  Per-person SHA Bernoulli — RNG-neutral like axis 3.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import has_icd_prefix
from clinosim.determinism import sha_bernoulli
from clinosim.modules.population import (
    BMI_MORBID_OBESITY_THRESHOLD as _BMI_MORBID_THRESHOLD,
)
from clinosim.modules.population import (
    BMI_OBESE_THRESHOLD as _BMI_OBESITY_THRESHOLD,
)
from clinosim.modules.population import (
    BMI_OVERWEIGHT_THRESHOLD as _BMI_OVERWEIGHT_THRESHOLD,
)

# WHO BMI tier bounds are imported from the population package to
# keep a single source of truth across the simulator (next WHO
# revision needs one patch, not two). The local underscore aliases
# keep the metabolic-side call sites unchanged.

# E88.81 metabolic syndrome AND-criteria.
_SYNDROME_BMI_THRESHOLD = 30.0
_HTN_PREFIXES: tuple[str, ...] = ("I10",)
_DYSLIPIDEMIA_PREFIXES: tuple[str, ...] = ("E78",)
_DM_PREFIXES: tuple[str, ...] = ("E10", "E11")
_SYNDROME_CODE = "E88.81"

# K76.0 NAFLD BMI-weighted prevalence anchors + DM uplift.
_NAFLD_CODE = "K76.0"
_NAFLD_OBESE_PREVALENCE = 0.60
_NAFLD_MORBID_PREVALENCE = 0.85
_NAFLD_DM_UPLIFT = 1.15
_NAFLD_SALT = "metabolic.nafld.v1"
# Issue #1756: K76.0 (nonalcoholic fatty liver disease) is mutually
# exclusive with F10 (alcohol use disorder) by definition. For an F10
# patient with the fatty-liver phenotype, the clinically correct ICD
# is K70.x (alcoholic liver disease), tracked separately under #1608.
# This prefix tuple gates the K76.0 enricher so it never adds the
# contradictory code; K70 assignment for F10 patients is a follow-up.
_F10_PREFIXES: tuple[str, ...] = ("F10",)

# G47.30 OSA BMI tier prevalence (male / female separately), times an
# age factor. Calibrated to moderate-to-severe OSA (AHI >= 15, the level
# that is diagnosed and treated) from Peppard et al. 2013: men 30-49 10%,
# 50-70 17%; women 30-49 3%, 50-70 9%. The earlier table matched any
# sleep-disordered breathing (AHI >= 5: men 34%, women 17%).
_OSA_CODE = "G47.30"
_OSA_PREVALENCE_MALE: dict[str, float] = {
    "reference": 0.02,
    "overweight": 0.085,
    "obese": 0.21,
    "morbid": 0.315,
}
_OSA_PREVALENCE_FEMALE: dict[str, float] = {
    "reference": 0.0065,
    "overweight": 0.032,
    "obese": 0.08,
    "morbid": 0.145,
}
_OSA_AGE_SPLIT = 50
_OSA_AGE_FACTOR_MALE = (0.8, 1.35)
_OSA_AGE_FACTOR_FEMALE = (0.6, 1.75)
_OSA_SALT = "metabolic.osa.v1"


def _derive_metabolic_syndrome(bmi: float, chronic: list[str]) -> str | None:
    """Return "E88.81" when all four criteria (BMI >= 30 + HTN +
    Dyslipidemia + DM) are satisfied by ``bmi`` and the condition
    list, otherwise ``None``.

    Deterministic — safe to call from any context without consuming
    RNG. The 4-way AND is intentionally strict to avoid
    over-identification; see module docstring for rationale.
    """
    if bmi < _SYNDROME_BMI_THRESHOLD:
        return None
    if not has_icd_prefix(chronic, _HTN_PREFIXES):
        return None
    if not has_icd_prefix(chronic, _DYSLIPIDEMIA_PREFIXES):
        return None
    if not has_icd_prefix(chronic, _DM_PREFIXES):
        return None
    return _SYNDROME_CODE


def _derive_e66_code(bmi: float) -> str | None:
    """Return the E66 ICD code for the given BMI, or ``None`` when
    BMI is in the reference range (< 25).

    Deterministic per-BMI mapping — safe to call from any context
    without consuming RNG.
    """
    if bmi >= _BMI_MORBID_THRESHOLD:
        return "E66.01"
    if bmi >= _BMI_OBESITY_THRESHOLD:
        return "E66.9"
    if bmi >= _BMI_OVERWEIGHT_THRESHOLD:
        return "E66.3"
    return None


# Issue #1773: real-EHR ICD-coding rates for BMI-derived obesity.
# Pre-fix every BMI-eligible adult was ICD-coded, driving E66 prevalence
# to 77 % of adults (CDC NHANES 2017-2020 benchmark: 42 % BMI-phenotype,
# with ~30-50 % of those actually ICD-coded in US EHRs — real-world
# chart-abstraction studies e.g. Kuhlemeier 2023 (JGIM) report
# 35-50 % E66 documentation rate among BMI≥30 adults). The per-tier
# rates below collapse the phenotype→coding gap:
#   - Overweight (E66.3): ~20 % — clinicians rarely formally code
#     overweight unless it's a prevention-focused encounter.
#   - Obesity (E66.9) and morbid obesity (E66.01): ~65 % — somewhat
#     higher because class-II/III obesity is more likely to drive a
#     comorbidity-focused encounter where E66 lands on the problem list.
# Draws are per-person SHA Bernoulli so cohort reproducibility is
# preserved and no master-stream RNG is consumed.
_E66_ICD_CODING_RATE_OVERWEIGHT = 0.20
_E66_ICD_CODING_RATE_OBESITY = 0.65
_E66_ICD_CODING_SALT = "metabolic.e66.icd_coding.v1"


def _is_e66_icd_coded(person_id: str, code: str) -> bool:
    """Per-person deterministic coin: should this BMI-eligible person
    receive the E66 ICD code on their chart?

    RNG-neutral: no master-stream draw. Uses ``sha_bernoulli`` with a
    stable salt so the coin is bit-reproducible across platforms and
    runs. ``code`` picks the per-tier rate.
    """
    if code == "E66.3":
        rate = _E66_ICD_CODING_RATE_OVERWEIGHT
    else:
        rate = _E66_ICD_CODING_RATE_OBESITY
    return sha_bernoulli(f"{_E66_ICD_CODING_SALT}|{person_id}|{code}", rate)


def e66_bmi_enricher(ctx: Any) -> None:
    """POST_POPULATION enricher: append the BMI-derived E66 sub-code
    to the chronic_conditions list for the subset of BMI-eligible
    persons who would be ICD-coded in real-world US EHR practice
    (Issue #1773).

    Idempotent — a person who already carries the derived code
    (e.g. imported from a cache snapshot or legacy demographics
    yaml) is left untouched. Mutually exclusive: a person is
    assigned AT MOST ONE E66 sub-code even if several thresholds
    are nominally crossed (the function returns the highest-tier
    code since the if-chain goes severe → mild). The BMI
    phenotype on ``person.bmi`` is unchanged — only the ICD slot
    is gated.
    """
    for person in ctx.population.persons.values():
        bmi = float(getattr(person, "bmi", 0.0) or 0.0)
        code = _derive_e66_code(bmi)
        if code is None:
            continue
        # Avoid duplicate append if another layer already added the
        # code (e.g. the chronic_prevalence yaml adds E66.* via the
        # legacy pathway in a future locale).
        if code in person.chronic_conditions:
            continue
        # Also skip if another E66 variant is already present —
        # the enricher is the SOT for BMI-derived obesity codes,
        # but a mid-sim BMI change that would re-classify is
        # out-of-scope for Phase A (patient-level BMI drift lives
        # on the aging-pass trajectory roadmap).
        if any(c.startswith("E66") for c in person.chronic_conditions):
            continue
        # Issue #1773: real-EHR coding-rate gate.
        person_id = getattr(person, "person_id", "") or ""
        if not person_id or not _is_e66_icd_coded(person_id, code):
            continue
        person.chronic_conditions.append(code)


def e88_81_syndrome_enricher(ctx: Any) -> None:
    """POST_POPULATION enricher: append E88.81 metabolic syndrome
    to every person whose chronic-condition list satisfies the 4-way
    AND (BMI >= 30 + HTN + Dyslipidemia + DM).

    Must run after both the chronic_prevalence sampler (POP_GENERATION)
    and ``e66_bmi_enricher`` so all input facts are finalized. Pure
    deterministic — zero RNG consumption. Idempotent — a person who
    already carries E88.81 is left untouched.
    """
    for person in ctx.population.persons.values():
        bmi = float(getattr(person, "bmi", 0.0) or 0.0)
        if _SYNDROME_CODE in person.chronic_conditions:
            continue
        code = _derive_metabolic_syndrome(bmi, person.chronic_conditions)
        if code is None:
            continue
        person.chronic_conditions.append(code)


def _nafld_probability(bmi: float, has_dm: bool) -> float:
    """Return the K76.0 assignment probability for a given BMI tier
    and DM status.

    Zero below the obesity threshold; the DM uplift is a relative
    15 % multiplier capped at 1.0 so a morbidly obese diabetic
    cannot exceed 100 %.
    """
    if bmi < _BMI_OBESITY_THRESHOLD:
        return 0.0
    base = _NAFLD_MORBID_PREVALENCE if bmi >= _BMI_MORBID_THRESHOLD else _NAFLD_OBESE_PREVALENCE
    if has_dm:
        base = min(1.0, base * _NAFLD_DM_UPLIFT)
    return base


def _draw_nafld(person_id: str, probability: float) -> bool:
    """SHA-256 Bernoulli: return True iff a per-person uniform
    quantile derived from a module-salted hash falls below the
    assignment probability.

    Thin wrapper over :func:`clinosim.determinism.sha_bernoulli` —
    kept here (plus the ``_`` prefix) as the historical API that
    the axis-3 unit tests import. RNG-neutral — the master
    simulation stream is not consumed.
    """
    return sha_bernoulli(f"{_NAFLD_SALT}|{person_id}", probability)


def _derive_nafld_assignment(person_id: str, bmi: float, chronic: list[str]) -> str | None:
    """Return "K76.0" when the SHA-salted per-person draw assigns
    NAFLD under the BMI + DM-weighted probability, otherwise ``None``.

    Issue #1756: suppress the assignment entirely when the person
    already carries F10.x on their problem list — K76.0 (nonalcoholic
    fatty liver) and F10 (alcohol use disorder) are mutually exclusive
    by ICD definition, and 305 patients in the US p=10k seed=42 5y
    cohort carried both pre-fix. The SHA Bernoulli draw is skipped on
    the gated path; the enricher is already RNG-neutral so no cursor
    bookkeeping is required.
    """
    if has_icd_prefix(chronic, _F10_PREFIXES):
        return None
    probability = _nafld_probability(bmi, has_icd_prefix(chronic, _DM_PREFIXES))
    return _NAFLD_CODE if _draw_nafld(person_id, probability) else None


def k76_0_nafld_enricher(ctx: Any) -> None:
    """POST_POPULATION enricher: append K76.0 NAFLD to each person
    whose SHA-salted per-person Bernoulli draw passes the BMI +
    DM-weighted threshold.

    Must run after both the chronic_prevalence sampler
    (POP_GENERATION) and ``e66_bmi_enricher`` so BMI and the DM
    criterion are finalized. Idempotent — a person who already
    carries K76.0 is left untouched. RNG-neutral — the master
    simulation stream is never consumed.
    """
    for person in ctx.population.persons.values():
        if _NAFLD_CODE in person.chronic_conditions:
            continue
        bmi = float(getattr(person, "bmi", 0.0) or 0.0)
        code = _derive_nafld_assignment(person.person_id, bmi, person.chronic_conditions)
        if code is None:
            continue
        person.chronic_conditions.append(code)


def _bmi_tier(bmi: float) -> str:
    """Return the WHO BMI tier label used by the OSA (and future
    tier-indexed) prevalence tables."""
    if bmi >= _BMI_MORBID_THRESHOLD:
        return "morbid"
    if bmi >= _BMI_OBESITY_THRESHOLD:
        return "obese"
    if bmi >= _BMI_OVERWEIGHT_THRESHOLD:
        return "overweight"
    return "reference"


def _osa_probability(bmi: float, sex: str, age: int | None = None) -> float:
    """Return the G47.30 assignment probability for a given BMI
    tier + biological sex, scaled by the age factor when ``age`` is given.

    Sex coding follows the simulator's ``PersonRecord.sex`` field
    ("M" / "F"); any other value falls back to the female table
    (lower prevalence, conservative under-identification rather
    than inflated misses).
    """
    male = sex.upper().startswith("M")
    base = (_OSA_PREVALENCE_MALE if male else _OSA_PREVALENCE_FEMALE)[_bmi_tier(bmi)]
    if age is None:
        return base
    young, old = _OSA_AGE_FACTOR_MALE if male else _OSA_AGE_FACTOR_FEMALE
    return base * (old if age >= _OSA_AGE_SPLIT else young)


def _draw_osa(person_id: str, probability: float) -> bool:
    """SHA-256 Bernoulli for the G47.30 assignment. RNG-neutral,
    deterministic per person id + module salt.

    Thin wrapper over :func:`clinosim.determinism.sha_bernoulli`
    with the OSA module salt baked in — kept at this spelling as
    the historical API the axis-4 unit tests import.
    """
    return sha_bernoulli(f"{_OSA_SALT}|{person_id}", probability)


def _derive_osa_assignment(person_id: str, bmi: float, sex: str, age: int | None = None) -> str | None:
    """Return "G47.30" when the SHA-salted per-person draw assigns
    OSA under the BMI + sex + age-weighted probability, otherwise
    ``None``.
    """
    probability = _osa_probability(bmi, sex, age)
    return _OSA_CODE if _draw_osa(person_id, probability) else None


def g47_30_osa_enricher(ctx: Any) -> None:
    """POST_POPULATION enricher: append G47.30 OSA to each person
    whose SHA-salted per-person Bernoulli draw passes the BMI +
    sex-weighted threshold.

    Must run after the chronic_prevalence sampler (POP_GENERATION);
    does not depend on the other metabolic enrichers but is kept
    at order=18 (after ``k76_0_nafld`` order=17) to keep the
    cluster's registration order predictable. Idempotent — a
    person who already carries G47.30 is left untouched. RNG-
    neutral — the master simulation stream is never consumed.
    """
    for person in ctx.population.persons.values():
        if _OSA_CODE in person.chronic_conditions:
            continue
        # Issue #1779: G47.30 (Sleep apnea, unspecified) is the adult
        # OSA code — pediatric OSA has its own leaf (G47.33) and a
        # much lower prevalence (~1-2% vs the 25-45% adult rate at
        # higher BMI tiers). The audit found 335 / 2553 pediatric
        # patients (13%, ~6-20× the US pediatric ICD-coded reference)
        # because this enricher applied the adult BMI-weighted
        # Bernoulli to anyone regardless of age. Gating by age ≥ 18
        # keeps the adult cohort unchanged while removing the
        # inappropriate pediatric assignment.
        age = int(getattr(person, "age", 0) or 0)
        if age < 18:
            continue
        bmi = float(getattr(person, "bmi", 0.0) or 0.0)
        sex = str(getattr(person, "sex", "") or "")
        code = _derive_osa_assignment(person.person_id, bmi, sex, age)
        if code is None:
            continue
        person.chronic_conditions.append(code)
