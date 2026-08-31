<!-- README.md から抽出 (Issue #568 PR A)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# CLI リファレンス

`clinosim` は 3 つの独立ステージ + デバッグ / audit / dataset /
eval / benchmark subcommand で構成。Stage 1 (`simulate`) が
structural CIF を生成、Stage 2 (`narrate`) と Stage 3 (`export-fhir`)
は CIF 上で走り、Stage 1 と合成するか、または再現性・リモート LLM
実行・反復 narrative 実験のため独立に実行可能。`clinosim generate`
は `simulate` の deprecated alias として残る。

```
┌────────────────┐  ┌────────────────┐  ┌──────────────────┐
│ simulate       │→ │ narrate        │→ │ export-fhir      │
│ (Stage 1)      │  │ (Stage 2)      │  │ (Stage 3)        │
│ structured CIF │  │ narrative CIF  │  │ FHIR R4 NDJSON   │
└────────────────┘  └────────────────┘  └──────────────────┘
```

権威 source は
[`clinosim/simulator/cli.py`](https://github.com/TomoOkuyama/clinosim/blob/master/clinosim/simulator/cli.py)
。最新オプション一覧は `clinosim <subcommand> --help` で確認。

## `clinosim simulate` — Stage 1 (structural シミュレーション)

集団駆動シミュレーション。structural CIF を生成し、末尾で
template Stage 2 narrative pass を自動実行するので
`clinosim simulate --format fhir-r4` だけで emit 可能な FHIR bundle
になる。`clinosim generate` は同じオプションを受け付ける。

| Option | Default | 説明 |
|---|---|---|
| `-o, --output DIR` | `./output` | 出力ディレクトリ |
| `-p, --population N` | hospital config の `recommended_population` | Catchment population |
| `--country CODE` | `US` | `US` または `JP` |
| `--start YYYY-MM-DD` | `--end` の 1 年前 | シミュレーション開始日 |
| `--end YYYY-MM-DD` | 今日 | シミュレーション終了日 = snapshot 日 |
| `--hospital-config PATH` | `clinosim/config/hospital_operations.yaml` (50 床) | Hospital config YAML |
| `--format ...` | `cif` | `cif` / `csv` / `fhir-r4` (alias: `fhir`) から 1 個以上。`OutputAdapter` (AD-58) を register することで追加可能。 |
| `-s, --seed N` | `42` | ランダム seed |
| `--jp-insurance / --no-jp-insurance` | on (JP のみ) | JP 保険加入 / 被保険者番号 の含有 (FHIR `Coverage` として emit)。非 JP では無視。 |
| `--cache-dir DIR` | (未設定) | F4 memoize: 前回 snapshot の cursor 前に完了した encounter を持つ患者を再利用。daily-cron 追記対応 (p=500k 追記が ~13 h → ~分)。 |
| `--log-file PATH` | `<output>/simulator.log` | 構造化 JSONL simulator ログ (Issue #172)。`tail -f` で live 監視。level は `CLINOSIM_LOG_LEVEL` (default `INFO`)。 |
| `--allow-legacy` | off | (JP のみ) JP-CLINS package 未インストール時に legacy 5-digit JLAC10 OID 出力を許可。default は fail-loud (Issue #418) — `--country JP` は eCS 準拠出力のため JP-CLINS package を要求。 |

## `clinosim narrate` — Stage 2 (臨床文書)

> **注**: template モードの DocumentReference は Stage 1 の
> `TemplateNarrativePass` により自動 emit されるので、
> `clinosim simulate --format fhir-r4` は別途 `narrate` step なしでも
> `docStatus="preliminary"` 文書付きの valid な FHIR bundle を生成。
> 後で `narrate` を実行すると新規 narrative version が書かれ、
> template provider の default で `current_version.txt` は新 version
> を指すよう更新される。

既存 CIF ディレクトリを読み、臨床文書を生成。
`<cif>/narratives/<version_id>/` に新規 narrative バージョンを書き
出す。

| Option | Default | 説明 |
|---|---|---|
| `--cif-dir DIR` | **必須** | 既存 CIF ディレクトリへのパス |
| `--provider NAME` | `template` | Narrative 生成器: `template` (決定的)、または LLM provider: `bedrock`、`ollama`、`mock`、`vllm` (OpenAI 互換 `/v1/chat/completions`; SGLang 他 OpenAI 互換サーバも対象)、`openai_compatible` (`vllm` の alias)。 |
| `--llm-config PATH` | provider ごとの default | LLM サービス YAML (`clinosim/config/llm_service*.yaml`)。Default: `bedrock` → `llm_service.bedrock.yaml`、`ollama` → `llm_service.yaml`、`mock` → in-code `MockProvider`。 |
| `--version-id ID` | provider 名 | Narrative バージョンディレクトリ名 |
| `--tasks LIST` | 全 Tier A+B | カンマ区切り `LLMTaskType` フィルタ (`discharge_summary,death_summary,operative_note,admission_hp,procedure_note`) |
| `--country CODE` | `US` | Country code (display 言語) |
| `--set-current / --no-set-current` | provider 依存 | `current_version.txt` を更新。Default: `--provider template` では yes、LLM provider (bedrock/ollama/mock) では no (M-3 / N-chain: 試験 run が production export を silent に上書きしない)、`--patient-filter` 指定時はどの provider でも常に no (chain 1b adv-1 I-1)。明示指定は常に勝つ。 |
| `--seed N` | `42` | 決定性のための RNG seed |
| `--patient-filter REGEX` | (未設定) | 患者ファイル stem / `patient_id` に対する正規表現 — マッチする患者のみ narrate (remote per-patient iteration、chain 1b T3)。フィルタは version manifest に記録。 |
| `--merge-into-version` | off | `--patient-filter` 併用時: 既に文書がある version ディレクトリへの書き込みを許可 (iterate-one-patient loop)。指定なしでは非空 version への filtered write は拒否。 |
| `--concurrency N` | `1` | narrate worker thread 数。値を上げると batching LLM backend (vLLM continuous batching 等) が N 個の in-flight `generate()` 呼を吸収 — サーバの `--max-num-seqs` またはその一部に合わせる。thread-safe provider (Ollama / vLLM / Mock) 必須。 |

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

## `clinosim export-fhir` — Stage 3 (FHIR R4 NDJSON)

既存 CIF ディレクトリを読み、FHIR R4 Bulk Data NDJSON ファイルを
書き出す。`DocumentReference` は `record.documents`
(Stage 1 の `document_enricher` が populate、選択 narrative
version により `final` docStatus に昇格) から emit。

| Option | Default | 説明 |
|---|---|---|
| `--cif-dir DIR` | **必須** | 既存 CIF ディレクトリへのパス |
| `-o, --output DIR` | `<cif>/../fhir_r4` | 出力ディレクトリ |
| `--country CODE` | `US` | `US` または `JP` |
| `--narrative-version ID` | `current` | Narrative version id (default は `current_version.txt` を参照) |

## `clinosim test-disease [DISEASE_ID]`

特定入院疾患の forced シナリオ生成 (デバッグ / golden fixture /
AD-66 patient-profile bootstrap)。`DISEASE_ID` は
`--patient-profile` 指定時は任意。

| Option | Default | 説明 |
|---|---|---|
| `--patient-profile NAME` | (未設定) | 患者 profile fixture 名またはパス (AD-66); CLI 引数は profile field を上書きし stderr `WARN` を出す |
| `-n, --count N` | 3 (または profile count) | 患者数 |
| `--severity LEVEL` | (YAML から) | severity 強制: `mild` / `moderate` / `severe` |
| `--archetype NAME` | (YAML から) | archetype 名強制 |
| `-s, --seed N` | 42 (または profile `random_seed`) | Random seed |
| `--country CODE` | US (または profile country) | Country code |
| `--format ...` | (stdout debug) | `cif` / `fhir-r4` / `csv` / `all` から 1 個以上。`-o` 必須。 |
| `-o, --output DIR` | (未設定) | 出力ディレクトリ (`--format` 指定時必須)。設定時は疾患別ミニコホートで 3-stage pipeline (structural CIF + template narrative + FHIR / CSV) を実行。 |

```bash
clinosim test-disease heart_failure_exacerbation \
  --severity severe --archetype treatment_resistant -n 3
```

## `clinosim test-encounter CONDITION_ID`

単一 ED / 外来 encounter YAML を通じて 1 (以上) の患者を simulate。

| Option | Default | 説明 |
|---|---|---|
| `-n, --count N` | 1 | 患者数 |
| `-s, --seed N` | 42 | Random seed |
| `--country CODE` | US | Country code |
| `--age N` | (サンプリング) | 患者年齢強制 |
| `--sex M/F` | (サンプリング) | 患者性別強制 |
| `--format ...` | (stdout debug) | `test-disease` と同じ |
| `-o, --output DIR` | (未設定) | 出力ディレクトリ (`--format` 指定時必須) |

```bash
clinosim test-encounter migraine --age 35 --sex F
```

## `clinosim validate`

生成データを公開ベンチマークに対して品質 check。

| Option | Default | 説明 |
|---|---|---|
| `-p, --population N` | 5000 | Population size |
| `-s, --seed N` | 42 | Random seed |
| `--country CODE` | US | Country code |

## `clinosim list-diseases`

全 32 入院疾患プロトコル (`clinosim/modules/disease/reference_data/*.yaml`)
+ 46 ED / 外来 encounter 症状
(`clinosim/modules/encounter/reference_data/*.yaml`) を表示。

## `clinosim enumerate` — 網羅的デバッグ (Issue #345)

(疾患 × severity × course_archetype) と (encounter × severity) の
各組合わせをそれぞれ 1 患者ずつ生成。集団駆動サンプリングは大 `-p`
でも rare pattern が発火しないことがあるため、`enumerate` は
決定的に全組合わせをカバーする。

| Option | Default | 説明 |
|---|---|---|
| `-o, --output DIR` | **必須** | `cif/` / `cif/narratives/template/` / `fhir_r4/` / `enumeration_manifest.json` を書き出す |
| `--level LEVEL` | `full` | `basic` (シナリオごとに 1)、`severity` (シナリオ × severity)、`full` (疾患 × severity × course_archetype) |
| `--country CODE` | `US` | `US` または `JP` |
| `--include-both-countries` | off | JP + US を 1 run で emit (case 数がおよそ倍) |
| `--seed N` | 42 | sub-seed 導出用のベース seed |
| `--yes-large` | off | coverage 爆発ガード (閾値: 2000 患者) をバイパス |
| `--format ...` | `cif fhir-r4` | `cif` / `fhir-r4` / `csv` / `all` |
| `--dry-run` | off | 計画のみ — 発見シナリオと case 数を表示、simulate / write せず |

## `clinosim diff` — snapshot diff → Bundle transaction

2 つの連続 snapshot を FHIR Bundle transaction に変換 (F3;
day-N vs day-M 追記)。export 済み FHIR ディレクトリで実行。

| Option | Default | 説明 |
|---|---|---|
| `--old DIR` | **必須** | 前 snapshot の FHIR 出力ディレクトリ |
| `--new DIR` | **必須** | 現 snapshot の FHIR 出力ディレクトリ |
| `--output-bundle PATH` | **必須** | Bundle transaction JSON 出力パス |
| `--output-summary PATH` | stdout | サマリテキスト出力パス |
| `--old-cursor DATE` | old ディレクトリ名 | 前 cursor 日付 (サマリ用) |
| `--new-cursor DATE` | new ディレクトリ名 | 現 cursor 日付 (サマリ用) |

## `clinosim regenerate-goldens`

AD-66 α-min-2c golden narrative bootstrap。
`tests/fixtures/patient_profiles/` 下の canonical 患者 profile に
対する golden を再生成。

| Option | Default | 説明 |
|---|---|---|
| `--profile NAME` \| `--all` | (どちらか必須) | 単一 profile 名、または全 profile |
| `--provider NAME` | `template` | `template` (`<name>.golden.json` を書く)、または `mock` / `bedrock` / `ollama` (`<name>.llm-<tag>.golden.json` を書く) |
| `--llm-config PATH` | (provider ごとの default) | `narrate` に渡す LLM サービス YAML |
| `--model-tag TAG` | provider 名 | LLM golden のファイル名 tag |

## `clinosim check-narratives` — 意味的 narrative-CIF ゲート

β-JP-1 chain 1b T2 意味 check: byte-diff が適用されない LLM 出力
ゲート。exit 0 = pass、1 = 検出あり。

| Option | Default | 説明 |
|---|---|---|
| `--cif-dir DIR` | **必須** | CIF ディレクトリへのパス |
| `--version ID` | **必須** | check 対象 narrative version id (例: `llm-mock`、`ollama`) |
| `--profile NAME` | (未設定) | 患者 profile — expectation を `tests/fixtures/patient_profiles/<name>.llm-expectations.yaml` に解決 |
| `--expectations PATH` | (未設定) | 明示的 expectation YAML パス (`--profile` を上書き) |
| `--report PATH` | (未設定) | `SemanticCheckReport` 全体を JSON で書き出す |

## `clinosim audit` — per-Module PR ゲート

AD-60 audit フレームワーク — 現在 6 つの per-module プラグイン
(`hai`、`antibiotic`、`order`、`imaging`、`document`、`triage`)。
`clinosim/audit/README.ja.md` と
[`../audit-cycles/`](../audit-cycles/README.ja.md) の workflow 参照。

## `clinosim dataset` — 名前付きプリセット dataset builder

4 つの名前付きプリセット (`us-100`、`us-1000`、`jp-100`、
`jp-1000`) をビルドまたは一覧表示。詳細は
[`datasets-full.ja.md`](datasets-full.ja.md)。

```bash
clinosim dataset list
clinosim dataset build jp-100 --output ./jp-100
```

## `clinosim eval` — 公開 3 軸評価

生成コホートを structural / clinical / locale の 3 軸でスコア化。
[`../eval.ja.md`](../eval.ja.md) と
[`../eval-rules.ja.md`](../eval-rules.ja.md) 参照。

## `clinosim benchmark` — P2-15 予測ベンチマークハーネス

下流 ML 予測ベンチマーク (AKI、sepsis)。
[`../benchmarks.ja.md`](../benchmarks.ja.md) と
`clinosim/benchmarks/README.ja.md` 参照。

## 典型的ワークフロー

**ローカル template のみ実行 (LLM なし、決定的):**
```bash
clinosim simulate -o ./output -p 5000 --country US --format fhir-r4
# Stage 2 template narrative + Stage 3 FHIR NDJSON が ./output 配下に出る。
```

**ローカル LLM (Ollama):**
```bash
clinosim simulate -o ./output -p 5000 --country US --format cif
clinosim narrate --cif-dir ./output/cif \
    --provider ollama --version-id ollama_en_v1
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
    --provider bedrock --version-id bedrock_sonnet_en_v1

# 結果を pull back、それから FHIR export をローカル実行
clinosim export-fhir --cif-dir ./output/cif \
    --narrative-version bedrock_sonnet_en_v1
```

EC2 + Bedrock セットアップガイドは
[../bedrock_setup.ja.md](../bedrock_setup.ja.md) 参照。

---
