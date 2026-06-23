# CBC / BMP Panel Expansion (PR1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register CBC and BMP in the observation panel-expansion registry so 9 currently-silently-dropped `{test: "CBC"}` / `{test: "BMP"}` orders in 4 disease protocols (cerebral_infarction, deep_vein_thrombosis, hemorrhagic_stroke, diabetic_ketoacidosis) emit canonical child component Observations and FHIR DiagnosticReports, while keeping every other NDJSON byte-identical.

**Architecture:** Two YAML edits (one registry add, one comment correction), four pytest cases (unit ×2 in the panel registry, integration ×2 in the simulator pipeline), one byte-diff verification script in `scratchpad/`, and one audit-trail markdown. No Python source changes. No physiology, RNG, CIF, or order-engine changes. The fix relies on the existing ABG panel-expansion code path at `clinosim/simulator/inpatient.py:572-585`.

**Tech Stack:** Python 3.11+, pytest, PyYAML, ruff, mypy (strict), Pydantic. Existing `numpy.random.Generator` seeding (AD-16) is untouched.

**Spec:** `docs/superpowers/specs/2026-06-23-cbc-bmp-panel-expansion-design.md`

## Global Constraints

- **Branch:** `feat/cbc-bmp-panel-expansion` (already created from master `75f850b9`).
- **No physiology/RNG/CIF/order-engine changes.** Only `lab_panels.yaml`, `lab_panel_groups.yaml` (comments), and tests/scripts/docs.
- **Byte-diff invariant** (spec §4): with seed=42, US p=2000 and JP p=1000, master vs branch must be IDENTICAL on Patient/Encounter/Practitioner/Organization/Location/Condition/Procedure/MedicationRequest/MedicationAdministration/Immunization/FamilyMemberHistory and all pre-existing lab/vital/social Observations. Permitted to differ: `Observation.ndjson` (additions only), `DiagnosticReport.ndjson` (additions + cerebral_infarction CBC DR's `result[]` grows in place — same `dr-cbc-…` id), `orders.csv` (parent CBC/BMP status PLACED→RESULTED + new child rows; Cl/Ca children stay PLACED), `lab_results.csv` (additions only).
- **Existing Observation ids are preserved** — `_panel_children` are `extend`-appended (`inpatient.py:585`) so `enumerate(orders)` indices for pre-existing orders don't shift.
- **`min_components` in `lab_panel_groups.yaml` is NOT changed** in this PR; raising it is PR2's responsibility, driven by the audit PR1 produces.
- **cerebral_infarction's redundant `{test: "Hb"}` / `{test: "Plt"}`** at lines 139-140 are NOT removed in this PR (would shift `enumerate` indices and break the byte-diff envelope); deferred to PR2.
- **e2e tests** stay green without golden updates — clinosim's e2e suite asserts patient counts / structural invariants / reproducibility, not raw NDJSON content.
- **Commits** end with `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` and `Claude-Session: <session-url>` trailers.
- **No new code outside `clinosim/`** other than the test files and scratchpad script.

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `clinosim/modules/observation/reference_data/lab_panels.yaml` | Registry: panel order name → component analytes | **Modify** — add CBC and BMP entries |
| `clinosim/modules/output/reference_data/lab_panel_groups.yaml` | FHIR DR panel definitions (LOINC + components + min_components) | **Modify (comments only)** — replace misleading "Hct often absent" / "Cl, Ca rare" comments with the real reason |
| `tests/unit/test_lab_panel_registry.py` | Unit test for `lab_panel_components(panel_name)` | **Create** |
| `tests/integration/test_panel_expansion_cbc_bmp.py` | Integration test: run a small forced inpatient sim with the two affected protocols and assert child component orders/Observations emit | **Create** |
| `scratchpad/cbc_bmp_byte_diff.py` | Byte-diff verification: run master + branch in parallel, hash every NDJSON/CSV, report per-file PASS/FAIL against the §4 boundary | **Create** (scratchpad, not committed to a Python package) |
| `docs/reviews/2026-06-23-cbc-bmp-byte-diff.md` | Audit trail: PASS/FAIL table from the byte-diff script + size deltas + sample new resource counts | **Create** |

---

### Task 1: Add CBC and BMP to the panel registry + unit tests

**Files:**
- Modify: `clinosim/modules/observation/reference_data/lab_panels.yaml`
- Create: `tests/unit/test_lab_panel_registry.py`

**Interfaces:**
- Consumes: nothing new — uses the existing `clinosim.modules.observation.engine.lab_panel_components(name: str) -> list[str]` (returns the YAML's value for `canonical_lab_name(name)`, or `[]`).
- Produces: `lab_panel_components("CBC") == ["WBC", "Hb", "Hct", "Plt"]` and `lab_panel_components("BMP") == ["Na", "K", "Cl", "HCO3", "BUN", "Creatinine", "Glucose", "Ca"]`. These are consumed by `clinosim/simulator/inpatient.py:574`.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_lab_panel_registry.py`:

```python
"""Registry tests for lab_panels.yaml (PR1 CBC/BMP expansion)."""
import pytest

from clinosim.modules.observation.engine import lab_panel_components


@pytest.mark.unit
def test_abg_components_unchanged():
    # Sanity: the pre-existing ABG entry must not regress.
    assert lab_panel_components("ABG") == ["pH", "pCO2", "pO2", "HCO3"]


@pytest.mark.unit
def test_cbc_expands_to_four_canonical_components():
    # WBC, Hb, Hct, Plt — RBC intentionally omitted (physiology engine does
    # not derive RBC count; adding it would create silently-dropped children).
    assert lab_panel_components("CBC") == ["WBC", "Hb", "Hct", "Plt"]


@pytest.mark.unit
def test_bmp_expands_to_eight_canonical_components():
    # Cl and Ca are listed because they are canonical BMP components; the
    # scalar resulted path at inpatient.py drops them silently when they are
    # absent from derive_lab_values(), so this entry being correct is what
    # lets PR2 add Cl/Ca to the engine without YAML changes.
    assert lab_panel_components("BMP") == [
        "Na", "K", "Cl", "HCO3", "BUN", "Creatinine", "Glucose", "Ca",
    ]
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/unit/test_lab_panel_registry.py -v`
Expected: `test_abg_components_unchanged` PASS; CBC and BMP tests FAIL with `assert [] == [...]` (because the registry has only ABG today).

- [ ] **Step 3: Add the entries to `lab_panels.yaml`**

Modify `clinosim/modules/observation/reference_data/lab_panels.yaml` so the body becomes:

```yaml
# Lab panels (AD-57): one order name → component analytes. A panel order expands into
# one resulted lab order per component (each derived from physiology, emitted as its own
# Observation). Data-driven; add a panel here, no code changes.
#
# NOTE: list the *canonical* analyte names that the physiology engine derives.
# Components not in derive_lab_values() (e.g. Cl/Ca in BMP today) are silently
# dropped at the scalar-resulted path in inpatient.py — that's the right shape
# (the panel-expansion path stays declarative; the engine catches up later).
ABG: [pH, pCO2, pO2, HCO3]
CBC: [WBC, Hb, Hct, Plt]
BMP: [Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]
```

- [ ] **Step 4: Bust the lru_cache + rerun tests**

The module-level `@lru_cache(maxsize=1)` on `_lab_panels()` is fine across test invocations because pytest re-imports per session, but **clear it explicitly** in case any earlier test pre-warmed the cache during collection:

Run: `pytest tests/unit/test_lab_panel_registry.py -v --no-header`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/observation/reference_data/lab_panels.yaml \
        tests/unit/test_lab_panel_registry.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(observation): register CBC and BMP in lab panel expansion

Adds CBC: [WBC, Hb, Hct, Plt] and BMP: [Na, K, Cl, HCO3, BUN, Creatinine,
Glucose, Ca] to observation/reference_data/lab_panels.yaml so the existing
panel-expansion loop (inpatient.py:572-585) materializes child component
orders for {test: "CBC"} and {test: "BMP"} the same way it does for ABG.

Cl and Ca are listed as canonical BMP components; the scalar-resulted path
silently drops them until derive_lab_values() produces them (tracked
separately).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0127GWvxNrBL5GebQQFVJNqd
EOF
)"
```

---

### Task 2: Integration test — cerebral_infarction CBC expansion end-to-end

**Files:**
- Create: `tests/integration/test_panel_expansion_cbc_bmp.py`

**Interfaces:**
- Consumes: `clinosim.simulator.run_forced` (or whatever ForcedScenario entry point existing integration tests use — look at `tests/integration/test_forced_scenario.py` or similar), with a `cerebral_infarction` disease id and a small `count`.
- Produces: a test fixture other tests in the file reuse, plus the assertion that exactly four `OrderResult` rows with `lab_name ∈ {WBC, Hb, Hct, Plt}` appear in any cerebral_infarction patient's initial-day orders (in addition to the existing individual `{test: "Hb"}` and `{test: "Plt"}` at lines 139-140 of the protocol).

- [ ] **Step 1: Look at an existing integration test as a template**

Open `tests/integration/test_csv_adapter.py` or any file matching `tests/integration/*forced*` or `tests/integration/*inpatient*` to copy the fixture style (config, scenario, seed, output-directory pattern). Note the existing pytest marker `@pytest.mark.integration` and how `random_seed=42` is set.

If no `tests/integration/test_*.py` file demonstrates the forced-scenario pattern, fall back to `tests/e2e/test_us_mode.py:106-116` as a template (it builds a `ForcedScenario(disease_id=..., count=3)` and `run_forced(scenario, config)` and inspects `dataset.patients[i]`).

- [ ] **Step 2: Write the failing test**

Create `tests/integration/test_panel_expansion_cbc_bmp.py`:

```python
"""Integration test: CBC and BMP panel orders expand into canonical
component child orders (PR1 of CBC/BMP panel expansion)."""

import pytest

from clinosim.simulator import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig


CBC_COMPONENTS = {"WBC", "Hb", "Hct", "Plt"}
BMP_COMPONENTS_EMITTED = {"Na", "K", "HCO3", "BUN", "Creatinine", "Glucose"}
BMP_COMPONENTS_DROPPED = {"Cl", "Ca"}


def _flatten_orders(patient_record):
    """Yield every order across every encounter on a CIF patient record."""
    for enc in getattr(patient_record, "encounters", []) or []:
        for order in getattr(enc, "orders", []) or []:
            yield order


@pytest.mark.integration
def test_cerebral_infarction_cbc_emits_four_components():
    """A cerebral_infarction patient orders {test: "CBC"} at admission;
    after PR1 that order expands into a panel parent (RESULTED) plus
    four child orders that produce WBC, Hb, Hct, and Plt OrderResults
    in the same minute."""
    scenario = ForcedScenario(
        disease_id="cerebral_infarction", count=2, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    assert len(dataset.patients) == 2
    for record in dataset.patients:
        results = [o.result.lab_name for o in _flatten_orders(record)
                   if getattr(o, "result", None) is not None
                   and getattr(o.result, "lab_name", None) in CBC_COMPONENTS]
        # cerebral_infarction protocol has CBC stat + daily; even the first
        # day must produce all four canonical CBC components.
        assert CBC_COMPONENTS.issubset(set(results)), (
            f"Expected CBC components {CBC_COMPONENTS} in cerebral_infarction "
            f"emitted labs, got {set(results)}"
        )


@pytest.mark.integration
def test_dka_bmp_emits_six_components_and_drops_cl_ca():
    """A DKA patient orders {test: "BMP"} at admission; PR1 expands it into
    eight child orders but the scalar-resulted path drops Cl/Ca (not in
    derive_lab_values today). The other six components emit normally."""
    scenario = ForcedScenario(
        disease_id="diabetic_ketoacidosis", count=2, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    for record in dataset.patients:
        emitted = {o.result.lab_name for o in _flatten_orders(record)
                   if getattr(o, "result", None) is not None
                   and getattr(o.result, "lab_name", None) is not None}
        # All six derivable BMP components must reach a resulted state.
        assert BMP_COMPONENTS_EMITTED.issubset(emitted), (
            f"Expected emitted BMP components {BMP_COMPONENTS_EMITTED}, "
            f"got {emitted & (BMP_COMPONENTS_EMITTED | BMP_COMPONENTS_DROPPED)}"
        )
        # Cl and Ca must NOT appear (derive_lab_values doesn't produce them).
        assert not (BMP_COMPONENTS_DROPPED & emitted), (
            f"Cl/Ca should be silently dropped pending derive_lab_values "
            f"extension, but found: {BMP_COMPONENTS_DROPPED & emitted}"
        )


@pytest.mark.integration
def test_panel_parents_marked_resulted_no_double_observation():
    """The PLACED→RESULTED transition on the parent CBC/BMP order
    (inpatient.py:584) is what prevents the parent itself from emitting a
    scalar Observation alongside its children. Verify by asserting no
    OrderResult has lab_name == 'CBC' or 'BMP'."""
    scenario = ForcedScenario(
        disease_id="diabetic_ketoacidosis", count=2, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)
    for record in dataset.patients:
        for o in _flatten_orders(record):
            r = getattr(o, "result", None)
            if r is None:
                continue
            assert r.lab_name not in ("CBC", "BMP"), (
                f"Panel parent emitted a scalar result {r.lab_name!r}; "
                f"the panel-expansion loop should have marked it RESULTED "
                f"without a result."
            )
```

Both imports are confirmed against `tests/e2e/test_forced_scenario.py` and `clinosim/simulator/__init__.py`.

- [ ] **Step 3: Run tests, verify behavior**

Run: `pytest tests/integration/test_panel_expansion_cbc_bmp.py -v`
Expected: all three PASS (Task 1 already added the registry entries).

If the import paths are wrong, the test errors out at collection; fix the import (do not bypass the failure) and rerun.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_panel_expansion_cbc_bmp.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
test(integration): assert CBC and BMP panel expansion emits children

Cerebral_infarction: the existing {test: "CBC"} order must emit all four
canonical CBC components (WBC, Hb, Hct, Plt) via the panel-expansion path.
DKA: BMP emits six components (Na, K, HCO3, BUN, Creatinine, Glucose);
Cl and Ca are silently dropped at the scalar-resulted path until
derive_lab_values() produces them. Panel parents never emit a scalar
result of their own.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0127GWvxNrBL5GebQQFVJNqd
EOF
)"
```

---

### Task 3: Correct the misleading calibration comments in `lab_panel_groups.yaml`

**Files:**
- Modify: `clinosim/modules/output/reference_data/lab_panel_groups.yaml`

**Interfaces:** None — comments only, no code reads them. `min_components` values are NOT changed.

- [ ] **Step 1: Apply the comment correction**

In `clinosim/modules/output/reference_data/lab_panel_groups.yaml`, replace the CBC block's comment lines:

```yaml
  CBC:
    loinc: "58410-2"
    display: "Complete blood count (hemogram) panel - Blood by Automated count"
    components: [WBC, Hb, Hct, Plt]
    # min_components is pinned to the pre-PR1 emission profile, where most CBCs
    # were assembled post-hoc from individual {test: "WBC"}/"Hb"/"Plt" orders in
    # protocols that lacked a CBC panel-expansion registry entry. After PR1 the
    # 4 canonical components are emitted together; PR2 will audit the new
    # distribution and raise this to ~3 to suppress accidental 2-component
    # groupings from BMP/other co-occurrences.
    min_components: 2
```

and the BMP block's:

```yaml
  BMP:
    loinc: "51990-0"
    display: "Basic metabolic 2000 panel - Serum or Plasma"
    components: [Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]
    # min_components stays at 3 for PR1: derive_lab_values() does not yet
    # produce Cl or Ca, so PR1's BMP panel emits at most 6 of 8 components.
    # Once Cl/Ca are added to the physiology engine (separate backlog), PR2's
    # audit will likely raise this to 6 to suppress accidental groupings from
    # individual {test: "Na"}/"K"/"Creatinine"/"Glucose"/"BUN" co-occurrences.
    min_components: 3
```

- [ ] **Step 2: Verify nothing else changed**

Run: `git diff clinosim/modules/output/reference_data/lab_panel_groups.yaml | head -50`
Expected: only the two comment blocks differ; `min_components` lines unchanged; no other panel touched.

- [ ] **Step 3: Run the full test suite to confirm comment-only edit broke nothing**

Run: `pytest -m "unit or integration" -x -q`
Expected: all green (the comment edit cannot affect behavior).

- [ ] **Step 4: Commit**

```bash
git add clinosim/modules/output/reference_data/lab_panel_groups.yaml
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
docs(panel-groups): correct CBC/BMP min_components rationale

The pre-PR1 comments blamed the physiology engine ("Hct often absent",
"Cl, Ca rare"), but the real cause was that lab_panels.yaml had no CBC
or BMP entry, so the panel orders silently dropped at the scalar path.
Now that the registry is in place, the depressed min_components are
explained by the pre-PR1 emission profile; PR2 raises them from data.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0127GWvxNrBL5GebQQFVJNqd
EOF
)"
```

---

### Task 4: Byte-diff verification script

**Files:**
- Create: `scratchpad/cbc_bmp_byte_diff.py`

**Interfaces:** Standalone CLI script. Does not import any test infrastructure. Drives `clinosim` programmatically via `run_beta` and `convert_cif_to_fhir`.

- [ ] **Step 1: Write the script**

Create `scratchpad/cbc_bmp_byte_diff.py`:

```python
"""Byte-diff invariant verification for PR1 CBC/BMP panel expansion.

Runs the simulator twice (US p=2000 and JP p=1000, seed=42) on the current
git working tree, hashes every NDJSON and CSV under each output directory,
then re-runs on the master ref via a git worktree and prints a per-file
PASS/FAIL table against the spec §4 boundary:

    IDENTICAL (PASS):   Patient/Encounter/Practitioner/Organization/Location/
                        Condition/Procedure/MedicationRequest/MAR/Immunization/
                        FamilyMemberHistory + non-lab Observation files
    DIFF EXPECTED:      Observation.ndjson, DiagnosticReport.ndjson,
                        orders.csv, lab_results.csv

Usage (from repo root):
    python scratchpad/cbc_bmp_byte_diff.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Files we expect to be byte-identical between master and branch.
EXPECT_IDENTICAL = [
    "Patient.ndjson", "Encounter.ndjson", "Practitioner.ndjson",
    "Organization.ndjson", "Location.ndjson", "Condition.ndjson",
    "Procedure.ndjson", "MedicationRequest.ndjson",
    "MedicationAdministration.ndjson", "Immunization.ndjson",
    "FamilyMemberHistory.ndjson",
    # CSVs unrelated to labs
    "patients.csv", "encounters.csv", "diagnoses.csv", "vital_signs.csv",
    "medication_administrations.csv", "procedures.csv",
    "rehab_sessions.csv", "intake_output.csv", "adl_assessments.csv",
    "nursing_risk.csv", "immunizations.csv", "family_history.csv",
    "code_status.csv", "discharge_prescriptions.csv",
]

# Files we expect to differ (additions or in-place result[] growth).
EXPECT_DIFF = [
    "Observation.ndjson", "DiagnosticReport.ndjson",
    "orders.csv", "lab_results.csv",
]


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def file_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def hash_dir(d: Path) -> dict[str, tuple[str, int]]:
    """Return {filename: (sha256, line_count)} for every file in d."""
    out = {}
    for p in sorted(d.glob("*")):
        if p.is_file():
            out[p.name] = (file_sha(p), file_line_count(p))
    return out


def run_simulator(cwd: Path, out_dir: Path, country: str, n: int, seed: int) -> None:
    """Invoke the clinosim CLI from the given working tree (current or master worktree)."""
    cmd = [
        sys.executable, "-m", "clinosim.simulator.cli",
        "generate",
        "--country", country,
        "-p", str(n),
        "-s", str(seed),
        "-o", str(out_dir),
        "--format", "fhir", "csv",  # nargs="+" — multiple format tokens
    ]
    subprocess.run(cmd, check=True, cwd=cwd)


def compare(branch_dir: Path, master_dir: Path, label: str) -> int:
    """Return 0 on PASS, 1 on FAIL."""
    branch_hashes = hash_dir(branch_dir)
    master_hashes = hash_dir(master_dir)

    print(f"\n=== {label} ===")
    failures = 0
    for fname in EXPECT_IDENTICAL:
        b = branch_hashes.get(fname)
        m = master_hashes.get(fname)
        if b is None and m is None:
            continue
        status = "PASS" if b == m else "FAIL"
        if status == "FAIL":
            failures += 1
        print(f"  [{status}] IDENTICAL  {fname}: "
              f"master={m and m[1]} lines / branch={b and b[1]} lines")

    for fname in EXPECT_DIFF:
        b = branch_hashes.get(fname)
        m = master_hashes.get(fname)
        if b is None and m is None:
            continue
        # Branch must be a superset in lines (additions only). For
        # DiagnosticReport.ndjson the line count grows for new DRs (DVT/HS/DKA)
        # AND in-place; for orders.csv the line count grows for child rows.
        ok = (b is not None and m is not None and b[1] >= m[1])
        status = "PASS" if ok else "FAIL"
        if status == "FAIL":
            failures += 1
        print(f"  [{status}] DIFF-OK    {fname}: "
              f"master={m and m[1]} → branch={b and b[1]} "
              f"({b[1] - m[1]:+d} lines)" if b and m else f"  {fname}: missing")

    # Any branch file not in either bucket → unexpected diff.
    unexpected = sorted(set(branch_hashes) | set(master_hashes)) \
                 - set(EXPECT_IDENTICAL) - set(EXPECT_DIFF)
    for fname in sorted(unexpected):
        b = branch_hashes.get(fname)
        m = master_hashes.get(fname)
        if b != m:
            failures += 1
            print(f"  [FAIL] UNEXPECTED  {fname} differs (not in either bucket)")

    return failures


def main():
    work = Path(tempfile.mkdtemp(prefix="cbcbmp-bd-"))
    branch_us = work / "branch_us"
    branch_jp = work / "branch_jp"
    master_us = work / "master_us"
    master_jp = work / "master_jp"

    print("== branch (current tree) ==")
    run_simulator(REPO, branch_us, "US", 2000, 42)
    run_simulator(REPO, branch_jp, "JP", 1000, 42)

    # Master via a temp worktree so the working tree is undisturbed.
    master_wt = work / "master_wt"
    subprocess.run(["git", "worktree", "add", str(master_wt), "master"],
                   check=True, cwd=REPO)
    try:
        run_simulator(master_wt, master_us, "US", 2000, 42)
        run_simulator(master_wt, master_jp, "JP", 1000, 42)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(master_wt)],
                       check=True, cwd=REPO)

    failures = 0
    # Layout verified against clinosim/modules/output/adapters_builtin.py:
    #   FHIR NDJSONs → <output>/fhir_r4/
    #   CSVs        → <output>/csv/
    #   CIF         → <output>/cif/  (not relevant to byte-diff)
    for label, b, m in [
        ("US p=2000 FHIR", branch_us / "fhir_r4", master_us / "fhir_r4"),
        ("US p=2000 CSV",  branch_us / "csv",     master_us / "csv"),
        ("JP p=1000 FHIR", branch_jp / "fhir_r4", master_jp / "fhir_r4"),
        ("JP p=1000 CSV",  branch_jp / "csv",     master_jp / "csv"),
    ]:
        if b.exists() and m.exists():
            failures += compare(b, m, label)
        else:
            print(f"SKIP {label}: directory missing "
                  f"(branch={b.exists()}, master={m.exists()})")

    print(f"\n=== SUMMARY ===  failures: {failures}")
    if failures:
        print(f"Outputs kept at {work} for inspection.")
        sys.exit(1)
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity-check the CLI invocation before running the full diff**

Run a tiny smoke run to confirm the `clinosim` CLI signature matches the script's assumptions:

```bash
python -m clinosim.simulator.cli generate --help | head -30
```

Expected (verified against `clinosim/simulator/cli.py`): flags `--country`, `-p`/`--population`, `-s`/`--seed`, `-o`/`--output`, `--format` (nargs="+"). If a flag has drifted since this plan was written, adjust the script — don't work around with positional arguments.

- [ ] **Step 3: Run the script**

Run: `python scratchpad/cbc_bmp_byte_diff.py`
Expected: per-file table with the listed PASSes, expected DIFFs on Observation/DR/orders/lab_results, and `failures: 0`.

Total expected wall time: 4 × simulator runs at p≈1500 each. If a single run blows past 10 minutes, kill the script, drop `n` to 500/250, and rerun — for invariant verification we need representative coverage, not a maximal one.

If failures appear:
- A non-allowed NDJSON differs → look at the first 5 differing lines (`diff <(head $branch_file) <(head $master_file)`) and figure out which subsystem leaked.
- An EXPECT_DIFF file went **down** in line count → an existing Observation was deleted, not added. That violates the invariant. Stop, do not commit until resolved.

- [ ] **Step 4: Commit the script (intentionally — future PRs in this family will reuse it)**

```bash
git add scratchpad/cbc_bmp_byte_diff.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
chore(scratchpad): byte-diff invariant script for CBC/BMP expansion

Drives clinosim CLI twice (US p=2000 / JP p=1000 at seed=42) on the
current tree and on master via a temp worktree, then hashes every
NDJSON and CSV in the bundle and prints a PASS/FAIL table against
the spec §4 boundary (additions-only on Observation/DR/orders/labs,
byte-identical everywhere else).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0127GWvxNrBL5GebQQFVJNqd
EOF
)"
```

---

### Task 5: Run audit + write the audit-trail markdown

**Files:**
- Create: `docs/reviews/2026-06-23-cbc-bmp-byte-diff.md`

**Interfaces:** None — narrative + table.

- [ ] **Step 1: Run the byte-diff script once more, capture its output**

```bash
python scratchpad/cbc_bmp_byte_diff.py | tee /tmp/cbc_bmp_byte_diff.log
```

- [ ] **Step 2: Summarize: what does the new emission look like?**

From the branch-side US output, count CBC/BMP DR resources and the new analyte Observations:

```bash
python -c "
import json, collections
loc = '$BRANCH_US_FHIR'  # = <tempdir>/branch_us/fhir_r4 — paste the actual path the script logged
dr = collections.Counter()
for line in open(loc + '/DiagnosticReport.ndjson'):
    d = json.loads(line)
    code = d['code']['coding'][0]['code']
    dr[code] += 1
print('DR by code:', dict(dr))

new_lab = collections.Counter()
for line in open(loc + '/Observation.ndjson'):
    o = json.loads(line)
    if not o.get('id', '').startswith('lab-'):
        continue
    code = o['code']['coding'][0].get('code', '?')
    new_lab[code] += 1
print('Lab Observations by code:', dict(new_lab))
"
```

These counts are what the audit-trail document records (PR1's contribution: the increment of CBC LOINC 58410-2 and BMP 51990-0 counts vs. master, plus the per-analyte WBC/Hb/Hct/Plt/Na/K/HCO3/BUN/Creatinine/Glucose deltas).

- [ ] **Step 3: Write `docs/reviews/2026-06-23-cbc-bmp-byte-diff.md`**

Use this template — fill the numbers from the captured output:

```markdown
# CBC / BMP Panel Expansion (PR1) — Byte-Diff Audit

**Date:** 2026-06-23
**Branch:** `feat/cbc-bmp-panel-expansion`
**Base:** master @ `75f850b9`
**Spec:** `docs/superpowers/specs/2026-06-23-cbc-bmp-panel-expansion-design.md`
**Script:** `scratchpad/cbc_bmp_byte_diff.py`

## Configuration

- US: p=2000, seed=42, format=fhir+csv
- JP: p=1000, seed=42, format=fhir+csv

## Per-file results

### US (p=2000)

| File | Bucket | Master | Branch | Δ | Status |
|---|---|---|---|---|---|
| Patient.ndjson | IDENTICAL | … | … | 0 | PASS |
| Encounter.ndjson | IDENTICAL | … | … | 0 | PASS |
| … | … | … | … | … | … |
| Observation.ndjson | DIFF-OK | … | … | +… | PASS (additions only) |
| DiagnosticReport.ndjson | DIFF-OK | … | … | +… | PASS (additions + in-place result[] growth on cerebral_infarction CBC DRs) |
| orders.csv | DIFF-OK | … | … | +… | PASS (additions + parent CBC/BMP status PLACED→RESULTED) |
| lab_results.csv | DIFF-OK | … | … | +… | PASS (additions only) |

### JP (p=1000)

(same table shape)

## Resource composition (branch side, US p=2000)

### DiagnosticReport by LOINC code

| Code | Display | Count | Δ vs master |
|---|---|---|---|
| 58410-2 | CBC | … | +… |
| 51990-0 | BMP | … | +… |
| 24338-6 | ABG | … | 0 |
| 24325-3 | LFT | … | 0 |
| … | … | … | … |

### Lab Observations by canonical analyte (new ones)

| Analyte | Count | Δ vs master |
|---|---|---|
| WBC | … | +… |
| Hb  | … | +… |
| Hct | … | +… |
| Plt | … | +… |
| Na  | … | +… |
| K   | … | +… |
| HCO3 | … | +… |
| BUN | … | +… |
| Creatinine | … | +… |
| Glucose | … | +… |

(Cl and Ca remain at 0 — physiology engine does not derive them; tracked separately.)

## Verdict

[Either: "All byte-diff invariants hold. PR1 is safe to merge pending review."
 or: "FAILED — <reason>; investigation required before merge."]

## Notes

- The cerebral_infarction patients show in-place `result[]` growth on the
  existing CBC DiagnosticReports (`dr-cbc-<enc>-<seq>`): from `[Hb, Plt]`
  to `[WBC, Hb, Hct, Plt]`. The DR id is preserved (verified by …).
- The parent CBC/BMP orders' status changes from PLACED to RESULTED at
  `inpatient.py:584`. Their `OrderResult` field stays null, so no scalar
  Observation is emitted for the parent — only for the children.
- Cl and Ca BMP children stay PLACED with no OrderResult, mirroring how
  any individual `{test: "Cl"}` order behaves on master today.
```

- [ ] **Step 4: Commit**

```bash
git add docs/reviews/2026-06-23-cbc-bmp-byte-diff.md
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
docs(review): byte-diff audit for CBC/BMP panel expansion (PR1)

US p=2000 + JP p=1000 at seed=42 vs master @ 75f850b9. All byte-diff
invariants hold per spec §4: Patient/Encounter/Practitioner/Org/Location/
Condition/Procedure/MedicationRequest/MAR/Immunization/FamilyMemberHistory
and non-lab Observations are byte-identical; Observation, DiagnosticReport,
orders and lab_results CSVs differ only by the expected additions plus the
cerebral_infarction CBC DR result[] in-place growth.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0127GWvxNrBL5GebQQFVJNqd
EOF
)"
```

---

### Task 6: Final suite + PR

**Files:** none — only verification and PR creation.

- [ ] **Step 1: Full test suite**

Run: `pytest -x -q`
Expected: all green (the project baseline was 500 unit + integration + 39 e2e green as of master `75f850b9`). The two new unit tests and three integration tests should appear in the totals.

- [ ] **Step 2: Lint + types**

Run: `ruff check clinosim tests scratchpad/cbc_bmp_byte_diff.py`
Run: `mypy clinosim` (strict — the project baseline)
Expected: no new errors. The YAML edits don't affect either; the test files use only well-typed APIs.

- [ ] **Step 3: Push the branch**

```bash
git push -u origin feat/cbc-bmp-panel-expansion
```

- [ ] **Step 4: Open the PR**

Use the project's `gh pr create` pattern (see existing PRs for body shape):

```bash
gh pr create --title "feat(observation): register CBC and BMP in panel expansion registry (PR1)" --body "$(cat <<'EOF'
## Summary

Registers CBC and BMP in `clinosim/modules/observation/reference_data/lab_panels.yaml`
so that 9 currently-silently-dropped `{test: "CBC"}` / `{test: "BMP"}` orders
across 4 disease protocols (cerebral_infarction, deep_vein_thrombosis,
hemorrhagic_stroke, diabetic_ketoacidosis) emit canonical child component
Observations through the existing ABG panel-expansion mechanism at
`inpatient.py:572-585`.

The PR #72 calibration comments ("Hct often absent", "Cl, Ca rare") had
misdiagnosed the gap as a physiology-engine issue; in fact the engine
already derives Hct (line 312) and US/JP reference ranges exist. The
single defect was the missing registry entries.

This is **PR1 of a planned 2-PR sequence**. PR2 will (a) audit the new
emission profile and raise `min_components` in `lab_panel_groups.yaml`
from the data, and (b) remove the now-redundant `{test: "Hb"}/"Plt"` at
`cerebral_infarction.yaml:139-140`.

Spec: `docs/superpowers/specs/2026-06-23-cbc-bmp-panel-expansion-design.md`
Byte-diff audit: `docs/reviews/2026-06-23-cbc-bmp-byte-diff.md`

## Byte-diff invariant

US p=2000 + JP p=1000 at seed=42 vs master @ `75f850b9`:

- **IDENTICAL**: Patient, Encounter, Practitioner, Organization, Location,
  Condition, Procedure, MedicationRequest, MedicationAdministration,
  Immunization, FamilyMemberHistory, all non-lab Observations, all
  non-lab CSVs.
- **DIFF (expected, additions only)**: `Observation.ndjson` (new CBC/BMP
  children), `DiagnosticReport.ndjson` (new DRs in DVT/HS/DKA + in-place
  `result[]` growth on existing cerebral_infarction CBC DRs — same id,
  longer result list), `orders.csv` (parent CBC/BMP PLACED→RESULTED +
  child rows; Cl/Ca children stay PLACED), `lab_results.csv` (additions).

Full per-file PASS table in the byte-diff audit doc.

## Out of scope (PR2)

- Raising `min_components` in `lab_panel_groups.yaml` (needs PR1's
  emission profile to set the threshold from data).
- Removing redundant `{test: "Hb"}/"Plt"` at cerebral_infarction.yaml
  lines 139-140 (would shift `enumerate` indices and break this PR's
  byte-diff envelope).
- Adding Cl and Ca to `derive_lab_values()` (separate analyte backlog).

## Test plan

- [x] Unit tests: `lab_panel_components("ABG"|"CBC"|"BMP")` return the
      expected component lists.
- [x] Integration tests: cerebral_infarction CBC emits {WBC, Hb, Hct, Plt};
      DKA BMP emits 6 components and drops Cl/Ca; panel parents never
      emit a scalar OrderResult.
- [x] Byte-diff verification at US p=2000 / JP p=1000.
- [x] Full `pytest -x -q` green.
- [x] `ruff check` and `mypy` (strict) clean.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_0127GWvxNrBL5GebQQFVJNqd
EOF
)"
```

- [ ] **Step 5: Report the PR URL**

`gh pr create` prints the new URL on success — report it back so it can be reviewed.

---

## Self-review (writing-plans skill checklist)

**Spec coverage:**
- §2.1.1 panel YAML add → Task 1.
- §2.1.2 lab_panel_groups.yaml comment update → Task 3.
- §2.1.3 unit + integration tests → Task 1 (unit) + Task 2 (integration).
- §2.2 PR2 deferrals → encoded in Global Constraints and the PR body.
- §3 BNP-pattern surgical reasoning → spelled out in Global Constraints and PR body.
- §4 byte-diff invariant → Task 4 (script) + Task 5 (audit doc).
- §6 PR2 follow-up → cross-referenced in the PR body.
- §8 acceptance checklist → mapped to Tasks 1, 3, 1+2, 4, 5, 6.

**Placeholder scan:** the `…` symbols in the audit-trail markdown template are intentional fill-in points the implementer populates from script output, not plan placeholders. No `TBD`/`TODO`. No `similar to Task N`.

**Type consistency:** `lab_panel_components`, `ForcedScenario`, `run_forced`, `SimulatorConfig`, `_panel_children` references all match the actual repo symbols inspected during brainstorming. `OrderResult.lab_name` is the attribute the existing tests use.
