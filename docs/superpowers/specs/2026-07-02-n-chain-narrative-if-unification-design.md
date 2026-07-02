# N-chain: Narrative Interface Unification — Design Spec

**Date:** 2026-07-02(session 31)
**Status:** Approved for implementation
**Branch:** `feature/n-chain-narrative-if-unification`
**Source findings:** `docs/design-notes/2026-07-02-grand-design-review-and-roadmap.md` §3.1 +
TODO.md § "N-chain" + interface recon (session 31)

## 1. Problem

Stage 2 narrative generation has ONE live path (`narrate --provider template` →
`TemplateNarrativePass` → hardcoded `TemplateNarrativeGenerator`) and TWO dormant subsystems
that do not compose:

| | narrative-side α-min-1 machinery | `llm_service` |
|---|---|---|
| Files | `llm_generator.py` / `replacement_strategy.py` / `cache.py` | `engine.py` / `factory.py` / `providers/` / `prompt_registry.py` / `cache.py` |
| Provider protocol | `LLMProvider.generate(prompt) -> str` | `LLMProvider.complete(...) -> ProviderResponse` |
| Output type | `NarrativeOutput` | `LLMResponse` |
| Production callers | 0(`__init__` re-export のみ) | 0(comment 参照のみ) |
| Tests | 34(MagicMock provider) | 29(MockProvider)— 両者を跨ぐ test 0 |

`DocumentTypeSpec.stage2_strategy` / `llm_enabled_sections` は片側でしか読まれず dead。
`CLINOSIM_NARRATIVE_LLM` env gate は隠し switch(silent-no-op class)。
`DocumentType`(9)と `LLMTaskType`(12)は 3 値しか重ならず sync 機構なし。
`llm_service/__init__.py` は空(public API surface 規約違反)。

## 2. Decision summary

**WIRE, not delete.** α-min-1 機構は master plan §3 の推奨戦略(D template-as-seed + E cache +
B section-level)の実装そのものなので、`NarrativePass` 配下に接続して生かす。LLM 呼出しは
`LLMService` の新 public API 1 本(`complete_prompt`)経由に統一し(AD-11 構造保証、retry /
PromptCache / cost 集計を無償で獲得)、narrative 側の独自 `LLMProvider` protocol は削除する。

## 3. N-1: Generator contract + injection + LLMNarrativePass

- **`NarrativeGenerator` Protocol** を `clinosim/types/document.py` に定義:
  `generate(ctx: NarrativeContext, spec: <DocumentTypeSpec>) -> NarrativeOutput`。
  spec 型は可能なら `DocumentTypeSpec` を `clinosim/types/document.py` へ移設して full-typed に
  (types 規約準拠。`registry.py` は loader + 後方互換 re-export を維持)。循環 import が
  発生する場合の fallback = Protocol 上は `Any` + docstring 指定(移設は独立 TODO 化)。
- **constructor 注入**: `NarrativePass.__init__(..., generator: NarrativeGenerator)` を base に
  持ち上げ、base の `_generate` default 実装 = `self.generator.generate(ctx, spec)`。
  `TemplateNarrativePass(generator=None)` は default で `TemplateNarrativeGenerator()`。
  既存挙動 byte-identical(template 経路の出力不変が本 chain の最重要 invariant)。
- **`LLMNarrativePass(NarrativePass)` 新設**(scaffold の wire):
  - generator = `LLMNarrativeGenerator(template_generator, llm=<LLMService>, cache=NarrativeCache)`
  - `_generator_name()` = `f"llm-{provider_name}"`、`_generator_config()` = model map 等
  - manifest `llm_cost_report` に `LLMService.cost_report()` を配線
  - walk order は base 継承(prompt cache friendly、変更禁止)
- **CLI**: `narrate --provider bedrock|ollama` の `NotImplementedError` を撤去し、
  `config/llm_service.bedrock.yaml` 等から `build_from_config_file` で `LLMService` を構築して
  `LLMNarrativePass` を起動。`--provider mock` を choices に追加(dev/test 用、MockProvider)。
  `--llm-config PATH` optional arg(default = provider に応じた config/llm_service*.yaml)。
- **`CLINOSIM_NARRATIVE_LLM` env gate は削除**: opt-in は CLI `--provider` の明示選択が担う。
  `LLMNarrativeGenerator` の分岐は「llm 未構成 → template_fallback(WARN)/ 構成済 →
  apply_replacement_strategy / 例外 → template_fallback(WARN)」の 3 経路に簡素化。

## 4. N-2: Provider protocol unification

- `replacement_strategy.LLMProvider`(`generate(prompt)->str`)を **削除**。
- **`LLMService.complete_prompt(system: str, user: str, *, language: str,
  task_type: LLMTaskType, max_tokens: int | None = None, temperature: float | None = None)
  -> LLMResponse`** を新設 — 事前構築 prompt を retry / PromptCache / token 集計 /
  template-fallback なしの raw 経路で実行する唯一の低レベル public API
  (fallback は呼び手 = `LLMNarrativeGenerator` の責務)。
- `apply_replacement_strategy(..., llm: LLMService, task_type, language, ...)` に signature 変更。
  section 置換は `llm.complete_prompt(...).text`。`NarrativeCache`(in-memory、
  disease/archetype/day/severity/demographics/lang/section key)は cross-patient 再利用の
  第 1 層として維持、`PromptCache`(disk、prompt-hash key)は第 2 層(両立、重複ではない —
  役割を docstring に明記)。

## 5. N-3: Prompt ownership + enum sync + public API

- `_build_seed_prompt` の inline 組立てを削除し、**`prompts/{en,ja}/narrative_seed.yaml`** を
  新設(既存 schema: task_type/version/max_tokens/temperature/system/user_template、
  variables = section / template_text 等)。`replacement_strategy` は `PromptRegistry.get(
  "narrative_seed", language).render(...)` で取得。ja は既存 ja prompt の書式規約
  (【】/■/・)に従う。
- **enum sync**: `LLMTaskType` に α-min-2/3 の 6 doc type(admission_nursing_assessment /
  nursing_shift_note / nursing_discharge_summary / outpatient_soap / ed_note / ed_triage_note)
  を追加し、coarse `NURSING_NOTE` は削除(consumer は TASK_CATEGORY/DOCUMENT_LOINC map のみ)。
  **import-time validation** を追加: `{d.value for d in DocumentType} ⊆
  {t.value for t in LLMTaskType if TASK_CATEGORY[t] is NARRATIVE}`(canonical-constants
  pattern、破ると ImportError)。逆方向(death_summary 等の LLMTaskType-only)は将来 phase の
  予約として許容。TASK_CATEGORY / DOCUMENT_LOINC へ新 6 値のエントリ追加
  (LOINC は document_type_specs.yaml と一致させ、値の二重管理は cross-validation test で pin)。
- **`llm_service/__init__.py` public API export**: `LLMService` / `LLMTaskType` /
  `LLMTaskCategory` / `LLMResponse` / `ClinicalEventData` / `PatientSummary` /
  `build_from_config` / `build_from_config_file` / `LLMProvider` / `ProviderResponse` /
  `MockProvider` / `PromptRegistry` / `PromptSpec` / `PromptCache`。

## 6. Out of scope(TODO 化)

- N-4 template_generator.py の section template YAML 化(段階的、別 chain)
- bedrock/ollama の実プロンプト品質チューニング + `<profile>.llm-<model>.golden.json`(β-JP-1)
- semantic diff mechanism(β-JP-1)
- `NarrativeContext` の disease_protocol/encounter_protocol None 配線(別 TODO)

## 7. Invariants / verification gates

1. **Template 経路 byte-identical**: `pytest -m regression`(6 goldens)不変 +
   3-stage pipeline byte-diff(narratives/ + FHIR NDJSON 一致)
2. unit / integration / e2e 全 green(orphan 機構の既存 34 tests は新 IF に移行)
3. **新 bridge test**: MockProvider → LLMService → LLMNarrativePass → narratives/<version>/
   round-trip(CLI `--provider mock` 経由の end-to-end 含む)+ template_seed 戦略で
   `llm_enabled_sections` のみ置換・他 section 不変・`facts_used`/raw_text 不変の pin
4. enum sync validation が import 時に発火することの negative test
5. ruff / mypy: 新規違反 0
