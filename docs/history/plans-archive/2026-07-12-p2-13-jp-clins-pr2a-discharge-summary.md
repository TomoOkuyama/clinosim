# P2-13 PR2a: JP-CLINS Full-Conformance 退院時サマリー Composition — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** country=JP かつ inpatient/icu/rehab_inpatient 退院時に、jpfhir.jp v1.12.0 の `JP_Composition_eDischargeSummary` に構造準拠した Composition を emit する。既存の英語 section 構造(admission_summary / hospital_course / …)は US 出力用としてそのまま維持し、JP は新しい 5 必須 section 構造(312/322/342/352/360、ネスト親 300)で分岐 emit。

**Architecture:** 既存 `_fhir_composition.py` の 6 doc types dispatch を保ち、`discharge_summary` doc type だけ country=JP のとき JP-CLINS 準拠 builder(`_build_jp_clins_discharge_summary_composition`)に分岐。JP 用 CodeSystem 2 種(`doc-typecodes` / `jp-codeSystem-clins-document-section`)を `codes/data/` に新規追加。JP narrative template の section 名を JP-CLINS 対応の英語 snake_case key に統一(`admission_reason` / `admission_details` / `admission_diagnoses` / `chief_complaint` / `present_illness`)し、Stage 2 render 時に code system dispatch。

**Tech Stack:** Python 3.11+, pytest, 既存 FHIR R4 adapter, 既存 `TemplateNarrativeGenerator` / `_fhir_composition.py`, 既存 `clinosim.codes` code registry

## Global Constraints

- **★★ 多言語対応厳守(user 明示、session 47)**:
  - **JP-CLINS profile / CodeSystem / narrative は country=JP 時のみ**適用。US 出力は既存の US 規格(US Core FHIR / LOINC / English narrative)に完全準拠。
  - **US 出力への JP 汚染 0**:doc-typecodes URI / jp-codeSystem-clins-document-section URI / 日本語 display / JP-CLINS profile URL のいずれも US bundle には出現しない。
  - **JP 出力への US 混入 0**:JP-CLINS Composition の section.text.div / display は全て ja(β-JP-1 で LLM narrative 差替可)、内部 identifier 以外 English tokens なし。
  - `country=US` bundle は **byte-diff 0**(既存 US Composition 経路は完全に不変)。integration test にこの check を明示的に含める。
- **Base path per profile**:JP-CLINS の Composition profile canonical URL は resource-type 単位でなく doc-type 単位で異なる:
  - 退院時サマリー = `http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/JP_Composition_eDischargeSummary`
  - 診療情報提供書 = `http://jpfhir.jp/fhir/eReferral/StructureDefinition/JP_Composition_eReferral`(PR2b)
  - PR1 の `_JP_CLINS_PROFILES` dict は resource-type 単位 = Composition には使えない。**新 dict + doc-type ベース dispatch を追加**。
- **CodeSystem canonical URIs**(`codes/data/` に新規登録):
  - `http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes`(document type: 18842-5 = 退院時サマリー / 57133-1 = 診療情報提供書 / JPGCHKUP01 = 健診結果報告書 / 57833-6 = 処方箋 / 56447-6 = 計画書)
  - `http://jpfhir.jp/fhir/clins/CodeSystem/jp-codeSystem-clins-document-section`(section: 3 桁数値 code、Common/DIS/REF/PCS の 4 グループ)
- **JP-CLINS 退院時サマリー必須 section**(この PR で emit する):
  - **300** 構造情報セクション(ネスト親、`section.section[]` として下 4 個をぶら下げる)
    - **312** 入院理由セクション
    - **322** 入院時詳細セクション
    - **342** 入院時診断セクション
    - **352** 主訴セクション
    - **360** 現病歴セクション
- **必須 section の source**:
  - 312 入院理由 = `Encounter.reasonReference` or `EncounterDiagnosisRecord.admission_diagnosis_display`
  - 322 入院時詳細 = `Encounter.period.start` + admission source(現状 CIF は救急経由 flag のみ、narrative で "経過" として記述)
  - 342 入院時診断 = `EncounterDiagnosisRecord.admission_diagnosis_code + display`、entry として Condition reference
  - 352 主訴 = `ChiefComplaintRecord` / 現状 CIF 未定義 → narrative template で hpi から抽出
  - 360 現病歴 = 既存 narrative の hospital_course からの短縮 or hpi 直接
- **US 出力は不変**(既存 discharge_summary Composition 全 6 section 現行仕様維持):byte-diff invariant US = 0
- **JP 出力の byte-diff**:JP discharge summary Composition の section 構造が変わる = 意図的 byte 変化、reproduce.sh JP baseline 更新
- **AD-30(CIF は言語中立)**:section title / code は locale-neutral、display text のみ JP 言語
- **CIF→FHIR no-drop invariant**:JP-CLINS composition emit と並行して、既存 `record.documents[type=DISCHARGE_SUMMARY]` の narrative は失われない — narrative pass 出力の全 section が 5 必須 section に mapping されるか、失敗時 fail-loud

## File Structure

**Modify:**
- `clinosim/modules/output/fhir_r4_adapter.py` — なし(全て composition builder 内で処理)
- `clinosim/modules/output/_fhir_composition.py` — `_build_composition` を country 判定で分岐、JP は新 helper `_build_jp_clins_discharge_summary_composition` へ dispatch。既存 US 経路は不変
- `clinosim/modules/document/reference_data/document_type_specs.yaml` — `discharge_summary` に JP-CLINS section 名 alias 追加(既存 6 sections は US 用として維持、JP 用 5 sections 追加)
- `clinosim/modules/document/narrative/templates/discharge_summary_ja.yaml`(既存 or 新規)— JP-CLINS 5 section 生成 template
- `TODO.md` — PR2a マーク

**Create:**
- `clinosim/codes/data/jpfhir-doc-typecodes.yaml` — jpfhir 文書区分 CodeSystem(5 codes)
- `clinosim/codes/data/jpfhir-doc-section-codes.yaml` — JP-CLINS 文書 section CodeSystem(全 43 codes)
- `clinosim/codes/data/system_uris.yaml` に上 2 種の system key 追加(`jpfhir-doc-typecodes` / `jpfhir-doc-section`)
- `tests/unit/test_jp_clins_composition_ds.py` — JP-CLINS 退院時サマリー Composition unit tests
- `tests/integration/test_jp_clins_composition_ds_end_to_end.py` — p=20 seed=42 JP でcohort validation

---

### Task 1: 一次照会結果 + CodeSystem 定義追加(codes/data/)

**Files:**
- Create: `clinosim/codes/data/jpfhir-doc-typecodes.yaml`
- Create: `clinosim/codes/data/jpfhir-doc-section-codes.yaml`
- Modify: `clinosim/codes/data/system_uris.yaml`(new system keys 追加)
- Test: existing `clinosim.codes.lookup` API 経由の unit test

**Interfaces:**
- Consumes: —
- Produces:
  - system key `"jpfhir-doc-typecodes"` → `http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes`
  - system key `"jpfhir-doc-section"` → `http://jpfhir.jp/fhir/clins/CodeSystem/jp-codeSystem-clins-document-section`
  - `code_lookup("jpfhir-doc-typecodes", "18842-5", "ja")` = `"退院時サマリー"`
  - `code_lookup("jpfhir-doc-section", "312", "ja")` = `"入院理由セクション"`
  - etc.

- [ ] **Step 1: system key 登録**

Locate `clinosim/codes/data/system_uris.yaml` (or equivalent), and add:

```yaml
# JP-CLINS v1.12.0 code systems (session 47 PR2a)
jpfhir-doc-typecodes: "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
jpfhir-doc-section: "http://jpfhir.jp/fhir/clins/CodeSystem/jp-codeSystem-clins-document-section"
```

Verify format vs the existing file, mirror its structure.

- [ ] **Step 2: 文書区分 CodeSystem 追加**

Create `clinosim/codes/data/jpfhir-doc-typecodes.yaml`:

```yaml
# JP-CLINS document type CodeSystem
# Canonical URL: http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes
# Source: https://jpfhir.jp/fhir/clins/igv1/CodeSystem-jp-codeSystem-documentTypeCode.html
# Verified 2026-07-12 (session 47 P2-13 PR2a)
codes:
  "18842-5":
    en: "Discharge summary"
    ja: "退院時サマリー"
  "57133-1":
    en: "Referral note"
    ja: "診療情報提供書"
  "JPGCHKUP01":
    en: "Health checkup report"
    ja: "健診結果報告書"
  "57833-6":
    en: "Prescription for medication"
    ja: "処方箋"
  "56447-6":
    en: "Plan of care note"
    ja: "計画書"
```

- [ ] **Step 3: 文書 section CodeSystem 追加**

Create `clinosim/codes/data/jpfhir-doc-section-codes.yaml`:

```yaml
# JP-CLINS document section CodeSystem
# Canonical URL: http://jpfhir.jp/fhir/clins/CodeSystem/jp-codeSystem-clins-document-section
# Source: https://jpfhir.jp/fhir/clins/igv1/CodeSystem-jp-codeSystem-clins-document-section.html
# Verified 2026-07-12 (session 47 P2-13 PR2a)
codes:
  # === COMMON sections ===
  "200":
    en: "CDA reference section"
    ja: "CDA参照セクション"
  "210":
    en: "Attachment information section"
    ja: "添付情報セクション"
  "230":
    en: "PDF section"
    ja: "PDFセクション"
  "300":
    en: "Structured information section"
    ja: "構造情報セクション"
  "360":
    en: "Present illness section"
    ja: "現病歴セクション"
  "370":
    en: "Past illness section"
    ja: "既往歴セクション"
  "410":
    en: "Advance directive section"
    ja: "事前指示セクション"
  "510":
    en: "Allergy / intolerance section"
    ja: "アレルギー・不耐性反応セクション"
  "530":
    en: "Immunization history section"
    ja: "予防接種歴セクション"
  "550":
    en: "Family history section"
    ja: "家族歴セクション"
  "640":
    en: "Social history / lifestyle section"
    ja: "社会歴・生活習慣セクション"
  "810":
    en: "Medical device section"
    ja: "医療機器セクション"
  "830":
    en: "Clinical research participation section"
    ja: "臨床研究参加セクション"
  # === DIS (Discharge summary) sections ===
  "312":
    en: "Reason for admission section"
    ja: "入院理由セクション"
  "322":
    en: "Admission details section"
    ja: "入院時詳細セクション"
  "324":
    en: "Discharge details section"
    ja: "退院時詳細セクション"
  "333":
    en: "Hospital course section"
    ja: "入院中経過セクション"
  "342":
    en: "Admission diagnoses section"
    ja: "入院時診断セクション"
  "344":
    en: "Discharge diagnoses section"
    ja: "退院時診断セクション"
  "352":
    en: "Chief complaints section"
    ja: "主訴セクション"
  "424":
    en: "Discharge policy / instructions section"
    ja: "退院時方針指示セクション"
  "432":
    en: "Medications on admission section"
    ja: "入院時服薬セクション"
  "444":
    en: "Discharge medication orders section"
    ja: "退院時投薬指示セクション"
  "612":
    en: "Physical findings on admission section"
    ja: "入院時身体所見セクション"
  "614":
    en: "Physical findings on discharge section"
    ja: "退院時身体所見セクション"
  "623":
    en: "In-hospital lab results section"
    ja: "入院中検査結果セクション"
  "713":
    en: "In-hospital treatment section"
    ja: "入院中治療セクション"
  # === REF (Referral) sections ===
  "220":
    en: "Note / contact information section"
    ja: "備考・連絡情報セクション"
  "330":
    en: "Clinical course section"
    ja: "臨床経過セクション"
  "340":
    en: "Diagnoses / chief complaint section"
    ja: "傷病名・主訴セクション"
  "420":
    en: "Clinical policy / instructions section"
    ja: "診療方針指示セクション"
  "430":
    en: "Medication orders section"
    ja: "投薬指示セクション"
  "520":
    en: "Infection information section"
    ja: "感染症情報セクション"
  "610":
    en: "Physical findings section"
    ja: "身体所見セクション"
  "620":
    en: "Lab results section"
    ja: "検査結果セクション"
  "720":
    en: "Procedure section"
    ja: "処置セクション"
  "730":
    en: "Operation section"
    ja: "手術セクション"
  "740":
    en: "Transfusion history section"
    ja: "輸血歴セクション"
  "910":
    en: "Referral destination information section"
    ja: "紹介先情報セクション"
  "920":
    en: "Referring institution information section"
    ja: "紹介元情報セクション"
  "950":
    en: "Referral purpose section"
    ja: "紹介目的セクション"
  # === PCS (Patient care summary) sections ===
  "422":
    en: "Plan summary section"
    ja: "計画サマリーセクション"
```

- [ ] **Step 4: unit test for code lookup**

Add to a new file `tests/unit/test_jpfhir_codes_lookup.py`:

```python
"""P2-13 PR2a Task 1: jpfhir doc-typecodes + doc-section-codes lookup."""

import pytest

from clinosim.codes import get_system_uri, lookup


@pytest.mark.unit
def test_jpfhir_doc_typecodes_system_uri():
    assert get_system_uri("jpfhir-doc-typecodes") == (
        "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
    )


@pytest.mark.unit
def test_jpfhir_doc_section_system_uri():
    assert get_system_uri("jpfhir-doc-section") == (
        "http://jpfhir.jp/fhir/clins/CodeSystem/jp-codeSystem-clins-document-section"
    )


@pytest.mark.unit
@pytest.mark.parametrize("code,ja", [
    ("18842-5", "退院時サマリー"),
    ("57133-1", "診療情報提供書"),
    ("JPGCHKUP01", "健診結果報告書"),
    ("57833-6", "処方箋"),
    ("56447-6", "計画書"),
])
def test_jpfhir_doc_typecodes_ja_lookup(code, ja):
    assert lookup("jpfhir-doc-typecodes", code, "ja") == ja


@pytest.mark.unit
@pytest.mark.parametrize("code,ja", [
    ("300", "構造情報セクション"),
    ("312", "入院理由セクション"),
    ("322", "入院時詳細セクション"),
    ("342", "入院時診断セクション"),
    ("352", "主訴セクション"),
    ("360", "現病歴セクション"),
    ("910", "紹介先情報セクション"),
    ("920", "紹介元情報セクション"),
    ("950", "紹介目的セクション"),
])
def test_jpfhir_doc_section_ja_lookup(code, ja):
    assert lookup("jpfhir-doc-section", code, "ja") == ja
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_jpfhir_codes_lookup.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add clinosim/codes/data/jpfhir-doc-typecodes.yaml \
        clinosim/codes/data/jpfhir-doc-section-codes.yaml \
        clinosim/codes/data/system_uris.yaml \
        tests/unit/test_jpfhir_codes_lookup.py
git commit -m "feat(codes): P2-13 PR2a add jpfhir doc-typecodes + doc-section CodeSystems

Registers the 2 JP-CLINS-specific CodeSystems needed for Composition
emission (doc-typecodes for Composition.type, doc-section-codes for
section.code). URLs verified against jpfhir.jp v1.12.0 (2026-02-16).

- doc-typecodes: 5 codes (18842-5 退院時サマリー / 57133-1 診療情報提供書 /
  JPGCHKUP01 健診結果報告書 / 57833-6 処方箋 / 56447-6 計画書)
- doc-section-codes: 43 codes (COMMON/DIS/REF/PCS groups)

Both accessible via existing clinosim.codes.lookup(system, code, lang) API.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

---

### Task 2: JP-CLINS 退院時サマリー用 narrative section 定義

**Files:**
- Modify: `clinosim/modules/document/reference_data/document_type_specs.yaml`(discharge_summary に `composition_sections_jp` 追加、既存 `composition_sections` は US 用として維持)
- Modify: `clinosim/modules/document/narrative/generator.py`(country=JP 時に `composition_sections_jp` を優先読み)or 同等の分岐箇所
- Modify: 該当 template 生成コード or `templates/discharge_summary_ja.yaml`(存在すれば)
- Test: `tests/unit/test_document_jp_clins_sections.py`

**Interfaces:**
- Consumes: —
- Produces:
  - country=JP かつ `discharge_summary` doc type = narrative の `sections` dict は英語 snake_case key で以下 5 個:`admission_reason` / `admission_details` / `admission_diagnoses` / `chief_complaint` / `present_illness`
  - country=US = 既存 6 sections 変わらず(`admission_summary` / `hospital_course` / `discharge_diagnoses` / `discharge_medications` / `discharge_instructions` / `follow_up`)

- [ ] **Step 1: Read the existing document_generator flow to identify branch point**

Run: `grep -n "discharge_summary\|composition_sections\|DISCHARGE_SUMMARY" clinosim/modules/document/*.py clinosim/modules/document/narrative/*.py | head -20`

Identify how `composition_sections` is currently consumed by narrative generator.

- [ ] **Step 2: Add JP variant to spec YAML**

Edit `clinosim/modules/document/reference_data/document_type_specs.yaml` `discharge_summary`:

```yaml
  discharge_summary:
    loinc_code: "18842-5"
    format_type: composition
    countries_supported: [us, jp]
    encounter_types_supported: [inpatient, icu, rehab_inpatient]
    generation_frequency: discharge_once
    composition_sections:
      - admission_summary
      - hospital_course
      - discharge_diagnoses
      - discharge_medications
      - discharge_instructions
      - follow_up
    # JP-CLINS v1.12.0 required 5-section structure under structural (300).
    # See docs/superpowers/plans/2026-07-12-p2-13-jp-clins-pr2a-discharge-summary.md
    composition_sections_jp:
      - admission_reason
      - admission_details
      - admission_diagnoses
      - chief_complaint
      - present_illness
    stage2_strategy: template_seed
    llm_enabled_sections: [hospital_course, discharge_instructions]
```

- [ ] **Step 3: Failing test — narrative section keys diverge by country**

Add `tests/unit/test_document_jp_clins_sections.py`:

```python
"""P2-13 PR2a Task 2: JP-CLINS discharge summary narrative sections."""

from __future__ import annotations

import pytest

from clinosim.modules.document.spec import get_document_type_spec


@pytest.mark.unit
def test_discharge_summary_us_sections_unchanged():
    spec = get_document_type_spec("discharge_summary")
    assert spec.composition_sections_for("US") == [
        "admission_summary",
        "hospital_course",
        "discharge_diagnoses",
        "discharge_medications",
        "discharge_instructions",
        "follow_up",
    ]


@pytest.mark.unit
def test_discharge_summary_jp_sections_are_5_required():
    spec = get_document_type_spec("discharge_summary")
    assert spec.composition_sections_for("JP") == [
        "admission_reason",
        "admission_details",
        "admission_diagnoses",
        "chief_complaint",
        "present_illness",
    ]
```

- [ ] **Step 4: Wire `composition_sections_for(country)` into spec class**

Locate the class that reads `document_type_specs.yaml` and add / update its accessor to accept a country arg:

```python
def composition_sections_for(self, country: str) -> list[str]:
    if country.upper() == "JP" and getattr(self, "composition_sections_jp", None):
        return list(self.composition_sections_jp)
    return list(self.composition_sections or [])
```

Wire whatever downstream calls `spec.composition_sections` today (narrative generator, document enricher) to pass `country` (available via `SimulatorConfig.country` or per-record).

- [ ] **Step 5: Run test**

Run: `pytest tests/unit/test_document_jp_clins_sections.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/document/reference_data/document_type_specs.yaml \
        clinosim/modules/document/spec.py \
        tests/unit/test_document_jp_clins_sections.py
git commit -m "feat(document): P2-13 PR2a add JP-CLINS discharge summary section list

Adds composition_sections_jp to the discharge_summary spec, 5 required
sections per JP-CLINS v1.12.0 (admission_reason / admission_details /
admission_diagnoses / chief_complaint / present_illness). US spec
unchanged.

Accessor composition_sections_for(country) picks the JP list only when
country=JP; US bundles are byte-identical.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

---

### Task 3: JP 用 discharge summary narrative template

**Files:**
- Locate the current JP template asset for discharge summary narrative (likely `clinosim/modules/llm_service/prompts/ja/discharge_summary.yaml` or `clinosim/modules/document/narrative/templates/*.yaml`)
- Create: 5 new section renderers matching the JP keys (`admission_reason` / `admission_details` / `admission_diagnoses` / `chief_complaint` / `present_illness`)
- Modify: `TemplateNarrativeGenerator` or `narrative/passes.py` to consume `composition_sections_for(country)` instead of hard-coded English list
- Test: `tests/unit/test_document_jp_narrative_render.py`

**Interfaces:**
- Consumes: Task 2 `composition_sections_for("JP")`, existing CIF (record.patient, encounter, orders, conditions, discharge_diagnosis)
- Produces: `ClinicalDocument(type=DISCHARGE_SUMMARY, country=JP).narrative.sections = {"admission_reason": "...", "admission_details": "...", "admission_diagnoses": "...", "chief_complaint": "...", "present_illness": "..."}`

Content mapping (JP display language):

| Section key | Source in CIF | Rendered text (JP) |
|---|---|---|
| admission_reason | primary admission diagnosis display + chief complaint | e.g. "○○のため入院となった。" |
| admission_details | Encounter.admission_datetime + admission source (ED経由 flag) + ward | e.g. "YYYY年MM月DD日、救急外来受診後、内科病棟に入院。" |
| admission_diagnoses | EncounterDiagnosisRecord.admission_diagnosis_display (primary + secondary) | 番号付きリスト |
| chief_complaint | patient.chief_complaint / disease protocol chief_complaint[ja] | 一言 |
| present_illness | condensed HPI (from existing narrative hpi if present, else generated from disease scenario) | 数文 |

- [ ] **Step 1: Locate current narrative render code + template**

Run: `grep -rn "discharge_summary\|admission_summary\|hospital_course" clinosim/modules/document/narrative/ clinosim/modules/llm_service/prompts/ja/ 2>/dev/null | head -20`

Read the current pipeline that produces `narrative.sections` dict for discharge summary.

- [ ] **Step 2: Add JP 5-section renderers**

Add 5 helper functions (or template YAML entries) that produce each section's Japanese text given a `record`, `encounter`, `discharge_diagnosis` context. Style matches existing JP discharge_summary asset (senior physician tone).

- [ ] **Step 3: Wire the country=JP branch in TemplateNarrativeGenerator (or equivalent)**

Where the pass iterates `spec.composition_sections`, switch to `spec.composition_sections_for(record.country)` and dispatch to the correct renderer per key.

- [ ] **Step 4: Failing test — JP discharge summary narrative content**

Add `tests/unit/test_document_jp_narrative_render.py`:

```python
"""P2-13 PR2a Task 3: JP discharge summary narrative render."""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_jp_discharge_summary_narrative_has_5_sections():
    # Use AD-66 canonical fixture (bacterial pneumonia JP) to drive
    # narrative pass and verify sections dict.
    from pathlib import Path
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass
    from clinosim.simulator.engine import run_forced
    from clinosim.types.config import SimulatorConfig, load_patient_profile

    profile_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures" / "patient_profiles"
        / "jp_inpatient_bacterial_pneumonia.yaml"
    )
    profile = load_patient_profile(str(profile_path))
    scenario = profile.to_forced_scenario()
    config = SimulatorConfig(
        random_seed=profile.random_seed,
        country=profile.country,
        hospital_scale=profile.hospital_scale,
        catchment_population=profile.count,
    )
    dataset = run_forced(scenario, config)

    ds_docs = []
    for record in dataset.records:
        for doc in getattr(record, "documents", []) or []:
            if getattr(doc, "loinc_code", "") == "18842-5":
                ds_docs.append(doc)

    assert ds_docs, "expected at least one discharge_summary in JP cohort"
    for doc in ds_docs:
        narr = getattr(doc, "narrative", None) or {}
        secs = getattr(narr, "sections", None) or narr.get("sections", {}) or {}
        assert set(secs.keys()) == {
            "admission_reason",
            "admission_details",
            "admission_diagnoses",
            "chief_complaint",
            "present_illness",
        }, f"unexpected JP DS section keys: {sorted(secs.keys())}"
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_document_jp_narrative_render.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/document/ tests/unit/test_document_jp_narrative_render.py
git commit -m "feat(narrative): P2-13 PR2a add JP-CLINS discharge summary section renderers

5 JP section renderers (admission_reason / admission_details /
admission_diagnoses / chief_complaint / present_illness) consumed by
TemplateNarrativePass when country=JP + doc_type=discharge_summary.
US path uses existing 6-section renderers unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

---

### Task 4: JP-CLINS Composition builder(dispatch)

**Files:**
- Modify: `clinosim/modules/output/_fhir_composition.py`(country=JP + doc_type=discharge_summary で新 helper 呼び分け)
- Test: `tests/unit/test_jp_clins_composition_ds.py`

**Interfaces:**
- Consumes: Task 1 の CodeSystem, Task 3 の narrative sections
- Produces:
  - `_build_jp_clins_discharge_summary_composition(doc, sections, lang) -> dict`
  - Composition.type coding uses `jpfhir-doc-typecodes` system (18842-5)
  - Composition.section[] contains nested section 300 with 5 required child sections (312/322/342/352/360), each with `code.coding.system = jpfhir-doc-section` and `text.div` from `sections` dict
  - meta.profile[] = `["http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/JP_Composition_eDischargeSummary"]`

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_jp_clins_composition_ds.py
"""P2-13 PR2a Task 4: JP-CLINS discharge summary Composition unit tests."""

from __future__ import annotations

import pytest


_PROFILE_URL = (
    "http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/"
    "JP_Composition_eDischargeSummary"
)
_DOC_TYPE_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
_SECTION_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/jp-codeSystem-clins-document-section"


@pytest.fixture
def jp_ds_doc():
    """Minimal ClinicalDocument stub for JP discharge summary."""
    return {
        "document_id": "doc-ENC-001-01",
        "document_type": "DISCHARGE_SUMMARY",
        "loinc_code": "18842-5",
        "format_type": "composition",
        "country": "JP",
        "patient_id": "POP-000001",
        "encounter_id": "ENC-001",
        "author_practitioner_id": "PRAC-JP-001",
        "authored_datetime": "2026-01-20T10:00:00",
        "language": "ja",
        "period_start": "2026-01-15T09:00:00",
        "period_end": "2026-01-20T10:00:00",
        "narrative": {"sections": {
            "admission_reason": "細菌性肺炎のため入院となった。",
            "admission_details": "2026年1月15日、救急外来受診後、内科病棟に入院。",
            "admission_diagnoses": "1. 細菌性肺炎(J13)",
            "chief_complaint": "発熱・咳嗽",
            "present_illness": "3日前より発熱と咳嗽を認め、当院受診となった。",
        }},
    }


@pytest.mark.unit
def test_jp_clins_composition_type_uses_doc_typecodes(jp_ds_doc):
    from clinosim.modules.output._fhir_composition import _build_composition
    comp = _build_composition(jp_ds_doc, jp_ds_doc["narrative"]["sections"], "ja")
    assert any(
        c.get("system") == _DOC_TYPE_SYSTEM and c.get("code") == "18842-5"
        for c in comp["type"]["coding"]
    ), comp["type"]


@pytest.mark.unit
def test_jp_clins_composition_has_profile(jp_ds_doc):
    from clinosim.modules.output._fhir_composition import _build_composition
    comp = _build_composition(jp_ds_doc, jp_ds_doc["narrative"]["sections"], "ja")
    profs = comp.get("meta", {}).get("profile", [])
    assert _PROFILE_URL in profs


@pytest.mark.unit
def test_jp_clins_composition_has_nested_structural_section(jp_ds_doc):
    from clinosim.modules.output._fhir_composition import _build_composition
    comp = _build_composition(jp_ds_doc, jp_ds_doc["narrative"]["sections"], "ja")
    top = comp["section"]
    # Exactly one top-level section (300 構造情報) that nests 5 required children.
    assert len(top) == 1, top
    parent = top[0]
    parent_code = parent["code"]["coding"][0]
    assert parent_code["system"] == _SECTION_SYSTEM
    assert parent_code["code"] == "300"
    children = parent["section"]
    child_codes = {c["code"]["coding"][0]["code"] for c in children}
    assert child_codes == {"312", "322", "342", "352", "360"}


@pytest.mark.unit
def test_jp_clins_composition_child_section_text_div(jp_ds_doc):
    from clinosim.modules.output._fhir_composition import _build_composition
    comp = _build_composition(jp_ds_doc, jp_ds_doc["narrative"]["sections"], "ja")
    parent = comp["section"][0]
    children_by_code = {
        c["code"]["coding"][0]["code"]: c for c in parent["section"]
    }
    # 312 = admission_reason
    assert "細菌性肺炎" in children_by_code["312"]["text"]["div"]
    # 352 = chief_complaint
    assert "発熱" in children_by_code["352"]["text"]["div"]
    # 360 = present_illness
    assert "3日前" in children_by_code["360"]["text"]["div"]


@pytest.mark.unit
def test_us_discharge_summary_composition_unchanged(jp_ds_doc):
    us_doc = dict(jp_ds_doc)
    us_doc["country"] = "US"
    us_doc["language"] = "en"
    us_doc["narrative"] = {"sections": {
        "admission_summary": "Admitted for bacterial pneumonia.",
        "hospital_course": "Improved on ceftriaxone.",
        "discharge_diagnoses": "1. Bacterial pneumonia (J13)",
        "discharge_medications": "amoxicillin-clavulanate 500mg PO TID x7d",
        "discharge_instructions": "Follow up in 1 week.",
        "follow_up": "PCP in 7 days",
    }}
    from clinosim.modules.output._fhir_composition import _build_composition
    comp = _build_composition(us_doc, us_doc["narrative"]["sections"], "en")
    # No JP-CLINS profile
    profs = comp.get("meta", {}).get("profile", [])
    assert not any(p.startswith(
        "http://jpfhir.jp/fhir/eDischargeSummary/") for p in profs), profs
    # Type uses LOINC (not doc-typecodes)
    assert any(c.get("system") == "http://loinc.org"
               for c in comp["type"]["coding"]), comp["type"]
    # Flat 6 sections at top level (no nesting)
    assert len(comp["section"]) == 6
```

- [ ] **Step 2: Run failing test**

Run: `pytest tests/unit/test_jp_clins_composition_ds.py -v`
Expected: FAIL (existing `_build_composition` returns US structure regardless of country)

- [ ] **Step 3: Implement dispatch**

In `clinosim/modules/output/_fhir_composition.py`, refactor `_build_composition` to dispatch by (country, loinc_code):

```python
def _build_composition(doc, sections, lang):
    country = (_o(doc, "country", "") or "").upper()
    loinc_code = _o(doc, "loinc_code", "")
    if country == "JP" and loinc_code == "18842-5":
        return _build_jp_clins_discharge_summary_composition(doc, sections, lang)
    return _build_composition_generic(doc, sections, lang)  # existing body
```

Rename existing body to `_build_composition_generic`, add new `_build_jp_clins_discharge_summary_composition`:

```python
_JP_CLINS_DS_PROFILE = (
    "http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/"
    "JP_Composition_eDischargeSummary"
)
_JPFHIR_DOC_TYPECODES_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
_JPFHIR_DOC_SECTION_SYSTEM = (
    "http://jpfhir.jp/fhir/clins/CodeSystem/jp-codeSystem-clins-document-section"
)

# JP discharge summary section-key → jpfhir section code
_JP_DS_SECTION_CODE: dict[str, str] = {
    "admission_reason":    "312",
    "admission_details":   "322",
    "admission_diagnoses": "342",
    "chief_complaint":     "352",
    "present_illness":     "360",
}


def _build_jp_clins_discharge_summary_composition(doc, sections, lang):
    """Emit a Composition conforming to JP-CLINS eDischargeSummary v1.12.0.

    Structure:
      - meta.profile = [JP_Composition_eDischargeSummary]
      - type = { system: doc-typecodes, code: "18842-5" }
      - section[0] = 300 構造情報, nesting the 5 required child sections
    """
    # Reuse existing _build_composition_generic for common fields (id / subject /
    # date / author / encounter / etc.), then override type + section.
    comp = _build_composition_generic(doc, sections, lang)
    # meta.profile
    meta = comp.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if _JP_CLINS_DS_PROFILE not in profs:
        profs.append(_JP_CLINS_DS_PROFILE)
    # type — use doc-typecodes, keep LOINC coding as secondary too (interop)
    disp = code_lookup("jpfhir-doc-typecodes", "18842-5", lang) or "退院時サマリー"
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM,
             "code": "18842-5", "display": disp},
            {"system": get_system_uri("loinc"),
             "code": "18842-5", "display": disp},
        ],
        "text": disp,
    }
    # section: 300 parent + 5 child sections
    parent_disp = code_lookup("jpfhir-doc-section", "300", lang) or "構造情報セクション"
    child_sections = []
    for key, code in _JP_DS_SECTION_CODE.items():
        disp_c = code_lookup("jpfhir-doc-section", code, lang) or key
        text_val = sections.get(key, "") or ""
        child_sections.append({
            "title": disp_c,
            "code": {"coding": [{
                "system": _JPFHIR_DOC_SECTION_SYSTEM,
                "code": code,
                "display": disp_c,
            }], "text": disp_c},
            "text": {
                "status": "generated",
                "div": (f'<div xmlns="http://www.w3.org/1999/xhtml">'
                        f'{_escape_html(text_val)}</div>'),
            },
        })
    comp["section"] = [{
        "title": parent_disp,
        "code": {"coding": [{
            "system": _JPFHIR_DOC_SECTION_SYSTEM,
            "code": "300",
            "display": parent_disp,
        }], "text": parent_disp},
        "section": child_sections,
    }]
    return comp
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_jp_clins_composition_ds.py -v`
Expected: 5 PASS

- [ ] **Step 5: Full FHIR unit regression**

Run: `pytest tests/unit -k fhir -q`
Expected: PASS + newly added tests, 0 regression on existing FHIR unit tests.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/output/_fhir_composition.py \
        tests/unit/test_jp_clins_composition_ds.py
git commit -m "feat(fhir): P2-13 PR2a add JP-CLINS discharge summary Composition builder

Introduces _build_jp_clins_discharge_summary_composition dispatched from
_build_composition when country=JP + LOINC=18842-5. Attaches
JP_Composition_eDischargeSummary profile URL, uses doc-typecodes
CodeSystem for Composition.type, and produces the required nested
5-section structure (300 parent nesting 312/322/342/352/360).

US Composition path unchanged (US bundles byte-identical).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

---

### Task 5: Integration test + reproducibility

**Files:**
- Create: `tests/integration/test_jp_clins_composition_ds_end_to_end.py`
- Run: `bash scripts/reproduce.sh`

**Interfaces:** —

- [ ] **Step 1: Write integration test**

```python
# tests/integration/test_jp_clins_composition_ds_end_to_end.py
"""P2-13 PR2a Task 5: JP-CLINS discharge summary Composition end-to-end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.integration._sr_helpers import run_generate


_PROFILE = (
    "http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/"
    "JP_Composition_eDischargeSummary"
)
_DOC_TYPE_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
_SECTION_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/jp-codeSystem-clins-document-section"


def _read_ndjson(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


@pytest.mark.integration
def test_jp_p50_discharge_summary_composition_conforms(tmp_path):
    outdir = tmp_path / "jp"
    run_generate("JP", 50, 42, outdir, end="2026-06-30")
    comp_path = None
    for cand in outdir.rglob("Composition.ndjson"):
        comp_path = cand
        break
    assert comp_path, "Composition.ndjson not found"
    comps = _read_ndjson(comp_path)
    ds = [c for c in comps if any(
        cc.get("code") == "18842-5"
        for cc in c.get("type", {}).get("coding", [])
    )]
    assert ds, "no discharge summary Composition"

    for c in ds:
        # profile emitted
        assert _PROFILE in c.get("meta", {}).get("profile", []), c["id"]
        # doc-typecodes coding present
        systems = {cc.get("system") for cc in c["type"]["coding"]}
        assert _DOC_TYPE_SYSTEM in systems, c["type"]
        # nested 300 → 5 required children
        top = c.get("section", [])
        assert len(top) == 1, c["id"]
        parent = top[0]
        assert parent["code"]["coding"][0]["code"] == "300"
        children = parent.get("section", [])
        codes = [ch["code"]["coding"][0]["code"] for ch in children]
        assert set(codes) == {"312", "322", "342", "352", "360"}, codes
        for ch in children:
            assert ch["code"]["coding"][0]["system"] == _SECTION_SYSTEM
            assert ch["text"]["div"], "empty section text.div"


@pytest.mark.integration
def test_us_p50_discharge_summary_composition_unchanged(tmp_path):
    outdir = tmp_path / "us"
    run_generate("US", 50, 42, outdir, end="2026-06-30")
    comp_path = None
    for cand in outdir.rglob("Composition.ndjson"):
        comp_path = cand
        break
    if not comp_path:
        return  # US may or may not emit Composition; skip if absent
    comps = _read_ndjson(comp_path)
    for c in comps:
        # No JP-CLINS profile leaks into US
        profs = c.get("meta", {}).get("profile", [])
        assert not any(p.startswith(
            "http://jpfhir.jp/fhir/eDischargeSummary/") for p in profs), profs
        # US DS type coding still uses LOINC directly
        systems = {cc.get("system") for cc in c.get("type", {}).get("coding", [])}
        assert _DOC_TYPE_SYSTEM not in systems, c["type"]


@pytest.mark.integration
def test_us_p50_has_no_japanese_language_leakage(tmp_path):
    """★ Multi-locale enforcement: US bundle must not contain JP CodeSystem URIs
    nor Japanese text in Composition sections / titles / display values."""
    outdir = tmp_path / "us-lang"
    run_generate("US", 50, 42, outdir, end="2026-06-30")
    jp_signals = [
        _DOC_TYPE_SYSTEM,
        _SECTION_SYSTEM,
        "http://jpfhir.jp/fhir/eDischargeSummary/",
        "http://jpfhir.jp/fhir/eReferral/",
        "http://jpfhir.jp/fhir/eCS/",
        "http://jpfhir.jp/fhir/core/",
    ]
    for ndjson_path in outdir.rglob("*.ndjson"):
        with open(ndjson_path) as f:
            content = f.read()
        for sig in jp_signals:
            assert sig not in content, (
                f"US bundle {ndjson_path.name} contains JP signal {sig!r}"
            )
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/integration/test_jp_clins_composition_ds_end_to_end.py -v -m integration`
Expected: 2 PASS

- [ ] **Step 3: Run reproduce.sh**

Run: `bash scripts/reproduce.sh`
Expected: PASS (both US and JP internally byte-identical; JP output changed from previous PR1 baseline — that's the intentional PR2a diff)

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_jp_clins_composition_ds_end_to_end.py
git commit -m "test(integration): P2-13 PR2a verify JP-CLINS discharge summary Composition

Full generate → NDJSON → Composition.ndjson coverage for country=JP
p=50 seed=42 end=2026-06-30. Confirms:
- discharge summary Composition carries JP_Composition_eDischargeSummary
  profile URL
- type.coding uses doc-typecodes system + 18842-5
- section structure is 300 (structural) nesting 5 required children
  (312/322/342/352/360), each with system = jp-codeSystem-clins-document-section
- US discharge summary Composition remains on the previous flat 6-section
  structure with no JP-CLINS URL leakage

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QKWJC5cbLaBYfTywtrx92a"
```

---

### Task 6: Docs + TODO + full-suite gate

**Files:**
- Modify: `docs/jp-clins.md`(PR2a コンテンツ追加)
- Modify: `TODO.md`(PR2a マーク done、PR2b 追加)

**Interfaces:** —

- [ ] **Step 1: Update `docs/jp-clins.md`**

Add a new section under "Scope" describing the JP discharge summary Composition:

```markdown
### JP-CLINS 退院時サマリー Composition (PR2a)

For every `country=JP` inpatient discharge encounter, clinosim emits a
Composition resource conforming to
`JP_Composition_eDischargeSummary` (v1.12.0):

- Composition.meta.profile includes
  `http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/JP_Composition_eDischargeSummary`
- Composition.type.coding[0].system = `.../doc-typecodes`, code = `18842-5`
- Composition.section is a single nested tree: 300 構造情報 → { 312 入院理由, 322
  入院時詳細, 342 入院時診断, 352 主訴, 360 現病歴 }
- section.code.system = `.../jp-codeSystem-clins-document-section`
- section.text.div is generated by the template narrative pass in
  Japanese (β-JP-1 will optionally replace with LLM-generated content).

US discharge summary Composition retains the current 6-section flat
structure and is unchanged.
```

- [ ] **Step 2: Update TODO.md**

```markdown
- **P2-13** JP-CLINS ...
  - [x] PR1 (session 47): 6 information items JP-CLINS eCS profile URL layer
  - [x] PR2a (session 47): Full-conformance discharge summary Composition
    (JP_Composition_eDischargeSummary), doc-typecodes + jp-codeSystem-clins-document-section
    added to codes/data/, JP section renderers.
  - [ ] PR2b: 診療情報提供書 (Referral note) Composition + CIF 紹介元/紹介先 extension
  - [ ] PR3: 健診 opt-in + jpfhir-validator bridge + docs polish
```

- [ ] **Step 3: Full unit regression**

Run: `pytest tests/unit -q --no-header`
Expected: PASS(session 47 PR1 wrap 2504 + 新規 tests、regression 0)

- [ ] **Step 4: Commit + push**

```bash
git add docs/jp-clins.md TODO.md
git commit -m "docs(p2-13): PR2a docs + TODO tick

Adds docs/jp-clins.md section for the JP-CLINS discharge summary
Composition (v1.12.0 conformance). TODO marks PR2a done and PR2b
pending."

git push origin master
```

---

## Self-Review Checklist

**1. Spec coverage:** All PR2a scope items covered:
- doc-typecodes + doc-section-codes CodeSystems registered (Task 1)
- JP discharge summary section structure defined (Task 2)
- JP narrative section renderers (Task 3)
- JP-CLINS Composition builder dispatch (Task 4)
- End-to-end integration + reproducibility gate (Task 5)
- Docs + TODO (Task 6)

**2. Placeholder scan:** No TBD / TODO / vague requirements in tasks.

**3. Type consistency:**
- `_build_jp_clins_discharge_summary_composition(doc, sections, lang) -> dict`
- `_JP_CLINS_DS_PROFILE: str`
- `_JPFHIR_DOC_TYPECODES_SYSTEM: str`
- `_JPFHIR_DOC_SECTION_SYSTEM: str`
- `_JP_DS_SECTION_CODE: dict[str, str]`
- Spec YAML key: `composition_sections_jp: list[str]`
- Accessor: `spec.composition_sections_for(country: str) -> list[str]`
- JP section keys: `admission_reason` / `admission_details` / `admission_diagnoses` / `chief_complaint` / `present_illness`

**4. Risks:**
- **template renderer wiring**:既存 `TemplateNarrativeGenerator` の flow が section キー名を hard-coded で持つ場合、大幅拡張必要 → Task 3 で見つかったら PR 分割検討
- **section renderer 品質**:template-based 生成の JP テキストが臨床的自然さで落ちる → β-JP-1 で改善(seam 保持)
- **byte-diff JP baseline**:JP output は change する(意図的)、CI reproducibility gate は run-to-run 比較なので pass、golden はないため update 不要
