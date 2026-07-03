# Admission Care Plan Document (入院診療計画書) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `admission_care_plan` (入院診療計画書, LOINC 18776-5) as the 10th `DocumentType` in clinosim's narrative pipeline — a JP-only, 10-section Composition document reusing 100% of the existing `NarrativePass`/`DocumentTypeSpec`/generic-Composition machinery, with zero FHIR builder changes.

**Architecture:** Pure additive spec-driven extension. One new `DocumentType` enum value + one `document_type_specs.yaml` entry (`countries_supported: [jp]`, `encounter_types_supported: [inpatient, icu]`, `generation_frequency: admission_once`, `stage2_strategy: template_only`) flows automatically through the existing `document_enricher` (Stage 1 stub) → `TemplateNarrativePass` (Stage 2 render) → generic `_fhir_composition.py` (Stage 3 FHIR) chain. The only new code is 10 section-builder methods on `TemplateNarrativeGenerator` plus one LOINC code registration.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy strict, PyYAML, existing clinosim `_shared.get_attr_or_key` (`_o`) dual-access helper, `clinosim.codes.lookup`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-03-admission-care-plan-design.md` (approved, committed `f5c6fe0c7d`). Every task below implements one part of that spec; do not add scope beyond it.
- Branch: create `feature/chain2-admission-care-plan` off `master` before Task 1.
- Code comments/docstrings: English. Commit messages: `feat(chain2): ...` / `test(chain2): ...` per this project's convention.
- **No new CIF schema fields.** All 10 sections source from fields that already exist on `NarrativeContext` / `Encounter` / `ProcedureRecord` / `ClinicalDiagnosis` — verified during planning (see Task 3 source table).
- **No FHIR builder changes** — `_fhir_composition.py` is generic over `spec.composition_sections`; do not touch it.
- Determinism (AD-16): no `datetime.now()` / `random.random()` in any new code. All new builders are pure functions of `ctx`.
- `codes/data/*.yaml` requires an authoritative, non-fabricated `en` field — LOINC 18776-5 "Plan of care note" already verified via web search during brainstorming (see spec §2).
- Run `pytest -m unit -q` after every task; run the full suite (`pytest -x -q`) before the final PR (Task 7).
- One deliberate spec deviation, decided during planning (documented in Task 3): `estimated_los` section sources from `ctx.los_days` (the already-computed actual/deterministic length of stay) rather than re-reading `disease_protocol.target_los` distributions — simpler, avoids any RNG/no-op risk, and is semantically equivalent for a synthetic dataset. Note this in the PR description.
- Second deviation (documented in Task 3): `other_plans` renders a fixed cross-reference phrase ("see nursing documentation") rather than pulling `admission_nursing_assessment` content — `NarrativeContext` does not carry other stub types' rendered content at this call site (each spec is walked independently in `NarrativePass.run`), so reusing that content is not actually available without a larger architecture change out of this chain's scope.

---

### Task 1: LOINC code registration + `DocumentType` enum value

**Files:**
- Modify: `clinosim/codes/data/loinc.yaml` (insert after line 25, the existing document-type block)
- Modify: `clinosim/types/document.py:40` (append to `DocumentType` enum, after `ED_TRIAGE_NOTE`)
- Test: `tests/unit/modules/document/narrative/test_registry.py` (new test function)

**Interfaces:**
- Produces: `DocumentType.ADMISSION_CARE_PLAN` (value `"admission_care_plan"`), consumed by Task 2's YAML spec entry and Task 3's builder registration.
- Produces: `clinosim.codes.lookup("loinc", "18776-5", "ja")` → `"入院診療計画書"`, `lookup("loinc", "18776-5", "en")` → `"Plan of care note"`, consumed by the FHIR `Composition.type`/`title` fields at export time (no code change needed there — already generic).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/modules/document/narrative/test_registry.py` (append at end of file):

```python
def test_admission_care_plan_loinc_code_resolves() -> None:
    """LOINC 18776-5 ('Plan of care note') must resolve in both languages —
    verified against loinc.org / findacode.com during design (spec §2)."""
    from clinosim.codes import lookup as code_lookup

    assert code_lookup("loinc", "18776-5", "en") == "Plan of care note"
    assert code_lookup("loinc", "18776-5", "ja") == "入院診療計画書"


def test_document_type_has_admission_care_plan() -> None:
    assert DocumentType.ADMISSION_CARE_PLAN.value == "admission_care_plan"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/modules/document/narrative/test_registry.py::test_admission_care_plan_loinc_code_resolves tests/unit/modules/document/narrative/test_registry.py::test_document_type_has_admission_care_plan -v`
Expected: FAIL — `AttributeError: ADMISSION_CARE_PLAN` (enum value doesn't exist yet) and/or LOINC lookup returning the bare code (unregistered).

- [ ] **Step 3: Add the LOINC code**

Edit `clinosim/codes/data/loinc.yaml`, insert immediately after the `18842-5` entry (line 25):

```yaml
  18776-5:
    en: Plan of care note
    ja: 入院診療計画書
```

- [ ] **Step 4: Add the enum value**

Edit `clinosim/types/document.py`, in the `DocumentType` class, after the `ED_TRIAGE_NOTE` line:

```python
    ED_TRIAGE_NOTE = "ed_triage_note"                             # LOINC 54094-8 (verified 2026-07)
    # β-JP-1 chain 2 (厚労省4帳票, first sub-project)
    ADMISSION_CARE_PLAN = "admission_care_plan"                   # LOINC 18776-5 (verified 2026-07-03)
```

- [ ] **Step 4b (discovered during execution): sync `LLMTaskType` in `llm_service/engine.py`**

Not anticipated by the original plan — `clinosim/modules/llm_service/engine.py` runs an
import-time validator (`_validate_document_task_sync()`, N-3 N-chain work) that requires
every `DocumentType` value to also exist as a NARRATIVE-category `LLMTaskType`. Adding the
enum value in Step 4 alone breaks test collection project-wide (`ImportError` at import time)
until this is added too. Add to `clinosim/modules/llm_service/engine.py`:

```python
    ED_TRIAGE_NOTE = "ed_triage_note"                              # LOINC 54094-8
    # chain 2 (厚労省4帳票, N-3 enum sync)
    ADMISSION_CARE_PLAN = "admission_care_plan"                    # LOINC 18776-5
```

in the `LLMTaskType` enum, plus:

```python
    LLMTaskType.ADMISSION_CARE_PLAN: LLMTaskCategory.NARRATIVE,
```

in `TASK_CATEGORY`, plus:

```python
    LLMTaskType.ADMISSION_CARE_PLAN: "18776-5",           # Plan of care note
```

in `DOCUMENT_LOINC` (required — the doc-producing / has-a-LOINC-code branch per
`_validate_document_task_sync`'s docstring). This also means `tests/unit/test_llm_task_enum_sync.py`
must pass with no changes (it's fully generic, no hardcoded per-type assertions) —
run it as part of Step 5 below.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/modules/document/narrative/test_registry.py -v`
Expected: PASS (all tests in the file, including the 2 new ones).

- [ ] **Step 6: Commit**

```bash
git add clinosim/codes/data/loinc.yaml clinosim/types/document.py tests/unit/modules/document/narrative/test_registry.py
git commit -m "feat(chain2): register LOINC 18776-5 + DocumentType.ADMISSION_CARE_PLAN"
```

---

### Task 2: `document_type_specs.yaml` entry + registry gating

**Files:**
- Modify: `clinosim/modules/document/reference_data/document_type_specs.yaml` (append after `ed_triage_note`)
- Modify: `clinosim/modules/document/narrative/registry.py` (`SUPPORTED_DOCUMENT_TYPES` frozenset)
- Test: `tests/unit/modules/document/narrative/test_registry.py`, `tests/unit/modules/document/narrative/test_encounter_types_supported.py`

**Interfaces:**
- Consumes: `DocumentType.ADMISSION_CARE_PLAN` (Task 1).
- Produces: `specs_for_country("jp")` includes an entry with `type_key == "admission_care_plan"`; `specs_for_country("us")` does not. `specs_for_encounter_type("inpatient")` and `("icu")` include it; `("rehab_inpatient")`, `("outpatient")`, `("emergency")` do not. Consumed by Task 4 (`document_enricher` dispatch) and Task 6 (integration test).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/modules/document/narrative/test_registry.py`:

```python
def test_registry_covers_admission_care_plan() -> None:
    specs = load_document_type_specs()
    assert DocumentType.ADMISSION_CARE_PLAN in specs


def test_admission_care_plan_spec_metadata() -> None:
    specs = load_document_type_specs()
    acp = specs[DocumentType.ADMISSION_CARE_PLAN]
    assert acp.loinc_code == "18776-5"
    assert acp.format_type == FormatType.COMPOSITION
    assert acp.countries_supported == ("jp",)
    assert acp.generation_frequency == "admission_once"
    assert acp.stage2_strategy == "template_only"
    assert set(acp.composition_sections) == {
        "ward_and_room", "other_staff", "diagnosis", "symptoms",
        "treatment_plan", "test_schedule", "surgery_schedule",
        "estimated_los", "special_nutrition_management", "other_plans",
    }


def test_admission_care_plan_is_jp_only() -> None:
    us_specs = specs_for_country("us")
    jp_specs = specs_for_country("jp")
    assert "admission_care_plan" not in [s.type_key for s in us_specs]
    assert "admission_care_plan" in [s.type_key for s in jp_specs]
```

Append to `tests/unit/modules/document/narrative/test_encounter_types_supported.py`:

```python
def test_admission_care_plan_excludes_rehab_inpatient() -> None:
    """rehab_inpatient uses the MHLW 別紙２の２ variant form, not this spec (design §2)."""
    from clinosim.modules.document.narrative.registry import load_document_type_specs
    from clinosim.types.document import DocumentType

    specs = load_document_type_specs()
    acp = specs[DocumentType.ADMISSION_CARE_PLAN]
    assert set(acp.encounter_types_supported) == {"inpatient", "icu"}

    inpatient_keys = {s.type_key for s in specs_for_encounter_type("inpatient")}
    icu_keys = {s.type_key for s in specs_for_encounter_type("icu")}
    rehab_keys = {s.type_key for s in specs_for_encounter_type("rehab_inpatient")}
    outpatient_keys = {s.type_key for s in specs_for_encounter_type("outpatient")}
    emergency_keys = {s.type_key for s in specs_for_encounter_type("emergency")}
    assert "admission_care_plan" in inpatient_keys
    assert "admission_care_plan" in icu_keys
    assert "admission_care_plan" not in rehab_keys
    assert "admission_care_plan" not in outpatient_keys
    assert "admission_care_plan" not in emergency_keys
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/modules/document/narrative/test_registry.py tests/unit/modules/document/narrative/test_encounter_types_supported.py -v`
Expected: FAIL — `KeyError: DocumentType.ADMISSION_CARE_PLAN` (spec not in YAML yet) and the `SUPPORTED_DOCUMENT_TYPES` forward/reverse-coverage validator (registry.py Layer 4) will raise `ValueError` because the enum exists (Task 1) but has no YAML entry.

- [ ] **Step 3: Add the YAML spec entry**

Append to `clinosim/modules/document/reference_data/document_type_specs.yaml` (end of file, after `ed_triage_note`):

```yaml

  # === chain 2 (厚労省4帳票, first sub-project, 2026-07-03) ===
  # LOINC 18776-5 verified via web search (loinc.org / findacode.com) —
  # "Plan of care note" is the correct generic match; MHLW form 別紙２
  # (https://www.mhlw.go.jp/bunya/iryouhoken/iryouhoken15/dl/h24_02-07-40.pdf)
  # confirmed the 10 core sections below (design spec §2). JP-only — the
  # first jp-only entry in this registry. rehab_inpatient uses a different
  # MHLW form (別紙２の２) and is intentionally excluded.
  admission_care_plan:
    loinc_code: "18776-5"
    format_type: composition
    countries_supported: [jp]
    encounter_types_supported: [inpatient, icu]
    generation_frequency: admission_once
    composition_sections:
      - ward_and_room
      - other_staff
      - diagnosis
      - symptoms
      - treatment_plan
      - test_schedule
      - surgery_schedule
      - estimated_los
      - special_nutrition_management
      - other_plans
    stage2_strategy: template_only
    llm_enabled_sections: []
```

- [ ] **Step 4: Register the enum in `SUPPORTED_DOCUMENT_TYPES`**

Edit `clinosim/modules/document/narrative/registry.py`. Change the comment and set:

```python
# α-min-2 scope = 9 doc types (α-min-1 3 + α-min-2 6); chain 2 adds 1 = 10
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
    # chain 2 addition
    DocumentType.ADMISSION_CARE_PLAN,
})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/modules/document/narrative/test_registry.py tests/unit/modules/document/narrative/test_encounter_types_supported.py -v`
Expected: PASS (all tests, including the pre-existing `test_registry_covers_α_min_1_doc_types` etc. — the Layer 4 forward/reverse-coverage validator now passes since YAML and enum agree).

- [ ] **Step 5b (discovered during execution): update 3 pre-existing hardcoded fixtures + 3 count assertions**

`test_load_raises_on_missing_required_field` / `test_load_raises_on_null_entry` /
`test_load_raises_on_empty_countries_supported` each hardcode a full 9-entry `bad_data["specs"]`
dict to exercise one specific validator layer. Once `SUPPORTED_DOCUMENT_TYPES` has 10 members,
the Layer-4 forward/reverse-coverage check (which runs BEFORE the per-field loop) fires first
on these 9-entry dicts with a "drift: missing=['admission_care_plan']" error instead of the
message each test expects — added a 10th valid `admission_care_plan` entry to all 3 dicts so
the intended validator layer is what actually fires. Also updated 3 count-assertion tests that
hardcoded the pre-chain-2 totals: `test_load_specs_returns_9_total` → `..._10_total`,
`test_supported_document_types_covers_9_entries` → `..._10_entries`,
`test_specs_for_encounter_type_inpatient_returns_6_specs` → `..._7_specs` (admission_care_plan
adds one more inpatient-restricted spec). None of this was anticipated in the original plan —
caught by running the full registry test file, not just the 2 new test functions.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/document/reference_data/document_type_specs.yaml clinosim/modules/document/narrative/registry.py tests/unit/modules/document/narrative/test_registry.py tests/unit/modules/document/narrative/test_encounter_types_supported.py
git commit -m "feat(chain2): document_type_specs.yaml entry for admission_care_plan (JP-only, inpatient/icu)"
```

---

### Task 3: Template generator — 10 section builders

**Files:**
- Modify: `clinosim/modules/document/narrative/template_generator.py`
- Test: Create `tests/unit/modules/document/narrative/test_template_generator_admission_care_plan.py`

**Interfaces:**
- Consumes: `NarrativeContext` fields `encounter` (dict-like, keys `ward_id`/`bed_number`/`primary_nurse_id`), `diagnoses` (`list[ClinicalDiagnosis]`), `disease_protocol`, `lab_results`, `procedures` (`list[ProcedureRecord]`, filter on `category_code == "387713003"`), `los_days` (`int`), `target_lang` (`"en"`/`"ja"`).
- Produces: `TemplateNarrativeGenerator.generate(ctx, spec)` returns a `NarrativeOutput` whose `.sections` dict has all 10 keys from `spec.composition_sections`, each a non-empty string, when `ctx.document_type == DocumentType.ADMISSION_CARE_PLAN`. Consumed by Task 4 (enricher/pass integration) and Task 6 (FHIR integration test).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/modules/document/narrative/test_template_generator_admission_care_plan.py`:

```python
"""Tests for TemplateNarrativeGenerator admission_care_plan sections (chain 2).

Mirrors the fixture style of test_template_generator_alpha2.py — SimpleNamespace
for encounter/protocol-shaped objects (exercises the _o() dict/dataclass dual
access path), dict for ClinicalDiagnosis-shaped objects.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, FormatType, NarrativeContext
from clinosim.types.patient import PatientProfile

_ACP_SECTIONS = (
    "ward_and_room", "other_staff", "diagnosis", "symptoms",
    "treatment_plan", "test_schedule", "surgery_schedule",
    "estimated_los", "special_nutrition_management", "other_plans",
)


def _make_spec() -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key="admission_care_plan",
        loinc_code="18776-5",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp",),
        generation_frequency="admission_once",
        composition_sections=_ACP_SECTIONS,
        encounter_types_supported=("inpatient", "icu"),
        stage2_strategy="template_only",
    )


def _make_encounter(
    ward_id: str = "4W",
    bed_number: str = "401-2",
    primary_nurse_id: str = "",
) -> Any:
    return SimpleNamespace(
        encounter_id="enc-acp-test",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        ward_id=ward_id,
        bed_number=bed_number,
        primary_nurse_id=primary_nurse_id,
    )


def _make_diagnosis(admission_diagnosis_code: str = "J18.9") -> Any:
    return SimpleNamespace(
        admission_diagnosis_code=admission_diagnosis_code,
        admission_diagnosis_system="icd-10",
        discharge_diagnosis_code="",
        discharge_diagnosis_system="",
    )


def _make_procedure(category_code: str = "387713003", procedure_type: str = "appendectomy") -> Any:
    return SimpleNamespace(
        procedure_type=procedure_type,
        category_code=category_code,
        start_datetime=datetime(2026, 7, 2, 9, 0),
    )


def _make_ctx(
    encounter: Any = None,
    diagnoses: list[Any] | None = None,
    lab_results: list[Any] | None = None,
    procedures: list[Any] | None = None,
    los_days: int = 7,
    target_lang: str = "ja",
    locale: str = "jp",
) -> NarrativeContext:
    return NarrativeContext(
        patient=PatientProfile(patient_id="pt-acp-test"),
        encounter=encounter or _make_encounter(),
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=los_days,
        vitals=[],
        lab_results=lab_results or [],
        medications=[],
        diagnoses=diagnoses or [],
        procedures=procedures or [],
        allergies=[],
        document_type=DocumentType.ADMISSION_CARE_PLAN,
        target_lang=target_lang,
        locale=locale,
    )


def test_admission_care_plan_returns_all_10_sections_non_empty() -> None:
    spec = _make_spec()
    ctx = _make_ctx(diagnoses=[_make_diagnosis()])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert isinstance(out.sections, dict)
    for section in _ACP_SECTIONS:
        assert section in out.sections, f"section {section!r} missing"
        assert out.sections[section].strip() != "", f"section {section!r} is empty"


def test_admission_care_plan_jp_has_japanese_text() -> None:
    spec = _make_spec()
    ctx = _make_ctx(diagnoses=[_make_diagnosis()], target_lang="ja", locale="jp")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    all_text = " ".join(out.sections.values())
    has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in all_text)
    assert has_jp, f"admission_care_plan sections contain no Japanese text: {all_text[:300]!r}"


def test_admission_care_plan_en_no_crash() -> None:
    """JP-only doc type is never rendered in en in production, but the
    builder pattern in this file always supports both languages defensively."""
    spec = _make_spec()
    ctx = _make_ctx(diagnoses=[_make_diagnosis()], target_lang="en", locale="us")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    for section in _ACP_SECTIONS:
        assert out.sections[section].strip() != ""


def test_ward_and_room_includes_ward_and_bed() -> None:
    spec = _make_spec()
    enc = _make_encounter(ward_id="4W", bed_number="401-2")
    ctx = _make_ctx(encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "4W" in out.sections["ward_and_room"]
    assert "401-2" in out.sections["ward_and_room"]


def test_other_staff_includes_primary_nurse_when_set() -> None:
    spec = _make_spec()
    enc = _make_encounter(primary_nurse_id="nurse-RN-001")
    ctx = _make_ctx(encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "nurse-RN-001" in out.sections["other_staff"]


def test_other_staff_fallback_when_no_nurse() -> None:
    spec = _make_spec()
    enc = _make_encounter(primary_nurse_id="")
    ctx = _make_ctx(encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.sections["other_staff"].strip() != ""


def test_diagnosis_resolves_admission_code_via_code_lookup() -> None:
    spec = _make_spec()
    ctx = _make_ctx(diagnoses=[_make_diagnosis(admission_diagnosis_code="J18.9")])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "J18.9" in out.sections["diagnosis"]


def test_diagnosis_falls_back_to_chief_complaint_when_no_diagnoses() -> None:
    spec = _make_spec()
    ctx = _make_ctx(diagnoses=[])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.sections["diagnosis"].strip() != ""


def test_surgery_schedule_lists_surgical_procedure() -> None:
    spec = _make_spec()
    ctx = _make_ctx(procedures=[_make_procedure(category_code="387713003", procedure_type="appendectomy")])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "appendectomy" in out.sections["surgery_schedule"]


def test_surgery_schedule_excludes_non_surgical_procedure() -> None:
    spec = _make_spec()
    ctx = _make_ctx(procedures=[_make_procedure(category_code="103693007", procedure_type="ct_scan")])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "ct_scan" not in out.sections["surgery_schedule"]


def test_surgery_schedule_none_planned_when_no_procedures() -> None:
    spec = _make_spec()
    ctx = _make_ctx(procedures=[])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.sections["surgery_schedule"].strip() != ""


def test_estimated_los_uses_ctx_los_days() -> None:
    spec = _make_spec()
    ctx = _make_ctx(los_days=12)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "12" in out.sections["estimated_los"]


def test_special_nutrition_management_is_always_no() -> None:
    """MVP decision (spec §3b): hardcoded 無 pending a future nutrition subsystem."""
    spec = _make_spec()
    ctx = _make_ctx()
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "無" in out.sections["special_nutrition_management"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/modules/document/narrative/test_template_generator_admission_care_plan.py -v`
Expected: FAIL — `_render_composition_sections` hits the `else` branch (`section_builders.get(section)` returns `None`) for every `admission_care_plan` section, so sections render as the generic fallback phrase, not the section-specific content the tests assert on ("4W"/"401-2"/"nurse-RN-001"/"J18.9"/"appendectomy"/"12"/"無" absent from generic fallback text).

- [ ] **Step 3: Add fallback constants**

Edit `clinosim/modules/document/narrative/template_generator.py`, after the existing `_ADL_FALLBACK_EN` constant (near line 243):

```python
_ACP_WARD_ROOM_FALLBACK_JA = "病棟・病室：未定"
_ACP_WARD_ROOM_FALLBACK_EN = "Ward/Room: not yet assigned"
_ACP_OTHER_STAFF_FALLBACK_JA = "担当なし"
_ACP_OTHER_STAFF_FALLBACK_EN = "No additional staff assigned"
_ACP_TEST_SCHEDULE_FALLBACK_JA = "検査：担当医の判断により決定"
_ACP_TEST_SCHEDULE_FALLBACK_EN = "Tests: to be determined by the attending physician"
_ACP_SURGERY_NONE_JA = "手術：予定なし"
_ACP_SURGERY_NONE_EN = "Surgery: none planned"
_ACP_NUTRITION_NO_JA = "特別な栄養管理の必要性：無"
_ACP_NUTRITION_NO_EN = "Special nutritional management required: No"
_ACP_OTHER_PLANS_JA = "その他：看護計画・リハビリテーション等の計画については看護記録を参照。"
_ACP_OTHER_PLANS_EN = "Other: see nursing documentation for the nursing care plan and rehabilitation plan."
```

- [ ] **Step 4: Register the 10 builders in `section_builders`**

Edit `clinosim/modules/document/narrative/template_generator.py`, in `_render_composition_sections`, add after the `"disposition": self._build_ed_disposition,` line:

```python
            # chain 2: ADMISSION_CARE_PLAN sections (LOINC 18776-5)
            "ward_and_room": self._build_acp_ward_and_room,
            "other_staff": self._build_acp_other_staff,
            "diagnosis": self._build_acp_diagnosis,
            "symptoms": self._build_acp_symptoms,
            "treatment_plan": self._build_acp_treatment_plan,
            "test_schedule": self._build_acp_test_schedule,
            "surgery_schedule": self._build_acp_surgery_schedule,
            "estimated_los": self._build_acp_estimated_los,
            "special_nutrition_management": self._build_acp_special_nutrition_management,
            "other_plans": self._build_acp_other_plans,
```

- [ ] **Step 5: Implement the 10 builder methods**

Add after `_build_care_plan` (the last α-min-2 ADMISSION_NURSING_ASSESSMENT builder, near line 1177), before the `NURSING_DISCHARGE_SUMMARY` section comment:

```python
    # ─────────────────────────────────────────────────────────────────
    # chain 2: ADMISSION_CARE_PLAN section builders (入院診療計画書, LOINC 18776-5)
    #
    # MHLW form 別紙２ (10 core fields, verified 2026-07-03 — design spec §2).
    # JP-only doc type (countries_supported=[jp]); both language branches are
    # implemented for consistency with every other builder in this file, even
    # though only target_lang="ja" is ever reached through the registry gate.
    # ─────────────────────────────────────────────────────────────────

    def _build_acp_ward_and_room(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """病棟（病室）— Encounter.ward_id + bed_number."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        ward = str(_o(ctx.encounter, "ward_id", "") or "")
        bed = str(_o(ctx.encounter, "bed_number", "") or "")
        if not ward and not bed:
            return (_ACP_WARD_ROOM_FALLBACK_JA if is_ja else _ACP_WARD_ROOM_FALLBACK_EN), facts
        if ward:
            facts.append("encounter.ward_id")
        if bed:
            facts.append("encounter.bed_number")
        if is_ja:
            return f"病棟：{ward or '未定'}　病室：{bed or '未定'}", facts
        return f"Ward: {ward or 'TBD'}, Room: {bed or 'TBD'}", facts

    def _build_acp_other_staff(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """主治医以外の担当者名 — Encounter.primary_nurse_id (same field AD-64 CareTeam uses)."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        nurse_id = str(_o(ctx.encounter, "primary_nurse_id", "") or "")
        if not nurse_id:
            return (_ACP_OTHER_STAFF_FALLBACK_JA if is_ja else _ACP_OTHER_STAFF_FALLBACK_EN), facts
        facts.append("encounter.primary_nurse_id")
        return (f"担当看護師：{nurse_id}" if is_ja else f"Assigned nurse: {nurse_id}"), facts

    def _build_acp_diagnosis(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """病名（他に考え得る病名）— ctx.diagnoses, admission code preferred
        (discharge dx is not yet known when this document is written at
        admission — unlike _build_discharge_diagnoses which prefers discharge)."""
        from clinosim.codes import lookup as code_lookup

        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        diagnoses = ctx.diagnoses or []
        if not diagnoses:
            return self._build_chief_complaint(ctx)

        facts.append("ctx.diagnoses")
        parts: list[str] = []
        for dx in diagnoses:
            code = str(_o(dx, "admission_diagnosis_code", "") or _o(dx, "discharge_diagnosis_code", "") or "")
            if not code:
                continue
            system = str(
                _o(dx, "admission_diagnosis_system", "")
                or _o(dx, "discharge_diagnosis_system", "")
                or ("icd-10" if is_ja else "icd-10-cm")
            )
            display = code_lookup(system, code, ctx.target_lang)
            if display and display != code:
                parts.append(f"{display}（{code}）" if is_ja else f"{display} ({code})")
            else:
                parts.append(code)

        if parts:
            return "; ".join(parts), facts
        return self._build_chief_complaint(ctx)

    def _build_acp_symptoms(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """症状 — reuses chief_complaint extraction (presenting symptom)."""
        return self._build_chief_complaint(ctx)

    def _build_acp_treatment_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """治療計画 — reuses assessment_and_plan extraction (admission_hp precedent)."""
        return self._build_assessment_and_plan(ctx)

    def _build_acp_test_schedule(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """検査内容及び日程 — distinct test names from ctx.lab_results.

        ctx has no separate "orders" field (only already-resulted lab_results);
        distinct test names is the best available data-driven proxy within
        NarrativeContext's existing schema (spec §3b decision)."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        names: set[str] = set()
        for lab in ctx.lab_results or []:
            name = _o(lab, "test_name", None)
            if name:
                names.add(str(name))
        if not names:
            return (_ACP_TEST_SCHEDULE_FALLBACK_JA if is_ja else _ACP_TEST_SCHEDULE_FALLBACK_EN), facts
        facts.append("ctx.lab_results")
        joined = "、".join(sorted(names)) if is_ja else ", ".join(sorted(names))
        return (f"検査項目：{joined} を実施予定" if is_ja else f"Planned tests: {joined}"), facts

    def _build_acp_surgery_schedule(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """手術内容及び日程 — ctx.procedures filtered to category_code=387713003 (surgical)."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        surgical = [p for p in (ctx.procedures or []) if str(_o(p, "category_code", "") or "") == "387713003"]
        if not surgical:
            return (_ACP_SURGERY_NONE_JA if is_ja else _ACP_SURGERY_NONE_EN), facts
        facts.append("ctx.procedures")
        types = [str(_o(p, "procedure_type", "") or "") for p in surgical if _o(p, "procedure_type", "")]
        joined = "、".join(types) if is_ja else ", ".join(types)
        return (f"手術予定：{joined}" if is_ja else f"Planned surgery: {joined}"), facts

    def _build_acp_estimated_los(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """推定される入院期間 — ctx.los_days (the actual computed LOS for this
        admission; simpler and RNG-free vs re-reading disease_protocol.target_los
        distributions — deliberate spec deviation, see plan Global Constraints)."""
        facts = ["ctx.los_days"]
        is_ja = ctx.target_lang == "ja"
        los = ctx.los_days or 1
        return (f"推定入院期間：約{los}日間" if is_ja else f"Estimated length of stay: approximately {los} days"), facts

    def _build_acp_special_nutrition_management(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """特別な栄養管理の必要性 — MVP: always「無」(no NutritionOrder subsystem
        exists yet; TODO.md tracks the future nutrition subsystem chain)."""
        is_ja = ctx.target_lang == "ja"
        return (_ACP_NUTRITION_NO_JA if is_ja else _ACP_NUTRITION_NO_EN), []

    def _build_acp_other_plans(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """その他（看護計画・リハビリテーション等の計画）— fixed cross-reference
        phrase. NarrativeContext does not carry other stub types' rendered
        content at this call site (each spec walked independently), so this
        section cannot dynamically pull admission_nursing_assessment content
        without a larger architecture change (out of scope, see plan)."""
        is_ja = ctx.target_lang == "ja"
        return (_ACP_OTHER_PLANS_JA if is_ja else _ACP_OTHER_PLANS_EN), []
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/modules/document/narrative/test_template_generator_admission_care_plan.py -v`
Expected: PASS (all 13 tests).

- [ ] **Step 7: Run the full α-min-2 template generator suite to check no regression**

Run: `pytest tests/unit/modules/document/narrative/test_template_generator_alpha2.py -v`
Expected: PASS (unchanged — new dict entries are additive, no existing keys touched).

- [ ] **Step 8: Commit**

```bash
git add clinosim/modules/document/narrative/template_generator.py tests/unit/modules/document/narrative/test_template_generator_admission_care_plan.py
git commit -m "feat(chain2): TemplateNarrativeGenerator section builders for admission_care_plan"
```

---

### Task 4: `document_enricher` dispatch verification (Stage 1 stub)

**Files:**
- Test only: Create `tests/unit/modules/document/test_engine_admission_care_plan.py` (no production code changes — this task proves the existing generic dispatch in `clinosim/modules/document/engine.py` correctly picks up the new spec).

**Interfaces:**
- Consumes: `clinosim.modules.document.engine.document_enricher(ctx)` (existing function, `EnricherContext`-shaped `ctx` with `.master_seed`, `.records`, `.config.country`).
- Produces: proof that a JP inpatient/icu encounter gets exactly 1 `admission_care_plan` `ClinicalDocument` stub at `period_start == admission_datetime`, and that JP `rehab_inpatient`/`outpatient`/`emergency` and US `inpatient` encounters get 0.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/modules/document/test_engine_admission_care_plan.py`:

```python
"""document_enricher dispatch tests for admission_care_plan (chain 2).

No production code change expected — proves the existing generic
specs_for_country / specs_for_encounter_type / admission_once dispatch in
document_enricher already handles the new JP-only spec correctly (design
spec §3a claim).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.engine import document_enricher


def _make_record(encounter_type: str, country_encounter_status: str = "completed") -> dict[str, Any]:
    return {
        "patient": {"patient_id": "pt-acp-engine-test"},
        "encounters": [
            {
                "encounter_id": "enc-acp-engine-test",
                "encounter_type": encounter_type,
                "status": country_encounter_status,
                "admission_datetime": datetime(2026, 7, 1, 10, 0),
                "discharge_datetime": datetime(2026, 7, 5, 10, 0),
                "attending_physician_id": "dr-acp-engine-test",
                "primary_nurse_id": "ns-acp-engine-test",
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


def _acp_docs(record: dict[str, Any]) -> list[Any]:
    return [d for d in record["documents"] if getattr(d, "task_type", "") == "admission_care_plan"]


def test_jp_inpatient_gets_one_admission_care_plan_stub() -> None:
    record = _run_enricher(_make_record("inpatient"), "jp")
    docs = _acp_docs(record)
    assert len(docs) == 1
    assert docs[0].loinc_code == "18776-5"
    assert docs[0].period_start == datetime(2026, 7, 1, 10, 0).isoformat()


def test_jp_icu_gets_one_admission_care_plan_stub() -> None:
    record = _run_enricher(_make_record("icu"), "jp")
    assert len(_acp_docs(record)) == 1


def test_jp_rehab_inpatient_gets_zero_admission_care_plan_stubs() -> None:
    record = _run_enricher(_make_record("rehab_inpatient"), "jp")
    assert len(_acp_docs(record)) == 0


def test_jp_outpatient_gets_zero_admission_care_plan_stubs() -> None:
    record = _run_enricher(_make_record("outpatient"), "jp")
    assert len(_acp_docs(record)) == 0


def test_jp_emergency_gets_zero_admission_care_plan_stubs() -> None:
    record = _run_enricher(_make_record("emergency"), "jp")
    assert len(_acp_docs(record)) == 0


def test_us_inpatient_gets_zero_admission_care_plan_stubs() -> None:
    record = _run_enricher(_make_record("inpatient"), "us")
    assert len(_acp_docs(record)) == 0
```

- [ ] **Step 2: Run test to confirm current behavior**

Run: `pytest tests/unit/modules/document/test_engine_admission_care_plan.py -v`
Expected: at this point Tasks 1-3 are already complete (this task runs after them), so this should **PASS immediately** — it is a verification/regression test for existing generic dispatch, not new production code. If any test fails, that indicates the generic dispatch does NOT handle the new spec as claimed in the design spec — stop and investigate `clinosim/modules/document/engine.py`'s `specs_for_encounter_type` / `country_spec_keys` intersection logic before proceeding (do not add a special-case branch; find why the generic path didn't pick it up).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/modules/document/test_engine_admission_care_plan.py
git commit -m "test(chain2): verify document_enricher generic dispatch handles admission_care_plan"
```

---

### Task 5: Audit `lift_firing_proof` extension (silent-no-op defense)

**Files:**
- Modify: `clinosim/modules/document/audit.py`
- Test: `tests/unit/test_document_audit_alpha2.py` (or sibling file — extend in place)

**Interfaces:**
- Consumes: `document_enricher` (Task 4 confirms behavior).
- Produces: 3 new `equality_checks` tuples in `_build_document_proof()`'s return value, consumed automatically by the existing `test_all_proof_checks_pass` test (iterates all `equality_checks` and asserts `actual == expected`).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_document_audit_alpha2.py`:

```python
def test_lift_firing_proof_includes_admission_care_plan_checks():
    """chain 2: admission_care_plan dispatch proof (JP-only, inpatient/icu gate)."""
    proof = _get_proof()
    labels = {c[0]: c for c in proof["equality_checks"]}
    assert "admission_care_plan_jp_inpatient_count" in labels
    assert "admission_care_plan_us_inpatient_count" in labels
    assert "admission_care_plan_jp_rehab_inpatient_count" in labels
    for label in (
        "admission_care_plan_jp_inpatient_count",
        "admission_care_plan_us_inpatient_count",
        "admission_care_plan_jp_rehab_inpatient_count",
    ):
        _, actual, expected = labels[label]
        assert actual == expected, f"{label}: {actual!r} != {expected!r}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_document_audit_alpha2.py::test_lift_firing_proof_includes_admission_care_plan_checks -v`
Expected: FAIL — `AssertionError: 'admission_care_plan_jp_inpatient_count' not in labels` (checks don't exist yet).

- [ ] **Step 3: Add the proof helper function**

Edit `clinosim/modules/document/audit.py`, add after `_proof_nursing_shift_3_per_day` (before `_build_document_proof`):

```python
def _proof_admission_care_plan() -> dict[str, Any]:
    """chain 2: prove the admission_care_plan JP-only / inpatient+icu gate fires.

    Three synthetic encounters (JP inpatient, US inpatient, JP rehab_inpatient)
    run through document_enricher; a regression that widens countries_supported
    or encounter_types_supported would silently leak this legally-scoped
    document into the wrong cohort (PR-90 class — same pattern as the α-min-1
    Task 10 encounter_types_supported fix).
    """
    from datetime import datetime
    from types import SimpleNamespace

    from clinosim.modules.document.engine import document_enricher

    def _run(encounter_type: str, country: str) -> int:
        record: dict[str, Any] = {
            "patient": {"patient_id": f"pt-acp-proof-{encounter_type}-{country}"},
            "encounters": [
                {
                    "encounter_id": f"enc-acp-proof-{encounter_type}-{country}",
                    "encounter_type": encounter_type,
                    "status": "completed",
                    "admission_datetime": datetime(2026, 7, 1, 10, 0),
                    "discharge_datetime": datetime(2026, 7, 5, 10, 0),
                    "attending_physician_id": "dr-acp-proof",
                    "primary_nurse_id": "ns-acp-proof",
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
            d for d in record["documents"] if getattr(d, "task_type", "") == "admission_care_plan"
        ])

    return {
        "jp_inpatient_count": _run("inpatient", "jp"),
        "us_inpatient_count": _run("inpatient", "us"),
        "jp_rehab_inpatient_count": _run("rehab_inpatient", "jp"),
    }
```

- [ ] **Step 4: Wire the proof into `_build_document_proof`**

Edit `clinosim/modules/document/audit.py`. Near the `_shift_proof = _proof_nursing_shift_3_per_day()` line, add:

```python
    # chain 2: admission_care_plan JP-only / inpatient+icu gate proof.
    _acp_proof = _proof_admission_care_plan()
```

Then, in the `equality_checks` list, immediately before the closing `]` (after the `nursing_shift_note_shift_hour_offsets` tuple), add:

```python
            # === chain 2: admission_care_plan gate proof (+3, total = 40) ===
            (
                "admission_care_plan_jp_inpatient_count",
                _acp_proof["jp_inpatient_count"],
                1,
            ),
            (
                "admission_care_plan_us_inpatient_count",
                _acp_proof["us_inpatient_count"],
                0,
            ),
            (
                "admission_care_plan_jp_rehab_inpatient_count",
                _acp_proof["jp_rehab_inpatient_count"],
                0,
            ),
```

- [ ] **Step 5: Update the module docstring check count**

Edit `clinosim/modules/document/audit.py` docstring near the top (`37 equality_checks in lift_firing_proof ...`) — change `37` to `40` and append a changelog line after the α-min-3 entry:

```
  chain 2 admission_care_plan gate (+3, total = 40):
    `admission_care_plan_jp_inpatient_count` / `admission_care_plan_us_inpatient_count` /
    `admission_care_plan_jp_rehab_inpatient_count` — proves the JP-only +
    inpatient/icu-only gate fires (not silently emitting for US or rehab_inpatient).
    See `_proof_admission_care_plan`.
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_document_audit_alpha2.py -v`
Expected: PASS (all tests, including `test_all_proof_checks_pass` and the new `test_lift_firing_proof_includes_admission_care_plan_checks`).

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/document/audit.py tests/unit/test_document_audit_alpha2.py
git commit -m "feat(chain2): lift_firing_proof gate check for admission_care_plan (+3, total=40)"
```

---

### Task 6: Full-chain integration test (Stage 1 → Stage 2 → FHIR)

**Files:**
- Create: `tests/integration/test_admission_care_plan_chain.py`

**Interfaces:**
- Consumes: `document_enricher` (Task 4), `TemplateNarrativePass` (`clinosim.modules.document.narrative.passes`), `_bb_compositions` (`clinosim.modules.output._fhir_composition`) — all pre-existing, no new interfaces produced by this task.

- [ ] **Step 1: Write the integration test**

First inspect an existing integration test for the exact `TemplateNarrativePass` + structural-CIF-on-disk invocation pattern:

Run: `sed -n '1,60p' tests/integration/test_bug_b_nurse_author.py`

Then create `tests/integration/test_admission_care_plan_chain.py` following that pattern (adapt the exact structural CIF write/read helper names found above — the skeleton below uses the documented `TemplateNarrativePass(cif_dir, version_id, country).run()` contract from `passes.py`):

```python
"""Full chain integration test: document_enricher → TemplateNarrativePass →
FHIR Composition, for admission_care_plan (chain 2).

Verifies: Composition emitted with LOINC 18776-5, exactly 10 sections, 100%
Japanese text (jp_language axis), and correctly ABSENT for out-of-scope
cohorts (US, outpatient, emergency, rehab_inpatient) — the silent-no-op
negative check the design spec §5 requires.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime

import pytest

from types import SimpleNamespace

from clinosim.modules.document.engine import document_enricher
from clinosim.modules.document.narrative.passes import TemplateNarrativePass
from clinosim.modules.output._fhir_composition import _bb_compositions


def _make_bundle_ctx(record: dict, country: str = "jp") -> SimpleNamespace:
    """Minimal BundleContext-shaped namespace (mirrors
    tests/unit/output/test_fhir_composition_alpha2.py's _make_ctx — only the
    fields _bb_compositions actually reads are populated)."""
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


def _write_structural_cif(cif_dir: str, patient_dict: dict) -> None:
    structural_dir = os.path.join(cif_dir, "structural", "patients")
    os.makedirs(structural_dir, exist_ok=True)
    with open(os.path.join(structural_dir, f"{patient_dict['patient']['patient_id']}.json"), "w") as f:
        json.dump(patient_dict, f, default=str)


def _jp_inpatient_patient_dict(patient_id: str, encounter_type: str = "inpatient") -> dict:
    from types import SimpleNamespace

    record: dict = {
        "patient": {"patient_id": patient_id, "age": 68, "sex": "M"},
        "encounters": [
            {
                "encounter_id": f"enc-{patient_id}",
                "encounter_type": encounter_type,
                "status": "completed",
                "admission_datetime": datetime(2026, 7, 1, 10, 0),
                "discharge_datetime": datetime(2026, 7, 6, 10, 0),
                "attending_physician_id": "dr-chain-test",
                "primary_nurse_id": "ns-chain-test",
                "ward_id": "4W",
                "bed_number": "401-2",
                "severity": "moderate",
                "clinical_course_archetype": "uncomplicated_improvement",
            }
        ],
        "documents": [],
        "extensions": {},
        "physiological_states": [],
        "condition_event": {},
        "clinical_diagnosis": {
            "admission_diagnosis_code": "J18.9",
            "admission_diagnosis_system": "icd-10",
        },
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


def test_jp_inpatient_produces_admission_care_plan_composition() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        patient_dict = _jp_inpatient_patient_dict("pt-chain-jp-inpatient")
        _write_structural_cif(tmp, patient_dict)

        manifest = TemplateNarrativePass(tmp, version_id="v1", country="jp").run()
        assert manifest.document_counts_by_type.get("admission_care_plan") == 1

        narrative_dir = os.path.join(tmp, "narratives", "v1", "documents", "enc-pt-chain-jp-inpatient")
        files = [f for f in os.listdir(narrative_dir) if "admission_care_plan" not in f] if os.path.isdir(narrative_dir) else []
        acp_files = [
            f for f in os.listdir(narrative_dir)
            for stub in patient_dict["documents"]
            if stub["task_type"] == "admission_care_plan" and f == f"{stub['document_id']}.json"
        ]
        assert len(acp_files) == 1
        with open(os.path.join(narrative_dir, acp_files[0])) as f:
            doc_payload = json.load(f)

        doc_record = next(d for d in patient_dict["documents"] if d["task_type"] == "admission_care_plan")
        doc_record["narrative"] = doc_payload["narrative"]
        patient_dict["extensions"] = {}
        bundle_ctx = _make_bundle_ctx(patient_dict, country="jp")
        comp_out = _bb_compositions(bundle_ctx)
        assert len(comp_out) == 1
        comp = comp_out[0]
        assert comp["type"]["coding"][0]["code"] == "18776-5"
        assert comp["type"]["coding"][0]["display"] == "入院診療計画書"
        assert len(comp["section"]) == 10

        all_text = " ".join(s["title"] + s["text"]["div"] for s in comp["section"])
        has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in all_text)
        assert has_jp


@pytest.mark.parametrize("encounter_type,country", [
    ("inpatient", "us"),
    ("outpatient", "jp"),
    ("emergency", "jp"),
    ("rehab_inpatient", "jp"),
])
def test_out_of_scope_cohorts_produce_no_admission_care_plan(encounter_type: str, country: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        from types import SimpleNamespace

        record: dict = {
            "patient": {"patient_id": f"pt-chain-{encounter_type}-{country}", "age": 50, "sex": "F"},
            "encounters": [
                {
                    "encounter_id": f"enc-{encounter_type}-{country}",
                    "encounter_type": encounter_type,
                    "status": "completed",
                    "admission_datetime": datetime(2026, 7, 1, 10, 0),
                    "discharge_datetime": datetime(2026, 7, 3, 10, 0),
                    "attending_physician_id": "dr-chain-test",
                }
            ],
            "documents": [],
            "extensions": {},
            "physiological_states": [],
        }
        ctx = SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace(country=country))
        document_enricher(ctx)
        acp_docs = [d for d in record["documents"] if d.task_type == "admission_care_plan"]
        assert len(acp_docs) == 0
```

- [ ] **Step 2: Run test, fix any structural-CIF-shape mismatches**

Run: `pytest tests/integration/test_admission_care_plan_chain.py -v`

Expected: this may initially fail on structural details (exact `TemplateNarrativePass`/`_bb_compositions` call signature, or CIF dict shape) since the skeleton above was written from source reading, not execution. If it fails on a shape mismatch (not a logic bug from Tasks 1-5), fix the test's fixture shape to match — do NOT modify production code to accommodate the test. Re-run until PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_admission_care_plan_chain.py
git commit -m "test(chain2): full-chain integration test for admission_care_plan (Stage1→Stage2→FHIR)"
```

---

### Task 7: Golden regen, TODO.md nutrition-flag entry, full suite, PR

**Files:**
- Modify: `TODO.md` (add the nutrition-flag MVP entry + mark 入院診療計画書 line as done in the β-JP-1 厚労省必須文書 list)
- Regenerate: `tests/fixtures/patient_profiles/jp_inpatient_bacterial_pneumonia.golden.json`, `jp_icu_sepsis_hai_clabsi.golden.json`, `jp_inpatient_copd_exacerbation.golden.json` (and their `.llm-mock.golden.json` siblings if present)

- [ ] **Step 1: Regenerate the 3 JP profile goldens**

Run:
```bash
clinosim regenerate-goldens --profile jp_inpatient_bacterial_pneumonia
clinosim regenerate-goldens --profile jp_icu_sepsis_hai_clabsi
clinosim regenerate-goldens --profile jp_inpatient_copd_exacerbation
```

- [ ] **Step 1b (discovered during execution): also regenerate the `.llm-mock` golden legs**

`pytest -m regression` failed after Step 1 with 3 `test_profile_narrative_llm_mock_byte_diff`
failures — the regression suite has a template leg AND an llm-mock leg per profile
(`<profile>.llm-mock.golden.json`), and `--provider mock` must be regenerated separately
(the plain `regenerate-goldens --profile X` only refreshes the template golden). Run:
```bash
clinosim regenerate-goldens --profile jp_inpatient_bacterial_pneumonia --provider mock
clinosim regenerate-goldens --profile jp_icu_sepsis_hai_clabsi --provider mock
clinosim regenerate-goldens --profile jp_inpatient_copd_exacerbation --provider mock
```

- [ ] **Step 2: Categorize the golden diff (AD-66 Rule 2)**

Run: `git diff --stat tests/fixtures/patient_profiles/*.golden.json`
Expected: new `admission_care_plan` document entries appear in the JSON (new Composition-shaped document per profile); no other document type's content should change. Read the diff (`git diff tests/fixtures/patient_profiles/jp_inpatient_bacterial_pneumonia.golden.json`) and confirm every changed line is additive (a new document block) — if any pre-existing document's content changed, STOP and investigate before proceeding (AD-66 Rule 2: unexpected diff on unrelated goldens = regression suspicion).

- [ ] **Step 3: Add the TODO.md nutrition-flag MVP entry**

Edit `TODO.md`. Find the "β-JP-1 phase — JP localization + 厚労省必須文書" section (currently lists 4 documents including 入院診療計画書) and replace the 入院診療計画書 bullet:

```markdown
- ~~**入院診療計画書** (Admission care plan document)~~ — **DONE (chain 2, 2026-07-03)**:
  LOINC 18776-5, Composition, 10 sections per MHLW 別紙２, JP-only,
  inpatient/icu only (rehab_inpatient uses the 別紙２の２ variant, out of
  scope). `special_nutrition_management` is hardcoded "無" pending a future
  nutrition subsystem chain (see below) — no NutritionOrder/nutritionist
  data source exists yet to derive a real value.
```

Then add a new formal TODO entry (near the existing 栄養管理計画書 bullet, or as a new small section):

```markdown
### chain 2 deferred: admission_care_plan real nutrition-need derivation

`_build_acp_special_nutrition_management` (`template_generator.py`) always
renders "無" (no special nutritional management needed) — an MVP
simplification, not a real clinical derivation. When the 栄養管理計画書
(nutrition care plan) subsystem chain lands (NutritionOrder + nutritionist
staff role), revisit this section to derive a real yes/no signal (e.g. from
BMI, albumin lab values, or disease-specific nutrition risk flags) instead
of the hardcoded default.
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest -x -q`
Expected: all tests pass (unit + integration + e2e). This is the final gate before PR per this project's workflow (CLAUDE.md "Always run unit tests before committing").

- [ ] **Step 5: Run the JP-cohort audit**

Run: `clinosim generate --population 200 --country jp --seed 42 --output /tmp/acp_audit_jp && clinosim narrate --cif-dir /tmp/acp_audit_jp --provider template --country jp && clinosim export-fhir --cif-dir /tmp/acp_audit_jp --narrative-version template && clinosim audit run -d /tmp/acp_audit_jp`
Expected: 4-axis audit PASS, including the `silent_no_op` axis (which now includes the 3 new `admission_care_plan_*` equality_checks from Task 5).

- [ ] **Step 6: Commit the golden regen + TODO.md update**

```bash
git add tests/fixtures/patient_profiles/*.golden.json TODO.md
git commit -m "$(cat <<'EOF'
feat(chain2): regenerate JP profile goldens + TODO.md nutrition-flag MVP entry

3 JP inpatient/icu canonical profiles now include the admission_care_plan
document (LOINC 18776-5). AD-66 Rule 2 diff categorized: additive only, no
pre-existing document content changed.
EOF
)"
```

- [ ] **Step 7: Push and open the PR**

```bash
git push -u origin feature/chain2-admission-care-plan
gh pr create --title "feat(chain2): admission care plan document (入院診療計画書, LOINC 18776-5)" --body "$(cat <<'EOF'
## Summary
- First chain-2 (厚労省4帳票) sub-project: adds `admission_care_plan` as the
  10th `DocumentType`, reusing the existing NarrativePass/DocumentTypeSpec/
  Composition machinery with zero FHIR builder changes.
- Verified against MHLW form 別紙２ (fetched + pdftotext-extracted) and
  LOINC 18776-5 (web search) — 10 core sections, JP-only, inpatient/icu only.
- `special_nutrition_management` is a deliberate MVP simplification (hardcoded
  "無"), tracked as a formal TODO.md entry pending the nutrition subsystem chain.

## Test plan
- [x] `pytest -x -q` full suite green
- [x] `clinosim audit run` 4-axis PASS on a JP cohort (silent_no_op axis
      includes 3 new admission_care_plan gate checks)
- [x] 3 JP inpatient/icu profile goldens regenerated, diff categorized
      additive-only per AD-66 Rule 2
- [x] Integration test proves Composition emission (10 sections, LOINC
      18776-5, 100% Japanese text) and correct absence for US/outpatient/
      emergency/rehab_inpatient cohorts

Spec: docs/superpowers/specs/2026-07-03-admission-care-plan-design.md
Plan: docs/superpowers/plans/2026-07-03-admission-care-plan.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Notes (completed during plan authoring)

- **Spec coverage**: §3a (registry) → Task 1+2. §3b (fact sourcing) → Task 3 (folded directly into builders; `section_extractor.py`/`fact_extractor.py` changes from the original spec text turned out to be unnecessary — every existing section builder in this file sources facts inline via `_o()`, not through the generic extractor, so I followed that established pattern instead. Noted as a plan-level simplification, not a scope cut — this is a strictly less-code path). §3c (template rendering) → Task 3. §3d (FHIR, no changes) → verified in Task 6 by construction (no `_fhir_composition.py` edits anywhere in this plan). §4 (out of scope) → respected throughout (no nutrition/rehab/DPC-form work; rehab_inpatient explicitly excluded and tested in Tasks 2/4/5/6). §5 (testing) → Tasks 1-6 cover unit/integration/audit; Task 7 covers goldens. §6 (verification gate) → Task 7 Steps 4-5.
- **Two documented deviations** from the spec's literal data-source suggestions (`estimated_los` uses `ctx.los_days` not raw `target_los`; `other_plans` is a fixed cross-reference phrase, not dynamically pulled `admission_nursing_assessment` content) are called out in Global Constraints with rationale — both are simplifications discovered while reading the actual `NarrativeContext`/`NarrativePass` code, not scope creep.
- **Placeholder scan**: no TBD/TODO-without-content; the one intentional "hardcoded MVP value" (`special_nutrition_management`) is a real, working implementation (not a stub) with its limitation documented as a formal TODO.md entry per Task 7 Step 3.
- **Type consistency**: all builder methods return `tuple[str, list[str]]` matching every existing `_build_*` method in `template_generator.py`; `_o()` import alias, `code_lookup` lazy-import pattern, and fallback-constant naming (`_ACP_*_JA`/`_ACP_*_EN`) all match established file conventions verified by direct source reading before this plan was written.
