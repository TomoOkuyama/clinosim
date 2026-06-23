# Phase 2a (D-dimer + causes_vte + J5) — Data-Quality Review

- **Date:** 2026-06-24
- **PR:** feat/phase2a-vte-d-dimer (master `b6bc8eab` + this branch)
- **Spec:** `docs/superpowers/specs/2026-06-24-phase2a-vte-d-dimer-design.md`
- **Plan:** `docs/superpowers/plans/2026-06-24-phase2a-vte-d-dimer.md`
- **Generator:** `python -m clinosim.simulator.cli generate -s 42 --format fhir csv`
  - US: p=10000
  - JP: p=5000
- **DQR script:** `scratchpad/dqr_phase2a_vte_review.py`
- **Raw output:** `scratchpad/phase2a_dqr_us.md` / `phase2a_dqr_jp.md`
- **Byte-diff evidence:** `scratchpad/phase2a_byte_diff_results.md`

## Verdict

**Pass on all three axes.** D-dimer (LOINC 48065-7 / JLAC10 2B140) is
fully active end-to-end; the `causes_vte` scenario flag lifts PE / DVT /
embolic ischemic stroke into the clinically positive range; sepsis
without VTE stays appropriately non-specific. The J5 wiring fix
(`scenario_flags_from_protocol` helper at every `derive_lab_values`
call site) holds master byte-diff for unrelated cohorts while letting
ED-route MI patients reach MI-grade troponin.

- US: **945 D-dimer Observations** across the seven D-dimer-ordering
  disease cohorts, all with reference ranges.
- JP: **45 D-dimer Observations**, fewer because the JP cohort is
  smaller (p=5000) and VTE incidence is lower.
- Master byte-diff: 9 NDJSON files (Patient / Encounter / Condition /
  Medication* / Procedure / ImagingStudy / Immunization / FamilyMemberHistory)
  **byte-identical** to master `b6bc8eab` on both countries; only
  Observation.ndjson changes (+65 US / +15 JP), DR unchanged
  (D-dimer is panel-external to LOINC 24373-3 Coag panel).

## Structural axis — PASS

| Check | US (p=10000) | JP (p=5000) |
|-------|--------------|-------------|
| D-dimer Observations with referenceRange | 945/945 = 100% (PASS) | 45/45 = 100% (PASS) |
| `display == code` or empty on D-dimer codings | 0 (PASS) | 0 (PASS) |
| D-dimer code → display resolution | `48065-7 → D-dimer` | `2B140 → D-Dダイマー` |

## Clinical axis — PASS

| Check | US p50 | JP p50 | Threshold |
|-------|--------|--------|-----------|
| PE (I26) admit-day D-dimer | 4.60 ug/mL [n=24] | 4.69 ug/mL [n=3] | ≥ 4 (positive) ✓ |
| DVT (I80) admit-day D-dimer | 4.70 ug/mL [n=22] | 4.91 ug/mL [n=1] | ≥ 4 (positive) ✓ |
| Cerebral infarction (I63) admit-day D-dimer | 4.45 ug/mL [n=119] | 4.67 ug/mL [n=11] | ≥ 4 (positive) ✓ |
| Sepsis (A41) admit-day D-dimer — should be non-specific | 0.84 ug/mL [n=50] | 0.90 ug/mL [n=9] | < 2 (specificity) ✓ |
| Whole-cohort D-dimer p10 / p50 / p90 | 0.48 / 0.60 / 4.47 | 0.56 / 0.95 / 5.04 | in [0.15, 20] clamp ✓ |

Healthy / non-VTE baseline US p10 = 0.48 is well below the typical
laboratory cutoff (0.50 ug/mL), confirming specificity. Whole-cohort p90
of ~4.5 reflects that the cohort is disease-weighted (the seven D-dimer-
ordering diseases include sepsis / MI / COPD where D-dimer rises from
inflammation/DIC even without VTE).

### J5 evidence — Troponin distribution

| Bucket | US count | JP count | Notes |
|--------|----------|----------|-------|
| Total Troponin_I Observations | 4945 | 156 | |
| > 5 ng/mL | 2531 | 48 | MI-grade or higher |
| > 30 ng/mL | 2499 | 43 | clearly MI-territory |

A large share of US Troponin_I results land above the MI threshold —
inpatient `acute_mi` patients (causes_myocardial_injury Pass-1
wiring, pre-existing) plus the J5 fix that now exercises the same flag
in any ED-route MI presentation. The byte-diff @ p=2000 showed
Troponin distribution unchanged because that smaller cohort did not
include an ED-route MI; the p=10000 cohort surfaces the J5-active
population, and the helper is proven correct end-to-end by
`tests/integration/test_panel_expansion_coag.py::test_ed_mi_now_emits_high_troponin_after_j5_fix`.

## JP language axis — PASS

| Check | Result |
|-------|--------|
| US output Japanese leak in D-dimer fields | 0 (PASS) — scanned 945 resources |
| JP output Japanese coverage in D-dimer fields | 90 instances (PASS) — scanned 45 resources |
| `jlac10.yaml` 2B140 `ja` | `D-Dダイマー` (JCCLS-official, not English abbreviation) ✓ |

PR #76's lesson preserved.

## Byte-diff invariant — PASS (AD-59)

US/JP @ p=2000 seed=42 vs master `b6bc8eab`. All nine expected-IDENTICAL
NDJSON files matched sha256 between master and branch on both countries:

- Patient, Encounter, Condition, MedicationRequest, MedicationAdministration,
  Procedure, ImagingStudy (MISSING both), Immunization, FamilyMemberHistory
  — all `OK`.
- Observation: US +65 lines (all D-dimer), JP +15 lines (all D-dimer).
- DiagnosticReport: unchanged (0 delta) on both countries — D-dimer is
  panel-external by LOINC 24373-3 authoritative scope.
- Troponin distribution unchanged at p=2000 (no ED-route MI surfaced in
  the smaller cohort lottery); the helper is proven correct by the
  ForcedScenario integration test above.

The AD-59 per-order RNG isolation (PR #74 `panel_specimen_seed` +
PR #78 `individual_lab_seed`) keeps this PR's additions cohort-neutral,
as designed.

## Follow-ups (deferred to subsequent PRs)

- **Phase 2b**: `on_anticoagulation` axis for warfarin/heparin INR
  therapeutic-range modelling (I5). Currently `PT_INR = 1 + (1-hepatic)*2
  + coag*1.5` cannot represent the 2.0–3.0 therapeutic range of
  anticoagulated patients.
- **D-dimer LOS-mid analysis**: walk multi-day labs of VTE patients
  who develop concomitant DIC over LOS, confirming D-dimer trajectory.
- **I4 / I6 / I7**: deferred from PR #80 backlog, unchanged.
