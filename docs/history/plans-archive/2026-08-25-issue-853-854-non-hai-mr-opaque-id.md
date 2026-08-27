# Issue #853 (+ #854 recipe) — Non-HAI MedicationRequest opaque id sibling-sweep

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend PR #357's opaque-id pattern (`mr-{sha256(structural_key)[:12]}` + `identifier[]` round-trip + shared resolver) from HAI antibiotic MedicationRequest to **every** MedicationRequest emit path (non-HAI inpatient / discharge-Rx / outpatient-Rx) plus their MedicationAdministration cross-references. Eliminates Issue #853's compound-key surface (visible `-Aminophy` / `-Meropene` truncations, patient-id leak in URLs, ~50-char id length) for the ~108k non-HAI MR + 359k MA that PR #357 did not touch.

**Architecture:** All work stays inside `clinosim/modules/output/fhir_r4/medications/medications.py`. The Phase 1a foundation (`clinosim/modules/output/fhir_r4/lib/ids.py`) is unchanged — this refactor only widens the caller policy. Rename `_resolve_antibiotic_mr_id` → `_resolve_mr_id` (drop the antibiotic-only semantic), remove the `if order_id.startswith(ABX_ORDER_ID_PREFIX)` guard so all orders resolve to opaque, drop the `is_antibiotic_mr` guard on `_build_medication_request_identifiers` so the structural-key identifier is unconditionally round-tripped, and follow the rename through the single downstream importer (`clinosim/audit/axes/clinical.py`) and the three internal call sites. MA cross-refs go through the same widened resolver so `MedicationAdministration.request.reference` stays byte-consistent with `MedicationRequest.id`.

**Tech Stack:** Python 3.12, pytest 8, ruff 0.16.3 (post-PR-#859), `jq` for FHIR verification.

**Spec:** [Issue #853](https://github.com/TomoOkuyama/clinosim/issues/853) (non-HAI MR compound-key) and [Issue #854](https://github.com/TomoOkuyama/clinosim/issues/854) (umbrella: 21 resource types Bucket A/B/C inventory). Reference implementation: [PR #357](https://github.com/TomoOkuyama/clinosim/pull/357) — commit `39ae1b7f2f`. Foundation module: [PR #354](https://github.com/TomoOkuyama/clinosim/pull/354) — commit `23d065522e`, `clinosim/modules/output/fhir_r4/lib/ids.py`. Repository-wide id-length gate: [PR #356](https://github.com/TomoOkuyama/clinosim/pull/356) — commit `49ca81aa10`.

## Global Constraints

- Every commit MUST include a DCO signoff (`git commit -s`).
- `master` direct-commit + `master`-branch pytest FORBIDDEN — branch first, `git branch --show-current` before running tests, report the branch in every message that quotes test output. See memory `feedback_no_direct_commit_to_master.md`.
- Branch name: `fix/853-non-hai-mr-opaque-id`.
- The PR REQUIRED-BLOCKING CI gates are: `Unit tests (Py 3.12)`, `Integration tests (shard 1-3/3)`, `ruff dead-code (F401 / F841)`, `Signed-off-by check`, `Build sdist + wheel`, `mkdocs build`, `JP p=300 seed=300 → eval only jp_clins_lab_compliance`. `Quality (informational)` is `continue-on-error: true` and does NOT block.
- Local ruff for this session is 0.16.3 (post-PR-#859) — matches CI's `ruff-dead-code` and `quality` jobs. Run `ruff format --check clinosim/ tests/` and `ruff check clinosim/ tests/` before each `git push` — see memory `feedback_ruff_format_before_push.md`.
- FHIR R4 `Resource.id` type = `[A-Za-z0-9\-\.]{1,64}`. `_fhir_id_is_spec_valid` (in `clinosim/modules/output/fhir_r4/__init__.py:112`) is the repository-wide gate — all emitted ids must pass it. See PR #356.
- Determinism guarantee: for the same `(seed, hospital_config, country, start, end, population)` tuple, output NDJSON is byte-identical across PATCH-only releases within the same MINOR line. This refactor CHANGES byte output (MR.id shape changes) — a CHANGELOG entry under `## [Unreleased]` MUST document that the shape change is intentional and MINOR-bumpable at the next release.
- FHIR-emit code fix data-patch discipline: DO NOT rewrite regen FHIR ndjson in place. `.id` changes cascade through every cross-reference field (`MedicationAdministration.request.reference`) — only the emit generator can keep those consistent. Sync path is: code fix on branch → `clinosim export-fhir` re-emit from the frozen CIF at `scratchpad_review_vllm-fp8-p10000-s500-n3/cif/` → rsync to `~/workspace/iris4h-ai/fhir_r4/`. See memory `feedback_fhir_emit_bug_no_direct_patch.md`.
- CIF is single Source of Truth. This refactor does NOT touch CIF — `Order.order_id` (which retains the compound shape including the 8-char `sanitize_id_token(drug_name, 8)` truncation at `clinosim/simulator/daily_loop.py:514`) is the structural key input to `derive_opaque_id`. Fixing the CIF-side truncation is out of scope; only the FHIR surface stops carrying it.

---

## File Structure

**Modified:**
- `clinosim/modules/output/fhir_r4/medications/medications.py` — resolver rename + widen; drop `is_antibiotic_mr` guard on identifier builder; wire the widened resolver at four sites (MR builder .id, MR builder identifiers, MA builder request.reference, discharge/outpatient Rx builder).
- `clinosim/audit/axes/clinical.py` — follow the rename (single downstream importer).
- `CHANGELOG.md` — `## [Unreleased] / ### Changed` entry documenting the MR.id shape change (MINOR bump signal).

**Created:**
- `tests/unit/output/test_fhir_medication_non_hai_opaque_id.py` — pins the widened contract (opaque .id for non-antibiotic MR, identifier[] round-trip, MA.request.reference resolution, discharge/outpatient Rx also opaque). Sibling to the existing `test_fhir_medication_opaque_id.py` (which pins the antibiotic-only case).

**Unchanged (verified by grep):**
- `clinosim/modules/output/fhir_r4/lib/ids.py` — `derive_opaque_id` / `wrap_as_identifier` / `structural_key_system` are already generic (accept any prefix / any structural_key). No signature change needed.
- `clinosim/simulator/daily_loop.py:514` — the CIF-side `sanitize_id_token(drug_name, 8)` stays put; it feeds `Order.order_id` which becomes the opaque-id input.
- `tests/unit/output/test_fhir_medication_opaque_id.py` — pins the antibiotic case; the widening means every existing assertion still holds (antibiotic MR is a special case of "MR" now). Add sibling test file rather than expanding this one.

---

## Task 1 — Widen `_resolve_antibiotic_mr_id` → `_resolve_mr_id`

**Deliverable:** The resolver returns `mr-{sha256(order_id)[:12]}` for every non-empty order_id, not just antibiotic prefixes. Rename lands together with the guard removal so import failures surface loudly.

**Files:**
- Modify: `clinosim/modules/output/fhir_r4/medications/medications.py:217-230` (`_resolve_antibiotic_mr_id` function body + docstring)
- Modify: `clinosim/modules/output/fhir_r4/medications/medications.py:675` (single internal use inside `_build_medication_request`)
- Modify: `clinosim/modules/output/fhir_r4/medications/medications.py:1225` (single internal use inside `_build_medication_admin`)
- Modify: `clinosim/audit/axes/clinical.py` (external importer — single site; grep-verify before edit)
- Test: `tests/unit/output/test_fhir_medication_non_hai_opaque_id.py` (new file — extend at each following task)

**Interfaces:**
- Consumes: nothing new (uses `derive_opaque_id` from `clinosim.modules.output.fhir_r4.lib.ids`, already imported).
- Produces: `_resolve_mr_id(order_id: str) -> str` — always returns `"mr-" + sha256(order_id).hexdigest()[:12]` for non-empty input. Rejects empty (raises `ValueError` via the underlying `derive_opaque_id` guard).

- [ ] **Step 1: Locate the audit importer to confirm scope**

Run: `grep -rn "_resolve_antibiotic_mr_id" clinosim/ tests/`
Expected: exactly 6 hits — 1 definition + 3 internal call sites in `medications.py` + 1 import in `clinosim/audit/axes/clinical.py` + 1 import in `tests/unit/output/test_fhir_medication_opaque_id.py`.
Purpose: if grep shows a hit outside these 6, the plan under-scopes the rename and needs revision.

- [ ] **Step 2: Create the new test file with the widened-resolver contract test (failing)**

Create `tests/unit/output/test_fhir_medication_non_hai_opaque_id.py`:

```python
"""Issue #853: opaque MR.id + identifier round-trip extended to all MR paths.

Sibling of tests/unit/output/test_fhir_medication_opaque_id.py (antibiotic-only,
PR #357) — this file pins the widened contract for non-HAI inpatient orders,
discharge-Rx (rxdc-), and outpatient-Rx (rxopd-) plus their MedicationAdministration
cross-references.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from clinosim.modules.output.fhir_r4.medications.medications import (
    MEDICATION_REQUEST_KEY_SYSTEM,
    _resolve_mr_id,
)

pytestmark = pytest.mark.unit

_OPAQUE_MR_ID_PATTERN = re.compile(r"^mr-[0-9a-f]{12}$")

_NON_ANTIBIOTIC_ORDER_ID = "ORD-ENC-POP-000012-351553611449-ESC-D3-Aminophy"
_INPATIENT_HM_ORDER_ID = "ORD-ENC-POP-002408-089914154887-HM-00"
_ADMISSION_ORDER_ID = "ORD-ENC-POP-002408-089914154887-ADM-S02"


def test_resolve_mr_id_returns_opaque_for_non_antibiotic_order() -> None:
    """Widened contract (Issue #853): every non-empty order_id -> opaque `mr-` id."""
    result = _resolve_mr_id(_NON_ANTIBIOTIC_ORDER_ID)
    assert _OPAQUE_MR_ID_PATTERN.match(result), f"got {result!r}"


def test_resolve_mr_id_is_deterministic() -> None:
    """Same order_id must always resolve to the same opaque id (byte-diff invariant)."""
    a = _resolve_mr_id(_NON_ANTIBIOTIC_ORDER_ID)
    b = _resolve_mr_id(_NON_ANTIBIOTIC_ORDER_ID)
    assert a == b


def test_resolve_mr_id_differs_across_orders() -> None:
    """Distinct order_ids yield distinct opaque ids (collision-avoidance smoke)."""
    a = _resolve_mr_id(_NON_ANTIBIOTIC_ORDER_ID)
    b = _resolve_mr_id(_INPATIENT_HM_ORDER_ID)
    c = _resolve_mr_id(_ADMISSION_ORDER_ID)
    assert a != b != c and a != c


def test_resolve_mr_id_still_opaque_for_antibiotic_prefix() -> None:
    """Backwards-compat: existing antibiotic prefix still gets opaque id.

    Pre-fix `_resolve_antibiotic_mr_id` returned opaque for `req-abx-` and
    passthrough for everything else. Widened `_resolve_mr_id` returns opaque
    for everything, so antibiotic behaviour is unchanged.
    """
    result = _resolve_mr_id("req-abx-hai-ENC-POP-000905-266868769799-vap-0-cft")
    assert _OPAQUE_MR_ID_PATTERN.match(result)
```

- [ ] **Step 3: Run the tests to verify they fail with an `ImportError`**

Run: `pytest tests/unit/output/test_fhir_medication_non_hai_opaque_id.py -x --tb=short`
Expected: `ImportError: cannot import name '_resolve_mr_id' from clinosim.modules.output.fhir_r4.medications.medications` (the widened name does not yet exist).

- [ ] **Step 4: Rename + widen the resolver in `medications.py`**

Replace lines 217-230 (the current `_resolve_antibiotic_mr_id` definition) with:

```python
def _resolve_mr_id(order_id: str) -> str:
    """Return the FHIR MedicationRequest.id for a CIF Order (Issue #853).

    Widened from Phase-1b's ``_resolve_antibiotic_mr_id`` (PR #357) — every
    non-empty ``Order.order_id`` now maps to the same
    ``mr-{sha256(order_id)[:12]}`` opaque shape. The compound structural key
    is preserved in ``MedicationRequest.identifier[]`` via
    :func:`_build_medication_request_identifiers` for round-trip. Cross-reference
    sites (``MedicationAdministration.request.reference``, discharge-Rx / outpatient-Rx
    builders) all go through this single helper so ``.id`` derivations stay
    byte-consistent across resources that reference the same order.

    Empty ``order_id`` raises ``ValueError`` via
    :func:`clinosim.modules.output.fhir_r4.lib.ids.derive_opaque_id`.
    """
    return derive_opaque_id("mr-", order_id)
```

- [ ] **Step 5: Update the 3 internal call sites**

Edit `clinosim/modules/output/fhir_r4/medications/medications.py:675`:
- Change `resource_id = _resolve_antibiotic_mr_id(_structural_key)` to `resource_id = _resolve_mr_id(_structural_key)`.

Edit `clinosim/modules/output/fhir_r4/medications/medications.py:1225`:
- Change `_mr_id = _resolve_antibiotic_mr_id(mar_order_id)` to `_mr_id = _resolve_mr_id(mar_order_id)`.

Edit the comment at `clinosim/modules/output/fhir_r4/medications/medications.py:1220` block — replace `_resolve_antibiotic_mr_id` with `_resolve_mr_id` in the two occurrences inside the docstring / comment there.

- [ ] **Step 6: Update the audit importer**

Read `clinosim/audit/axes/clinical.py` first to see the import shape:
Run: `grep -n "_resolve_antibiotic_mr_id" clinosim/audit/axes/clinical.py`

Then rewrite the import statement in that file to reference `_resolve_mr_id` instead. The consumer body probably calls the function with an already-known antibiotic prefix, so the widened return value is a superset of the antibiotic case — the caller keeps working with no logic change.

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `pytest tests/unit/output/test_fhir_medication_non_hai_opaque_id.py -x --tb=short`
Expected: 4 passed.

- [ ] **Step 8: Run the existing antibiotic-pinning test to verify no regression**

Run: `pytest tests/unit/output/test_fhir_medication_opaque_id.py -x --tb=short`
Expected: all existing tests pass (the file imports `_resolve_antibiotic_mr_id` — this will FAIL until Step 9).

- [ ] **Step 9: Update the existing test file to use the widened name**

Edit `tests/unit/output/test_fhir_medication_opaque_id.py`:
- Change the import at line 35 from `_resolve_antibiotic_mr_id` to `_resolve_mr_id`.
- Change every occurrence in the test bodies (`grep -n "_resolve_antibiotic_mr_id" tests/unit/output/test_fhir_medication_opaque_id.py`).

Re-run: `pytest tests/unit/output/test_fhir_medication_opaque_id.py -x --tb=short`
Expected: all previously-passing tests still pass.

- [ ] **Step 10: Broader unit-test sweep + ruff**

Run: `pytest tests/unit/ -q`
Expected: all pass (typically ~4400 tests as of 2026-08-25 master).

Run: `ruff check clinosim/ tests/` and `ruff format --check clinosim/ tests/`
Expected: `All checks passed`, `... files already formatted`.

Run: `grep -rn "_resolve_antibiotic_mr_id" clinosim/ tests/`
Expected: 0 hits (the old name is fully retired).

- [ ] **Step 11: Commit**

```bash
git checkout -b fix/853-non-hai-mr-opaque-id
git add clinosim/modules/output/fhir_r4/medications/medications.py \
        clinosim/audit/axes/clinical.py \
        tests/unit/output/test_fhir_medication_opaque_id.py \
        tests/unit/output/test_fhir_medication_non_hai_opaque_id.py
git commit -s -m "refactor(fhir-emit): widen _resolve_antibiotic_mr_id → _resolve_mr_id (Issue #853, step 1/N)"
```

---

## Task 2 — Widen `_build_medication_request_identifiers` to unconditionally round-trip the structural key

**Deliverable:** Every MR resource emits an `identifier[]` entry under `MEDICATION_REQUEST_KEY_SYSTEM` carrying the original `Order.order_id`. Prior to this task, only `is_antibiotic_mr=True` callers got that entry (PR #357 scope).

**Files:**
- Modify: `clinosim/modules/output/fhir_r4/medications/medications.py:255-295` (the `_build_medication_request_identifiers` function — drop the `if is_antibiotic_mr:` guard around `wrap_as_identifier`).
- Modify: `clinosim/modules/output/fhir_r4/medications/medications.py:674` (drop the `_is_antibiotic_mr = _structural_key.startswith(...)` local — no longer used).
- Modify: `clinosim/modules/output/fhir_r4/medications/medications.py:743-748` (the `_build_medication_request_identifiers(...)` call — drop the `_is_antibiotic_mr` positional argument).
- Modify: `clinosim/modules/output/fhir_r4/medications/medications.py:930-948` (the discharge-Rx / outpatient-Rx builder's `_build_medication_request_identifiers(...)` call — change `False` to be dropped along with the parameter).
- Test: `tests/unit/output/test_fhir_medication_non_hai_opaque_id.py` (extend).

**Interfaces:**
- Consumes: `_resolve_mr_id` (Task 1) — indirectly, via the structural_key passed by callers.
- Produces: `_build_medication_request_identifiers(structural_key: str, country_code: str, rp_number: str, order_in_rp: str) -> dict[str, list[dict[str, str]]]` (dropped the `is_antibiotic_mr: bool` parameter — signature shrinks by one).

- [ ] **Step 1: Add the identifier[] round-trip test (failing)**

Append to `tests/unit/output/test_fhir_medication_non_hai_opaque_id.py`:

```python
from clinosim.modules.output.fhir_r4.medications.medications import (
    _build_medication_request,
)


def _non_hai_order(order_id: str = _NON_ANTIBIOTIC_ORDER_ID) -> dict[str, Any]:
    """Minimal Order fixture that exercises the non-HAI MR emit path."""
    return {
        "order_id": order_id,
        "encounter_id": "ENC-POP-000012-351553611449",
        "patient_id": "POP-000012",
        "order_type": "medication",
        "order_code": "",
        "display_name": "Aminophylline 250mg IV q6h",
        "urgency": "routine",
        "clinical_intent": "Escalation day 3: Aminophylline (no improvement)",
        "ordered_datetime": "2026-02-14T10:00:00",
        "ordered_by": "DR-IM-005",
        "status": "placed",
        "dose_quantity": 250.0,
        "dose_unit": "mg",
        "frequency": "Q6H",
        "route": "IV",
    }


def test_non_hai_mr_id_is_opaque() -> None:
    """The full MR emit path (not just the resolver) produces the opaque id."""
    resource = _build_medication_request(_non_hai_order(), country="JP")
    assert _OPAQUE_MR_ID_PATTERN.match(resource["id"]), f"got {resource['id']!r}"


def test_non_hai_mr_identifier_round_trip() -> None:
    """Non-HAI MR carries the structural key in identifier[] under the canonical URI."""
    resource = _build_medication_request(_non_hai_order(), country="JP")
    idents = resource.get("identifier") or []
    structural = [i for i in idents if i.get("system") == MEDICATION_REQUEST_KEY_SYSTEM]
    assert len(structural) == 1, f"expected exactly 1 structural-key ident, got {structural!r}"
    assert structural[0]["value"] == _NON_ANTIBIOTIC_ORDER_ID


def test_non_hai_mr_identifier_coexists_with_jp_core_rp_slices() -> None:
    """JP Core rpNumber + orderInRp slices must still land alongside the structural key."""
    resource = _build_medication_request(_non_hai_order(), country="JP")
    idents = resource.get("identifier") or []
    systems = [i.get("system") for i in idents]
    assert MEDICATION_REQUEST_KEY_SYSTEM in systems
    assert "http://jpfhir.jp/fhir/core/mhlw/IdSystem/Medication-RPGroupNumber" in systems
    assert "http://jpfhir.jp/fhir/core/mhlw/IdSystem/MedicationAdministrationIndex" in systems
```

Note on the fixture: the actual `_build_medication_request` signature may require additional arguments (patient, encounter, etc.). Before running the failing test, verify the signature with `grep -n "^def _build_medication_request" clinosim/modules/output/fhir_r4/medications/medications.py` and extend the fixture / call to match. Do NOT invent unrelated positional args — read the function body for defaults and mirror what `tests/unit/output/test_fhir_medication_opaque_id.py::_abx_order` uses.

- [ ] **Step 2: Run tests, expect failure**

Run: `pytest tests/unit/output/test_fhir_medication_non_hai_opaque_id.py::test_non_hai_mr_identifier_round_trip -x --tb=short`
Expected: FAIL — no structural-key entry in `identifier[]` for non-antibiotic MR (the `is_antibiotic_mr` guard still gates it out).

- [ ] **Step 3: Drop the `is_antibiotic_mr` guard in the identifier builder**

Edit `_build_medication_request_identifiers` at `clinosim/modules/output/fhir_r4/medications/medications.py:255-295`:

1. Drop the `is_antibiotic_mr: bool` parameter from the signature.
2. Replace the current guarded block:
```python
entries: list[dict[str, str]] = []
if is_antibiotic_mr:
    entries.append(wrap_as_identifier(structural_key, MEDICATION_REQUEST_KEY_SYSTEM))
```
with the unconditional version:
```python
entries: list[dict[str, str]] = [
    wrap_as_identifier(structural_key, MEDICATION_REQUEST_KEY_SYSTEM),
]
```
3. Update the docstring: replace the "Antibiotic MR (Issue #349 Phase 1b): the structural key preserved..." bullet with a widened form documenting that every MR (Issue #853) carries the round-trip.

- [ ] **Step 4: Drop the `_is_antibiotic_mr` local + update the caller argument in inpatient MR builder**

Edit `_build_medication_request` around lines 673-748:
- Line 674: delete `_is_antibiotic_mr = _structural_key.startswith(ABX_ORDER_ID_PREFIX)` entirely.
- Lines 743-748 (the `_build_medication_request_identifiers(...)` call): remove the `_is_antibiotic_mr` positional argument.
- Check whether `_is_antibiotic_mr` is used anywhere else in the function body (grep the local file after edit) — if the STOP-order gate or the meta.tag emission depends on it, keep a local `_is_antibiotic_mr` derivation for those but stop passing it to the identifier builder.

- [ ] **Step 5: Same treatment on discharge-Rx / outpatient-Rx builder**

Edit the `_build_medication_request_identifiers(resource_id, False, country_code, "1", str(seq))` call at `clinosim/modules/output/fhir_r4/medications/medications.py:930-940`:
- Drop the `False` positional (matches the parameter removal in Step 3).

Note: this builder passes `resource_id` (the discharge-Rx / outpatient-Rx opaque-shape id, e.g. `rxdc-ENC-POP-000058-...-01`) as the structural_key. After Task 3 (below) `resource_id` at this call site will change shape — this task only shrinks the signature; Task 3 wires the resolver in.

- [ ] **Step 6: Re-run the failing test**

Run: `pytest tests/unit/output/test_fhir_medication_non_hai_opaque_id.py -x --tb=short`
Expected: `test_non_hai_mr_identifier_round_trip` + `test_non_hai_mr_identifier_coexists_with_jp_core_rp_slices` now pass.

- [ ] **Step 7: Broader unit + ruff**

Run: `pytest tests/unit/ -q && ruff check clinosim/ tests/ && ruff format --check clinosim/ tests/`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add clinosim/modules/output/fhir_r4/medications/medications.py \
        tests/unit/output/test_fhir_medication_non_hai_opaque_id.py
git commit -s -m "refactor(fhir-emit): unconditional structural-key identifier round-trip on MR (Issue #853, step 2/N)"
```

---

## Task 3 — MA cross-reference resolves through the widened resolver

**Deliverable:** Every `MedicationAdministration.request.reference` field consumes the same `_resolve_mr_id(mar_order_id)` derivation, so MR.id and MA.request.reference stay byte-consistent by construction. This was already true for the antibiotic case (PR #357); this task extends it to non-HAI MAs.

**Files:**
- Modify: `clinosim/modules/output/fhir_r4/medications/medications.py:1215-1235` (the MA cross-ref block that currently only opaque-resolves antibiotic MARs).
- Test: `tests/unit/output/test_fhir_medication_non_hai_opaque_id.py` (extend).

**Interfaces:**
- Consumes: `_resolve_mr_id` (from Task 1).
- Produces: No new symbol — post-fix `_build_medication_admin` uses the widened resolver unconditionally for `.request.reference`.

- [ ] **Step 1: Read the current MA cross-ref block**

Run: `sed -n '1215,1235p' clinosim/modules/output/fhir_r4/medications/medications.py`
Confirm the block currently guards the opaque resolution on antibiotic prefix (or similar). The exact guard shape drives the edit in Step 3.

- [ ] **Step 2: Add the MA request.reference resolution test (failing)**

Append to `tests/unit/output/test_fhir_medication_non_hai_opaque_id.py`:

```python
from clinosim.modules.output.fhir_r4.medications.medications import (
    _build_medication_admin,
)


def test_non_hai_ma_request_reference_uses_opaque_mr_id() -> None:
    """MA.request.reference must resolve to the SAME opaque MR.id the MR builder produces
    for the same Order (byte-consistent cross-reference).
    """
    order = _non_hai_order()
    mr = _build_medication_request(order, country="JP")

    mar = {
        "order_id": order["order_id"],
        "drug_name": order["display_name"],
        "scheduled_datetime": "2026-02-14T10:00:00",
        "actual_datetime": "2026-02-14T10:00:00",
        "status": "given",
        "dose": "250mg Q6H",
        "route": "IV",
        "administered_by": "NS-IM-001",
    }
    ma = _build_medication_admin(
        mar, patient_id="POP-000012", index=0, country="JP", encounter_id="ENC-POP-000012-351553611449"
    )
    assert ma["request"]["reference"] == f"MedicationRequest/{mr['id']}"
```

- [ ] **Step 3: Run, expect failure**

Run: `pytest tests/unit/output/test_fhir_medication_non_hai_opaque_id.py::test_non_hai_ma_request_reference_uses_opaque_mr_id -x --tb=short`
Expected: FAIL — MA.request.reference contains the un-opaque `ORD-ENC-POP-...` order id, not `mr-<12hex>`.

- [ ] **Step 4: Drop the guard in MA builder**

Edit `clinosim/modules/output/fhir_r4/medications/medications.py:1215-1235`:

Whatever guard currently reads `if mar_order_id.startswith(ABX_ORDER_ID_PREFIX):` (or an equivalent), replace it with an unconditional `_mr_id = _resolve_mr_id(mar_order_id)` for every MAR. Consequence: `MedicationAdministration.request.reference` becomes `"MedicationRequest/mr-<12hex>"` for every MA that has a parent MR.

Update the surrounding comment/docstring to point at Issue #853 (the widening) alongside the existing Issue #349 Phase 1b (PR #357) reference.

- [ ] **Step 5: Re-run the test**

Run: `pytest tests/unit/output/test_fhir_medication_non_hai_opaque_id.py::test_non_hai_ma_request_reference_uses_opaque_mr_id -x --tb=short`
Expected: PASS.

- [ ] **Step 6: Broader unit-test sweep**

Run: `pytest tests/unit/output/ -q`
Expected: all pass. If any legacy test asserts `MedicationAdministration.request.reference == "MedicationRequest/ORD-..."` for a non-antibiotic case, update it to assert the opaque shape — see Task 5 for the plausible list of affected tests.

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/output/fhir_r4/medications/medications.py \
        tests/unit/output/test_fhir_medication_non_hai_opaque_id.py
git commit -s -m "refactor(fhir-emit): MA.request.reference resolves via widened _resolve_mr_id (Issue #853, step 3/N)"
```

---

## Task 4 — Discharge-Rx / outpatient-Rx builder emits opaque id via resolver

**Deliverable:** `rxdc-ENC-POP-...-NN` and `rxopd-ENC-POP-...-NN` MR.id shapes go away. Both prefixes get their own opaque form (`rxdc-{sha256(structural_key)[:12]}` / `rxopd-{sha256(structural_key)[:12]}`) using the same `derive_opaque_id` foundation. The `identifier[]` round-trip already lands from Task 2.

**Files:**
- Modify: `clinosim/modules/output/fhir_r4/medications/medications.py:937-948` (`_build_discharge_rx_medication_request` — the `resource_id = f"{prefix}{encounter_id}-{seq:02d}"` construction).
- Add: `_resolve_dc_rx_id(structural_key: str) -> str` and `_resolve_opd_rx_id(structural_key: str) -> str` helpers next to `_resolve_mr_id` at `clinosim/modules/output/fhir_r4/medications/medications.py:217`.
- Test: `tests/unit/output/test_fhir_medication_non_hai_opaque_id.py` (extend).

**Interfaces:**
- Consumes: `derive_opaque_id` (existing foundation).
- Produces: `_resolve_dc_rx_id(structural_key: str) -> str` returning `"rxdc-" + sha256(structural_key)[:12]`; `_resolve_opd_rx_id(structural_key: str) -> str` returning `"rxopd-" + sha256(structural_key)[:12]`. Distinct prefixes so a consumer can tell a take-home script written at inpatient discharge from an outpatient chronic renewal (unchanged from Issue #445's original intent).

- [ ] **Step 1: Add tests (failing)**

Append to `tests/unit/output/test_fhir_medication_non_hai_opaque_id.py`:

```python
from clinosim.modules.output.fhir_r4.medications.medications import (
    _resolve_dc_rx_id,
    _resolve_opd_rx_id,
)

_OPAQUE_DC_RX_PATTERN = re.compile(r"^rxdc-[0-9a-f]{12}$")
_OPAQUE_OPD_RX_PATTERN = re.compile(r"^rxopd-[0-9a-f]{12}$")


def test_resolve_dc_rx_id_returns_opaque() -> None:
    """Discharge-Rx opaque id has `rxdc-` prefix + 12-hex digest."""
    result = _resolve_dc_rx_id("ENC-POP-000058-281217974268-01")
    assert _OPAQUE_DC_RX_PATTERN.match(result), f"got {result!r}"


def test_resolve_opd_rx_id_returns_opaque() -> None:
    """Outpatient-Rx opaque id has `rxopd-` prefix + 12-hex digest."""
    result = _resolve_opd_rx_id("ENC-POP-000058-281217974268-01")
    assert _OPAQUE_OPD_RX_PATTERN.match(result), f"got {result!r}"


def test_dc_rx_and_opd_rx_ids_differ_for_same_structural_key() -> None:
    """The prefix distinguishes discharge-Rx from outpatient-Rx even for identical structural keys.

    Consumers rely on this distinction (Issue #445 intent).
    """
    a = _resolve_dc_rx_id("ENC-POP-000058-281217974268-01")
    b = _resolve_opd_rx_id("ENC-POP-000058-281217974268-01")
    assert a != b
```

- [ ] **Step 2: Run tests, expect failure**

Run: `pytest tests/unit/output/test_fhir_medication_non_hai_opaque_id.py -k "dc_rx or opd_rx" -x --tb=short`
Expected: FAIL with `ImportError` (helpers do not yet exist).

- [ ] **Step 3: Add the two helpers**

Insert into `clinosim/modules/output/fhir_r4/medications/medications.py` immediately after `_resolve_mr_id` (from Task 1):

```python
def _resolve_dc_rx_id(structural_key: str) -> str:
    """Return the FHIR MedicationRequest.id for a discharge-Rx entry (Issue #853).

    Shape: ``rxdc-{sha256(structural_key)[:12]}``. The 6-char prefix keeps a
    take-home script written at inpatient discharge distinguishable from an
    outpatient chronic renewal (Issue #445 intent) even after both ids become
    opaque under Issue #853.
    """
    return derive_opaque_id(DISCHARGE_RX_ID_PREFIX, structural_key)


def _resolve_opd_rx_id(structural_key: str) -> str:
    """Return the FHIR MedicationRequest.id for an outpatient-Rx entry (Issue #853).

    Shape: ``rxopd-{sha256(structural_key)[:12]}``. Companion to
    :func:`_resolve_dc_rx_id` — see Issue #445 for why the two prefixes stay
    distinguishable.
    """
    return derive_opaque_id(OUTPATIENT_RX_ID_PREFIX, structural_key)
```

- [ ] **Step 4: Wire the discharge-Rx / outpatient-Rx builder**

Edit `clinosim/modules/output/fhir_r4/medications/medications.py:937-940`:

Replace:
```python
prefix = DISCHARGE_RX_ID_PREFIX if encounter_type == "inpatient" else OUTPATIENT_RX_ID_PREFIX
resource_id = f"{prefix}{encounter_id}-{seq:02d}"
```
with:
```python
# Issue #853: opaque id. Structural key = same compound the pre-#853 id
# encoded (`{encounter_id}-{seq:02d}`) so downstream consumers can recover
# it from identifier[] (Task 2). Prefix retained so a discharge script and
# an outpatient renewal stay visually distinguishable in the URL.
_structural_key = f"{encounter_id}-{seq:02d}"
resolve = _resolve_dc_rx_id if encounter_type == "inpatient" else _resolve_opd_rx_id
resource_id = resolve(_structural_key)
```

The subsequent `"id": resource_id,` line at ~945 stays unchanged (it now sees the opaque value). The `_build_medication_request_identifiers(resource_id, country_code, "1", str(seq))` call also stays unchanged — but the structural_key it round-trips is now the opaque id, not the compound.

**Correctness gotcha**: the structural key we want in `identifier[]` is the ORIGINAL compound (`ENC-POP-...-01`), not the opaque digest. Pass `_structural_key` (the compound), not `resource_id` (the opaque), to `_build_medication_request_identifiers`. Update the call arg accordingly.

- [ ] **Step 5: Re-run tests**

Run: `pytest tests/unit/output/test_fhir_medication_non_hai_opaque_id.py -x --tb=short`
Expected: all pass.

- [ ] **Step 6: Broader sweep**

Run: `pytest tests/unit/ -q && pytest tests/integration/ -q`
Expected: all pass. If a legacy discharge-Rx test asserts `.id == "rxdc-ENC-POP-..."` literal, update it to match the opaque shape.

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/output/fhir_r4/medications/medications.py \
        tests/unit/output/test_fhir_medication_non_hai_opaque_id.py
git commit -s -m "refactor(fhir-emit): discharge-Rx + outpatient-Rx MR.id opaque via _resolve_*_rx_id (Issue #853, step 4/N)"
```

---

## Task 5 — P=200 seed=500 sim-and-verify + fix breakages surfaced

**Deliverable:** A full local sim + FHIR emit at P=200 seed=500 produces a working NDJSON set where every `MedicationRequest.id`, `MedicationAdministration.request.reference`, and identifier[] round-trip is consistent under Task-1-to-4 changes. Any test failure surfaced by the sim / integration sweep gets fixed before push.

**Files:**
- No new files. This is a run-and-verify task that may add small fixes to legacy tests or emit sites depending on what the sim surfaces.

**Interfaces:** No new signatures.

- [ ] **Step 1: Regenerate scratchpad sim + FHIR**

```bash
mkdir -p scratchpad/p200_verify_853
clinosim simulate -p 200 -s 500 --country JP --format cif fhir-r4 -o scratchpad/p200_verify_853
```
Expected: exits 0 in ~15-30 s. `scratchpad/p200_verify_853/fhir_r4/MedicationRequest.ndjson` and `.../MedicationAdministration.ndjson` exist.

- [ ] **Step 2: Verify #853 invariants on the fresh output**

Run:
```bash
D=scratchpad/p200_verify_853/fhir_r4

# All MR.id must match one of the three opaque shapes
python3 - <<'PY'
import json, re, sys
opaque_patterns = [re.compile(r"^mr-[0-9a-f]{12}$"),
                   re.compile(r"^rxdc-[0-9a-f]{12}$"),
                   re.compile(r"^rxopd-[0-9a-f]{12}$")]
n = 0
bad = []
with open("scratchpad/p200_verify_853/fhir_r4/MedicationRequest.ndjson") as f:
    for line in f:
        n += 1
        rid = json.loads(line)["id"]
        if not any(p.match(rid) for p in opaque_patterns):
            bad.append(rid)
print(f"MR total {n}, non-opaque {len(bad)}")
for r in bad[:5]:
    print(f"  BAD: {r}")
sys.exit(0 if not bad else 1)
PY

# Every MR must carry the MEDICATION_REQUEST_KEY_SYSTEM identifier round-trip
python3 - <<'PY'
import json
n = 0; missing = 0
KEY = "urn:clinosim:identifier:medication-request-key"
with open("scratchpad/p200_verify_853/fhir_r4/MedicationRequest.ndjson") as f:
    for line in f:
        n += 1
        r = json.loads(line)
        idents = r.get("identifier") or []
        if not any(i.get("system") == KEY for i in idents):
            missing += 1
print(f"MR total {n}, missing structural-key identifier {missing}")
PY

# Every MA.request.reference must resolve to an MR that actually exists in the emit set
python3 - <<'PY'
import json
mr_ids = set()
with open("scratchpad/p200_verify_853/fhir_r4/MedicationRequest.ndjson") as f:
    for line in f:
        mr_ids.add(json.loads(line)["id"])
n = 0; dangling = 0
with open("scratchpad/p200_verify_853/fhir_r4/MedicationAdministration.ndjson") as f:
    for line in f:
        n += 1
        ref = (json.loads(line).get("request") or {}).get("reference", "")
        rid = ref.replace("MedicationRequest/", "")
        if rid and rid not in mr_ids:
            dangling += 1
print(f"MA total {n}, dangling request.reference {dangling}")
PY

# PR #356 gate: no id exceeds 64 chars
python3 - <<'PY'
import json
for name in ("MedicationRequest.ndjson", "MedicationAdministration.ndjson"):
    over = 0
    with open(f"scratchpad/p200_verify_853/fhir_r4/{name}") as f:
        for line in f:
            rid = json.loads(line).get("id", "")
            if len(rid) > 64:
                over += 1
    print(f"{name}: >64-char ids = {over}")
PY
```
Expected: MR non-opaque = 0, MR missing structural-key ident = 0, MA dangling request.reference = 0, no id > 64 chars.

- [ ] **Step 3: Fix breakages surfaced by the invariant script**

If any of the four expected-0 counts is > 0, read the offending record with `jq`, locate the emit site (grep for the id prefix or the field that failed), and produce a minimal fix. Do NOT patch the NDJSON in place (memory `feedback_fhir_emit_bug_no_direct_patch.md`) — fix the emit code and rerun Step 1.

- [ ] **Step 4: Full unit + integration sweep on the branch**

```bash
pytest tests/unit/ -q
pytest tests/integration/ -q
```
Expected: all pass. If any integration test asserts a compound-shape MR.id (e.g. `ORD-ENC-POP-...-ESC-D3-Aminophy` literal), update the assertion to compute the opaque form via `_resolve_mr_id` — do not hardcode the digest since it is derived and would go stale on any prefix change.

- [ ] **Step 5: Commit any test / emit fixups from Steps 3-4**

```bash
git add -u
git commit -s -m "test(fhir-emit): update fixtures for opaque MR.id (Issue #853, step 5/N)"
```

---

## Task 6 — CHANGELOG entry + PR

**Deliverable:** The refactor lands in a single squashed PR with a `## [Unreleased] / ### Changed` entry documenting the MR.id shape change (MINOR-bumpable signal).

**Files:**
- Modify: `CHANGELOG.md` — insert the new entry under `## [Unreleased]`, above the existing `### Fixed` section, in a new `### Changed` subsection (create it if it does not yet exist).

**Interfaces:** No code changes in this task.

- [ ] **Step 1: Draft the CHANGELOG entry**

Insert:

```markdown
### Changed

- **`MedicationRequest.id` is now opaque for every code path** (Issue #853). Extends PR #357's Phase-1b antibiotic-MR pattern (`mr-{sha256(order_id)[:12]}` + `identifier[]` round-trip) to non-HAI inpatient MRs (~108k in the JP p=10000 s500 sample), discharge-Rx (`rxdc-{sha256}` — was `rxdc-ENC-POP-...-NN`), and outpatient-Rx (`rxopd-{sha256}` — was `rxopd-ENC-POP-...-NN`). `MedicationAdministration.request.reference` (359k in the sample) resolves through the same widened `_resolve_mr_id` derivation so cross-references stay byte-consistent by construction. Visible surface effects: (a) the 8-char drug-slug truncation (`-Aminophy` / `-Meropene` / `-Ampicill` / etc., 576 records in the ESC-D*-\*/STOP-D*-\* codepath) no longer appears in `MedicationRequest.id` — the compound Order.order_id is preserved in `identifier[]` under `urn:clinosim:identifier:medication-request-key`; (b) `Resource.id` length drops from up to 50 chars to a fixed 15 (mr / rxdc) or 18 (rxopd), giving 46–49 chars of headroom under FHIR R4's 64-char cap; (c) patient identifier no longer leaks into every `MedicationRequest` / `MedicationAdministration` URL. Byte output changes across the MR and MA NDJSON — MINOR-bumpable at next release. `sanitize_id_token(drug_name, 8)` at `clinosim/simulator/daily_loop.py:514` (the CIF-side source of the truncation) is intentionally NOT touched — CIF Order.order_id retains the compound shape as the structural-key input to `derive_opaque_id`.
```

- [ ] **Step 2: Ruff format + push**

```bash
ruff check clinosim/ tests/
ruff format --check clinosim/ tests/
git add CHANGELOG.md
git commit -s -m "docs(changelog): #853 non-HAI MR opaque id + MA cross-ref (step 6/N)"
git push -u origin fix/853-non-hai-mr-opaque-id
```

- [ ] **Step 3: Open the PR**

```bash
gh pr create --title "refactor(fhir-emit): non-HAI MedicationRequest opaque id + MA cross-ref (Issue #853)" --body "$(cat <<'EOF'
## Summary

Extends PR #357's Phase-1b HAI antibiotic MR pattern (`mr-{sha256(order_id)[:12]}` + `identifier[]` round-trip + shared resolver) to **every** `MedicationRequest` emit path — non-HAI inpatient orders, discharge-Rx (`rxdc-`), and outpatient-Rx (`rxopd-`) — plus their `MedicationAdministration.request.reference` cross-references. Closes Issue #853; unblocks per-resource-type follow-ups on Issue #854 Bucket A (ServiceRequest / Observation / DeviceUseStatement / Procedure / Device).

## Changes

- **Widened resolver**: `_resolve_antibiotic_mr_id` → `_resolve_mr_id` (drops the `startswith(ABX_ORDER_ID_PREFIX)` guard so all order_ids resolve to `mr-<12hex>`). Follows the rename through the single downstream importer (`clinosim/audit/axes/clinical.py`) and 3 internal call sites.
- **Unconditional identifier[] round-trip**: `_build_medication_request_identifiers` no longer takes the `is_antibiotic_mr: bool` parameter — every MR carries the structural key under `urn:clinosim:identifier:medication-request-key`.
- **Discharge-Rx / outpatient-Rx opaque**: two new helpers `_resolve_dc_rx_id` / `_resolve_opd_rx_id` produce `rxdc-<12hex>` / `rxopd-<12hex>` (was `rxdc-ENC-POP-...-NN` / `rxopd-ENC-POP-...-NN`). Distinct prefixes retained per Issue #445 intent.
- **MA cross-ref**: `MedicationAdministration.request.reference` now uses `_resolve_mr_id(mar_order_id)` unconditionally so MR.id and MA.request.reference stay byte-consistent by construction for every drug family.

## Verification

- Full local unit sweep + integration sweep (`pytest tests/`).
- P=200 seed=500 sim + emit: all MR.id match the 3 opaque shapes, all MR carry the structural-key identifier, 0 dangling MA.request.reference, 0 ids > 64 chars.
- `ruff check` + `ruff format --check` clean.

## Test plan

- [x] Local `pytest tests/unit/output/test_fhir_medication_non_hai_opaque_id.py` — new sibling test file, 10+ cases (opaque .id / identifier[] round-trip / MA cross-ref / discharge-Rx / outpatient-Rx / dc-vs-opd distinction).
- [x] Local `pytest tests/unit/output/test_fhir_medication_opaque_id.py` — antibiotic-only cases still pass with the widened name.
- [x] Local `pytest tests/unit/` + `tests/integration/` — full sweep green.
- [x] P=200 seed=500 sim + FHIR emit + 4-invariant script all clean.
- [ ] CI: Unit + Integration + ruff-dead-code + DCO + build + mkdocs.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Closes #853.
EOF
)"
```

- [ ] **Step 4: iris4h-ai deploy refresh (post-merge only)**

Do NOT run this task before the PR is merged to master — it publishes the change to the shared deploy.

After merge:
```bash
git checkout master && git pull --ff-only origin master
mkdir -p scratchpad/p10000_regen_853
clinosim export-fhir \
  --cif-dir scratchpad_review_vllm-fp8-p10000-s500-n3/cif \
  --output scratchpad/p10000_regen_853/fhir_r4 \
  --country JP \
  --narrative-version vllm-fp8-p10000-s500
# Verify (repeat Task 5 Step 2 invariants against the P=10000 output)
# Then rsync
rsync -a --delete --exclude='backups' \
  scratchpad/p10000_regen_853/fhir_r4/ \
  ~/workspace/iris4h-ai/fhir_r4/
```

---

## Appendix A — Issue #854 recipe for Bucket A resource types

Once #853 lands, the exact same pattern applies to the remaining 5 Bucket A resource types (max id > 50 chars per Issue #854). Each becomes its own PR — do NOT batch them, because the shared-resolver contract for each resource type has its own set of cross-referencing readers that must be checked one at a time.

Per-type template (fill in the 5 bracketed slots, then follow the same 6 task shapes as #853):

| Slot | ServiceRequest | Observation | DeviceUseStatement | Procedure | Device |
|---|---|---|---|---|---|
| Resource kind | ServiceRequest | Observation | DeviceUseStatement | Procedure | Device |
| Sample current id | `sr-ORD-ENC-POP-000012-351553611449-MOD-D3-ABG-HCO3` | `vs-ENC-POP-000002-344642685226-0000-respiratory-rate` | `dus-dev-ENC-POP-000297-444117387516-mechanical-ventilator-2` | `proc-order-ORD-ENC-POP-000321-579224764599-DEV-D2-NIV-BiPA` | `dev-ENC-POP-000297-444117387516-mechanical-ventilator-2` |
| Current max chars | 53 | 55 | 59 | 58 | 55 |
| Volume | 274,806 | **1,580,109** | 98 | 3,011 | 99 |
| Opaque prefix | `sr-` | `obs-` | `dus-` | `proc-` | `dev-` |
| identifier[] system slug | `service-request-key` | `observation-key` | `device-use-statement-key` | `procedure-key` | `device-key` |
| Resolver name | `_resolve_service_request_id` | `_resolve_observation_id` | `_resolve_device_use_statement_id` | `_resolve_procedure_id` | `_resolve_device_id` |
| Emit-site file (grep starting point) | `clinosim/modules/output/fhir_r4/service_request*.py` / `labs/` subtree | `clinosim/modules/output/fhir_r4/observation*.py` | `clinosim/modules/output/fhir_r4/device*.py` | `clinosim/modules/output/fhir_r4/procedure*.py` | `clinosim/modules/output/fhir_r4/device*.py` |
| Cross-refs to update (from Issue #854) | `DiagnosticReport.basedOn[]`, `Observation.basedOn[]`, `ServiceRequest.basedOn[]` (order → sub-order) | `DiagnosticReport.result[]`, `Composition.section.entry[]` | `DeviceUseStatement.device` → `Device.id` (needs both PRs before the deploy) | `Procedure.reasonReference[]` → `Condition.id` (Bucket B), plus emit code that reads MR-id (already opaque post-#853) | `Device.location` → `Location.id` (unchanged), `DeviceUseStatement.device` (see previous row) |

**Volume-based sequencing recommendation:**

1. **DeviceUseStatement + Device together** (Bucket A rows 3 & 5). Only 98 + 99 records but they cross-reference each other — do them in a single stacked pair of PRs. Highest raw id length so biggest headroom win.
2. **Procedure** (Bucket A row 4). 3,011 records, self-contained cross-refs into Condition (Bucket B — that migration is separate).
3. **ServiceRequest** (Bucket A row 1). 274,806 records. Highest volume among the "moderate-count" tier. Cross-refs cascade into DiagnosticReport / Observation basedOn[], so post-merge those two resources briefly carry mismatched-shape references until the next per-type PR lands. Document this in the PR body and land the Observation + DiagnosticReport refactors close together (or add a temporary shim in the reader-side gate — do this only if the mismatched window would be user-visible in some intermediate deploy).
4. **Observation** (Bucket A row 2). **1.58 M records** — highest volume in the tree. Estimated wall-clock impact of the emit change: ~50-100 MB reduction in the Observation NDJSON. Land this last in Bucket A so all upstream cross-refs (DiagnosticReport.result[], Composition.section.entry[]) already point at opaque shapes.

Each Bucket A PR duplicates the 6-task shape from #853 above with the slot values from the table. Do not attempt to abstract the resolver into a generic factory — the small copy-paste keeps the change surface reviewable, and PR #357's contract explicitly favors per-resource explicitness over a generic factory (foundation module notes on `derive_opaque_id`).

## Appendix B — Bucket B and C deferrals

Issue #854 lists 10 additional Bucket B resource types (max id 33-43 chars) and 5 Bucket C types (patient-scoped, no encounter number). These are lower priority — same anti-pattern, but the 64-char-gate headroom is much larger. They get their own plan doc when scheduled. Include the Bucket B / C rows from Issue #854 verbatim as the source of truth for that future plan.

`Patient.id` itself (Bucket C, 10 chars, `POP-000002`) is arguably the root of the leak — every other resource id inherits `POP-{patient}` from it. Migrating `Patient.id` is a separate call because it is the outermost external identifier and probably has downstream consumers of its own. Note this in whatever future plan touches Bucket C so the discussion happens before the migration, not during.
