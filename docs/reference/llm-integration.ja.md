<!-- README.md から抽出 (Issue #568 PR A)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# LLM 統合 (オプション)

clinosim は LLM を **臨床文書** (Stage 2) にのみ使用。全 structural
データ (labs、vitals、diagnoses、meds) は決定的で LLM を必要としない。

### アーキテクチャ

- 単一エントリポイント: `clinosim.modules.llm_service.LLMService`
  (AD-11)。他のモジュールが直接 LLM SDK を呼んではならない。
- 2 タスクカテゴリ (AD-13、AD-24):
  - **JUDGMENT** — 臨床推論、常に英語、structured 出力 (将来使用
    のために予約)。
  - **NARRATIVE** — 臨床文書、対象言語、free text。
- `clinosim.modules.llm_service.providers` 経由の pluggable
  provider:
  - `ollama` (alias `local`) — ローカル Ollama サーバ (`llm_service.yaml` の既定)
  - `bedrock` — AWS Bedrock、Converse API 経由 (EC2 デプロイ用)
  - `vllm` — OpenAI 互換 `/v1/chat/completions` エンドポイント
    (vLLM、SGLang、その他 OpenAI 互換サーバ; `clinosim narrate` の
    `--concurrency` で continuous batching)
  - `openai_compatible` — `vllm` の alias
  - `mock` — テスト用決定的 stub
  - 新規 provider は `providers.register_provider()` で登録可能。
- プロンプトテンプレートは
  `clinosim/modules/llm_service/prompts/<lang>/<task>.yaml` に YAML
  として配置、`string.Template` でレンダリング。
- 全レスポンスは再現性とコスト制御のため SHA256(system + user +
  model) で disk cache。

### ローカル Ollama (デフォルト)

```bash
brew install ollama
ollama serve
ollama pull llama3.1:8b

clinosim narrate --cif-dir ./output/cif --provider ollama \
  --llm-config clinosim/config/llm_service.yaml \
  --version-id ollama_en_v1
```

### AWS Bedrock (EC2)

```bash
pip install boto3   # bedrock runtime deps は clinosim の extras には含まれない

# bedrock:Converse を許可する IAM ロール付きの EC2 インスタンスで:
clinosim narrate --cif-dir ./cif --provider bedrock \
  --llm-config clinosim/config/llm_service.bedrock.yaml \
  --version-id bedrock_sonnet_en_v1
```

完全な EC2 + IAM セットアップは
[../bedrock_setup.ja.md](../bedrock_setup.ja.md) 参照。

### テンプレートモード (LLM なし)

```bash
clinosim narrate --cif-dir ./output/cif --version-id template_v1
```

テンプレートモードはネットワーク呼び出しなしで Stage 2 を実行し
決定的プレースホルダコンテンツを生成。`--provider` の既定は `template` なので、LLM を使うには `--provider` を明示する (`--llm-config` だけでは LLM は呼ばれない)。CI、再現性テスト、sanity
チェックに有用。

### 新規プロバイダへの拡張

```python
from clinosim.modules.llm_service.providers import register_provider

class MyProvider:
    def __init__(self, config): ...
    def complete(self, prompt, model, max_tokens, system_prompt, **kwargs): ...
    def health_check(self): return True

register_provider("my_provider", lambda cfg: MyProvider(cfg))
```

その後 `llm_service.yaml` で `provider: my_provider` を参照。`--llm-config` を渡すと `clinosim narrate` はその YAML から provider を構築する (`template` 以外の `--provider` 値なら LLM 経路) が、`register_provider()` は `narrate` 開始前に同一 Python プロセス内で実行されている必要がある — `--provider` フラグ自体は built-in 名しか受け付けない。

詳細: [../clinical_documents.ja.md](../clinical_documents.ja.md)、
`clinosim/modules/llm_service/README.ja.md`

---
