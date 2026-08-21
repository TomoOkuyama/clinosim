<!-- README.md から抽出 (Issue #568 PR A)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# CLI リファレンス

clinosim は 3 つの独立ステージで構成。`clinosim simulate` が Stage 1
を実行; Stage 2 と 3 は `--narrative` と `--format fhir` で合成
可能、または再現性・リモート実行 (Bedrock on EC2 等) ・反復
narrative 実験のため独立に実行。`clinosim generate` は
`simulate` の deprecated alias として残存。

```
┌────────────────┐  ┌────────────────┐  ┌──────────────────┐
│ simulate       │→ │ narrate        │→ │ export-fhir      │
│ (Stage 1)      │  │ (Stage 2)      │  │ (Stage 3)        │
│ structured CIF │  │ narrative CIF  │  │ FHIR R4 NDJSON   │
└────────────────┘  └────────────────┘  └──────────────────┘
```

### `clinosim simulate` — Stage 1 (structural シミュレーション)

集団駆動シミュレーション。structural CIF を生成、オプションで
Stage 2/3 を 1 コマンドで実行。

| Option | Default | 説明 |
|---|---|---|
| `-o, --output DIR` | `./output` | 出力ディレクトリ |
| `-p, --population N` | hospital config の `recommended_population` | Catchment population |
| `--country CODE` | `US` | `US` または `JP` |
| `--start YYYY-MM-DD` | `--end` から 1 年前 | シミュレーション開始日 |
| `--end YYYY-MM-DD` | 今日 | シミュレーション終了日 = snapshot 日 |
| `--hospital-config PATH` | `clinosim/config/hospital_operations.yaml` (50 床) | Hospital config YAML |
| `--format ...` | `cif fhir` | `cif` / `csv` / `fhir` |
| `-s, --seed N` | `42` | ランダム seed |
| `--narrative` | off | Stage 1 後に Stage 2 (臨床文書) を実行 |
| `--llm-config PATH` | (未設定) | `--narrative` 時に使用する LLM サービス YAML |
| `--narrative-version ID` | auto | FHIR エクスポート時に使用する narrative version id |
| `--narrative-model NAME` | `qwen:7b` | レガシー Ollama モデル名 (`--llm-config` 設定時は無視) |

### `clinosim narrate` — Stage 2 (臨床文書)

> **注**: template モードの DocumentReference は Stage 1 の
> `document_enricher` モジュールにより自動 emit されるので、
> `clinosim simulate --format fhir-r4` は別途 `narrate` step なしでも
> `docStatus="preliminary"` 文書を含む valid な FHIR bundle を生成。
> 後で `narrate` を実行するとそれらを LLM 生成テキストで
> `docStatus="final"` にアップグレード (template モードなら
> `preliminary` のまま)。

既存 CIF ディレクトリを読み、LLM サービス経由で臨床文書を生成。
`<cif>/narratives/<version_id>/` に新規 narrative バージョンを書き
出す。

| Option | Default | 説明 |
|---|---|---|
| `--cif-dir DIR` | **必須** | 既存 CIF ディレクトリへのパス |
| `--llm-config PATH` | (template モード) | LLM サービス YAML (`clinosim/config/llm_service*.yaml`) |
| `--version-id ID` | auto-timestamped | Narrative バージョンディレクトリ名 |
| `--language LANG` | `en` | 文書言語 (`en` \| `ja`) |
| `--tasks LIST` | 全 Tier A+B | カンマ区切りサブセット: `discharge_summary,death_summary,operative_note,admission_hp,procedure_note` |

**Tier A+B 文書 scope** (デフォルト):

| 文書 | LOINC | 生成タイミング | 頻度 |
|---|---|---|---|
| Discharge Summary | `18842-5` | 各入院退院 | encounter ごとに 1 |
| Death Note | `69730-0` | 死亡入院患者 | 死亡ごとに 1 |
| Operative Note | `11504-8` | 外科手技 (SNOMED 387713003) | 手術ごとに 1 |
| Admission H&P | `34117-2` | 各入院 | encounter ごとに 1 |
| Procedure Note | `28570-0` | 侵襲的ベッドサイド (central line、LP、thoracentesis、paracentesis、chest tube、intubation、bronchoscopy、cardioversion) | 処置ごとに 1 |

詳細は [../clinical_documents.ja.md](../clinical_documents.ja.md)
参照。

### `clinosim export-fhir` — Stage 3 (FHIR R4 NDJSON)

既存 CIF ディレクトリを読み、FHIR R4 Bulk Data NDJSON ファイルを
書き出す。DocumentReference リソースは `record.documents`
(Stage 1 enricher 出力) から emit。

| Option | Default | 説明 |
|---|---|---|
| `--cif-dir DIR` | **必須** | 既存 CIF ディレクトリへのパス |
| `-o, --output DIR` | `<cif>/../fhir_r4` | 出力ディレクトリ |
| `--country CODE` | `US` | Country code (display 言語) |

### `clinosim test-disease DISEASE_ID`

特定疾患の forced シナリオ生成 (デバッグ / golden test)。

```bash
clinosim test-disease heart_failure_exacerbation \
  --severity severe --archetype treatment_resistant -n 3
```

### `clinosim test-encounter CONDITION_ID`

ED / 外来 encounter unit test。

```bash
clinosim test-encounter migraine --age 35 --sex F
```

### `clinosim validate`

生成データを公開ベンチマークに対して品質 check。

### `clinosim list-diseases`

全 32 疾患 (`clinosim/modules/disease/reference_data/*.yaml`) + 46
encounter 症状 (`clinosim/modules/encounter/reference_data/*.yaml`)
を表示。

### 典型的ワークフロー

**ローカル template のみ実行 (LLM なし、決定的):**
```bash
clinosim simulate -o ./output -p 5000 --country US
clinosim narrate --cif-dir ./output/cif --version-id template_v1
clinosim export-fhir --cif-dir ./output/cif --narrative-version template_v1
```

**ローカル LLM (Ollama):**
```bash
clinosim simulate -o ./output -p 5000 --country US
clinosim narrate --cif-dir ./output/cif \
    --llm-config clinosim/config/llm_service.yaml \
    --version-id ollama_en_v1
clinosim export-fhir --cif-dir ./output/cif --narrative-version ollama_en_v1
```

**分割: ローカル Stage 1、EC2 Stage 2 (Bedrock)、ローカル Stage 3
に戻る:**
```bash
# ローカルマシン
clinosim simulate -o ./output -p 5000 --country US --format cif
scp -r ./output/cif ec2-user@ec2-host:/home/ec2-user/

# EC2 (IAM ロールに bedrock:Converse)
clinosim narrate --cif-dir /home/ec2-user/cif \
    --llm-config clinosim/config/llm_service.bedrock.yaml \
    --version-id bedrock_sonnet_en_v1

# 結果を pull back、それから
clinosim export-fhir --cif-dir ./output/cif \
    --narrative-version bedrock_sonnet_en_v1
```

EC2 + Bedrock セットアップガイドは
[../bedrock_setup.ja.md](../bedrock_setup.ja.md) 参照。

---
