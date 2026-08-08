# Rehabilitation Plan Document (LOINC 34823-5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add リハビリテーション実施計画書 (rehabilitation plan) as the third and final
chain-2 (厚労省4帳票) document type, gated on already-firing `RehabSession` data for JP
inpatient encounters, with zero changes to the procedure/simulator layer.

**Architecture:** Same 3-layer pattern as `admission_care_plan`/`nutrition_care_plan`:
(1) registry additions (`DocumentType`, `document_type_specs.yaml`, LOINC entry), (2) a
new `document_enricher` dispatch branch gated on `RehabSession` presence per encounter
(third variant of the `admission_once` family — bundled with a small DRY
`_make_doc_stub()` extraction the prior chain's own deferred TODO anticipated), (3) 9
new `TemplateNarrativeGenerator` section builders reading `NarrativeContext.rehab_sessions`
(a new field wired through the live `passes.py` construction path).

**Tech Stack:** Python 3.11+, existing clinosim document module (no new dependencies).

**Design spec:** `docs/superpowers/specs/2026-07-04-rehabilitation-plan-design.md` — read
this first for the "why" behind every decision below (LOINC code rejection reasoning,
MHLW form source, aspirational-scaffold findings). This plan implements that spec exactly;
where this plan and the spec appear to disagree, the discrepancy in Task 3 (below) is a
plan-time correction discovered while reading the actual code — `NarrativeContext` is
built inline in `passes.py`, NOT via the `context.py:build_narrative_context()` factory
the spec's §3a described (that factory is unused dead code, verified by grep — only
referenced by its own unit test and the module README). Task 3 wires the new field into
the actual live path (`passes.py`) and additionally into `context.py` for documentation
consistency, but the latter has no test-observable effect in production.

## Global Constraints

- **AD-30**: CIF/NarrativeContext carries codes/enums, not display text. `RehabSession.activities`
  (raw English phrases) must NOT be rendered into JP narrative sections — use the derived
  `day_post_op` → phase mapping instead (see Task 4).
- **AD-16**: no `random.random()`, no new RNG in this chain (pure read-side document
  generation, no sampling).
- **Canonical single-source rule** (implementation-rules.md §4): the `target_los`-lookup
  arithmetic currently inline in `_build_acp_estimated_los` becomes a shared
  `_estimated_los_days()` helper once this chain becomes its second consumer — do not
  duplicate the calculation.
- **LOINC code must not be fabricated or reused from another document's canonical
  code** — this chain uses `34823-5` (verified via loinc.org 2026-07-04, see design spec
  §2), never `18776-5` (already owns the `admission_care_plan` display).
- **`encounter_types_supported: [inpatient]` only** — `icu` and `rehab_inpatient` are
  both verified-unreachable `EncounterType` values (design spec §1); declaring support
  for them would itself be a new aspirational-scaffold violation.
- Every touched YAML/registry file keeps its existing fail-loud validation working —
  do not weaken `_validate_document_type_specs` or `GENERATION_FREQUENCIES`.
- Run `pytest -m unit` after every task; run the full suite (`pytest -x -q`) at the end
  of Task 4 before considering the chain done.

---

### Task 1: `NarrativeContext.rehab_sessions` field + `DocumentType` enum + LOINC entry

**Note on sequencing:** this task deliberately does NOT touch `SUPPORTED_DOCUMENT_TYPES`
or `document_type_specs.yaml`. `_validate_document_type_specs()`'s Layer 4 check requires
`yaml_keys == SUPPORTED_DOCUMENT_TYPES` **exactly** — if `SUPPORTED_DOCUMENT_TYPES` gained
`REHABILITATION_PLAN` before the YAML gained a matching `rehabilitation_plan:` entry,
`load_document_type_specs()` would raise `ValueError` on every call, breaking
`document_enricher` (and therefore most of the test suite) until the YAML entry landed.
Task 2 adds both together in the same commit so the tree is never in a broken state.

**Files:**
- Modify: `clinosim/types/document.py` (DocumentType enum, NarrativeContext dataclass)
- Modify: `clinosim/modules/document/narrative/registry.py` (GENERATION_FREQUENCIES only
  — NOT SUPPORTED_DOCUMENT_TYPES, see note above)
- Modify: `clinosim/codes/data/loinc.yaml`
- Test: `tests/unit/modules/document/narrative/test_registry.py` (new tests appended)

**Interfaces:**
- Produces: `DocumentType.REHABILITATION_PLAN` (value `"rehabilitation_plan"`);
  `NarrativeContext.rehab_sessions: list[Any]` (default `[]`); LOINC `34823-5` resolves
  via `code_lookup("loinc", "34823-5", "ja") == "リハビリテーション実施計画書"`;
  `"admission_once_if_rehab_sessions"` is a member of `GENERATION_FREQUENCIES`.

- [ ] **Step 1: Write failing registry tests**

Append to `tests/unit/modules/document/narrative/test_registry.py`:

```python
# === chain 2: rehabilitation_plan (LOINC 34823-5) ===

def test_document_type_has_rehabilitation_plan() -> None:
    assert DocumentType.REHABILITATION_PLAN.value == "rehabilitation_plan"


def test_generation_frequencies_includes_admission_once_if_rehab_sessions() -> None:
    from clinosim.modules.document.narrative.registry import GENERATION_FREQUENCIES

    assert "admission_once_if_rehab_sessions" in GENERATION_FREQUENCIES
```

(`DocumentType` import already present at top of file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/modules/document/narrative/test_registry.py -k rehabilitation_plan -v`
Expected: FAIL — `AttributeError: REHABILITATION_PLAN` / `NameError` (enum member and
frequency string don't exist yet).

- [ ] **Step 3: Add `DocumentType.REHABILITATION_PLAN`**

In `clinosim/types/document.py`, in the `DocumentType` enum, after the existing chain-2
entries:

```python
    # β-JP-1 chain 2 (厚労省4帳票, first sub-project)
    ADMISSION_CARE_PLAN = "admission_care_plan"                   # LOINC 18776-5 (verified 2026-07-03)
    NUTRITION_CARE_PLAN = "nutrition_care_plan"                   # LOINC 80791-7 (verified 2026-07-03)
    # β-JP-1 chain 2 (厚労省4帳票, third and final sub-project)
    REHABILITATION_PLAN = "rehabilitation_plan"                   # LOINC 34823-5 (verified 2026-07-04)
```

- [ ] **Step 4: Add `NarrativeContext.rehab_sessions` field**

In `clinosim/types/document.py`, `NarrativeContext` dataclass, add after the existing
`discharge_medications` field (must go after `procedures` since it needs a default and
`procedures` has none — dataclass field-ordering rule):

```python
    # === β-JP-1 chain 2 (rehabilitation_plan, 2026-07-04) ===
    # list[RehabSession] (clinosim/types/procedure.py) — unfiltered, mirrors the
    # existing `procedures` field's record-wide (not per-encounter) scope.
    rehab_sessions: list[Any] = field(default_factory=list)
```

- [ ] **Step 5: Add LOINC entry**

In `clinosim/codes/data/loinc.yaml`, after the `80791-7` entry:

```yaml
  34823-5:
    en: Physical medicine and rehab Note
    ja: リハビリテーション実施計画書
```

- [ ] **Step 6: Add the new generation_frequency (registry.py only, NOT SUPPORTED_DOCUMENT_TYPES)**

In `clinosim/modules/document/narrative/registry.py`:

```python
GENERATION_FREQUENCIES: frozenset[str] = frozenset({
    "admission_once",
    "admission_once_los_gt_7",  # chain 2: nutrition_care_plan (MHLW LOS>7 mandate)
    "admission_once_if_rehab_sessions",  # chain 2: rehabilitation_plan (RehabSession presence gate)
    "daily",
    "daily_3shift",  # α-min-3: 3 nursing notes per LOS day (night/day/evening)
    "discharge_once",
    "encounter_once",
})
```

Do **not** touch `SUPPORTED_DOCUMENT_TYPES` in this step — see the task-level note above.

- [ ] **Step 7: Run new tests to verify they pass**

Run: `pytest tests/unit/modules/document/narrative/test_registry.py -k rehabilitation_plan -v`
Expected: PASS (2 tests).

- [ ] **Step 8: Run the full registry test file + document module unit tests (regression check)**

Run: `pytest tests/unit/modules/document/narrative/test_registry.py -v`
Expected: all PASS unchanged (adding an unused enum member, an unused dataclass field
with a default, an unused LOINC entry, and an unused frequency string are all additive
no-ops — nothing yet reads `DocumentType.REHABILITATION_PLAN` or dispatches on
`admission_once_if_rehab_sessions`).

Run: `pytest tests/unit/modules/document -v`
Expected: all PASS unchanged (confirms `SUPPORTED_DOCUMENT_TYPES` staying untouched
means `load_document_type_specs()` still validates cleanly against the unmodified YAML).

- [ ] **Step 9: Commit**

```bash
git add clinosim/types/document.py clinosim/modules/document/narrative/registry.py \
  clinosim/codes/data/loinc.yaml tests/unit/modules/document/narrative/test_registry.py
git commit -m "feat(chain2): rehabilitation_plan types/LOINC/frequency (registry not yet activated)"
```

---

### Task 2: `document_type_specs.yaml` entry + registry activation + `document_enricher` dispatch branch

**Files:**
- Modify: `clinosim/modules/document/reference_data/document_type_specs.yaml`
- Modify: `clinosim/modules/document/narrative/registry.py` (SUPPORTED_DOCUMENT_TYPES —
  deferred from Task 1, must land together with the YAML entry below)
- Modify: `clinosim/modules/document/engine.py`
- Modify: `tests/unit/modules/document/narrative/test_registry.py` (3 existing
  `bad_data` fixtures need the new key added so they stay valid-except-one-field;
  2 count assertions bump 11→12; 1 inpatient-count assertion bumps 8→9 — all of this
  is safe to do in this task because the real YAML gains the matching entry in the
  same task, so `load_document_type_specs()` never observes a Layer-4 mismatch)
- Test: `tests/unit/modules/document/test_engine_rehabilitation_plan.py` (new)
- Test: `tests/unit/modules/document/narrative/test_encounter_types_supported.py` (new
  test appended)

**Interfaces:**
- Consumes: `DocumentType.REHABILITATION_PLAN`, `"admission_once_if_rehab_sessions"` from
  Task 1.
- Produces: `document_enricher()` emits a `ClinicalDocument(task_type="rehabilitation_plan",
  loinc_code="34823-5")` stub for any JP inpatient encounter with ≥1 `RehabSession`
  sharing its `encounter_id`; `_make_doc_stub()` (new module-level helper in
  `engine.py`) — later tasks do not need this directly (Task 3/4 work in
  `template_generator.py`/`passes.py`, not `engine.py`).

- [ ] **Step 1: Write failing dispatch tests**

Create `tests/unit/modules/document/test_engine_rehabilitation_plan.py`:

```python
"""document_enricher dispatch tests for rehabilitation_plan (chain 2, third
and final chain-2 sub-project).

Covers the NEW admission_once_if_rehab_sessions generation_frequency — proves
BOTH the positive case (RehabSession present -> fires) and the negative case
(no RehabSession -> does not fire), per the nutrition_care_plan adv-1 lesson
(design spec §5). Also proves the encounter_types_supported=[inpatient]-only
scope: icu must NOT fire even with rehab sessions present (design spec §1 —
icu is a verified-unreachable EncounterType value; declaring support for it
would be a new aspirational-scaffold violation).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.engine import document_enricher


def _rehab_session(encounter_id: str, session_date: datetime) -> dict[str, Any]:
    return {
        "session_id": f"REHAB-{encounter_id}-001",
        "patient_id": "pt-rp-engine-test",
        "encounter_id": encounter_id,
        "therapy_type": "PT",
        "session_date": session_date,
        "duration_minutes": 40,
        "day_post_op": 1,
        "activities": ["bed exercises"],
        "patient_participation": "good",
        "pain_score": 3,
        "functional_progress": "stable",
    }


def _make_record(
    encounter_type: str, with_rehab: bool, encounter_id: str = "enc-rp-engine-test"
) -> dict[str, Any]:
    admission_dt = datetime(2026, 7, 1, 10, 0)
    return {
        "patient": {"patient_id": "pt-rp-engine-test"},
        "encounters": [
            {
                "encounter_id": encounter_id,
                "encounter_type": encounter_type,
                "status": "completed",
                "admission_datetime": admission_dt,
                "discharge_datetime": admission_dt + timedelta(days=10),
                "attending_physician_id": "dr-rp-engine-test",
                "primary_nurse_id": "ns-rp-engine-test",
            }
        ],
        "documents": [],
        "extensions": {},
        "physiological_states": [],
        "rehab_sessions": (
            [_rehab_session(encounter_id, admission_dt + timedelta(days=1))]
            if with_rehab
            else []
        ),
    }


def _run_enricher(record: dict[str, Any], country: str) -> dict[str, Any]:
    ctx = SimpleNamespace(
        master_seed=42,
        records=[record],
        config=SimpleNamespace(country=country),
    )
    document_enricher(ctx)
    return record


def _rp_docs(record: dict[str, Any]) -> list[Any]:
    return [d for d in record["documents"] if getattr(d, "task_type", "") == "rehabilitation_plan"]


def test_jp_inpatient_with_rehab_sessions_gets_one_stub() -> None:
    record = _run_enricher(_make_record("inpatient", with_rehab=True), "jp")
    docs = _rp_docs(record)
    assert len(docs) == 1
    assert docs[0].loinc_code == "34823-5"


def test_jp_inpatient_without_rehab_sessions_gets_zero_stubs() -> None:
    record = _run_enricher(_make_record("inpatient", with_rehab=False), "jp")
    assert len(_rp_docs(record)) == 0


def test_jp_icu_with_rehab_sessions_gets_zero_stubs() -> None:
    """icu is not in encounter_types_supported (design spec §1: icu never fires
    in production, declaring support for it would be a new aspirational scaffold)."""
    record = _run_enricher(_make_record("icu", with_rehab=True), "jp")
    assert len(_rp_docs(record)) == 0


def test_us_inpatient_with_rehab_sessions_gets_zero_stubs() -> None:
    record = _run_enricher(_make_record("inpatient", with_rehab=True), "us")
    assert len(_rp_docs(record)) == 0


def test_authored_datetime_is_first_rehab_session_date_not_admission_date() -> None:
    """authored_datetime should reflect when the rehab plan was actually
    assessed (first session date), not the admission date (design spec §3b)."""
    record = _run_enricher(_make_record("inpatient", with_rehab=True), "jp")
    doc = _rp_docs(record)[0]
    assert doc.authored_datetime == "2026-07-02T10:00:00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/modules/document/test_engine_rehabilitation_plan.py -v`
Expected: FAIL — no documents emitted at all (spec not registered in YAML yet, unknown
`generation_frequency` would raise at YAML load if referenced, but since we haven't
added it to the YAML, `specs_for_encounter_type`/`specs_for_country` simply won't
return a `rehabilitation_plan` spec, so `applicable_specs` is empty and 0 documents
are emitted for every case — all 5 assertions comparing `len(...) == 1` fail).

- [ ] **Step 3: Activate `SUPPORTED_DOCUMENT_TYPES` + fix the 3 `bad_data` fixtures + 3 count assertions**

This step and Step 4 (the YAML entry) must land together — `SUPPORTED_DOCUMENT_TYPES`
and the YAML's key set are cross-validated exactly (Layer 4), so adding one without the
other breaks `load_document_type_specs()` for every caller.

In `clinosim/modules/document/narrative/registry.py`:

```python
# α-min-2 scope = 9 doc types (α-min-1 3 + α-min-2 6); chain 2 adds 3 = 12
SUPPORTED_DOCUMENT_TYPES: frozenset[DocumentType] = frozenset({
    # α-min-1
    DocumentType.ADMISSION_HP,
    DocumentType.PROGRESS_NOTE,
    DocumentType.DISCHARGE_SUMMARY,
    # α-min-2 additions
    DocumentType.ADMISSION_NURSING_ASSESSMENT,
    DocumentType.NURSING_SHIFT_NOTE,
    DocumentType.NURSING_DISCHARGE_SUMMARY,
    DocumentType.OUTPATIENT_SOAP,
    DocumentType.ED_NOTE,
    DocumentType.ED_TRIAGE_NOTE,
    # chain 2 additions
    DocumentType.ADMISSION_CARE_PLAN,
    DocumentType.NUTRITION_CARE_PLAN,
    DocumentType.REHABILITATION_PLAN,
})
```

`load_document_type_specs()` requires `yaml_keys == SUPPORTED_DOCUMENT_TYPES` exactly
(Layer 4), so every `bad_data` fixture dict in `test_registry.py` that lists all
currently-known doc types must gain a valid `rehabilitation_plan` entry (the test's
*intentionally* broken field stays on a different key). Add this entry to the `specs`
dict in **all three** of `test_load_raises_on_missing_required_field`,
`test_load_raises_on_null_entry`, and `test_load_raises_on_empty_countries_supported`
(each currently ends with the `nutrition_care_plan` entry — add this block right after
it, before the closing `}` of `specs`):

```python
            "rehabilitation_plan": {
                "loinc_code": "34823-5",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "admission_once_if_rehab_sessions",
            },
```

Then update the two total-count tests and the inpatient-count test:

```python
def test_load_specs_returns_11_total() -> None:
```
→ rename to `test_load_specs_returns_12_total` and change body:
```python
def test_load_specs_returns_12_total() -> None:
    """12 (3 α-min-1 + 6 α-min-2 + 3 chain-2) total specs loaded from YAML."""
    load_document_type_specs.cache_clear()
    specs = load_document_type_specs()
    assert len(specs) == 12, f"Expected 12 specs (3 α-min-1 + 6 α-min-2 + 3 chain-2), got {len(specs)}"
```

```python
def test_supported_document_types_covers_11_entries() -> None:
```
→ rename to `test_supported_document_types_covers_12_entries`:
```python
def test_supported_document_types_covers_12_entries() -> None:
    """SUPPORTED_DOCUMENT_TYPES frozenset has 12 members (α-min-1 3 + α-min-2 6 + chain-2 3)."""
    assert len(SUPPORTED_DOCUMENT_TYPES) == 12
```

```python
def test_specs_for_encounter_type_inpatient_returns_8_specs() -> None:
```
→ rename to `test_specs_for_encounter_type_inpatient_returns_9_specs`:
```python
def test_specs_for_encounter_type_inpatient_returns_9_specs() -> None:
    """3 α-min-1 (no restriction, matches all) + 3 nursing specs + admission_care_plan +
    nutrition_care_plan + rehabilitation_plan (chain 2) = 9 total for inpatient."""
    load_document_type_specs.cache_clear()
    inpatient_specs = specs_for_encounter_type("inpatient")
    assert len(inpatient_specs) == 9, f"Expected 9 inpatient specs, got {len(inpatient_specs)}"
```

Do NOT run tests yet — the YAML entry (Step 4) must land first, otherwise
`load_document_type_specs()` raises `ValueError` (Layer 4 drift) for every test in this
file that loads the real YAML.

- [ ] **Step 4: Add the YAML spec entry**

In `clinosim/modules/document/reference_data/document_type_specs.yaml`, after the
`nutrition_care_plan` entry, add a comment block matching the existing chain-2 style
and the new spec:

```yaml
  # === chain 2 (厚労省4帳票, third and final sub-project, 2026-07-04) ===
  # LOINC 34823-5 verified via loinc.org — "Physical medicine and rehab Note" is a
  # generic PM&R clinical-note code (design spec §2; NOT 18776-5, which already
  # owns the admission_care_plan display — reusing it would be an AD-30-class
  # code/display integrity violation). MHLW form 別紙様式21
  # (https://www.mhlw.go.jp/bunya/iryouhoken/iryouhoken15/dl/h24_02-07-32.pdf)
  # base form (page 1 of 6; variants 21の2〜21の5 excluded, design spec §2).
  # generation_frequency=admission_once_if_rehab_sessions: emitted only when the
  # encounter has ≥1 RehabSession record (design spec §1 — reuses the existing
  # post-surgical RehabSession data rather than the never-fired rehab_inpatient/icu
  # ward-transfer scaffold). encounter_types_supported=[inpatient] only for the
  # same reason. 6 of 9 sections are data-driven (design spec §3e).
  rehabilitation_plan:
    loinc_code: "34823-5"
    format_type: composition
    countries_supported: [jp]
    encounter_types_supported: [inpatient]
    generation_frequency: admission_once_if_rehab_sessions
    composition_sections:
      - patient_and_diagnosis
      - rehab_team
      - functional_status
      - basic_movement
      - session_frequency
      - goals
      - policy
      - discharge_estimate
      - explanation_consent
    stage2_strategy: template_only
    llm_enabled_sections: []
```

- [ ] **Step 5: Run the registry test file (now green — YAML and SUPPORTED_DOCUMENT_TYPES landed together)**

Run: `pytest tests/unit/modules/document/narrative/test_registry.py -v`
Expected: all PASS, **including** `test_load_specs_returns_12_total`,
`test_supported_document_types_covers_12_entries`, and
`test_specs_for_encounter_type_inpatient_returns_9_specs` from Step 3.

Run: `pytest tests/unit/modules/document -v`
Expected: all PASS (no other doc-type tests regressed from the new YAML entry).

- [ ] **Step 6: Extract `_make_doc_stub()` and add the dispatch branch**

In `clinosim/modules/document/engine.py`, add a module-level helper function right
after `_compute_los_days` (before the `# Enricher entry point` section comment):

```python
def _make_doc_stub(
    spec: Any, encounter_id: str, doc_seq: int, dt: datetime,
    pid: str, lang: str, author: str,
) -> ClinicalDocument:
    """Shared ClinicalDocument construction for the admission_once family of
    generation_frequency branches (admission_once / admission_once_los_gt_7 /
    admission_once_if_rehab_sessions) — all three set authored_datetime ==
    period_start == period_end to the same instant `dt`. Extracted once a
    third variant landed (rehabilitation_plan design spec §3b), closing the
    nutrition_care_plan chain's PR #139 deferred TODO ("LOS-gated
    document_enricher pattern") — mechanical refactor, no behavior change to
    the two existing call sites (admission_dt in, identical ClinicalDocument
    out).
    """
    return ClinicalDocument(
        document_id=f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}",
        task_type=spec.type_key,
        loinc_code=spec.loinc_code,
        patient_id=pid,
        encounter_id=encounter_id,
        author_practitioner_id=author,
        authored_datetime=dt.isoformat(),
        period_start=dt.isoformat(),
        period_end=dt.isoformat(),
        language=lang,
        format_type=spec.format_type.value,
        narrative=None,
    )
```

Replace the `admission_once` branch body (currently constructs `ClinicalDocument(...)`
inline) with:

```python
                if freq == "admission_once":
                    documents.append(_make_doc_stub(
                        spec, encounter_id, doc_seq, admission_dt, pid, lang,
                        _pick_document_author(spec, encounter),
                    ))
                    doc_seq += 1
```

Replace the `admission_once_los_gt_7` branch body identically (keep the `if los_days <= 7:
continue` guard, just swap the inline `ClinicalDocument(...)` construction for the
helper call):

```python
                elif freq == "admission_once_los_gt_7":
                    # MHLW mandate: 栄養管理計画書 required only for admissions
                    # > 7 days (design spec §3a). Mirrors the `daily` branch's
                    # LOS-skip pattern below.
                    if los_days <= 7:
                        continue
                    documents.append(_make_doc_stub(
                        spec, encounter_id, doc_seq, admission_dt, pid, lang,
                        _pick_document_author(spec, encounter),
                    ))
                    doc_seq += 1
```

Add the new branch immediately after (before the `elif freq == "daily":` branch):

```python
                elif freq == "admission_once_if_rehab_sessions":
                    # MHLW 別紙様式21: rehabilitation plan required only when the
                    # patient is actually receiving disease-specific rehab therapy
                    # (design spec §1 — reuses the existing RehabSession data
                    # rather than the never-fired rehab_inpatient ward-transfer
                    # scaffold). authored_datetime = first rehab session's date,
                    # NOT admission_dt (the plan is assessed when rehab starts,
                    # which is POD1+ per generate_rehab_sessions, not at admission).
                    enc_rehab_sessions = [
                        s for s in (_o(record, "rehab_sessions", []) or [])
                        if _o(s, "encounter_id", "") == encounter_id
                    ]
                    if not enc_rehab_sessions:
                        continue
                    first_session_dt = min(
                        _o(s, "session_date", admission_dt) for s in enc_rehab_sessions
                    )
                    documents.append(_make_doc_stub(
                        spec, encounter_id, doc_seq, first_session_dt, pid, lang,
                        _pick_document_author(spec, encounter),
                    ))
                    doc_seq += 1
```

Also update the module docstring's "Supported generation_frequency values" list near
the top of the file (after `admission_once_los_gt_7 → ...`):

```python
  admission_once_if_rehab_sessions → 1 document at the first RehabSession's
                    date, only if the encounter has ≥1 RehabSession record
                    (chain 2: rehabilitation_plan, MHLW 別紙様式21)
```

- [ ] **Step 7: Run the new dispatch tests**

Run: `pytest tests/unit/modules/document/test_engine_rehabilitation_plan.py -v`
Expected: PASS (5 tests).

- [ ] **Step 8: Regression-check the two refactored branches**

Run: `pytest tests/unit/modules/document/test_engine_admission_care_plan.py tests/unit/modules/document/test_engine_nutrition_care_plan.py -v`
Expected: all PASS unchanged (the `_make_doc_stub` extraction must not alter
`admission_once`/`admission_once_los_gt_7` output — same `document_id`/`authored_datetime`/
`period_start`/`period_end` values as before).

- [ ] **Step 9: Run the encounter-type-gating test suite and add the new gating test**

Append to `tests/unit/modules/document/narrative/test_encounter_types_supported.py`,
after `test_nutrition_care_plan_excludes_rehab_inpatient`:

```python
def test_rehabilitation_plan_is_inpatient_only() -> None:
    """rehabilitation_plan does NOT declare icu or rehab_inpatient support —
    both are verified-unreachable EncounterType values in production (design
    spec §1); declaring support for them would be a new aspirational-scaffold
    violation, unlike admission_care_plan/nutrition_care_plan which legitimately
    support icu (a real, if narrow, dispatch path)."""
    from clinosim.modules.document.narrative.registry import load_document_type_specs
    from clinosim.types.document import DocumentType

    specs = load_document_type_specs()
    rp = specs[DocumentType.REHABILITATION_PLAN]
    assert set(rp.encounter_types_supported) == {"inpatient"}

    inpatient_keys = {s.type_key for s in specs_for_encounter_type("inpatient")}
    icu_keys = {s.type_key for s in specs_for_encounter_type("icu")}
    rehab_keys = {s.type_key for s in specs_for_encounter_type("rehab_inpatient")}
    outpatient_keys = {s.type_key for s in specs_for_encounter_type("outpatient")}
    assert "rehabilitation_plan" in inpatient_keys
    assert "rehabilitation_plan" not in icu_keys
    assert "rehabilitation_plan" not in rehab_keys
    assert "rehabilitation_plan" not in outpatient_keys
```

Run: `pytest tests/unit/modules/document/narrative/test_encounter_types_supported.py tests/unit/modules/document/narrative/test_registry.py -v`
Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add clinosim/modules/document/reference_data/document_type_specs.yaml \
  clinosim/modules/document/narrative/registry.py \
  tests/unit/modules/document/narrative/test_registry.py \
  clinosim/modules/document/engine.py \
  tests/unit/modules/document/test_engine_rehabilitation_plan.py \
  tests/unit/modules/document/narrative/test_encounter_types_supported.py
git commit -m "feat(chain2): rehabilitation_plan dispatch branch + _make_doc_stub DRY refactor"
```

---

### Task 3: `passes.py` context wiring + `template_generator.py` section builders

**Files:**
- Modify: `clinosim/modules/document/narrative/passes.py`
- Modify: `clinosim/modules/document/narrative/context.py` (parity only, dead-code path)
- Modify: `clinosim/modules/document/narrative/template_generator.py`
- Test: `tests/unit/modules/document/narrative/test_template_generator_rehabilitation_plan.py` (new)
- Test: `tests/unit/modules/document/narrative/test_context.py` (small addition for parity)

**Interfaces:**
- Consumes: `NarrativeContext.rehab_sessions` (Task 1), `DocumentType.REHABILITATION_PLAN`
  (Task 1), `rehabilitation_plan`'s 9 `composition_sections` (Task 2 YAML).
- Produces: `TemplateNarrativeGenerator._build_rp_*` (9 methods) +
  `TemplateNarrativeGenerator._estimated_los_days()` (shared helper, 2nd use extracted
  from `_build_acp_estimated_los`) — no other task depends on these directly.

- [ ] **Step 1: Write failing section-builder tests**

Create `tests/unit/modules/document/narrative/test_template_generator_rehabilitation_plan.py`:

```python
"""Tests for TemplateNarrativeGenerator rehabilitation_plan sections (chain 2,
third and final chain-2 sub-project).

Mirrors tests/unit/modules/document/narrative/test_template_generator_nutrition_care_plan.py.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, FormatType, NarrativeContext
from clinosim.types.patient import PatientProfile

_RP_SECTIONS = (
    "patient_and_diagnosis", "rehab_team", "functional_status", "basic_movement",
    "session_frequency", "goals", "policy", "discharge_estimate", "explanation_consent",
)


def _make_spec() -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key="rehabilitation_plan",
        loinc_code="34823-5",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp",),
        generation_frequency="admission_once_if_rehab_sessions",
        composition_sections=_RP_SECTIONS,
        encounter_types_supported=("inpatient",),
        stage2_strategy="template_only",
    )


def _make_encounter() -> Any:
    return SimpleNamespace(
        encounter_id="enc-rp-test",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        attending_physician_id="dr-rp-001",
    )


def _rehab_session(
    day_post_op: int = 1,
    session_date: datetime = datetime(2026, 7, 2, 10, 0),
    functional_progress: str = "stable",
    patient_participation: str = "good",
    pain_score: int | None = 3,
    duration_minutes: int = 40,
    therapy_type: str = "PT",
) -> dict[str, Any]:
    return {
        "session_id": f"REHAB-test-{day_post_op:03d}",
        "patient_id": "pt-rp-test",
        "encounter_id": "enc-rp-test",
        "therapy_type": therapy_type,
        "session_date": session_date,
        "duration_minutes": duration_minutes,
        "day_post_op": day_post_op,
        "activities": ["bed exercises"],
        "patient_participation": patient_participation,
        "pain_score": pain_score,
        "functional_progress": functional_progress,
    }


def _make_ctx(
    encounter: Any = None,
    rehab_sessions: list[Any] | None = None,
    target_lang: str = "ja",
    locale: str = "jp",
) -> NarrativeContext:
    return NarrativeContext(
        patient=PatientProfile(patient_id="pt-rp-test"),
        encounter=encounter or _make_encounter(),
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=10,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.REHABILITATION_PLAN,
        target_lang=target_lang,
        locale=locale,
        rehab_sessions=rehab_sessions if rehab_sessions is not None else [_rehab_session()],
    )


def test_rehabilitation_plan_returns_all_9_sections_non_empty() -> None:
    spec = _make_spec()
    ctx = _make_ctx()
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert isinstance(out.sections, dict)
    for section in _RP_SECTIONS:
        assert section in out.sections, f"section {section!r} missing"
        assert out.sections[section].strip() != "", f"section {section!r} is empty"


def test_rehabilitation_plan_jp_has_japanese_text() -> None:
    spec = _make_spec()
    ctx = _make_ctx(target_lang="ja", locale="jp")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    all_text = " ".join(out.sections.values())
    has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in all_text)
    assert has_jp, f"rehabilitation_plan sections contain no Japanese text: {all_text[:300]!r}"


def test_rehabilitation_plan_en_no_crash() -> None:
    spec = _make_spec()
    ctx = _make_ctx(target_lang="en", locale="us")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    for section in _RP_SECTIONS:
        assert out.sections[section].strip() != ""


def test_rehab_team_lists_therapy_type() -> None:
    spec = _make_spec()
    ctx = _make_ctx(rehab_sessions=[_rehab_session(therapy_type="PT")])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "PT" in out.sections["rehab_team"]


def test_rehab_team_fallback_when_no_sessions() -> None:
    spec = _make_spec()
    ctx = _make_ctx(rehab_sessions=[])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.sections["rehab_team"].strip() != ""


def test_functional_status_reflects_latest_session() -> None:
    spec = _make_spec()
    older = _rehab_session(
        day_post_op=1, session_date=datetime(2026, 7, 2, 10, 0),
        functional_progress="stable", pain_score=6,
    )
    latest = _rehab_session(
        day_post_op=5, session_date=datetime(2026, 7, 6, 10, 0),
        functional_progress="improved", pain_score=2,
    )
    ctx = _make_ctx(rehab_sessions=[older, latest])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "改善" in out.sections["functional_status"]
    assert "2/10" in out.sections["functional_status"]


def test_basic_movement_early_phase_for_day_post_op_1() -> None:
    spec = _make_spec()
    ctx = _make_ctx(rehab_sessions=[_rehab_session(day_post_op=1)])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "早期" in out.sections["basic_movement"]


def test_basic_movement_late_phase_for_day_post_op_20() -> None:
    spec = _make_spec()
    ctx = _make_ctx(rehab_sessions=[_rehab_session(day_post_op=20)])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "後期" in out.sections["basic_movement"]


def test_session_frequency_counts_and_dates() -> None:
    spec = _make_spec()
    s1 = _rehab_session(day_post_op=1, session_date=datetime(2026, 7, 2, 10, 0))
    s2 = _rehab_session(day_post_op=2, session_date=datetime(2026, 7, 3, 10, 0))
    ctx = _make_ctx(rehab_sessions=[s1, s2])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "2" in out.sections["session_frequency"]
    assert "2026-07-02" in out.sections["session_frequency"]
    assert "2026-07-03" in out.sections["session_frequency"]


def test_discharge_estimate_uses_los_days_fallback_when_no_disease_protocol() -> None:
    spec = _make_spec()
    ctx = _make_ctx()
    ctx.los_days = 14
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "14" in out.sections["discharge_estimate"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/modules/document/narrative/test_template_generator_rehabilitation_plan.py -v`
Expected: FAIL — `"rehabilitation_plan"` section keys not in `section_builders` dict yet,
so `_render_composition_sections` falls through to the generic fallback text for all 9
sections (tests asserting specific content like `"PT"`, `"早期"`, counts, etc. fail;
the "non-empty" tests may pass by coincidence via the generic fallback — that's fine,
the content-specific tests are the ones that must currently fail).

- [ ] **Step 3: Wire `rehab_sessions` into the live context-construction path**

In `clinosim/modules/document/narrative/passes.py`, in `_build_context()`, add one line
after the existing `procedures=` line:

```python
            procedures=patient_dict.get("procedures", []) or [],
            rehab_sessions=patient_dict.get("rehab_sessions", []) or [],
            allergies=_o(patient_dict.get("patient") or {}, "allergies", []) or [],
```

For documentation-consistency parity (this path is currently dead code — verified via
grep, only reached from its own unit test — but keeping it in sync avoids a
misleading, half-updated "canonical factory" the module README still points to), in
`clinosim/modules/document/narrative/context.py`, add one line to
`build_narrative_context()`'s `NarrativeContext(...)` call after the existing
`procedures=` line:

```python
        procedures=_o(record, "procedures", []) or [],
        rehab_sessions=_o(record, "rehab_sessions", []) or [],
        allergies=allergies or [],
```

Add one assertion to `tests/unit/modules/document/narrative/test_context.py` (open the
file first to find an existing test asserting on `ctx.procedures` and add a sibling
assertion in the same test for `ctx.rehab_sessions`, following whatever fixture-record
shape that test already uses — if the existing fixture record has no `"rehab_sessions"`
key, assert the default-empty-list behavior: `assert ctx.rehab_sessions == []`).

- [ ] **Step 4: Extract `_estimated_los_days()` from `_build_acp_estimated_los`**

In `clinosim/modules/document/narrative/template_generator.py`, replace the body of
`_build_acp_estimated_los` (currently computes `los` inline) with a new shared helper
plus a thin wrapper. Replace:

```python
    def _build_acp_estimated_los(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """推定される入院期間 — disease_protocol.target_los[country][severity].mean
        when available: a genuine day-0 estimate, RNG-free (target_los is a static
        YAML dict, read directly with no sampling — adv-1 finding: the original
        implementation used ctx.los_days, the already-realized LOS, which is
        tautologically 100% accurate and therefore unrealistic for a document
        meant to represent an AT-ADMISSION prediction). Falls back to ctx.los_days
        only when disease_protocol is unavailable (e.g. unknown-condition path)."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        los: float = 0
        proto = ctx.disease_protocol
        if proto is not None:
            country_key = "japan" if ctx.locale == "jp" else "us"
            target_los = _o(proto, "target_los", {}) or {}
            los_cfg = (target_los.get(country_key) or {}).get(ctx.severity) or {}
            if "mean" in los_cfg:
                los = los_cfg["mean"]
                facts.append("disease_protocol.target_los")
        if not los:
            los = ctx.los_days or 1
            facts.append("ctx.los_days")
        los_days = round(los)
        if is_ja:
            return f"推定入院期間：約{los_days}日間", facts
        return f"Estimated length of stay: approximately {los_days} days", facts
```

with:

```python
    def _estimated_los_days(self, ctx: NarrativeContext) -> tuple[int, list[str]]:
        """disease_protocol.target_los[country][severity].mean → whole days,
        RNG-free (target_los is a static YAML dict, read with no sampling —
        adv-1 finding on admission_care_plan: ctx.los_days, the already-realized
        LOS, is tautologically 100% accurate and unrealistic for a document
        meant to represent an AT-ADMISSION prediction). Falls back to
        ctx.los_days only when disease_protocol is unavailable.

        Shared by _build_acp_estimated_los and _build_rp_discharge_estimate —
        extracted once rehabilitation_plan became the 2nd consumer
        (implementation-rules.md §4 canonical single-source rule)."""
        facts: list[str] = []
        los: float = 0
        proto = ctx.disease_protocol
        if proto is not None:
            country_key = "japan" if ctx.locale == "jp" else "us"
            target_los = _o(proto, "target_los", {}) or {}
            los_cfg = (target_los.get(country_key) or {}).get(ctx.severity) or {}
            if "mean" in los_cfg:
                los = los_cfg["mean"]
                facts.append("disease_protocol.target_los")
        if not los:
            los = ctx.los_days or 1
            facts.append("ctx.los_days")
        return round(los), facts

    def _build_acp_estimated_los(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """推定される入院期間 — see _estimated_los_days for the shared calculation."""
        is_ja = ctx.target_lang == "ja"
        los_days, facts = self._estimated_los_days(ctx)
        if is_ja:
            return f"推定入院期間：約{los_days}日間", facts
        return f"Estimated length of stay: approximately {los_days} days", facts
```

Run: `pytest tests/unit/modules/document/narrative/test_template_generator_admission_care_plan.py -v`
Expected: all PASS unchanged (pure extract-method refactor, identical output).

- [ ] **Step 5: Add the `_RP_*` fallback/label constants**

In `clinosim/modules/document/narrative/template_generator.py`, after the existing
`_NCP_DISCHARGE_EVAL_FALLBACK_EN` block (around line 285), add:

```python
_RP_TEAM_FALLBACK_JA = "リハビリ実施なし"
_RP_TEAM_FALLBACK_EN = "No rehabilitation therapy on record"
_RP_THERAPIST_FALLBACK_JA = "担当者未定"
_RP_THERAPIST_FALLBACK_EN = "Named therapist: not yet assigned"
_RP_FUNCTIONAL_FALLBACK_JA = "機能評価：記録なし"
_RP_FUNCTIONAL_FALLBACK_EN = "Functional assessment: no record"
_RP_MOVEMENT_FALLBACK_JA = "基本動作：記録なし"
_RP_MOVEMENT_FALLBACK_EN = "Basic movement: no record"
_RP_FREQUENCY_FALLBACK_JA = "実施回数：記録なし"
_RP_FREQUENCY_FALLBACK_EN = "Session frequency: no record"
_RP_GOALS_FALLBACK_JA = (
    "本人の希望：現在の身体機能の回復・自宅復帰を希望／"
    "家族の希望：早期の日常生活動作自立を希望"
)
_RP_GOALS_FALLBACK_EN = (
    "Patient goal: recovery of function and return home / "
    "Family goal: early independence in activities of daily living"
)
_RP_POLICY_FALLBACK_JA = (
    "リハビリテーション治療方針：疾患特異的リハビリテーションを継続し、"
    "日常生活動作の自立度向上を図る"
)
_RP_POLICY_FALLBACK_EN = (
    "Rehabilitation policy: continue disease-specific rehabilitation therapy "
    "to improve independence in activities of daily living"
)
_RP_EXPLANATION_FALLBACK_JA = "本人・家族への説明：説明予定"
_RP_EXPLANATION_FALLBACK_EN = "Explanation to patient/family: pending"

_RP_THERAPY_TYPE_JA = {"PT": "理学療法(PT)", "OT": "作業療法(OT)", "ST": "言語聴覚療法(ST)"}
_RP_THERAPY_TYPE_EN = {
    "PT": "Physical therapy (PT)", "OT": "Occupational therapy (OT)", "ST": "Speech therapy (ST)",
}
_RP_PROGRESS_JA = {"improved": "改善", "stable": "維持", "unable_to_assess": "評価不能"}
_RP_PROGRESS_EN = {
    "improved": "improved", "stable": "stable", "unable_to_assess": "unable to assess",
}
_RP_PARTICIPATION_JA = {"good": "良好", "fair": "やや不良", "refused": "拒否"}
_RP_PARTICIPATION_EN = {"good": "good", "fair": "fair", "refused": "refused"}
_RP_PHASE_JA = {
    "early": "早期(ベッド上運動・座位保持練習)",
    "mid": "中期(歩行器歩行・移乗動作練習)",
    "late": "後期(独立歩行・ADL練習)",
}
_RP_PHASE_EN = {
    "early": "Early phase (bed exercises, sitting practice)",
    "mid": "Mid phase (walker ambulation, transfer training)",
    "late": "Late phase (independent ambulation, ADL practice)",
}
```

- [ ] **Step 6: Add the 9 `_build_rp_*` methods**

Add these methods after the last `_build_ncp_*` method (`_build_ncp_discharge_evaluation`,
around line 1548) in `clinosim/modules/document/narrative/template_generator.py`:

```python
    # ─────────────────────────────────────────────────────────────────
    # chain 2: REHABILITATION_PLAN sections (LOINC 34823-5)
    # ─────────────────────────────────────────────────────────────────

    def _build_rp_patient_and_diagnosis(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """患者・原因疾患 — reuses admission_care_plan's diagnosis extraction
        (same ctx.diagnoses source, design spec §3e)."""
        return self._build_acp_diagnosis(ctx)

    def _build_rp_rehab_team(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """リハ担当医・PT・OT・ST — therapy_type set from ctx.rehab_sessions.
        generate_rehab_sessions (modules/procedure/engine.py) currently only
        produces "PT" — this renders whatever therapy types are actually
        present rather than implying multi-disciplinary coverage that doesn't
        exist (design spec §3e / §4 out-of-scope note)."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        therapy_types = sorted({
            str(_o(s, "therapy_type", "") or "") for s in (ctx.rehab_sessions or [])
            if _o(s, "therapy_type", "")
        })
        if not therapy_types:
            return (_RP_TEAM_FALLBACK_JA if is_ja else _RP_TEAM_FALLBACK_EN), facts
        facts.append("ctx.rehab_sessions")
        labels = _RP_THERAPY_TYPE_JA if is_ja else _RP_THERAPY_TYPE_EN
        joined = ("、" if is_ja else ", ").join(labels.get(t, t) for t in therapy_types)
        therapist_note = _RP_THERAPIST_FALLBACK_JA if is_ja else _RP_THERAPIST_FALLBACK_EN
        if is_ja:
            return f"担当リハビリ職種：{joined}／{therapist_note}", facts
        return f"Rehab discipline(s): {joined} / {therapist_note}", facts

    def _build_rp_functional_status(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """機能評価 — latest (by session_date) session's functional_progress /
        patient_participation / pain_score."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        sessions = ctx.rehab_sessions or []
        if not sessions:
            return (_RP_FUNCTIONAL_FALLBACK_JA if is_ja else _RP_FUNCTIONAL_FALLBACK_EN), facts
        latest = max(sessions, key=lambda s: _o(s, "session_date", datetime(1970, 1, 1)))
        facts.append("ctx.rehab_sessions")
        progress = str(_o(latest, "functional_progress", "") or "")
        participation = str(_o(latest, "patient_participation", "") or "")
        pain = _o(latest, "pain_score", None)
        progress_label = (_RP_PROGRESS_JA if is_ja else _RP_PROGRESS_EN).get(progress, progress)
        participation_label = (
            _RP_PARTICIPATION_JA if is_ja else _RP_PARTICIPATION_EN
        ).get(participation, participation)
        pain_text = f"{pain}/10" if pain is not None else ("評価なし" if is_ja else "not assessed")
        if is_ja:
            return (
                f"機能的改善度：{progress_label}／リハビリへの参加度：{participation_label}／"
                f"疼痛スコア：{pain_text}"
            ), facts
        return (
            f"Functional progress: {progress_label} / Participation: {participation_label} / "
            f"Pain score: {pain_text}"
        ), facts

    def _build_rp_basic_movement(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """基本動作 — day_post_op から phase (early/mid/late) を再導出。
        generate_rehab_sessions (modules/procedure/engine.py) が内部で使う閾値
        (<=3 early, <=14 mid, else late) と同一 — RehabSession に phase フィールド
        はないため再計算する。AD-30: RehabSession.activities の生英語文は使わない
        (design spec §4)。"""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        sessions = ctx.rehab_sessions or []
        if not sessions:
            return (_RP_MOVEMENT_FALLBACK_JA if is_ja else _RP_MOVEMENT_FALLBACK_EN), facts
        latest = max(sessions, key=lambda s: _o(s, "session_date", datetime(1970, 1, 1)))
        facts.append("ctx.rehab_sessions")
        day_post_op = _o(latest, "day_post_op", 0) or 0
        if day_post_op <= 3:
            phase = "early"
        elif day_post_op <= 14:
            phase = "mid"
        else:
            phase = "late"
        return (_RP_PHASE_JA if is_ja else _RP_PHASE_EN)[phase], facts

    def _build_rp_session_frequency(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """実施回数・期間・1回あたりの時間。"""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        sessions = ctx.rehab_sessions or []
        if not sessions:
            return (_RP_FREQUENCY_FALLBACK_JA if is_ja else _RP_FREQUENCY_FALLBACK_EN), facts
        facts.append("ctx.rehab_sessions")
        dates = [_o(s, "session_date", datetime(1970, 1, 1)) for s in sessions]
        first_date, last_date = min(dates), max(dates)
        duration = _o(sessions[0], "duration_minutes", 0) or 0
        count = len(sessions)
        if is_ja:
            return (
                f"実施回数：{count}回（{first_date.date().isoformat()}〜"
                f"{last_date.date().isoformat()}）、1回あたり{duration}分"
            ), facts
        return (
            f"Sessions: {count} ({first_date.date().isoformat()} to "
            f"{last_date.date().isoformat()}), {duration} min each"
        ), facts

    def _build_rp_goals(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """本人の希望・家族の希望 — CIF に患者意向を表すフィールドなし
        (design spec §3d)、固定フォールバック。"""
        is_ja = ctx.target_lang == "ja"
        return (_RP_GOALS_FALLBACK_JA if is_ja else _RP_GOALS_FALLBACK_EN), []

    def _build_rp_policy(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """リハビリテーション治療方針 — 固定フォールバック(design spec §3d)。"""
        is_ja = ctx.target_lang == "ja"
        return (_RP_POLICY_FALLBACK_JA if is_ja else _RP_POLICY_FALLBACK_EN), []

    def _build_rp_discharge_estimate(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """リハビリテーション終了の目安・時期 — _estimated_los_days を再利用
        (admission_care_plan の estimated_los と同じ target_los データ、
        リハ完了フレーミングの文言のみ異なる)。"""
        is_ja = ctx.target_lang == "ja"
        los_days, facts = self._estimated_los_days(ctx)
        if is_ja:
            return f"リハビリテーション終了の目安：入院後約{los_days}日", facts
        return (
            f"Estimated rehabilitation completion: approximately {los_days} days post-admission"
        ), facts

    def _build_rp_explanation_consent(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """本人・家族への説明(署名欄) — 固定フォールバック
        (admission_care_plan/nutrition_care_plan と同じ signature-block pattern)。"""
        is_ja = ctx.target_lang == "ja"
        return (_RP_EXPLANATION_FALLBACK_JA if is_ja else _RP_EXPLANATION_FALLBACK_EN), []
```

- [ ] **Step 7: Register the 9 sections in `section_builders`**

In `_render_composition_sections`, add after the `# chain 2: NUTRITION_CARE_PLAN sections`
block:

```python
            # chain 2: REHABILITATION_PLAN sections (LOINC 34823-5)
            "patient_and_diagnosis": self._build_rp_patient_and_diagnosis,
            "rehab_team": self._build_rp_rehab_team,
            "functional_status": self._build_rp_functional_status,
            "basic_movement": self._build_rp_basic_movement,
            "session_frequency": self._build_rp_session_frequency,
            "goals": self._build_rp_goals,
            "policy": self._build_rp_policy,
            "discharge_estimate": self._build_rp_discharge_estimate,
            "explanation_consent": self._build_rp_explanation_consent,
```

- [ ] **Step 8: Run the new and regression tests**

Run: `pytest tests/unit/modules/document/narrative/test_template_generator_rehabilitation_plan.py tests/unit/modules/document/narrative/test_template_generator_admission_care_plan.py tests/unit/modules/document/narrative/test_template_generator_nutrition_care_plan.py tests/unit/modules/document/narrative/test_context.py -v`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add clinosim/modules/document/narrative/passes.py \
  clinosim/modules/document/narrative/context.py \
  clinosim/modules/document/narrative/template_generator.py \
  tests/unit/modules/document/narrative/test_template_generator_rehabilitation_plan.py \
  tests/unit/modules/document/narrative/test_context.py
git commit -m "feat(chain2): rehabilitation_plan template sections + shared _estimated_los_days"
```

---

### Task 4: LLM sync, audit proof, integration test, TODO.md, golden regen, full suite

**Files:**
- Modify: `clinosim/modules/llm_service/engine.py`
- Modify: `clinosim/modules/document/audit.py`
- Test: `tests/integration/test_rehabilitation_plan_chain.py` (new)
- Modify: `TODO.md`

**Interfaces:**
- Consumes: everything from Tasks 1-3.
- Produces: nothing further downstream — this is the closing task.

- [ ] **Step 1: Sync `LLMTaskType` / `TASK_CATEGORY` / `DOCUMENT_LOINC`**

In `clinosim/modules/llm_service/engine.py`, in the `LLMTaskType` enum, after
`NUTRITION_CARE_PLAN`:

```python
    ADMISSION_CARE_PLAN = "admission_care_plan"                    # LOINC 18776-5
    NUTRITION_CARE_PLAN = "nutrition_care_plan"                    # LOINC 80791-7
    REHABILITATION_PLAN = "rehabilitation_plan"                    # LOINC 34823-5
```

In `TASK_CATEGORY`, after `LLMTaskType.NUTRITION_CARE_PLAN`:

```python
    LLMTaskType.ADMISSION_CARE_PLAN: LLMTaskCategory.NARRATIVE,
    LLMTaskType.NUTRITION_CARE_PLAN: LLMTaskCategory.NARRATIVE,
    LLMTaskType.REHABILITATION_PLAN: LLMTaskCategory.NARRATIVE,
```

In `DOCUMENT_LOINC`, after `LLMTaskType.NUTRITION_CARE_PLAN`:

```python
    LLMTaskType.ADMISSION_CARE_PLAN: "18776-5",           # Plan of care note
    LLMTaskType.NUTRITION_CARE_PLAN: "80791-7",           # Nutrition and dietetics Plan of care note
    LLMTaskType.REHABILITATION_PLAN: "34823-5",           # Physical medicine and rehab Note
```

Run: `python -c "import clinosim.modules.llm_service.engine"`
Expected: no `ImportError` (the `_validate_document_task_sync()` call at module import
time passes — if you forgot a step above it raises immediately here, before any test
runs).

- [ ] **Step 2: Add `_proof_rehabilitation_plan` to `audit.py`**

In `clinosim/modules/document/audit.py`, after `_proof_nutrition_care_plan` (before
`_build_document_proof`):

```python
def _proof_rehabilitation_plan() -> dict[str, Any]:
    """chain 2: prove the rehabilitation_plan RehabSession-presence + JP-only +
    inpatient-only gate fires.

    Four synthetic encounters (JP inpatient with rehab sessions, JP inpatient
    without, US inpatient with rehab sessions, JP icu with rehab sessions) run
    through document_enricher; proves the positive dispatch (rehab sessions
    present -> fires), the negative dispatch (no rehab sessions -> does not
    fire), the country gate (non-JP does not fire even with sessions present),
    and the encounter-type gate (icu does not fire even with sessions present
    — unlike admission_care_plan/nutrition_care_plan, icu is NOT in this
    spec's encounter_types_supported since it's a verified-unreachable
    EncounterType value, design spec §1) — same both-directions discipline as
    _proof_nutrition_care_plan, extended with the icu negative check specific
    to this spec's narrower scope.
    """
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from clinosim.modules.document.engine import document_enricher

    def _run(encounter_type: str, country: str, with_rehab: bool) -> int:
        admission_dt = datetime(2026, 7, 1, 10, 0)
        encounter_id = f"enc-rp-proof-{encounter_type}-{country}-{with_rehab}"
        rehab_sessions = (
            [{
                "session_id": "REHAB-rp-proof-001",
                "patient_id": "pt-rp-proof",
                "encounter_id": encounter_id,
                "therapy_type": "PT",
                "session_date": admission_dt + timedelta(days=1),
                "duration_minutes": 40,
                "day_post_op": 1,
                "activities": [],
                "patient_participation": "good",
                "pain_score": 3,
                "functional_progress": "stable",
            }]
            if with_rehab
            else []
        )
        record: dict[str, Any] = {
            "patient": {"patient_id": "pt-rp-proof"},
            "encounters": [
                {
                    "encounter_id": encounter_id,
                    "encounter_type": encounter_type,
                    "status": "completed",
                    "admission_datetime": admission_dt,
                    "discharge_datetime": admission_dt + timedelta(days=10),
                    "attending_physician_id": "dr-rp-proof",
                    "primary_nurse_id": "ns-rp-proof",
                }
            ],
            "documents": [],
            "extensions": {},
            "physiological_states": [],
            "rehab_sessions": rehab_sessions,
        }
        ctx = SimpleNamespace(
            master_seed=42, records=[record], config=SimpleNamespace(country=country)
        )
        document_enricher(ctx)
        return len([
            d for d in record["documents"] if getattr(d, "task_type", "") == "rehabilitation_plan"
        ])

    return {
        "jp_inpatient_with_rehab_count": _run("inpatient", "jp", True),
        "jp_inpatient_no_rehab_count": _run("inpatient", "jp", False),
        "us_inpatient_with_rehab_count": _run("inpatient", "us", True),
        "jp_icu_with_rehab_count": _run("icu", "jp", True),
    }
```

- [ ] **Step 3: Wire the proof into `_build_document_proof`'s equality_checks**

Add after `_ncp_proof = _proof_nutrition_care_plan()`:

```python
    # chain 2: rehabilitation_plan RehabSession-presence + JP-only + inpatient-only gate proof.
    _rp_proof = _proof_rehabilitation_plan()
```

Add after the 4 `nutrition_care_plan_*` tuples in the `equality_checks` list (before the
closing `]`):

```python
            # === chain 2: rehabilitation_plan gate proof (+4, total = 49) ===
            (
                "rehabilitation_plan_jp_inpatient_with_rehab_count",
                _rp_proof["jp_inpatient_with_rehab_count"],
                1,
            ),
            (
                "rehabilitation_plan_jp_inpatient_no_rehab_count",
                _rp_proof["jp_inpatient_no_rehab_count"],
                0,
            ),
            (
                "rehabilitation_plan_us_inpatient_with_rehab_count",
                _rp_proof["us_inpatient_with_rehab_count"],
                0,
            ),
            (
                "rehabilitation_plan_jp_icu_with_rehab_count",
                _rp_proof["jp_icu_with_rehab_count"],
                0,
            ),
```

Update the module docstring's running total (top of `audit.py`): change
`"45 equality_checks in lift_firing_proof guard canonical constants and"` to
`"49 equality_checks in lift_firing_proof guard canonical constants and"`, and add a new
bullet after the `chain 2 nutrition_care_plan gate (+4, total = 45):` block:

```python
  chain 2 rehabilitation_plan gate (+4, total = 49):
    `rehabilitation_plan_jp_inpatient_with_rehab_count` (positive) /
    `rehabilitation_plan_jp_inpatient_no_rehab_count` (negative: no
    RehabSession) / `rehabilitation_plan_us_inpatient_with_rehab_count`
    (negative: country gate) / `rehabilitation_plan_jp_icu_with_rehab_count`
    (negative: icu not in encounter_types_supported, unlike
    admission_care_plan/nutrition_care_plan which legitimately support icu).
    See `_proof_rehabilitation_plan`.
```

- [ ] **Step 4: Run the audit module test**

Run: `pytest tests/unit/test_document_audit_alpha2.py -v`
Expected: all PASS (this test file exercises `lift_firing_proof` generically over
whatever `equality_checks` the module returns — it does not hardcode a total count per
the earlier grep check, so no numeric assertion needs updating there).

- [ ] **Step 5: Write the full-chain integration test**

Create `tests/integration/test_rehabilitation_plan_chain.py`:

```python
"""Full chain integration test: document_enricher → TemplateNarrativePass →
FHIR Composition, for rehabilitation_plan (chain 2, third and final chain-2
sub-project).

Verifies: Composition emitted with LOINC 34823-5, exactly 9 sections, 100%
Japanese text, ONLY for JP inpatient encounters with ≥1 RehabSession —
correctly ABSENT when no RehabSession exists, and for out-of-scope cohorts
(US, outpatient, emergency, icu, rehab_inpatient).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.document.engine import document_enricher
from clinosim.modules.document.narrative.passes import TemplateNarrativePass
from clinosim.modules.output._fhir_composition import _bb_compositions


def _write_structural_cif(cif_dir: str, patient_dict: dict) -> None:
    structural_dir = os.path.join(cif_dir, "structural", "patients")
    os.makedirs(structural_dir, exist_ok=True)
    path = os.path.join(structural_dir, f"{patient_dict['patient']['patient_id']}.json")
    with open(path, "w") as f:
        json.dump(patient_dict, f, default=str)


def _make_bundle_ctx(record: dict, country: str = "jp") -> SimpleNamespace:
    return SimpleNamespace(
        record=record,
        country=country,
        patient_id=record.get("patient", {}).get("patient_id", ""),
        primary_enc_id=record["encounters"][0]["encounter_id"],
        roster_map={},
        hospital_config={},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10",
        patient_sex="",
    )


def _jp_patient_dict(patient_id: str, with_rehab: bool, encounter_type: str = "inpatient") -> dict:
    admission_dt = datetime(2026, 7, 1, 10, 0)
    encounter_id = f"enc-{patient_id}"
    rehab_sessions = (
        [{
            "session_id": f"REHAB-{patient_id}-001",
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "therapy_type": "PT",
            "session_date": admission_dt + timedelta(days=1, hours=10),
            "duration_minutes": 40,
            "day_post_op": 1,
            "activities": ["bed exercises"],
            "patient_participation": "good",
            "pain_score": 3,
            "functional_progress": "stable",
        }]
        if with_rehab
        else []
    )
    record: dict = {
        "patient": {"patient_id": patient_id, "age": 70, "sex": "F"},
        "encounters": [
            {
                "encounter_id": encounter_id,
                "encounter_type": encounter_type,
                "status": "completed",
                "admission_datetime": admission_dt,
                "discharge_datetime": admission_dt + timedelta(days=10),
                "attending_physician_id": "dr-rp-chain-test",
                "primary_nurse_id": "ns-rp-chain-test",
            }
        ],
        "documents": [],
        "extensions": {},
        "physiological_states": [],
        "condition_event": {},
        "vital_signs": [],
        "lab_results": [],
        "medication_administrations": [],
        "procedures": [],
        "rehab_sessions": rehab_sessions,
    }
    ctx = SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace(country="jp"))
    document_enricher(ctx)
    record["documents"] = [
        {
            "document_id": d.document_id,
            "task_type": d.task_type,
            "loinc_code": d.loinc_code,
            "encounter_id": d.encounter_id,
            "author_practitioner_id": d.author_practitioner_id,
            "authored_datetime": d.authored_datetime,
            "period_start": d.period_start,
            "period_end": d.period_end,
            "language": d.language,
            "format_type": d.format_type,
        }
        for d in record["documents"]
    ]
    return record


@pytest.mark.integration
def test_jp_inpatient_with_rehab_sessions_produces_rehabilitation_plan_composition() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        patient_id = "pt-rp-chain-inpatient"
        patient_dict = _jp_patient_dict(patient_id, with_rehab=True)
        _write_structural_cif(tmp, patient_dict)

        manifest = TemplateNarrativePass(tmp, version_id="v1", country="jp").run()
        assert manifest.document_counts_by_type.get("rehabilitation_plan") == 1

        narrative_dir = os.path.join(tmp, "narratives", "v1", "documents", f"enc-{patient_id}")
        rp_stub = next(
            d for d in patient_dict["documents"] if d["task_type"] == "rehabilitation_plan"
        )
        rp_file = os.path.join(narrative_dir, f"{rp_stub['document_id']}.json")
        assert os.path.exists(rp_file)
        with open(rp_file) as f:
            doc_payload = json.load(f)

        rp_stub["narrative"] = doc_payload["narrative"]
        patient_dict["extensions"] = {}
        bundle_ctx = _make_bundle_ctx(patient_dict, country="jp")
        comp_out = _bb_compositions(bundle_ctx)
        assert len(comp_out) == 1
        comp = comp_out[0]
        assert comp["type"]["coding"][0]["code"] == "34823-5"
        assert comp["type"]["coding"][0]["display"] == "リハビリテーション実施計画書"
        assert len(comp["section"]) == 9

        all_text = " ".join(s["title"] + s["text"]["div"] for s in comp["section"])
        has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in all_text)
        assert has_jp


@pytest.mark.integration
def test_jp_inpatient_without_rehab_sessions_produces_no_rehabilitation_plan() -> None:
    patient_dict = _jp_patient_dict("pt-rp-chain-norehab", with_rehab=False)
    assert not any(d["task_type"] == "rehabilitation_plan" for d in patient_dict["documents"])


@pytest.mark.integration
@pytest.mark.parametrize("encounter_type,country", [
    ("inpatient", "us"),
    ("outpatient", "jp"),
    ("emergency", "jp"),
    ("icu", "jp"),
    ("rehab_inpatient", "jp"),
])
def test_out_of_scope_cohorts_produce_no_rehabilitation_plan(
    encounter_type: str, country: str
) -> None:
    admission_dt = datetime(2026, 7, 1, 10, 0)
    encounter_id = f"enc-rp-{encounter_type}-{country}"
    record: dict = {
        "patient": {"patient_id": f"pt-rp-chain-{encounter_type}-{country}", "age": 50, "sex": "M"},
        "encounters": [
            {
                "encounter_id": encounter_id,
                "encounter_type": encounter_type,
                "status": "completed",
                "admission_datetime": admission_dt,
                "discharge_datetime": admission_dt + timedelta(days=10),
                "attending_physician_id": "dr-rp-chain-test",
            }
        ],
        "documents": [],
        "extensions": {},
        "physiological_states": [],
        "rehab_sessions": [{
            "session_id": "REHAB-oos-001",
            "patient_id": f"pt-rp-chain-{encounter_type}-{country}",
            "encounter_id": encounter_id,
            "therapy_type": "PT",
            "session_date": admission_dt + timedelta(days=1),
            "duration_minutes": 40,
            "day_post_op": 1,
            "activities": [],
            "patient_participation": "good",
            "pain_score": 3,
            "functional_progress": "stable",
        }],
    }
    ctx = SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace(country=country))
    document_enricher(ctx)
    rp_docs = [d for d in record["documents"] if d.task_type == "rehabilitation_plan"]
    assert len(rp_docs) == 0
```

- [ ] **Step 6: Run the integration test**

Run: `pytest tests/integration/test_rehabilitation_plan_chain.py -v`
Expected: all PASS (7 tests: 1 positive composition test + 1 negative-no-rehab test + 5
parametrized out-of-scope cases).

- [ ] **Step 7: Update TODO.md**

In `TODO.md`, find the line (β-JP-1 phase — JP localization + 厚労省必須文書 section):

```
- **リハビリテーション計画書** (Rehabilitation plan) — mandatory for rehab wards. Requires
  `extensions["procedure"]` rehab sessions.
```

Replace with:

```
- ~~**リハビリテーション計画書** (Rehabilitation plan)~~ — **DONE (chain 2, 2026-07-04)**:
  LOINC 34823-5, Composition, 9 sections per MHLW 別紙様式21 (base form only —
  variants 21の2〜21の5 out of scope), JP-only, inpatient-only (icu/rehab_inpatient
  both verified-unreachable EncounterType values — see status-audit finding in
  design spec §1). Gated on existing RehabSession data (post-surgical rehab for
  `requires_surgery: true` diseases), NOT the never-implemented rehab_inpatient
  ward-transfer subsystem the original TODO entry envisioned. 6/9 sections are
  data-driven.
```

Add these deferred entries after the existing `chain 2 deferred: LOS-gated
document_enricher pattern` entry (before `### β-2 phase`):

```
### chain 2 deferred: rehab_inpatient / EncounterType.ICU ward-transfer subsystem

Both `EncounterType.REHAB_INPATIENT` and `EncounterType.ICU` are defined in the
enum and referenced in downstream module allowlists (`document`, `nursing`) but
are **never actually assigned** anywhere in the simulator — verified empirically
(JP p=500 cohort produced zero occurrences of either value; `create_inpatient_encounter()`
hardcodes `EncounterType.INPATIENT`, `icu_transferred` is a boolean flag on that
same encounter, not a distinct one). The rehabilitation_plan chain (2026-07-04)
deliberately built against the already-firing `RehabSession` data on ordinary
`inpatient` encounters instead of this subsystem — see design spec
`docs/superpowers/specs/2026-07-04-rehabilitation-plan-design.md` §1. If a rehab
ward transfer / distinct ICU encounter is ever prioritized, it is a
simulator-level feature (transfer trigger in `inpatient.py` or
`encounter/engine.py` + disease YAML trigger conditions), not a document-module
change — and every downstream module currently declaring `rehab_inpatient`/`icu`
support (`document`, `nursing`) would need re-verification against real data at
that point, since none of it has ever been exercised in production.

### chain 2 deferred: rehabilitation_plan OT/ST therapy types + named therapist

`generate_rehab_sessions` (`modules/procedure/engine.py`) hardcodes
`therapy_type="PT"` — the `rehabilitation_plan` document's `rehab_team` section
will only ever show PT until that module (procedure module, out of scope for
the document-module chain) is extended to produce OT/ST sessions. Separately,
no PT/OT/ST staff role exists in the roster (mirrors the `nutrition_care_plan.dietitian`
gap), so the named-therapist sub-field is a permanent fixed fallback until a
therapist staff role is built.

### chain 2 deferred: rehabilitation_plan patient/family goals data source

`goals` and `policy` sections are fixed fallbacks with no CIF data source — no
field represents a patient's stated rehab goals or family wishes. This is why
`stage2_strategy=template_only` (no LLM) was chosen even though these two
sections read as narrative-shaped (design spec §3d): an LLM asked to fill them
would fabricate entirely. Revisit `stage2_strategy` for these two sections only
if a patient-goals data model is ever built.

### chain 2 deferred: RehabSession.activities free-text localization

`RehabSession.activities` (`types/procedure.py`) holds hardcoded English phrases
(e.g. "bed exercises") with no JP mapping. `rehabilitation_plan`'s
`basic_movement` section avoids this entirely by re-deriving a phase
(early/mid/late) from `day_post_op` instead of rendering the raw activity list.
If a future consumer needs the raw activities in JP output, add a proper
activity-key → {en, ja} lookup table then — do not hardcode ad hoc translations
at that call site.
```

- [ ] **Step 8: Golden regen check (expected: zero diff)**

None of the 6 canonical patient-profile fixtures
(`tests/fixtures/patient_profiles/*.yaml`) use a `requires_surgery: true` disease
(`sepsis`, `bacterial_pneumonia`, `copd_exacerbation`, `acute_mi`,
`hemorrhagic_stroke`, `diabetic_ketoacidosis` — none of the 9 diseases with
`requires_surgery: true`), so none of them ever produce a `RehabSession`. Run the
regen anyway to get an explicit negative confirmation (AD-66 Rule 2 — an
unexpected diff here would mean the new gate is leaking):

Run: `clinosim regenerate-goldens --all`
Run: `git status tests/fixtures/patient_profiles/`
Expected: no modified `.golden.json` files (clean status) — confirms the new
`rehabilitation_plan` gate does not fire for any canonical profile, as expected.
If any golden shows a diff, STOP and investigate before proceeding (per AD-66 Rule 2 —
do not commit an unexplained golden diff).

- [ ] **Step 9: Run the full test suite**

Run: `pytest -x -q`
Expected: all tests PASS (unit + integration + e2e, ~1600+ tests per session 35's
baseline count, now +~25 for this chain).

- [ ] **Step 10: Production cohort audit run**

Run: `clinosim generate --country jp --population 5000 --seed 42 --output /tmp/rp_chain_jp5k`
Run: `clinosim narrate --cif-dir /tmp/rp_chain_jp5k --provider template`
Run: `clinosim export-fhir --cif-dir /tmp/rp_chain_jp5k --narrative-version current`
Run: `clinosim audit run -d /tmp/rp_chain_jp5k`
Expected: all 4 axes PASS (structural / clinical / jp_language / silent_no_op), and the
`rehabilitation_plan_*` equality_checks from Step 3 show non-degenerate counts (the
`jp_inpatient_with_rehab_count`-style synthetic proof always returns exactly 1 by
construction — this step's real value is confirming the cohort-level Composition count
for `34823-5` is `> 0` and matches the number of JP inpatient encounters with
`requires_surgery: true` diseases and ≥1 RehabSession in the cohort manifest).

- [ ] **Step 11: Commit**

```bash
git add clinosim/modules/llm_service/engine.py clinosim/modules/document/audit.py \
  tests/integration/test_rehabilitation_plan_chain.py TODO.md
git commit -m "feat(chain2): rehabilitation_plan LLM sync, audit proof, integration test, TODO.md"
```

---

## Plan self-review notes

- **Spec coverage**: §2 (LOINC/MHLW source) → Task 2 Step 4 YAML comment. §3a
  (NarrativeContext field) → Task 1 Step 4 + Task 3 Step 3 (plan-corrected to the real
  `passes.py` path). §3b (dispatch + `_make_doc_stub`) → Task 2 Steps 3/6. §3c
  (registry) → Task 1 + Task 2 Step 3. §3d (no LLM) → Task 2 YAML
  (`stage2_strategy: template_only`). §3e (9 sections) → Task 3. §3f (no FHIR changes)
  → verified by the integration test asserting generic `_bb_compositions` handles the
  new type with zero builder changes. §4 (out-of-scope) → Task 4 Step 7 TODO.md entries.
  §5/§6 (testing/verification) → Tasks 1-4's test steps + Task 4 Steps 8-10.
- **Placeholder scan**: none found — every step has literal code, exact file paths, and
  concrete expected test output.
- **Type consistency**: `_build_rp_*` methods all return `tuple[str, list[str]]` matching
  every existing `_build_*` method's signature; `_estimated_los_days` returns
  `tuple[int, list[str]]` (distinct from the `tuple[str, list[str]]` builders — it's a
  helper, not a section builder, consistent with not being registered in
  `section_builders`); `NarrativeContext.rehab_sessions: list[Any]` matches the existing
  `procedures: list[Any]` field's typing exactly.
- **Sequencing correction found during self-review**: the original draft added
  `SUPPORTED_DOCUMENT_TYPES` in Task 1 alongside the enum/LOINC/frequency additions,
  before the matching YAML entry existed. Since `_validate_document_type_specs()`
  requires `yaml_keys == SUPPORTED_DOCUMENT_TYPES` exactly (Layer 4), this would have
  made `load_document_type_specs()` raise on every call the moment Task 1 landed —
  breaking `document_enricher` and most of the test suite until Task 2. Fixed by moving
  `SUPPORTED_DOCUMENT_TYPES` (and the 3 dependent `test_registry.py` fixture/count
  updates) into Task 2 Step 3, landing in the same commit as the YAML entry (Step 4).
  Also fixed a timestamp arithmetic bug in Task 2 Step 1's test fixture
  (`admission_dt + timedelta(days=1, hours=10)` produced `20:00`, not the asserted
  `10:00`, in `test_authored_datetime_is_first_rehab_session_date_not_admission_date`).
