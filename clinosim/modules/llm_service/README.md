# clinosim.modules.llm_service — Centralized LLM Service

## 目的

clinosim 内の **全 LLM 呼び出しの単一エントリポイント** を提供する (AD-11)。

他のモジュール (encounter, diagnosis, observation, output 等) は LLM API を直接呼ばず、 必ず本サービス経由でテキスト生成を依頼する。 これにより:

- LLM プロバイダ (Ollama, Anthropic, ローカルモック) を 1 箇所で切り替え可能
- プロンプトテンプレートが集中管理され、 監査・改善が容易
- LLM 障害時の **自動 template フォールバック** で simulation を止めない
- コスト/トークン使用量を集中計測
- JUDGMENT (診断推論) と NARRATIVE (記録生成) を独立したプロバイダ・モデルで運用可能 (AD-24)

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **Single point of LLM access (AD-11)** | 他モジュールから LLM SDK (`anthropic`, `httpx` 等) を直接 import しない |
| 2 | **Modules never write prompts** | 呼び出し側は構造化された `ClinicalEventData` を渡すのみ。 プロンプト構築は本モジュール内で行う |
| 3 | **Mode hierarchy** | `none` < `template` < `llm`。 LLM 失敗時は自動的に template にフォールバック |
| 4 | **Category-aware routing (AD-24)** | JUDGMENT / NARRATIVE で別 provider・別モデル可能 |
| 5 | **JUDGMENT は常に英語** | 言語設定に関わらず、 診断推論は英語で行う (medical literature の標準) |
| 6 | **Deterministic-friendly** | mode=`none`/`template` ではネットワーク呼び出しゼロ → 完全再現可能 |

## ディレクトリ構造

```
clinosim/modules/llm_service/
├── __init__.py
├── README.md            # 本ドキュメント
├── SPEC.md
├── engine.py            # LLMService + プロンプトビルダー + テンプレート
└── providers.py         # OllamaProvider, MockProvider
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
        judgment_provider: Any = None,
        narrative_provider: Any = None,
        judgment_model_map: dict[str, str] | None = None,
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

### `LLMTaskType` — タスク種別

| Category | TaskType | 説明 |
|---|---|---|
| JUDGMENT | `DIAGNOSTIC_REASONING` | 鑑別診断・確信度の推論 (常に英語) |
| JUDGMENT | `TREATMENT_DECISION` | 治療方針の意思決定 |
| JUDGMENT | `CLINICAL_JUDGMENT` | 一般的な臨床判断 |
| JUDGMENT | `CONSISTENCY_REVIEW` | データ整合性チェック |
| NARRATIVE | `CHIEF_COMPLAINT` | 主訴の自然文化 |
| NARRATIVE | `ADMISSION_HP` | 入院時 H&P |
| NARRATIVE | `PROGRESS_NOTE` | SOAP 形式の経過記録 |
| NARRATIVE | `DISCHARGE_SUMMARY` | 退院時サマリー |
| NARRATIVE | `NURSING_NOTE` | 看護記録 |

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

### JUDGMENT/NARRATIVE で異なる provider (AD-24)

```python
# 高品質モデルで診断推論、 ローカル軽量モデルで記録生成
llm = LLMService(
    mode="llm",
    judgment_provider=anthropic_provider,         # Claude for reasoning
    judgment_model_map={"medium": "claude-3-5-sonnet"},
    narrative_provider=OllamaProvider(),          # local Llama for notes
    narrative_model_map={"medium": "llama3.1:8b"},
)
```

## セットアップ — Ollama (デフォルト)

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

設定ファイル: `clinosim/config/llm_service.yaml` (デフォルト・local Ollama)、 `clinosim/config/llm_service.cloud.yaml` (Anthropic 直接呼び出し設定例、 `ANTHROPIC_API_KEY` が必要)。

## 依存関係

- `httpx` — HTTP クライアント (Ollama 通信)
- `numpy` (間接、 simulation 全般)
- 外部依存ゼロでテスト可能 (`MockProvider` 使用時)

本モジュールは clinosim の他モジュールに **依存しない**。 逆に他モジュール (output/narrative_generator, encounter 等) が本モジュールに依存する。

## 権威ソース

| プロバイダ | ドキュメント |
|---|---|
| Ollama | [ollama.com](https://ollama.com) / [API リファレンス](https://github.com/ollama/ollama/blob/main/docs/api.md) |
| Anthropic API | [docs.anthropic.com](https://docs.anthropic.com/) |
| llama.cpp / GGUF | [llama.cpp](https://github.com/ggerganov/llama.cpp) |

## 既知の制約・今後

- v0.1-beta 時点で **JUDGMENT カテゴリは未配線** — diagnosis モジュールから呼ばれる経路は実装途中
- AnthropicProvider クラスは `providers.py` に未実装 (config だけ存在)
- プロンプトキャッシュ・レスポンスキャッシュ未実装
- ストリーミング非対応 (1 リクエスト = 1 完全レスポンス)
