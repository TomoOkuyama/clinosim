# clinosim.modules.output — Output Adapters Module

## 目的

CIF (Clinosim Intermediate Format) を読み込み、 各種実用フォーマットへ変換する **唯一の出力経路** を提供する。

clinosim のシミュレーション内部 (physiology, encounter, observation 等) は CIF を生成するのみで、 ファイル形式・標準仕様への変換は本モジュールの責務とする (AD-17)。

サポート出力フォーマット:

| Stage | フォーマット | 用途 |
|---|---|---|
| 1 | **CIF JSON** | 内部正規表現。 全構造データを 1 ファイル/エンカウンタで保存 |
| 2 | **Narrative JSON** | 自由記述ノート (入院記録・経過記録・退院サマリー)。 LLM/template 経由で生成 |
| 3 | **FHIR R4 NDJSON** | [HL7 FHIR Bulk Data Access](https://hl7.org/fhir/uv/bulkdata/) 仕様準拠の Bulk Export |
| 3 | **CSV** | 解析・統計利用向けフラットテーブル |

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **CIF is the source of truth** | 全アダプタは CIF 構造データのみを読む。 シミュレーション内部状態には触れない |
| 2 | **Stage 分離** | 構造データ生成 (Stage 1) と物語生成 (Stage 2) と外部フォーマット変換 (Stage 3) を独立実行可能にする |
| 3 | **Re-runnable narratives** | LLM だけ差し替えて narrative を再生成できる (シミュレーション再実行不要) |
| 4 | **標準準拠** | FHIR R4 / Bulk Data Access / JP Core / US Core の公式仕様に従う |
| 5 | **コード→表示は codes モジュール経由** | 表示テキストは出力時に `clinosim.codes.lookup()` で解決 (国別言語フォールバック) |

## ディレクトリ構造

```
clinosim/modules/output/
├── __init__.py
├── README.md                    # 本ドキュメント
├── SPEC.md
├── cif_writer.py                # Stage 1: CIFDataset → JSON ファイル群
├── document_generator.py        # Stage 2: 構造 CIF → narrative CIF (5 doc types)
├── hospital_course_extractor.py # Stage 2: CIF → deterministic clinical facts
├── fhir_r4_adapter.py           # Stage 3a: CIF → FHIR R4 NDJSON (Bulk Data)
└── csv_adapter.py               # Stage 3b: CIF → 平たい CSV テーブル群
```

## API リファレンス

### `write_cif(dataset: CIFDataset, output_dir: str) -> None`

`CIFDataset` をディスク上の JSON ファイル群に書き出す (Stage 1)。

**生成されるファイル**:

```
<output_dir>/
├── metadata.json                          # データセットメタ情報
├── hospital.json                          # 病院ロスター + config
└── structural/
    └── patients/
        ├── ENC-0001.json                  # エンカウンタ単位 (再入院対応)
        ├── ENC-0002.json
        └── ...
```

エンカウンタ単位で 1 ファイルを生成することで、 同一患者の複数入院 (readmission) や外来訪問を独立した CIF レコードとして扱える。 各レコードは `dataclasses.asdict()` で平坦化され、 `datetime` / `date` / `timedelta` / `Enum` を扱う `_CIFEncoder` で JSON 化する。

```python
from clinosim.modules.output.cif_writer import write_cif

write_cif(dataset, "./output/run_001")
```

### `convert_cif_to_fhir(cif_dir: str, output_dir: str, country: str = "US") -> None`

CIF を **FHIR R4 Bulk Data Export** 形式の NDJSON 群に変換する。

[HL7 FHIR Bulk Data Access (Flat FHIR)](https://hl7.org/fhir/uv/bulkdata/) 仕様に従い、 リソース型ごとに 1 つの `.ndjson` ファイル (1 行 = 1 リソース)、 およびトランザクションを記述する `manifest.json` を生成する。

**生成されるファイル**:

```
<output_dir>/
├── manifest.json                # Bulk Data Export manifest
├── Patient.ndjson               # 患者マスター (de-dup)
├── Encounter.ndjson             # 入院/外来エンカウンタ
├── Condition.ndjson             # 診断
├── AllergyIntolerance.ndjson    # アレルギー (de-dup)
├── Observation.ndjson           # ラボ + バイタル
├── MedicationRequest.ndjson     # 処方
├── MedicationAdministration.ndjson # MAR (実投与)
├── Procedure.ndjson             # 手技
├── Practitioner.ndjson          # スタッフ (de-dup)
├── PractitionerRole.ndjson      # スタッフロール (de-dup)
├── Organization.ndjson          # 病院 + 診療科 (de-dup)
├── Location.ndjson              # 病棟 + ベッド + 手術室 (de-dup)
└── DocumentReference.ndjson     # 臨床文書 (narrative version 指定時)
```

**Dedup ロジック**: `Patient`, `Practitioner`, `PractitionerRole`, `Organization`, `Location`, `AllergyIntolerance` は患者横断のマスターリソースのため、 `id` で重複排除して 1 度だけ書き込む。 一方 `Encounter`, `Observation`, `MedicationAdministration` 等のイベント系リソースは全件出力する。

**Manifest 形式**:

```json
{
  "transactionTime": "2026-04-06T10:30:00",
  "request": "clinosim generate (country=US)",
  "requiresAccessToken": false,
  "output": [
    {"type": "Patient", "url": "Patient.ndjson"},
    {"type": "Encounter", "url": "Encounter.ndjson"}
  ],
  "error": []
}
```

```python
from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir

convert_cif_to_fhir("./output/run_001", "./output/run_001/fhir", country="JP")
```

**国別の振る舞い**:

- `country="US"`: 表示テキストは英語、 ICD-10-CM / RxNorm / CPT / LOINC を主体とする
- `country="JP"`: 表示テキストは日本語、 ICD-10 / YJ コード / K コード / JLAC10 を主体とし、 病院名・診療科名も日本語化

### `convert_cif_to_csv(cif_dir: str, output_dir: str) -> None`

CIF を解析・統計利用向けの **フラット CSV** に変換する。

**生成されるテーブル**:

| ファイル | 内容 |
|---|---|
| `patients.csv` | 患者デモグラフィクス + 慢性疾患 (パイプ区切り) |
| `encounters.csv` | 入院/外来エピソード (再入院フラグ含む) |
| `diagnoses.csv` | 入院時/退院時診断 + ground truth + 合併症 |
| `lab_results.csv` | 検査結果 (1 行 = 1 結果) |
| `vital_signs.csv` | バイタルサイン時系列 |
| `orders.csv` | オーダー (検査・処方・画像等) |
| `medication_administrations.csv` | MAR (実投与記録) |
| `procedures.csv` | 手技 (手術・ベッドサイド) |
| `rehab_sessions.csv` | リハビリセッション |
| `intake_output.csv` | I/O 記録 |
| `adl_assessments.csv` | ADL 評価 (Barthel 等) |
| `prescriptions.csv` | 退院処方 |

```python
from clinosim.modules.output.csv_adapter import convert_cif_to_csv

convert_cif_to_csv("./output/run_001", "./output/run_001/csv")
```

### `generate_narratives(cif_dir, llm_service, version_id=None, language="en", enabled_tasks=None) -> str`

構造 CIF を読み、 各患者について臨床文書を生成する (Stage 2)。 LLM は `LLMService` 経由のため、 mode を `"none"` / `"template"` / `"llm"` で切り替えられる (AD-11)。

**生成されるノート種別 (Tier A+B)**:

| 文書 | LOINC | 生成条件 |
|---|---|---|
| `admission_hp` | 34117-2 | 全入院 |
| `discharge_summary` | 18842-5 | 全退院 |
| `death_summary` | 69730-0 | 死亡退院 |
| `operative_note` | 11504-8 | 手術 |
| `procedure_note` | 28570-0 | 侵襲的ベッドサイド処置 |

**補助モジュール**:
- `hospital_course_extractor.py` — CIF からラボ動向、治療タイムライン、入院経過イベント、臨床ガイダンスを決定論的に抽出
- `document_generator.py` — 抽出されたファクトを LLM プロンプト変数に変換し、各文書を生成

**日本語対応 (AD-42/43)**:
- `language="ja"` 指定時、CRP を mg/L→mg/dL にコード側で変換 (LLM に変換させない)
- スタッフ名は「医師」サフィックス付きで LLM に渡される

**バージョン管理**: `narratives/<version_id>/documents/<encounter_id>/` 配下に文書 JSON を保存し、 同 dir に `manifest.json` (LLM mode, モデル, コスト, 文書数) を書き出す。 同じ構造 CIF に対して異なる LLM/言語で複数バージョンを生成・保持できる。

```python
from clinosim.modules.output.document_generator import generate_narratives
from clinosim.modules.llm_service.factory import build_from_config_file

llm = build_from_config_file("clinosim/config/llm_service.bedrock.yaml")
version_id = generate_narratives("./output/run_001/cif", llm, language="ja")
```

## データ構造

### CIF 出力ディレクトリレイアウト (全 stage 完了後)

```
<output_dir>/
├── metadata.json
├── hospital.json
├── structural/
│   └── patients/
│       └── <encounter_id>.json
├── narratives/
│   ├── current_version.txt
│   └── <version_id>/
│       ├── manifest.json
│       └── patients/
│           └── <encounter_id>.json
├── fhir/                                  # convert_cif_to_fhir の出力先
│   ├── manifest.json
│   ├── Patient.ndjson
│   └── ...
└── csv/                                   # convert_cif_to_csv の出力先
    ├── patients.csv
    └── ...
```

## 使用例

### 完全パイプライン: シミュレーション → 構造 CIF → narrative → FHIR + CSV

```python
from clinosim.simulator import Simulator
from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.output.narrative_generator import generate_narratives
from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir
from clinosim.modules.output.csv_adapter import convert_cif_to_csv
from clinosim.modules.llm_service.engine import LLMService

# Stage 0: simulate
sim = Simulator(country="JP", seed=42)
dataset = sim.run(n_patients=10)

# Stage 1: structural CIF
out = "./output/run_001"
write_cif(dataset, out)

# Stage 2: narratives (template mode, no LLM call)
generate_narratives(out, LLMService(mode="template"), language="ja")

# Stage 3: external formats
convert_cif_to_fhir(out, f"{out}/fhir", country="JP")
convert_cif_to_csv(out, f"{out}/csv")
```

### Narrative の再生成 (シミュレーション再実行なし)

```python
# 同じ構造 CIF に対して異なる LLM で narrative を再生成
llm_local = LLMService(mode="llm", narrative_provider=ollama_provider)
generate_narratives("./output/run_001", llm_local,
                    version_id="ollama_llama3_v1", language="ja")
```

## 依存関係

- `clinosim.types.output.CIFDataset` — Stage 1 入力型
- `clinosim.codes` — code → display 解決 (FHIR adapter)
- `clinosim.locale.loader` — locale 別の用語/コードマッピング/参照範囲
- `clinosim.modules.llm_service` — narrative 生成 (AD-11)

本モジュールから他のシミュレーションモジュール (physiology, encounter 等) は **呼び出さない**。 シミュレーション完了後の純粋なファイル変換のみ。

## 出力フォーマット仕様の権威ソース

| フォーマット | 仕様 |
|---|---|
| FHIR R4 | [HL7 FHIR R4](https://hl7.org/fhir/R4/) |
| FHIR Bulk Data Access | [HL7 SMART Bulk Data Access (Flat FHIR)](https://hl7.org/fhir/uv/bulkdata/) |
| US Core Profile | [HL7 US Core](https://hl7.org/fhir/us/core/) |
| JP Core Profile | [HL7 FHIR JP Core](https://jpfhir.jp/fhir/core/) |
| NDJSON | [ndjson.org](http://ndjson.org/) |

## 既知の制約

- Bundle 形式 (`Bundle.entry[]` ラップ) は出力しない。 NDJSON のみ
- `MedicationStatement` (在宅薬), `CarePlan`, `Goal` は未実装
- CSV はネスト構造をパイプ区切りで平坦化する。 完全な可逆変換ではない
- Progress Note (日次 SOAP 記録) は Tier C として将来計画 (v0.3)
