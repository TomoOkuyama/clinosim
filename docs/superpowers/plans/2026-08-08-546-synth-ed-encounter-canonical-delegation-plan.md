# synth-ED Encounter Canonical Delegation — Implementation Plan (Issue #546)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delegate the synthesised ED partOf Encounter emission in `clinosim/modules/output/fhir_r4/lib/inline_bb.py::_bb_encounters` to the single canonical `_build_encounter` builder, eliminating the 90-LOC parallel emitter and the `_SYNTH_ED_DISPLAYS` bespoke display table.

**Architecture:** Introduce one local helper `_make_synth_ed_enc_dict(ctx, imp_enc, partof_id) -> dict` that constructs a minimal CIF-shape enc dict; `_bb_encounters` feeds it to `_build_encounter(synth_enc, ctx.patient_id, country=ctx.country)` and applies one post-hoc `pop("dischargeDisposition", None)` on the returned resource. Delete the old `_SYNTH_ED_DISPLAYS` table, its `_synth_ed_display` helper, the 90-LOC inline synthesis block, and the session-84 lock-in test file that guards their existence.

**Tech Stack:** Python 3.12, pytest, ruff==0.16.0 (CI-pinned), mypy strict, `clinosim` FHIR R4 emit path.

## Global Constraints

- Session 86 branch discipline: never commit directly to `master`; work on branch `fix/546-synth-ed-canonical-delegation` off current `origin/master`.
- ruff version: install `ruff==0.16.0` (CI-pinned) before any lint step; local `ruff` may produce different `format` output.
- Signed-off commits required: every `git commit` must include `--signoff` (DCO gate).
- Byte-diff neutrality is NOT a global constraint — this refactor produces documented shifts on synth-ED bridge Encounters only. Non-Encounter resources MUST remain byte-identical vs baseline; this is a per-verification gate.
- Base ref for byte-diff comparisons: **current `origin/master` at branch cut time** (record the exact commit SHA in the PR body — this becomes the fingerprint baseline). Do NOT reuse the stale spec SHA `f9c774b4515`.
- JP cohort env var (required for JP validation runs): `CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package'`
- Sub-project spec: `docs/superpowers/specs/2026-08-08-546-synth-ed-encounter-canonical-delegation-design.md` — authoritative for every design decision (DD1-DD4). Any deviation blocks merge.

---

## File Structure

**Files created:**

| Path | Responsibility |
|---|---|
| `tests/unit/output/test_fhir_synth_ed_encounter_delegation.py` | 5 regression tests that lock the canonical-delegation behaviour (replaces the session-84 lock-in file) |

**Files modified:**

| Path | Change |
|---|---|
| `clinosim/modules/output/fhir_r4/lib/inline_bb.py` | Delete `_SYNTH_ED_DISPLAYS` (L185-214), `_synth_ed_display()` (L217-220), and the 90-LOC inline synthesis block (L283-378). Add `_make_synth_ed_enc_dict()`. Update `_bb_encounters` synth-ED branch to delegate + post-hoc pop. |

**Files deleted:**

| Path | Reason |
|---|---|
| `tests/unit/output/test_synth_ed_display_constants.py` | Locks `_SYNTH_ED_DISPLAYS` + `_synth_ed_display` (both removed). Its AST guard against bare `救急外来 / 緊急 / 外来より / 入院となる` literals in `inline_bb.py` becomes moot once those literals are gone from the file. |

**Files NOT modified:**

- `clinosim/modules/output/fhir_r4/encounters/encounter.py::_build_encounter` — canonical builder, unchanged.
- `clinosim/codes/data/hl7-admit-source.yaml`, `hl7-discharge-disposition.yaml` — no CS registry changes (spec DD2).
- `clinosim/codes/hl7_encounter.py::AdmitSource.HOSP` — retained (spec F2 removes it after this Issue lands).

---

## Task 1: Preflight measurement — canonical builder's synth_enc emission shape

**Files:**
- Read: `clinosim/modules/output/fhir_r4/encounters/encounter.py:69-599`
- Read: `clinosim/modules/output/fhir_r4/lib/localization.py:224-370`
- Write to scratchpad: `/private/tmp/claude-*/scratchpad/546-preflight-emission.json`

**Interfaces:**
- Consumes: none.
- Produces: JSON dump of `_build_encounter(synth_enc, ...)` output for both JP and US, used by Task 2 to write assertion values verbatim and by Task 4 to enumerate expected diffs.

**Purpose:** The spec (§ Data flow → "Diffs pending spec-time measurement") flagged two canonical-builder branches whose output for a synth-ED-shaped input is not obvious from reading:

1. `type[]` (SNOMED) — depends on `_ENCOUNTER_TYPE_SNOMED_CODE.get("emergency")` in `encounter.py:119`.
2. `serviceType.text` — depends on `_dept_display("", country)` in `encounter.py:176`.

Measurement runs `_build_encounter` **once** with the intended synth_enc dict shape, captures the full output, and freezes the observed `type[]` / `serviceType` presence-and-values for use in Task 2 assertions and Task 4 diff-table.

- [ ] **Step 1: Ensure clean branch and pinned ruff**

Run:
```bash
cd /Users/tokuyama/workspace/clinosim
git fetch --prune origin
git checkout -b fix/546-synth-ed-canonical-delegation origin/master
git rev-parse HEAD > /tmp/546-baseline-sha.txt   # capture baseline SHA for PR body
python -m pip install ruff==0.16.0
```

Expected: on new branch, HEAD SHA captured, ruff 0.16.0 installed.

- [ ] **Step 2: Write and run a one-shot preflight script**

Create `/private/tmp/claude-*/scratchpad/546-preflight.py` (use the actual scratchpad dir listed in the environment header):

```python
"""Preflight measurement for Issue #546. Runs _build_encounter against the
intended synth_enc dict shape and dumps the JP and US outputs. Not a test —
its output feeds Task 2 assertions and Task 4 diff enumeration."""
from __future__ import annotations

import json
from clinosim.codes.hl7_encounter import ActPriority, AdmitSource
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter


def _synth_enc(imp_adm_iso: str, imp_id: str) -> dict:
    from datetime import datetime, timedelta
    dt0 = datetime.fromisoformat(imp_adm_iso)
    ed_start = (dt0 - timedelta(hours=3, minutes=30)).isoformat()
    return {
        "encounter_id": f"{imp_id}-ED",
        "encounter_type": "emergency",
        "status": "completed",
        "priority": ActPriority.EM.value,
        "admit_source": AdmitSource.OUTP.value,
        "admission_datetime": ed_start,
        "discharge_datetime": imp_adm_iso,
        "attending_physician_id": "PRAC-000001",
        "chief_complaint": "Chest pain",
        "department_id": "",
    }


for country in ("JP", "US"):
    synth_enc = _synth_enc("2026-01-15T10:00:00", "ENC-000001")
    result = _build_encounter(synth_enc, "POP-000001", country=country)
    print(f"\n=== country={country} ===")
    print(json.dumps(result, indent=2, ensure_ascii=False))
```

Run:
```bash
python /private/tmp/claude-*/scratchpad/546-preflight.py \
  | tee /private/tmp/claude-*/scratchpad/546-preflight-emission.json
```

Expected: two JSON blocks (JP and US) printed. Record which of `type`, `serviceType`, `hospitalization.dischargeDisposition` appear in the output.

- [ ] **Step 3: Record observations in a note file**

Create `/private/tmp/claude-*/scratchpad/546-preflight-notes.md` with:

```markdown
# 546 preflight — canonical builder shape for synth_enc

Baseline SHA: <contents of /tmp/546-baseline-sha.txt>

## Observed extra fields (vs current synth-ED inline emit)

- `type[]`: <present with SNOMED code | absent>
- `serviceType.text`: <"<value>" | absent>
- `hospitalization.dischargeDisposition`: <present with fallback "home" | absent>

## Field values to assert in Task 2

- `class.coding[0].display` (JP): <verbatim string>
- `class.coding[0].display` (US): <verbatim string>
- `priority.coding[0].display` (JP): <verbatim string>
- `priority.coding[0].display` (US): <verbatim string>
- `hospitalization.admitSource.coding[0].display` (JP): <verbatim string>
- `hospitalization.admitSource.coding[0].display` (US): <verbatim string>
- `participant[0].type[0].coding[0]`: <verbatim dict>
```

Fill in every `<...>` from the preflight output. Task 2 reads this file to write assertions with the exact observed values (no guessing).

- [ ] **Step 4: Commit the branch anchor (no code change yet)**

Nothing to commit yet — scratchpad files are session-local. Verify branch state:

```bash
git status --short   # expect: clean
git log --oneline -1 # expect: current origin/master SHA
```

No commit in this task. The measurement outputs live in the scratchpad; they are inputs to Task 2, not repo artefacts.

---

## Task 2: Write regression tests (all initially FAIL)

**Files:**
- Create: `tests/unit/output/test_fhir_synth_ed_encounter_delegation.py`

**Interfaces:**
- Consumes: Task 1's `/private/tmp/claude-*/scratchpad/546-preflight-notes.md` for exact assertion values; `patient_factory` fixture from `tests/conftest.py`; `BundleContext` from `clinosim.modules.output.fhir_r4.lib.common`; `_bb_encounters` and (post-refactor) `_make_synth_ed_enc_dict` from `clinosim.modules.output.fhir_r4.lib.inline_bb`; `_build_encounter` from `clinosim.modules.output.fhir_r4.encounters.encounter`.
- Produces: 5 pytest tests. All are RED against current code; all turn GREEN after Task 3's refactor.

- [ ] **Step 1: Write the test file with all 5 tests**

Create `tests/unit/output/test_fhir_synth_ed_encounter_delegation.py`:

```python
"""Regression guards for Issue #546 — synth-ED Encounter delegates to
canonical `_build_encounter`.

These tests lock the post-refactor behaviour:

1. `_bb_encounters` calls `_build_encounter` twice per IMP encounter with
   `admit_source_encounter_id` set (once for the primary IMP, once for
   the synth-ED bridge) — no parallel dict construction.
2. The synth-ED bridge Encounter's `class.coding[0].display` matches what
   `_build_encounter` would emit for a plain `encounter_type="emergency"`
   input — silent-drift is impossible when both go through the same
   builder.
3. The synth-ED bridge omits `hospitalization.dischargeDisposition`
   entirely — the ED→IMP transition is expressed via `partOf`, and the
   canonical `home` fallback (encounter.py:487) is suppressed by the
   caller's post-hoc pop. See spec DD2 / DD4.
4. The synth-ED bridge's admit-source display comes from the CS registry
   (`code_lookup("hl7-admit-source", "outp", <lang>)`) — single source
   of truth.
5. The synth-ED bridge's `participant[0].type[]` has the canonical
   ATND coding shape (proof of full delegation to `_build_encounter`,
   which is the only source of that shape via `make_participant`).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter
from clinosim.modules.output.fhir_r4.lib.common import BundleContext
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_encounters


def _make_ctx(country: str) -> BundleContext:
    """Build a BundleContext with one IMP encounter that has an
    `admit_source_encounter_id` set — the trigger for synth-ED emission.
    """
    imp_id = "ENC-000001"
    ed_id = f"{imp_id}-ED"
    encounters = [
        {
            "encounter_id": imp_id,
            "encounter_type": "inpatient",
            "status": "completed",
            "admission_datetime": "2026-01-15T10:00:00",
            "discharge_datetime": "2026-01-20T14:00:00",
            "admit_source": "emd",
            "admit_source_encounter_id": ed_id,   # <-- triggers synth-ED emit
            "attending_physician_id": "PRAC-000001",
            "chief_complaint": "Chest pain",
        }
    ]
    return BundleContext(
        record={"encounters": encounters, "orders": []},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={"chronic_conditions": []},
        patient_id="POP-000001",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id=imp_id,
        patient_sex="M",
    )


def _synth_ed_resource(resources: list[dict]) -> dict:
    """Return the ED bridge encounter (id ends with `-ED`) from the list."""
    for r in resources:
        if r.get("id", "").endswith("-ED"):
            return r
    raise AssertionError(f"No synth-ED bridge encounter in resources: {[r.get('id') for r in resources]}")


@pytest.mark.parametrize("country", ["JP", "US"])
def test_synth_ed_delegated_via_canonical_builder(country: str) -> None:
    """Refactor guarantee: `_bb_encounters` calls `_build_encounter` for
    BOTH the primary IMP AND the synth-ED bridge. No parallel emit path.
    """
    ctx = _make_ctx(country)
    with patch(
        "clinosim.modules.output.fhir_r4.lib.inline_bb._build_encounter",
        wraps=_build_encounter,
    ) as spy:
        _bb_encounters(ctx)
    assert spy.call_count == 2, (
        f"_build_encounter should be called twice (primary IMP + synth-ED); "
        f"got {spy.call_count}. A parallel emitter has regressed."
    )


@pytest.mark.parametrize("country", ["JP", "US"])
def test_synth_ed_class_display_matches_canonical(country: str) -> None:
    """Silent-drift guard: synth-ED bridge's class.display equals what
    the canonical builder emits for a plain emergency Encounter."""
    ctx = _make_ctx(country)
    synth_ed = _synth_ed_resource(_bb_encounters(ctx))
    canonical_emergency = _build_encounter(
        {"encounter_id": "cmp", "encounter_type": "emergency", "status": "completed"},
        patient_id="POP-000001",
        country=country,
    )
    assert synth_ed["class"]["display"] == canonical_emergency["class"]["display"]


@pytest.mark.parametrize("country", ["JP", "US"])
def test_synth_ed_omits_discharge_disposition(country: str) -> None:
    """Spec DD2 + DD4: synth-ED emits no `dischargeDisposition`.
    ED→IMP transition is expressed via `partOf` on the IMP encounter.
    The canonical `home` fallback is suppressed by the caller's post-hoc pop.
    """
    ctx = _make_ctx(country)
    synth_ed = _synth_ed_resource(_bb_encounters(ctx))
    hosp = synth_ed.get("hospitalization", {})
    assert "dischargeDisposition" not in hosp, (
        f"synth-ED must NOT emit dischargeDisposition (spec DD2). Got: {hosp!r}"
    )


@pytest.mark.parametrize("country,lang", [("JP", "ja"), ("US", "en")])
def test_synth_ed_admit_source_uses_registry_display(country: str, lang: str) -> None:
    """Single-source-of-truth: synth-ED's admitSource display equals the
    CS registry lookup, not a bespoke hardcoded string.
    """
    ctx = _make_ctx(country)
    synth_ed = _synth_ed_resource(_bb_encounters(ctx))
    admit_source_display = synth_ed["hospitalization"]["admitSource"]["coding"][0]["display"]
    expected = code_lookup("hl7-admit-source", "outp", lang)
    assert admit_source_display == expected


@pytest.mark.parametrize("country", ["JP", "US"])
def test_synth_ed_participant_has_canonical_type(country: str) -> None:
    """Full delegation proof: `participant[0].type[]` comes from
    `make_participant` (canonical) and has an ATND coding under
    v3-ParticipationType. The pre-refactor inline emitter omitted `type[]`.
    """
    ctx = _make_ctx(country)
    synth_ed = _synth_ed_resource(_bb_encounters(ctx))
    participants = synth_ed.get("participant", [])
    assert participants, "synth-ED must have a participant (attending physician)"
    types = participants[0].get("type", [])
    assert types, "participant[0].type[] must be present (canonical shape)"
    coding = types[0]["coding"][0]
    assert coding["code"] == "ATND"
    assert coding["system"].endswith("v3-ParticipationType")
```

- [ ] **Step 2: Run the new tests — all must FAIL against current code**

Run:
```bash
pytest tests/unit/output/test_fhir_synth_ed_encounter_delegation.py -v
```

Expected failures (current code shape):
- `test_synth_ed_delegated_via_canonical_builder`: FAIL — `spy.call_count == 1` (only primary IMP goes through `_build_encounter`; synth-ED is inline)
- `test_synth_ed_class_display_matches_canonical`: FAIL — `"救急外来" != "救急"` (JP) or `"Emergency" != "emergency"` (US)
- `test_synth_ed_omits_discharge_disposition`: FAIL — current synth-ED emits `dischargeDisposition = {code: "hosp", display: "入院となる"}`
- `test_synth_ed_admit_source_uses_registry_display`: FAIL — `"外来より" != "外来より入院"` (JP)
- `test_synth_ed_participant_has_canonical_type`: FAIL — current inline emit has `{"individual": ...}` only, no `type[]`

If any test unexpectedly PASSES, the current code has already been changed since the plan was written; stop and investigate.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/unit/output/test_fhir_synth_ed_encounter_delegation.py
git commit --signoff -m "test(output): synth-ED canonical delegation regression tests — Issue #546

5 regression tests locking the target behaviour for the synth-ED bridge
Encounter emission:
- delegated via _build_encounter (spy assertion)
- class.display matches canonical (silent-drift guard)
- omits dischargeDisposition (spec DD2)
- admit_source display from CS registry (single source of truth)
- participant[0].type[] canonical shape (full delegation proof)

All 5 currently FAIL — turn GREEN after Task 3's refactor lands."
```

---

## Task 3: Refactor `inline_bb.py` — delegate synth-ED, delete dead code

**Files:**
- Modify: `clinosim/modules/output/fhir_r4/lib/inline_bb.py` — remove L185-220 (table + helper + explanatory comment) and L283-378 (inline block); add `_make_synth_ed_enc_dict` and 12-line delegation.
- Delete: `tests/unit/output/test_synth_ed_display_constants.py` — locks removed symbols.

**Interfaces:**
- Consumes: Task 1 preflight for `type[]` / `serviceType` expected behaviour (informs no code change here but confirms what tests will observe).
- Produces: All 5 Task 2 tests GREEN. Existing `tests/unit/output/test_synth_ed_display_constants.py` is removed (its subjects are deleted).

- [ ] **Step 1: Add `_make_synth_ed_enc_dict` helper**

Edit `clinosim/modules/output/fhir_r4/lib/inline_bb.py`. Immediately after the deleted `_synth_ed_display` slot (i.e., between the imports region and `_bb_patient` at old L223), insert:

```python
def _make_synth_ed_enc_dict(
    ctx: BundleContext,
    imp_enc: dict,
    partof_id: str,
) -> dict:
    """Build a minimal CIF-shape enc dict for the synth-ED bridge Encounter.

    Fed to `_build_encounter` so the synth-ED path emits through the
    single canonical builder (Issue #546, spec DD1). Preserves the
    ValueError/TypeError-tolerant admission_datetime derivation of the
    pre-refactor inline block: if the IMP encounter's admission_datetime
    is missing or non-ISO, admission_datetime is left empty and the
    canonical builder skips the period block (encounter.py:179).
    """
    _imp_adm = imp_enc.get("admission_datetime", "") if isinstance(imp_enc, dict) else getattr(
        imp_enc, "admission_datetime", ""
    )
    _imp_adm_str = str(_imp_adm) if _imp_adm else ""
    # ED stay ~3.5 hours before IMP admission — clinical-realistic bridge.
    _ed_end_str = _imp_adm_str
    _ed_start_str = ""
    try:
        from datetime import datetime as _dt
        from datetime import timedelta as _td

        if _imp_adm_str and "T" in _imp_adm_str:
            _dt0 = _dt.fromisoformat(_imp_adm_str.replace("Z", "+00:00"))
            _ed_start_str = (_dt0 - _td(hours=3, minutes=30)).isoformat()
    except (ValueError, TypeError):
        pass
    _att = imp_enc.get("attending_physician_id", "") if isinstance(imp_enc, dict) else getattr(
        imp_enc, "attending_physician_id", ""
    )
    _chief = imp_enc.get("chief_complaint", "") if isinstance(imp_enc, dict) else getattr(
        imp_enc, "chief_complaint", ""
    )
    return {
        "encounter_id": partof_id,
        "encounter_type": "emergency",
        "status": "completed",
        "priority": ActPriority.EM.value,
        "admit_source": AdmitSource.OUTP.value,
        "admission_datetime": _ed_start_str,
        "discharge_datetime": _ed_end_str,
        "attending_physician_id": _att,
        "chief_complaint": _chief,
        "department_id": "",
    }
```

Ensure the necessary imports (`ActPriority`, `AdmitSource`) are present at the top of the file. Grep first:

```bash
grep -n 'from clinosim.codes.hl7_encounter' clinosim/modules/output/fhir_r4/lib/inline_bb.py
```

If not present, add:
```python
from clinosim.codes.hl7_encounter import ActPriority, AdmitSource
```

- [ ] **Step 2: Delete `_SYNTH_ED_DISPLAYS` + `_synth_ed_display` + explanatory comment**

Delete lines 185-220 of the current `inline_bb.py`:
- The 30-line comment block starting `# Synthesised ED encounter (CY7-05) display strings — Issue #546 partial.`
- The `_SYNTH_ED_DISPLAYS: dict[str, tuple[str, str]] = { ... }` assignment
- The `def _synth_ed_display(slot: str, country: str) -> str: ...` helper (4 lines)

Verify no other file imports these symbols:

```bash
grep -rn '_SYNTH_ED_DISPLAYS\|_synth_ed_display' clinosim/ tests/
```

Expected: only the file being deleted (`tests/unit/output/test_synth_ed_display_constants.py`) references them. If any other file imports, stop and add explicit remediation to this step.

- [ ] **Step 3: Replace the inline synth-ED block in `_bb_encounters` with delegation**

In `clinosim/modules/output/fhir_r4/lib/inline_bb.py`, locate `_bb_encounters` and its inline synth-ED block (current L283-378, starting with `if _partof_id and "partOf" not in _resource:`). Replace the entire block (from that `if` through `_resources.append(_ed_resource)`) with:

```python
        if _partof_id and "partOf" not in _resource:
            _resource["partOf"] = {"reference": f"Encounter/{_partof_id}"}
            # CY7-05 synth-ED bridge Encounter: delegate to canonical
            # `_build_encounter` so the localization / CS-registry path is
            # single-source-of-truth (Issue #546, spec DD1).
            synth_enc = _make_synth_ed_enc_dict(ctx, enc, _partof_id)
            _ed_resource = _build_encounter(
                synth_enc,
                ctx.patient_id,
                country=ctx.country,
            )
            # synth-ED conveys the discharge-to-IMP transition via partOf,
            # not dischargeDisposition; the canonical "home" fallback
            # (encounter.py:487) does not fit the bridge-encounter context
            # (spec DD2 / DD4).
            _ed_resource.get("hospitalization", {}).pop("dischargeDisposition", None)
            _resources.append(_ed_resource)
```

Verify `_build_encounter` is already imported into `inline_bb.py`:

```bash
grep -n '_build_encounter' clinosim/modules/output/fhir_r4/lib/inline_bb.py | head -5
```

Expected: existing import at L76 (`_build_encounter,`). No new import needed.

- [ ] **Step 4: Delete the session-84 lock-in test file**

```bash
git rm tests/unit/output/test_synth_ed_display_constants.py
```

Verify removal:
```bash
ls tests/unit/output/test_synth_ed_display_constants.py 2>&1
```
Expected: "No such file or directory".

- [ ] **Step 5: Run the Task 2 regression tests — all 5 must PASS**

```bash
pytest tests/unit/output/test_fhir_synth_ed_encounter_delegation.py -v
```

Expected: 5 pass, 0 fail. If any test still fails, DO NOT proceed — the refactor is incomplete. Fix inline, then re-run.

- [ ] **Step 6: Run the full unit test suite**

```bash
pytest tests/unit -x
```

Expected: 3968 baseline + 5 new = 3973 pass; − 5 deleted (session 84 lock-in) → **3968 pass** net. (The 5 deleted tests were pinning removed symbols.)

If any other test fails, likely candidates:
- A test that asserted the old synth-ED display strings verbatim (`"救急外来"` etc.). Update to expected canonical value.
- A test that asserted `dischargeDisposition = "hosp"` on a synth-ED encounter. Update to assert absence.

For each failure, decide inline: legitimate assertion update vs unrelated breakage. Only update assertions that are directly a consequence of the spec's decisions.

- [ ] **Step 7: Lint + type check**

```bash
ruff==0.16.0 check clinosim/modules/output/fhir_r4/lib/inline_bb.py tests/unit/output/test_fhir_synth_ed_encounter_delegation.py
ruff==0.16.0 format --check clinosim/modules/output/fhir_r4/lib/inline_bb.py tests/unit/output/test_fhir_synth_ed_encounter_delegation.py
mypy clinosim/
```

Expected: clean on all three. If `ruff format --check` fails, run `ruff==0.16.0 format <files>` and re-verify.

- [ ] **Step 8: Commit the refactor**

```bash
git add -u clinosim/modules/output/fhir_r4/lib/inline_bb.py
git add -u tests/unit/output/test_synth_ed_display_constants.py   # -u picks up deletion
git commit --signoff -m "refactor(output): synth-ED Encounter delegates to _build_encounter — Issue #546

Eliminates the 90-LOC parallel Encounter synthesis in _bb_encounters:

- Adds _make_synth_ed_enc_dict() to build a minimal CIF-shape enc dict
- _bb_encounters synth-ED branch: 1 call to canonical _build_encounter
  + post-hoc pop() of the dischargeDisposition fallback (spec DD4)
- Deletes _SYNTH_ED_DISPLAYS table + _synth_ed_display helper
- Deletes session-84 lock-in tests (subjects removed)

Byte-diff surface on synth-ED bridge Encounters (documented in PR body):
- class.display: 救急外来 → 救急 (JP), Emergency → emergency (US)
- priority.display: 緊急 → 救急 (JP), unchanged (US)
- admitSource.display: 外来より → 外来より入院 (JP; from CS registry)
- dischargeDisposition: field removed (partOf conveys ED→IMP transition)
- participant[0].type[]: added (canonical ATND shape)

All 5 new regression tests in test_fhir_synth_ed_encounter_delegation.py
turn GREEN. Full tests/unit suite remains green. See design spec:
docs/superpowers/specs/2026-08-08-546-synth-ed-encounter-canonical-delegation-design.md"
```

---

## Task 4: Cohort byte-diff + downstream verification

**Files:**
- Read (regeneration output): `/tmp/546-baseline-jp/`, `/tmp/546-baseline-us/`, `/tmp/546-pr-jp/`, `/tmp/546-pr-us/`
- Write to scratchpad: `/private/tmp/claude-*/scratchpad/546-diff-jp.txt`, `.../546-diff-us.txt`, `.../546-verification-report.md`

**Interfaces:**
- Consumes: Task 3's refactor commit on the current branch, Task 1's `/tmp/546-baseline-sha.txt` for the baseline ref.
- Produces: A `verification-report.md` block that gets pasted verbatim into the PR body as the verification checklist evidence.

- [ ] **Step 1: Generate baseline cohort (current `origin/master` at branch-cut time)**

Use a temporary git worktree so the current branch stays intact:

```bash
BASELINE_SHA=$(cat /tmp/546-baseline-sha.txt)
git worktree add /tmp/546-baseline-worktree "$BASELINE_SHA"
cd /tmp/546-baseline-worktree
PYTHONPATH=. python -m clinosim generate -p 30 -s 42 --country JP --format fhir-r4 -o /tmp/546-baseline-jp
PYTHONPATH=. python -m clinosim generate -p 30 -s 42 --country US --format fhir-r4 -o /tmp/546-baseline-us
cd /Users/tokuyama/workspace/clinosim
```

Expected: two output dirs with `Encounter.ndjson`, `Patient.ndjson`, etc.

**Rationale for the isolated worktree + PYTHONPATH=. combo:** the CLI must run the exact code committed at the baseline SHA, not whatever pyenv's shim points at (see memory `feedback_pythonpath_for_isolated_worktree.md`). Skipping either produces silently-wrong baseline output.

- [ ] **Step 2: Generate PR-branch cohort (current HEAD, post-refactor)**

```bash
PYTHONPATH=. python -m clinosim generate -p 30 -s 42 --country JP --format fhir-r4 -o /tmp/546-pr-jp
PYTHONPATH=. python -m clinosim generate -p 30 -s 42 --country US --format fhir-r4 -o /tmp/546-pr-us
```

- [ ] **Step 3: Diff both cohorts**

```bash
diff -r /tmp/546-baseline-jp /tmp/546-pr-jp -x _generator_metadata.json > /private/tmp/claude-*/scratchpad/546-diff-jp.txt
diff -r /tmp/546-baseline-us /tmp/546-pr-us -x _generator_metadata.json > /private/tmp/claude-*/scratchpad/546-diff-us.txt
```

- [ ] **Step 4: Enumerate the diff and gate on expected shifts only**

Open each diff file. For each hunk, categorise:

- **Expected — display shifts** (spec § Data flow → Confirmed diffs): on `Encounter.ndjson`, matching one of:
  - `class.display`: `"救急外来"` → `"救急"` (JP), `"Emergency"` → `"emergency"` (US)
  - `priority.display`: `"緊急"` → `"救急"` (JP), unchanged (US)
  - `hospitalization.admitSource.display`: `"外来より"` → `"外来より入院"` (JP), `"From outpatient"` → `"From outpatient department"` (US)
  - `hospitalization.dischargeDisposition`: field removed
- **Expected — canonical enrichments** (spec § Data flow → Preflight-observed extras):
  - `type[]` added (SNOMED 50849002 "救急入院" / "Emergency hospital admission")
  - `serviceType.text` added (`"内科"` / `"Internal Medicine"`)
  - `serviceProvider.reference` changed: `Organization/hospital-main` → `Organization/dept-internal-medicine`
  - `location[]` added (`loc-dept-internal-medicine`)
  - `participant[]` grows 1 → 3 (ATND with `type[]` + ADM + DIS, all referencing the attending practitioner)
  - `meta.profile` on JP synth-ED bridges: gains `JP_Encounter` if the source IMP encounter's `meta.profile` was empty (canonical builder always emits it for JP)
- **Unexpected**: any other file, or any Encounter diff not matching either category above.

Every unexpected hunk BLOCKS merge until root-caused. Common root causes:
- IMP encounter changes (indicates the refactor accidentally touched the primary path — undo).
- Non-Encounter resource changes (indicates a shared helper's behaviour drifted — investigate).

Count each expected category and write to `/private/tmp/claude-*/scratchpad/546-verification-report.md`:

```markdown
## Byte-diff verification (30-patient seed 42)

Baseline SHA: <SHA from /tmp/546-baseline-sha.txt>
PR head SHA: $(git rev-parse HEAD)

### JP cohort
- Total synth-ED bridge Encounters diffed: <N>
- class.display shifts: <N>
- priority.display shifts: <N>
- admitSource.display shifts: <N>
- dischargeDisposition removals: <N>
- participant[0].type[] additions: <N>
- Preflight-observed additions (type[] / serviceType): <details>
- Unexpected hunks: <MUST be 0>

### US cohort
<same layout>

### Non-Encounter resources
- Total non-Encounter diff hunks: <MUST be 0>
```

- [ ] **Step 5: fhir-jp-validator run**

The CI gate `JP p=300 seed=300 → eval only jp_clins_lab_compliance` is what runs in GitHub Actions. Reproduce locally on the PR cohort:

```bash
grep -A 30 'JP p=300 seed=300' .github/workflows/*.yml | head -40
```

Follow the exact command sequence emitted (it typically involves generating a p=300 seed=300 JP cohort and invoking the validator on it). Record:

- Baseline validator error count (from the just-generated `/tmp/546-baseline-jp` cohort, or a separate p=300 baseline if the CI target uses that size).
- PR validator error count (from `/tmp/546-pr-jp` at the same size).

Expected: error count is **equal to or lower than** baseline. A reduction is plausible because `dischargeDisposition = "hosp"` (an unregistered discharge-disposition code) may have contributed warnings; removal should not add errors.

If validator error count INCREASES, stop and investigate. Do not proceed to PR open.

Append the finding to `/private/tmp/claude-*/scratchpad/546-verification-report.md`:

```markdown
### fhir-jp-validator (p=300 seed=300 JP cohort)
- Baseline errors: <N>
- PR errors: <N>
- Delta: <(PR - Baseline)>  # MUST be <= 0
```

- [ ] **Step 6: iris4h-ai downstream grep**

Per memory `feedback_iris_ai_copy.md`, clinosim's FHIR output is copied to `../fhir-jp-validator/fhir_r4/`. Grep for consumers that branch on the removed field:

```bash
grep -rn 'dischargeDisposition' ../fhir-jp-validator/ 2>/dev/null | grep -v '^Binary\|.git/'
grep -rn 'dischargeDisposition' ../iris4h-ai/ 2>/dev/null | grep -v '^Binary\|.git/'
```

For each hit, evaluate whether it reads `dischargeDisposition` on a **synth-ED bridge** Encounter (i.e., an Encounter whose ID ends in `-ED` or whose class is EMER with a partOf reference). Most consumers process all Encounters uniformly; the specific-to-synth-ED check is what matters.

Record findings:

```markdown
### iris4h-ai / fhir-jp-validator downstream grep
- Total `dischargeDisposition` references: <N>
- References that specifically branch on synth-ED bridge: <N>
- If N > 0: <owner notified via <mechanism>, issue #<link>>
- If N == 0: no downstream consumer affected — safe to ship
```

- [ ] **Step 7: Run integration tests**

```bash
pytest tests/integration -x
```

Expected: all pass. Any failure that mentions `synth-ED`, `dischargeDisposition`, or `partOf` on an EMER encounter is a legitimate assertion-update request — fix inline with a comment referencing this design.

- [ ] **Step 8: Cleanup the baseline worktree**

```bash
git worktree remove /tmp/546-baseline-worktree
rm -rf /tmp/546-baseline-jp /tmp/546-baseline-us /tmp/546-pr-jp /tmp/546-pr-us
```

- [ ] **Step 9: No commit — this task produces a scratchpad report only**

The verification report is inputs to Task 5's PR body. No repo commit here.

---

## Task 5: Open PR + file follow-up issues F1/F2/F3

**Files:**
- Read: `/private/tmp/claude-*/scratchpad/546-verification-report.md` (Task 4 output)
- No new files, no repo modifications.

**Interfaces:**
- Consumes: Task 3 commit on `fix/546-synth-ed-canonical-delegation`; Task 4 verification report.
- Produces: PR opened against `master`, 3 new follow-up Issues (F1/F2/F3) filed.

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/546-synth-ed-canonical-delegation
```

- [ ] **Step 2: Open the PR with verification evidence**

```bash
gh pr create --title "refactor(output): synth-ED Encounter delegates to _build_encounter (closes #546)" --body "$(cat <<'EOF'
## Summary

Eliminates the parallel synth-ED Encounter synthesis in `_bb_encounters`
(~90 LOC), delegating to the single canonical `_build_encounter` builder.
See design: `docs/superpowers/specs/2026-08-08-546-synth-ed-encounter-canonical-delegation-design.md`.

## Design decisions realised

- **DD1**: clean delegation — no override mechanism on the canonical builder.
- **DD2**: `dischargeDisposition` omitted from synth-ED (the pre-existing
  `hosp` code was semantically wrong under HL7 discharge-disposition CS;
  `partOf` reference already conveys ED→IMP transition).
- **DD3**: `_ACT_PRIORITY_DISPLAY_JA["EM"]` improvement deferred to F1
  (see follow-ups below).
- **DD4**: canonical `home` fallback suppressed via post-hoc `pop` in the
  caller (SRP preserved on the builder).

## Byte-diff surface (documented shift)

Applies to synth-ED bridge Encounters only. Non-Encounter resources are
byte-identical vs baseline.

<PASTE `## Byte-diff verification` section from
/private/tmp/claude-*/scratchpad/546-verification-report.md here>

## Downstream verification

<PASTE `### fhir-jp-validator` and `### iris4h-ai / fhir-jp-validator downstream grep` sections here>

## Test plan
- [x] `pytest tests/unit` — all pass (net 3968 = 3973 new + 5 removed)
- [x] `pytest tests/integration` — all pass
- [x] `mypy clinosim/` strict — clean
- [x] `ruff==0.16.0 check` + `format --check` — clean
- [x] 30-patient seed 42 JP+US cohort diff-r vs master baseline: only expected Encounter shifts on synth-ED bridge resources
- [x] fhir-jp-validator error count vs baseline: unchanged or lower
- [x] Downstream `dischargeDisposition` grep on synth-ED bridge: no consumer affected (or owner notified)

## Follow-up issues

- F1: `_ACT_PRIORITY_DISPLAY_JA["EM"]` display improvement (`"救急"` → `"緊急"`) — filed as #<F1-number>
- F2: `AdmitSource.HOSP` enum member deletion (semantic misuse) — filed as #<F2-number>
- F3: cross-cutting `country_code == "JP"` → `is_jp()` sweep in medications.py / conditions.py / types/document.py — filed as #<F3-number>

Closes #546.
EOF
)"
```

Copy the PR URL from the command output for use in follow-up issues.

- [ ] **Step 3: File follow-up F1 (priority EM display improvement)**

```bash
gh issue create --title "[CODE-QUALITY] Improve _ACT_PRIORITY_DISPLAY_JA[\"EM\"] from \"救急\" to \"緊急\" (priority level, not class name)" --body "$(cat <<'EOF'
Split-off from #546 (deferred per design DD3).

## Context

`clinosim/modules/output/fhir_r4/lib/localization.py::_ACT_PRIORITY_DISPLAY_JA["EM"]` currently maps to `"救急"`.

`"救急"` is the display for the **Encounter class** EMER (\"emergency
encounter\"). The **Encounter.priority** slot is a priority-level value
(EM = emergency-priority, UR = urgent, R = routine). Rendering priority
EM as `\"救急\"` conflates the class label with the priority label.

`\"緊急\"` (urgent / emergent) is the accurate JP display for priority EM.

## Impact

- Encounters with `priority=EM` (all synth-ED bridges + IMP encounters
  admitted for `EMERGENCY_PRIORITY_DISEASES` per
  `simulator/inpatient.py:535` and `simulator/emergency.py:300`)
  currently emit `Encounter.priority.coding[0].display = \"救急\"`.
- Same JP display string for class.display (\"救急\") makes the two slots
  visually indistinguishable in JP-facing consumers.

## Change

- `_ACT_PRIORITY_DISPLAY_JA[\"EM\"]` = `\"救急\"` → `\"緊急\"`
- `_ACT_PRIORITY_DISPLAY_JA[\"emergency\"]` = `\"救急\"` → `\"緊急\"`
  (alias for compatibility with legacy raw string input)

## Verification

- `pytest tests/unit`
- 30-patient seed 42 cohort diff-r vs master: `priority.display` shifts
  on all Encounters with `priority=EM` (expected count: primary IMP with
  EMERGENCY_PRIORITY_DISEASES + synth-ED bridges); no other diffs.

## Effort

Small — 2-line change + expected-value updates in tests + cohort diff review.
EOF
)"
```

- [ ] **Step 4: File follow-up F2 (`AdmitSource.HOSP` enum member deletion)**

Before creating, verify #546 PR is open (F2 explicitly depends on #546 landing):

```bash
gh issue create --title "[CODE-QUALITY] Delete AdmitSource.HOSP enum member (semantic misuse — was synth-ED overload)" --body "$(cat <<'EOF'
Split-off from #546 (unblocked once #546 PR lands).

## Context

`clinosim/codes/hl7_encounter.py:44-45`:

\`\`\`python
class AdmitSource(StrEnum):
    ...
    HOSP = \"hosp\"
    \"\"\"Hospital transfer — synth-ED companion Encounter's discharge-to-inpatient path.\"\"\"
\`\`\`

`AdmitSource` is a StrEnum for the HL7 admit-source CS. Its `HOSP` member
existed **only to support the synth-ED bridge Encounter's**
`dischargeDisposition` emission (a semantic misuse: an admit-source value
emitted under the discharge-disposition CS, where HL7 spec assigns
`\"hosp\"` the meaning \"Hospice\").

Now that #546 removes `dischargeDisposition` from synth-ED emission, the
`HOSP` member has no remaining consumer.

## Change

- Delete `HOSP = \"hosp\"` from `AdmitSource`.
- `grep -rn 'AdmitSource.HOSP\|AdmitSource\\.HOSP' clinosim/ tests/` to
  confirm no callers remain (should be empty after #546 lands).

## Verification

- `pytest tests/unit`
- `mypy clinosim/` — clean (any remaining reference produces a type error).

## Blocked by

#546 PR merged.

## Effort

Trivial — one-line deletion + type-check confirmation.
EOF
)"
```

- [ ] **Step 5: File follow-up F3 (cross-cutting `country == "JP"` sweep)**

```bash
gh issue create --title "[CODE-QUALITY] Cross-cutting country == \"JP\" literal sweep → is_jp() helper" --body "$(cat <<'EOF'
Split-off from #546 (out of scope; independent cleanup).

## Context

`clinosim/modules/_shared.py:32` defines the canonical `is_jp(country)`
helper (whitespace-tolerant, case-normalising, matches the AGENTS.md
rule). Several sites still use the bare literal comparison
`country == \"JP\"` / `country_code == \"JP\"` / `country.upper() == \"JP\"`,
each of which is non-whitespace-tolerant and drifts from the canonical.

## Sites to sweep (as of #546 branch cut)

Approximate count per file (verified via
`grep -rn 'country_code == \"JP\"\\|country == \"JP\"\\|country.upper() == \"JP\"' clinosim/`):

- `clinosim/modules/output/fhir_r4/medications/medications.py` — ~14 sites
- `clinosim/modules/output/fhir_r4/conditions/conditions.py` — ~4 sites
- `clinosim/types/document.py` — 2 sites (uses `country.upper() == \"JP\"`)
- others surfaced by re-grep

## Change

Replace each site with `is_jp(country)` (importing from
`clinosim.modules._shared`). Add a pre-commit ruff-style grep guard
(`.pre-commit-hooks.yaml` or a new `ruff` custom rule) that forbids new
`country[_code]? == \"JP\"` literals in `clinosim/`.

## Verification

- `pytest tests/unit`
- 30-patient seed 42 cohort diff-r vs master: **zero diffs**
  (`is_jp(country)` is functionally identical to
  `str(country).upper() == \"JP\"` for all inputs clinosim currently
  emits; the change is name-shape only).

## Effort

Medium — ~20 mechanical substitutions across 3+ files + pre-commit rule.
EOF
)"
```

- [ ] **Step 6: Update the #546 PR body with actual follow-up issue numbers**

```bash
gh pr view --json url,number | jq '.'   # get PR number
# Copy the PR number, then:
gh pr edit <PR#> --body "$(gh pr view <PR#> --json body -q .body \
  | sed -e 's|#<F1-number>|#<actual F1 issue number>|' \
        -e 's|#<F2-number>|#<actual F2 issue number>|' \
        -e 's|#<F3-number>|#<actual F3 issue number>|')"
```

- [ ] **Step 7: Wait for CI, then request review**

The PR is now open with all verification evidence + follow-ups linked. CI runs asynchronously. Poll status:

```bash
gh pr checks <PR#>
```

If any check fails, diagnose and push a fixup commit (with `--signoff`). Do not force-push unless a rebase is explicitly needed.

Once all checks pass, this task is complete.

- [ ] **Step 8: No local repo commit — GitHub artefacts only**

Nothing to commit locally in this task. The PR + 3 issues are all filed as GitHub artefacts. Local branch stays at Task 3's commit.

---

## Self-Review

### Spec coverage

| Spec section | Task |
|---|---|
| Goal (delegate synth-ED to `_build_encounter`) | Task 3 |
| DD1 (no override mechanism) | Task 3 (no builder change) |
| DD2 (`dischargeDisposition` omit) | Task 3 (post-hoc `pop`), Task 2 (test #3) |
| DD3 (F1 deferred) | Task 5 (Step 3 files F1) |
| DD4 (post-hoc `pop`) | Task 3 (Step 3), Task 2 (test #3) |
| Architecture (`_make_synth_ed_enc_dict` + delegate + pop) | Task 3 |
| C1 (`_make_synth_ed_enc_dict`) | Task 3 (Step 1) |
| C2 (updated `_bb_encounters`) | Task 3 (Step 3) |
| C3 (deletions) | Task 3 (Step 2, Step 4) |
| Data flow (5 confirmed diffs + preflight-measured extras) | Task 1 (preflight), Task 4 (diff enumeration) |
| Error handling (partOf gate, admission_datetime robustness, etc.) | Task 3 (Step 1 preserves ValueError/TypeError try) |
| Unit tests (5 tests) | Task 2 |
| Cohort byte-diff verification | Task 4 (Step 1-4) |
| Downstream verification V-D1 (fhir-jp-validator) | Task 4 (Step 5) |
| Downstream verification V-D2 (iris4h-ai grep) | Task 4 (Step 6) |
| V-D3 (integration suite) | Task 4 (Step 7) |
| PR body checklist | Task 5 (Step 2) |
| Follow-up F1 filing | Task 5 (Step 3) |
| Follow-up F2 filing | Task 5 (Step 4) |
| Follow-up F3 filing | Task 5 (Step 5) |

All spec sections mapped.

### Placeholder scan

No TBD / TODO / FIXME / "see Task N" placeholders. Two intentional `<placeholder>` markers exist in Task 4 Step 4 (report template values filled in at execution time) and Task 5 Step 2 (PR body template — verification report block pasted in) — these are runtime substitutions, not plan placeholders.

### Type consistency

- `_make_synth_ed_enc_dict(ctx, imp_enc, partof_id) -> dict` signature identical in spec C1, Task 3 Step 1 code, and Task 2 test consumer (via `_bb_encounters` mock).
- `_build_encounter` signature (from `encounters/encounter.py:69`) used consistently in Task 2 tests and Task 3 delegation call.
- `BundleContext` fields used in Task 2 `_make_ctx` helper match `common.py:94-110` definition.
