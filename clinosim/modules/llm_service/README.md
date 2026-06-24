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

本モジュールは clinosim の他モジュールに **依存しない**。

## Consumers

このモジュールに依存するもの:

| Caller | How | Impact |
|---|---|---|
| `modules/output/narrative_generator.py` | 退院サマリ・H&P 等の narrative 生成で LLM provider を呼出 | optional (narrative path) |
| `modules/output/document_generator.py` | clinical document (discharge / death / op note 等) 生成 | optional |
| `simulator/cli.py` | `--narrative` フラグ時に LLM service を起動 | optional (CLI) |
| `tests/e2e/test_narrative_generation.py` | narrative pipeline e2e test | guard |
| `tests/unit/test_clinical_documents.py` | document 生成 unit tests | guard |
| `tests/unit/test_llm_service.py` | provider + cache unit tests | guard |

## 権威ソース

| プロバイダ | ドキュメント |
|---|---|
| Ollama | [ollama.com](https://ollama.com) / [API リファレンス](https://github.com/ollama/ollama/blob/main/docs/api.md) |
| Anthropic API | [docs.anthropic.com](https://docs.anthropic.com/) |
| llama.cpp / GGUF | [llama.cpp](https://github.com/ggerganov/llama.cpp) |

## トークン消費・生成コスト見積もり（日本語出力）

> **実測** (2026-06-15): 人口 10,000 / 既定 50 床病院 (`hospital_operations.yaml`) / 1 年
> (start 2023-07-01 〜 snapshot 2024-06-30) / seed 42。
> **生成必要文書数は catchment 人口ではなく「病床数 × 期間」で律速** される
> (人口を増やしても入院は病床上限で頭打ち。同一 50 床なら 1 万人でも 6 万人でも同程度)。

| Document Type | 平均 Input | 平均 Output | 件数（実測） |
|---|---|---|---|
| Admission H&P | ~800 | ~2,500 | 491 |
| Discharge Summary | ~1,200 | ~3,500 | 491 |
| Operative Note | ~600 | ~2,000 | 39 |
| Procedure Note | ~400 | ~1,000 | 66 |
| Death Summary | ~300 | ~800 | 27 |
| **合計** | **≈ 1.04M** | **≈ 3.11M** | **1,114 documents (≈ 4.2M tokens)** |

経過記録・看護記録を含めると **50倍以上** になるため、5種類のみに限定。

### Bedrock 生成コスト（参考・オンデマンド us, 上記 1,114 文書 / 1 回フル生成）

| モデル | 単価 (in / out per 1M) | 概算コスト | 円 (¥150/$) |
|---|---|---|---|
| **Claude Sonnet 4**（既定 `medium`） | $3 / $15 | **≈ $50** | ≈ ¥7,500 |
| Claude Haiku 4.5（`small`） | $1 / $5 | ≈ $17 | ≈ ¥2,600 |
| Claude Opus 4（`large`） | $15 / $75 | ≈ $250 | ≈ ¥37,000 |

**前提・補足**:
- 上記 per-doc トークンは過去 Bedrock 実行ベースの目安。実出力長で **±数十%** の幅。
- **enrichment は非 LLM**（JUDGMENT 未実装）→ LLM 呼び出しは文書数 = **1,114** のみ。
- **SHA256 キャッシュ (AD-41)** で同一入力の再実行は無料。初回のみ全額。
- **Bedrock prompt caching 未対応**（対応すれば共通プロンプト分の input がさらに低減）。
- 参考タイミング（実測, 人口 1 万）: 構造データ生成 **≈ 109 秒** / テンプレートナラティブ生成 **≈ 4 秒**（LLM 不要）。
- 正確な実測は、Bedrock で数十件サンプル生成し各文書 JSON の `llm_input_tokens` / `llm_output_tokens` を集計すれば誤差数 % で得られる。

## Enrichment アーキテクチャ (AD-44)

A/B テストにより確認された原則:

- **Enrichment（LLM に渡す構造化データ）は言語中立（英語）** で統一
- LLM は `prompts/ja/*.yaml` の言語指示に従って翻訳出力
- **コード側で行うべき2項目のみ locale 依存**:
  1. `code_lookup(system, code, lang)` — 診断名の公式短縮形
  2. CRP mg/L→mg/dL 変換 — 数学的操作 (AD-42)
- 薬品名・手術名・合併症ラベル・イベント記述は **LLM に翻訳させる** (事前翻訳しない)

**根拠**: A/B テストで LLM (Claude Sonnet 4) の翻訳精度が事前翻訳と同等以上。
事前翻訳の問題点: CRP 単位変換エラー、ICD 正式名直訳の不自然さ。

## JP プロンプトのスタイルルール (AD-43)

日本語プロンプト (`prompts/ja/*.yaml`) の共通ルール:

- Markdown 記号 (`**`, `##`, `-`) 使用禁止
- セクション見出し: 【】 で囲む（例: 【主訴】、【現病歴】）
- 小見出し: ■ を使用（例: ■バイタルサイン）
- 箇条書き: ・を使用
- 医師名には必ず「医師」を付ける（例: 田中 太郎医師）
- 検査値の単位は入力データのまま使用（変換不要 — コード側で変換済み）

## 修正ガイド

### 新しい言語のプロンプトを追加する

1. `prompts/<lang>/` ディレクトリを作成
2. 5 つの YAML ファイルを作成 (`admission_hp.yaml`, `discharge_summary.yaml`, `death_summary.yaml`, `operative_note.yaml`, `procedure_note.yaml`)
3. 各ファイルの `system` セクションに言語指示を記載
4. `user_template` は `${variable_name}` プレースホルダで共通 (EN プロンプトからコピー可)
5. PromptRegistry は言語に対応する YAML を自動検出 (EN fallback あり)

### 新しい LLM プロバイダを追加する

1. `providers/` に新プロバイダクラスを作成 (`LLMProvider` Protocol 準拠)
2. `providers/__init__.py` の `_PROVIDERS` dict にエントリ追加
3. `clinosim/config/llm_service.<provider>.yaml` を作成
4. `factory.build_from_config_file()` が自動認識

### EC2 で Bedrock ナラティブを生成する

```bash
cd clinosim && source .venv/bin/activate
nohup ./scripts/full_run_ja.sh > /dev/null 2>&1 &  # JP
nohup ./scripts/full_run_us.sh > /dev/null 2>&1 &  # US
tail -f test_data/bedrock_*_results.txt
```

中断しても再実行可能 (PromptCache でリジューム)。

## 既知の制約・今後

- ✅ SHA256 レスポンスキャッシュ実装済 (`cache.py`, AD-41)
- ✅ YAML プロンプトテンプレート実装済 (`prompt_registry.py`, AD-40)
- ✅ 日本語プロンプト 5 種類実装済 (AD-43, 【】形式)
- ✅ A/B テスト完了: enrichment は言語中立が最適 (AD-44)
- ストリーミング非対応 (1 リクエスト = 1 完全レスポンス)
- AnthropicProvider (直接API) は未実装 (Bedrock 経由を推奨)
- OpenAI-compatible provider (LiteLLM / vLLM) は未実装
- Bedrock Prompt Caching (server-side) は未対応
