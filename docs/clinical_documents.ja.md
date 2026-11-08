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

clinosim の国別文書レジストリ
(`clinosim/modules/document/narrative/registry.py::specs_for_country()`)
は **US で 13 文書種別**、**JP で 18 種別** を国 / エンカウンター種別
ゲート → 各文書ビルダー → bundled `narrative_seed_bundle.yaml` LLM
戦略 → DocumentReference emit path で end-to-end 配線しています。
JP のみの 5 種 (admission_care_plan, nutrition_care_plan,
rehabilitation_plan, referral_note, health_checkup_report) は JP-CLINS
eReferral / 臨床ワークフロー要件を反映。Progress Note (LOINC 11506-3)
は初期リリースでは Tier C 予約扱いでしたが、v0.6.x 系で end-to-end
配線済みです。

### 医師 (入院) 文書 (US + JP)

| 文書 | LOINC | 生成タイミング | エンカウンター別回数 |
| --- | --- | --- | --- |
| Admission H&P | `34117-2` | 各入院 / ICU / rehab-inpatient エンカウンター | 1 |
| Progress Note | `11506-3` | 入院中の各在院日 | 在院日ごとに 1 |
| Discharge Summary | `18842-5` | 完了した各入院エンカウンター (非死亡) | 1 |
| Operative Note | `11504-8` | `ProcedureRecord.category_code = 387713003` (手術) | 手術ごとに 1 |
| Procedure Note | `28570-0` | 固定 allowlist からの侵襲的ベッドサイド手技 | 0..N |
| Death Discharge Summary | `18842-5` (specialized) | `record.deceased = true` — 死亡症例で通常の退院サマリを置換 | 1 |
| Death Certificate | `64297-5` | `record.deceased = true` — 医師法第 20 条 mandate | 1 |

### 看護記録 (US + JP)

| 文書 | LOINC | 生成タイミング | エンカウンター別回数 |
| --- | --- | --- | --- |
| Admission Nursing Assessment | `78390-2` | 各入院時 | 1 |
| Nursing Shift Note | `34746-8` | 各看護シフト (日勤 / 準夜 / 深夜) | 在院日ごとに 3 |
| Nursing Discharge Summary | `34745-0` | 各入院退院時 | 1 |

### 外来 / 救急 (US + JP)

| 文書 | LOINC | 生成タイミング | エンカウンター別回数 |
| --- | --- | --- | --- |
| Outpatient SOAP | `34131-3` | 各外来エンカウンター | 1 |
| ED Note | `34878-9` | 各救急エンカウンター | 1 |
| ED Triage Note | `54094-8` | 各救急エンカウンター | 1 |

### JP のみ (JP-CLINS / 臨床ワークフロー)

| 文書 | LOINC | 生成タイミング | エンカウンター別回数 |
| --- | --- | --- | --- |
| Admission Care Plan | `18776-5` | JP 各入院時 | 1 |
| Nutrition Care Plan | `80791-7` | JP 入院かつ在院 > 7 日 | 1 |
| Rehabilitation Plan | `34823-5` | JP 入院かつリハビリセッション oder あり | 1 |
| Referral Note | `57133-1` | JP 退院エンカウンターの決定的 20% サブセット (JP-CLINS eReferral) | 1 |
| Health Checkup Report | `53576-5` | JP の各 `checkup` エンカウンター | 1 |

### Procedure Note allowlist

Procedure Note は、`procedure_code` が
`clinosim/modules/document/reference_data/bedside_procedure_codes.yaml`
の `procedure_note_codes` (正本、現在 16 コード) に含まれる
`ProcedureRecord` ごとに生成される。`operative_note_codes` に含まれる
手術コードには代わりに Operative Note が生成される:

| `procedure_code` | 処置 |
| --- | --- |
| `D225` | 観血的動脈圧測定 (Arterial line) |
| `D302` | 気管支ファイバースコピー (Bronchoscopy) |
| `D403` | 腰椎穿刺 (Lumbar puncture) |
| `G005-2` | 中心静脈カテーテル挿入 (Central venous catheter insertion) |
| `J008` | 胸腔穿刺 (Thoracentesis) |
| `J010` | 腹腔穿刺 (Paracentesis) |
| `J019` | 持続的胸腔ドレナージ (Chest tube insertion) |
| `J034` | イレウス用ロングチューブ挿入法 (Long tube for bowel obstruction) |
| `J034-2` | 経鼻栄養・薬剤投与用チューブ挿入術 (Nasogastric tube insertion) |
| `J038` | 人工腎臓 (Acute hemodialysis) |
| `J044` | 救命のための気管挿管 (Endotracheal intubation) |
| `J047` | カウンターショック (Electrical cardioversion) |
| `J063` | 留置カテーテル設置 (Urinary catheter insertion) |
| `K546` | 経皮的冠動脈形成術 (PCI) |
| `K597` | ペースメーカー移植術 (Pacemaker implantation) |
| `K920` | 輸血 (Blood transfusion) |

どちらのリストにも無い処置コードには処置単位の文書は生成されない。

### **生成しないもの** (意図的)

| 文書 | LOINC | 除外理由 |
| --- | --- | --- |
| Consultation Note | `11488-4` | consult ワークフロー必須 (未モデル化)。 |
| Radiology Report | `11526-1` | 放射線は Procedure + ServiceRequest + `DiagnosticReport` として表現、自由文レポート文書ではない。 |
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

オプションの完全な一覧は [CLI リファレンス](reference/cli.ja.md) 参照。

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
    --provider ollama --llm-config clinosim/config/llm_service.yaml \
    --version-id ollama_en_v1
```

### AWS Bedrock (EC2)

EC2 + IAM の完全セットアップは
[bedrock_setup.ja.md](bedrock_setup.ja.md) 参照。

```bash
clinosim narrate --cif-dir ./cif \
    --provider bedrock --llm-config clinosim/config/llm_service.bedrock.yaml \
    --version-id bedrock_sonnet_en_v1
```

### サブセットのみ生成

```bash
# 退院・死亡・手術の文書のみ
# (値は registry の type_key 名)
clinosim narrate --cif-dir ./output/cif \
    --tasks discharge_summary,death_discharge_summary,death_certificate,operative_note
```

### 同一 structural CIF から複数 narrative version

```bash
clinosim narrate --cif-dir ./cif --version-id template_v1
clinosim narrate --cif-dir ./cif --version-id ollama_en_v1 --provider ollama --llm-config clinosim/config/llm_service.yaml
clinosim narrate --cif-dir ./cif --version-id bedrock_en_v1 --provider bedrock --llm-config clinosim/config/llm_service.bedrock.yaml

# version ごとに FHIR をエクスポート
clinosim export-fhir --cif-dir ./cif --narrative-version template_v1 -o ./fhir_template
clinosim export-fhir --cif-dir ./cif --narrative-version ollama_en_v1 -o ./fhir_ollama
clinosim export-fhir --cif-dir ./cif --narrative-version bedrock_en_v1 -o ./fhir_bedrock
```

version-id 文字列は呼び出し側が任意に選択できます。公開されている
GitHub Release tarball (`clinosim-vX.Y.Z-*-*-narrative.tar.gz` asset)
では以下の convention を採用:

- **template tarball**: `cif/narratives/template/`、`current_version.txt = "template"`。
- **llm-polished tarball**: `cif/narratives/{template,llm-polished}/`
  (両者存在)、`current_version.txt = "llm-polished"`。

ローカル実行では任意のラベル使用可、release asset 側の convention
のみ固定。

---

## Prompts

プロンプトテンプレートは
`clinosim/modules/llm_service/prompts/<language>/<task_type>.yaml`
に配置。各言語ディレクトリには narrative パイプラインの 2 つのプロンプト
`narrative_seed.yaml` (1 section) と `narrative_seed_bundle.yaml`
(ランタイムの multi-document bundle 経路) がある。削除した
`LLMService.generate` 経路の文書別プロンプトは削除した (Issue #2556):

```
clinosim/modules/llm_service/prompts/
├── en/
│   ├── narrative_seed.yaml             # 1 section
│   └── narrative_seed_bundle.yaml      # bundle 戦略 (multi-doc 呼び出し)
└── ja/                                 # 同じ 2 ファイル
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
| --- | --- |
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

### プロンプト変数

各プロンプトが参照する変数は `apply_replacement_strategy`
(`clinosim/modules/document/narrative/replacement_strategy.py`) が渡す。
タスク別の変数リストは存在しない。文書ごとの臨床内容は、テンプレート
セクションと `_build_extra_context`
(`narrative/_extra_context_builder.py`) から組み立てた JSON ブロックの
中で LLM に渡る。

**narrative_seed** (1 セクション、`template_seed` strategy):
`section, template_text, severity, day_index, context_json_block`

**narrative_seed_bundle** (1 文書の `llm_enabled_sections` 全体、
`template_seed_bundle` strategy):
`document_type, target_language, severity, day_index,
sections_json_block, context_json_block, output_schema_block`

文書種別ごとの指示は bundle プロンプトの `system:` テキスト内に、
文書種別ごと 1 つの `### <type_key>` ブロック (例: `### admission_hp`、
`### referral_note`) として置かれている。

### プロンプト編集

プロンプトテンプレートを改善するとき:

1. **`version:` フィールドを bump。** version 番号は各生成文書
   (`ClinicalDocument.prompt_version`) に記録され、どの version が
   各 note を生成したかを監査可能。
2. **変数名変更禁止** — `replacement_strategy.py` が渡す変数 dict も
   同時に更新すること。テンプレートがコードの提供しない変数を参照
   すると registry が `KeyError` を発生させる。
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
    "death_discharge_summary": 2
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

**スコープ注記:** エンカウンター当たりの生成数が多い文書 (例:
Consultation Note、シフト別追加 note) を追加する際は、スコープ判断
を先に確認 — エンカウンター当たり文書数を 5–10× に増やし FHIR export
を大幅に肥大化させ得るため。

1. **LOINC コードを選択**
   [Regenstrief LOINC browser](https://loinc.org/) から選び、少なく
   とも `en` フィールドとともに `clinosim/codes/data/loinc.yaml` に
   追加:
   ```yaml
   11488-4:
     en: Consultation note
     ja: 診療依頼書
   ```

2. **タスク種別を enum に追加** — 場所は
   `clinosim/modules/llm_service/engine.py` (`TASK_CATEGORY` と
   `DOCUMENT_LOINC` は手順 3 の yaml から構築される):
   ```python
   class LLMTaskType(StrEnum):
       ...
       CONSULTATION_NOTE = "consultation_note"  # LOINC 11488-4
   ```

3. **task_loincs.yaml + task_categories.yaml に登録**
   (`clinosim/modules/llm_service/reference_data/`)。engine は
   import 時に完全被覆を検証 — `task_loincs.yaml` に行がない新
   `LLMTaskType` 値は fail-loud。

4. **`DocumentTypeSpec` を登録** —
   `clinosim/modules/document/reference_data/document_type_specs.yaml`:
   ```yaml
   consultation_note:
     loinc_code: "11488-4"
     format_type: free_text              # または `composition`
     countries_supported: [us, jp]
     encounter_types_supported: [outpatient]
     generation_frequency: per_encounter # or `admission_once` / `daily` ...
     composition_sections:               # `format_type: composition` 時のみ
       - reason_for_consult
       - findings
       - recommendation
     stage2_strategy: template_seed_bundle
     llm_enabled_sections: [recommendation]
   ```
   `format_type: composition` は named `section[]` 付き
   `Composition` を emit、`free_text` は本文全体を
   `content.attachment.data` に収めた `DocumentReference` を emit。

5. **bundle プロンプトに LLM 指示を追加** — 文書種別ごとの
   プロンプトファイルは存在しない (Issue #2556 で削除)。
   `clinosim/modules/llm_service/prompts/<lang>/narrative_seed_bundle.yaml`
   (`en/` と `ja/` の両方) の `system:` テキストに
   `### consultation_note` ブロックを追加し、`llm_enabled_sections` に
   挙げた各セクションの書き方を記述して、ファイルの `version:` を
   bump する。`llm_enabled_sections` に無いセクションはテンプレート
   テキストのまま残る。

6. **Section builder を実装** —
   `clinosim/modules/document/narrative/renderers/section_builders/<section>.py`
   に `build_<section>(generator, ctx)` 自由関数として実装。C1a-s
   分割後、per-section ロジックは全てここに置く
   (`template_generator.py` はビルダーを re-export する thin façade)。
   `format_type: free_text` タスクは単一 body builder、`composition`
   は `composition_sections` 1 エントリにつき 1 builder。dispatcher の
   配線は `clinosim/modules/document/narrative/renderers/composition_sections.py`。

7. **単体テスト追加** —
   `tests/unit/modules/document/narrative/` (per-section builder テスト) と
   `tests/unit/test_clinical_documents.py` (end-to-end emit)。

8. **このドキュメント** (`docs/clinical_documents.ja.md`) と
   `README.ja.md`、EN sibling を更新。

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

2. `clinosim/modules/llm_service/prompts/<lang>/` を作成し、2 つの
   narrative プロンプト `narrative_seed.yaml` と
   `narrative_seed_bundle.yaml` の翻訳を置く。対象言語のネイティブ
   スピーカーの臨床医が各テンプレートを review すべき。

3. `clinosim narrate --cif-dir <cif> --country <XX>` で新規プロンプトをテスト。
   `narrate` に `--language` フラグは無い: 文書言語は国 (`--country`、
   省略時は `cif/metadata.json` から自動検出) に従う。

4. プロンプトレジストリは特定プロンプトファイルが欠けている場合
   自動的に英語にフォールバックするので、部分翻訳は安全。

---

## 関連

- [README.md](../README.ja.md) — メインユーザガイド
- [bedrock_setup.ja.md](bedrock_setup.ja.md) — EC2 + AWS Bedrock
  デプロイ
- [architecture-notes.ja.md](architecture/architecture-notes.ja.md) —
  臨床文書のアーキテクチャ判断 (AD-36〜AD-41)
- `clinosim/modules/llm_service/README.ja.md` — LLM サービスモジュール
  リファレンス
- `clinosim/modules/output/README.ja.md` — 出力アダプタモジュール
  リファレンス
