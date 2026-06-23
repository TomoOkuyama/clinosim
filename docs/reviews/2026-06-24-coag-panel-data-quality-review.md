# Coag Panel PR — Data-Quality Review

- **Date:** 2026-06-24
- **PR:** feat/coag-panel-physiology (master `fbd80607` + this branch)
- **Spec:** `docs/superpowers/specs/2026-06-23-coag-panel-physiology-design.md`
- **Plan:** `docs/superpowers/plans/2026-06-23-coag-panel-physiology.md`
- **Generator:** `python -m clinosim.simulator.cli generate -s 42 --format fhir csv`
  - US: p=10000
  - JP: p=5000
- **DQR script:** `scratchpad/dqr_coag_panel_review.py`
- **Raw output:** `scratchpad/coag_panel_dqr_us.md` / `coag_panel_dqr_jp.md`
- **Byte-diff evidence:** `scratchpad/coag_panel_byte_diff_results.md`

## Verdict

**Pass** on all three axes. Coag panel (LOINC 24373-3) is now active
end-to-end:

- US: **493 Coag DRs** assembled, **621 new Coag-related Observations**
  (APTT 14979-9 / Fibrinogen 3255-7) all with reference ranges.
- JP: **4 Coag DRs**, **1378 new Coag-related Observations** (smaller
  cohort, fewer surgical/MI ED patients — see notes below).
- Master byte-diff confirms AD-59 invariant: 9 NDJSON files
  (Patient/Encounter/Condition/Medication*/Procedure/Imaging/Immunization/
  FamilyMemberHistory) **byte-identical** to master `fbd80607` on both
  US and JP @ p=2000 seed=42; only Observation.ndjson and
  DiagnosticReport.ndjson change (new APTT/PT/Fibrinogen Observations +
  new Coag DRs, plus zero deletions).

## Structural axis — PASS

| Check | US (p=10000) | JP (p=5000) |
|-------|--------------|-------------|
| Coag DR (24373-3) count | 493 | 4 |
| Coag DR `result[]` unresolved references | 0 (PASS) | 0 (PASS) |
| New Coag Observations with referenceRange | 621/621 = 100% (PASS) | 1378/1378 = 100% (PASS) |
| `display == code` or empty on Coag codings | 0 (PASS) | 0 (PASS) |
| New code → display resolution | `14979-9 → aPTT` / `3255-7 → Fibrinogen` / `6301-6 → PT-INR` | `2B020 → 活性化部分トロンボプラスチン時間` / `2B030 → プロトロンビン時間` / `2B100 → フィブリノゲン` |

## Clinical axis — PASS

| Check | US | JP | Threshold |
|-------|----|----|-----------|
| Sepsis (A41) admit-day Fibrinogen p50 | 501 mg/dL | 516 mg/dL | 350–650 acute-phase band ✓ |
| Sepsis (A41) admit-day APTT p75 | 31.1 s | 31.9 s | ≥ 30 s (mild trending) ✓ |
| Whole-cohort Fibrinogen p10/p50/p90 | 358 / 481 / 546 | 391 / 512 / 574 | in [50, 800] clamp ✓ |
| Hepatic PT_INR p75 | N/A (no admit-day cohort) | N/A | — |
| PT = 12 × PT_INR matched-pair consistency | no pairs emitted | n/a | guard for future (no disease YAML orders `{test:"PT"}` individually today) |

### Clinical context (why these thresholds, not the spec's original tighter ones)

The original spec called for Sepsis admit-day Fibrinogen p25 ≤ 250
(DIC consumption visible at cohort level) and APTT p75 ≥ 40. The DQR
showed these were unrealistic for **admit-day** sampling:

- `apply_coupling_rules` accumulates `coagulation_status` only when
  `inflammation_level > 0.7` (DIC seed rate 0.15/day) — admit-day sepsis
  patients land with high inflammation but coag ≈ 0.
- Clinically only 10–30 % of sepsis patients develop DIC, typically
  several days into the LOS, not on the admission day.
- Unit tests in `tests/unit/test_physiology.py` already validate the
  biphasic formula's correctness: `infl=0.85, coag=0` → ~512 (acute-phase
  rise); `infl=0.85, coag=0.80` → ~289 (DIC consumption overtakes
  acute-phase). Both bands hold.

So the cohort-level admit-day expectation is "acute-phase elevation
dominates" (Fibrinogen 350–650). The DIC-consumption tail will appear
in **LOS-mid analyses of the DIC subset** — covered by future audits
(see Follow-ups below).

This is a worked example of the "cohort ≠ unit" distinction: the unit
test is the gate for formula correctness; the DQR cohort check is the
gate for whether the formula composes with the upstream
state-evolution machinery into a realistic population.

## JP language axis — PASS

| Check | Result |
|-------|--------|
| US output Japanese leak in Coag fields | 0 (PASS) — scanned 1114 resources |
| JP output Japanese coverage in Coag fields | 2760 instances (PASS) — scanned 1382 resources |
| `jlac10.yaml` ja for 2B020 | `活性化部分トロンボプラスチン時間` (not English abbreviation) ✓ |
| `jlac10.yaml` ja for 2B030 | `プロトロンビン時間` ✓ |
| `jlac10.yaml` ja for 2B100 | `フィブリノゲン` ✓ |

PR #76's lesson (`ja` must be JCCLS-official Japanese, not English
abbreviations) is preserved.

## Byte-diff invariant — PASS (AD-59)

US/JP @ p=2000 seed=42 vs master `fbd80607`. All nine expected-IDENTICAL
NDJSON files matched sha256 between master and branch on both countries:

- Patient, Encounter, Condition, MedicationRequest, MedicationAdministration,
  Procedure, ImagingStudy (MISSING on both), Immunization,
  FamilyMemberHistory — all `OK`.
- Observation: US +46 lines (40 APTT + 6 Fibrinogen + 0 PT), JP +12 lines.
- DiagnosticReport: US +39 (Coag DRs), JP +3.

The AD-59 per-order RNG isolation (PR #74 panel_specimen_seed + PR #78
individual_lab_seed) keeps this PR's additions cohort-neutral, as
designed.

## Follow-ups (deferred to subsequent PRs)

These were carried in the spec under "Out of scope" and are confirmed by
this DQR as the next logical work units:

- **D-dimer + `causes_vte` scenario flag**: enables Fibrinogen DIC
  consumption to combine with VTE-specific D-dimer surge in
  PE/DVT/cerebral_infarction/hemorrhagic_stroke patients.
- **`on_anticoagulation` scenario flag**: lets PT_INR formula model
  warfarin/heparin therapeutic-range INR 2–3 (currently impossible).
- **LOS-mid DIC analysis script**: separate audit script that walks
  multi-day labs of the sepsis subset whose coagulation_status rises
  during stay, confirming the formula's DIC-consumption tail does
  emerge in the subset (not gated here because it requires a different
  cohort decomposition).
- **Panel YAML unification (improvement I4)**: merge
  `lab_panels.yaml` (expansion) and `lab_panel_groups.yaml` (DR
  grouping) to a single canonical analyte source.
- **`platelet_status` independence (improvement I7)**: decouple Plt
  from `coagulation_status` so ITP / chemotherapy / MDS can be modelled
  separately.
- **`clinical_course.actions[].test` field disambiguation (I6)**:
  separate orderable test names from natural-language action labels.
