# Design: Delegate synth-ED Encounter emission to canonical `_build_encounter`

Issue: [#546](https://github.com/TomoOkuyama/clinosim/issues/546)
Date: 2026-08-08
Status: Design approved, ready for implementation-plan phase.

## Goal

Eliminate the parallel Encounter synthesis path in
`clinosim/modules/output/fhir_r4/lib/inline_bb.py::_bb_encounters` (the
CY7-05 synthesised ED partOf Encounter, ~90 LOC). All Encounter emission
routes through the single canonical builder
`clinosim/modules/output/fhir_r4/encounters/encounter.py::_build_encounter`,
gaining CS-registry lookup and localization for free and removing the
silent-drift risk that motivated Issue #546.

## Non-goals (out of scope, tracked as follow-up issues)

- **F1**: Improve canonical `_ACT_PRIORITY_DISPLAY_JA["EM"]` display from
  `"救急"` (class-name flavour) to `"緊急"` (priority-level flavour) —
  affects real IMP encounters with `priority=EM`, not just synth-ED.
- **F2**: Delete `AdmitSource.HOSP` enum member (semantic misuse: an
  admit-source enum value overloaded for discharge-disposition slot).
  Unblocked once this Issue lands.
- **F3**: Cross-cutting `country_code == "JP"` → `is_jp()` sweep across
  `medications.py` (14 sites), `conditions.py` (4 sites), and
  `types/document.py` (2 sites). Independent cleanup; not tied to synth-ED.

## Background — what the current code actually does

`_bb_encounters` already delegates the **primary IMP Encounter** to
`_build_encounter` (`inline_bb.py:267`). It only inlines the synthesised
**ED partOf** Encounter (`inline_bb.py:285-378`), and that inline block:

1. Constructs `_ed_resource` as a dict directly (no builder call).
2. Uses a locally-owned display table `_SYNTH_ED_DISPLAYS` +
   `_synth_ed_display()` helper (session 84 partial refactor) to pick
   JP/EN display strings for four slots:
   - `class.display`: `"救急外来"` (JP) / `"Emergency"` (US)
   - `priority.display`: `"緊急"` (JP) / `"emergency"` (US)
   - `hospitalization.admitSource.display`: `"外来より"` /
     `"From outpatient"`
   - `hospitalization.dischargeDisposition.display`: `"入院となる"` /
     `"Admitted to hospital"`
3. The above four displays **intentionally diverge** from the canonical
   `_CLASS_DISPLAY_JA` / `_ACT_PRIORITY_DISPLAY_JA` / `code_lookup`
   sources (per session 84 code comment). Any canonical-side revision
   silently drifts these away.

### Discoveries during design (motivate design decisions)

- **D1 — `AdmitSource.HOSP` semantic misuse**: The synth-ED path emits
  `dischargeDisposition.coding.code = AdmitSource.HOSP.value = "hosp"`.
  `AdmitSource` is a StrEnum for the admit-source CS; its `HOSP` member
  is documented as "synth-ED companion Encounter's discharge-to-inpatient
  path" (`clinosim/codes/hl7_encounter.py:44-45`). The value is emitted
  under `system = hl7-discharge-disposition`, where HL7 spec assigns
  `"hosp"` the meaning **"Hospice"** — not "hospitalized". The
  hardcoded display `"入院となる"` covers this semantic mismatch.
- **D2 — CS registry gap**: `codes/data/hl7-discharge-disposition.yaml`
  contains only `home` and `exp`; `hosp` is not registered at all. A
  naive `code_lookup("hl7-discharge-disposition", "hosp", "ja")` returns
  the code as fallback text, not a display. Adding `hosp` to the
  registry with its HL7-spec meaning (`"Hospice"` / `"ホスピス"`)
  would introduce actively-wrong semantics for the synth-ED use case.
- **D3 — Priority EM appears on real IMP encounters**:
  `simulator/inpatient.py:535` and `simulator/emergency.py:300` set
  `Encounter.priority = ActPriority.EM` on IMP encounters admitted for
  emergency-priority diseases. Any change to
  `_ACT_PRIORITY_DISPLAY_JA["EM"]` propagates to **all** such
  encounters, not just synth-ED. Out of scope for #546 (see F1).

## Design decisions

### DD1: Clean delegation — no override mechanism on the canonical builder

`_build_encounter` stays a pure canonical builder. Adding a
`display_overrides: dict[str, str] | None = None` param to accommodate
synth-ED divergence was considered and rejected:

- SRP: mixes "build canonical Encounter" with "allow caller display
  customization" in a widely-used builder.
- Maintainability: every reader now must know which slots are
  overridable and which are not; every new call site must decide.
- Silent-drift risk shifts rather than disappears — canonical updates
  are still masked by the override table.

Trade-off accepted: synth-ED loses its bespoke JP displays and adopts
the canonical CS-registry / localization-table displays (byte-diff shift
documented below).

### DD2: `dischargeDisposition` field omitted entirely from synth-ED

The current emission
`{system: discharge-disposition, code: "hosp", display: "入院となる"}` is
factually invalid data (D1, D2). Rather than "fix the invalid code"
(which requires choosing a real HL7 code and shifting downstream
consumers), the synth-ED emit path **omits `dischargeDisposition`
entirely**. Rationale:

- ED → IMP transition is already conveyed by
  `Encounter.partOf → Encounter/{IMP-id}`.
- HL7 FHIR bridge Encounters are not required to carry a
  `dischargeDisposition`; the `partOf` reference is the canonical
  representation of "this ED encounter is the start-of-stay for that
  inpatient encounter".
- Omission also unblocks F2 (`AdmitSource.HOSP` deletion) without
  needing to invent a substitute code first.

### DD3: `_ACT_PRIORITY_DISPLAY_JA["EM"]` improvement deferred (F1)

The canonical display `"救急"` for priority EM is semantically weaker
than the synth-ED override `"緊急"` (priority-level vs class-name
flavour). Correcting the canonical table would:

- Improve display accuracy on the wider corpus of real IMP encounters
  where `priority=EM` fires (D3).
- Require re-review of every JP-facing consumer that keys off
  priority display.

That is a canonical-quality improvement independent of the synth-ED
delegation and is filed as follow-up F1. In this PR, synth-ED accepts
canonical `"救急"`.

### DD4: `dischargeDisposition` fallback (`home` auto-emit) suppression via post-hoc `pop`

`_build_encounter` (encounter.py:487-496) auto-fills
`dischargeDisposition = home` when the input's `status ∈
{"completed", "finished"}` and no explicit disposition is set. For
synth-ED (`status = "completed"`, no explicit disposition per DD2), this
would silently emit a wrong `home` disposition.

Options considered:

| Option | Fix | Verdict |
|---|---|---|
| P | Pass `status=""` in synth_enc dict | ✗ produces invalid `status=""` FHIR field |
| **Q** | **Post-hoc `pop` on the returned resource in `_bb_encounters`** | **✓ SRP preserved, one-line local correction** |
| R | Add `emit_discharge_fallback: bool` param to `_build_encounter` | ✗ pollutes canonical builder for one caller |
| S | Change canonical fallback condition globally | ✗ affects unrelated IMP encounters |

**Chosen: Q**. `_bb_encounters` calls `_build_encounter`, then executes:

```python
# synth-ED conveys the discharge-to-IMP transition via partOf, not
# dischargeDisposition; the canonical "home" fallback (encounter.py:487)
# does not fit the bridge-encounter context.
_ed_resource.get("hospitalization", {}).pop("dischargeDisposition", None)
```

One comment line explains why. Canonical builder stays untouched.

## Architecture

**Current**:

```
_bb_encounters(ctx)
├─ Primary IMP encounter: _build_encounter(enc, ...) ── canonical path
└─ synth-ED partOf encounter: 90-LOC inline dict construction
   ├─ Uses _SYNTH_ED_DISPLAYS table for 4 divergent displays
   ├─ Emits invalid discharge_disposition = "hosp" with fabricated display
   └─ Serves as a parallel Encounter emitter, out of sync with canonical
```

**After**:

```
_bb_encounters(ctx)
├─ Primary IMP encounter: _build_encounter(enc, ...) ── canonical path
└─ synth-ED partOf encounter:
   ├─ synth_enc = _make_synth_ed_enc_dict(ctx, imp_enc, partof_id)
   ├─ _ed_resource = _build_encounter(synth_enc, ctx.patient_id,
   │                                  country=ctx.country)
   ├─ _ed_resource.get("hospitalization", {}).pop("dischargeDisposition", None)
   └─ _resources.append(_ed_resource)
```

- `_bb_encounters` — orchestration only ("which encounters to emit").
- `_make_synth_ed_enc_dict` — new local helper ("what CIF-shape enc dict
  represents the synth-ED case").
- `_build_encounter` — the single canonical Encounter builder;
  unchanged.

## Components

### C1 — new helper `_make_synth_ed_enc_dict`

Location: `clinosim/modules/output/fhir_r4/lib/inline_bb.py`
(module-private, same file as `_bb_encounters`).

Signature and behaviour:

```python
def _make_synth_ed_enc_dict(
    ctx: BundleContext,
    imp_enc: dict | Encounter,
    partof_id: str,
) -> dict:
    """Build minimal CIF-shape enc dict for the synth-ED companion Encounter.

    The returned dict is fed to `_build_encounter` so the synth-ED path
    emits through the single canonical builder.

    Fields set:
      - encounter_id       = partof_id
      - encounter_type     = "emergency"          → class EMER via _build_encounter
      - status             = "completed"          → "finished" via map_encounter_status
      - priority           = ActPriority.EM.value
      - admit_source       = AdmitSource.OUTP.value ("outp")
      - admission_datetime = IMP adm − 3h30m (ED stay window)
      - discharge_datetime = IMP admission_datetime (ED → IMP transition)
      - attending_physician_id, chief_complaint: propagated from imp_enc
      - department_id      = ""                   → serviceProvider fallback
                                                     Organization/hospital-main
      - discharge_disposition = ""                → OMIT (post-hoc pop in caller)

    Robustness: `admission_datetime` computation preserves the existing
    ValueError/TypeError-tolerant behaviour (inline_bb.py:293-302). If
    the IMP encounter's admission_datetime is missing / not ISO-parseable,
    the returned dict has admission_datetime = "" and _build_encounter
    skips the period block (encounter.py:179).
    """
```

### C2 — modified `_bb_encounters`

Replace `inline_bb.py:283-379` (the 90-LOC inline block) with:

```python
if _partof_id and "partOf" not in _resource:
    _resource["partOf"] = {"reference": f"Encounter/{_partof_id}"}
    synth_enc = _make_synth_ed_enc_dict(ctx, enc, _partof_id)
    _ed_resource = _build_encounter(
        synth_enc,
        ctx.patient_id,
        country=ctx.country,
    )
    # synth-ED conveys the discharge-to-IMP transition via partOf, not
    # dischargeDisposition; the canonical "home" fallback (encounter.py:487)
    # does not fit the bridge-encounter context.
    _ed_resource.get("hospitalization", {}).pop("dischargeDisposition", None)
    _resources.append(_ed_resource)
```

### C3 — deletions

| File | Location | Content |
|---|---|---|
| `inline_bb.py` | L185-214 | `_SYNTH_ED_DISPLAYS` table + surrounding 30-line explanatory comment |
| `inline_bb.py` | L217-220 | `_synth_ed_display()` helper function |
| `inline_bb.py` | L283-379 | Inline `_ed_resource` synthesis block |

### C4 — untouched by this Issue

- `clinosim/modules/output/fhir_r4/encounters/encounter.py::_build_encounter` —
  no signature or behaviour change.
- `clinosim/codes/data/hl7-admit-source.yaml`,
  `hl7-discharge-disposition.yaml` — no CS registry changes.
- `clinosim/codes/hl7_encounter.py::AdmitSource.HOSP` — enum member
  retained for now (F2 will remove it once #546 lands).

## Data flow — byte-diff surface

Two categories:

### Confirmed diffs (5 fields, applies to every synth-ED Encounter)

| Field | Before | After | Locale |
|---|---|---|---|
| `class.display` | `"救急外来"` / `"Emergency"` | `"救急"` / `"emergency"` | JP / US |
| `priority.display` | `"緊急"` / `"emergency"` | `"救急"` / `"emergency"` | JP only (US unchanged) |
| `hospitalization.admitSource.display` | `"外来より"` / `"From outpatient"` | `"外来より入院"` / `"From outpatient department"` | JP / US |
| `hospitalization.dischargeDisposition` | full field with code=`"hosp"` display=`"入院となる"`/`"Admitted to hospital"` | **field omitted** | JP / US |
| `participant[0].type[]` | absent (minimal shape) | `[{coding: [{system: v3-ParticipationType, code: "ATND", display: "attender"}]}]` (canonical shape) | both |

Expected volume: seed 42, 30-patient JP+US cohort emits approximately
20-30 synth-ED Encounter resources (one per IMP encounter admitted via
ED); the exact count is fingerprint-stable and is captured in the PR
verification report.

### Diffs pending spec-time measurement (canonical builder branches)

- `type[]` (SNOMED): `_ENCOUNTER_TYPE_SNOMED_CODE.get("emergency")` in
  `encounter.py:119`. If a code exists, `type[]` gains a coding array;
  if not, no change.
- `serviceType.text`: `_dept_display("", country)` in `encounter.py:176`.
  Returns whatever the localization table maps `""` to; may add a
  `{"text": "..."}` field.

**Action**: at the start of implementation, run `_build_encounter` with
the intended synth_enc dict shape, dump the result, and add the
observed `type[]` / `serviceType` behaviour to the confirmed-diff table
in the PR body. This measurement replaces speculation with data.

## Error handling & edge cases

- **IMP encounter has existing `partOf`** (readmission case,
  `inline_bb.py:283`): synth-ED emission remains gated by
  `"partOf" not in _resource`. Preserved verbatim.
- **`admission_datetime` missing or unparseable**:
  `_make_synth_ed_enc_dict` catches `(ValueError, TypeError)` and
  returns `admission_datetime=""`. `_build_encounter` skips the period
  block; no crash, no `length` emitted. Matches current graceful
  degrade behaviour.
- **`chief_complaint` empty**: canonical `_build_encounter` skips
  `reasonCode` when the chief complaint is falsy (`encounter.py:285`).
  Same as current.
- **`attending_physician_id` empty**: canonical builder gates
  `participant` emission on truthy IDs (`encounter.py:335-346`); no
  empty-string references produced.
- **`is_readmission` false path**: synth-ED does not pass
  `is_readmission` (canonical default is `False`), so `partOf` is not
  set by the canonical builder either. The synth-ED emitter's own
  `partOf` (set two lines earlier by the caller) is on the primary IMP
  encounter, not on the synth-ED encounter; there is no conflict.
- **canonical `classHistory` / `statusHistory` gating**: both blocks
  gate on `class_code == "IMP"` (`encounter.py:194, 248`); synth-ED
  emits `class_code == "EMER"` so neither fires. Confirmed safe.
- **canonical `diagnosis[]`**: gated on truthy `primary_dx_code`; we
  pass the default empty string. No diagnosis block added.
- **canonical dischargeDisposition auto-fill (`home` fallback)**:
  handled by post-hoc `pop` (DD4 / Q).

## Testing

### Unit tests (new file)

Path: `tests/unit/output/test_fhir_synth_ed_encounter_delegation.py`.

1. **`test_synth_ed_delegated_via_canonical_builder`** — patch
   `_build_encounter`, run `_bb_encounters` on a fixture IMP encounter
   with `admit_source_encounter_id` set, assert the mock is called
   twice (once for the primary IMP, once for the synth-ED bridge).
2. **`test_synth_ed_class_display_matches_canonical`** — for both JP
   and US, assert
   `synth_ed.class.display == _build_encounter({..."encounter_type":"emergency"...}).class.display`.
   Direct regression guard on the silent-drift risk Issue #546 targets.
3. **`test_synth_ed_omits_discharge_disposition`** — assert the synth-ED
   resource has no `hospitalization.dischargeDisposition` key. Includes
   an inline comment pointing at DD2 rationale.
4. **`test_synth_ed_admit_source_uses_registry_display`** — assert
   `synth_ed.hospitalization.admitSource.coding[0].display ==
   code_lookup("hl7-admit-source", "outp", "ja")` (JP) and the
   English equivalent (US). Guards single-source-of-truth.
5. **`test_synth_ed_participant_has_canonical_type`** — assert
   `participant[0].type` exists and matches the canonical
   v3-ParticipationType ATND coding shape.

### Existing test updates

`grep -rn "救急外来\|synth.*ED\|_ed_resource\|_SYNTH_ED_DISPLAYS" tests/`
enumerates the sites needing expected-value updates. Anticipated
locations: any unit test that asserts specific display strings on the
partOf ED Encounter output.

### Cohort byte-diff verification (must run before requesting review)

1. Check out master `f9c774b4515` in a scratch directory; generate:
   ```bash
   clinosim generate -p 30 -s 42 --country JP --format fhir-r4 -o /tmp/baseline-jp
   clinosim generate -p 30 -s 42 --country US --format fhir-r4 -o /tmp/baseline-us
   ```
2. Check out the PR branch; generate the same seeds to `/tmp/pr-{jp,us}`.
3. Diff:
   ```bash
   diff -r /tmp/baseline-jp /tmp/pr-jp -x _generator_metadata.json > /tmp/diff-jp.txt
   diff -r /tmp/baseline-us /tmp/pr-us -x _generator_metadata.json > /tmp/diff-us.txt
   ```
4. Gate:
   - Non-Encounter resources: `diff.txt` must be empty for every other
     resource type (Patient, Condition, MedicationRequest, …).
   - `Encounter.ndjson`: diff limited to the 5 confirmed-diff fields
     (plus any additions observed at spec-time measurement per Data
     Flow section) applied only to synth-ED bridge Encounters.
   - Every diff line must map to an expected shift; unexplained lines
     block merge until root-caused.

### Downstream impact verification (per Section 3 agreement)

**V-D1 — fhir-jp-validator**: run the JP CLINS validator (existing CI
gate script `.github/workflows/*.yml` `JP p=300 seed=300 → eval only
jp_clins_lab_compliance`) on the PR cohort. Expected:

- Validator error count against master baseline: unchanged or lower.
  `dischargeDisposition = "hosp"` was silently emitting an unregistered
  code; its removal may reduce warnings.
- No new error introduced by canonical delegation.

**V-D2 — iris4h-ai consumer**: the copy path per memory
`feedback_iris_ai_copy.md` is `../fhir-jp-validator/fhir_r4/`. Before
merging:

- `grep -rn "dischargeDisposition" ../fhir-jp-validator/ ../iris4h-ai/`
  (or wherever downstream consumers live) to identify any code path
  that reads `dischargeDisposition` on synth-ED bridge Encounters.
- If any consumer branches on that field: file a downstream issue and
  notify the owner; do not silently ship the removal.
- If no consumer branch found: record the grep result in the PR body
  as verification evidence.

**V-D3 — integration suite**: `pytest tests/integration` and any
`-k "synth_ed"` selector must remain green. Any integration test that
asserted the old dischargeDisposition emission needs updating with a
comment referencing this design.

### PR body verification checklist

```markdown
- [ ] `pytest tests/unit` — 3968 baseline + 5 new = 3973 pass
- [ ] `pytest tests/integration` — all pass
- [ ] `mypy clinosim/` strict — clean
- [ ] `ruff==0.16.0 check` + `ruff==0.16.0 format --check` — clean
- [ ] 30-patient seed 42 JP+US cohort diff-r vs master: only expected
      Encounter shifts on synth-ED bridge resources
- [ ] fhir-jp-validator error count vs baseline: unchanged or lower
- [ ] Downstream grep for `dischargeDisposition` on synth-ED
      bridge encounters: no consumer, or downstream owner notified
- [ ] Cohort fingerprint shift documented in PR body with per-field
      before/after
```

## Effort estimate

- Implementation deletions: ~100 LOC (`_SYNTH_ED_DISPLAYS` + helper +
  inline block in `inline_bb.py`).
- Implementation additions: ~40 LOC (`_make_synth_ed_enc_dict` +
  updated call site in `inline_bb.py`).
- New tests: ~150 LOC (5 unit tests in
  `test_fhir_synth_ed_encounter_delegation.py`).
- Verification: ~30 min (cohort diff + downstream grep + validator run).
- Net implementation LOC: ~−60; net complexity: significant reduction
  (one emission path instead of two, one localization chokepoint
  instead of three).

## Severity / priority

`high` per Issue #546 severity. Silent localization drift is
identified in project memory
(`feedback_fhir_localization_variable_mutation_side_effects.md`,
`feedback_rule_text_violates_its_own_rule.md`) as a recurring failure
mode.

## Follow-up issue tracking

The following are explicit non-goals of this PR and should be filed as
separate issues at the time this PR opens:

- **F1** — Update `_ACT_PRIORITY_DISPLAY_JA["EM"]` from `"救急"` to
  `"緊急"` (canonical display accuracy improvement; affects all
  IMP encounters with `priority=EM`).
- **F2** — Delete `AdmitSource.HOSP` enum member (blocked by this
  Issue; unblocked once synth-ED no longer emits `"hosp"` as a
  discharge-disposition code).
- **F3** — Cross-cutting `country_code == "JP"` → `is_jp()` sweep
  across `medications.py` (14 sites), `conditions.py` (4 sites), and
  `types/document.py` (2 sites).
