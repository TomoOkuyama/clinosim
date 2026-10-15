"""Metabolic module engine (Issue #1137 cluster 2 axis 1).

Enricher that deterministically appends an E66 obesity sub-code to
``person.chronic_conditions`` based on ``person.bmi``. Pure
deterministic function — zero RNG consumption, no cascade.
Byte-identity for cohorts without BMI thresholds crossed is
preserved; cohorts with BMI in E66 range get the appropriate ICD
without disturbing any downstream probability draw.

Clinical basis:
  WHO + CDC BMI classification + ICD-10 2024:
    - BMI < 25        -> no E66 code (within reference range)
    - 25 <= BMI < 30  -> E66.3 Overweight
    - 30 <= BMI < 40  -> E66.9 Obesity, unspecified (Class I + II)
    - BMI >= 40       -> E66.01 Morbid obesity (Class III)

The simulator's PersonRecord.bmi field is already set at
cohort-generation time (lifestyle attributes). This enricher is
POST_POPULATION so BMI is finalized by the time it runs; the
derived E66 code becomes available to all downstream encounter /
observation emit paths that read ``person.chronic_conditions``.
"""

from __future__ import annotations

from typing import Any

# ICD-10 BMI thresholds (upper bounds exclusive on the lower edges
# per the WHO classification; e.g. 24.9 -> no E66, 25.0 -> E66.3).
_BMI_OVERWEIGHT_THRESHOLD = 25.0
_BMI_OBESITY_THRESHOLD = 30.0
_BMI_MORBID_THRESHOLD = 40.0


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
