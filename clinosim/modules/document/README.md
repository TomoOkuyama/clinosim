# document モジュール

## 役割

Tier 1 #3 α-min-1 の Always-on Module (AD-55 near-essential cascade)。
入院・外来・救急 encounter ごとに臨床 narrative (入院時記録 / 経過記録 / 退院サマリ) を生成し、
FHIR `DocumentReference` / `Composition` として emit する。

α-min-1 段階では骨格 (DocumentTypeSpec registry + NarrativeContext factory) を提供。
Task 6+ で template generator、Task 8 で POST_ENCOUNTER enricher、Task 9 で FHIR builder を追加する。

## Dependencies

- `clinosim/types/document.py` — `DocumentType` / `FormatType` / `DocumentTypeSpec` /
  `NarrativeContext` / `NarrativeOutput` / `NarrativeGenerator` Protocol(N-chain で
  `DocumentTypeSpec` と generator 契約を types へ移設。`narrative/registry.py` は
  loader + 後方互換 re-export)
- `clinosim/types/allergy.py` — `Allergy` (NarrativeContext.allergies)
- `clinosim/modules/_shared.py` — `get_attr_or_key` (dual-access helper for dict / dataclass)
- `clinosim/modules/llm_service/` — `LLMService.complete_prompt`(AD-11 経由の LLM 呼出し。
  `LLMNarrativeGenerator` / `apply_replacement_strategy` / `LLMNarrativePass` のみが使用、
  template 経路は依存しない)

## Reference data

| ファイル | 説明 |
|---|---|
| `reference_data/document_type_specs.yaml` | 3 文書種別の LOINC コード・表示名・セクション構成・生成戦略 |

α-min-1 scope = `ADMISSION_HP` / `PROGRESS_NOTE` / `DISCHARGE_SUMMARY` の 3 種。本 chain では追加禁止 (scope discipline)。

## generation_frequency 値(canonical allowlist = `registry.GENERATION_FREQUENCIES`)

| 値 | 発行 cadence | 使用 doc type |
|---|---|---|
| `admission_once` | day 0 に 1 通 | ADMISSION_HP / ADMISSION_NURSING_ASSESSMENT |
| `daily` | LOS 日ごとに 1 通(LOS=1 skip) | PROGRESS_NOTE |
| `daily_3shift` | LOS 日ごとに 3 通(深夜 00:00 / 日勤 08:00 / 準夜 16:00、`engine.SHIFT_SCHEDULE`。LOS=1 skip、AD-32 同様)| NURSING_SHIFT_NOTE(α-min-3) |
| `discharge_once` | 最終日に 1 通(in-progress は AD-32 で skip) | DISCHARGE_SUMMARY / NURSING_DISCHARGE_SUMMARY |
| `encounter_once` | day 0 に 1 通(外来/ED 単回受診) | OUTPATIENT_SOAP / ED_NOTE / ED_TRIAGE_NOTE |

未知の値は `registry._validate_document_type_specs` Layer 7 が YAML load 時に fail-loud
(engine dispatch は if/elif のため、allowlist なしでは typo が silent no-op になる — PR-90 class)。
`daily_3shift` の stub は neutral shift key(`ClinicalDocument.shift` = night/day/evening)を保持し、
localized label(en: night/day/evening、ja: 深夜/日勤/準夜)は Stage 2 render 時に解決(AD-30 spirit)。

## Canonical ID-prefix constants

| 定数 | 値 | 対応 FHIR resource |
|---|---|---|
| `DOC_REFERENCE_ID_PREFIX` | `"doc-"` | `DocumentReference.id` |
| `COMPOSITION_ID_PREFIX` | `"comp-"` | `Composition.id` |
| `ALLERGY_ID_PREFIX` | `"allergy-"` | 参照先 `AllergyIntolerance.id` |
| `CLINICAL_IMPRESSION_ID_PREFIX` | `"ci-"` | `ClinicalImpression.id` |

FHIR builder (Task 9) はこれらをインポートして使用する。

## Consumers

- Task 6 narrative generator: `build_narrative_context()` で `NarrativeContext` を受け取り `NarrativeOutput` を返す
- Task 8 enricher: `load_document_type_specs()` + `specs_for_country()` で生成対象文書を決定
- Task 9 FHIR builder: ID-prefix 定数でリソース ID を構築

## Architecture: Two-Pass Generation (AD-65)

clinosim narrative generation は structural CIF と narrative CIF の **物理ファイル分離** により、
narrative version を独立に差し替え可能 にする (Stage 1 immutable + Stage 2 versioned)。

```
┌──────────────────────────────────────────────────────────────────┐
│ clinosim generate ...                                            │
│                                                                  │
│  Stage 1: Simulate + write structural CIF                        │
│  ──────────────────────────────────────                          │
│  simulator/run_beta                                              │
│    └─ per patient: inpatient/emergency/outpatient simulate       │
│       └─ run_stage(POST_ENCOUNTER)                               │
│           └─ document_enricher(★ AD-65 revised)                 │
│               → append ClinicalDocument STUB(metadata + author + │
│                 encounter_id + narrative=None) to record.documents│
│           └─ triage_enricher / nursing_enricher(unchanged)       │
│  write_cif(dataset, cif_dir)                                     │
│    → cif/structural/patients/<enc_id>.json                       │
│                                                                  │
│  Stage 2: Template narrative pass(★ new, can be re-run)         │
│  ──────────────────────────────────────                          │
│  TemplateNarrativePass.run(cif_dir, version_id="template")       │
│    ├─ scan structural CIF                                        │
│    ├─ collect (doc_stub, structural_ctx) pairs                   │
│    ├─ group by (doc_type, language) for Bedrock-cache            │
│    ├─ for each group:                                            │
│    │    for each patient:                                        │
│    │       build NarrativeContext(patient + encounter + labs +   │
│    │                              conditions + medications + ...)│
│    │       TemplateNarrativeGenerator.generate(ctx, spec)        │
│    │       → NarrativeOutput(raw_text, sections, facts_used)     │
│    │    write cif/narratives/template/documents/<enc>/<doc>.json │
│    └─ write cif/narratives/template/manifest.json                │
│    write cif/narratives/current_version.txt = "template"         │
│                                                                  │
│  Stage 3: FHIR export                                            │
│  ─────────────────                                               │
│  get_adapter("fhir-r4").convert(cif_dir, output_dir, ctx)        │
│    ├─ CIFReader(cif_dir, narrative_version="current")           │
│    │    → merge structural + narrative → CIFPatientRecord        │
│    ├─ _bb_compositions(ctx)     [reads doc.narrative.sections]   │
│    ├─ _bb_document_references() [reads doc.narrative.text]       │
│    └─ writes fhir_r4/*.ndjson + manifest.json                    │
└──────────────────────────────────────────────────────────────────┘

LLM opt-in (N-chain wired; prompt quality tuning = β-JP-1):
┌──────────────────────────────────────────────────────────────────┐
│ clinosim narrate --cif-dir ./output/cif --provider bedrock      │
│                  --version-id "sonnet4-2026-07-02"               │
│                  [--llm-config config/llm_service.bedrock.yaml]  │
│   → LLMNarrativePass.run(...) — drop-in on NarrativePass base   │
│      generator = LLMNarrativeGenerator(template base +           │
│        LLMService.complete_prompt + NarrativeCache)              │
│   → cif/narratives/sonnet4-2026-07-02/documents/<enc>/<doc>.json│
│   → manifest.llm_cost_report = LLMService.cost_report()          │
│   (--provider ollama = config/llm_service.yaml、                 │
│    --provider mock = MockProvider dev/test 用・network 不要)     │
│                                                                  │
│ clinosim export-fhir --cif-dir ./output/cif                      │
│                      --narrative-version sonnet4-2026-07-02      │
│   → 同 structural CIF + 選択 narrative version で再 emit         │
└──────────────────────────────────────────────────────────────────┘
```

### Key invariants

- `document_enricher` (Stage 1) は `ClinicalDocument` stub のみ生成。`narrative` field は `None` に固定。
  narrative content の populate 禁止（Stage 2 差替時 silent-no-op risk）。
- `NarrativePass.run()` (Stage 2) は structural CIF を read → patient profile + labs + conditions +
  medications + scenario_spine を input として narrative を導出 → `narratives/<version>/documents/<enc>/<doc>.json` 書出。
- walk 順序 = `(doc_type, language)` group 単位 serial(Bedrock prompt cache 5 分 TTL の hit rate 最大化)。
  `NarrativePass` base class で契約確定 → β-JP-1 の LLMNarrativePass が drop-in。
- FHIR builders は `doc.narrative.sections` / `doc.narrative.text` 経由のみ。ClinicalDocument flat field
  (`doc.text` / `doc.sections`) は AD-65 で削除。

## Unified narrative interface (N-chain, 2026-07-02)

Stage 2 は単一契約 `NarrativeGenerator` Protocol(`clinosim/types/document.py`:
`generate(ctx, spec) -> NarrativeOutput`)に統一。`NarrativePass` base が generator を
constructor injection で保持し、walk order / CIF I/O と content 生成を分離する。

| 部品 | 役割 |
|---|---|
| `TemplateNarrativePass` | default。`TemplateNarrativeGenerator`(決定的、LLM 依存なし) |
| `LLMNarrativePass` | `LLMNarrativeGenerator`(template base + section 置換)。`narrate --provider bedrock\|ollama\|mock` |
| `LLMNarrativeGenerator` | 3 経路: llm=None → template_fallback WARN / llm 構成済 → `apply_replacement_strategy` / 例外 → template_fallback WARN |
| `apply_replacement_strategy` | `stage2_strategy` dispatch。`template_seed` は `llm_enabled_sections` のみ `LLMService.complete_prompt` で置換(prompt = `prompts/{en,ja}/narrative_seed.yaml`) |
| cache 2 層 | layer 1 = `NarrativeCache`(in-memory、臨床 context key、cross-patient 再利用)/ layer 2 = `PromptCache`(disk、prompt-hash key、`LLMService` 内) |

- LLM 呼出しは `LLMService.complete_prompt` 1 本(AD-11)。retry / PromptCache / token
  集計は service 側、template fallback は generator 側の責務。
- `CLINOSIM_NARRATIVE_LLM` env gate は削除済 — opt-in は CLI `--provider` の明示選択のみ。
- 残 β-JP-1 scope: bedrock/ollama 実プロンプト品質チューニング + `<profile>.llm-<model>.golden.json`
  + semantic diff。Longitudinal chart summary は後期 phase。

## Bug Fix Log (AD-65 Chain)

### Bug A: US H&P Japanese Contamination

**現象**: US p=10k cohort の全 ADMISSION_HP の HPI + Physical Examination section が日本語で emit (4,507 doc)。

**根因**: `narrative/template_generator.py` の複数 builder が `_ja` field を unconditional access。
Disease YAML の narrative field(hpi_en / physical_examination_en)が未 populate → ja fallback → US cohort silently ja 化。

**修正**: `_pick_localized(tmpl, key_base, lang) -> str` helper で lang dispatch、片方 missing なら explicit warn log + empty string。
全 32 disease YAML の narrative field audit + missing en 補填。

### Bug B: Nurse Notes に Physician が author

**現象**: LOINC 34746-8 (NURSING_SHIFT_NOTE) + 78390-2 (ADMISSION_NURSING_ASSESSMENT) +
34119-8 (NURSING_DISCHARGE_SUMMARY) 全て `author = attending_physician_id` (23,279 doc)。
primary_nurse_id 無視 → α-min-2 nursing_assignment enricher との author mismatch。

**修正**: `_pick_document_author(spec, encounter) -> str` helper で nursing LOINC 判定 → nursing 時は
primary_nurse_id 優先。4 branch 内の hardcoded attending_id 直接使用を全て helper 経由に置換。

## 関連

- 設計: `docs/superpowers/specs/2026-07-02-tier1-3-narrative-stage2-architecture-design.md` (AD-65)
- 仕様: `docs/spec/tier1-document-density-alpha-min-1-spec.md`
- マスタープラン: `docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`
- DESIGN.md (AD-55, AD-62, AD-63, AD-65)
