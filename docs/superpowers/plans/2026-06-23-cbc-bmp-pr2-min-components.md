# CBC / BMP PR2 — min_components Raise + Redundancy Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise `lab_panel_groups.yaml` min_components from PR1-pinned values (CBC=2, BMP=3) to canonical-N − 1 (CBC=3, BMP=5), validated by an audit script, and remove the now-redundant `{test:"Hb"}` / `{test:"Plt"}` orders at `cerebral_infarction.yaml` lines 139-140.

**Architecture:** One new audit script in `scratchpad/` to validate the rule against the post-PR1 emission profile (no value derivation — `spec §3.2`), one YAML edit each to `panel_groups.yaml` and `cerebral_infarction.yaml`, two integration tests, one byte-diff re-run using the existing PR1 script, one audit-trail markdown. No Python source changes. No physiology, RNG, CIF, or simulator changes.

**Tech Stack:** Python 3.11+, PyYAML, pytest. Reuses PR1's `scratchpad/cbc_bmp_byte_diff.py` (no change).

**Spec:** `docs/superpowers/specs/2026-06-23-cbc-bmp-pr2-min-components-design.md`

## Global Constraints

- **Branch:** `feat/cbc-bmp-pr2-min-components` (already created from master `28834f6a`).
- **No Python source changes.** Only YAML edits, new audit script (in `scratchpad/`, so not a clinosim package), new integration tests, and docs.
- **min_components decision rule:** "canonical N − 1" per spec §3.1. Audit (Task 1) **validates** the rule — it does not derive values.
- **Audit must support the chosen values.** If the empirical 95th-percentile day on a `{test:"CBC"}` panel order is < 3, or the same for `{test:"BMP"}` is < 5, **STOP and report** — the spec returns to brainstorming.
- **Byte-diff invariant** (spec §5): cohort drift ≤ 1% on every non-lab file; lab files shrink at the cerebral_infarction cohort by ~2 rows per cerebral_infarction patient (Hb/Plt deletion) and may shift due to enumerate-index re-numbering inside cerebral_infarction encounters.
- **e2e tests** stay green without golden updates (assertion-style suite; PR1 verified the same shape holds for structural lab changes).
- **Commits** end with `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` and `Claude-Session: <session-url>` trailers.

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `scratchpad/cbc_bmp_panel_audit.py` | Generate a single US p=4000 / JP p=4000 bundle on the current tree, walk `Observation.ndjson` and `orders.csv`, and report per-(encounter, day) component-count distributions per panel — split into "panel-order-was-placed" vs "post-hoc-coincidence-only" buckets. | **Create** |
| `clinosim/modules/output/reference_data/lab_panel_groups.yaml` | DR panel definitions (LOINC + components + min_components). | **Modify** — CBC `min_components: 2 → 3`, BMP `min_components: 3 → 5`, comments. |
| `clinosim/modules/disease/reference_data/cerebral_infarction.yaml` | Cerebral infarction protocol; admission orders list at lines 138-140 carries CBC + Hb + Plt. | **Modify** — delete lines 139-140 (`{test:"Hb"}`, `{test:"Plt"}`). |
| `tests/integration/test_panel_expansion_cbc_bmp.py` | Existing integration suite for the PR1 panel-expansion change. | **Modify** — append two new tests for PR2's deletions and DR composition regression guard. |
| `docs/reviews/2026-06-23-cbc-bmp-pr2-audit.md` | Audit trail: audit-script output, 95th-percentile interpretation, justification for CBC=3 / BMP=5, byte-diff result, verdict. | **Create** |

---

### Task 1: Write and run the audit script; validate canonical-N − 1

**Files:**
- Create: `scratchpad/cbc_bmp_panel_audit.py`

**Interfaces:**
- Consumes: nothing — driven via subprocess of `python -m clinosim.simulator.cli generate`.
- Produces: a `dict[panel_name, dict[component_count, freq]]` written to stdout. The plan asserts (95th-percentile when a panel order was placed) ≥ (canonical N − 1).

- [ ] **Step 1: Write the audit script**

Create `scratchpad/cbc_bmp_panel_audit.py`:

```python
"""PR2 audit: empirical per-panel per-day component-count distribution.

Validates (does not derive) the canonical-N − 1 rule for CBC and BMP
min_components in lab_panel_groups.yaml. Generates a US p=4000 / JP p=4000
bundle on the current tree, walks the resulting Observation.ndjson +
orders.csv, then reports the distribution split into two buckets per panel:

  (a) panel-order-was-placed   ← the bucket whose 95th-percentile must be
                                  ≥ canonical N − 1 for the rule to hold.
  (b) post-hoc-coincidence-only ← bucket grouped only because individual
                                  lab orders co-occurred on the same day
                                  without a {test: "CBC"} / {test: "BMP"}
                                  parent order.

If (a)'s 95th-percentile is below the planned threshold, the spec returns
to brainstorming.
"""
import collections
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# LOINC → canonical analyte. Verified against
# docs/reviews/2026-06-23-cbc-bmp-byte-diff.md (US-branch audit table) and
# clinosim/codes/data/loinc.yaml. The audit only cares about US bundles
# because JP uses JLAC10 codes, which require a parallel mapping that is
# unnecessary for the rule-validation we're doing (per-panel grouping
# semantics are identical across locales).
LOINC_TO_COMPONENT = {
    "6690-2": "WBC", "718-7": "Hb", "4544-3": "Hct", "777-3": "Plt",
    "2951-2": "Na", "2823-3": "K", "1963-8": "HCO3", "3094-0": "BUN",
    "2160-0": "Creatinine", "2345-7": "Glucose",
    # Cl (2075-0) and Ca (17861-6) don't emit until derive_lab_values adds them.
}

CBC_COMPONENTS = {"WBC", "Hb", "Hct", "Plt"}
BMP_COMPONENTS = {"Na", "K", "HCO3", "BUN", "Creatinine", "Glucose"}  # 6 emit-able


def run_simulator(cwd: Path, out_dir: Path, country: str, n: int, seed: int = 42) -> None:
    subprocess.run([
        sys.executable, "-m", "clinosim.simulator.cli",
        "generate", "--country", country, "-p", str(n), "-s", str(seed),
        "-o", str(out_dir), "--format", "fhir", "csv",
    ], check=True, cwd=cwd)


def load_lab_observations(fhir_dir: Path):
    """Yield (encounter_id, day, component) for every lab Observation."""
    with open(fhir_dir / "Observation.ndjson") as f:
        for line in f:
            o = json.loads(line)
            if not o.get("id", "").startswith("lab-"):
                continue
            loinc = o["code"]["coding"][0].get("code", "")
            comp = LOINC_TO_COMPONENT.get(loinc)
            if not comp:
                continue
            enc_ref = (o.get("encounter") or {}).get("reference", "")
            enc_id = enc_ref.split("/")[-1] if enc_ref else ""
            day = (o.get("effectiveDateTime") or "")[:10]
            if enc_id and len(day) == 10:
                yield (enc_id, day, comp)


def load_panel_orders(csv_dir: Path):
    """Return {(encounter_id, day): set of panel display_names}."""
    out: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    with open(csv_dir / "orders.csv") as f:
        for row in csv.DictReader(f):
            if row["display_name"] in {"CBC", "BMP"}:
                day = (row["ordered_datetime"] or "")[:10]
                if len(day) == 10:
                    out[(row["encounter_id"], day)].add(row["display_name"])
    return out


def bucket_distributions(fhir_dir: Path, csv_dir: Path):
    """Return per-panel {with_parent: Counter[N], coincidence: Counter[N]}."""
    panel_orders = load_panel_orders(csv_dir)

    # (enc, day) -> set of CBC components present, set of BMP components present
    cbc_buckets: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    bmp_buckets: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for enc, day, comp in load_lab_observations(fhir_dir):
        key = (enc, day)
        if comp in CBC_COMPONENTS:
            cbc_buckets[key].add(comp)
        if comp in BMP_COMPONENTS:
            bmp_buckets[key].add(comp)

    out = {
        "CBC": {"with_parent": collections.Counter(),
                "coincidence":   collections.Counter()},
        "BMP": {"with_parent": collections.Counter(),
                "coincidence":   collections.Counter()},
    }
    for key, comps in cbc_buckets.items():
        if not comps:
            continue
        b = "with_parent" if "CBC" in panel_orders.get(key, set()) else "coincidence"
        out["CBC"][b][len(comps)] += 1
    for key, comps in bmp_buckets.items():
        if not comps:
            continue
        b = "with_parent" if "BMP" in panel_orders.get(key, set()) else "coincidence"
        out["BMP"][b][len(comps)] += 1
    return out


def percentile(counter, p: float) -> int:
    """Approximate p-th percentile from a Counter[component_count]."""
    items = sorted(counter.items())
    total = sum(c for _, c in items)
    if total == 0:
        return 0
    cutoff = total * p / 100.0
    running = 0
    for n, c in items:
        running += c
        if running >= cutoff:
            return n
    return items[-1][0]


def report(dist) -> int:
    """Pretty-print + validate. Return 0 on success, 1 on rule failure."""
    failures = 0
    plan = {"CBC": 3, "BMP": 5}
    canonical = {"CBC": 4, "BMP": 6}
    for panel, buckets in dist.items():
        wp = buckets["with_parent"]
        co = buckets["coincidence"]
        print(f"\n=== {panel} ===")
        print(f"  components-present distribution (with panel order):")
        for n in sorted(wp):
            print(f"    {n} components: {wp[n]:5d}")
        print(f"  components-present distribution (coincidence only):")
        for n in sorted(co):
            print(f"    {n} components: {co[n]:5d}")
        p95_wp = percentile(wp, 5.0)  # 5th-percentile of "with-parent" = floor of typical real-panel size
        canonical_minus_one = canonical[panel] - 1
        chosen = plan[panel]
        verdict = "PASS" if p95_wp >= chosen else "FAIL"
        if verdict == "FAIL":
            failures += 1
        print(f"  5th-percentile (with panel order)   = {p95_wp}")
        print(f"  canonical N − 1 (proposed threshold) = {canonical_minus_one}")
        print(f"  Verdict: {verdict}  (chosen min_components = {chosen})")
    return failures


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="cbcbmp-pr2-audit-"))
    us = work / "us"
    jp = work / "jp"
    print("Generating US p=4000 / JP p=4000 on the current tree (seed=42)...")
    run_simulator(REPO, us, "US", 4000)
    run_simulator(REPO, jp, "JP", 4000)

    print("\n##### US #####")
    us_dist = bucket_distributions(us / "fhir_r4", us / "csv")
    us_failures = report(us_dist)

    # JP runs with JLAC10 codes (not in LOINC_TO_COMPONENT), so JP-side
    # validation is left to the byte-diff cohort-drift gate in Task 5.
    # The structural rule itself is locale-independent.

    print(f"\n=== SUMMARY ===  US failures: {us_failures}")
    print(f"Outputs kept at {work} for inspection.")
    if us_failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the audit script in the background**

The simulator generation is ~5-10 minutes per country at p=4000.

Run: `python scratchpad/cbc_bmp_panel_audit.py | tee /tmp/cbc_bmp_panel_audit.log`
Expected: completes with `failures: 0` and shows for each panel a 5th-percentile (`with-parent`) ≥ canonical N − 1.

What the 5th-percentile cell means: of every `(encounter, day)` bucket where a `{test:"CBC"}` parent order was placed, the bucket whose component count puts it at the 5th-percentile (i.e. the bucket size below which only 5% of buckets fall) — this is the conservative floor of "how many components does a real panel order typically produce". If that floor sits at or above the proposed threshold (N − 1), the threshold accepts essentially every real panel order. Below it, the threshold is rejecting clinically valid panels.

- [ ] **Step 3: Read the report**

If both panels PASS, proceed to Task 2.

If either fails: **stop** and report. The spec §3.2 prescribes that a failed audit returns the spec to brainstorming — do not lower the threshold in this plan; the threshold is the spec's chosen value, and the audit is the gate.

- [ ] **Step 4: Commit the script**

```bash
git add scratchpad/cbc_bmp_panel_audit.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
chore(scratchpad): audit script validating CBC/BMP min_components rule

Drives clinosim CLI to generate a US p=4000 / JP p=4000 bundle on the
current tree at seed=42, walks Observation.ndjson + orders.csv, and
reports per-(encounter, day) component-count distributions split into
two buckets per panel: "panel-order-placed" and
"coincidence-only". The audit validates (does not derive) the
canonical-N − 1 rule chosen in the spec; exits non-zero when the
5th-percentile of the panel-order-placed bucket falls below the
proposed threshold.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0127GWvxNrBL5GebQQFVJNqd
EOF
)"
```

---

### Task 2: Add integration tests for PR2's behavioral contract (TDD: tests fail first)

**Files:**
- Modify: `tests/integration/test_panel_expansion_cbc_bmp.py`

**Interfaces:**
- Consumes: `clinosim.simulator.run_forced`, `ForcedScenario`, `SimulatorConfig`, `OrderStatus` (all already imported by the existing file).

- [ ] **Step 1: Append the two new test functions**

Edit `tests/integration/test_panel_expansion_cbc_bmp.py` and append at the end:

```python
@pytest.mark.integration
def test_cerebral_infarction_individual_hb_plt_orders_removed():
    """PR2: cerebral_infarction.yaml lines 139-140 (individual {test: "Hb"}
    and {test: "Plt"} stat orders) are deleted. The CBC panel order at
    line 126 supplies both analytes via its panel children, so no
    individual Hb / Plt order should appear in any cerebral_infarction
    patient's record. (Panel-child orders are allowed — their order_id
    ends in "-Hb" or "-Plt".)"""
    scenario = ForcedScenario(
        disease_id="cerebral_infarction", count=5, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)
    for record in dataset.patients:
        for order in record.orders:
            if order.display_name in {"Hb", "Plt"}:
                comp = order.display_name
                assert order.order_id.endswith(f"-{comp}"), (
                    f"Found individual {comp} order {order.order_id} — "
                    f"PR2 deletes these from cerebral_infarction.yaml "
                    f"lines 139-140; only CBC panel children should "
                    f"emit {comp} in this protocol."
                )


@pytest.mark.integration
def test_cerebral_infarction_cbc_panel_still_emits_all_four_components():
    """Regression guard: after PR2 removes individual Hb / Plt, the CBC
    panel order at cerebral_infarction.yaml line 126 must still emit
    all four canonical components via its children. This protects
    against accidentally deleting too many lines in the YAML edit."""
    scenario = ForcedScenario(
        disease_id="cerebral_infarction", count=5, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)
    for record in dataset.patients:
        emitted = {
            o.result.lab_name
            for o in record.orders
            if o.result is not None and o.result.lab_name in CBC_COMPONENTS
        }
        assert CBC_COMPONENTS.issubset(emitted), (
            f"After PR2 cerebral_infarction must still emit "
            f"{CBC_COMPONENTS}; missing {CBC_COMPONENTS - emitted}."
        )
```

- [ ] **Step 2: Run the tests, verify the new ones fail**

Run: `pytest tests/integration/test_panel_expansion_cbc_bmp.py::test_cerebral_infarction_individual_hb_plt_orders_removed -v`
Expected: FAIL — the cerebral_infarction YAML still has lines 139-140, so individual `Hb` / `Plt` orders are present, the `order_id.endswith("-Hb")` assertion fails for at least one order.

Run: `pytest tests/integration/test_panel_expansion_cbc_bmp.py::test_cerebral_infarction_cbc_panel_still_emits_all_four_components -v`
Expected: **PASS** — CBC is unchanged in this task; this test exists to guard against accidentally over-editing the YAML in Task 3.

Both outcomes are correct. Continue to Task 3.

- [ ] **Step 3: Do NOT commit yet** — the failing test belongs with Task 3's YAML edit so the bisect history shows test-first then fix.

---

### Task 3: Delete `cerebral_infarction.yaml` lines 139-140 + commit

**Files:**
- Modify: `clinosim/modules/disease/reference_data/cerebral_infarction.yaml`
- Modify: `tests/integration/test_panel_expansion_cbc_bmp.py` (from Task 2; not yet committed)

**Interfaces:** none — pure YAML / commit step.

- [ ] **Step 1: Edit the YAML**

In `clinosim/modules/disease/reference_data/cerebral_infarction.yaml`, locate
`order_protocols.admission_orders.labs` and delete the two lines:

```yaml
      - {test: "Hb", urgency: "stat"}
      - {test: "Plt", urgency: "stat"}
```

These are at lines 139 and 140 in the file (pre-PR2). After deletion the
list goes:

```yaml
      - {test: "TSH", urgency: "routine", probability: 0.50}
      - {test: "AST", urgency: "stat", probability: 0.80}
```

i.e. `TSH` is followed directly by `AST` (was `TSH` → `Hb` → `Plt` → `AST`).

- [ ] **Step 2: Re-run the integration tests**

Run: `pytest tests/integration/test_panel_expansion_cbc_bmp.py -v`
Expected: all 7 tests PASS (5 pre-existing + 2 new).

- [ ] **Step 3: Run unit + integration suite for regressions**

Run: `pytest -m "unit or integration" -x -q`
Expected: green. ~510 tests baseline + 2 new = 512.

- [ ] **Step 4: Commit**

```bash
git add clinosim/modules/disease/reference_data/cerebral_infarction.yaml \
        tests/integration/test_panel_expansion_cbc_bmp.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
fix(cerebral_infarction): drop redundant Hb/Plt individual orders

Pre-PR1 the {test: "Hb"} and {test: "Plt"} individual stat orders at
admission kept cerebral_infarction's CBC DR alive when the panel
registry had no CBC entry. After PR #74 the CBC panel order at line
126 emits Hb and Plt via its children, so the individual orders
produced a duplicate at the same minute (one specimen → two
Observations per analyte). PR2 deletes them; the CBC panel order
continues to emit all four canonical components.

Verified by two new integration tests:
- No individual {Hb, Plt} order survives — only CBC panel children
  (order_id ending in -Hb / -Plt).
- CBC continues to emit {WBC, Hb, Hct, Plt} for every
  cerebral_infarction patient.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0127GWvxNrBL5GebQQFVJNqd
EOF
)"
```

---

### Task 4: Update `lab_panel_groups.yaml` min_components + comments + commit

**Files:**
- Modify: `clinosim/modules/output/reference_data/lab_panel_groups.yaml`

**Interfaces:** none — pure YAML / commit step. No source-code reads this file's comments.

- [ ] **Step 1: Edit the CBC and BMP blocks**

In `clinosim/modules/output/reference_data/lab_panel_groups.yaml` replace the
CBC block:

```yaml
  CBC:
    loinc: "58410-2"
    display: "Complete blood count (hemogram) panel - Blood by Automated count"
    components: [WBC, Hb, Hct, Plt]
    # canonical N − 1 rule: CBC has 4 canonical components; one specimen-
    # handling anomaly (an individual stat draw failing for an unrelated
    # reason) is tolerated. Validated by scratchpad/cbc_bmp_panel_audit.py
    # on master @ PR #74's head: the 5th-percentile bucket of "panel order
    # placed" was ≥ 3, so 3 accepts every real CBC.
    min_components: 3
```

and the BMP block:

```yaml
  BMP:
    loinc: "51990-0"
    display: "Basic metabolic 2000 panel - Serum or Plasma"
    components: [Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]
    # canonical N − 1 rule: BMP has 8 listed components but Cl and Ca
    # are silently dropped at Pass 2 because derive_lab_values does not
    # produce them yet, so the emit-able canonical N = 6 (Na, K, HCO3,
    # BUN, Creatinine, Glucose). 6 − 1 = 5. When Cl/Ca are added to the
    # physiology engine (separate backlog), an audit-driven PR can
    # raise this to 7.
    min_components: 5
```

- [ ] **Step 2: Diff-check that nothing else moved**

Run: `git diff clinosim/modules/output/reference_data/lab_panel_groups.yaml | head -60`
Expected: only the CBC and BMP comment blocks plus the `min_components` values differ. LFT, Lipid, Coag, UA, ABG sections untouched.

- [ ] **Step 3: Run unit + integration suite**

Run: `pytest -m "unit or integration" -x -q`
Expected: green. The integration test
`tests/integration/test_diagnostic_report_panels.py` (PR #72) — if it pins
specific CBC/BMP DR counts — may need its expectations to widen. Verify
which integration tests reference `lab_panel_groups.yaml`:

Run: `git grep -l 'lab_panel_groups\|min_components' tests/`
Expected: a short list. Inspect each for hard-coded thresholds; if any
asserts `min_components == 2` or counts CBC DRs at the pre-PR2 rate,
update its expected value or convert it to a structural assertion.

- [ ] **Step 4: Commit**

```bash
git add clinosim/modules/output/reference_data/lab_panel_groups.yaml
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(panel-groups): raise CBC/BMP min_components per canonical-N − 1 rule

CBC: 2 → 3 (canonical 4, one specimen-handling tolerance).
BMP: 3 → 5 (canonical 6 emit-able today, same tolerance).

Validated by scratchpad/cbc_bmp_panel_audit.py on master @ PR #74's
head: the 5th-percentile bucket of "panel-order-placed" days was
≥ N − 1 for both panels, so the new thresholds accept every real
panel order while suppressing 1- and 2-component accidental groupings
from individual lab orders in non-DKA encounters.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0127GWvxNrBL5GebQQFVJNqd
EOF
)"
```

---

### Task 5: Re-run byte-diff + write audit doc + commit

**Files:**
- Create: `docs/reviews/2026-06-23-cbc-bmp-pr2-audit.md`

**Interfaces:** none — runs the existing `scratchpad/cbc_bmp_byte_diff.py` and the new Task 1 script outputs.

- [ ] **Step 1: Re-run the byte-diff script (master vs branch)**

```bash
python scratchpad/cbc_bmp_byte_diff.py | tee /tmp/cbc_bmp_byte_diff_pr2.log
```

Wall-clock: ~15-20 minutes (PR1's measured runtime).

Expected: every non-lab cohort file ≤ 1% line-count drift; `Observation.ndjson`, `DiagnosticReport.ndjson`, `orders.csv`, `lab_results.csv` shift (the script will report them as `DIFF-OK` if branch ≥ master in line count). Note that PR2 introduces a *negative* delta on lab files for cerebral_infarction-cohort patients; the script's strict-grow check will flag this. The audit doc interprets the flag against the spec §5 deltas — a strict-grow FAIL on `Observation.ndjson` due to cerebral_infarction Hb/Plt deletion is the expected outcome.

- [ ] **Step 2: Write the audit doc**

Create `docs/reviews/2026-06-23-cbc-bmp-pr2-audit.md`:

```markdown
# CBC / BMP PR2 — Audit Trail

**Date:** 2026-06-23
**Branch:** `feat/cbc-bmp-pr2-min-components`
**Base:** master @ `28834f6a` (PR #74 merged)
**Spec:** `docs/superpowers/specs/2026-06-23-cbc-bmp-pr2-min-components-design.md`
**Audit script:** `scratchpad/cbc_bmp_panel_audit.py`
**Byte-diff script:** `scratchpad/cbc_bmp_byte_diff.py`

## 1. min_components rule validation

Audit run on master @ `28834f6a` (the post-PR1 emission profile), US
p=4000 seed=42:

(Paste the relevant CBC and BMP blocks from `/tmp/cbc_bmp_panel_audit.log`
showing the distributions and the PASS verdict for each panel.)

Interpretation: the 5th-percentile bucket of "panel-order-placed" days
sits at … for CBC and … for BMP, so the chosen min_components = 3 / 5
accept essentially every real panel order. The "coincidence-only"
buckets concentrate at … components, so the new thresholds correctly
suppress accidental groupings.

## 2. Byte-diff (PR2 branch vs master)

(Paste the US and JP per-file table from `/tmp/cbc_bmp_byte_diff_pr2.log`.)

Per-file interpretation:

- Patient / Encounter / Practitioner / Condition / Procedure / Med* /
  Immunization / FamilyMemberHistory / Allergy / Coverage / Specimen and
  every non-lab CSV: line-count drift ≤ 1% (PR1 boundary).
- `Observation.ndjson`: net delta on the cerebral_infarction cohort.
  Pre-PR2, every cerebral_infarction patient produced 2 extra lab
  Observations (the individual Hb and Plt stat orders). PR2 removes
  them; the CBC panel order continues to emit Hb and Plt via panel
  children, so each cerebral_infarction patient produces 2 fewer
  Observations net. The cerebral_infarction enumerate(orders) index
  shifts by −2 for every order at line 141+, so every cerebral_infarction
  lab Observation after the deletion site is re-numbered. The byte-diff
  script reports this as a strict-grow FAIL; it is in fact the
  expected outcome per spec §5.
- `DiagnosticReport.ndjson`: net delta from the threshold raise. CBC
  DRs from coincidence-only buckets in non-DKA protocols (BMP-derivable
  Na+K from individual orders that hit the old CBC=2 threshold) vanish;
  CBC DRs from real CBC orders are unchanged.

## 3. Verdict

(PASS / FAIL with the supporting evidence.)
```

Fill the bracketed sections from the actual logs.

- [ ] **Step 3: Commit**

```bash
git add docs/reviews/2026-06-23-cbc-bmp-pr2-audit.md
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
docs(review): CBC/BMP PR2 audit trail

Records the audit-script validation of the canonical-N − 1 rule and
the byte-diff result for PR2's panel_groups + cerebral_infarction
edits.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0127GWvxNrBL5GebQQFVJNqd
EOF
)"
```

---

### Task 6: Full pytest + ruff + push + PR

- [ ] **Step 1: Full test suite**

Run: `pytest -x -q`
Expected: all green (510 unit + integration + 39 e2e baseline + 2 new integration tests = 651 total).

If e2e runs longer than ~10 minutes per the PR1 measurement, set a 15-minute timeout.

- [ ] **Step 2: Lint check on PR-changed files**

```bash
git diff --name-only master HEAD | grep -E "\.py$" | xargs ruff check --output-format=concise 2>&1 | tail -20
```

Expected: zero new errors. The two new integration tests use the same patterns as the existing file. The audit script's imports follow PR1's `cbc_bmp_byte_diff.py` shape (stdlib only).

If any new diagnostics appear, fix them.

- [ ] **Step 3: Push the branch**

```bash
git push -u origin feat/cbc-bmp-pr2-min-components
```

- [ ] **Step 4: Open the PR**

```bash
gh pr create --title "feat(panel-groups): raise CBC/BMP min_components + drop cerebral_infarction Hb/Plt redundancy (PR2)" --body "$(cat <<'EOF'
## Summary

PR2 of the CBC/BMP sequence. Closes both follow-ups left by PR #74:

1. Raise `lab_panel_groups.yaml` min_components per canonical N − 1:
   CBC 2 → 3, BMP 3 → 5. Validated by a new audit script
   (`scratchpad/cbc_bmp_panel_audit.py`) showing the 5th-percentile
   bucket of "panel-order-placed" days sits at or above the new
   thresholds.
2. Delete the now-redundant individual `{test:"Hb"}` and
   `{test:"Plt"}` stat orders at `cerebral_infarction.yaml` lines
   139-140. After PR #74 the CBC panel order at line 126 emits both
   analytes via its children; the individual orders were producing
   a duplicate Observation at the same minute (one specimen → two
   Observations per analyte — clinically meaningless).

Spec: `docs/superpowers/specs/2026-06-23-cbc-bmp-pr2-min-components-design.md`
Audit: `docs/reviews/2026-06-23-cbc-bmp-pr2-audit.md`

## Changes

- `clinosim/modules/output/reference_data/lab_panel_groups.yaml`:
  CBC.min_components 2 → 3, BMP.min_components 3 → 5, comments
  rewritten to reflect the post-PR1 emission profile and the rule.
- `clinosim/modules/disease/reference_data/cerebral_infarction.yaml`:
  delete lines 139-140 (individual Hb / Plt stat orders).
- `tests/integration/test_panel_expansion_cbc_bmp.py`: two new tests
  pinning the deletion and the CBC-panel-still-emits-4-components
  regression guard.
- `scratchpad/cbc_bmp_panel_audit.py`: new audit script.
- `docs/reviews/2026-06-23-cbc-bmp-pr2-audit.md`: audit trail.

## Out of scope (PR3 backlog)

- Add Cl / Ca to `derive_lab_values` (will raise BMP canonical to 8 and
  enable a further min_components raise).
- PT / APTT / Urine_* engine extensions.

## Test plan

- [x] Audit script validates the rule on master @ PR #74's head.
- [x] Integration tests pin the cerebral_infarction Hb/Plt deletion
      and CBC composition regression guard.
- [x] Byte-diff vs master: cohort drift ≤ 1% on non-lab files; lab
      files shrink at the cerebral_infarction cohort by ~2 rows per
      patient as designed.
- [x] `pytest -x -q` green.
- [x] `ruff check` on PR-changed files clean.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_0127GWvxNrBL5GebQQFVJNqd
EOF
)"
```

- [ ] **Step 5: Report the PR URL**

`gh pr create` prints the URL; report it back.

---

## Self-review

**Spec coverage:**
- §2.1 panel_groups edit → Task 4.
- §2.1 cerebral_infarction edit → Task 3.
- §2.1 integration test additions → Tasks 2 and 3 (test-first / YAML-second).
- §2.1 audit script → Task 1.
- §2.1 audit doc → Task 5.
- §3 decision rule → encoded as the canonical-N − 1 values in Tasks 1 (validator) and 4 (YAML).
- §4 audit procedure → Task 1.
- §5 byte-diff invariant boundary → Task 5.
- §6 tests → Tasks 2 and 3.
- §7 risks: BMP=5 misfires → Task 1's audit gate. Cohort drift > 1% → Task 5's byte-diff. e2e regressions → Task 6 full suite.
- §10 acceptance checklist → covered.

**Placeholder scan:** the audit doc template at Task 5 has bracketed
`(Paste …)` and `(PASS / FAIL …)` cells — those are the implementer's
fill-in-from-log instructions, not abandoned placeholders. No `TBD` /
`TODO` / `similar to Task N`.

**Type consistency:** `LOINC_TO_COMPONENT`, `CBC_COMPONENTS`,
`BMP_COMPONENTS`, `bucket_distributions`, `percentile`, `report`,
`load_lab_observations`, `load_panel_orders`, `run_simulator` are
defined together in Task 1's single-file script and used only inside
that script. The integration tests in Tasks 2/3 reuse the module-level
`CBC_COMPONENTS` already defined in the file by PR #74's existing
tests (`{"WBC", "Hb", "Hct", "Plt"}` — same shape).
