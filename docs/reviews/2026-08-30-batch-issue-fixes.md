# Session 91 + Batch-2 review — 14 issue-fix PRs + 3 chore PRs

**Dates**: 2026-08-29 → 2026-08-30
**Scope**: two sessions of batch issue-fix work following the v0.5.0 tag.
Session 91 landed the first-batch 10 issues (#909-#918 filed, #919-#927
resolved via PRs #928-#937), then batch-2 filed 10 more issues
(#938-#947), resolved them via PRs #948-#956, and opened one follow-up
(#957) for deep-oncology and true-perinatal work deferred out of #943.

Master shifted from `de261adf` (v0.5.0 tag) to `3d618cb4`. The next
release will be **v0.6.0** (MINOR) — see "Version implication" below.

## Summary

- **18 PRs merged total**: 14 issue-fix PRs + 3 chore PRs + 1 support
  test-reseed (#936).
- **20 new Issues filed**: 10 first-batch (#909-#918) resolved by
  #928-#937; 10 second-batch (#938-#947) resolved by #948-#956; 1
  follow-up (#957) for deep-oncology + true-perinatal chain deferred
  out of #943.
- **CHANGELOG.md**: 14 new `[Unreleased]` entries authored (4 pre-existing
  from PRs #939 / #919 / #927 / #923 preserved verbatim).
- **AGENTS.md**: 5 new convention entries recording patterns from
  #942 / #947 / #948+#953 / #951 / #950 (see "AGENTS.md conventions
  added" below).
- **Test-fixture reseeds required**: 2 (#936 seed=49, #956 in-tree
  seed=55) — both driven by the chronic-prevalence + service-line
  cohort shape shifts, same pattern as sessions 42 / 89 B-3 / 90
  determinism / #933 restore.

## Issues resolved

### First batch (session 91, Issues #919-#927)

| Issue | PR   | One-line resolution |
|-------|------|---------------------|
| #919  | #933 | Restore E11.9 / N18 / J44 (JP + US) + E78 (US) chronic_prevalence to hospital-cohort targets under marginal-preserving engine (B-3 phase 2) |
| #920  | #930 | Emit `doseAndRate.doseQuantity` + `timing.repeat` + `rateQuantity` from CIF/yaml on discharge / outpatient-renewal MRs; parse via shared `parse_dose_string` |
| #921  | #935 | Seasonal flu distribution (Oct-Feb, Nov peak) + COVID `wave_epochs` (initial_rollout / primary_series_ramp / booster / annual) two-stage sampler |
| #922  | #937 | Right-size pediatric_schedule cadence + `care_seeking.age_conditional` block + participation gate in `generate_pediatric_events` |
| #923  | #934 | Multi-FY `Coverage.period` (one row per fiscal year) + age-conditional insurance type sampler (`late_elderly` at ≥ 75, `dependent` demote for minors on employee policy) |
| #924  | #929 | Sample external `Organization` for 紹介先 from `external_organizations.yaml` catalog via `sha256 % N`; break the hospital-main self-loop |
| #925  | #932 | Populate `Composition.section.entry[]` from encounter-linked resources across SOAP + JP-CLINS discharge summary via a single `_build_encounter_resource_index` walk |
| #926  | #928 | Flip `Patient.active = false` when deceased + immunization `_as_of` clamp at date_of_death + universal `_drop_entries_after_death` bundle filter |
| #927  | #931 | Visit-type conditional `Encounter.length` triangular distribution (JP 再診 5-9-20 tail + health-screening 20-30-45 mode + US MEPS/E&M equivalents) via `ambulatory_visit_length_seed` per-encounter sub-RNG |
| #939  | #954 | Add PCI / pacemaker / craniotomy / ileus-tube / bowel-resection Procedure catalog entries + disease-triggered dispatch via `issue939_procedure_seed` sub-RNG |

Also merged in session 91: **#936** (integration test reseed to seed=49
after #933 chronic_prevalence restore, US carryforward fixture).

### Second batch (Issues #938-#947)

| Issue | PR   | One-line resolution |
|-------|------|---------------------|
| #938  | #950 | Pediatric age gate on alcohol / smoking Observations (`age_gates.{alcohol,smoking}_min_age` default 15, USPSTF / MHLW 高校) |
| #940  | #950 | LTCI carelevel age + 相当疾病 gate (第1号 ≥ 65 universal, 第2号 40-64 with F00 / G30 / G20 / J44 / I60-I69 / G12.2 / M80 chronic) |
| #941  | #952 | Dual-slot `Encounter.hospitalization.admitSource` + `dischargeDisposition` — EN `coding[0].display` + locale-resolved `.text` at emit site; deceased-fallback to `deceased_code` |
| #942  | #955 | NKA positive assertion (SNOMED 716186003) + age-conditional polyallergy sampling with per-patient SHA256 sub-RNG |
| #943  | #956 | Cancer (C18/C22/C34/C50 F-only/C61 M-only) + obstetric (Z34/Z37) service lines + I10 dilution (0.20/0.50/0.65 → 0.11/0.30/0.40 JP; 0.33 → 0.22 US); scope limitations tracked in #957 |
| #944  | #948 | Derive `Coverage.status` from `period.end` vs `snapshot_date` (returns `cancelled` iff expired; boundary inclusive) |
| #945  | #953 | Universal `_drop_entries_after_snapshot` bundle-finalize filter + second-pass dangling-reference scrubber (7 resource types × 12 timestamp fields) |
| #946  | #951 | Emit height / weight / BMI / head-circumference Observations at every encounter via SHA256 sub-seed pattern; pediatric medians from `anthropometric_reference.yaml` |
| #947  | #949 | Sex-locked ICD-10 dispatch — `sex_gating.is_sex_locked_for(code, patient_sex)` at every dispatch site; canonical `icd10_sex_restrictions.yaml`; unified two inline `_SEX_RESTRICTED_ICD` tables |

Chore PRs: **#960** (vulture whitelist for `load_allergens` false
positive after #942 refactor), **#958** (actions/setup-java 5 → 6),
**#959** (ruff 0.16.3 → 0.16.4).

Follow-up filed: **#957** (deep-oncology chemo cycles + true perinatal
chain + newborn Patient synthesis) — deferred out of #943's scope
limitations block.

## Cross-PR interactions caught

- **#928 death gate ↔ #935 vaccine seasonality**. The immunization
  sub-RNG stream shifted for deceased patients under #928's `_as_of`
  clamp; #935's new `_pick_flu_month` and COVID `wave_epochs` picker
  preserve the same clamp — the seasonal draw occurs before the
  death-gate check, and the death-gate filter still runs at bundle
  finalize. Verified by the `#928 death gate still holds after
  seasonality change` regression test.
- **#948 snapshot_date plumbing ↔ #953 universal snapshot filter**.
  #948 introduced `BundleContext.snapshot_date` (populated by
  `convert_cif_to_fhir` reading `cif/metadata.json`, soft-failure on
  missing / malformed). #953's `_drop_entries_after_snapshot` filter
  reuses that context field verbatim — no second copy, no drift
  path. When `ctx.snapshot_date is None` (test fixtures / legacy CIF
  without metadata), the filter is a no-op — backward-compatible by
  construction.
- **#922 pediatric skew ↔ #916 Z-code inflation ↔ #917 childhood
  immunization empty**. #922 halves the pediatric well-child +
  immunization cadence (well_child_infant [6,7,8] → [3,4,5];
  immunization_infant [2,3] → [1,2] to avoid double counting with
  co-administered well-child slots). This cascades to fewer Z00.0
  well-child encounter rows (moving #916 in the right direction
  without directly closing it) and reduces the population of
  pediatric patients whose Immunization records #917 characterises
  as empty. #917 remains open — the reduced visit count is
  orthogonal to whether emitted Immunization resources are
  populated.
- **#942 NKA rate ↔ `test_document_chain` baseline_prevalence**. After
  #942 every patient carries ≥ 1 `AllergyIntolerance` record (NKA
  positive assertion or real allergen), so the per-patient rate is
  ≥ 100% + polyallergy tail. Baseline range widened from 5-30% to
  95-150% in both `test_document_chain.py` and
  `test_document_chain_alpha2.py`. Load-bearing detections
  preserved: enricher off → 0%, runaway → > 150%. Test expectation
  update, not a regression.
- **#956 I10 dilution ↔ chronic RNG cascade**. Adding C-chapter +
  Z-chapter chronic codes to `demographics.yaml` and retuning I10
  prevalence cascades sampling for every downstream patient event.
  The `test_memoize_hit_bit_identical` xfail was loosened to
  `strict=False` — the specific p=100/seed=42 cross-patient defect
  it documents no longer triggers with the shifted cohort. The
  underlying defect class (`_IMPLIED_CHRONIC_BY_DISEASE`
  cross-patient accretion on cache hit) stands; other cohort seeds
  still exhibit it, per the test's own docstring.

## Test-fixture reseeds required

Both reseeds were driven by chronic-prevalence + service-line cohort
shape shifts, following the same precedent as sessions 42 / 89 B-3 /
90 determinism / #933 restore. The test docstring already
authorises seed migration when the specific fixture drifts out.

- **#936**: `test_anticoag_carryforward` reseeded seed=42 → seed=49
  after #933 restored E11.9 / E78 / J44 / N18 marginals, causing
  seed=45 to lose the AFib + 2-admission + newly-started-anticoag
  candidate. Scouted seeds 45..100; seed=49 was the first to retain
  the fixture (POP-000360).
- **#956 in-tree reseed**: same fixture reseeded seed=49 → seed=55
  after the C-chapter + Z-chapter additions from #956 shifted the
  cohort out again. Same maintenance pattern; documented in the same
  commit that adds the service-line yaml.

## Deferred to follow-up

- **#957** (filed by session 91 during #956 work). Deep-oncology
  chemo cycle scheduling (FOLFOX infusion days, taxane pre-med,
  radiation-therapy Procedure emission K722 / K731, oncology-specific
  Composition) + true perinatal chain (delivery Encounter,
  mother-baby link, newborn Patient generation, Z38 birth event).
  #956 models Z34 as active-during-sim chronic marker, not a
  time-boxed pregnancy state; that reshape is what #957 tracks.
- **`_IMPLIED_CHRONIC_BY_DISEASE` cross-patient accretion on
  memoize cache-hit path**. The `test_memoize_hit_bit_identical`
  xfail-strict was flipped to `strict=False` in #956 because the
  specific p=100/seed=42 fixture no longer manifests with the
  shifted cohort. The underlying defect class stands (see the
  test's own docstring line 313-319); root fix (replay implied-
  chronic mutation on cache-hit path) is a separate
  `order/engine.py` / `hospital_state.py` task.
- **US p=1000 audit for cohort-shape validation**. #937 calibrated
  JP against MHLW 患者調査 2020; US carries an analogous
  `care_seeking.age_conditional` block directionally per JP tuning,
  but a CDC NAMCS / MEPS audit script for US cohort shape is not yet
  authored.

## CI hygiene

Three fix commits landed after main PR merges — all traceable to
test-fixture drift from cohort-shape shifts, not real regressions:

- **#936 reseed** — post-#933 anticoag-carryforward fixture drift.
- **#960 vulture whitelist** — false positive after #942 introduced a
  sibling `load_allergen_config` alongside legacy `load_allergens`.
  Both functions kept; whitelist entry added.
- **Sibling test-expectation updates during #955 rebase** —
  `test_document_chain{,_alpha2}.py::baseline_prevalence` widened
  5-30 → 95-150 to accommodate per-patient NKA. Same "load-bearing
  detections preserved" audit as #955's own baseline change.

Root-cause classification: **test-fixture drift from cohort-shape
shifts**, expected class per the
`feedback_versioning_policy_cif_narrative_consistency` policy. No
correctness regressions surfaced during merges.

## Version implication

**Next release: v0.6.0 (MINOR)** under the CIF ↔ narrative-CIF
consistency policy documented in `CHANGELOG.md`. Multiple MINOR
drivers cascade CIF structure or RNG shape, requiring a fresh
`narrate` run for consistency:

- **MINOR drivers (per commit body)**: #933, #937, #951, #954, #956.
- **MINOR drivers (RNG-stream shift for a resource emission)**:
  #928 (deceased-subset immunization stream), #955 (per-patient
  `AllergyIntolerance` sub-RNG).
- **PATCH-scope entries** (FHIR-emit-only or reference-scrubber, no
  RNG shape or CIF-schema drift): #929, #930, #932, #934, #935,
  #948, #949, #950, #952, #953, #960.

The two MINOR-adjacent classifications (#928 immunization shift,
#955 per-patient allergy stream) mean full `narrate` + regen is
required at release time to keep the narrative CIF aligned with the
structured CIF the emitters now produce.

## Memory candidates

Genuinely new patterns surfaced across the batch that may be worth
persisting to maintainer auto-memory. Left here for the maintainer's
own decision — not written into `~/.claude/projects/.../memory/`.

- **Sex-locked ICD-10 dispatch requires a canonical yaml, not inline
  tables (#947)**. Two per-file inline `_SEX_RESTRICTED_ICD = {"N40":
  "M"}` tables covered only BPH; every other anatomy-locked ICD was
  silently emit-able. Pattern: whenever a dispatch table needs a
  code-scoped restriction, resist inlining — sink it to shared
  yaml + one helper module.
- **RNG-neutral candidate re-picking (#947)**. When the top-ranked
  candidate is filtered out post-hoc, walk the already-sorted
  candidate list rather than sampling a fresh candidate. Consumes
  no fresh RNG state, preserves cross-platform bit-reproducibility.
- **Universal bundle-finalize filters need a dangling-ref
  scrubber sibling (#953)**. Dropping resources leaves
  `.result[]` / `.section.entry[]` / `.hasMember[]` / `.derivedFrom[]`
  / `.basedOn[]` / `.report[]` / `.context.related[]` /
  `MedicationAdministration.request` pointing at ghosts. A fixed-
  point-bounded (3-pass) second-pass scrubber closes the gap.
  Companion to the death-gate + snapshot-gate filters.
- **NKA is a positive assertion, not a default (#942)**. The absence
  of an `AllergyIntolerance` row is ambiguous between "no known
  allergy" and "not assessed". Every emitted patient should carry
  either a real allergen or SNOMED 716186003; downstream analytics
  cannot rely on absence.
- **Anthropometric emission via SHA256 sub-seed pattern (#951)**. A
  new per-encounter numeric field can piggy-back on
  `hashlib.sha256(patient_id|encounter_id|suffix)` → Gaussian
  quantile via `mpmath.erfinv` (prec=128) — the same pattern as
  `_derive_rh_factor`, and RNG-neutral against the master stream.
  Fifth documented consumer of this pattern.
- **snapshot_date plumbing is shared context, not per-builder arg
  (#948 + #953)**. Multiple downstream consumers need
  `snapshot_date` (Coverage.status derivation, universal filter, any
  future date-scoped emission). Route it via
  `BundleContext.snapshot_date` populated once from
  `cif/metadata.json`; individual builders read from context, never
  re-parse.
