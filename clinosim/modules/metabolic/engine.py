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

# G47.30 OSA BMI tier prevalence (male / female separately).
_OSA_CODE = "G47.30"
_OSA_PREVALENCE_MALE: dict[str, float] = {
    "reference": 0.05,
    "overweight": 0.20,
    "obese": 0.50,
    "morbid": 0.75,
}
_OSA_PREVALENCE_FEMALE: dict[str, float] = {
    "reference": 0.02,
    "overweight": 0.10,
    "obese": 0.25,
    "morbid": 0.45,
}
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


def e66_bmi_enricher(ctx: Any) -> None:
    """POST_POPULATION enricher: append the BMI-derived E66 sub-code
    to every person's ``chronic_conditions`` list.

    Idempotent — a person who already carries the derived code
    (e.g. imported from a cache snapshot or legacy demographics
    yaml) is left untouched. Mutually exclusive: a person is
    assigned AT MOST ONE E66 sub-code even if several thresholds
    are nominally crossed (the function returns the highest-tier
    code since the if-chain goes severe → mild).
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
    """
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


def _osa_probability(bmi: float, sex: str) -> float:
    """Return the G47.30 assignment probability for a given BMI
    tier + biological sex.

    Sex coding follows the simulator's ``PersonRecord.sex`` field
    ("M" / "F"); any other value falls back to the female table
    (lower prevalence, conservative under-identification rather
    than inflated misses).
    """
    table = _OSA_PREVALENCE_MALE if sex.upper().startswith("M") else _OSA_PREVALENCE_FEMALE
    return table[_bmi_tier(bmi)]


def _draw_osa(person_id: str, probability: float) -> bool:
    """SHA-256 Bernoulli for the G47.30 assignment. RNG-neutral,
    deterministic per person id + module salt.

    Thin wrapper over :func:`clinosim.determinism.sha_bernoulli`
    with the OSA module salt baked in — kept at this spelling as
    the historical API the axis-4 unit tests import.
    """
    return sha_bernoulli(f"{_OSA_SALT}|{person_id}", probability)


def _derive_osa_assignment(person_id: str, bmi: float, sex: str) -> str | None:
    """Return "G47.30" when the SHA-salted per-person draw assigns
    OSA under the BMI + sex-weighted probability, otherwise
    ``None``.
    """
    probability = _osa_probability(bmi, sex)
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
        bmi = float(getattr(person, "bmi", 0.0) or 0.0)
        sex = str(getattr(person, "sex", "") or "")
        code = _derive_osa_assignment(person.person_id, bmi, sex)
        if code is None:
            continue
        person.chronic_conditions.append(code)
