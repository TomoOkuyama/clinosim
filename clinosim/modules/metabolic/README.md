# `clinosim.modules.metabolic` — BMI-derived and metabolic-cluster chronic conditions

Deterministic chronic-condition enrichment for metabolic syndrome
components. First axis implemented is **E66 obesity ICD derivation**
from `PersonRecord.bmi`; future axes expand to **E88.81 metabolic
syndrome**, **K76.0 NAFLD**, **G47.30 OSA**, and GLP-1 / bariatric
management (per META #1137 cluster 2 scope).

## Purpose

Fill a data-completeness gap identified in the session-102 cohort
audit: `PersonRecord.bmi` was already set at generation and
consumed by multiple acute-event risk multipliers, but the ICD-10
obesity classification derived from BMI (E66) was absent from
`chronic_conditions` entirely (0% emission vs ~41% CDC NHANES
2017-20 US adult prevalence).

The module splits BMI-driven condition derivation out of the
shared `demographics.yaml:chronic_prevalence` sampler so a
Bernoulli draw is never involved in a condition that is a
deterministic function of a Layer-1 attribute.

## Public API

- `e66_bmi_enricher(ctx)` — POST_POPULATION enricher. Appends
  the appropriate E66 sub-code to every person's
  `chronic_conditions` based on their BMI. Idempotent and
  mutually exclusive (one E66 code per person).
- `_derive_e66_code(bmi) -> str | None` — pure function
  mapping a BMI value to its ICD-10 code. Returns `None` for
  BMI < 25 (reference range, no E66 code).

## Clinical mapping

WHO + CDC BMI classification + ICD-10 2024:

| BMI | Classification | ICD-10 |
|---|---|---|
| < 25 | Normal / underweight | — |
| 25 – <30 | Overweight | E66.3 |
| 30 – <40 | Obesity (Class I + II) | E66.9 |
| ≥ 40 | Morbid obesity (Class III) | E66.01 |

Thresholds encoded as module-level constants
(`_BMI_OVERWEIGHT_THRESHOLD`, `_BMI_OBESITY_THRESHOLD`,
`_BMI_MORBID_THRESHOLD`) rather than yaml so the deterministic-
derivation invariant is co-located with the code performing the
derivation.

## Enricher wiring

Registered in `clinosim.simulator.enrichers.register_builtin_
enrichers` at **POST_POPULATION order=15** — between
allergy/identity (order 10) and natural_death (order 20). This
places E66 code assignment after patient fundamentals are
finalized and before any downstream pass reads
`chronic_conditions`.

Always-on (no locale or config gate).

## Determinism / RNG

**Zero RNG consumption.** The enricher is a pure function of
`PersonRecord.bmi`. Byte-identity is preserved for every cohort
whose BMI distribution does not cross an E66 threshold; cohorts
with persons in the E66 range get the code without disturbing any
master-stream RNG state.

No entry in `ENRICHER_SEED_OFFSETS` is required.

## Reference data

None in Phase A — thresholds are inline constants matching the
WHO BMI classification + ICD-10 2024.

A future axis (E88.81 metabolic syndrome) will add a
`reference_data/metabolic_syndrome_criteria.yaml` encoding the
NCEP ATP III criteria (BMI/waist + HTN + Dyslipidemia + DM
pattern-match).

## Tests

`tests/unit/modules/metabolic/test_e66_bmi_enricher.py`:
- 5 pure-derivation tier boundary tests
  (normal/overweight/obesity/morbid + exact boundary values)
- 5 enricher behavior tests (per-tier append + normal-BMI no-op
  + mutex guard + idempotence)
- 1 mixed-cohort smoke test
- 1 pre-existing E66 variant pass-through test

## Follow-ups (cluster 2 roadmap per META #1137)

- **E88.81 metabolic syndrome** — 4-way AND over BMI + HTN +
  Dyslipidemia + DM.
- **K76.0 NAFLD** — BMI ≥ 30 + ALT/AST elevation; requires a
  lab-conditional path (enricher reads post-generation lab
  state).
- **G47.30 OSA** — BMI-correlated risk + sleep-study procedure
  path.
- **GLP-1 agonist / bariatric management** — ties into the
  `chronic_medications.yaml` sampler via a new E66-conditioned
  entry.
- **BMI trajectory** — current `person.bmi` is static over the
  sim window. Adding a bmi_trajectory (mirror of the DM
  glycemic_trajectory pattern) would let BMI drift year-over-
  year and reclassify a patient between E66 tiers mid-sim.

## See also

- `clinosim/modules/allergy/README.md` — POST_POPULATION enricher
  template reference (meta #1137 names it as a model wiring).
- Issue #1137 (META: new modules — mental_health/ + metabolic/).
- Issue #1126 (motivating issue for cluster 2 scope).
