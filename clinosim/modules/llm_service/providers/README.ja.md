# `clinosim.modules.llm_service.providers` — LLM プロバイダ プラグイン registry

## 目的

[`clinosim.modules.llm_service`](../README.ja.md) が narrative 生成で
ディスパッチする backend 群。全プロバイダは
[`LLMProvider` Protocol](base.py) を実装するため、`LLMService` は
config のみで backend を差し替え可能 (AD-11 / AD-24)。

親パッケージがオーケストレーション (prompt cache、cost accounting、
fallback 順、response-format 処理) を担い、本サブパッケージは
プロバイダ実装と、config 名 → インスタンス化子への registry を担う。

## スコープ

- **In scope**: `LLMProvider` Protocol、`ProviderResponse` dataclass、
  同梱 4 プロバイダ (`mock`, `ollama`, `bedrock`, および `ollama` の
  alias である `local`)、`_REGISTRY` / `register_provider` /
  `build_provider` のプラグイン surface。
- **Out of scope**: prompt テンプレート、layer-2 ディスクキャッシュ、
  per-run コスト集約 — これらは
  [`clinosim.modules.llm_service`](../README.ja.md) 側。

## 同梱プロバイダ

| ファイル | 登録名 | 役割 |
| --- | --- | --- |
| `mock.py` | `mock` | 決定論的な固定応答を返す。テスト・テンプレート抜きの dry-run 用。ネットワーク I/O なし。`call_count` / `last_prompt` / `last_model` を記録しアサーション可能。 |
| `ollama.py` | `ollama`, `local` | [Ollama](https://ollama.com/) HTTP API 経由でローカル self-hosted モデルを呼ぶ。開発時のデフォルト。config: `endpoint` (デフォルト `http://localhost:11434`)、`model` (デフォルト `llama3.1:8b`)。 |
| `bedrock.py` | `bedrock` | AWS Bedrock を Converse API 経由で呼ぶ (Claude / Llama / Mistral を uniform)。`boto3` は遅延 import — Bedrock を使わないホストで AWS SDK を要求しない。config: `region`, `profile` (または AWS のデフォルト認証チェーン)、`model_id`、クロスリージョン inference profile 用の任意 `inference_profile_arn`。 |

全プロバイダで共有するインターフェイス + レスポンス型:

- `base.LLMProvider` — `@runtime_checkable` Protocol。
  `complete(prompt, model, max_tokens, system_prompt, temperature, stop_sequences)`
  1 メソッド。実装はエラー時に例外送出、呼び出し側 (`LLMService`)
  が retry / fallback / コスト集計を担う。
- `base.ProviderResponse` — 統一 dataclass: `text`, `input_tokens`,
  `output_tokens`, `model`, `latency_ms`, `metadata` (stop 理由 /
  safety フラグ / コスト見積など、プロバイダ固有の任意フィールド)。

## Registry API

Registry は config 名 → builder callable (config `dict` を受け取り
プロバイダインスタンスを返す) のマップ:

```python
_REGISTRY: dict[str, Callable[[dict[str, Any]], Any]] = {
    "local":   lambda cfg: OllamaProvider(cfg),
    "ollama":  lambda cfg: OllamaProvider(cfg),
    "bedrock": lambda cfg: BedrockProvider(cfg),
    "mock":    lambda cfg: MockProvider(cfg),
}
```

`build_provider(provider_name, provider_config)` を `LLMService` が
起動時に呼ぶ。未登録名は現在の登録集合を列挙した `ValueError` を送出。

## 独自プロバイダの追加 (ship your own)

third-party やユーザーコードは、同梱 `__init__.py` を編集せず実行時に
registry を拡張できる:

```python
from typing import Any
from clinosim.modules.llm_service.providers import (
    ProviderResponse,
    register_provider,
)


class MyCustomProvider:
    """base.LLMProvider Protocol を満たすクラスならば ABC 継承不要 (structural typing)。"""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def complete(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 1000,
        system_prompt: str = "",
        temperature: float = 0.4,
        stop_sequences: list[str] | None = None,
    ) -> ProviderResponse:
        # ...backend を呼び、ProviderResponse を返す
        return ProviderResponse(text="...", output_tokens=42, model=model or "mine")


register_provider("my_custom", lambda cfg: MyCustomProvider(cfg))
```

登録後は同梱プロバイダと全く同じ形で `LLMService` config から選択可能:

```yaml
# clinosim/config/llm_service.my_custom.yaml
provider: my_custom
provider_config:
  api_key_env: MY_CUSTOM_API_KEY
  # ...
```

Protocol は structural (`@runtime_checkable`) なので `LLMProvider` を
継承する必要はなく、メソッドシグネチャ一致で十分。

## 相互参照

- 親オーケストレータ: [`clinosim.modules.llm_service`](../README.ja.md)
- Narrative の消費者:
  [`clinosim.modules.document.narrative`](../../document/narrative/README.ja.md)
- AWS Bedrock セットアップ手順: [`docs/bedrock_setup.md`](../../../../docs/bedrock_setup.md) (英語)
- プロバイダ config ファイル: `clinosim/config/llm_service.<name>.yaml`
