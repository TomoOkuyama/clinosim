# `clinosim.modules.llm_service` — 単一 LLM ゲートウェイ (AD-11)

## 概要

他モジュールが LLM 呼び出しに使う唯一のゲートウェイ (AD-11 —
「LLM 呼び出しは `llm_service` 経由のみ」、AD-24)。provider SDK
(Ollama / Bedrock / Anthropic / vLLM / mock) は他モジュールから
**直接呼ばれない**。task-type enum、prompt 構築、response 検証、
prompt cache、provider 選択を所有する。

## Scope

- **In scope**: `LLMService` (top-level orchestrator、sync +
  concurrency-safe な call 面)、`LLMTaskType` / `LLMTaskCategory`
  (StrEnum task 一覧)、`TASK_CATEGORY` (task → category map)、
  `DOCUMENT_LOINC` / `loinc_for(task_type)` (document 生成 task ごとの
  LOINC コード)、`PatientSummary` + `ClinicalEventData` (入力 DTO)、
  `LLMResponse` + `LLMCompletionError`、document-task validation
  (`_validate_document_task_sync`)、task 別 prompt builder
  (`_build_prompt` dispatch と言語別
  `_jp_chief_complaint`, `_en_chief_complaint`, `_progress_note`,
  `_discharge_summary`, `_admission_hp`, `_diagnostic_reasoning`,
  `_treatment_decision`, `_death_summary_template`,
  `_operative_note_template`, `_procedure_note_template`)、
  `PromptRegistry` + `PromptSpec` (task 別 prompt manifest)、
  `PromptCache` (再現性 + Stage 2 再実行の economy のための
  SHA-256 keyed disk cache)、`build_from_config` +
  `build_from_config_file` factory、`providers/` 配下の 6 provider。
- **Out of scope**: narrative content 組立 / template rendering
  ([`clinosim.modules.document.narrative`](../document/narrative/README.md)
  が 2-pass narrative を所有し `LLMService` を import する)、
  cost tracking / accounting、FHIR emission
  ([`clinosim.modules.output`](../output/README.md))。

## Public API

全 downstream module は package root から import する。下記 17
symbol が公開 surface の全て:

```python
from clinosim.modules.llm_service import (
    # Core
    LLMService,                  # top-level gateway (sync + concurrency-safe)
    LLMTaskType,                 # StrEnum task 一覧 (document + reasoning task ごと)
    LLMTaskCategory,             # StrEnum {"document", "reasoning", …}
    LLMResponse,                 # 正規化 response dataclass
    LLMCompletionError,          # RuntimeError subclass

    # Task metadata
    TASK_CATEGORY,               # {LLMTaskType: LLMTaskCategory}
    DOCUMENT_LOINC,              # {LLMTaskType: LOINC code}
    loinc_for,                   # (task_type) -> LOINC | None

    # 入力 DTO
    PatientSummary,
    ClinicalEventData,

    # Factory + registry
    build_from_config,           # (config_dict) -> LLMService
    build_from_config_file,      # (path) -> LLMService
    PromptRegistry,
    PromptSpec,
    PromptCache,

    # Provider 面 (providers/README.md 参照)
    LLMProvider,                 # Protocol
    ProviderResponse,            # dataclass
    MockProvider,                # test 用決定論的 fixture
)
```

## 決定論

- `LLMService.complete(...)` 経路は `PromptCache` 有効かつ underlying
  provider が `MockProvider` または `temperature=0` の実 provider
  のときに決定論的。cache key は
  `sha256(prompt + task_type + model + temperature + …)` で
  content-addressed。
- 並行安全: `LLMService` は各 provider 呼び出しに lock を用い、
  prompt / response state の interleave を防ぐ。
  `tests/unit/test_narrate_concurrency_byte_identity.py` が
  single-thread と 4-thread narrate の byte-identity 契約を pin する。
- Stage 2 再実行 economy: narrate 失敗後の同一 prompt は LLM を
  再呼び出しせず `PromptCache` が既 JSON entry を返す。on-disk 配置は
  [`cache.py`](cache.py) 参照 (`<cache_dir>/<sha256_prefix>/<sha256>.json`)。

## 依存

- `clinosim.modules.llm_service.providers` — `LLMProvider` Protocol
  と 5 concrete provider (bedrock / ollama / vllm / anthropic /
  mock)。
- Provider SDK (`llm_service` 自体ではなく各 provider file で遅延
  load): `boto3` (bedrock)、`httpx` (ollama + vllm + anthropic)。
- `hashlib.sha256` — cache key 導出。
- `yaml` — `factory.py` の config file loader。
- 他の `clinosim.modules.*` には依存しない (本モジュールは全 module が
  依存できる leaf)。

## 定数と設定

- **`LLMTaskType`** (StrEnum) — 完全な task 列挙
  (document 種別: `progress_note`, `admission_hp`,
  `discharge_summary`, `death_summary`, `operative_note`,
  `procedure_note`, `chief_complaint_jp`, `chief_complaint_en`、
  および reasoning task `diagnostic_reasoning`, `treatment_decision` 等)。
- **`TASK_CATEGORY`** — `{LLMTaskType: LLMTaskCategory}` mapping。
  caller が task list を hard-code せず category (document vs
  reasoning) で gate できる。
- **`DOCUMENT_LOINC`** — document 生成 task ごとの LOINC code。
  FHIR builder は `loinc_for(task_type)` で参照するため、新 document
  type は LOINC を 1 度だけ登録し全 consumer が同 map から lookup する。
- **Prompt manifest**: [`prompts/{en,ja}/`](prompts/) — 言語別
  prompt file を `PromptRegistry` が load。新言語追加は folder +
  `PromptSpec` entry を足すだけで engine code 変更不要。
- **Config schema** (`build_from_config` が消費):
  [`clinosim/types/config.py`](../../types/config.py) の
  `LLMProviderConfig` を参照。`provider` (`"bedrock_gateway" |
  "anthropic_direct" | "openai_compatible" | "local" | "none"`)、
  `mode` (`"llm" | "template" | "none"`)、`model_map` (`small` /
  `medium` / `large` → 実 model ID)、provider 別 config dict。

## ディレクトリ構造

```
clinosim/modules/llm_service/
  __init__.py                    公開 API surface (17 symbol)
  engine.py                      LLMService + task enum + prompt builder (900 LOC)
  factory.py                     build_from_config + build_from_config_file
  prompt_registry.py             PromptRegistry + PromptSpec
  cache.py                       PromptCache (SHA-256 keyed disk cache)
  prompts/
    en/                          英語 prompt manifest
    ja/                          日本語 prompt manifest
  providers/                     LLMProvider Protocol + 5 concrete provider (bedrock/ollama/vllm/anthropic/mock)
  SPEC.md                        拡張設計参考 (runtime data ではない)
```

**`audit.py` / `enricher.py` / `reference_data/` は存在しない**。

## Enricher 配線

該当なし — 本モジュールは narrative と CLI 経路から呼ばれる leaf
library。`register_builtin_enrichers` に登録なく、`ENRICHER_SEED_OFFSETS`
にも seed 未登録。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Narrative pass | [`clinosim/modules/document/narrative/llm_generator.py`](../document/narrative/llm_generator.py), [`replacement_strategy.py`](../document/narrative/replacement_strategy.py), [`passes.py`](../document/narrative/passes.py) | Stage 2 narrative 生成が document 種別ごとに `LLMService.complete(...)` を呼び出す。 |
| CLI `narrate` subcommand | [`clinosim/simulator/cli_narrate.py`](../../simulator/cli_narrate.py) | boot 時に `--llm-config` から `LLMService` を build、`NarrativePass` を invoke、`PromptCache` を配線。 |

## テスト

```bash
pytest tests/unit -k "llm" -q
```

個別ファイル:

- [`tests/unit/test_llm_service.py`](../../../tests/unit/test_llm_service.py)
  — `LLMService.complete` orchestration。
- [`tests/unit/test_llm_service_complete_prompt.py`](../../../tests/unit/test_llm_service_complete_prompt.py)
  — task-type 別 prompt-builder dispatch。
- [`tests/unit/test_llm_task_enum_sync.py`](../../../tests/unit/test_llm_task_enum_sync.py)
  — `LLMTaskType` ↔ `TASK_CATEGORY` ↔ `DOCUMENT_LOINC` の coverage
  invariant。
- [`tests/unit/test_llm_narrative_pass.py`](../../../tests/unit/test_llm_narrative_pass.py)
  — narrative-pass の `LLMService` 経由 integration。
- [`tests/unit/test_narrate_concurrency_byte_identity.py`](../../../tests/unit/test_narrate_concurrency_byte_identity.py)
  — 並行安全 (1-thread vs 4-thread narrate が同一出力)。
- [`tests/unit/test_clinical_documents.py`](../../../tests/unit/test_clinical_documents.py)
  — cross-module document emission guard。
- [`tests/fixtures/patient_profiles/`](../../../tests/fixtures/patient_profiles/)
  配下の fixture pack — `*.llm-expectations.yaml` +
  `*.llm-mock.golden.json` per-profile golden narrative (mock
  provider 用)。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
