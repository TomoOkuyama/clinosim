# clinosim の臨床文書

clinosim はシミュレーションパイプラインの一部として **臨床的に構造化
された narrative 文書** をシミュレートします。各文書は 2 回書かれ
ます: 一度は CIF 中間 JSON (*narrative CIF*)、もう一度は Bulk Data
NDJSON エクスポート内の FHIR R4 `DocumentReference` リソースとして。

本ガイドがカバーする範囲:

- [emit される文書種別と生成タイミング](#document-scope)
- [LOINC マッピングと FHIR フィールド](#fhir-mapping)
- [エンドツーエンドワークフロー](#workflow)
- [プロンプトテンプレートの記述と編集](#prompts)
- [プロブナンスと再現性](#provenance)
- [新規文書種別の追加](#新規文書種別の追加)
- [新規言語の追加](#新規言語の追加)

---

## Document scope

clinosim の LLM service enum `LLMTaskType`
(`clinosim/modules/llm_service/engine.py`) は 20+ の NARRATIVE task type
と 4 つの JUDGMENT task type を定義しています。うち **prompt YAML →
template pass → DocumentReference emit path で end-to-end 配線済みの
サブセット**が以下の 8 文書種別で、いずれも
`clinosim/modules/llm_service/prompts/{en,ja}/` に EN + JA prompt YAML
を持ちます。Progress Note (LOINC 11506-3) は enum 定義済ながら、実世界
の progress note が構造化 vitals/labs/MAR レイヤと重複度が高いため
将来の Tier C opt-in として予約。nursing / outpatient / ED / care-plan /
health-checkup 系 NARRATIVE type も同様に将来 phase 用に enum のみ宣言。

| Tier | 文書 | LOINC | 生成タイミング | エンカウンター別回数 |
|---|---|---|---|---|
| A | Discharge Summary | `18842-5` | 完了した各入院エンカウンター (非死亡) | 1 |
| A | Death Summary | `69730-0` | `record.deceased = true` | 1 |
| A | Death Discharge Summary | `18842-5` (specialized title) | `record.deceased = true` — 死亡症例で通常の退院サマリを置換 (Issue #961) | 1 |
| A | Death Certificate | `64297-5` | `record.deceased = true` — 医師法第 20 条 mandate (Issue #961) | 1 |
| A | Operative Note | `11504-8` | `ProcedureRecord.category_code = 387713003` (手術) | 手術ごとに 1 |
| B | Admission H&P | `34117-2` | 各入院エンカウンター | 1 |
| B | Procedure Note | `28570-0` | 固定 allowlist からの侵襲的ベッドサイド手技 | 0..N |
| JP | Referral Note | `57133-1` | `country=JP` の退院エンカウンターの決定的 20% サブセット (JP-CLINS eReferral、PR2b) | 1 |

### Procedure Note allowlist

実世界の文書化慣習に合わせ、**8 つの侵襲的ベッドサイド手技** のみが
正式な Procedure Note を生成:

| `procedure_type` | 根拠 |
|---|---|
| `central_line` | 挿入部位、血管、確認要 |
| `lumbar_puncture` | 開放圧、CSF 性状、tube 採取 |
| `thoracentesis` | 液量と性状、処置後画像 |
| `paracentesis` | 液量と性状、適応 |
| `chest_tube` | 挿入部位、初期ドレナージ、確認 |
| `intubation` | Cormack-Lehane grade、tube サイズ、ETCO₂ 確認 |
| `bronchoscopy` | 所見、BAL 結果、biopsy 検体 |
| `cardioversion` | エネルギー、成否、rhythm before/after |

このリストにない処置 (尿カテーテル、NG チューブ、心エコー、輸血、
透析、動脈ライン、創傷 debridement) は nursing record や補助
レポートに折り込まれ、独立した DocumentReference は生成されない。

### **生成しないもの** (意図的)

| 文書 | LOINC | Milestone 1 で除外理由 |
|---|---|---|
| Progress Note | `11506-3` | 構造化観察と ~80% 重複; 4–10x の文書膨張と限界的研究価値。Tier C opt-in として予約。 |
| Consultation Note | `11488-4` | consult ワークフロー必須 (未モデル化)。 |
| Nursing Note | `34119-8` | narrative は vitals/I/O record に吸収。 |
| Radiology Report | `11526-1` | 放射線は Procedure + ServiceRequest として表現、自由文レポートではない。 |
| Pathology Report | `11526-1` (pathology variant) | 検体病理未モデル化。 |

---

## FHIR mapping

narrative CIF の各 `ClinicalDocument` は 1 つの FHIR R4
`DocumentReference` リソースになります:

```
DocumentReference.id          = <document_id>
  .status                     = "current"
  .docStatus                  = "final" | "preliminary"
  .type.coding[0]             = { system: http://loinc.org, code: <loinc>, display: <lookup> }
  .category[0].coding[0]      = { system: us-core-documentreference-category, code: clinical-note }
  .subject                    = Patient/<patient_id>
  .date                       = <authored_datetime>
  .author[0]                  = Practitioner/<author_practitioner_id>
  .content[0].attachment
      .contentType            = "text/plain; charset=utf-8"
      .language               = "en" | "ja"
      .data                   = base64(text)
      .title                  = <loinc display>
      .size                   = テキストのバイト長
      .hash                   = base64(sha1(text))
  .context.encounter[0]       = Encounter/<encounter_id>
  .context.period             = { start: <period_start>, end: <period_end> }
  .context.related[0]         = Procedure/<related_procedure_id>  (op/procedure note のみ)
```

**docStatus セマンティクス:**
- `"final"` — テキストは LLM 呼び出し由来 (`text_source = "llm" | "cache"`)
- `"preliminary"` — テキストは決定的フォールバックテンプレート由来
  (`text_source = "template"`)。最終化文書を要求する下流 consumer
  はこれをフィルタ可能。

**空 stub は emit されない。** Stage 2 が実行されなかった / `narrate`
がスキップされた / 文書 stub のテキストが空の場合、DocumentReference
は生成されない。これは FHIR R4 profile 期待に合致 (空 `data` の
attachment はセマンティクス上無意味)。

**Reference integrity.** 各 `subject` / `encounter` / `author` /
`context.related[*]` reference は同じ Bulk Data エクスポート内に存在
するリソースに解決。`export-fhir` Stage 3 は対応する NDJSON ファイル
に現れない Patient や Encounter を指す DocumentReference を emit
しない。

---

## Workflow

### 3 ステージ

```
clinosim simulate   →   cif/structural/patients/*.json       (Stage 1)
clinosim narrate    →   cif/narratives/<ver>/documents/*.json (Stage 2)
clinosim export-fhir →  fhir_r4/*.ndjson (DocumentReference.ndjson 含む)  (Stage 3)
```

CLI 完全リファレンスはメインの
[README.md](../README.md#cli-reference) 参照。

### テンプレートモード (LLM なし)

```bash
clinosim narrate --cif-dir ./output/cif --version-id template_v1
```

テンプレートモードは決定的な Python フォールバックを使用し LLM を
呼び出さない。用途:
- LLM 呼び出しが禁止された CI パイプライン
- 再現性テスト
- narrative CIF → FHIR DocumentReference パスの smoke test
- 高価な LLM 実行前のベースライン文書数確立

### ローカル Ollama モード

```bash
ollama pull llama3.1:8b
clinosim narrate --cif-dir ./output/cif \
    --llm-config clinosim/config/llm_service.yaml \
    --version-id ollama_en_v1
```

### AWS Bedrock (EC2)

EC2 + IAM の完全セットアップは
[bedrock_setup.ja.md](bedrock_setup.ja.md) 参照。

```bash
clinosim narrate --cif-dir ./cif \
    --llm-config clinosim/config/llm_service.bedrock.yaml \
    --version-id bedrock_sonnet_en_v1
```

### サブセットのみ生成

```bash
# 法的必須文書 (Tier A) のみ
clinosim narrate --cif-dir ./output/cif \
    --tasks discharge_summary,death_summary,operative_note
```

### 同一 structural CIF から複数 narrative version

```bash
clinosim narrate --cif-dir ./cif --version-id template_v1
clinosim narrate --cif-dir ./cif --version-id ollama_en_v1 --llm-config clinosim/config/llm_service.yaml
clinosim narrate --cif-dir ./cif --version-id bedrock_en_v1 --llm-config clinosim/config/llm_service.bedrock.yaml

# version ごとに FHIR をエクスポート
clinosim export-fhir --cif-dir ./cif --narrative-version template_v1 -o ./fhir_template
clinosim export-fhir --cif-dir ./cif --narrative-version ollama_en_v1 -o ./fhir_ollama
clinosim export-fhir --cif-dir ./cif --narrative-version bedrock_en_v1 -o ./fhir_bedrock
```

---

## Prompts

プロンプトテンプレートは
`clinosim/modules/llm_service/prompts/<language>/<task_type>.yaml`
に配置:

```
clinosim/modules/llm_service/prompts/
└── en/
    ├── admission_hp.yaml
    ├── discharge_summary.yaml
    ├── death_summary.yaml
    ├── operative_note.yaml
    └── procedure_note.yaml
```

各ファイルの構造:

```yaml
task_type: discharge_summary
version: 1                # テンプレート変更時に bump
max_tokens: 2000
temperature: 0.4
description: |            # 任意の人間可読目的
  FHIR DocumentReference with LOINC 18842-5 (Discharge summary note).
  Required by CMS §482.24 for every inpatient admission.

system: |                 # システムプロンプト (自然言語、${...} 可)
  You are an attending physician writing a comprehensive discharge summary ...

user_template: |          # ユーザープロンプト、${variable} プレースホルダ付き
  Patient: ${age}yo ${sex}
  Admission date: ${admission_date}
  Discharge date: ${discharge_date}
  ...
```

### 変数レンダリング

- `system` は `string.Template.safe_substitute()` でレンダリング —
  未知の `${...}` シーケンスはそのまま残り自然言語コンテンツを
  壊さない。
- `user_template` は `string.Template.substitute()` でレンダリング —
  欠けた変数は `KeyError` を発生させ、不正なプロンプトを出荷せず
  はっきり失敗。

### 変数フォーマット

プロンプトレジストリは substitution 前に変数を正規化:

| Python 型 | レンダリング形式 |
|---|---|
| `str` | そのまま |
| `int` / `float` | `str(value)` |
| `None` | 空文字列 |
| `list[str]` (非空) | 改行結合の bullet リスト (`- item`) |
| `list[str]` (空) | `(none)` |
| `list[dict]` | 再帰的に文字列化 |
| `dict` | `key: value` を 1 行ずつ |

つまり discharge summary プロンプトが
`"discharge_medications": ["Amoxicillin 500mg PO BID x 7 days"]` を
渡せば、テンプレートは自動的に bullet リストとしてレンダリングする。

### タスク別利用可能変数

変数名は `document_generator.py` で定義され、YAML テンプレートの
プレースホルダと一致する必要あり。完全リスト:

**discharge_summary**:
`age, sex, admission_date, discharge_date, los_days, disposition,
attending_physician, chief_complaint, past_medical_history,
admission_diagnosis, discharge_diagnoses, hospital_course_bullets,
procedures_performed, discharge_medications`

**death_summary**:
`age, sex, admission_date, death_datetime, los_days,
attending_physician, admission_diagnosis, primary_diagnosis,
past_medical_history, hospital_course_bullets, terminal_findings,
complications`

**operative_note**:
`surgery_date, procedure_name, procedure_code, preop_diagnosis,
postop_diagnosis, surgeon, assistants, anesthesiologist,
anesthesia_type, asa_class, duration_minutes,
estimated_blood_loss_ml, body_site, approach, implants_used,
specimens_sent, intraop_complications, outcome`

**admission_hp**:
`age, sex, admission_datetime, admitting_physician, department,
chief_complaint, hpi_summary, past_medical_history,
home_medications, allergies, admission_vitals, initial_labs,
admission_diagnosis`

**procedure_note**:
`procedure_date, procedure_name, procedure_code, operator, indication,
body_site, anesthesia_type, duration_minutes, findings,
specimens_obtained, complications, outcome`

### プロンプト編集

プロンプトテンプレートを改善するとき:

1. **`version:` フィールドを bump。** version 番号は各生成文書
   (`ClinicalDocument.prompt_version`) に記録され、どの version が
   各 note を生成したかを監査可能。
2. **変数名変更禁止** — `document_generator.py` 更新なしで。生成器
   はテンプレートがコードの提供しない変数を参照すると `KeyError`
   を発生させる。
3. **LLM token を消費せずレンダリング検証するためテンプレートモード
   で先にテスト**:
   ```bash
   clinosim narrate --cif-dir ./output/cif --version-id prompt_v2_test
   ```

---

## Provenance

各 `ClinicalDocument` JSON ファイルは完全なプロブナンスを記録:

```json
{
  "document_id": "doc-ENC-POP-000005-0001-discharge_summary",
  "task_type": "discharge_summary",
  "loinc_code": "18842-5",
  "patient_id": "POP-000005",
  "encounter_id": "ENC-POP-000005-0001",
  "author_practitioner_id": "DR-IM-003",
  "authored_datetime": "2026-03-15T14:30:00",
  "period_start": "2026-03-01T09:00:00",
  "period_end": "2026-03-15T14:30:00",
  "language": "en",
  "text": "DISCHARGE SUMMARY\n...",
  "text_source": "llm",
  "llm_model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
  "llm_provider": "bedrock",
  "llm_input_tokens": 1250,
  "llm_output_tokens": 480,
  "prompt_version": 1,
  "cache_hit": false,
  "generated_at": "2026-04-09T12:34:56",
  "fallback_reason": ""
}
```

- **`text_source`** はテキストがどう生成されたかの決定的宣言:
  - `"llm"` — 新規 LLM 呼び出し
  - `"cache"` — SHA256 プロンプト cache から (同モデル / system /
    user prompt)
  - `"template"` — 決定的 Python フォールバック (LLM 失敗後または
    テンプレートモード)
  - `"none"` — LLMService が `none` モード; 文書はテキスト空
- **`cache_hit`** は `text_source = "cache"` と冗長だがコストレポート
  集約を容易にするため保持。
- **`fallback_reason`** は LLM 呼び出しが失敗しテンプレートに
  フォールバックしたときに populate。形式:
  `provider_error:<ExceptionType>: <message>` (200 文字に truncate)。

narrative version の `manifest.json` はこれらを集約:

```json
{
  "version_id": "bedrock_sonnet_en_v1",
  "generated_at": "2026-04-09T13:00:00",
  "language": "en",
  "llm_mode": "llm",
  "patient_count": 171,
  "document_counts_by_type": {
    "admission_hp": 171,
    "discharge_summary": 171,
    "operative_note": 11,
    "procedure_note": 19,
    "death_summary": 2
  },
  "total_documents": 374,
  "llm_cost_report": {
    "total_calls": 374,
    "total_input_tokens": 412389,
    "total_output_tokens": 58041,
    "fallback_count": 0,
    "cache_hit_count": 0,
    "cache_stats": {"hits": 0, "misses": 374, "writes": 374, "enabled": 1}
  }
}
```

---

## 新規文書種別の追加

**スコープ注記:** Tier C 文書 (Progress Note / Consultation Note)
を追加する場合、スコープ判断を最初に確認 — Progress Note は意図的
に defer 済で、Tier C 生成は文書数を 5–10x に増やす。

1. **LOINC コードを選択**
   [Regenstrief LOINC browser](https://loinc.org/) から選び、少なく
   とも `en` フィールドとともに `clinosim/codes/data/loinc.yaml` に
   追加:
   ```yaml
   11488-4:
     en: Consultation note
     ja: 診療依頼書
   ```

2. **タスク種別を enum と LOINC map に追加** — 場所は
   `clinosim/modules/llm_service/engine.py`:
   ```python
   class LLMTaskType(str, Enum):
       ...
       CONSULTATION_NOTE = "consultation_note"  # LOINC 11488-4

   TASK_CATEGORY[LLMTaskType.CONSULTATION_NOTE] = LLMTaskCategory.NARRATIVE
   DOCUMENT_LOINC[LLMTaskType.CONSULTATION_NOTE] = "11488-4"
   ```

3. **英語プロンプト YAML 作成**
   `clinosim/modules/llm_service/prompts/en/consultation_note.yaml`
   を上述テンプレートに従って作成。

4. **入力ビルダーを追加** —
   `clinosim/modules/output/document_generator.py`:
   ```python
   def _build_consultation_note(record, encounter, llm, language):
       variables = {
           "age": ...,
           "sex": ...,
           "consulting_service": ...,
           "reason_for_consult": ...,
           ...
       }
       stub = _make_stub(
           task_type=LLMTaskType.CONSULTATION_NOTE,
           patient_id=...,
           encounter_id=...,
           ...,
       )
       return _fill_text(stub, llm, variables)
   ```

5. **ビルダーを `_generate_for_record` に配線**。

6. **`_resolve_enabled_tasks()` に追加** してデフォルトセットに出現
   させる。

7. **単体テスト追加** — `tests/unit/test_clinical_documents.py` の
   既存 `TestDocumentGeneratorE2E` パターンに従う。

8. **このドキュメント** (`docs/clinical_documents.md`) と
   `README.md` / `DESIGN.md` を更新。

---

## 新規言語の追加

1. 臨床文書が使用する各 LOINC コードが新言語の display translation
   を `clinosim/codes/data/loinc.yaml` 内に持つことを確認:
   ```yaml
   18842-5:
     en: Discharge summary note
     ja: 退院時サマリー
     de: Arztbrief / Entlassungsbrief
   ```

2. `clinosim/modules/llm_service/prompts/<lang>/` の下にタスク別
   プロンプト YAML ファイルを作成。対象言語のネイティブスピーカー
   の臨床医が各テンプレートを review すべき。

3. `clinosim narrate --language <lang>` で新規プロンプトをテスト。

4. プロンプトレジストリは特定プロンプトファイルが欠けている場合
   自動的に英語にフォールバックするので、部分翻訳は安全。

---

## 関連

- [README.md](../README.md) — メインユーザガイド
- [bedrock_setup.ja.md](bedrock_setup.ja.md) — EC2 + AWS Bedrock
  デプロイ
- [../DESIGN.md](../DESIGN.md) Section 7 — 臨床文書のアーキテクチャ
  判断 (AD-36〜AD-41)
- `clinosim/modules/llm_service/README.ja.md` — LLM サービスモジュール
  リファレンス
- `clinosim/modules/output/README.ja.md` — 出力アダプタモジュール
  リファレンス
