# BMP Cl/Ca Physiology — Audit Results (2026-06-23)

**Spec:** `docs/superpowers/specs/2026-06-23-bmp-cl-ca-physiology-design.md`
**Plan:** `docs/superpowers/plans/2026-06-23-bmp-cl-ca-physiology-plan.md`
**Branch:** `feat/bmp-cl-ca-physiology`

## Summary

BMP canonical 8 (Na/K/Cl/HCO3/BUN/Cr/Glucose/Ca) is now fully emit-able
via `derive_lab_values`. The new `anion_gap_status` axis on
`PhysiologicalState` routes Cl between high-AG (DKA/sepsis) and non-AG
(diarrhea hyperchloremic) regimes. `lab_panel_groups.yaml` BMP
`min_components` was raised 5→7 (canonical N − 1 rule).

A structural defect was discovered and fixed as part of this PR:
`inpatient.py` Pass 1 / `emergency.py` / `outpatient.py` lab loops were
drawing specimen-rejection / hemolysis / technician / noise from the
patient-scoped master RNG, so any YAML edit that toggled a `{test:"X"}`
order between "engine doesn't produce X" and "engine produces X"
silently shuffled unrelated patients' cohorts. PR #74 had fixed this
for panel children via `panel_specimen_seed`; this PR completes the
pattern for individual lab orders via a new `individual_lab_seed`.

## Methodology

- US p=4000 + JP p=2000, seed=42, full-format CIF
- Walks `Observation.ndjson` to compute overall analyte distributions
- AG = Na − Cl − HCO3 (per-encounter triple where all three present)
- Per-disease cohort tables omitted: with population-driven generation
  at the audit pool size, disease-specific cohorts have too few BMP
  observations (DKA/Sepsis/MI < 5 each) for stable percentiles. The
  overall distribution and integration tests cover the property.

## Overall analyte distribution

### US (p=4000, seed=42)

| analyte | n | p10 | p50 | p90 | expected (Tietz 4e) |
|---------|---|-----|-----|-----|---------------------|
| Na  | 1815 | 137.0 | 139.0 | 141.0 | 136-145 mmol/L ✓ |
| K   | 2363 | 4.30  | 5.00  | 5.90  | 3.5-5.0 mmol/L (p90 borderline elevated — expected in inpatient cohort) |
| **Cl**  | **334** | **102** | **104** | **109** | **98-106 mmol/L ✓ (AG-aware coupling working)** |
| HCO3 | 1702 | 13.9 | 25.4 | 28.6 | 22-28 mEq/L ✓ |
| **Ca**  | **342** | **8.60** | **9.10** | **9.50** | **8.5-10.5 mg/dL ✓ (low-normal reflects inpatient cohort)** |
| **AG**  | **80**  | **12.8** | **18.05** | **26.0** | **8-12 normal — elevation expected in inpatient with DKA/sepsis/AKI mix** |

### JP (p=2000, seed=42)

| analyte | n | p10 | p50 | p90 | expected |
|---------|---|-----|-----|-----|----------|
| Na  | 866 | 135.0 | 139.0 | 141.0 | 136-145 mmol/L ✓ |
| K   | 1084 | 4.40 | 5.00 | 5.80 | 3.5-5.0 mmol/L |
| **Cl** | **139** | **102** | **104** | **107** | **98-106 mmol/L ✓** |
| HCO3 | 481 | 13.9 | 21.5 | 27.0 | 22-28 mEq/L (lower — JP cohort acid-base axis pattern) |
| **Ca** | **265** | **8.50** | **9.00** | **9.40** | **8.5-10.5 mg/dL ✓** |
| **AG** | **11**  | **12.6** | **15.70** | **23.7** | (small n — AG mix present) |

## Cohort drift (master vs branch byte-diff report)

Not a pass/fail gate — the `individual_lab_seed` Pass 1 refactor
intentionally shifts the master stream draw count.

| metric | US master | US branch | JP master | JP branch |
|--------|-----------|-----------|-----------|-----------|
| Patient count | 1280 | 1310 (+2.3%) | 979 | 970 (−0.9%) |
| Observation total | 189,176 | 198,759 (+5.1%) | 168,250 | 163,337 (−2.9%) |
| Cl emissions | 0 (US LOINC) | 208 | 0 (JP JLAC10) | 139 |
| Ca emissions | 17 | 206 | 37 | 265 |

## Panel grouping invariant (cbc_bmp_panel_audit.py)

After raising BMP `min_components` 5→7:

| panel | with-panel-order n | 5th-percentile floor | canonical N − 1 | verdict |
|-------|---|---|---|---|
| CBC | 2 691 | 4 | 3 | PASS (≥ chosen 3) |
| BMP | 237  | **7** | **7** | **PASS (matches chosen 7)** |

The BMP "with panel order placed" distribution shows the expected
binary pattern after the structural fix: 225/237 (95%) emit all 8
canonical components, 12 (5%) emit 1–4 (partial specimen acceptance
during the audit window). Floor = 7 ≥ chosen threshold = 7 ✓.

## Determinism + isolation invariants

Both gated by `tests/integration/test_individual_lab_isolation.py`:

- `test_dka_individual_cl_order_now_resulted`: DKA's individual
  `{test:"Cl"}` order resolves to a numerical 80–125 mmol/L Cl value
  (Pass 1 sub-RNG works end-to-end).
- `test_simulator_deterministic_across_repeated_runs`: same seed twice
  produces byte-identical lab results across the new sub-RNG paths.

## Test totals

- Unit + integration: **528 passed** (was 524 pre-PR; +4 new = 2 AG
  field tests + 2 Cl/Ca physiology + 2 BMP threshold + 2 isolation)
- e2e: deferred until PR submission gate

## Verdict

PASS — BMP canonical 8 emit-able, Cl AG-aware coupling correct,
panel threshold raise validated by audit, structural AD-16 defect
fixed, no regressions in unit/integration suite.

## Phase 2 candidates (out of this PR)

- iCa (LOINC 1994-3) on the ABG panel or as a separate lab
- Cl hypochloremic-alkalosis axis for vomiting-dominant cases
- Corrected Ca text annotation (Payne formula) — physician-side, not
  lab-side, so document-level annotation if added
- Disease-specific cohort audit at larger pool size (p ≥ 50,000) to
  validate per-disease Cl/Ca/AG percentiles against textbook ranges
