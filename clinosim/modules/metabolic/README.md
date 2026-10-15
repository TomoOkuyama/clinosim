# `clinosim.modules.metabolic` — BMI-derived and metabolic-cluster chronic conditions

Deterministic chronic-condition enrichment for metabolic syndrome components. Axis 1 is **E66 obesity ICD derivation** from `PersonRecord.bmi`; axis 2 is **E88.81 metabolic syndrome** from the 4-way AND over BMI + HTN + Dyslipidemia + DM; axis 3 is **K76.0 NAFLD** from a BMI + DM-weighted SHA Bernoulli (RNG-neutral per-person assignment); axis 4 is **G47.30 OSA** from a BMI + sex-weighted SHA Bernoulli; axis 5 is **GLP-1 agonist pharmacotherapy** for the E66.9 / E66.01 cohort via new entries in `chronic_medications.yaml` (Semaglutide / Tirzepatide / Liraglutide, SC, exclusive-class). All five axes close out the META #1137 cluster 2 scope.

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
- `e88_81_syndrome_enricher(ctx)` — POST_POPULATION enricher (order=16, runs after `e66_bmi`). Appends `E88.81` metabolic syndrome when the 4-way AND holds. Idempotent, zero RNG consumption.
- `k76_0_nafld_enricher(ctx)` — POST_POPULATION enricher (order=17, runs after both BMI-driven enrichers). Appends `K76.0` fatty-liver when a per-person SHA-salted Bernoulli draw passes the BMI + DM-weighted threshold. Idempotent, RNG-neutral (hashes a module salt + person id rather than the master stream).
- `g47_30_osa_enricher(ctx)` — POST_POPULATION enricher (order=18). Appends `G47.30` obstructive sleep apnea when a per-person SHA-salted Bernoulli draw passes the BMI tier × biological sex table (male ~2× female per Peppard 2013). Idempotent, RNG-neutral.
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

The E88.81 metabolic syndrome enricher (axis 2) encodes the
strictest-intersection criteria inline (BMI ≥ 30 + HTN + Dyslipidemia + DM, 4-way AND). A later refinement can externalize these into `reference_data/metabolic_syndrome_criteria.yaml` once a 3-of-5 relaxation (lipid-panel conditional) is added.

## Tests

`tests/unit/modules/metabolic/test_e66_bmi_enricher.py`:
- 5 pure-derivation tier boundary tests
  (normal/overweight/obesity/morbid + exact boundary values)
- 5 enricher behavior tests (per-tier append + normal-BMI no-op
  + mutex guard + idempotence)
- 1 mixed-cohort smoke test
- 1 pre-existing E66 variant pass-through test

`tests/unit/modules/metabolic/test_e88_81_syndrome_enricher.py`:
- 8 pure-derivation AND-criteria tests
  (full match / each criterion missing / Type 1 DM path / category-header codes / exact BMI boundary)
- 5 enricher behavior tests (append on full match + sub-criteria no-op + sub-BMI no-op + idempotence + E66/E88.81 coexistence)
- 1 mixed-cohort smoke test

`tests/unit/modules/metabolic/test_k76_0_nafld_enricher.py`:
- 4 pure-probability anchor + DM-uplift tests
- 4 SHA-draw tests (zero / one / per-person determinism / cross-cohort distribution ~p)
- 2 derivation-wrapper tests (sub-threshold None + morbid+DM high-rate assignment)
- 4 enricher behavior tests (sub-BMI no-op + idempotence + 500-person prevalence band + RNG-neutral cross-seed)

`tests/unit/modules/metabolic/test_g47_30_osa_enricher.py`:
- 1 BMI-tier boundary test
- 4 prevalence anchor tests (male + female tables + 2:1 ratio + unknown-sex fallback)
- 4 SHA-draw tests (zero / one / per-person determinism / salt separation from K76.0)
- 2 derivation-wrapper tests (reference-BMI low-rate + morbid-male high-rate)
- 4 enricher behavior tests (idempotence + 500-person obese-male band + sex gradient visible + RNG-neutral cross-seed)

## Follow-ups (cluster 2 roadmap per META #1137)

- **K76.0 NAFLD → ALT/AST baseline tie-in** — downstream PR will steer liver-enzyme emission toward elevated range for K76.0-chronic patients so the "lab-conditional" half of the issue scope is also satisfied.
- **Bariatric surgery referral encounter + weight-loss counseling procedure** — the GLP-1 pharmacotherapy half of axis 5 ships here; the surgery referral encounter and counseling procedure code emission are tracked as a follow-up (requires new encounter yaml entries rather than a chronic-med addition).
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
