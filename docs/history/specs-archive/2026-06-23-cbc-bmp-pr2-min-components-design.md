# CBC / BMP PR2 — Audit-Driven min_components Raise + cerebral_infarction Redundancy Removal

**Date**: 2026-06-23
**Status**: APPROVED (brainstorming complete, ready for plan)
**Sequence**: PR2 of the CBC/BMP panel sequence (PR1 = #74, lab_panels.yaml registry + panel-children sub-RNG refactor)
**Related**: PR #74 (2026-06-23), PR #72 (2026-06-22, DR panel grouping)

## 1. Problem

PR1 (#74) registered CBC and BMP in `lab_panels.yaml` and isolated panel-children
RNG into per-parent sub-streams. It deliberately left two follow-ups for PR2,
documented in PR1 spec §2.2:

1. **`min_components` is pinned to the pre-PR1 emission profile.** PR1 was
   precisely the change that materially altered the per-day panel-component
   distribution: CBC now emits 4 canonical components per panel order, BMP
   emits 6 (Cl/Ca silently dropped pending engine extension). The PR1
   thresholds CBC=2 / BMP=3 were calibrated for the **old** (post-hoc
   reconstruction) profile. With the new emission profile they let through
   accidental 2-component co-occurrences (e.g. BMP-derivable Na+K from
   individual orders in a non-DKA encounter forming a false-positive CBC DR).

2. **cerebral_infarction.yaml lines 139-140** carry `{test: "Hb"}` and
   `{test: "Plt"}` as individual stat orders alongside the `{test: "CBC"}`
   admission order. Pre-PR1 these were the workaround keeping CBC grouping
   alive in this protocol; post-PR1 the CBC panel itself emits Hb and Plt,
   so the individual orders now produce a duplicate at the same minute —
   1 panel order with 4 children plus 2 additional individual orders for
   2 of the same analytes = an Observation count for Hb and Plt that
   doubles in cerebral_infarction. Clinically meaningless (1 specimen, 1
   result per analyte).

This PR closes both follow-ups in a single edit because the right
`min_components` value depends on the new co-occurrence distribution, which
requires the redundancy be resolved first (the duplicated Hb / Plt rows
inflate the post-PR1 emission profile and would skew the audit).

## 2. Scope

### 2.1 In scope (3 files + tests + 1 audit script)

| File | Change |
|---|---|
| `clinosim/modules/output/reference_data/lab_panel_groups.yaml` | `CBC.min_components: 2 → 3`, `BMP.min_components: 3 → 5`, comments rewritten to reflect the post-PR1+PR2 emission profile and the "canonical N − 1" tolerance rule |
| `clinosim/modules/disease/reference_data/cerebral_infarction.yaml` | Delete `{test: "Hb", urgency: "stat"}` (line 139) and `{test: "Plt", urgency: "stat"}` (line 140) from `order_protocols.admission_orders.labs` |
| `tests/integration/test_panel_expansion_cbc_bmp.py` | Extend with two assertions: (1) cerebral_infarction `record.orders` contains no order with `display_name == "Hb"` or `"Plt"` that is **not** a CBC panel child (i.e. no individual stat order); (2) cerebral_infarction CBC DRs continue to carry all 4 components (regression guard) |
| `scratchpad/cbc_bmp_panel_audit.py` (new) | Read a generated bundle, count per-encounter per-day component co-occurrence per panel, print the 0–N component distribution; used to justify the chosen min_components values |
| `docs/reviews/2026-06-23-cbc-bmp-pr2-audit.md` (new) | Audit-trail markdown: empirical distribution, justification for CBC=3 / BMP=5, byte-diff result, PR2 verdict |

### 2.2 Out of scope (deferred or unrelated)

- **Adding Cl/Ca to `derive_lab_values`.** Tracked under the missing-analyte
  backlog; once they emit, a future PR can raise BMP to 6 or 7.
- **PT/APTT/Urine_* in the engine.** Same backlog.
- **Other protocols' redundancy.** Only cerebral_infarction has a CBC
  panel **plus** Hb/Plt individual orders. Other protocols either use CBC
  alone (DVT, hemorrhagic_stroke, DKA — fully resolved by PR1) or use
  individual WBC/Hb/Plt without a panel order (58 files; no duplication
  because there's no panel to compete with).

## 3. Decision rules

### 3.1 min_components rule — "canonical N − 1" (per the 4-axis evaluation)

The four-axis evaluation from `feedback_decision_axes` selected option A
(canonical N − 1) over 95-percentile auto-derivation and the strict canonical
maximum:

| Rule | Data | Clinical | Maintainability | Concept | Choice |
|---|---|---|---|---|---|
| A. canonical N − 1 | ◎ | ◎ panel order normally has every component | ◎ explicit rule, no magic number | ◎ faithful to panel concept | **CHOSEN** |
| B. 95-percentile from audit | ◎ | ◯ | △ value drifts every audit | ◯ | not chosen |
| C. canonical N (strict) | ◯ false-positive proof | △ specimen-rejection makes DR vanish | ◎ | ◯ overly strict | not chosen |

Concretely:

- **CBC** canonical components: `{WBC, Hb, Hct, Plt}` = 4. `min_components`
  = **4 − 1 = 3**. One analyte can drop (lost during specimen handling
  outside the per-specimen rejection model, e.g. an individual stat WBC
  failed to result for an unrelated reason) and the DR still fires.
- **BMP** canonical components currently emitted by the engine: `{Na, K,
  HCO3, BUN, Creatinine, Glucose}` = 6 (`Cl` and `Ca` are listed in
  `lab_panels.yaml` but silently dropped at Pass 2 because
  `derive_lab_values` does not produce them). `min_components` = **6 − 1
  = 5**. Same tolerance as CBC.

### 3.2 Audit purpose — validate, not derive

The audit (§4) does NOT set the values. It **validates** that the
canonical-N − 1 rule sits at a sensible point in the empirical distribution:
the 95th-percentile day on a {test: "CBC"} or {test: "BMP"} panel order
should contain ≥ N − 1 components. If the audit disagrees materially
(e.g. 95th-percentile is 2 for a CBC order, meaning per-specimen rejection
or some other engine bug is dropping more components than expected), the
spec is wrong and goes back to brainstorming.

## 4. Audit procedure

A new script `scratchpad/cbc_bmp_panel_audit.py`:

1. Generates US p=4000 and JP p=4000 at seed=42 against the current master
   tree (no master worktree needed — current branch's parent is master).
   Output written to a temp dir.
2. Walks `Observation.ndjson` and groups lab Observations by
   `(encounter_id, date(effectiveDateTime), panel_membership)`, where
   panel_membership is derived from the canonical-component lookup in
   `lab_panel_groups.yaml`.
3. For each panel and each (encounter, day) bucket, counts:
   - distinct CBC components present
   - distinct BMP components present
4. Reports the distribution per panel (0, 1, 2, …, N components present)
   and the 95th-percentile day.
5. Cross-references with `orders.csv` so we can separate
   "post-hoc-coincidence buckets" (no parent panel order) from
   "real panel buckets" (a parent panel order exists). Real-bucket
   distribution validates `min_components`; coincidence distribution
   validates that the chosen threshold suppresses false positives.

This script lives in `scratchpad/` and is committed (same pattern as
`cbc_bmp_byte_diff.py` from PR1).

## 5. Byte-diff invariant boundary

Same recipe as PR1 §4: cohort drift ≤ 1% on non-lab files, strict-grow
**or strict-shrink** on lab files (the cerebral_infarction Hb/Plt deletion
shrinks lab_results.csv, Observation.ndjson, and the lab portion of
orders.csv — additions plus deletions, not net additions).

| File | Expected delta vs master | Reason |
|---|---|---|
| `Patient.ndjson`, `Encounter.ndjson`, … (cohort files) | ≤ 1% line-count drift | enumerate(orders) index shifts in cerebral_infarction encounters re-cohort a few patients at the edge |
| `Observation.ndjson` | Net deletion of cerebral_infarction Hb / Plt individual rows (~ 2 × cerebral_infarction patient count); plus minor re-id of every cerebral_infarction lab Observation after line-138 in admission_orders (enumerate index shifts by −2) | The duplicate Observations vanish; CBC panel child Hb/Plt continue to emit |
| `DiagnosticReport.ndjson` | CBC DRs in cerebral_infarction keep their `dr-cbc-{enc}-{seq}` id and shed the two now-removed result[] entries (from {WBC, individual-Hb, Hct, individual-Plt} → {panel-WBC, panel-Hb, panel-Hct, panel-Plt} — same 4 entries, different obs refs). False-positive DRs in non-DKA protocols that previously hit the CBC=2 or BMP=3 thresholds are removed |
| `orders.csv` | −2 rows per cerebral_infarction encounter; otherwise stable | Hb / Plt individual stat orders deleted |
| `lab_results.csv` | −2 rows per cerebral_infarction encounter (one cancelled-but-resulted scenario is impossible for individual orders not actually ordered) | Same deletion |

`scratchpad/cbc_bmp_byte_diff.py` (PR1's script) is re-run unchanged; the
audit doc interprets the failure messages against the §5 expected deltas.

## 6. Tests

### 6.1 Integration test additions

`tests/integration/test_panel_expansion_cbc_bmp.py`:

```python
@pytest.mark.integration
def test_cerebral_infarction_hb_plt_individual_orders_removed():
    """PR2: cerebral_infarction.yaml lines 139-140 (individual Hb / Plt stat
    orders) are deleted. The CBC panel order at line 126 supplies both
    analytes via its panel children, so no individual {test: "Hb"} or
    {test: "Plt"} order should appear in a cerebral_infarction patient's
    record."""
    scenario = ForcedScenario(
        disease_id="cerebral_infarction", count=3, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)
    for record in dataset.patients:
        for order in record.orders:
            if order.display_name in {"Hb", "Plt"}:
                # Only acceptable Hb / Plt orders are panel children (order_id
                # ends in "-Hb" or "-Plt" and the prefix matches a CBC parent).
                assert "-" in order.order_id and (
                    order.order_id.endswith("-Hb") or order.order_id.endswith("-Plt")
                ), (
                    f"Found individual Hb/Plt order {order.order_id} "
                    f"({order.display_name}) — PR2 removed these from "
                    f"cerebral_infarction.yaml lines 139-140."
                )


@pytest.mark.integration
def test_cerebral_infarction_cbc_dr_still_has_all_four_components():
    """Regression guard: after PR2 the CBC DR in cerebral_infarction must
    still gather all four canonical components. The DR builder reads from
    Observations, so this verifies the CBC panel-children emission path
    is still intact after the redundancy removal."""
    # (Implementation in plan: load FHIR DR.ndjson from a tmp generation
    #  and assert each dr-cbc-* has result[] of length 4 with refs to
    #  Observations whose lab_name is in {WBC, Hb, Hct, Plt}.)
```

### 6.2 No unit-level change

`min_components` is data, not behaviour — the runtime grouping code in
`_fhir_diagnostic_report.py` reads from YAML. Existing unit tests still
pin the registry shape. e2e suite is assertion-style and survives the
threshold change.

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| BMP=5 misfires for cerebral_infarction and other protocols whose individual BMP-like orders rarely reach 5 components in the same day | Medium | Audit (§4) measures real BMP-component co-occurrence. If 5 turns out unreachable for protocols that should have BMP DRs (DKA aside, where the panel order itself emits 6), spec returns to brainstorming and we revisit. |
| Byte-diff cohort drift > 1% on non-lab files | Low | Same as PR1's accepted band. The change does not touch the lab-resulting RNG path; it only removes two orders from cerebral_infarction admission and changes one YAML threshold. |
| e2e regressions caused by Observation id re-numbering in cerebral_infarction | Low | e2e is assertion-style. Verified by `pytest -m e2e -x` after the change. |
| The redundancy removal also drops a clinically meaningful "second Hb / Plt draw" the protocol author intended | Very low | The two lines are stat orders at admission, not serial follow-up. cerebral_infarction.yaml's daily monitoring section (line 166) orders CBC again per day, which serves the serial-monitoring intent. |

## 8. PR3 (deferred follow-up)

PR3 will add `Cl` and `Ca` to `derive_lab_values`. With BMP canonical at
8 emit-able components, `min_components` can be raised to 6 or 7 by a
PR3.1 audit. The same backlog adds PT / APTT / Urine_* under separate
PRs because each needs its own physiology coupling and locale ranges.

## 9. Open questions

None at design time.

- min_components rule → A (canonical N − 1), confirmed by 4-axis evaluation.
- Audit population → US p=4000 / JP p=4000, single run, current master.
- cerebral_infarction edit scope → only lines 139-140, daily monitoring
  unchanged.
- Whether to update PR1's `lab_panel_groups.yaml` comments → yes (PR2's
  comment is the final wording; PR1's comment said "a follow-up
  audit-driven PR will measure …" which PR2 is).

## 10. Acceptance checklist

- [ ] `lab_panel_groups.yaml`: CBC.min_components = 3, BMP.min_components = 5,
      comments rewritten.
- [ ] `cerebral_infarction.yaml`: lines 139-140 removed.
- [ ] `scratchpad/cbc_bmp_panel_audit.py` created and run; output in
      `docs/reviews/2026-06-23-cbc-bmp-pr2-audit.md`.
- [ ] Audit's 95th-percentile per panel-order day ≥ N − 1 for both CBC
      (4 → 3) and BMP (6 → 5).
- [ ] Integration tests added: individual Hb/Plt absence + CBC DR
      composition.
- [ ] Byte-diff vs master: cohort drift ≤ 1% on non-lab files; lab files
      strict-grow or strict-shrink-on-cerebral_infarction as expected.
- [ ] `pytest -x -q` green.
- [ ] `ruff check` on PR-changed files clean.
- [ ] PR description references this spec, PR #74, and the audit doc.
