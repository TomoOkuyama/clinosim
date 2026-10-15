"""Metabolic module engine (Issue #1137 cluster 2).

Two deterministic enrichers that extend ``person.chronic_conditions``:

- ``e66_bmi_enricher`` (axis 1): BMI-derived E66 obesity sub-code.
- ``e88_81_syndrome_enricher`` (axis 2): 4-way AND over BMI + HTN +
  Dyslipidemia + DM collapses onto E88.81 metabolic syndrome.

Both are POST_POPULATION, pure deterministic (no RNG consumption),
so byte-identity is preserved for cohorts without the thresholds
crossed; cohorts in range get the derived code without disturbing
any downstream probability draw.

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
"""

from __future__ import annotations

from typing import Any

# ICD-10 BMI thresholds (upper bounds exclusive on the lower edges
# per the WHO classification; e.g. 24.9 -> no E66, 25.0 -> E66.3).
_BMI_OVERWEIGHT_THRESHOLD = 25.0
_BMI_OBESITY_THRESHOLD = 30.0
_BMI_MORBID_THRESHOLD = 40.0

# E88.81 metabolic syndrome AND-criteria.
_SYNDROME_BMI_THRESHOLD = 30.0
_HTN_PREFIXES: tuple[str, ...] = ("I10",)
_DYSLIPIDEMIA_PREFIXES: tuple[str, ...] = ("E78",)
_DM_PREFIXES: tuple[str, ...] = ("E10", "E11")
_SYNDROME_CODE = "E88.81"


def _has_code_with_prefix(chronic: list[str], prefixes: tuple[str, ...]) -> bool:
    """Return True if any entry in ``chronic`` starts with any of ``prefixes``.

    Chronic condition lists may carry either the category header (e.g.
    "E11") or a billable leaf (e.g. "E11.9"); the prefix match treats
    both as equivalent for the AND-check.
    """
    return any(c.startswith(prefixes) for c in chronic)


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
    if not _has_code_with_prefix(chronic, _HTN_PREFIXES):
        return None
    if not _has_code_with_prefix(chronic, _DYSLIPIDEMIA_PREFIXES):
        return None
    if not _has_code_with_prefix(chronic, _DM_PREFIXES):
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
