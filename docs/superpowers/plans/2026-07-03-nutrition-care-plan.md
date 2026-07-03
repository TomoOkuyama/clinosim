# Nutrition Care Plan Document (栄養管理計画書) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `nutrition_care_plan` (栄養管理計画書, LOINC 80791-7) as the 11th `DocumentType` in clinosim's narrative pipeline — a JP-only, 12-section Composition document emitted only for inpatient/ICU admissions with LOS > 7 days, mirroring the `admission_care_plan` chain's architecture with one new addition: a new `generation_frequency` value requiring a small `document_enricher` dispatch branch.

**Architecture:** Same additive spec-driven extension pattern as `admission_care_plan` (PR #138, merged): one new `DocumentType` enum value + one `document_type_specs.yaml` entry flows through `document_enricher` (Stage 1 stub) → `TemplateNarrativePass` (Stage 2 render) → generic `_fhir_composition.py` (Stage 3 FHIR). The one architectural delta: MHLW mandates this document only for admissions > 7 days, and no existing `generation_frequency` expresses that, so `document_enricher` gains one new `elif` branch (`admission_once_los_gt_7`) mirroring the existing `daily` branch's LOS-skip pattern. No FHIR builder changes.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy strict, PyYAML, existing clinosim `_shared.get_attr_or_key` (`_o`) dual-access helper, `clinosim.codes.lookup`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-03-nutrition-care-plan-design.md` (approved, committed `192a837266`). Every task implements one part of that spec; do not add scope beyond it.
- Branch: create `feature/chain2-nutrition-care-plan` off `master` before Task 1. Current `master` HEAD includes the merged `admission_care_plan` chain (PR #138) — its files are the direct precedent for every task below; follow their exact conventions (`_o()` dual-access, fallback-constant naming, lazy `code_lookup` import, `tuple[str, list[str]]` builder return type).
- Code comments/docstrings: English. Commit messages: `feat(chain2): ...` / `test(chain2): ...` per project convention.
- **No new CIF schema fields.** All data-driven sections source from `PatientProfile.bmi` / `PatientProfile.weight_kg` (already exist, `clinosim/types/patient.py:98-100`) and `Encounter` fields already used by `admission_care_plan`.
- **No FHIR builder changes** — `_fhir_composition.py` is generic (verified during the `admission_care_plan` chain).
- Determinism (AD-16): no `datetime.now()` / `random.random()` in any new code.
- `codes/data/loinc.yaml` requires an authoritative, non-fabricated `en` field — LOINC 80791-7 "Nutrition and dietetics Plan of care note" already verified via web search during brainstorming (spec §2).
- **N-3 cross-validator**: `clinosim/modules/llm_service/engine.py` runs an import-time validator requiring every `DocumentType` value to also exist as a NARRATIVE-category `LLMTaskType` with a `DOCUMENT_LOINC` entry (discovered mid-execution during the `admission_care_plan` chain — this plan bakes it into Task 1 from the start, not as a later surprise).
- Run `pytest -m unit -q` after every task; run the full suite (`pytest -x -q`) before the final PR (Task 8).
- MVP data-coverage tradeoff (spec §2, user-confirmed): only 3 of 12 composition sections are genuinely data-driven (`ward_and_physician`, `nutrition_risk`, `nutrition_supply`); the other 9 are fixed fallback strings. This is intentional, not a shortcut to fix later in this PR — the fallback sections still need real code (a builder method + fallback constants), just no CIF data source behind them.
- adv-1 lesson baked in from Task 1 (not discovered later, unlike the `admission_care_plan` chain): every new dispatch gate must be proven **both positive AND negative** (fires when it should, does NOT fire when it shouldn't) at both the unit-test level and the audit `lift_firing_proof` level. Apply this to the `admission_once_los_gt_7` LOS gate in Tasks 3, 5, and 6.

---

### Task 1: LOINC code + `DocumentType` enum + `LLMTaskType` sync

**Files:**
- Modify: `clinosim/codes/data/loinc.yaml:26-28` (insert before the `69730-0` entry)
- Modify: `clinosim/types/document.py` (append to `DocumentType` enum, after `ADMISSION_CARE_PLAN`)
- Modify: `clinosim/modules/llm_service/engine.py` (append to `LLMTaskType` enum after `ADMISSION_CARE_PLAN`, `TASK_CATEGORY` dict, `DOCUMENT_LOINC` dict — same 3 locations touched for `admission_care_plan`)
- Test: `tests/unit/modules/document/narrative/test_registry.py` (new test functions, appended)

**Interfaces:**
- Produces: `DocumentType.NUTRITION_CARE_PLAN` (value `"nutrition_care_plan"`), consumed by Task 2's YAML spec entry and Task 4's builder registration.
- Produces: `clinosim.codes.lookup("loinc", "80791-7", "ja")` → `"栄養管理計画書"`, `lookup("loinc", "80791-7", "en")` → `"Nutrition and dietetics Plan of care note"`.
- Produces: `LLMTaskType.NUTRITION_CARE_PLAN` in `TASK_CATEGORY` (→ `LLMTaskCategory.NARRATIVE`) and `DOCUMENT_LOINC` (→ `"80791-7"`), satisfying the N-3 import-time cross-validator (`_validate_document_task_sync()`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/modules/document/narrative/test_registry.py`:

```python
def test_nutrition_care_plan_loinc_code_resolves() -> None:
    """LOINC 80791-7 ('Nutrition and dietetics Plan of care note') must
    resolve in both languages — verified against loinc.org during design
    (spec §2)."""
    from clinosim.codes import lookup as code_lookup

    assert code_lookup("loinc", "80791-7", "en") == "Nutrition and dietetics Plan of care note"
    assert code_lookup("loinc", "80791-7", "ja") == "栄養管理計画書"


def test_document_type_has_nutrition_care_plan() -> None:
    assert DocumentType.NUTRITION_CARE_PLAN.value == "nutrition_care_plan"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/modules/document/narrative/test_registry.py::test_nutrition_care_plan_loinc_code_resolves tests/unit/modules/document/narrative/test_registry.py::test_document_type_has_nutrition_care_plan -v`
Expected: FAIL — `AttributeError: NUTRITION_CARE_PLAN` and/or LOINC lookup returning the bare code (unregistered).

- [ ] **Step 3: Add the LOINC code**

Edit `clinosim/codes/data/loinc.yaml`, insert immediately after the `18776-5` entry (before `69730-0`):

```yaml
  80791-7:
    en: Nutrition and dietetics Plan of care note
    ja: 栄養管理計画書
```

- [ ] **Step 4: Add the `DocumentType` enum value**

Edit `clinosim/types/document.py`, after the `ADMISSION_CARE_PLAN` line:

```python
    ADMISSION_CARE_PLAN = "admission_care_plan"                   # LOINC 18776-5 (verified 2026-07-03)
    NUTRITION_CARE_PLAN = "nutrition_care_plan"                   # LOINC 80791-7 (verified 2026-07-03)
```

- [ ] **Step 5: Sync `LLMTaskType` in `llm_service/engine.py`**

Edit `clinosim/modules/llm_service/engine.py`. In the `LLMTaskType` enum, after `ADMISSION_CARE_PLAN`:

```python
    ADMISSION_CARE_PLAN = "admission_care_plan"                    # LOINC 18776-5
    NUTRITION_CARE_PLAN = "nutrition_care_plan"                    # LOINC 80791-7
```

In `TASK_CATEGORY`, after the `ADMISSION_CARE_PLAN` line:

```python
    LLMTaskType.ADMISSION_CARE_PLAN: LLMTaskCategory.NARRATIVE,
    LLMTaskType.NUTRITION_CARE_PLAN: LLMTaskCategory.NARRATIVE,
```

In `DOCUMENT_LOINC`, after the `ADMISSION_CARE_PLAN` line:

```python
    LLMTaskType.ADMISSION_CARE_PLAN: "18776-5",           # Plan of care note
    LLMTaskType.NUTRITION_CARE_PLAN: "80791-7",           # Nutrition and dietetics Plan of care note
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/modules/document/narrative/test_registry.py tests/unit/test_llm_task_enum_sync.py -v`
Expected: PASS (all tests, including the pre-existing N-3 sync tests — `test_every_document_type_is_a_narrative_llm_task_type` etc. now pass with the new enum member registered everywhere required).

- [ ] **Step 7: Commit**

```bash
git add clinosim/codes/data/loinc.yaml clinosim/types/document.py clinosim/modules/llm_service/engine.py tests/unit/modules/document/narrative/test_registry.py
git commit -m "feat(chain2): register LOINC 80791-7 + DocumentType.NUTRITION_CARE_PLAN"
```

---

### Task 2: `document_type_specs.yaml` entry + `GENERATION_FREQUENCIES` + registry gating

**Files:**
- Modify: `clinosim/modules/document/reference_data/document_type_specs.yaml` (append after `admission_care_plan`)
- Modify: `clinosim/modules/document/narrative/registry.py:39-45` (`GENERATION_FREQUENCIES`), `:59-73` (`SUPPORTED_DOCUMENT_TYPES`)
- Test: `tests/unit/modules/document/narrative/test_registry.py`, `tests/unit/modules/document/narrative/test_encounter_types_supported.py`

**Interfaces:**
- Consumes: `DocumentType.NUTRITION_CARE_PLAN` (Task 1).
- Produces: `specs_for_country("jp")` includes `type_key == "nutrition_care_plan"`; `specs_for_country("us")` does not. `specs_for_encounter_type("inpatient")`/`("icu")` include it; `("rehab_inpatient")`, `("outpatient")`, `("emergency")` do not. `load_document_type_specs()[DocumentType.NUTRITION_CARE_PLAN].generation_frequency == "admission_once_los_gt_7"`. Consumed by Task 3 (`document_enricher` dispatch) and Task 7 (integration test).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/modules/document/narrative/test_registry.py`:

```python
def test_registry_covers_nutrition_care_plan() -> None:
    specs = load_document_type_specs()
    assert DocumentType.NUTRITION_CARE_PLAN in specs


def test_nutrition_care_plan_spec_metadata() -> None:
    specs = load_document_type_specs()
    ncp = specs[DocumentType.NUTRITION_CARE_PLAN]
    assert ncp.loinc_code == "80791-7"
    assert ncp.format_type == FormatType.COMPOSITION
    assert ncp.countries_supported == ("jp",)
    assert ncp.generation_frequency == "admission_once_los_gt_7"
    assert ncp.stage2_strategy == "template_only"
    assert set(ncp.composition_sections) == {
        "ward_and_physician", "dietitian", "nutrition_risk",
        "nutrition_assessment", "nutrition_goals", "nutrition_supply",
        "dysphagia_diet", "dietary_content", "nutrition_counseling",
        "other_issues", "reassessment_timing", "discharge_evaluation",
    }


def test_nutrition_care_plan_is_jp_only() -> None:
    us_specs = specs_for_country("us")
    jp_specs = specs_for_country("jp")
    assert "nutrition_care_plan" not in [s.type_key for s in us_specs]
    assert "nutrition_care_plan" in [s.type_key for s in jp_specs]


def test_admission_once_los_gt_7_in_generation_frequencies_allowlist() -> None:
    from clinosim.modules.document.narrative.registry import GENERATION_FREQUENCIES

    assert "admission_once_los_gt_7" in GENERATION_FREQUENCIES
```

Append to `tests/unit/modules/document/narrative/test_encounter_types_supported.py`:

```python
def test_nutrition_care_plan_excludes_rehab_inpatient() -> None:
    """Mirrors admission_care_plan's inpatient/icu-only scope (spec §3b)."""
    from clinosim.modules.document.narrative.registry import load_document_type_specs
    from clinosim.types.document import DocumentType

    specs = load_document_type_specs()
    ncp = specs[DocumentType.NUTRITION_CARE_PLAN]
    assert set(ncp.encounter_types_supported) == {"inpatient", "icu"}

    inpatient_keys = {s.type_key for s in specs_for_encounter_type("inpatient")}
    icu_keys = {s.type_key for s in specs_for_encounter_type("icu")}
    rehab_keys = {s.type_key for s in specs_for_encounter_type("rehab_inpatient")}
    assert "nutrition_care_plan" in inpatient_keys
    assert "nutrition_care_plan" in icu_keys
    assert "nutrition_care_plan" not in rehab_keys
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/modules/document/narrative/test_registry.py tests/unit/modules/document/narrative/test_encounter_types_supported.py -v`
Expected: FAIL — `KeyError: DocumentType.NUTRITION_CARE_PLAN` (no YAML entry yet) and `AssertionError` on the `GENERATION_FREQUENCIES` membership test.

- [ ] **Step 3: Add `admission_once_los_gt_7` to `GENERATION_FREQUENCIES`**

Edit `clinosim/modules/document/narrative/registry.py:39-45`:

```python
GENERATION_FREQUENCIES: frozenset[str] = frozenset({
    "admission_once",
    "admission_once_los_gt_7",  # chain 2: nutrition_care_plan (MHLW LOS>7 mandate)
    "daily",
    "daily_3shift",  # α-min-3: 3 nursing notes per LOS day (night/day/evening)
    "discharge_once",
    "encounter_once",
})
```

- [ ] **Step 4: Add the YAML spec entry**

Append to `clinosim/modules/document/reference_data/document_type_specs.yaml` (end of file, after `admission_care_plan`):

```yaml

  # === chain 2 (厚労省4帳票, second sub-project, 2026-07-03) ===
  # LOINC 80791-7 verified via web search (loinc.org) — "Nutrition and
  # dietetics Plan of care note" is a specific, strong match. MHLW form
  # 別紙23 (https://www.dietitian.or.jp/assets/data/medical-fee/0000196315_292.pdf)
  # confirmed the fields below (design spec §2). JP-only, inpatient/icu only.
  # generation_frequency=admission_once_los_gt_7: MHLW mandates this document
  # only for admissions > 7 days (design spec §3a) — see document/engine.py
  # dispatch branch. MVP: only ward_and_physician / nutrition_risk /
  # nutrition_supply are data-driven (PatientProfile.bmi / weight_kg); the
  # other 9 sections are fixed fallback strings pending future subsystems
  # (dietitian staff role, real nutrition assessment data) — see TODO.md.
  nutrition_care_plan:
    loinc_code: "80791-7"
    format_type: composition
    countries_supported: [jp]
    encounter_types_supported: [inpatient, icu]
    generation_frequency: admission_once_los_gt_7
    composition_sections:
      - ward_and_physician
      - dietitian
      - nutrition_risk
      - nutrition_assessment
      - nutrition_goals
      - nutrition_supply
      - dysphagia_diet
      - dietary_content
      - nutrition_counseling
      - other_issues
      - reassessment_timing
      - discharge_evaluation
    stage2_strategy: template_only
    llm_enabled_sections: []
```

- [ ] **Step 5: Register the enum in `SUPPORTED_DOCUMENT_TYPES`**

Edit `clinosim/modules/document/narrative/registry.py:58-73`:

```python
# α-min-2 scope = 9 doc types (α-min-1 3 + α-min-2 6); chain 2 adds 2 = 11
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
})
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/modules/document/narrative/test_registry.py tests/unit/modules/document/narrative/test_encounter_types_supported.py -v`
Expected: mostly PASS, but the Layer-4 forward/reverse-coverage validator (`_validate_document_type_specs`) will now raise inside 3 pre-existing hardcoded 10-entry `bad_data` fixtures in `test_registry.py` (`test_load_raises_on_missing_required_field`, `test_load_raises_on_null_entry`, `test_load_raises_on_empty_countries_supported`) — this is the SAME class of pre-existing-fixture staleness discovered in the `admission_care_plan` chain (Task 2 Step 5b there). Fix now:

- [ ] **Step 6b: Add a valid `nutrition_care_plan` entry to the 3 hardcoded `bad_data` fixtures**

In `tests/unit/modules/document/narrative/test_registry.py`, each of the 3 functions above has a `bad_data["specs"]` dict ending with an `admission_care_plan` entry (added in the prior chain). Add a valid sibling entry immediately after it in all 3 places:

```python
            "admission_care_plan": {
                "loinc_code": "18776-5",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "admission_once",
            },
            "nutrition_care_plan": {
                "loinc_code": "80791-7",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "admission_once_los_gt_7",
            },
```

Also update the 3 pre-existing count-assertion tests that hardcode totals (same pattern as the `admission_care_plan` chain): find and update:
- `test_load_specs_returns_10_total` → rename to `test_load_specs_returns_11_total`, change `== 10` to `== 11` and the docstring/message from "10" to "11 (3 α-min-1 + 6 α-min-2 + 2 chain-2)".
- `test_supported_document_types_covers_10_entries` → rename to `test_supported_document_types_covers_11_entries`, change `== 10` to `== 11`.
- `test_specs_for_encounter_type_inpatient_returns_7_specs` → rename to `test_specs_for_encounter_type_inpatient_returns_8_specs`, change `== 7` to `== 8` (nutrition_care_plan adds one more inpatient-restricted spec), update the docstring math.

Run: `pytest tests/unit/modules/document/narrative/test_registry.py tests/unit/modules/document/narrative/test_encounter_types_supported.py -v`
Expected: PASS (all tests).

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/document/reference_data/document_type_specs.yaml clinosim/modules/document/narrative/registry.py tests/unit/modules/document/narrative/test_registry.py tests/unit/modules/document/narrative/test_encounter_types_supported.py
git commit -m "feat(chain2): document_type_specs.yaml entry for nutrition_care_plan (JP-only, LOS>7 gated)"
```

---

### Task 3: `document_enricher` new dispatch branch (`admission_once_los_gt_7`)

**Files:**
- Modify: `clinosim/modules/document/engine.py:290-309` (add new `elif` branch after the `admission_once` branch, before `elif freq == "daily":` at line 310)
- Test: Create `tests/unit/modules/document/test_engine_nutrition_care_plan.py`

**Interfaces:**
- Consumes: `spec.generation_frequency == "admission_once_los_gt_7"` (Task 2), `los_days` (already computed at `engine.py:283` via `_compute_los_days`, in scope for this branch — no new computation needed).
- Produces: a `ClinicalDocument` stub with `task_type == "nutrition_care_plan"` when `los_days > 7`, none when `los_days <= 7`. Consumed by Task 5 (audit) and Task 7 (integration test).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/modules/document/test_engine_nutrition_care_plan.py`:

```python
"""document_enricher dispatch tests for nutrition_care_plan (chain 2).

Covers the NEW admission_once_los_gt_7 generation_frequency — proves BOTH
the positive case (LOS>7 fires) and the negative case (LOS<=7 does not
fire), per the admission_care_plan adv-1 lesson (design spec §5).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.engine import document_enricher


def _make_record(encounter_type: str, los_days: int, country: str = "jp") -> dict[str, Any]:
    admission_dt = datetime(2026, 7, 1, 10, 0)
    return {
        "patient": {"patient_id": f"pt-ncp-engine-{los_days}"},
        "encounters": [
            {
                "encounter_id": f"enc-ncp-engine-{los_days}",
                "encounter_type": encounter_type,
                "status": "completed",
                "admission_datetime": admission_dt,
                "discharge_datetime": admission_dt + timedelta(days=los_days),
                "attending_physician_id": "dr-ncp-engine-test",
                "primary_nurse_id": "ns-ncp-engine-test",
            }
        ],
        "documents": [],
        "extensions": {},
        "physiological_states": [],
    }


def _run_enricher(record: dict[str, Any], country: str) -> dict[str, Any]:
    ctx = SimpleNamespace(
        master_seed=42,
        records=[record],
        config=SimpleNamespace(country=country),
    )
    document_enricher(ctx)
    return record


def _ncp_docs(record: dict[str, Any]) -> list[Any]:
    return [d for d in record["documents"] if getattr(d, "task_type", "") == "nutrition_care_plan"]


def test_jp_inpatient_los_gt_7_gets_one_nutrition_care_plan_stub() -> None:
    record = _run_enricher(_make_record("inpatient", los_days=10), "jp")
    docs = _ncp_docs(record)
    assert len(docs) == 1
    assert docs[0].loinc_code == "80791-7"


def test_jp_inpatient_los_exactly_7_gets_zero_stubs() -> None:
    """Boundary: LOS==7 must NOT fire (spec requires strictly > 7)."""
    record = _run_enricher(_make_record("inpatient", los_days=7), "jp")
    assert len(_ncp_docs(record)) == 0


def test_jp_inpatient_los_5_gets_zero_stubs() -> None:
    record = _run_enricher(_make_record("inpatient", los_days=5), "jp")
    assert len(_ncp_docs(record)) == 0


def test_jp_icu_los_gt_7_gets_one_nutrition_care_plan_stub() -> None:
    record = _run_enricher(_make_record("icu", los_days=14), "jp")
    assert len(_ncp_docs(record)) == 1


def test_jp_rehab_inpatient_los_gt_7_gets_zero_stubs() -> None:
    record = _run_enricher(_make_record("rehab_inpatient", los_days=20), "jp")
    assert len(_ncp_docs(record)) == 0


def test_us_inpatient_los_gt_7_gets_zero_stubs() -> None:
    record = _run_enricher(_make_record("inpatient", los_days=10), "us")
    assert len(_ncp_docs(record)) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/modules/document/test_engine_nutrition_care_plan.py -v`
Expected: all tests asserting `len(docs) == 0` PASS trivially (no dispatch branch exists yet, so nothing is ever emitted); `test_jp_inpatient_los_gt_7_gets_one_nutrition_care_plan_stub` and `test_jp_icu_los_gt_7_gets_one_nutrition_care_plan_stub` FAIL (`assert 0 == 1`) — this confirms the positive case is the one genuinely exercising new code.

- [ ] **Step 3: Add the dispatch branch**

Edit `clinosim/modules/document/engine.py`, insert a new `elif` branch between the `admission_once` branch (ends at line 308 `doc_seq += 1`) and `elif freq == "daily":` (line 310):

```python
                elif freq == "admission_once_los_gt_7":
                    # MHLW mandate: 栄養管理計画書 required only for admissions
                    # > 7 days (design spec §3a). Mirrors the `daily` branch's
                    # LOS-skip pattern below.
                    if los_days <= 7:
                        continue
                    documents.append(ClinicalDocument(
                        document_id=f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}",
                        task_type=spec.type_key,
                        loinc_code=spec.loinc_code,
                        patient_id=pid,
                        encounter_id=encounter_id,
                        author_practitioner_id=_pick_document_author(spec, encounter),
                        authored_datetime=admission_dt.isoformat(),
                        period_start=admission_dt.isoformat(),
                        period_end=admission_dt.isoformat(),
                        language=lang,
                        format_type=spec.format_type.value,
                        narrative=None,
                    ))
                    doc_seq += 1

```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/modules/document/test_engine_nutrition_care_plan.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Run the broader document engine suite to check no regression**

Run: `pytest tests/unit/modules/document/ -q`
Expected: PASS (all tests — the new `elif` branch is purely additive, unreachable by any pre-existing `generation_frequency` value).

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/document/engine.py tests/unit/modules/document/test_engine_nutrition_care_plan.py
git commit -m "feat(chain2): document_enricher admission_once_los_gt_7 dispatch branch"
```

---

### Task 4: Template generator — 12 section builders

**Files:**
- Modify: `clinosim/modules/document/narrative/template_generator.py`
- Test: Create `tests/unit/modules/document/narrative/test_template_generator_nutrition_care_plan.py`

**Interfaces:**
- Consumes: `NarrativeContext.encounter` (keys `ward_id`/`attending_physician_id`/`admission_datetime`), `NarrativeContext.patient` (`PatientProfile`-shaped, fields `bmi: float`, `weight_kg: float`).
- Produces: `TemplateNarrativeGenerator.generate(ctx, spec)` returns a `NarrativeOutput` whose `.sections` dict has all 12 keys from `spec.composition_sections`, each non-empty, when `ctx.document_type == DocumentType.NUTRITION_CARE_PLAN`. Consumed by Task 7 (integration test).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/modules/document/narrative/test_template_generator_nutrition_care_plan.py`:

```python
"""Tests for TemplateNarrativeGenerator nutrition_care_plan sections (chain 2).

Mirrors tests/unit/modules/document/narrative/test_template_generator_admission_care_plan.py.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, FormatType, NarrativeContext
from clinosim.types.patient import PatientProfile

_NCP_SECTIONS = (
    "ward_and_physician", "dietitian", "nutrition_risk", "nutrition_assessment",
    "nutrition_goals", "nutrition_supply", "dysphagia_diet", "dietary_content",
    "nutrition_counseling", "other_issues", "reassessment_timing", "discharge_evaluation",
)


def _make_spec() -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key="nutrition_care_plan",
        loinc_code="80791-7",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp",),
        generation_frequency="admission_once_los_gt_7",
        composition_sections=_NCP_SECTIONS,
        encounter_types_supported=("inpatient", "icu"),
        stage2_strategy="template_only",
    )


def _make_encounter(ward_id: str = "4W", attending_physician_id: str = "dr-ncp-001") -> Any:
    return SimpleNamespace(
        encounter_id="enc-ncp-test",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        ward_id=ward_id,
        attending_physician_id=attending_physician_id,
    )


def _make_patient(bmi: float = 22.5, weight_kg: float = 65.0) -> PatientProfile:
    patient = PatientProfile(patient_id="pt-ncp-test")
    patient.bmi = bmi
    patient.weight_kg = weight_kg
    return patient


def _make_ctx(
    encounter: Any = None,
    patient: Any = None,
    target_lang: str = "ja",
    locale: str = "jp",
) -> NarrativeContext:
    return NarrativeContext(
        patient=patient or _make_patient(),
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
        document_type=DocumentType.NUTRITION_CARE_PLAN,
        target_lang=target_lang,
        locale=locale,
    )


def test_nutrition_care_plan_returns_all_12_sections_non_empty() -> None:
    spec = _make_spec()
    ctx = _make_ctx()
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert isinstance(out.sections, dict)
    for section in _NCP_SECTIONS:
        assert section in out.sections, f"section {section!r} missing"
        assert out.sections[section].strip() != "", f"section {section!r} is empty"


def test_nutrition_care_plan_jp_has_japanese_text() -> None:
    spec = _make_spec()
    ctx = _make_ctx(target_lang="ja", locale="jp")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    all_text = " ".join(out.sections.values())
    has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in all_text)
    assert has_jp, f"nutrition_care_plan sections contain no Japanese text: {all_text[:300]!r}"


def test_nutrition_care_plan_en_no_crash() -> None:
    spec = _make_spec()
    ctx = _make_ctx(target_lang="en", locale="us")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    for section in _NCP_SECTIONS:
        assert out.sections[section].strip() != ""


def test_ward_and_physician_includes_ward_and_physician_id() -> None:
    spec = _make_spec()
    enc = _make_encounter(ward_id="6S", attending_physician_id="dr-ncp-999")
    ctx = _make_ctx(encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "6S" in out.sections["ward_and_physician"]
    assert "dr-ncp-999" in out.sections["ward_and_physician"]


def test_nutrition_risk_low_for_low_bmi() -> None:
    spec = _make_spec()
    ctx = _make_ctx(patient=_make_patient(bmi=17.0))
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "低栄養" in out.sections["nutrition_risk"]


def test_nutrition_risk_normal_for_mid_bmi() -> None:
    spec = _make_spec()
    ctx = _make_ctx(patient=_make_patient(bmi=22.0))
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "22.0" in out.sections["nutrition_risk"]


def test_nutrition_risk_over_for_high_bmi() -> None:
    spec = _make_spec()
    ctx = _make_ctx(patient=_make_patient(bmi=27.0))
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "過栄養" in out.sections["nutrition_risk"]


def test_nutrition_supply_computes_energy_and_protein_from_weight() -> None:
    """weight_kg=60.0 -> energy=round(60*27.5)=1650, protein=round(60*1.1,1)=66.0"""
    spec = _make_spec()
    ctx = _make_ctx(patient=_make_patient(weight_kg=60.0))
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "1650" in out.sections["nutrition_supply"]
    assert "66.0" in out.sections["nutrition_supply"]
    assert "経口" in out.sections["nutrition_supply"]


def test_dysphagia_diet_fixed_none() -> None:
    spec = _make_spec()
    ctx = _make_ctx()
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "なし" in out.sections["dysphagia_diet"]


def test_discharge_evaluation_is_pending_placeholder() -> None:
    """Genuinely unknowable at plan-creation time (design spec §2, row 10)."""
    spec = _make_spec()
    ctx = _make_ctx()
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "退院時" in out.sections["discharge_evaluation"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/modules/document/narrative/test_template_generator_nutrition_care_plan.py -v`
Expected: FAIL — every `nutrition_care_plan` section falls to the generic fallback phrase (no builder registered yet), so assertions on specific content (ward id, BMI risk labels, kcal/protein numbers) fail.

- [ ] **Step 3: Add fallback constants**

Edit `clinosim/modules/document/narrative/template_generator.py`, after the `_ACP_OTHER_PLANS_EN` constant block (near line 261-263):

```python
_NCP_DIETITIAN_FALLBACK_JA = "担当なし"
_NCP_DIETITIAN_FALLBACK_EN = "No dietitian assigned"
_NCP_ASSESSMENT_FALLBACK_JA = "栄養状態の評価と課題：特記事項なし"
_NCP_ASSESSMENT_FALLBACK_EN = "Nutrition status assessment: no significant findings"
_NCP_GOALS_FALLBACK_JA = "栄養管理計画の目標：現在の栄養状態を維持"
_NCP_GOALS_FALLBACK_EN = "Nutrition management goal: maintain current nutritional status"
_NCP_DYSPHAGIA_NONE_JA = "嚥下調整食の必要性：なし"
_NCP_DYSPHAGIA_NONE_EN = "Dysphagia diet required: No"
_NCP_DIETARY_CONTENT_FALLBACK_JA = "食事内容：常食"
_NCP_DIETARY_CONTENT_FALLBACK_EN = "Dietary content: regular diet"
_NCP_COUNSELING_FALLBACK_JA = "栄養食事相談：必要に応じて実施"
_NCP_COUNSELING_FALLBACK_EN = "Nutrition counseling: to be provided as needed"
_NCP_OTHER_ISSUES_FALLBACK_JA = "その他栄養管理上の課題：特記事項なし"
_NCP_OTHER_ISSUES_FALLBACK_EN = "Other nutrition management issues: none noted"
_NCP_REASSESSMENT_FALLBACK_JA = "栄養状態の再評価：入院後1週間を目安に実施"
_NCP_REASSESSMENT_FALLBACK_EN = "Nutrition status reassessment: planned approximately 1 week after admission"
_NCP_DISCHARGE_EVAL_FALLBACK_JA = "退院時及び終了時の総合的評価：退院時に評価予定"
_NCP_DISCHARGE_EVAL_FALLBACK_EN = "Comprehensive evaluation at discharge: pending, to be assessed at discharge"
```

- [ ] **Step 4: Register the 12 builders in `section_builders`**

Edit `clinosim/modules/document/narrative/template_generator.py`, in `_render_composition_sections`, add after the `"other_plans": self._build_acp_other_plans,` line:

```python
            # chain 2: NUTRITION_CARE_PLAN sections (LOINC 80791-7)
            "ward_and_physician": self._build_ncp_ward_and_physician,
            "dietitian": self._build_ncp_dietitian,
            "nutrition_risk": self._build_ncp_nutrition_risk,
            "nutrition_assessment": self._build_ncp_nutrition_assessment,
            "nutrition_goals": self._build_ncp_nutrition_goals,
            "nutrition_supply": self._build_ncp_nutrition_supply,
            "dysphagia_diet": self._build_ncp_dysphagia_diet,
            "dietary_content": self._build_ncp_dietary_content,
            "nutrition_counseling": self._build_ncp_nutrition_counseling,
            "other_issues": self._build_ncp_other_issues,
            "reassessment_timing": self._build_ncp_reassessment_timing,
            "discharge_evaluation": self._build_ncp_discharge_evaluation,
```

- [ ] **Step 5: Implement the 12 builder methods**

Add after `_build_acp_other_plans` (the last `admission_care_plan` builder):

```python
    # ─────────────────────────────────────────────────────────────────
    # chain 2: NUTRITION_CARE_PLAN section builders (栄養管理計画書, LOINC 80791-7)
    #
    # MHLW form 別紙23 (verified 2026-07-03 — design spec §2). JP-only,
    # LOS>7-gated. Only 3 of 12 sections are data-driven (ward_and_physician /
    # nutrition_risk / nutrition_supply); the rest are MVP fixed fallbacks —
    # no dietitian role or real nutrition-assessment data source exists yet
    # (TODO.md tracks this). Both language branches implemented for
    # consistency with every other builder in this file, though this doc
    # type is JP-only in production.
    # ─────────────────────────────────────────────────────────────────

    def _build_ncp_ward_and_physician(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """病棟／担当医師名／入院日 — same Encounter fields as admission_care_plan."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        ward = str(_o(ctx.encounter, "ward_id", "") or "")
        physician = str(_o(ctx.encounter, "attending_physician_id", "") or "")
        if ward:
            facts.append("encounter.ward_id")
        if physician:
            facts.append("encounter.attending_physician_id")
        ward_disp = ward or ("未定" if is_ja else "TBD")
        physician_disp = physician or ("未定" if is_ja else "TBD")
        if is_ja:
            return f"病棟：{ward_disp}　担当医師：{physician_disp}", facts
        return f"Ward: {ward_disp}, Attending physician: {physician_disp}", facts

    def _build_ncp_dietitian(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """担当管理栄養士名 — MVP: no dietitian staff role exists yet."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_DIETITIAN_FALLBACK_JA if is_ja else _NCP_DIETITIAN_FALLBACK_EN), []

    def _build_ncp_nutrition_risk(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """入院時栄養状態に関するリスク — BMI 3-tier threshold (coarse screening
        proxy, not a validated instrument like GLIM/MUST — design spec §4)."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        bmi = _o(ctx.patient, "bmi", None)
        if bmi is None:
            fallback = "栄養リスク：評価データなし" if is_ja else "Nutrition risk: no assessment data"
            return fallback, facts
        facts.append("patient.bmi")
        bmi_r = round(float(bmi), 1)
        if bmi_r < 18.5:
            return (
                f"低栄養リスク：高（BMI {bmi_r}）" if is_ja
                else f"Malnutrition risk: high (BMI {bmi_r})"
            ), facts
        if bmi_r > 25:
            return (
                f"過栄養傾向（BMI {bmi_r}）" if is_ja
                else f"Overnutrition tendency (BMI {bmi_r})"
            ), facts
        return (
            f"低栄養リスク：低（BMI {bmi_r}、リスクなし）" if is_ja
            else f"Malnutrition risk: low (BMI {bmi_r}, no risk identified)"
        ), facts

    def _build_ncp_nutrition_assessment(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養状態の評価と課題 — MVP fixed fallback."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_ASSESSMENT_FALLBACK_JA if is_ja else _NCP_ASSESSMENT_FALLBACK_EN), []

    def _build_ncp_nutrition_goals(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養管理計画 目標 — MVP fixed fallback."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_GOALS_FALLBACK_JA if is_ja else _NCP_GOALS_FALLBACK_EN), []

    def _build_ncp_nutrition_supply(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養補給に関する事項 (エネルギー/たんぱく質/補給方法) — standard
        initial-planning estimation formulas from PatientProfile.weight_kg
        (25-30 kcal/kg/day energy midpoint, 1.0-1.2 g/kg/day protein
        midpoint — design spec §3c). Route fixed to 経口 (oral) MVP default."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        weight = _o(ctx.patient, "weight_kg", None)
        if weight is None:
            fallback = "栄養補給量：算出データなし" if is_ja else "Nutrition supply: no data to compute"
            return fallback, facts
        facts.append("patient.weight_kg")
        energy = round(float(weight) * 27.5)
        protein = round(float(weight) * 1.1, 1)
        if is_ja:
            return (
                f"エネルギー：{energy}kcal／日　たんぱく質：{protein}g／日　"
                f"補給方法：経口"
            ), facts
        return (
            f"Energy: {energy} kcal/day, Protein: {protein} g/day, Route: oral"
        ), facts

    def _build_ncp_dysphagia_diet(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """嚥下調整食の必要性 — MVP fixed 「なし」."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_DYSPHAGIA_NONE_JA if is_ja else _NCP_DYSPHAGIA_NONE_EN), []

    def _build_ncp_dietary_content(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """食事内容 — MVP fixed fallback."""
        is_ja = ctx.target_lang == "ja"
        return (
            _NCP_DIETARY_CONTENT_FALLBACK_JA if is_ja else _NCP_DIETARY_CONTENT_FALLBACK_EN
        ), []

    def _build_ncp_nutrition_counseling(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養食事相談に関する事項 — MVP fixed fallback (collapses the 3 MHLW
        sub-items — admission/consult/discharge instruction — into one
        section; no per-item data source exists, design spec §2 row 7)."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_COUNSELING_FALLBACK_JA if is_ja else _NCP_COUNSELING_FALLBACK_EN), []

    def _build_ncp_other_issues(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """その他栄養管理上解決すべき課題 — MVP fixed fallback."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_OTHER_ISSUES_FALLBACK_JA if is_ja else _NCP_OTHER_ISSUES_FALLBACK_EN), []

    def _build_ncp_reassessment_timing(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養状態の再評価の時期 — MVP fixed fallback."""
        is_ja = ctx.target_lang == "ja"
        return (
            _NCP_REASSESSMENT_FALLBACK_JA if is_ja else _NCP_REASSESSMENT_FALLBACK_EN
        ), []

    def _build_ncp_discharge_evaluation(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """退院時及び終了時の総合的評価 — genuinely unknowable at plan-creation
        time; this system has no mechanism to revise a Stage-1 stub at a
        later encounter phase for this doc type (design spec §2 row 10)."""
        is_ja = ctx.target_lang == "ja"
        return (
            _NCP_DISCHARGE_EVAL_FALLBACK_JA if is_ja else _NCP_DISCHARGE_EVAL_FALLBACK_EN
        ), []
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/modules/document/narrative/test_template_generator_nutrition_care_plan.py -v`
Expected: PASS (all 13 tests).

- [ ] **Step 7: Run ruff and fix any line-length violations in the new code**

Run: `ruff check --output-format=concise clinosim/modules/document/narrative/template_generator.py tests/unit/modules/document/narrative/test_template_generator_nutrition_care_plan.py`
Fix any `E501` (line too long) violations by wrapping the offending line — check via `git diff` that the violation is in code you just added, not pre-existing (the `admission_care_plan` chain found pre-existing violations at lines ~1149-1150 in this file; do not touch those).

- [ ] **Step 8: Run the broader document narrative test suite to check no regression**

Run: `pytest tests/unit/modules/document/ -q`
Expected: PASS (all tests).

- [ ] **Step 9: Commit**

```bash
git add clinosim/modules/document/narrative/template_generator.py tests/unit/modules/document/narrative/test_template_generator_nutrition_care_plan.py
git commit -m "feat(chain2): TemplateNarrativeGenerator section builders for nutrition_care_plan"
```

---

### Task 5: Audit `lift_firing_proof` extension (positive + negative LOS gate)

**Files:**
- Modify: `clinosim/modules/document/audit.py`
- Test: `tests/unit/test_document_audit_alpha2.py`

**Interfaces:**
- Consumes: `document_enricher` (Task 3).
- Produces: 4 new `equality_checks` tuples in `_build_document_proof()`'s return value (mirroring the 4 added for `admission_care_plan`, but for the NEW `nutrition_care_plan` gate): `nutrition_care_plan_jp_inpatient_los10_count` (positive), `nutrition_care_plan_jp_inpatient_los5_count` (negative — the adv-1 lesson applied from the start), `nutrition_care_plan_jp_icu_los10_count` (positive), `nutrition_care_plan_us_inpatient_los10_count` (negative, country gate).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_document_audit_alpha2.py`:

```python
@pytest.mark.unit
def test_lift_firing_proof_includes_nutrition_care_plan_checks():
    """chain 2: nutrition_care_plan dispatch proof — LOS>7 gate, JP-only gate.

    Proves BOTH positive (LOS>7 fires) and negative (LOS<=7 does not fire)
    cases, per the admission_care_plan adv-1 lesson (design spec §5).
    """
    proof = _build_proof()
    labels = {c[0]: c for c in proof["equality_checks"]}
    expected_labels = (
        "nutrition_care_plan_jp_inpatient_los10_count",
        "nutrition_care_plan_jp_inpatient_los5_count",
        "nutrition_care_plan_jp_icu_los10_count",
        "nutrition_care_plan_us_inpatient_los10_count",
    )
    for label in expected_labels:
        assert label in labels, f"missing check {label!r}"
        _, actual, expected = labels[label]
        assert actual == expected, f"{label}: {actual!r} != {expected!r}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_document_audit_alpha2.py::test_lift_firing_proof_includes_nutrition_care_plan_checks -v`
Expected: FAIL — `AssertionError: missing check 'nutrition_care_plan_jp_inpatient_los10_count'`.

- [ ] **Step 3: Add the proof helper function**

Edit `clinosim/modules/document/audit.py`, add after `_proof_admission_care_plan` (before `_build_document_proof`):

```python
def _proof_nutrition_care_plan() -> dict[str, Any]:
    """chain 2: prove the nutrition_care_plan LOS>7 + JP-only gate fires.

    Four synthetic encounters (JP inpatient LOS=10, JP inpatient LOS=5, JP
    ICU LOS=10, US inpatient LOS=10) run through document_enricher; proves
    BOTH the positive dispatch (LOS>7 fires) and the negative dispatch
    (LOS<=7 does not fire, non-JP does not fire) — the admission_care_plan
    adv-1 lesson (that chain's first proof only tested one direction of a
    related gate) applied here from the start.
    """
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from clinosim.modules.document.engine import document_enricher

    def _run(encounter_type: str, los_days: int, country: str) -> int:
        admission_dt = datetime(2026, 7, 1, 10, 0)
        record: dict[str, Any] = {
            "patient": {"patient_id": f"pt-ncp-proof-{encounter_type}-{los_days}-{country}"},
            "encounters": [
                {
                    "encounter_id": f"enc-ncp-proof-{encounter_type}-{los_days}-{country}",
                    "encounter_type": encounter_type,
                    "status": "completed",
                    "admission_datetime": admission_dt,
                    "discharge_datetime": admission_dt + timedelta(days=los_days),
                    "attending_physician_id": "dr-ncp-proof",
                    "primary_nurse_id": "ns-ncp-proof",
                }
            ],
            "documents": [],
            "extensions": {},
            "physiological_states": [],
        }
        ctx = SimpleNamespace(
            master_seed=42, records=[record], config=SimpleNamespace(country=country)
        )
        document_enricher(ctx)
        return len([
            d for d in record["documents"] if getattr(d, "task_type", "") == "nutrition_care_plan"
        ])

    return {
        "jp_inpatient_los10_count": _run("inpatient", 10, "jp"),
        "jp_inpatient_los5_count": _run("inpatient", 5, "jp"),
        "jp_icu_los10_count": _run("icu", 10, "jp"),
        "us_inpatient_los10_count": _run("inpatient", 10, "us"),
    }
```

- [ ] **Step 4: Wire the proof into `_build_document_proof`**

Edit `clinosim/modules/document/audit.py`. Near the `_acp_proof = _proof_admission_care_plan()` line, add:

```python
    # chain 2: nutrition_care_plan LOS>7 + JP-only gate proof.
    _ncp_proof = _proof_nutrition_care_plan()
```

Then, in the `equality_checks` list, immediately before the closing `]` (after the `admission_care_plan_jp_rehab_inpatient_count` tuple), add:

```python
            # === chain 2: nutrition_care_plan gate proof (+4, total = 45) ===
            (
                "nutrition_care_plan_jp_inpatient_los10_count",
                _ncp_proof["jp_inpatient_los10_count"],
                1,
            ),
            (
                "nutrition_care_plan_jp_inpatient_los5_count",
                _ncp_proof["jp_inpatient_los5_count"],
                0,
            ),
            (
                "nutrition_care_plan_jp_icu_los10_count",
                _ncp_proof["jp_icu_los10_count"],
                1,
            ),
            (
                "nutrition_care_plan_us_inpatient_los10_count",
                _ncp_proof["us_inpatient_los10_count"],
                0,
            ),
```

- [ ] **Step 5: Update the module docstring check count**

Edit `clinosim/modules/document/audit.py` docstring near the top (`41 equality_checks in lift_firing_proof ...`) — change `41` to `45` and append a changelog line after the chain-2 `admission_care_plan` entry:

```
  chain 2 nutrition_care_plan gate (+4, total = 45):
    `nutrition_care_plan_jp_inpatient_los10_count` (positive: LOS>7 fires) /
    `nutrition_care_plan_jp_inpatient_los5_count` (negative: LOS<=7 does not
    fire) / `nutrition_care_plan_jp_icu_los10_count` (positive, icu) /
    `nutrition_care_plan_us_inpatient_los10_count` (negative, country gate).
    See `_proof_nutrition_care_plan`.
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_document_audit_alpha2.py -v`
Expected: PASS (all tests, including `test_all_proof_checks_pass` and the new `test_lift_firing_proof_includes_nutrition_care_plan_checks`).

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/document/audit.py tests/unit/test_document_audit_alpha2.py
git commit -m "feat(chain2): lift_firing_proof gate checks for nutrition_care_plan (+4, total=45)"
```

---

### Task 6: Full-chain integration test (Stage 1 → Stage 2 → FHIR)

**Files:**
- Create: `tests/integration/test_nutrition_care_plan_chain.py`

**Interfaces:**
- Consumes: `document_enricher` (Task 3), `TemplateNarrativePass`, `_bb_compositions` — all pre-existing/from Task 3, no new interfaces produced.

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_nutrition_care_plan_chain.py`, following the exact pattern of `tests/integration/test_admission_care_plan_chain.py` (structural CIF dict construction → `document_enricher` → `TemplateNarrativePass.run()` → read the written narrative JSON → `_bb_compositions` via a `BundleContext`-shaped `SimpleNamespace`):

```python
"""Full chain integration test: document_enricher → TemplateNarrativePass →
FHIR Composition, for nutrition_care_plan (chain 2).

Verifies: Composition emitted with LOINC 80791-7, exactly 12 sections, 100%
Japanese text, ONLY for LOS>7 JP inpatient/ICU encounters — correctly ABSENT
for LOS<=7 and for out-of-scope cohorts (US, outpatient, emergency,
rehab_inpatient).
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


def _jp_patient_dict(patient_id: str, los_days: int, encounter_type: str = "inpatient") -> dict:
    admission_dt = datetime(2026, 7, 1, 10, 0)
    record: dict = {
        "patient": {"patient_id": patient_id, "age": 70, "sex": "F", "bmi": 21.0, "weight_kg": 55.0},
        "encounters": [
            {
                "encounter_id": f"enc-{patient_id}",
                "encounter_type": encounter_type,
                "status": "completed",
                "admission_datetime": admission_dt,
                "discharge_datetime": admission_dt + timedelta(days=los_days),
                "attending_physician_id": "dr-ncp-chain-test",
                "primary_nurse_id": "ns-ncp-chain-test",
                "ward_id": "5N",
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
@pytest.mark.parametrize("encounter_type", ["inpatient", "icu"])
def test_jp_los_gt_7_produces_nutrition_care_plan_composition(encounter_type: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        patient_id = f"pt-ncp-chain-{encounter_type}"
        patient_dict = _jp_patient_dict(patient_id, los_days=10, encounter_type=encounter_type)
        _write_structural_cif(tmp, patient_dict)

        manifest = TemplateNarrativePass(tmp, version_id="v1", country="jp").run()
        assert manifest.document_counts_by_type.get("nutrition_care_plan") == 1

        narrative_dir = os.path.join(tmp, "narratives", "v1", "documents", f"enc-{patient_id}")
        ncp_stub = next(
            d for d in patient_dict["documents"] if d["task_type"] == "nutrition_care_plan"
        )
        ncp_file = os.path.join(narrative_dir, f"{ncp_stub['document_id']}.json")
        assert os.path.exists(ncp_file)
        with open(ncp_file) as f:
            doc_payload = json.load(f)

        ncp_stub["narrative"] = doc_payload["narrative"]
        patient_dict["extensions"] = {}
        bundle_ctx = _make_bundle_ctx(patient_dict, country="jp")
        comp_out = _bb_compositions(bundle_ctx)
        assert len(comp_out) == 1
        comp = comp_out[0]
        assert comp["type"]["coding"][0]["code"] == "80791-7"
        assert comp["type"]["coding"][0]["display"] == "栄養管理計画書"
        assert len(comp["section"]) == 12

        all_text = " ".join(s["title"] + s["text"]["div"] for s in comp["section"])
        has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in all_text)
        assert has_jp


@pytest.mark.integration
def test_jp_los_5_produces_no_nutrition_care_plan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        patient_dict = _jp_patient_dict("pt-ncp-chain-los5", los_days=5)
        assert not any(d["task_type"] == "nutrition_care_plan" for d in patient_dict["documents"])


@pytest.mark.integration
@pytest.mark.parametrize("encounter_type,country", [
    ("inpatient", "us"),
    ("outpatient", "jp"),
    ("emergency", "jp"),
    ("rehab_inpatient", "jp"),
])
def test_out_of_scope_cohorts_produce_no_nutrition_care_plan(
    encounter_type: str, country: str
) -> None:
    admission_dt = datetime(2026, 7, 1, 10, 0)
    record: dict = {
        "patient": {"patient_id": f"pt-ncp-chain-{encounter_type}-{country}", "age": 50, "sex": "M"},
        "encounters": [
            {
                "encounter_id": f"enc-ncp-{encounter_type}-{country}",
                "encounter_type": encounter_type,
                "status": "completed",
                "admission_datetime": admission_dt,
                "discharge_datetime": admission_dt + timedelta(days=10),
                "attending_physician_id": "dr-ncp-chain-test",
            }
        ],
        "documents": [],
        "extensions": {},
        "physiological_states": [],
    }
    ctx = SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace(country=country))
    document_enricher(ctx)
    ncp_docs = [d for d in record["documents"] if d.task_type == "nutrition_care_plan"]
    assert len(ncp_docs) == 0
```

- [ ] **Step 2: Run test, fix any structural-CIF-shape mismatches**

Run: `pytest tests/integration/test_nutrition_care_plan_chain.py -v -m integration`
Expected: this may initially fail on structural details not anticipated by reading source alone (e.g. exact key names `NarrativeContext` expects for `patient.bmi`/`patient.weight_kg` when constructed from a raw JSON dict via `PatientProfile`-shaped deserialization — check `passes.py`'s `_build_context` reads `patient_dict.get("patient")` and passes it through as `ctx.patient` verbatim, a plain dict, and `_o()` supports dict access, so `bmi`/`weight_kg` keys should resolve — but verify empirically). Fix the test's fixture shape to match reality — do NOT modify production code to accommodate the test. Re-run until PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_nutrition_care_plan_chain.py
git commit -m "test(chain2): full-chain integration test for nutrition_care_plan (Stage1→Stage2→FHIR, LOS>7 gate)"
```

---

### Task 7: Golden regen, TODO.md deferred entries, full suite, PR

**Files:**
- Modify: `TODO.md` (mark 栄養管理計画書 line done in the β-JP-1 厚労省必須文書 list; add the deferred-scope entries from spec §4: dietitian role, real nutrition-assessment data, discharge-time revision, plus re-affirm 看護必要度評価票 and リハビリテーション計画書 remain deferred with the corrected terminology from spec §1)
- Regenerate: any of the 3 JP profile goldens whose realized LOS > 7 (all 3 are very likely to qualify — `jp_inpatient_bacterial_pneumonia` / `jp_icu_sepsis_hai_clabsi` / `jp_inpatient_copd_exacerbation` all showed `estimated_los` means of 14/35/12 days in the admission_care_plan chain's golden diff, spec §5 — but VERIFY empirically per-profile rather than assuming, since `estimated_los` is the disease's target_los mean, not necessarily each fixture's realized `los_days`)

- [ ] **Step 1: Determine which profiles have LOS > 7 empirically**

Run:
```bash
for p in jp_inpatient_bacterial_pneumonia jp_icu_sepsis_hai_clabsi jp_inpatient_copd_exacerbation; do
  echo "=== $p ==="
  clinosim regenerate-goldens --profile "$p"
  git diff --stat -- "tests/fixtures/patient_profiles/${p}.golden.json"
done
```
For each profile, check `git diff` — if a new `nutrition_care_plan` document block appears, that profile's realized LOS > 7 (keep the regen). If the diff is empty, that profile's LOS <= 7 (the regen produced no change — this is a valid, useful negative confirmation of the LOS gate per spec §5, not a mistake). Run `git checkout -- <path>` only for genuinely empty-diff profiles to avoid an unnecessary no-op commit (verify with `git diff --stat` showing 0 changes first).

- [ ] **Step 2: Regenerate the corresponding `.llm-mock.golden.json` legs for every profile that changed in Step 1**

Run (only for profiles that had a real diff in Step 1):
```bash
clinosim regenerate-goldens --profile <profile> --provider mock
```

- [ ] **Step 3: Categorize the golden diff (AD-66 Rule 2)**

Run: `git diff tests/fixtures/patient_profiles/*.golden.json tests/fixtures/patient_profiles/*.llm-mock.golden.json`
Expected: every changed line is a new, additive `nutrition_care_plan` document block; no pre-existing document's content changed. Read the actual rendered section content and confirm it's clinically coherent (correct BMI-derived risk tier, plausible kcal/protein numbers for the patient's weight, ward/physician IDs present). If any pre-existing document changed, STOP and investigate (AD-66 Rule 2).

- [ ] **Step 4: Update TODO.md**

Edit `TODO.md`, find the "β-JP-1 phase — JP localization + 厚労省必須文書" section and replace the 栄養管理計画書 bullet:

```markdown
- ~~**栄養管理計画書** (Nutrition care plan)~~ — **DONE (chain 2, 2026-07-03)**:
  LOINC 80791-7, Composition, 12 sections per MHLW 別紙23, JP-only,
  inpatient/icu only, emitted only for admissions with LOS > 7 days (new
  `admission_once_los_gt_7` generation_frequency). Only 3/12 sections are
  data-driven (ward/physician from Encounter, nutrition_risk from
  PatientProfile.bmi, nutrition_supply energy/protein estimate from
  PatientProfile.weight_kg); the other 9 are MVP fixed fallbacks — see
  deferred entries below.
```

Update the 看護必要度D表 bullet to correct the terminology finding from spec §1:

```markdown
- **重症度、医療・看護必要度に係る評価票**(TODO.mdの旧記載「看護必要度D表」は誤記 — 正式名称は
  A項目/B項目/C項目の評価票、"D表"という区分はMHLW公式には存在しない、chain 2調査で訂正
  2026-07-03)— DPC/診療報酬算定用の国内専用スコアリング様式。**適切なLOINCコードなし**
  (検証済み:LOINC 80346-0 "Nursing physiologic assessment panel"は米国の一般看護身体
  アセスメントパネルで別物、誤用不可)。ローカルコード体系でのQuestionnaireResponse実装が
  必要(現状は`FormatType.QUESTIONNAIRE_RESPONSE`のinfrastructure stubのみ)。GCS/ADLデータは
  `nursing_enricher.py`に既存だが、評価票のA/B/C項目粒度とは一致しない。
```

Then add the formal deferred entries (near where the 入院診療計画書 nutrition-flag deferred entry already lives):

```markdown
### chain 2 deferred: nutrition_care_plan real data derivation

`_build_ncp_dietitian` / `_build_ncp_nutrition_assessment` /
`_build_ncp_nutrition_goals` / `_build_ncp_dysphagia_diet` /
`_build_ncp_dietary_content` / `_build_ncp_nutrition_counseling` /
`_build_ncp_other_issues` / `_build_ncp_reassessment_timing` (8 of 12
sections) render MVP fixed fallback strings — no CIF data source exists for
dietitian staff, real nutrition assessment/counseling content, or dysphagia
screening. Revisit when a richer nutrition-assessment data model + dietitian
staff role are built. `nutrition_risk`'s BMI-threshold heuristic is a coarse
screening proxy (not GLIM/MUST-validated) — acceptable for synthetic-data
MVP but should not be treated as clinically authoritative if reused
elsewhere.

### chain 2 deferred: nutrition_care_plan discharge-time revision

`_build_ncp_discharge_evaluation` always renders a fixed "pending" phrase —
this system has no mechanism to re-render a Stage-1 document stub at a later
encounter phase. If discharge-time nutrition evaluation becomes a priority,
this would need either a second document type (mirroring the
`nursing_discharge_summary` vs `admission_nursing_assessment` split
precedent) or a new Stage-2 revision mechanism.
```

- [ ] **Step 5: Run the full test suite**

Run: `pytest -x -q`
Expected: all tests pass.

- [ ] **Step 6: Run the JP-cohort audit**

Run:
```bash
rm -rf /tmp/ncp_audit_jp
clinosim generate --population 300 --country JP --seed 42 --output /tmp/ncp_audit_jp
clinosim narrate --cif-dir /tmp/ncp_audit_jp/cif --provider template --country JP
clinosim export-fhir --cif-dir /tmp/ncp_audit_jp/cif --country JP
clinosim audit run -d /tmp/ncp_audit_jp
```
Expected: `document_chain`'s `silent_no_op` axis PASS including all 4 new `nutrition_care_plan_*` checks. `grep -c "80791-7" /tmp/ncp_audit_jp/fhir_r4/Composition.ndjson` should show a count roughly proportional to the inpatient/icu-with-LOS>7 subset of the cohort (fewer than the `admission_care_plan` count from the same run, since this is LOS-gated). The overall audit may show the same pre-existing small-population CareTeam nurse-roster `FAIL` documented in TODO.md ("Small-p roster export gap") — that is unrelated to this PR, do not attempt to fix it here.

- [ ] **Step 7: Commit the golden regen + TODO.md update**

```bash
git add tests/fixtures/patient_profiles/*.golden.json tests/fixtures/patient_profiles/*.llm-mock.golden.json TODO.md
git commit -m "$(cat <<'EOF'
feat(chain2): regenerate applicable JP profile goldens + TODO.md deferred entries

JP inpatient/icu profiles with realized LOS>7 now include the
nutrition_care_plan document (LOINC 80791-7). AD-66 Rule 2 diff
categorized: additive only. TODO.md corrects the "看護必要度D表" terminology
(no official "D表" designation exists) and formally defers both remaining
厚労省文書 (看護必要度評価票, リハビリテーション計画書) with the LOINC/scope
findings from this chain's design spec.
EOF
)"
```

- [ ] **Step 8: Push and open the PR**

```bash
git push -u origin feature/chain2-nutrition-care-plan
gh pr create --title "feat(chain2): nutrition care plan document (栄養管理計画書, LOINC 80791-7)" --body "$(cat <<'EOF'
## Summary
- Second chain-2 (厚労省4帳票) sub-project: adds `nutrition_care_plan` as the
  11th `DocumentType`, LOS>7-gated via a new `admission_once_los_gt_7`
  generation_frequency (one new document_enricher dispatch branch — the key
  architectural delta from admission_care_plan, which needed zero engine
  changes).
- LOINC tractability was checked for all 3 remaining 厚労省文書 before choosing
  this one: 看護必要度評価票 has no defensible LOINC match (also corrects a
  TODO.md terminology error — "看護必要度D表" is not an official MHLW term),
  リハビリテーション計画書 has no rehab-specific match; 栄養管理計画書's LOINC
  80791-7 is an excellent, specific match.
- MVP scope (user-confirmed tradeoff): only 3 of 12 composition sections are
  genuinely data-driven (ward/physician, BMI-derived nutrition risk,
  weight-derived energy/protein estimate); 9 are fixed fallbacks pending a
  dietitian role + real nutrition-assessment data model (formal TODO.md
  entries added).

## Test plan
- [x] `pytest -x -q` full suite green
- [x] `clinosim audit run` on a JP cohort: document_chain silent_no_op axis
      PASS, all 4 new nutrition_care_plan gate checks green — BOTH positive
      (LOS>7 fires) and negative (LOS<=7 does not fire) cases proven at unit
      AND audit-gate level (applying the admission_care_plan adv-1 lesson
      from the start this time)
- [x] Applicable JP inpatient/icu profile goldens regenerated, diff
      categorized additive-only per AD-66 Rule 2, clinical content reviewed
- [x] Integration test proves Composition emission (12 sections, LOINC
      80791-7, 100% Japanese text) for LOS>7 JP inpatient/icu, and correct
      absence for LOS<=7 and out-of-scope cohorts

Spec: docs/superpowers/specs/2026-07-03-nutrition-care-plan-design.md
Plan: docs/superpowers/plans/2026-07-03-nutrition-care-plan.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Notes (completed during plan authoring)

- **Spec coverage**: §1 (LOINC tractability triage) → captured in Task 7's TODO.md update (the corrected terminology + deferral rationale for the other 2 docs). §2 (data sourcing table) → Task 4 builders map 1:1 to the table. §3a (new dispatch condition) → Task 3. §3b (registry) → Tasks 1-2. §3c (fact extraction) → Task 4. §3d (no FHIR changes) → verified by construction (no `_fhir_composition.py` edits anywhere in this plan). §4 (out of scope) → Task 7 Step 4 formal TODO.md entries. §5 (testing, esp. the positive+negative LOS gate emphasis) → Tasks 3, 5, 6 all include explicit negative-case tests. §6 (verification gate) → Task 7 Steps 5-6.
- **Placeholder scan**: no TBD/TODO-without-content. All 9 MVP-fallback builder methods are real, working code with real fallback strings — the "placeholder" nature is a deliberate spec-documented data-coverage limitation, not an unwritten stub.
- **Type consistency**: all 12 new builder methods return `tuple[str, list[str]]`, matching every existing builder and the `admission_care_plan` chain's `_build_acp_*` methods exactly. `_o()` import, lazy-import pattern (not needed here — no `code_lookup` call in this doc type, unlike `admission_care_plan`'s diagnosis section), and fallback-constant naming (`_NCP_*_JA`/`_NCP_*_EN`) all follow the established file convention verified by direct source reading (current post-merge line numbers) before this plan was written.
- **New pattern vs. precedent**: Task 3 (the `document_enricher` dispatch branch) is the one task with no direct precedent in the `admission_care_plan` chain — extra care was taken to mirror the exact style of the neighboring `daily`/`daily_3shift` branches (early-`continue` LOS guard, same `ClinicalDocument` field population) rather than inventing a new idiom.
