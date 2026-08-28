# Session 89 review — Issue #854 closeout + post-p=500/p=1000 audit resolutions

**Dates**: 2026-08-27 → 2026-08-28
**Scope**: post-Issue-#854 quality review at p=500 (JP) and p=1000 (JP),
plus the resolutions that landed in the extended session.

## Timeline

1. **Issue #854 closeout** (2026-08-27) — Bucket A+B+C row 1-18 = 20 PRs
   (#878-#900) merged; opaque-id migration covers 21 resource types /
   ~130 cross-ref sites / ~40 modules. Full unit + integration + JP CI
   green. See individual PR bodies + `docs/history/plans-archive/`.
2. **Versioning policy formalisation** (#895) — SemVer scoped to
   CIF↔narrative-CIF-consistency contract; retroactive rename
   v0.5.0 → v0.4.1 for the FHIR-emit-only Bucket A+B tranche.
3. **Post-close p=500 review, 8-dimension** — 5 gaps found (P0 MA
   opaque migration miss / P1 J44 chronic age-gate on minors / P2×3
   dual-slot mb-org text, discharge MR rpNumber dup, mb-org category
   text). All 5 fixed same day via PRs #896-#900.
4. **Post-close p=1000 review, 11-dimension** — 4 additional
   findings, 3 turned out to be metric-definition errors (documented
   in this session as A-1 / A-2 / B-4), 1 was a real bug (B-3).

## Findings tally

| # | Dim | Finding | Resolution |
|---|---|---|---|
| P0 | Cross-ref opaque | MA `.id` compound not migrated | ✅ PR #896 |
| P1 | Chronic age gate | J44 (COPD) implied to 6/7-yr-olds | ✅ PR #897 MINOR (age gate table) |
| P2 | Dual-slot | `Composition.section.code` text missing | ✅ PR #898 |
| P2 | JP rp collision | Discharge MR rpNumber dup | ✅ PR #899 |
| P2 | Dual-slot | mb-org/mb-sus category text missing | ✅ PR #900 |
| A-1 | Immunization | 100% ≥1 record vs 53% per-season MHLW | ✅ PR #901 (docs) — false positive; metric mismatch |
| A-2 | Age distribution | 65+ 48% vs 30% Census | ✅ PR #901 (docs) — by-design catchment skew, correct against MHLW 患者調査 |
| B-3 | Chronic prevalence | 2-5× over-shoot on cascading comorbidity codes | ✅ PR #902 — real bug; marginal-preserving engine |
| B-4 | AllergyIntolerance | 13.5% vs 30-40% ANY allergic disease | ✅ PR #903 (docs) — apples-to-oranges scope; correct against real EHR 10-20% |

Deferred:
- **B-3 phase 2** — Issue #739 base_prev downscales (E11.9 / N18 / US
  T2DM/COPD) are now over-compensations under the marginal-preserving
  engine; restore to intended hospital-cohort targets in a follow-up
  recalibration PR. Target: v0.5.1 or later.
- **p=10000 periodic deep audit** — reserved for future release gates
  and cross-tab audits that need larger cohorts than p=1000 supports.
- **US p=1000 audit** — symmetric to JP audit; B-3 engine change
  applies to US too but marginal convergence has only been verified on
  JP p=1000 s=42.

## B-3: marginal-preserving prevalence (technical summary)

Root cause (old engine, JP p=1000 s=42 pre-fix):

```
I25 (IHD) age 70+:  actual 0.488 vs target 0.10  → 4.9× over
E78 age 70+:        actual 0.824 vs target 0.45  → 1.8× over
N18 age 70+:        actual 0.260 vs target 0.12  → 2.2× over
Mean chronic conds: 3.24        vs MHLW 65+ 2.3 → 1.4× over
```

The old `population/engine.py` sampled each chronic code as
`base_prev × corr_mult(patient) × life_mult(patient)`, with `corr_mult`
compounding multipliers from all already-sampled prior codes. For a
typical elderly patient with I10 + E78 + I50, the multipliers stacked
(2.0 × 2.2 × 2.2 = 9.68×), producing marginals far above the yaml target
even though each per-code multiplier was epidemiologically defensible.

Fix: rescale per-patient probability by the population-expected compound
multiplier, computed analytically from the target marginals of prior
codes + the population BMI × smoking distribution.

```
scaled_base = base_prev / E[compound multiplier over (age, sex)]
final_prev  = min(1, scaled_base * corr_mult(patient) * life_mult(patient))
```

Because `E[corr_mult × life_mult] ≈ E[compound]` (independence of BMI ×
smoking × prior-code sampling), the population marginal converges to
`base_prev` while each multiplier still shapes WHICH patients get the
condition.

New pure helpers in `population/engine.py` — all inputs derived from
existing yaml, no new tunable constants per grand-design principle:

- `_target_prev_at_age`
- `_bmi_category_probabilities` (analytic Normal CDF via `math.erf`)
- `_smoking_status_probabilities`
- `_expected_lifestyle_multiplier`
- `_expected_comorbidity_multiplier`

Post-fix marginals at JP p=1000 s=42:

```
I25 70+:  0.161  (was 0.488, target 0.10; residual +0.061 is care-seeking
                 filter bias — by design)
E78 70+:  0.520  (was 0.824, target 0.45)
N18 70+:  0.108  (was 0.260, target 0.12) ✅
Mean:     2.63   (was 3.24, MHLW 65+ 2.3)
```

Cascade side effects: 4,775 unit tests pass (+3 new marginal-preservation
tests, +2 rewritten to test correlation shape within mixed cohort);
1 integration test needed a seed migration (seed=42 → 43) because
the cohort reshape lost a specific AFib + 2-inpatient-admission +
newly-started-anticoag fixture at that seed.

Under the CIF↔narrative-CIF-consistency versioning policy this is a
MINOR bump (`chronic_conditions` list changes per patient) → v0.5.0.

## Lessons learned

1. **Audit metric definition matters** — three of the four p=1000
   findings turned out to be apples-to-oranges benchmark comparisons:
   per-season MHLW rate vs cumulative EHR-window record, general Census
   vs care-seeking-filtered cohort, general allergic-disease
   epidemiology vs FHIR AllergyIntolerance documentation scope. The
   correct move was to fix the audit script and document scope, not
   change code.
2. **Marginal-preserving sampling is a first-class pattern** — when
   correlation multipliers stack, the population marginal drifts far
   from the per-code target. Rescaling by `E[compound]` restores
   marginal preservation while retaining the correlation shape the
   multipliers encode.
3. **Constants live in external config not code** (grand design) — the
   B-3 engine change added zero new tunable constants; every input
   comes from existing yaml.
4. **Care-seeking filter compounds population marginals** — the
   emitted cohort skews sicker than the sampled population regardless
   of engine correctness. This is by-design hospital-catchment behavior
   but must be documented so future audits don't mis-frame it.

## Cross-references

- Obsidian:
  - `[[concepts/constants-live-in-external-config-not-code]]` (grand design)
  - `[[concepts/cif-narrative-consistency-versioning]]` (SemVer scope)
- Repo:
  - `docs/history/plans-archive/` (Issue #854 archive)
  - `CHANGELOG.md` (per-PR audit trail for v0.5.0)
  - `scripts/audit_realworld_stats_jp.py` (correct benchmark script)
  - `clinosim/modules/population/README.md` (Marginal-preserving section)
  - `clinosim/modules/immunization/README.md` (Cumulative vs per-season)
  - `clinosim/modules/allergy/README.md` (AllergyIntolerance scope)

## Ownership

Session 89 extended cycle. Maintainer: `tomo.okuyama@gmail.com`.
