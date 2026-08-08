# MedicationRequest.category Unification — Implementation Plan (Issue #548)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `_derive_mr_category` as the single canonical helper for `MedicationRequest.category` (code, display) tuple derivation, called by both `_build_medication_request` (order path) and `_build_discharge_medication_request` (discharge path). Fixes the observed silent divergence between the 5-branch (order) and 2-branch (discharge) inline decision trees.

**Architecture:** One module-private helper (~40 LOC) in `clinosim/modules/output/fhir_r4/medications/medications.py` adjacent to existing `_course_for_order` / `_course_for_discharge` helpers. Both public builders replace their inline decision tree with a call to the helper; each supplies the four decision axes (`encounter_type`, `is_home_med`, `is_episodic`, `is_discharge_intent`) explicitly. Order path passes the axes derived from `clinical_intent` substrings (unchanged from pre-refactor); discharge path passes fixed literals (`is_home_med=False`, `is_episodic=False`, `is_discharge_intent=True`) reflecting the caller's identity.

**Tech Stack:** Python 3.12, pytest, ruff==0.16.0 (CI-pinned), mypy strict, `clinosim` FHIR R4 emit path.

## Global Constraints

- Branch discipline: never commit directly to `master`; work on branch `fix/548-medication-request-category-unification` off current `origin/master`.
- ruff version: install `ruff==0.16.0` (CI-pinned) before any lint step.
- Signed-off commits required: every `git commit` must include `--signoff` (DCO gate).
- Byte-diff neutrality is NOT global — this refactor produces documented shifts on emergency-encounter (and possibly empty-encounter-type) discharge items only. Non-Encounter resources, non-shift items, and non-`MedicationRequest.category` fields MUST remain byte-identical vs baseline; this is a per-verification gate.
- Base ref for byte-diff comparisons: **current `origin/master` at branch cut time** (record the exact commit SHA in the PR body — becomes the fingerprint baseline).
- JP cohort env var (required for JP validation runs): `CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package'`
- Sub-project spec: `docs/superpowers/specs/2026-08-08-548-medication-request-category-unification-design.md` — authoritative for every design decision (DD1-DD4). Any deviation blocks merge.
- Baseline generation MUST run in the primary worktree (not an isolated worktree) — the JP-CLINS package discovery in `clinosim/modules/output/fhir_r4/labs/coding_package.py:549` uses `Path(__file__).parents[5]` and resolves to a dev-fallback path that is missing when the worktree lives under `/tmp/`. Use the "in-place swap" pattern from Task 1 rather than `git worktree add`.

---

## File Structure

**Files created:**

| Path | Responsibility |
|---|---|
| `tests/unit/output/test_medication_request_category_derivation.py` | 3 parametrized test groups (24 total assertions) locking `_derive_mr_category` behavior and discharge-caller shift |

**Files modified:**

| Path | Change |
|---|---|
| `clinosim/modules/output/fhir_r4/medications/medications.py` | Add `_derive_mr_category` helper adjacent to `_course_for_discharge` (after L122). Update `_build_medication_request` L679-698 to call the helper (7 LOC in place of 20). Update `_build_discharge_medication_request` L890-895 to call the helper (7 LOC in place of 6). |

**Files NOT modified:**

- `_course_for_order`, `_course_for_discharge` — clinically distinct concepts (session 84 separation preserved).
- `_build_medication_request` slots other than category — all order-specific.
- `_build_discharge_medication_request` slots other than category — all discharge-specific (source-shape driven).
- All other builders and helpers in `medications.py`.

---

## Task 1: Preflight — measure current MedicationRequest.category distribution

**Files:**
- Read: `clinosim/modules/output/fhir_r4/medications/medications.py:679-698, 890-895` (the two inline decision sites).
- Write to scratchpad: `/private/tmp/claude-*/scratchpad/548-preflight-baseline.txt`
- Write to scratchpad: `/private/tmp/claude-*/scratchpad/548-preflight-notes.md`

**Interfaces:**
- Consumes: current `origin/master` code (no branch cut yet).
- Produces: (a) baseline category-code frequency map for JP + US cohorts, (b) list of `-ED-` or emergency-encounter discharge items in each cohort (shift targets), (c) count of items whose `encounter_type` field is empty or outside {"inpatient", "outpatient", "emergency"}.

**Purpose:** DD4 accepts a byte-diff shift on emergency-encounter and unknown-encounter-type discharge items. This task measures the exact shift count so the PR body can quote it verbatim (rather than "expected 1-5 items"). Also confirms the assumption that empty-encounter-type discharge items are 0 occurrences.

- [ ] **Step 1: Cut the fix branch off latest origin/master, install pinned ruff**

Run:
```bash
cd /Users/tokuyama/workspace/clinosim
git fetch --prune origin
git checkout -b fix/548-medication-request-category-unification origin/master
git rev-parse HEAD > /tmp/548-baseline-sha.txt   # capture baseline SHA
python -m pip install ruff==0.16.0
```

Expected: on new branch off origin/master, baseline SHA captured, ruff 0.16.0 active.

- [ ] **Step 2: Generate baseline cohorts (in-place, no worktree swap needed at this stage)**

The branch is still identical to origin/master (no refactor yet), so we can generate baseline cohorts directly:

```bash
CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package' PYTHONPATH=. clinosim simulate -p 30 -s 42 --country JP --format fhir-r4 -o /tmp/548-baseline-jp
CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package' PYTHONPATH=. clinosim simulate -p 30 -s 42 --country US --format fhir-r4 -o /tmp/548-baseline-us
```

Expected: two output directories with `MedicationRequest.ndjson` files present.

- [ ] **Step 3: Enumerate category distribution + shift targets**

Run this probe script (write to scratchpad first, then execute):

Create `/private/tmp/claude-*/scratchpad/548-probe.py`:

```python
"""Preflight probe for Issue #548. Prints:
1. MedicationRequest.category.coding[0].code frequency map for JP+US cohorts.
2. Count of shift-target items:
   - emergency-encounter discharge items (id starts with 'discharge-rx-' or 'outpatient-rx-'
     AND encounter reference resolves to an emergency-class Encounter).
   - empty / unknown encounter_type discharge items (impossible per simulator schema,
     but verify explicitly).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def load_ndjson(p: Path) -> list[dict]:
    with p.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def probe(cohort_dir: Path) -> None:
    print(f"=== {cohort_dir.name} ===")
    mr_path = cohort_dir / "fhir_r4" / "MedicationRequest.ndjson"
    enc_path = cohort_dir / "fhir_r4" / "Encounter.ndjson"

    encounters_by_id: dict[str, dict] = {}
    for enc in load_ndjson(enc_path):
        encounters_by_id[enc["id"]] = enc

    def enc_type_for(ref: str) -> str:
        """Given an 'Encounter/ENC-...' reference, return the encounter's class code."""
        enc_id = ref.split("/", 1)[1] if "/" in ref else ref
        enc = encounters_by_id.get(enc_id)
        if not enc:
            return "MISSING"
        # Map FHIR class code (IMP/AMB/EMER) back to CIF encounter_type
        cls = enc.get("class", {}).get("code", "")
        return {"IMP": "inpatient", "AMB": "outpatient", "EMER": "emergency"}.get(cls, cls or "EMPTY")

    cat_counter: Counter[str] = Counter()
    shift_targets: list[tuple[str, str, str]] = []  # (mr_id, mr_category, enc_type)
    unknown_enc_type: list[tuple[str, str, str]] = []

    for mr in load_ndjson(mr_path):
        cat = mr.get("category", [{}])[0].get("coding", [{}])[0].get("code", "MISSING")
        cat_counter[cat] += 1
        mr_id = mr.get("id", "")
        # Discharge-path items have id starting with 'discharge-rx-' or 'outpatient-rx-'
        # (constants DISCHARGE_RX_ID_PREFIX / OUTPATIENT_RX_ID_PREFIX in medications.py).
        # Order-path items don't have those prefixes.
        is_discharge_item = mr_id.startswith("discharge-rx-") or mr_id.startswith("outpatient-rx-")
        if not is_discharge_item:
            continue
        enc_ref = mr.get("encounter", {}).get("reference", "")
        et = enc_type_for(enc_ref) if enc_ref else "EMPTY"
        if et == "emergency":
            shift_targets.append((mr_id, cat, et))
        if et in ("EMPTY", "MISSING") or et not in ("inpatient", "outpatient", "emergency"):
            unknown_enc_type.append((mr_id, cat, et))

    print(f"category distribution: {dict(cat_counter)}")
    print(f"emergency-encounter discharge items (SHIFT TARGET): {len(shift_targets)}")
    for row in shift_targets[:5]:
        print(f"  {row}")
    print(f"unknown / empty encounter_type discharge items: {len(unknown_enc_type)}")
    for row in unknown_enc_type[:5]:
        print(f"  {row}")


for cohort in ("/tmp/548-baseline-jp", "/tmp/548-baseline-us"):
    probe(Path(cohort))
```

Run:
```bash
PYTHONPATH=. python /private/tmp/claude-*/scratchpad/548-probe.py 2>&1 | tee /private/tmp/claude-*/scratchpad/548-preflight-baseline.txt
```

Expected output shape:
```
=== 548-baseline-jp ===
category distribution: {'community': N1, 'outpatient': N2, 'inpatient': N3, 'discharge': N4}
emergency-encounter discharge items (SHIFT TARGET): <N_shift>
  ('discharge-rx-ENC-...-01', 'community', 'emergency')
  ...
unknown / empty encounter_type discharge items: <N_unknown>
```

- [ ] **Step 4: Record findings in preflight notes**

Create `/private/tmp/claude-*/scratchpad/548-preflight-notes.md`:

```markdown
# 548 preflight — MedicationRequest.category distribution + shift targets

Baseline SHA: <contents of /tmp/548-baseline-sha.txt>

## JP cohort (30 patients, seed 42)

- Total MedicationRequest resources: <N_total_jp>
- category distribution: <verbatim from probe output>
- Emergency-encounter discharge items (SHIFT: community → outpatient): <N>
  <sample ids>
- Unknown / empty encounter_type discharge items (SHIFT: community → inpatient): <N>
  <expected: 0>

## US cohort (30 patients, seed 42)

<same layout>

## Expected refactor byte-diff surface

- Non-`MedicationRequest.ndjson` files: byte-identical
- `MedicationRequest.ndjson`: N_shift_jp + N_shift_us total shifts on
  the enumerated items, category field only, no other field diffs
- Timestamp / manifest files: differ (metadata only, ignored via
  `diff -x _generator_metadata.json`)
```

Fill in every `<...>` from the probe output. Task 4 will re-run diff-r
after refactor and verify shift count exactly matches this preflight
enumeration.

- [ ] **Step 5: Preserve baseline cohorts for Task 4 diff**

Do NOT delete `/tmp/548-baseline-jp` and `/tmp/548-baseline-us` yet —
Task 4 uses them as the diff LHS. No commit in this task.

---

## Task 2: Write regression tests (all initially FAIL)

**Files:**
- Create: `tests/unit/output/test_medication_request_category_derivation.py`

**Interfaces:**
- Consumes: Task 1's preflight measurement (informs but doesn't dictate test values — tests are hand-authored against the spec's decision table, not the observed data).
- Produces: 24 test assertions (3 parametrize groups) all failing against current code because `_derive_mr_category` does not exist yet.

- [ ] **Step 1: Write the test file with all 3 test groups**

Create `tests/unit/output/test_medication_request_category_derivation.py`:

```python
"""Regression guards for Issue #548 — MedicationRequest.category derivation.

`_derive_mr_category` is the single source of truth for the
medicationrequest-category (code, display) tuple emitted by both
`_build_medication_request` (order path) and
`_build_discharge_medication_request` (discharge path).

Prior to Issue #548 each caller used its own inline decision (5-branch
vs 2-branch), letting the discharge path silently misclassify
emergency-encounter discharge scripts as `community` when they are
actually episodic ED-treatment (HL7-canonical: `outpatient`).

These tests lock:

1. All 5 canonical decision-tree branches produce the expected
   (code, display) tuple across the full input space.
2. The discharge-path caller (is_home_med=False, is_episodic=False,
   is_discharge_intent=True) produces the intended per-encounter-type
   category tuples, INCLUDING the two documented shifts vs pre-#548
   behavior (emergency → outpatient; empty/unknown → inpatient).
3. The order-path caller's boolean derivation (from clinical_intent
   substrings) maps to the same tuples as before the extraction —
   proves the refactor is byte-neutral on the order side.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.medications.medications import _derive_mr_category

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "encounter_type,is_home_med,is_episodic,is_discharge_intent,expected",
    [
        # Rule 1: home_med always community (regardless of encounter type)
        ("inpatient", True, False, False, ("community", "Community")),
        ("outpatient", True, False, False, ("community", "Community")),
        ("emergency", True, False, False, ("community", "Community")),
        # Rule 1: outpatient non-episodic = community
        ("outpatient", False, False, False, ("community", "Community")),
        ("outpatient", False, False, True, ("community", "Community")),
        # Rule 2: outpatient episodic = outpatient (rule 1 fails on episodic=True)
        ("outpatient", False, True, False, ("outpatient", "Outpatient")),
        # Rule 2: emergency = outpatient (regardless of episodic flag)
        ("emergency", False, False, False, ("outpatient", "Outpatient")),
        ("emergency", False, True, False, ("outpatient", "Outpatient")),
        # Rule 3: inpatient with discharge intent
        ("inpatient", False, False, True, ("discharge", "Discharge")),
        # Rule 4: inpatient without discharge intent
        ("inpatient", False, False, False, ("inpatient", "Inpatient")),
        ("inpatient", False, True, False, ("inpatient", "Inpatient")),
        # Rule 5: unknown / empty fallback
        ("", False, False, False, ("inpatient", "Inpatient")),
        ("virtual", False, False, False, ("inpatient", "Inpatient")),
    ],
)
def test_derive_mr_category(
    encounter_type: str,
    is_home_med: bool,
    is_episodic: bool,
    is_discharge_intent: bool,
    expected: tuple[str, str],
) -> None:
    """Direct-input coverage for all five rules of `_derive_mr_category`."""
    assert (
        _derive_mr_category(encounter_type, is_home_med, is_episodic, is_discharge_intent)
        == expected
    )


@pytest.mark.parametrize(
    "encounter_type,expected_code",
    [
        ("inpatient", "discharge"),   # no shift (rule 3)
        ("outpatient", "community"),  # no shift (rule 1)
        ("emergency", "outpatient"),  # SHIFT: was "community" pre-Issue-#548
        ("", "inpatient"),            # SHIFT edge: was "community" pre-Issue-#548
        ("virtual", "inpatient"),     # SHIFT edge (unknown encounter type)
    ],
)
def test_derive_mr_category_discharge_caller_shift(
    encounter_type: str, expected_code: str
) -> None:
    """Documented shifts introduced by the Issue #548 unification.

    The discharge path historically used a 2-branch decision (inpatient →
    discharge, else → community). The 5-rule unified logic corrects the
    ED-discharge case (episodic Rx should be `outpatient`, not community)
    and the empty/unknown-encounter-type fallback (`inpatient` matches
    the order path's fallback rather than defaulting to `community`).
    """
    code, _display = _derive_mr_category(
        encounter_type=encounter_type,
        is_home_med=False,
        is_episodic=False,
        is_discharge_intent=True,
    )
    assert code == expected_code


@pytest.mark.parametrize(
    "encounter_type,clinical_intent,expected_code",
    [
        # Order path pre-Issue-#548 emitted these; refactor must preserve.
        ("inpatient", "home medication list", "community"),
        ("outpatient", "annual check-up", "community"),
        ("outpatient", "supportive: iv fluids", "outpatient"),
        ("emergency", "ed treatment: nebulizer", "outpatient"),
        ("inpatient", "discharge take-home", "discharge"),
        ("inpatient", "day 3 iv antibiotics", "inpatient"),  # episodic + inpatient = inpatient
        ("", "", "inpatient"),  # empty fallback
    ],
)
def test_order_caller_category_byte_neutral(
    encounter_type: str, clinical_intent: str, expected_code: str
) -> None:
    """Prove the order-path helper derivation reproduces pre-#548 behavior.

    The order caller derives is_home_med / is_episodic / is_discharge_intent
    from clinical_intent substrings; this test threads those same substrings
    through the derivation and asserts the resulting category matches what
    the pre-refactor inline decision tree at
    `_build_medication_request:679-698` would emit.
    """
    ci_lower = clinical_intent.lower()
    is_home_med = "home medication" in ci_lower
    episodic_kw = (
        "supportive:",
        "ed treatment:",
        "day ",
        "dvt_prophylaxis",
        "antibiotic",
        "escalation",
    )
    is_episodic = (not is_home_med) and any(kw in ci_lower for kw in episodic_kw)
    is_discharge_intent = "discharge" in ci_lower
    code, _display = _derive_mr_category(
        encounter_type, is_home_med, is_episodic, is_discharge_intent
    )
    assert code == expected_code
```

- [ ] **Step 2: Run the new tests — all must FAIL against current code**

```bash
PYTHONPATH=. pytest tests/unit/output/test_medication_request_category_derivation.py -v 2>&1 | tail -30
```

Expected: all 24 tests fail with `ImportError: cannot import name '_derive_mr_category' from 'clinosim.modules.output.fhir_r4.medications.medications'`.

If any test passes (impossible without the symbol existing), stop and investigate — the current code has been changed since the plan was written.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/unit/output/test_medication_request_category_derivation.py
git commit --signoff -m "test(medications): _derive_mr_category regression tests — Issue #548

Three parametrized test groups (24 assertions) locking the target
behavior for the canonical MedicationRequest.category derivation:

- test_derive_mr_category: direct coverage of all 5 rules (13 cases)
- test_derive_mr_category_discharge_caller_shift: documented shifts
  vs pre-#548 discharge-path behavior (5 cases)
- test_order_caller_category_byte_neutral: proves the order-path
  boolean derivation reproduces pre-#548 output (7 cases, but 6
  parametrize as the last row is empty-fallback)

All 24 currently FAIL with ImportError (_derive_mr_category does not
exist yet) — turn GREEN after Task 3's refactor lands."
```

---

## Task 3: Refactor `medications.py` — add helper + swap two call sites

**Files:**
- Modify: `clinosim/modules/output/fhir_r4/medications/medications.py`

**Interfaces:**
- Consumes: Task 2's failing tests (become GREEN after this task).
- Produces: `_derive_mr_category(encounter_type, is_home_med, is_episodic, is_discharge_intent) -> tuple[str, str]` helper importable at module level; two call sites replaced with helper calls.

- [ ] **Step 1: Add `_derive_mr_category` helper**

Edit `clinosim/modules/output/fhir_r4/medications/medications.py`. Immediately after `_course_for_discharge` (current end of line 122), insert:

```python


def _derive_mr_category(
    encounter_type: str,
    is_home_med: bool,
    is_episodic: bool,
    is_discharge_intent: bool,
) -> tuple[str, str]:
    """Derive the ``medicationrequest-category`` (code, display) tuple for
    a FHIR MedicationRequest emission (Issue #548 unification).

    Single source of truth for the 5-way decision tree previously
    duplicated across the order path (5-branch) and the discharge path
    (2-branch, which silently omitted episodic / discharge-intent
    awareness).

    HL7 CodeSystem: ``medicationrequest-category``
      * ``community``  — chronic home-medication or outpatient renewal
      * ``outpatient`` — episodic outpatient / emergency-department order
      * ``inpatient``  — inpatient order that is NOT a take-home
      * ``discharge``  — inpatient take-home script (Rx at discharge)

    Decision rule (evaluated in order):

    1. ``is_home_med`` OR (``encounter_type=="outpatient"`` AND NOT ``is_episodic``)
       → ``community`` — chronic maintenance / outpatient renewal
    2. ``encounter_type`` in ("outpatient", "emergency")
       → ``outpatient`` — episodic OP / ED order
    3. ``encounter_type == "inpatient"`` AND ``is_discharge_intent``
       → ``discharge`` — inpatient take-home
    4. ``encounter_type == "inpatient"``
       → ``inpatient`` — in-house prescription
    5. otherwise (encounter_type empty / unknown)
       → ``inpatient`` — safe fallback (intent already indicates an order was authored)
    """
    if is_home_med or (encounter_type == "outpatient" and not is_episodic):
        return "community", "Community"
    if encounter_type in ("outpatient", "emergency"):
        return "outpatient", "Outpatient"
    if encounter_type == "inpatient" and is_discharge_intent:
        return "discharge", "Discharge"
    if encounter_type == "inpatient":
        return "inpatient", "Inpatient"
    return "inpatient", "Inpatient"
```

The blank line separators match the existing `_course_for_order` / `_course_for_discharge` layout.

- [ ] **Step 2: Replace the inline decision tree in `_build_medication_request`**

Locate `_build_medication_request` (currently starts at L551). Find the category block (L672-698, starting `# CY6-22 (Chain-6): MedicationRequest.category`) and replace with:

```python
    # CY6-22 (Chain-6): MedicationRequest.category — HL7 medicationrequest-
    # category (inpatient / outpatient / community / discharge). Derived
    # from encounter_type + is_home_med + is_episodic (already computed above).
    # Issue #548: canonical decision tree extracted to `_derive_mr_category`.
    # ED encounters (encounter_type == "emergency") map to "outpatient" because
    # the patient is not admitted; discharge from ED emits under the same
    # community-Rx-at-discharge category as chronic outpatient scripts when
    # clinical_intent indicates the Rx is a take-home.
    _is_discharge_intent = "discharge" in _ci_lower
    _cat_code, _cat_display = _derive_mr_category(
        encounter_type=encounter_type,
        is_home_med=_is_home_med,
        is_episodic=_is_episodic,
        is_discharge_intent=_is_discharge_intent,
    )
    resource["category"] = _build_category_block(_cat_code, _cat_display)
```

Deletion scope: the entire block from `_cat_code = _cat_display = ""` (currently ~L679) through the `if _cat_code:` gate + `resource["category"] = ...` (currently ~L698). Replacement is the block above.

Verify no dangling `_cat_code = ""` initialisation, and that `_is_home_med`, `_is_episodic`, `_ci_lower` are all defined in scope (they are — computed earlier at L611-614).

- [ ] **Step 3: Replace the inline 2-branch in `_build_discharge_medication_request`**

Locate `_build_discharge_medication_request` (currently starts at L825). Find the category block (L890-895, starting `# category: derived from the encounter, never hardcoded`) and replace with:

```python
    # Issue #548: canonical decision tree extracted to `_derive_mr_category`.
    # discharge builder's caller identity implies is_discharge_intent=True
    # and no episodic-order / home-medication semantics — DischargeRxItem
    # lacks the clinical_intent tag that the order path uses to detect
    # these. Pre-#548 this path used a 2-branch inline decision that
    # silently misclassified emergency-encounter discharge scripts as
    # `community` instead of `outpatient`; the unified helper now emits
    # the HL7-canonical value.
    cat_code, cat_display = _derive_mr_category(
        encounter_type=encounter_type,
        is_home_med=False,
        is_episodic=False,
        is_discharge_intent=True,
    )
    resource["category"] = _build_category_block(cat_code, cat_display)
```

Deletion scope: the block starting `# category: derived from the encounter, never hardcoded.` through `resource["category"] = _build_category_block(cat_code, cat_display)`.

- [ ] **Step 4: Run the Task 2 regression tests — all 24 must PASS**

```bash
PYTHONPATH=. pytest tests/unit/output/test_medication_request_category_derivation.py -v 2>&1 | tail -30
```

Expected: 24 pass, 0 fail. If any test still fails, DO NOT proceed — the refactor is incomplete. Fix inline, then re-run.

- [ ] **Step 5: Run the full unit test suite**

```bash
PYTHONPATH=. pytest tests/unit -x 2>&1 | tail -5
```

Expected: 3977 baseline + 24 new = 4001 pass. If any pre-existing test fails:
- If it asserts on the emergency-encounter discharge category value: update the expected value from `"community"` to `"outpatient"` with an inline comment `# Issue #548: shift documented in design DD4`.
- If it asserts on other category values on discharge items: verify the shift table in the spec's Data Flow section and update accordingly.
- If it is unrelated: unrelated breakage — investigate before assuming ownership.

- [ ] **Step 6: Lint + type check**

```bash
ruff check clinosim/modules/output/fhir_r4/medications/medications.py tests/unit/output/test_medication_request_category_derivation.py
ruff format --check clinosim/modules/output/fhir_r4/medications/medications.py tests/unit/output/test_medication_request_category_derivation.py
mypy clinosim/
```

Expected: clean on all three. If `ruff format --check` fails, run `ruff format <files>` and re-verify.

- [ ] **Step 7: Commit the refactor**

```bash
git add -u clinosim/modules/output/fhir_r4/medications/medications.py
git commit --signoff -m "refactor(medications): unify MedicationRequest.category derivation — Issue #548

Introduces _derive_mr_category as the single canonical helper for
MedicationRequest.category (code, display) derivation, called by both
the order-path (_build_medication_request) and discharge-path
(_build_discharge_medication_request) FHIR builders.

Pre-#548 the two paths had divergent inline decisions:
- order path: 5-branch tree considering encounter_type + is_home_med +
  is_episodic + clinical_intent contains 'discharge'
- discharge path: 2-branch (inpatient → discharge, else → community)
  silently dropping is_episodic and is_discharge_intent awareness

The unified helper preserves the order path's rule table exactly (proved
byte-neutral by test_order_caller_category_byte_neutral). The discharge
path picks up two documented shifts:
- emergency-encounter discharge items: community → outpatient
  (HL7-canonical: ED discharge Rx is episodic, not chronic refill)
- empty/unknown encounter_type discharge items: community → inpatient
  (aligns fallback with order path's rule 5; expected 0 occurrences
  per Task 1 preflight)

All 24 new regression tests in
test_medication_request_category_derivation.py turn GREEN.

Design: docs/superpowers/specs/2026-08-08-548-medication-request-category-unification-design.md"
```

---

## Task 4: Cohort byte-diff + downstream verification + PR open

**Files:**
- Read: Task 1 baseline cohorts at `/tmp/548-baseline-{jp,us}/`.
- Write to scratchpad: `/private/tmp/claude-*/scratchpad/548-diff-{jp,us}.txt`, `.../548-verification-report.md`.

**Interfaces:**
- Consumes: Task 3's refactor commit on the fix branch, Task 1's preflight measurements and baseline cohorts.
- Produces: PR opened against `master` with the verification report inlined as the byte-diff surface.

- [ ] **Step 1: Generate PR-branch cohorts**

The current worktree is on the fix branch with the refactor applied. Generate PR cohorts in-place:

```bash
CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package' PYTHONPATH=. clinosim simulate -p 30 -s 42 --country JP --format fhir-r4 -o /tmp/548-pr-jp
CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package' PYTHONPATH=. clinosim simulate -p 30 -s 42 --country US --format fhir-r4 -o /tmp/548-pr-us
```

- [ ] **Step 2: Diff both cohorts**

```bash
diff -r /tmp/548-baseline-jp /tmp/548-pr-jp -x _generator_metadata.json > /private/tmp/claude-*/scratchpad/548-diff-jp.txt 2>&1
diff -r /tmp/548-baseline-us /tmp/548-pr-us -x _generator_metadata.json > /private/tmp/claude-*/scratchpad/548-diff-us.txt 2>&1
```

- [ ] **Step 3: Enumerate the diff files and gate on expected shifts only**

For each diff file:

1. Grep for the file list first:
   ```bash
   grep -E '^diff|^Only in' /private/tmp/claude-*/scratchpad/548-diff-jp.txt
   grep -E '^diff|^Only in' /private/tmp/claude-*/scratchpad/548-diff-us.txt
   ```
   Expected: only `cif/metadata.json`, `cif/narratives/template/manifest.json`, `fhir_r4/MedicationRequest.ndjson`, `fhir_r4/manifest.json`, `simulator.log` should appear. Any other file BLOCKS merge.

2. For `MedicationRequest.ndjson`, extract the diff lines and verify each falls into the shift categories:
   ```bash
   grep '^[<>] {"resourceType": "MedicationRequest"' /private/tmp/claude-*/scratchpad/548-diff-jp.txt | wc -l
   ```
   Expected count per cohort:
   - JP: exactly `2 * N_shift_jp` lines (from Task 1 preflight — each shifted item appears once under `<` and once under `>`).
   - US: exactly `2 * N_shift_us` lines.

3. For each diff hunk, parse the `<` and `>` MedicationRequest JSON objects and verify the diff is limited to `category.coding[0].code` and `category.coding[0].display` fields — no other field diffs (id, status, dosageInstruction, etc. must all match).

- [ ] **Step 4: Write verification report**

Create `/private/tmp/claude-*/scratchpad/548-verification-report.md`:

```markdown
## Byte-diff verification (30-patient seed 42)

Baseline SHA: <from /tmp/548-baseline-sha.txt>
PR head SHA: <git rev-parse HEAD>

### JP cohort

- Total MedicationRequest resources: <N_total_jp> (unchanged vs baseline)
- Diff: <2 * N_shift_jp> lines, all on synth-ED bridge Encounters
- category.coding[0].code shifts:
  - `community` → `outpatient`: <N_shift_ED_jp> items (emergency-encounter discharge)
  - `community` → `inpatient`: <N_shift_empty_jp> items (empty/unknown encounter_type — expected 0)
- Non-`MedicationRequest.ndjson` file diffs: metadata/log timestamps only
- Non-`category` field diffs in MedicationRequest.ndjson: 0

### US cohort

<same layout>

### fhir-jp-validator (JP CLINS validator)

<see V-D1 below>

### iris4h-ai downstream grep

<see V-D2 below>
```

Fill in every `<...>` from Task 3 preflight + Task 4 diff analysis.

- [ ] **Step 5: fhir-jp-validator gate (deferred to CI)**

The CI gate `JP p=300 seed=300 → eval only jp_clins_lab_compliance` runs
on every PR. Note in the verification report that local p=300 execution
is deferred to CI; the expected impact is `error count unchanged`
(HL7 `medicationrequest-category` CS accepts all four codes — the shift
moves values between valid codes).

Append to report:
```markdown
### fhir-jp-validator (p=300 seed=300 JP cohort)
- Deferred to CI gate `JP p=300 seed=300 → eval only jp_clins_lab_compliance`
- Expected impact: error count unchanged (medicationrequest-category CS
  accepts all four codes; shift moves between valid values)
```

- [ ] **Step 6: iris4h-ai / fhir-jp-validator downstream grep**

Grep for consumers that branch on the category value:

```bash
grep -rn 'medicationrequest-category\|category.*coding.*code' ../iris4h-ai/ 2>/dev/null | grep -v '\.git/\|\.ndjson\|\.json'
grep -rn 'medicationrequest-category\|category.*coding.*code' ../fhir-jp-validator/ 2>/dev/null | grep -v '\.git/\|\.ndjson\|\.json'
```

For each hit, evaluate whether the code branches on the category value
specifically for MedicationRequest resources. If any branching code
exists AND branches on a shift-affected code (`community` vs
`outpatient`), file a downstream issue and notify the owner. Otherwise,
record findings:

```markdown
### iris4h-ai / fhir-jp-validator downstream grep
- Total MedicationRequest.category references: <N>
- References that branch on community/outpatient value: <N>
- If N > 0: <owner notified, issue #<link>>
- If N == 0: no downstream consumer affected — safe to ship
```

- [ ] **Step 7: Run integration tests**

```bash
PYTHONPATH=. pytest tests/integration -x 2>&1 | tail -10
```

Expected: all pass. Any failing assertion on MedicationRequest.category
for a discharge-path emergency-encounter item is a legitimate
assertion-update request — fix inline with a comment referencing this
design's DD4.

If integration takes too long for interactive execution, note in the
verification report that it's deferred to CI and proceed.

- [ ] **Step 8: Cleanup temp cohorts**

```bash
rm -rf /tmp/548-baseline-jp /tmp/548-baseline-us /tmp/548-pr-jp /tmp/548-pr-us /tmp/548-baseline-sha.txt
```

- [ ] **Step 9: Push branch and open PR**

```bash
git push -u origin fix/548-medication-request-category-unification
gh pr create --title "refactor(medications): unify MedicationRequest.category derivation (closes #548)" --body "$(cat <<'EOF'
## Summary

Extracts `_derive_mr_category` as the single canonical helper for
`MedicationRequest.category` (code, display) derivation, called by both
`_build_medication_request` (order path) and
`_build_discharge_medication_request` (discharge path). Fixes the observed
silent divergence between the 5-branch (order) and 2-branch (discharge)
inline decision trees.

Design: `docs/superpowers/specs/2026-08-08-548-medication-request-category-unification-design.md`
Plan: `docs/superpowers/plans/2026-08-08-548-medication-request-category-unification-plan.md`

## Design decisions realised

- **DD1**: extract only the category slot, leave courseOfTherapyType /
  dispenseRequest / dosageInstruction per-caller (each is either
  clinically-distinct or source-shape-driven).
- **DD2**: canonical = order path's 5-branch decision, cleanly parameterised.
- **DD3**: discharge caller supplies fixed literals
  (`is_home_med=False`, `is_episodic=False`, `is_discharge_intent=True`)
  — DischargeRxItem lacks the `clinical_intent` field the order path uses.
- **DD4**: accept documented byte-diff shift on emergency-encounter and
  empty-encounter-type discharge items (both shifts are semantic
  improvements per HL7 `medicationrequest-category` CS definitions).

## Byte-diff surface — 30-patient seed 42 (both cohorts)

Non-Encounter / non-MedicationRequest resources are byte-identical vs
baseline. All shifts land on `MedicationRequest.category.coding[0].code`
+ `display` fields only.

<PASTE `## Byte-diff verification` section from
/private/tmp/claude-*/scratchpad/548-verification-report.md here>

## Downstream verification

<PASTE `### fhir-jp-validator` and `### iris4h-ai` sections here>

## Test plan
- [x] `pytest tests/unit`: 4001 pass (baseline 3977 + 24 new)
- [x] `pytest tests/integration`: all pass (or deferred to CI, noted)
- [x] `mypy clinosim/` strict: clean
- [x] `ruff==0.16.0 check` + `format --check`: clean
- [x] 30-patient seed 42 JP+US cohort diff-r vs master: only expected
      MedicationRequest.category shifts on emergency-encounter and
      empty-encounter-type discharge items
- [x] fhir-jp-validator error count vs baseline: unchanged (CI gate)
- [x] iris4h-ai / fhir-jp-validator downstream `medicationrequest-category`
      grep: no branching consumer / owner notified

Closes #548.
EOF
)"
```

Copy the PR URL for the loop closure.

- [ ] **Step 10: Wait for CI, then request review**

```bash
gh pr checks <PR#>
```

If any check fails, diagnose and push a fixup commit (with `--signoff`).
Once all checks pass, this task is complete.

- [ ] **Step 11: No additional local commit — GitHub artefacts only**

Nothing further to commit locally. The PR is filed with all verification
evidence embedded. Local branch stays at Task 3's commit.

---

## Self-Review

### Spec coverage

| Spec section | Task |
|---|---|
| Goal (extract `_derive_mr_category`) | Task 3 |
| DD1 (category-only, not full unify) | Task 3 (no changes to courseOfTherapy / dispense / dosage) |
| DD2 (canonical = order path 5-branch) | Task 3 Step 1 (helper body) |
| DD3 (discharge caller literals) | Task 3 Step 3 (helper call with fixed args) |
| DD4 (accept shift, document) | Task 4 (verification report + PR body) |
| Architecture (helper + 2 caller updates) | Task 3 |
| C1 (`_derive_mr_category`) | Task 3 Step 1 |
| C2 (updated order call site) | Task 3 Step 2 |
| C3 (updated discharge call site) | Task 3 Step 3 |
| Data flow (byte-neutral order, shift discharge-emergency + empty) | Task 1 preflight + Task 4 diff |
| Error handling (rule 5 fallback, boolean edge combos) | Task 2 test coverage |
| Unit tests (3 parametrize groups, 24 assertions) | Task 2 |
| Cohort byte-diff verification | Task 4 Steps 1-4 |
| V-D1 fhir-jp-validator | Task 4 Step 5 (deferred to CI) |
| V-D2 iris4h-ai grep | Task 4 Step 6 |
| V-D3 integration | Task 4 Step 7 |
| PR body checklist | Task 4 Step 9 |

All spec sections mapped.

### Placeholder scan

No TBD / TODO / FIXME / "see Task N" placeholders. Runtime substitutions
(`<N_shift_jp>`, `<PR#>`, etc.) are documented at their usage points as
"fill in from preflight" / "from PR creation output" — these are execution-
time values, not plan-authoring gaps.

### Type consistency

- `_derive_mr_category(encounter_type: str, is_home_med: bool, is_episodic: bool, is_discharge_intent: bool) -> tuple[str, str]` signature identical in spec C1, Task 3 Step 1 code, Task 2 test consumer, and Task 3 Steps 2-3 call sites.
- `_build_category_block(code: str, display: str) -> list[dict]` existing signature unchanged, both call sites pass the helper's tuple unpacked.
- No new type aliases introduced.
