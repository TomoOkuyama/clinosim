# Coag Panel Physiology + LOINC 24373-3 Activation — Design Spec

- **Date:** 2026-06-23
- **Status:** DRAFT (pending user review)
- **Predecessors:** PR #74 (`panel_specimen_seed`), PR #75 (`min_components` raise), PR #78 (`individual_lab_seed`, BMP Cl/Ca, AD-59), PR #79 (docs sync)
- **Pattern lineage:** AD-57 BNP-pattern surgical (formula-only, state-unchanged) + AD-59 per-order lab RNG isolation
- **Branch:** `feat/coag-panel-physiology` (to be created from `master`)

## 1. Goal

Activate the **Coag DiagnosticReport panel (LOINC 24373-3)** by implementing the
missing `derive_lab_values` branches so that the canonical Coag components
(`PT`, `PT_INR`, `APTT`) all resolve to results, and so that `Fibrinogen` —
already ordered by sepsis/hemorrhagic-stroke YAMLs but silently dropped —
emits as an individual Observation with realistic DIC physiology.

Currently:

- `lab_panel_groups.yaml:52-56` defines `Coag: components: [PT, PT_INR, APTT]`,
  `min_components: 2`, LOINC `24373-3` — but **only `PT_INR` is derived** in
  `physiology/engine.py:307`, so the panel never hits `min_components` and no
  Coag DR is ever assembled.
- 18 disease YAMLs order `{test: "PT_INR"}`, 3 also order `{test: "APTT"}`,
  2 order `{test: "Fibrinogen"}` — but only `PT_INR` results.
- `locale/{us,jp}/reference_range_lab.yaml` already declares ranges for
  `D_dimer` and `Fibrinogen` (a typical "range exists, derive missing" gap).

## 2. Scope

### In-scope (this PR — Option B)

1. **Physiology**: extend `physiology/engine.py:derive_lab_values` with
   `APTT`, `PT` (seconds), `Fibrinogen` — all derived from existing state
   axes (`coagulation_status`, `inflammation`, `hepatic_function`); **no new
   `PhysiologicalState` axis**.
2. **Panel expansion source (`lab_panels.yaml`)**: add `Coag`, `LFT`,
   `Lipid`, `UA` panels so `{test: "Coag"}` etc. can be ordered as panel
   expansions (currently only ABG/CBC/BMP can). Refresh the stale comment
   about `Cl/Ca` silent-dropping (resolved by PR #78).
3. **Panel grouping source (`lab_panel_groups.yaml`)**: keep Coag at the
   authoritative LOINC 24373-3 scope (`[PT, PT_INR, APTT]`); add a comment
   recording why `Fibrinogen` / `D_dimer` are NOT in this panel
   (LOINC 24373-3 is "aPTT and PT/INR panel", a different LOINC covers
   broader DIC panels — out of scope here).
4. **Locale**: add `APTT` / `PT` / `Fibrinogen` entries to
   `code_mapping_lab.yaml` (US LOINC, JP JLAC10) and `APTT` / `PT` ranges
   to `reference_range_lab.yaml` (Fibrinogen range already present).
5. **Authoritative code data**: add `APTT 14979-9`, `PT 5902-2`,
   `Fibrinogen 3255-7` to `codes/data/loinc.yaml` (NLM/Regenstrief
   verified); add JLAC10 codes verified against JSLM v137
   (`reference_jlac10_source` memory) to `codes/data/jlac10.yaml` with
   JCCLS-official Japanese names in `ja` (PR #76 lesson: never an English
   abbreviation in `ja`).
6. **AD-59 invariant guard**: extend `tests/integration/test_individual_lab_isolation.py`
   to cover the new analytes — adding a `{test: "Fibrinogen"}` order to one
   disease YAML must NOT shift unrelated patients' cohorts (validated via
   per-order sub-rng draw routing already established by PR #78).
7. **Whole-population DQR**: US p ≥ 10,000 + JP p ≥ 5,000, seed=42, all
   three axes (structural / clinical / JP language).
8. **Docs sync in same PR** (PR #79 lesson): README.md, README.ja.md,
   DESIGN.md, `modules/physiology/README.md`, `modules/observation/README.md`,
   CLAUDE.md, TODO.md.

### Out of scope (deferred to follow-up PRs)

- **`D_dimer` derive + VTE-specificity flag** — needs a new scenario flag
  `causes_vte` (AD-57 family) on PE/DVT/cerebral_infarction/hemorrhagic_stroke
  YAMLs. Bundled with the next item below.
- **`on_anticoagulation` scenario flag for warfarin/heparin INR targeting**
  — current `PT_INR` formula `1.0 + (1 - hepatic) * 2.0 + coag * 1.5` cannot
  express the therapeutic-range INR 2-3 of anticoagulated patients (improvement
  I5). Pair with `D_dimer` in a single Phase-2 PR.
- **Panel-YAML unification refactor** — `observation/.../lab_panels.yaml`
  (expansion source) and `output/.../lab_panel_groups.yaml` (DR grouping
  source) duplicate canonical analyte lists for CBC/BMP/ABG. Responsibility
  split is clean (input vs output) but DRY violation. Defer (improvement I4).
- **`clinical_course.actions[].test` field disambiguation** — same field name
  is used both for orderable test names (workup) and for natural-language
  action descriptors (`PT_INR_stat`, `PT_INR_aPTT_fibrinogen_stat` in
  `cerebral_infarction.yaml`). Type-unsafe. Defer (improvement I6).
- **`Plt` multi-factor independence** — current `Plt = max(20, 250 - coag * 200)`
  collapses ITP / chemotherapy / MDS / sepsis to a single axis. Defer to a
  `platelet_status` axis PR (improvement I7).

## 3. Existing-code improvements adopted (uniform rule applied)

Per the uniform rule "既存コードは所与でなく 4 軸で見直し、改善点を提案する"
(memory `feedback_propose_improvements_to_existing`), the following
improvements are folded into this PR:

| # | Improvement | 4-axis | This PR |
|---|---|---|---|
| **I1** | `lab_panels.yaml` had no Coag/LFT/Lipid/UA → `{test:"Coag"}` etc. could not be ordered as panel expansions. Asymmetric with `lab_panel_groups.yaml`. | data ◎ / maintainability ◎ / concept ◎ | **adopted** |
| **I2** | Coag panel components scope (Fibrinogen NOT included) was undocumented — looked like an omission. | data ○ | **adopted (comment)** |
| **I3** | `lab_panels.yaml` header comment "e.g. Cl/Ca in BMP today" was stale post-PR #78. | maintainability ◎ | **adopted** |
| **I8** | `D_dimer` / `Fibrinogen` ranges existed in locale but no derive — emission silently dropped. | data ◎ (core goal) | **adopted (Fibrinogen only; D_dimer deferred)** |

The following improvements are explicitly deferred to follow-up PRs to keep
this PR focused on Coag-panel activation:

- **I4**: panel-YAML unification (separate refactor PR)
- **I5**: `on_anticoagulation` axis (paired with D_dimer Phase-2 PR)
- **I6**: `clinical_course.actions[].test` field disambiguation
- **I7**: `platelet_status` axis independence

## 4. Design

### 4.1 Physiology formulas (`physiology/engine.py:derive_lab_values`)

All three formulas are pure functions of existing `PhysiologicalState`
fields. **No new axis. No state mutation. AD-57 BNP-pattern surgical.**

```python
# --- Coagulation panel: APTT / PT(seconds) / Fibrinogen ---
# coagulation_status drives common-pathway perturbation (DIC, hepatic
# coagulopathy already wired by apply_coupling_rules). PT_INR (existing,
# line 307) and Plt (existing, line 313) already use coagulation_status;
# the three additions below complete the canonical Coag panel and add
# Fibrinogen as a separate DIC marker (panel-external by LOINC 24373-3).

# APTT (activated partial thromboplastin time, seconds). Normal 25-35,
# DIC 60-100+. Intrinsic-pathway sensitive; coagulation_status proxies
# DIC + hepatic factor depletion already aggregated in apply_coupling_rules.
labs["APTT"] = clamp(30.0 + state.coagulation_status * 55.0, 20.0, 150.0)

# PT (prothrombin time, seconds). Mathematically tied to PT_INR via
# INR = (PT / normal_PT)^ISI; with ISI ≈ 1.0 and normal_PT ≈ 12s,
# PT ≈ 12 * PT_INR. We derive PT FROM PT_INR (not in parallel) so the two
# stay numerically consistent across all venues.
labs["PT"] = clamp(12.0 * labs["PT_INR"], 9.0, 90.0)

# Fibrinogen (mg/dL). Biphasic: acute-phase reactant (inflammation ↑↑)
# and consumed in DIC (coagulation_status ↑↑). Healthy baseline 200-400.
# Sepsis without DIC: rises (450+). Sepsis with DIC: falls (<200, hallmark).
# Clamp floor 50 (laboratory measurement floor; clinically <100 = DIC).
labs["Fibrinogen"] = clamp(
    300.0 + infl * 250.0 - state.coagulation_status * 280.0,
    50.0, 800.0,
)
```

Coefficient calibration ties:

- `coagulation_status` is already in `[0.0, 1.0]` (clamped on increment in
  `apply_coupling_rules`). DIC scenarios (sepsis, hepatic failure) push it
  toward 0.7-1.0.
- `inflammation` (variable `infl`) is in `[0.0, 1.0]`. Sepsis pushes 0.7-0.9.
- Sepsis-DIC patient (infl=0.85, coag=0.80): Fibrinogen = 300 + 213 - 224 ≈
  **289** (DIC-borderline, will fall further if coag rises). APTT = 30 + 44
  ≈ **74**. PT ≈ 12 * (1 + (1-hepatic)*2 + 0.80*1.5) = 12 * (1 + 0 + 1.20)
  ≈ **26s** (PT_INR ≈ 2.2). Clinically coherent.
- Healthy patient (infl=0, coag=0): Fibrinogen = **300**, APTT = **30s**,
  PT = **12s**. Reference-range center.

**State invariance**: none of these formulas mutate `state` or its fields.
Pure function of `state.coagulation_status`, `infl`, `labs["PT_INR"]`.

### 4.2 `lab_panels.yaml` (expansion source, observation module)

Add Coag/LFT/Lipid/UA panels for panel-order expansion. Refresh stale comment.

```yaml
# Lab panels (AD-57): one order name → component analytes. A panel order
# expands into one resulted lab order per component (each derived from
# physiology, emitted as its own Observation). Data-driven; add a panel
# here, no code changes.
#
# Components must match the canonical analyte names produced by
# physiology.derive_lab_values(). Missing components are silently dropped
# at the scalar-resulted path (acceptable: the engine catches up later).
#
# NOTE: as of 2026-06-23 (PR #78 Cl/Ca, Coag panel PR) all listed
# components have derives. Any future panel extension must add the derive
# in physiology/engine.py FIRST (or accept silent-drop semantics
# explicitly).

ABG: [pH, pCO2, pO2, HCO3]
CBC: [WBC, Hb, Hct, Plt]
BMP: [Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]
Coag: [PT, PT_INR, APTT]
LFT: [AST, ALT, ALP, T_Bil, Albumin, TP, GGT, LDH]
Lipid: [TC, LDL, HDL, TG]
UA: [Urine_pH, Urine_specific_gravity, Urine_protein, Urine_glucose,
     Urine_ketones, Urine_blood, Urine_nitrite, Urine_leukocyte_esterase]
```

UA components will all silently drop until the future UA-panel PR
implements urine physiology — this is the documented "engine catches up
later" semantics. (Acceptable here because the alternative — omitting UA
from `lab_panels.yaml` — keeps the input/output asymmetry that improvement
I1 set out to remove.)

### 4.3 `lab_panel_groups.yaml` (grouping source, output module)

Keep Coag scope unchanged. Add an explanatory comment that records the
authoritative LOINC 24373-3 boundary, so future readers do not file
"Fibrinogen missing" as a bug.

```yaml
  Coag:
    loinc: "24373-3"
    display: "Activated partial thromboplastin time (aPTT) and Prothrombin time (PT)/INR panel - Platelet poor plasma"
    # LOINC 24373-3 is authoritatively the "aPTT and PT/INR panel".
    # Fibrinogen (3255-7) and D-dimer (30240-9) are NOT part of this panel
    # per Regenstrief. They emit as individual Observations. A broader DIC
    # panel (e.g. LOINC 48995-7 "Coagulation panel") is a future enhancement.
    components: [PT, PT_INR, APTT]
    min_components: 2
```

### 4.4 Locale data (`locale/{us,jp}/`)

**`code_mapping_lab.yaml`** — add entries (verified via authoritative sources):

US (LOINC):
```yaml
APTT: "14979-9"          # NLM clinicaltables.nlm.nih.gov verify
PT: "5902-2"             # NLM verify
Fibrinogen: "3255-7"     # NLM verify (PT-poor plasma, coag assay)
```

JP (JLAC10, JSLM v137 verified — memory `reference_jlac10_source`):
```yaml
APTT: "<TBD-verify>"     # candidate: 2B020 family
PT: "<TBD-verify>"       # candidate: 2B010 family (PT_INR is 2B030)
Fibrinogen: "<TBD-verify>" # candidate: 2B070 family
```

(JP JLAC10 codes will be locked at implementation time against the JSLM
master spreadsheet. If a code is uncertain it gets a `# TODO: verify`
marker per memory `feedback_clinosim_workflow` — never fabricated.)

**`reference_range_lab.yaml`** — add ranges:

```yaml
APTT:
  low: 25
  high: 38
  unit: "s"
PT:
  low: 11
  high: 13
  unit: "s"
# Fibrinogen already present (200-400 mg/dL).
```

### 4.5 Authoritative code-system data

`clinosim/codes/data/loinc.yaml` — add 3 entries with English (and `ja` if
JCCLS-equivalent Japanese term is unambiguous):

```yaml
14979-9:
  en: "aPTT in Platelet poor plasma by Coagulation assay"
  ja: "活性化部分トロンボプラスチン時間"
5902-2:
  en: "Prothrombin time (PT)"
  ja: "プロトロンビン時間"
3255-7:
  en: "Fibrinogen [Mass/volume] in Platelet poor plasma by Coagulation assay"
  # already present (line 142) — verify no duplication; reuse if present.
  ja: "フィブリノゲン"
```

`clinosim/codes/data/jlac10.yaml` — add JCCLS-official Japanese names in
`ja`. **`ja` MUST be the official JCCLS-JSLM display, not an English
abbreviation** (PR #76 enforcement).

### 4.6 AD-59 invariant guard (`tests/integration/test_individual_lab_isolation.py`)

Extend the existing test (added in PR #78) with a new case:

```python
def test_adding_fibrinogen_order_does_not_shift_unrelated_patients():
    """Improvement I8 guard: adding {test: "Fibrinogen"} to a single disease
    YAML must not perturb the patient-master RNG stream → unrelated patients'
    demographics, encounters, and chronic conditions unchanged.

    Validates that the AD-59 per-order sub-rng routing (individual_lab_seed
    + panel_specimen_seed, established by PR #74/#78) keeps new analyte
    additions cohort-neutral.
    """
    # Run baseline (no Fibrinogen order), then run with a Fibrinogen order
    # added to one disease YAML's workup, compare patient demographics:
    # name, dob, sex, chronic_conditions for every patient must be byte-
    # identical. Only the lab Observations of the patient(s) with that
    # disease may change.
```

Also add a `Coag DR appears for at least N patients` smoke check (where
N is calibrated from the audit run — likely ≥ 50% of patients with
PT_INR + APTT orders).

### 4.7 Determinism and byte-diff invariant

Per AD-16 and AD-59:

- **Expected to change**: `Observation.ndjson` (new APTT/PT/Fibrinogen),
  `DiagnosticReport.ndjson` (new Coag DRs).
- **Expected IDENTICAL** (vs master `fbd80607`, same seed=42, p=2000):
  `Patient.ndjson`, `Encounter.ndjson`, `Condition.ndjson`,
  `MedicationRequest.ndjson`, `MedicationAdministration.ndjson`,
  `Procedure.ndjson`, `ImagingStudy.ndjson`, `Immunization.ndjson`,
  `FamilyMemberHistory.ndjson`, manifest.json (modulo new resource counts).
- **Byte-diff verification script**: `scratchpad/coag_panel_byte_diff.py`
  pattern from PR #78.

### 4.8 Testing strategy

- **Unit (physiology)**: 6 acceptance tests in `tests/unit/test_physiology.py`:
  1. Healthy state → APTT 30 ± 1, PT 12 ± 1, Fibrinogen 300 ± 1.
  2. Sepsis-DIC state (infl=0.85, coag=0.80) → APTT ≥ 65, Fibrinogen 200-350.
  3. Severe DIC (coag=1.0) → Fibrinogen ≤ 100.
  4. Hepatic failure (hepatic=0.2, coag=0) → PT ≥ 17 (via PT_INR ≥ 1.4).
  5. PT = 12 * PT_INR (consistency invariant) for any state.
  6. APTT ≥ PT (clinical norm — aPTT measures broader pathway).
- **Unit (panel registry)**:
  - `lab_panels.yaml` Coag panel returns `[PT, PT_INR, APTT]` via the loader.
  - `lab_panel_groups.yaml` Coag still returns `[PT, PT_INR, APTT]`, min=2.
- **Integration**:
  - Existing `test_diagnostic_report_panels.py` — extend with a DKA-sepsis
    fixture that asserts a Coag DR is emitted with ≥ 2 components.
  - `test_individual_lab_isolation.py` — Fibrinogen-add invariant (4.6).
- **e2e**: existing golden suite must remain green. New analytes will
  appear in goldens — regenerate as part of the PR (documented in PR body).

### 4.9 3-axis DQR

Per memory `feedback_pr_merge_dqr_required`. Pre-PR, generate US p=10,000 +
JP p=5,000, seed=42:

**Structural**:
- All Coag-related Observations have `referenceRange` 100%.
- All `code.coding[]` have `display`, no `display == code`.
- New LOINC `14979-9`, `5902-2`, `3255-7` resolve to authoritative
  English text (and Japanese for JP).
- DiagnosticReport `result[]` references all resolve.

**Clinical coherence (admit-day stats)**:
- Sepsis (A41): Fibrinogen p25 ≤ 250 (DIC-trending tail), APTT p75 ≥ 45.
- Hepatic failure (K72) / cirrhosis decompensated: PT p75 ≥ 17, INR p75 ≥ 1.5.
- DKA without DIC (E11): Fibrinogen p50 in 250-450 (no consumption).
- Healthy outpatient: APTT 25-38, PT 11-13, Fibrinogen 200-400 (>95% in range).
- Coag DR count: at least N (calibration from real audit).
- Internal invariant: `PT == 12 * PT_INR` to within 0.1s for every patient.

**JP language**:
- US output has zero Japanese characters in new Coag fields.
- JP output: APTT/PT/Fibrinogen `display` and DR text in proper Japanese.
- New JLAC10 codes' `ja` fields use JCCLS-official Japanese names
  (not English abbreviations — PR #76 enforcement).
- Authoritative source citation in `jlac10.yaml` comment.

DQR script: `scratchpad/dqr_coag_panel_review.py` adapted from
`scratchpad/dqr_pr75_review.py`. Output report saved as
`docs/reviews/2026-06-23-coag-panel-data-quality-review.md`.

### 4.10 Docs sync (in the same PR — PR #79 lesson)

Files to update in this PR:

- **`README.md`** — physiology-axis count (currently mentions BMP canonical 8;
  add Coag canonical 3 + Fibrinogen). Bump panel count.
- **`README.ja.md`** — mirror README.md.
- **`DESIGN.md`** — no new ADR is needed (AD-57 BNP-pattern surgical and
  AD-59 per-order RNG isolation already cover this work). Add a brief note
  under §6.10 (or relevant section) that Coag panel is now active.
- **`clinosim/modules/physiology/README.md`** — document APTT / PT(seconds) /
  Fibrinogen derivations alongside the existing PT_INR/Plt entries.
- **`clinosim/modules/observation/README.md`** — note Coag panel addition
  to `lab_panels.yaml` and the LOINC 24373-3 authoritative scope.
- **`CLAUDE.md`** — no new architecture rule (AD-59 already cited); update
  the "Adding a new disease" / "Adding a new code" guidance with Coag
  canonical 3 example if it improves discoverability.
- **`TODO.md`** — mark Coag panel activation done; carry forward I4/I5/I6/I7
  follow-ups as backlog items.

## 5. Risks

- **Byte-diff cascade (low risk)**: AD-59 sub-rng routing established in
  PR #74/#78 should keep unrelated cohorts unchanged. Mitigation: invariant
  test (4.6) + byte-diff script run as gate.
- **Coefficient miscalibration (medium risk)**: Sepsis-DIC Fibrinogen
  consumption needs validation against an audit; if the formula produces
  Fibrinogen ≤ 200 in only 5% of sepsis patients (too sparse) or 80%
  (too aggressive), recalibrate the `coagulation_status * 280` coefficient.
  Mitigation: DQR pre-PR with calibration loop.
- **JLAC10 verification gap (low risk)**: if a candidate JLAC10 code
  cannot be confirmed against JSLM v137, leave a `# TODO: verify` marker
  rather than fabricate (memory `feedback_clinosim_workflow`).
- **e2e golden regeneration churn (low risk)**: new Observations and DRs
  will change goldens. Standard regeneration step.

## 6. Open questions

- **Q1**: Should `Fibrinogen` be added to `Coag` panel `components` despite
  the LOINC 24373-3 authoritative scope? **Resolution (this spec)**: No.
  Keep `[PT, PT_INR, APTT]` per authoritative LOINC. Fibrinogen emits as
  individual Observation. Document the choice in the YAML comment.
- **Q2**: Should `PT` (seconds) be derived in parallel with `PT_INR`
  (both from state) or derived FROM `PT_INR` for numerical consistency?
  **Resolution (this spec)**: Derive PT from PT_INR (`PT = 12 * PT_INR`).
  This guarantees the two never disagree across releases.
- **Q3**: Should the UA panel be added to `lab_panels.yaml` now even though
  no urine analyte has a derive? **Resolution (this spec)**: Yes — improves
  symmetry with `lab_panel_groups.yaml`; silent-drop semantics are documented
  in the file header. UA will activate when the future UA-panel PR
  implements urine physiology.

## 7. Implementation order (high-level)

To be expanded into a writing-plans plan in the next step:

1. Authoritative code data (LOINC + JLAC10) — additions only, no
   downstream behavior change.
2. Locale code mappings + reference ranges.
3. `physiology/engine.py` `derive_lab_values` extension + 6 unit tests
   (TDD).
4. `lab_panels.yaml` Coag/LFT/Lipid/UA additions + comment refresh.
5. `lab_panel_groups.yaml` Coag comment.
6. AD-59 isolation invariant test extension.
7. Byte-diff invariant verification (`scratchpad/coag_panel_byte_diff.py`).
8. Calibration loop: US p=10k + JP p=5k audit; if Fibrinogen DIC tail or
   APTT tail is mis-calibrated, adjust coefficients and re-run from step 7.
9. 3-axis DQR + `docs/reviews/2026-06-23-coag-panel-data-quality-review.md`.
10. Full docs sync (in the same PR — README, README.ja, DESIGN, module
    READMEs, CLAUDE, TODO).
11. PR.
