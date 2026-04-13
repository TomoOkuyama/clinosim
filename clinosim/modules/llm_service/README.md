# clinosim.modules.llm_service — Centralized LLM Service

## 目的

clinosim 内の **臨床文書ナラティブ生成の単一エントリポイント** を提供する (AD-11)。

**5種類の必須文書のみ対応** (LOINC 準拠):
- **34117-2**: Admission H&P (全入院)
- **18842-5**: Discharge Summary (全退院)
- **11504-8**: Operative Note (手術)
- **28570-0**: Procedure Note (侵襲的 bedside 処置)
- **69730-0**: Death Note (死亡退院)

他のモジュール (output 等) は LLM API を直接呼ばず、 必ず本サービス経由でテキスト生成を依頼する。 これにより:

- LLM プロバイダ (Ollama, Bedrock, Anthropic) を 1 箇所で切り替え可能
- プロンプトテンプレートが集中管理され、 監査・改善が容易
- LLM 障害時の **自動 template フォールバック** で simulation を止めない
- コスト/トークン使用量を集中計測

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **Single point of LLM access (AD-11)** | 他モジュールから LLM SDK (`anthropic`, `boto3` 等) を直接 import しない |
| 2 | **Modules never write prompts** | 呼び出し側は構造化された `ClinicalEventData` を渡すのみ。 プロンプト構築は本モジュール内で行う |
| 3 | **Mode hierarchy** | `none` < `template` < `llm`。 LLM 失敗時は自動的に template にフォールバック |
| 4 | **5 document types only** | LOINC 準拠の5種類のみ生成。経過記録・看護記録等は含まない（トークン削減） |
| 5 | **Deterministic-friendly** | mode=`none`/`template` ではネットワーク呼び出しゼロ → 完全再現可能 |

## ディレクトリ構造

```
clinosim/modules/llm_service/
├── __init__.py
├── README.md              # 本ドキュメント
├── SPEC.md
├── engine.py              # LLMService (generate entry point, template fallbacks)
├── factory.py             # build_from_config_file() — YAML → LLMService
├── prompt_registry.py     # PromptRegistry (YAML prompt loading + rendering)
├── cache.py               # PromptCache (SHA256 disk cache, AD-41)
├── providers/             # LLM provider plugin subpackage (AD-39)
│   ├── __init__.py        # Provider registry + build_provider()
│   ├── base.py            # LLMProvider Protocol
│   ├── ollama.py          # OllamaProvider (local HTTP)
│   ├── bedrock.py         # BedrockProvider (AWS Converse API)
│   └── mock.py            # MockProvider (deterministic test)
└── prompts/               # Per-language prompt YAML templates (AD-40)
    ├── en/                # English (5 files)
    └── ja/                # Japanese (5 files, AD-43)
```

## 動作モード

| Mode | LLM 呼び出し | 用途 |
|---|---|---|
| `"none"` | 行わない (空 LLMResponse 返却) | narrative を生成しない |
| `"template"` | 行わない (Python テンプレートで生成) | デフォルト・CI・確定的テスト |
| `"llm"` | 実際にプロバイダを呼ぶ (失敗時 template fallback) | 高品質ノート生成 |

## API リファレンス

### `LLMService`

```python
class LLMService:
    def __init__(
        self,
        mode: str = "none",
        narrative_provider: Any = None,
        narrative_model_map: dict[str, str] | None = None,
    ) -> None: ...

    def generate(
        self, task_type: LLMTaskType, event: ClinicalEventData
    ) -> LLMResponse: ...

    def cost_report(self) -> dict: ...
```

`generate()` がモジュール側からの唯一のエントリ。 task type に応じて JUDGMENT/NARRATIVE のカテゴリが決まり、 適切な provider と言語が選択される。

```python
from clinosim.modules.llm_service.engine import (
    LLMService, LLMTaskType, ClinicalEventData, PatientSummary,
)
from clinosim.modules.llm_service.providers import OllamaProvider

# Local Ollama for narratives, no JUDGMENT yet
narrative = OllamaProvider({"endpoint": "http://localhost:11434",
                            "model": "llama3.1:8b"})

llm = LLMService(
    mode="llm",
    narrative_provider=narrative,
    narrative_model_map={"medium": "llama3.1:8b"},
)

ps = PatientSummary(age=72, sex="M", country="JP",
                    chief_complaint="発熱と咳", current_diagnosis="細菌性肺炎",
                    hospital_day=3, department="internal_medicine")
ev = ClinicalEventData(patient_summary=ps,
                       event_data={"vitals": {"temperature": "37.8"},
                                   "key_labs": {"CRP": "8.2"}},
                       language="ja")

resp = llm.generate(LLMTaskType.PROGRESS_NOTE, ev)
print(resp.text, resp.source)  # source: "llm" | "template" | "none"
```

### `LLMTaskType` — タスク種別（5種類のみ）

| LOINC | TaskType | 説明 | 生成条件 |
|---|---|---|---|
| 34117-2 | `ADMISSION_HP` | 入院時 H&P | 全入院 |
| 18842-5 | `DISCHARGE_SUMMARY` | 退院時サマリー | 全退院 |
| 11504-8 | `OPERATIVE_NOTE` | 手術記録 | 手術 (hip fracture 等) |
| 28570-0 | `PROCEDURE_NOTE` | 処置記録 | 侵襲的 bedside 処置 (central line, intubation 等) |
| 69730-0 | `DEATH_NOTE` | 死亡診断書 | 死亡退院 |

### `OllamaProvider`

ローカル Ollama サーバへの HTTP クライアント。 デフォルトで `http://localhost:11434` の `/api/generate` を叩く。

```python
class OllamaProvider:
    def __init__(self, config: dict[str, Any] | None = None) -> None: ...
    def complete(
        self, prompt: str, model: str | None = None,
        max_tokens: int = 1000, system_prompt: str = "",
    ) -> ProviderResponse: ...
    def health_check(self) -> bool: ...
    def list_models(self) -> list[str]: ...
```

エラーハンドリング:

- `httpx.ConnectError` → `ConnectionError("Cannot connect to Ollama at ...")` (Ollama サーバ未起動)
- `404` → `RuntimeError("Model 'X' not found in Ollama")` (モデル未 pull)
- その他 HTTP エラー → 再 raise

`LLMService._llm_generate()` はこれらの例外を 3 回までリトライ (1s, 2s, 3s 待機) し、 全失敗時に template フォールバックする。

```python
provider = OllamaProvider({"endpoint": "http://localhost:11434",
                           "model": "llama3.1:8b"})
if provider.health_check():
    print("Available models:", provider.list_models())
```

### `BedrockProvider`

Amazon Bedrock 経由で Claude モデルを使用。 boto3 クライアントで Bedrock Runtime API を呼び出す。

```python
class BedrockProvider:
    def __init__(self, config: dict[str, Any] | None = None) -> None: ...
    def complete(
        self, prompt: str, model: str | None = None,
        max_tokens: int = 1000, system_prompt: str = "",
    ) -> ProviderResponse: ...
    def health_check(self) -> bool: ...
```

必要な依存:

```bash
pip install boto3
```

AWS 認証情報の設定 (いずれか):

1. AWS CLI: `aws configure`
2. 環境変数: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`
3. IAM ロール (EC2/ECS で実行時)
4. AWS プロファイル: config に `profile_name` 指定

必要な IAM 権限:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "bedrock:InvokeModel",
    "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-*"
  }]
}
```

エラーハンドリング:

- `ImportError` → `RuntimeError("boto3 is required...")` (boto3 未インストール)
- `ValidationException` → `ValueError("Invalid request...")` (リクエスト不正)
- `ModelNotReadyException` → `RuntimeError("Model not ready...")` (モデル未利用可能)
- `ThrottlingException` → `RuntimeError("API throttling...")` (レート制限)

```python
from clinosim.modules.llm_service.providers import BedrockProvider

provider = BedrockProvider({
    "region": "us-east-1",
    "model": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    # "profile_name": "default"  # optional
})

if provider.health_check():
    resp = provider.complete("Write a brief chief complaint.", max_tokens=200)
    print(resp.text)
```

対応モデル (2026年4月時点):

| Model ID | 名称 | 用途 |
|---|---|---|
| `us.anthropic.claude-sonnet-4-20250514-v1:0` | Claude Sonnet 4 | 推奨 (on-demand inference profile) |
| `us.anthropic.claude-opus-4-20250514-v1:0` | Claude Opus 4 | 最高品質 |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Claude Haiku 4.5 | 高速・低コスト |

**注意**: Bedrock on-demand throughput では `us.` プレフィックス（inference profile）が必要。

### `MockProvider`

テスト用の確定的プロバイダ。 LLM 呼び出しなしで `[Mock LLM response #N]` を返す。

```python
from clinosim.modules.llm_service.providers import MockProvider

llm = LLMService(mode="llm",
                 narrative_provider=MockProvider(),
                 narrative_model_map={"medium": "mock"})
```

### `cost_report() -> dict`

```python
{
    "total_calls": 42,
    "total_input_tokens": 8700,
    "total_output_tokens": 4200,
    "fallback_count": 1,        # template にフォールバックした回数
}
```

## データ構造

### `PatientSummary`

```python
@dataclass
class PatientSummary:
    age: int = 0
    sex: str = ""
    country: str = ""
    chief_complaint: str = ""
    relevant_conditions: list[str] | None = None  # 既往
    current_diagnosis: str = ""
    diagnosis_confidence: float = 0.0
    hospital_day: int = 0
    department: str = ""
```

LLM context として渡す **コンパクトな患者要約**。 個別の lab 値や時系列は `event_data` 側に入れる。

### `ClinicalEventData`

```python
@dataclass
class ClinicalEventData:
    patient_summary: PatientSummary
    event_data: dict[str, Any]   # vitals / labs / decision context
    language: str = "ja"
```

呼び出し元はこのオブジェクトを渡すだけ。 プロンプト文字列は構築しない。

### `LLMResponse`

```python
@dataclass
class LLMResponse:
    text: str | None = None
    source: str = "none"          # "llm" | "template" | "cache" | "none"
    model: str | None = None
    chosen_option: str | None = None
    reasoning: str | None = None
```

### `ProviderResponse`

```python
@dataclass
class ProviderResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    latency_ms: int = 0
```

## プロンプト構築 (engine.py 内)

`_build_prompt(task_type, event, language)` がタスク種別ごとに system prompt と user prompt を組み立てる。 抜粋:

```python
case LLMTaskType.PROGRESS_NOTE:
    system = (
        f"You are a physician writing a daily progress note. "
        f"Use SOAP format. Be concise. {lang_instruction}"
    )
    user = (
        f"Patient: {ps.age}yo {ps.sex}, Hospital Day {ps.hospital_day}\n"
        f"Diagnosis: {ps.current_diagnosis}\n"
        f"Vitals: {ed.get('vitals', {})}\n"
        f"Key labs: {ed.get('key_labs', {})}\n"
        f"Write the progress note."
    )
```

`lang_instruction` は `language="ja"` なら "Write in Japanese..."、 `"en"` なら "Write in English..."。 JUDGMENT カテゴリのタスクは `language` パラメータを無視して常に英語で生成する (AD-24)。

## 使用例

### Narrative 生成 (template モード — LLM なし)

```python
llm = LLMService(mode="template")
resp = llm.generate(LLMTaskType.DISCHARGE_SUMMARY, ev)
# resp.source == "template"
# resp.text == "【退院時サマリー】\n患者: 72歳 M\n入院期間: 14日間\n..."
```

### LLM モード + コスト追跡

```python
llm = LLMService(mode="llm", narrative_provider=OllamaProvider(),
                 narrative_model_map={"medium": "llama3.1:8b"})

for patient_event in events:
    llm.generate(LLMTaskType.PROGRESS_NOTE, patient_event)

print(llm.cost_report())
# {'total_calls': 30, 'total_input_tokens': 4500,
#  'total_output_tokens': 2100, 'fallback_count': 0}
```

### Bedrock で高品質な narrative 生成

```python
from clinosim.modules.llm_service.providers import BedrockProvider

llm = LLMService(
    mode="llm",
    narrative_provider=BedrockProvider({
        "region": "us-east-1",
        "model": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    }),
    narrative_model_map={"medium": "us.anthropic.claude-sonnet-4-20250514-v1:0"},
)

# 手術記録生成
event = ClinicalEventData(
    patient_summary=patient,
    event_data={
        "procedure_type": "ORIF",
        "anesthesia_type": "general",
        "duration_minutes": 120,
        "estimated_blood_loss_ml": 450,
    },
    language="ja",
)
response = llm.generate(LLMTaskType.OPERATIVE_NOTE, event)
print(response.text)  # Bedrock Claude で生成された手術記録
```

## セットアップ

### オプション1: Ollama (デフォルト・ローカル)

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# サーバ起動
ollama serve

# 推奨モデルを pull
ollama pull llama3.1:8b
```

設定ファイル: `clinosim/config/llm_service.yaml`

### オプション2: Amazon Bedrock (推奨・本番環境)

```bash
# boto3 インストール
pip install boto3

# AWS 認証設定 (いずれか)
aws configure                     # 対話式設定
# または環境変数
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=us-east-1
```

設定ファイル: `clinosim/config/llm_service.bedrock.yaml`

IAM ポリシー例:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "bedrock:InvokeModel",
    "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-*"
  }]
}
```

利用可能リージョン: `us-east-1`, `us-west-2`, `ap-northeast-1` (東京), `eu-west-3` 等。 詳細は [Bedrock ドキュメント](https://docs.aws.amazon.com/bedrock/)。

### オプション3: Anthropic API 直接

設定ファイル: `clinosim/config/llm_service.cloud.yaml` (要 `ANTHROPIC_API_KEY` 環境変数)

## 依存関係

| 依存 | 用途 | 必須? |
|---|---|---|
| `httpx` | Ollama 通信 | Ollama 使用時 |
| `boto3` | Amazon Bedrock 通信 | Bedrock 使用時 |
| `numpy` | 間接 (simulation 全般) | 常時 |

外部依存ゼロでテスト可能 (`MockProvider` 使用時)。

本モジュールは clinosim の他モジュールに **依存しない**。 逆に他モジュール (output/narrative_generator, encounter 等) が本モジュールに依存する。

## 権威ソース

| プロバイダ | ドキュメント |
|---|---|
| Ollama | [ollama.com](https://ollama.com) / [API リファレンス](https://github.com/ollama/ollama/blob/main/docs/api.md) |
| Anthropic API | [docs.anthropic.com](https://docs.anthropic.com/) |
| llama.cpp / GGUF | [llama.cpp](https://github.com/ggerganov/llama.cpp) |

## トークン消費見積もり（日本語出力の場合）

| Document Type | 平均 Input | 平均 Output | 合計 | 頻度（60k catchment, 1年） |
|---|---|---|---|---|
| Admission H&P | ~800 | ~2,500 | ~3,300 | 171 |
| Discharge Summary | ~1,200 | ~3,500 | ~4,700 | 171 |
| Operative Note | ~600 | ~2,000 | ~2,600 | 11 |
| Procedure Note | ~400 | ~1,000 | ~1,400 | 19 |
| Death Note | ~300 | ~800 | ~1,100 | 2 |
| **合計** | | | **~1.8M tokens** | **374 documents** |

経過記録・看護記録を含めると **50倍以上** になるため、5種類のみに限定。

## 既知の制約・今後

- ✅ SHA256 レスポンスキャッシュ実装済 (`cache.py`, AD-41)
- ✅ YAML プロンプトテンプレート実装済 (`prompt_registry.py`, AD-40)
- ✅ 日本語プロンプト 5 種類実装済 (AD-43)
- ストリーミング非対応 (1 リクエスト = 1 完全レスポンス)
- AnthropicProvider (直接API) は未実装 (Bedrock 経由を推奨)
- OpenAI-compatible provider (LiteLLM / vLLM) は未実装
- Bedrock Prompt Caching (server-side) は未対応
