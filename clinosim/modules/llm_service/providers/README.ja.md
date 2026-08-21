# `clinosim.modules.llm_service.providers` — LLM provider プラグイン registry

## 概要

[`clinosim.modules.llm_service`](../README.md) が dispatch する具体的
LLM backend 群。各 provider は `LLMProvider` Protocol を実装しており
`LLMService` は config だけで backend を差し替えられる (AD-11 /
AD-24)。親パッケージが orchestration (prompt cache、cost accounting、
task-type dispatch) を所有、本 subpackage は実装 + registry を所有する。

## Scope

- **In scope**: `LLMProvider` Protocol (`base.py`)、`ProviderResponse`
  dataclass、bundle されている 5 provider 実装 (`mock`、
  `ollama` + `local` alias、`bedrock`、`vllm` + `openai_compatible`
  alias)、`_REGISTRY` mapping、plug-in 面
  (`register_provider` + `build_provider`)。
- **Out of scope**: prompt template、response caching、task-type
  dispatch、LOINC mapping — 全て
  [`clinosim.modules.llm_service`](../README.md) 上位。

## Public API

```python
from clinosim.modules.llm_service.providers import (
    LLMProvider,             # Protocol
    ProviderResponse,        # dataclass (text, input_tokens, output_tokens, model, latency_ms, metadata)
    MockProvider,            # 決定論的、I/O 無し (test + template-free dry run)
    OllamaProvider,          # local self-hosted model (HTTP API)
    BedrockProvider,         # AWS Bedrock Converse API 経由
    VLLMProvider,            # vLLM + 任意の OpenAI-compatible endpoint
    build_provider,          # (provider_name, provider_config) -> provider instance
    register_provider,       # (name, builder_callable) -> None (third-party 拡張)
)
```

Registry (`__init__.py` の `_REGISTRY`) が config section 名 →
provider builder を map:

| Config 名 | Builder |
|---|---|
| `mock` | `MockProvider(cfg)` |
| `ollama` | `OllamaProvider(cfg)` |
| `local` | `OllamaProvider(cfg)` (alias) |
| `bedrock` | `BedrockProvider(cfg)` |
| `vllm` | `VLLMProvider(cfg)` |
| `openai_compatible` | `VLLMProvider(cfg)` (alias) |

`anthropic_direct` は bundle されていない — third-party code が
`register_provider("anthropic_direct", builder)` で登録できる。

## 決定論

- `MockProvider` は完全決定論的 (prompt hash / manifest lookup に
  基づく canned text を返す)。`call_count`、`last_prompt`、`last_model`
  を記録し test が assert できる。
- 3 network provider は設定 `temperature=0` かつ backend が同 model
  version を serve するときのみ決定論的。親層の `PromptCache` は
  content-addressed なので、両条件が揃えば再実行間の byte-identity を
  cache 経由で復元する。

## 依存

- `base.py` + `mock.py` + `__init__.py` は標準ライブラリのみ。
- `boto3` — `bedrock.py` で lazy import
  (`BedrockProvider.__init__` 内で `import boto3`)。Bedrock を使わない
  host では clinosim boot に AWS SDK が要らない。
- `httpx` — `ollama.py` + `vllm.py` の HTTP 呼び出しに必須。
- 他の `clinosim.modules.*` に依存しない。`llm_service` 上位にも
  依存しない (pure implementation 層)。

## 定数と設定

- **`LLMProvider` Protocol** (`base.py`) — `@runtime_checkable`、
  method 1 つ `complete(prompt, model, max_tokens, system_prompt,
  temperature, stop_sequences) -> ProviderResponse`。実装は error 時に
  raise、caller (`LLMService`) が retry / fallback / cost tally を扱う。
- **`ProviderResponse` field** — `text`, `input_tokens`,
  `output_tokens`, `model`, `latency_ms`, `metadata`
  (`dict[str, Any] | None`、provider 固有 field 例: stop reason、
  safety flag、cost 見積り)。
- **Provider 別 config shape** — 各 provider の `__init__(cfg: dict)`
  が消費する config key を docstring で示す。詳細は `bedrock.py`,
  `ollama.py`, `vllm.py`, `mock.py` を参照。

## ディレクトリ構造

```
clinosim/modules/llm_service/providers/
  __init__.py                    registry + build_provider + register_provider
  base.py                        LLMProvider Protocol + ProviderResponse
  mock.py                        MockProvider — 決定論的、I/O 無し
  ollama.py                      OllamaProvider — local Ollama HTTP API
  bedrock.py                     BedrockProvider — AWS Bedrock Converse API (lazy boto3)
  vllm.py                        VLLMProvider — vLLM + 任意の OpenAI-compatible endpoint
```

**`audit.py` / `enricher.py` / `reference_data/` は存在しない** —
data (prompt + config) は上位 `clinosim.modules.llm_service` にある。

## Enricher 配線

該当なし — leaf library の subpackage。`register_builtin_enrichers`
に登録なく seed offset も無い。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| `LLMService` 構築 | [`clinosim/modules/llm_service/factory.py`](../factory.py) | `_build_provider_from_section` → `build_provider(name, cfg)`。 |
| Package 再 export | [`clinosim/modules/llm_service/__init__.py`](../__init__.py) | `LLMProvider`, `ProviderResponse`, `MockProvider` が親 package root で再 export。 |
| Third-party 拡張 | (user code) | `register_provider(name, builder)` で本 file を編集せず custom provider を追加できる。 |

## テスト

Provider 固有の unit test は `tests/unit/` 配下の `llm_service` test
と同居し、多くは `MockProvider` を直接 instantiate して I/O-free に
保たれる。network provider (Bedrock / Ollama / vLLM) 別の専用 test
file は無く、`--llm-config` を差し替えた narrative pass 経由で
end-to-end に動作を確認する。

**coverage gap**: provider 別 unit test (config parsing、error
translation、retry 意味論) は低コストの follow-up。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
