# CBC / BMP Panel Expansion + Per-Specimen RNG Refactor — Design

**Date**: 2026-06-23
**Status**: APPROVED-REVISED (scope grew during execution after byte-diff revealed a latent RNG-cascade defect; see §1)
**Sequence**: PR1 of a planned 2-PR sequence (PR2 = audit-driven `min_components` raise + redundancy removal)
**Related**: PR #72 (FHIR DiagnosticReport panel grouping, 2026-06-22)

## 1. Problem

### 1.1 First-order defect: panel-registry gap

PR #72 introduced post-hoc grouping of lab Observations into FHIR `DiagnosticReport`
panel resources (CBC LOINC 58410-2, BMP 51990-0, etc.). To make the grouping fire
on the existing emission profile, `min_components` had to be calibrated downward —
CBC dropped from the canonical 4 to **2** and BMP from 8 to **3** — with the comment
"Hct often absent in the current physiology engine" and "Cl, Ca rare in current
engine".

Investigation while preparing this PR established that the comments are not the
actual reason. The full picture:

- `clinosim/modules/physiology/engine.py:312` **does** derive `Hct` (as `Hb × 3.0`).
- `clinosim/locale/{us,jp}/reference_range_lab.yaml` both already carry an `Hct`
  entry.
- BMP's `Na/K/HCO3/BUN/Creatinine/Glucose` are all derived (engine lines 252–342);
  only `Cl` and `Ca` are genuinely unimplemented.
- The real defect is in **`clinosim/modules/observation/reference_data/lab_panels.yaml`**:
  this is the registry that drives `lab_panel_components(name)` and thereby the
  panel-expansion loop at `clinosim/simulator/inpatient.py:572-585`. It currently
  contains **only the ABG entry**. Without entries for CBC and BMP,
  `lab_panel_components("CBC")` returns `[]` and the order is not expanded into
  child component orders. The scalar fallback then fails too (`canon = "CBC"` is
  not a key in `true_labs`), so the order is **silently dropped** — no
  `OrderResult`, no Observation, no audit trail.

Concretely, 9 orders across 4 protocols vanish today:

| Protocol | `{test: "CBC"}` sites | `{test: "BMP"}` sites |
|---|---|---|
| `cerebral_infarction.yaml` | line 126 (stat), 166 (daily_first_3_days) | — |
| `deep_vein_thrombosis.yaml` | line 127 (stat), 150 (daily) | — |
| `hemorrhagic_stroke.yaml` | line 129 (stat), 158 (daily) | — |
| `diabetic_ketoacidosis.yaml` | line 152 (stat) | line 139 (stat), 171 (q4-6h) |

For DVT, hemorrhagic stroke, and DKA-only-CBC the drop is total: the simulator
emits no CBC components at all unless a separate individual `{test: "Hb"}` or
`{test: "WBC"}` line is also present (cerebral_infarction is the only protocol
with a partial workaround at lines 139-140). DKA also loses its BMP entirely.

### 1.2 Second-order defect (surfaced during execution): RNG cascade + per-analyte specimen rejection

The original plan added the CBC/BMP entries to `lab_panels.yaml` as a YAML-only
change and asserted a tight "additions only" byte-diff invariant. The first
verification run (US p=2000, JP p=1000, seed=42, master @ `75f850b9` vs
branch @ Task-3 head) disproved that assumption:

```
US:  Patient.ndjson    master=1285 → branch=1287   (+2)
     Encounter.ndjson  master=8416 → branch=8481   (+65)
     Condition.ndjson  master=29850 → branch=30315 (+465)
     MedicationAdmin   master=35896 → branch=38743 (+2847)
JP:  Patient.ndjson    master=485 → branch=486    (+1)
     Encounter.ndjson  master=3242 → branch=3188  (-54  ← cohort divergence)
     Observation.ndjson master=77083 → branch=75862 (-1221)
59 byte-diff invariant failures total.
```

Patient counts shifted, JP Observation **decreased** despite adding new panels —
the master RNG stream was being polluted by the registry edit. Root cause: the
lab-resulting loop in `_run_daily_loop`:

```python
for order in all_orders:               # parent + panel_children all together
    canon = canonical_lab_name(order.display_name)
    if order.order_type.value == "lab" and order.status == OrderStatus.PLACED and canon in true_labs:
        if rng.random() < 0.02:                       # ← 1 draw per resulted lab order
            order.status = OrderStatus.CANCELLED; continue
        if canon in ("K", "LDH") and rng.random() < 0.03:  # ← +draw for K/LDH
            ...
```

Registering CBC adds 4 children per `{test: "CBC"}` order to `all_orders`. Each
child consumes `rng.random()` for specimen rejection (and possibly hemolysis,
staff assignment, result timing). The master patient-scoped stream thereby
advances further per day, and downstream clinical-course / mortality / readmission
branches see a different RNG state — re-cohorting unrelated patients. This is
the **same class of AD-16 violation** that the 2026-06-21 septic-shock perfusion
fix (memory `project_ehr_enrichment.md` PR #62) was rejected for: changing one
patient's path through the shared master stream shifts every later draw and
therefore every later patient.

That defect was always present for the existing ABG panel; it just never showed
up because ABG was registered on both master and branch, so the consumption
delta was zero. CBC/BMP exposed it.

The same code path carries a **second, separate** defect that the refactor
also resolves: specimen rejection is drawn **per analyte**, but in real
laboratories specimen rejection is **per specimen**. A panel order is one tube;
either the whole tube gets rejected and every analyte is lost, or the tube is
processed and every analyte produces a value. The pre-refactor model allowed an
ABG order where pH was "specimen rejected" while pCO2 from the same draw was
fine — clinically impossible.

This PR fixes both defects together, because Defect 1 cannot be merged without
fixing Defect 2 (cascade) and Defect 2's natural fix (per-specimen rejection)
also makes Defect 1 byte-diff clean.

## 2. Scope (PR1)

### 2.1 In scope

1. **`clinosim/modules/observation/reference_data/lab_panels.yaml`** — add CBC and
   BMP beside the existing ABG line:

   ```yaml
   ABG: [pH, pCO2, pO2, HCO3]
   CBC: [WBC, Hb, Hct, Plt]
   BMP: [Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]
   ```

   `Cl` and `Ca` are listed because they are canonical BMP components; the
   simulator silently drops them at the Pass 2 fallback below because
   `derive_lab_values` does not produce them (a known follow-up — see §6).
   The remaining six BMP components emit fine.

2. **`clinosim/modules/output/reference_data/lab_panel_groups.yaml`** — rewrite
   the inline `# Calibrated to clinosim emission ...` comments on the CBC and
   BMP panels to state the **real** reason `min_components` is depressed
   (pinned to PR1's emission profile pending a follow-up audit-driven raise).
   No threshold change.

3. **`clinosim/simulator/seeding.py`** — add a `panel_specimen_seed(parent_order_id)`
   helper alongside the existing `derive_sub_seed`. The helper returns a
   deterministic seed in `[0, 2**32)` derived from a salted SHA-256 of the
   parent order_id (which itself is derived deterministically from the master
   seed by the simulator, so the new RNG stream is reproducible without
   needing the master seed plumbed through to `_run_daily_loop`).

4. **`clinosim/simulator/inpatient.py`** — split the lab-resulting loop into
   two passes:

   - **Pass 1**: iterate `all_orders` and result every order whose
     `order_id` is **not** a panel child (`order.order_id not in
     _panel_child_ids`). Draws come from the patient-scoped master `rng`.
     Identical draw count to pre-refactor for every patient whose protocol
     does not touch a panel registry entry.
   - **Pass 2**: iterate `_panel_children_by_parent`. For each parent, build
     `sub_rng = np.random.default_rng(panel_specimen_seed(parent_order_id))`.
     Draw specimen rejection **once** for the parent (cancels all children
     if rejected). For each accepted child, draw `assign_staff`,
     `calculate_result_time_from_state`, hemolysis, and the noise/value
     generator all from `sub_rng`. Children whose `canon` is not in
     `true_labs` (e.g. BMP Cl/Ca pending a future engine extension) are
     silently skipped — `status` stays PLACED, `result` stays None,
     matching the existing scalar-fallback shape.

5. **Tests**:
   - Unit: `lab_panel_components("CBC"|"BMP")` returns the expected lists
     (Task 1); `panel_specimen_seed` is pinned to a literal value, is
     deterministic, key-sensitive, and isolated from the `derive_sub_seed`
     key space (Task 4).
   - Integration: cerebral_infarction `{test: "CBC"}` emits four canonical
     components; DKA `{test: "BMP"}` emits six and drops Cl/Ca; CBC/BMP
     panel parents are RESULTED with no scalar result; **per-specimen
     specimen rejection** invariant (all children of a parent share their
     CANCELLED/RESULTED fate); BMP Cl/Ca children stay PLACED (silent drop,
     not CANCELLED).
   - Byte-diff: see §4.

6. **e2e tests** — no golden file update required. clinosim's e2e suite
   asserts patient counts, structural invariants, reference-range presence,
   value ranges, and reproducibility (`len(r1.lab_results) == len(r2.lab_results)`
   compares two same-branch runs, not against a frozen baseline). It does not
   read panel-specific Observation values or counts. `pytest -m e2e -x`
   stays green without rebless.

### 2.2 Explicitly out of scope (deferred to PR2)

- **Removing the redundant `{test: "Hb"}` and `{test: "Plt"}` at
  `cerebral_infarction.yaml` lines 139-140.** Today those individual orders
  produce their own Observations *in addition to* the (now-emitting) CBC.
  Duplication of one analyte at the same minute is clinically meaningless.
  PR2 removes the redundancy; doing it in PR1 would shift the
  `enumerate(orders)` index for every order after line 140 and inflate the
  byte-diff envelope unnecessarily.
- **Raising `min_components` in `lab_panel_groups.yaml`.** PR1 is precisely
  the change that materially alters the emission profile that informs the
  right threshold. PR2 audits US+JP at p≥4000, counts actual component
  co-occurrence per panel per day, and picks `min_components` from data
  (anticipated CBC=3, BMP=6) rather than from a guess.
- **Daily-monitoring default labs** (`clinosim/modules/order/engine.py:266` —
  `["CRP", "WBC", "Creatinine"]`). Out of scope.
- **Adding `Cl` and `Ca` to `derive_lab_values`.** Tracked separately under
  the "missing analyte" backlog (Hct already done; Cl/Ca/PT/APTT/Urine_*
  remain).

## 3. Why this design — evaluated on the four axes

(`feedback_decision_axes` — data quality / clinical fidelity / module maintainability
& responsibility boundaries / conceptual fit)

| Option considered | Data | Clinical | Maintainability | Concept | Choice |
|---|---|---|---|---|---|
| A. Accept the cascade (no refactor) | ◎ | ◎ | △ | ✗ same pattern AKI/DKA rejected | not chosen |
| B. Partial sub-RNG for CBC/BMP only, ABG keeps master | ◎ | ◎ | △ inhomogeneous | △ split logic | not chosen |
| **C.** **All panel children share the Pass-2 sub-RNG model** | **◎** | **◎ per-specimen** | **◎ clear boundary** | **◎ AD-16 compliant** | **CHOSEN** |
| D. Rewrite disease YAMLs to enumerate analytes per protocol | ◎ | ✗ loses 1-order = 1-tube concept | ✗ DRY violation, hand-maintained | ✗ panel concept exists but unused | not chosen |
| E. Abandon CBC/BMP fix | ✗ | ✗ | ◯ | ✗ leave known defect | not chosen |

C wins all four axes. The "BNP-pattern surgical (formula only)" memory
guideline applies to realism calibration, **not** to structural defect fixes:
this PR fixes a per-analyte vs. per-specimen modelling bug that was always
clinically wrong, regardless of CBC/BMP. The fact that the refactor also
removes the cascade is a free consequence, not the motivation.

## 4. Correctness gate — what's checked, what's accepted

This PR is a **structural fix that necessarily moves the master patient-scoped
RNG stream**. A naïve "byte-identical on every non-lab NDJSON" invariant — the
shape used by the AKI/DKA calibration PR #69 — does not apply here, and trying
to force it back would mean keeping the per-analyte specimen-rejection bug
that this PR is designed to fix.

### 4.1 What necessarily shifts

ABG was already registered in `lab_panels.yaml` before this PR. Its child
orders were therefore already draining the patient-scoped master RNG for
specimen rejection, hemolysis, staff assignment, and result-time computation
on every existing patient and every existing day. Moving those draws onto
the per-parent sub-RNG in Pass 2 leaves the master stream lighter by a
patient-and-day-dependent number of draws, which propagates into:

- ABG Observation **values** (count and id preserved per parent).
- The clinical_course / mortality / complication branches downstream in
  `_run_daily_loop`, because they read from the same `rng`. Their
  branching points slip by ≤ a handful of `random()` calls per patient,
  which redistributes a small fraction of patients across the catchment
  population.

The 2026-06-23 byte-diff run at p=US 2000 / JP 1000 / seed=42 quantifies the
shift:

```
US:  Patient   1285 → 1293   (+8,  +0.6%)
     Encounter 8416 → 8398   (-18, -0.2%)
     Condition 29850 → 29897 (+47, +0.2%)
JP:  Patient   485 → 486     (+1,  +0.2%)
     Encounter 3242 → 3259   (+17, +0.5%)
```

This is consistent with "a small redistribution at the edge of the catchment,
no cohort-class disappears, no metric drifts >1%". It is **not** the
"runaway cohort divergence" the original v1 byte-diff revealed (where JP
Observation shrank by 1,221 lines because ABG and CBC were *both* drawing
from master and compounding).

### 4.2 What is the actual gate

A PR1-acceptance run must pass **all three** of:

1. **`pytest -x -q` green.** Unit + integration + e2e. The e2e suite is
   assertion-driven (patient counts in `ForcedScenario`, structural
   invariants, value ranges, reproducibility) — it pins the structural
   contract that downstream consumers rely on.
2. **byte-diff script run** with results recorded in
   `docs/reviews/2026-06-23-cbc-bmp-byte-diff.md`. The expectation is
   `Organization`, `Location` byte-identical (no rng influence on those);
   `Observation.ndjson`, `DiagnosticReport.ndjson`, `orders.csv`, and
   `lab_results.csv` strictly grow (additions plus the panel-children
   value shift); every other resource shifts within ≤ 1% line-count
   delta. The script labels everything outside the strict-grow set as
   FAIL for visibility, but the audit doc interprets each FAIL against
   the §4.1 threshold and records the verdict.
3. **Data-quality audit** in the same review doc:
   - Lab Observation `referenceRange` 100% present where it should be
     (numeric labs only; oxygen flow rate and 24h I/O excluded as
     designed).
   - Display ≠ code on all lab Observations (FHIR R5 anti-pattern).
   - No US Observation contains Japanese characters; no JP Observation
     contains a CM-granularity ICD code (per AD-30 invariants).
   - Per-disease admit-day labs sit in their clinically expected bands
     (e.g. DKA HCO3 ≤ 18, ACS Troponin_I ≥ 10× normal, sepsis Lactate
     median > 2.0). Pin against the matching numbers from PR #66's
     2026-06-22 data-quality audit.

### 4.3 Procedure

`scratchpad/cbc_bmp_byte_diff.py` runs master via a temp worktree, the branch
in the current tree, hashes every file, and prints PASS/FAIL against the
strict-grow boundary so cohort drift is visible in the log. Data-quality
audit is performed by reading the branch-side bundle directly with the
helpers in `scratchpad/` (per-LOINC counts, refRange coverage, sample
distribution); results go into `docs/reviews/2026-06-23-cbc-bmp-byte-diff.md`.

## 5. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| ABG Observation values shift in ways downstream e2e assertions catch | Low | Existing e2e assertions check ranges (`0 <= val`), counts (`len(patients) == 3`), reproducibility (`r1 == r2`), and structural invariants (LOINC in `coding.system`), not specific numeric outputs. Verified by `pytest -m e2e -x` after the refactor. |
| The `panel_specimen_seed` formula collides with a `derive_sub_seed` value and two RNG streams overlap | Very low | `tests/unit/test_seeding.py::TestPanelSpecimenSeed::test_isolated_from_derive_sub_seed` exhaustively checks four master seeds × three module offsets × three keys and asserts no collision. |
| BMP `min_components=3` misfires because Cl/Ca are dropped and the resulting 6 components are not present in some shorter encounters | Low | Six emitting components ≥ threshold; the only encounters where 3 won't be reached are ones where the BMP order itself was cancelled at the specimen-rejection step (≤2% per parent). |
| `lab_results.csv` row order changes break existing CSV-shape tests | Low | `csv_adapter.py:156` iterates `record["orders"]` in list order; PR1's children are `extend`-appended, so every pre-existing row keeps its position. |

## 6. PR2 (deferred follow-up — for the record)

PR2 will:

1. Generate US p≥4000 and JP p≥4000 on master, measure per-day
   component-count distribution per panel.
2. Set `min_components` in `lab_panel_groups.yaml` from the empirical
   distribution (target: 95th-percentile day captures a "real panel" as
   DR while a 1- or 2-component co-occurrence does not). Likely values:
   CBC=3, BMP=6, LFT/Lipid/Coag/UA unchanged.
3. Delete the redundant `{test: "Hb"}` and `{test: "Plt"}` at
   `cerebral_infarction.yaml:139-140`. Accept that this shifts the
   `enumerate` index for cerebral_infarction encounters and that lab
   Observations for those patients move.

The "missing analyte" backlog (Hct already done, Cl/Ca/PT/APTT/Urine_*)
is tracked separately as it is not panel-grouping work.

## 7. Open questions

None at design time. Resolved during execution:

- Hct emission path → fixed by registry add.
- BMP coverage of same defect → fixed by registry add.
- Whether to also raise `min_components` in PR1 → no; PR2 audits PR1's
  emission profile.
- Whether to remove cerebral_infarction redundancy in PR1 → no; PR2.
- Whether to keep the original "additions-only" byte-diff invariant →
  no; the byte-diff verification demonstrated that the lab-resulting
  loop's master-RNG draws on panel children cascade. The correct fix
  is the sub-RNG refactor; the new boundary is patient-cohort
  IDENTICAL plus per-specimen-isolated panel children DIFF-OK.

## 8. Acceptance checklist

- [ ] `lab_panels.yaml` contains CBC and BMP entries.
- [ ] `lab_panel_groups.yaml` calibration comments rewritten.
- [ ] `panel_specimen_seed` helper added to `simulator/seeding.py` and
      pinned in `tests/unit/test_seeding.py`.
- [ ] `_run_daily_loop` lab section is split into Pass 1 (master RNG,
      non-panel-child orders) and Pass 2 (panel children, per-parent
      `panel_specimen_seed` sub-RNG).
- [ ] Unit + integration tests cover registry expansion, per-specimen
      rejection, Cl/Ca silent drop, panel parent RESULTED.
- [ ] byte-diff script in `scratchpad/` run; cohort line-count drift on
      each FHIR resource and each CSV ≤ 1% (US p=2000, JP p=1000,
      seed=42). Strict-grow on `Observation.ndjson`,
      `DiagnosticReport.ndjson`, `orders.csv`, `lab_results.csv`. Results
      and interpretation recorded in
      `docs/reviews/2026-06-23-cbc-bmp-byte-diff.md`.
- [ ] Data-quality audit in the same review doc: lab refRange coverage,
      display ≠ code, no JP CM-granular ICD, per-disease admit-day labs
      in expected bands.
- [ ] `pytest -x -q` green (unit + integration + e2e).
- [ ] `ruff check` and `mypy` (strict) clean.
- [ ] PR description references this spec and PR #72 and links to the
      byte-diff audit doc.
