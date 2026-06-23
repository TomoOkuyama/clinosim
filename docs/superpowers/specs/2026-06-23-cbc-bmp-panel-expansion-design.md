# CBC / BMP Panel Expansion — Design

**Date**: 2026-06-23
**Status**: APPROVED (brainstorming complete, ready for plan)
**Sequence**: PR1 of a planned 2-PR sequence (PR2 = audit-driven `min_components` raise + redundancy removal)
**Related**: PR #72 (FHIR DiagnosticReport panel grouping, 2026-06-22)

## 1. Problem

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

The 5,324 CBC DiagnosticReports observed in the 2026-06-22 audit are therefore
post-hoc reconstructions from individual `{test: "WBC"}/"Hb"/"Plt"` orders in
**other** protocols (134 such individual orders across 58 files), not actual CBC
orders being resulted. This is the data-quality gap PR1 closes.

## 2. Scope (PR1)

Surgical: only the `lab_panels.yaml` registry plus a corrective comment update on
the `lab_panel_groups.yaml` calibration notes. No changes to physiology, no
changes to disease/encounter protocol YAML, no changes to `min_components`.
That keeps the byte-diff envelope tight (see §4) and lets PR2 set
`min_components` against measured emission.

### 2.1 In scope

1. **`clinosim/modules/observation/reference_data/lab_panels.yaml`** — add two
   entries beside the existing ABG line:

   ```yaml
   ABG: [pH, pCO2, pO2, HCO3]
   CBC: [WBC, Hb, Hct, Plt]
   BMP: [Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]
   ```

   `Cl` and `Ca` are listed because they are the canonical BMP components; the
   simulator will silently drop them at the scalar fallback because
   `derive_lab_values` does not produce them (a known follow-up — see §6). The
   remaining six BMP components emit fine.

2. **`clinosim/modules/output/reference_data/lab_panel_groups.yaml`** — rewrite
   the inline `# Calibrated to clinosim emission ...` comments on the CBC and
   BMP panels to state the **real** reason `min_components` is depressed: it is
   pinned to PR1's emission profile pending a PR2 audit. No code/threshold
   change here.

3. **Tests**:
   - Unit: `lab_panel_components("CBC")` returns `["WBC", "Hb", "Hct", "Plt"]`,
     `lab_panel_components("BMP")` returns 8 components.
   - Integration: a cerebral_infarction encounter with the existing
     `{test: "CBC", urgency: "stat"}` order at line 126 produces a panel-parent
     order in `RESULTED` state with no scalar result, plus four child orders
     whose `lab_results` carry `lab_name ∈ {WBC, Hb, Hct, Plt}`. A DKA encounter
     with `{test: "BMP", urgency: "stat"}` at line 139 produces six BMP children
     (the Cl/Ca pair is silently dropped, mirroring the existing behavior for
     any analyte not in `true_labs`).
   - Byte-diff invariant: see §4.

4. **e2e tests** — no golden file update is needed. clinosim's e2e suite
   (`tests/e2e/`) asserts on patient counts, structural invariants, value
   ranges, and reproducibility (`len(r1.lab_results) == len(r2.lab_results)`
   compares two same-branch runs, not against a frozen baseline), not on
   byte-equal NDJSON output. None of the existing assertions reads the
   Observation or DiagnosticReport count. Run `pytest -m e2e -x` and confirm
   it stays green.

### 2.2 Explicitly out of scope (deferred to PR2)

- **Removing the redundant `{test: "Hb"}` and `{test: "Plt"}` at
  `cerebral_infarction.yaml` lines 139-140.** Today those individual orders
  produce their own Observations *in addition to* the (currently dropped) CBC.
  Once PR1 lands, the CBC will also emit Hb and Plt — duplication of one analyte
  at the same minute is clinically meaningless (one order, one result). PR2
  removes the redundancy, but doing it in PR1 would shift the index of every
  order after line 140 in cerebral_infarction encounters by two, breaking the
  `lab-{enc}-{idx:04d}` id stability of every downstream Observation in those
  encounters (`_fhir_observations.py:406` indexes by `enumerate(orders)`).
  Deferring keeps PR1's byte-diff envelope at "additions only".

- **Raising `min_components` in `lab_panel_groups.yaml`.** PR1 is precisely the
  change that materially alters the emission profile that informs the right
  threshold. PR2 will audit US+JP at p≥4000, count actual component co-occurrence
  per panel per day, and pick `min_components` from data (anticipated: CBC 3,
  BMP 6) rather than from a guess.

- **Daily-monitoring default labs** (`clinosim/modules/order/engine.py:266` —
  `["CRP", "WBC", "Creatinine"]`). Switching the default to `["CBC", "BMP",
  "CRP"]` would broadcast the change across every protocol that does not
  override `daily_monitoring.labs`, which is unrelated and much larger than the
  defect being fixed.

- **Adding `Cl` and `Ca` to `derive_lab_values`.** Tracked separately as part of
  the "missing analyte" backlog (Hct/Cl/Ca/PT/APTT/Urine_*); each requires its
  own physiology coupling and locale reference ranges, and each is a candidate
  PR on its own.

## 3. Why this is safe (the BNP-pattern surgical recipe applied)

PR #69 (AKI/DKA calibration) established the working pattern: change as little
as possible, no state mutation, gate on byte-diff invariant. PR1 fits that
shape exactly:

- **No physiology change.** `derive_lab_values` is untouched; the simulator's
  state evolution is bit-identical to master.
- **No RNG change.** The panel-expansion loop already exists for ABG and uses
  no random draws (`inpatient.py:572-585` is a deterministic list extension).
- **No id collisions.** Existing orders' `enumerate` index is preserved because
  `all_orders.extend(_panel_children)` (line 585) appends; the new children take
  the next index slots. Every existing Observation `lab-{enc}-{idx:04d}` id is
  byte-identical to master.
- **No CIF schema change.** Existing CIF types accept any analyte name in
  `OrderResult.lab_name`; the new components flow through the existing schema.

The only behavioral change is that 9 previously-dropped orders now produce
6–8 component child orders each (4 for CBC, 6 for BMP after dropping Cl/Ca)
and emit corresponding Observations and DiagnosticReports.

## 4. Byte-diff invariant (the PR's correctness gate)

Generate US p=2000 and JP p=1000 with seed=42 on master and on the branch.
Diff every NDJSON in the output bundle. The acceptance criterion is:

**IDENTICAL on both populations**:
- `Patient.ndjson`
- `Encounter.ndjson`
- `Practitioner.ndjson`
- `Organization.ndjson`
- `Location.ndjson`
- `Condition.ndjson`
- `Procedure.ndjson`
- `MedicationRequest.ndjson`
- `MedicationAdministration.ndjson`
- `Immunization.ndjson`
- `FamilyMemberHistory.ndjson`
- All vital-sign, nursing, smoking/alcohol/care-level/code-status,
  microbiology-DR, and occupation Observations
- All existing `lab-{enc}-{idx:04d}` Observations whose `idx` corresponds to
  an order that already existed pre-branch

**Permitted to differ**:
- `Observation.ndjson`: net additions for the new CBC/BMP child results in
  the four protocols listed in §1 (no existing Observation id is reused,
  modified, or removed — additions only).
- `DiagnosticReport.ndjson`: net additions for new CBC DRs in DVT and
  hemorrhagic stroke (which had none today) and new BMP DRs in DKA. **In
  cerebral_infarction the existing CBC DRs keep their ids but their
  `result[]` array grows** from `[Hb, Plt]` (the partial grouping the
  individual line-139-140 orders made today) to roughly
  `[panel_child_WBC, individual_Hb, panel_child_Hct, individual_Plt]` —
  same `dr-cbc-{enc}-{seq}` resource, longer result list. Microbiology DRs
  and panel groupings in protocols not in §1's list are byte-identical.
- `orders.csv`: net additions for the new panel-child orders, **plus a
  status change on the parent `{test: "CBC"}`/`{test: "BMP"}` orders**
  from `PLACED` to `RESULTED` (`inpatient.py:584`). Existing rows otherwise
  unchanged. The BMP children for `Cl` and `Ca` stay `PLACED` (the scalar
  fallback finds them absent from `true_labs` and skips them); this is the
  same shape as any existing individual `{test: "Cl"}` order that the
  current engine cannot result, so the CSV row pattern is not a new one.
- `lab_results.csv`: net additions only for the components actually resulted
  (CBC ×4, BMP ×6 — Cl/Ca yield no row).

Procedure: a small Python script in `scratchpad/` that runs master and branch
in parallel, hashes each NDJSON and CSV, and prints PASS/FAIL per file
against the criteria above. Results saved into
`docs/reviews/2026-06-23-cbc-bmp-byte-diff.md` for the audit trail.

## 5. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `lab_results.csv` row order changes break existing CSV-shape tests | Low | `csv_adapter.py:156` iterates `record["orders"]` in list order; PR1's children are `extend`-appended to the parent list, so every pre-existing row keeps its position and only new rows append at the tail. Verified by `pytest tests/integration/test_csv_adapter.py` after the change. |
| BMP `min_components=3` accidentally still misfires because Cl/Ca are dropped and the resulting 6 components are not present in some shorter encounters | Low | The existing BMP threshold (3) is already calibrated to match the prior emission of individual `Na/K/Creatinine/Glucose/BUN` lines, and PR1's new BMP emission is a strict superset of those (drops nothing that emitted before, adds HCO3). |
| e2e golden update masks an unintended regression | Medium | The golden update step diffs against master first (§4) and only re-blesses Observation/DR/CSV. A reviewer sees both diffs in the PR. |
| New CBC orders in DVT exceed clinical realism (CBC is genuinely q1d for DVT, but `daily_first_3_days` was a workaround for the drop) | Low | The protocol YAML is unchanged — frequencies stay as authored. Realism follows the existing protocol. |

## 6. PR2 (deferred follow-up — for the record)

PR2 will:

1. Generate US p≥4000 and JP p≥4000 on PR1's branch, measure per-day
   component-count distribution per panel.
2. Set `min_components` in `lab_panel_groups.yaml` from the empirical
   distribution (target: 95th-percentile day captures a "real panel" as DR
   while a 1- or 2-component co-occurrence does not). Likely values: CBC=3,
   BMP=6, LFT/Lipid/Coag/UA unchanged.
3. Delete the redundant `{test: "Hb"}` and `{test: "Plt"}` at
   `cerebral_infarction.yaml:139-140`. Accept that this shifts the
   `enumerate` index for cerebral_infarction encounters; rebless e2e golden
   accordingly.

The "missing analyte" backlog (Hct already done, Cl/Ca/PT/APTT/Urine_*) is
tracked separately as it is not panel-grouping work.

## 7. Open questions

None at design time. All resolved during brainstorming:

- Hct emission path → confirmed dropped at `lab_panels.yaml`, not at engine.
- BMP coverage of same defect → confirmed (2 DKA sites, same shape).
- Whether to also raise `min_components` in PR1 → no; it requires data PR1
  produces.
- Whether to remove cerebral_infarction redundancy in PR1 → no; it shifts
  `enumerate` indices and inflates the byte-diff envelope.

## 8. Acceptance checklist

- [ ] `lab_panels.yaml` contains CBC and BMP entries with the components listed
      in §2.1.
- [ ] `lab_panel_groups.yaml` calibration comments rewritten to describe the
      real reason `min_components` is depressed.
- [ ] Unit tests for `lab_panel_components("CBC")` and `lab_panel_components("BMP")`.
- [ ] Integration tests covering cerebral_infarction CBC expansion and DKA BMP
      expansion.
- [ ] Byte-diff invariant script in `scratchpad/`, results recorded in
      `docs/reviews/2026-06-23-cbc-bmp-byte-diff.md`.
- [ ] `pytest -m e2e -x` green without golden updates; PR description
      includes the byte-diff summary (NDJSON sizes before/after, new
      resource counts per type, confirmation that non-Observation NDJSONs
      are byte-identical).
- [ ] `pytest -x` green (unit, integration, e2e).
- [ ] PR description references this spec and PR #72.
