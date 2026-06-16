# clinosim.modules.output — Output Adapters Module

## 目的

CIF (Clinosim Intermediate Format) を読み込み、 各種実用フォーマットへ変換する **唯一の出力経路** を提供する。

clinosim のシミュレーション内部 (physiology, encounter, observation 等) は CIF を生成するのみで、 ファイル形式・標準仕様への変換は本モジュールの責務とする (AD-17)。

サポート出力フォーマット:

| Stage | フォーマット | 用途 |
|---|---|---|
| 1 | **CIF JSON** | 内部正規表現。 全構造データを 1 ファイル/エンカウンタで保存 |
| 2 | **Narrative JSON** | 臨床文書 (入院時記録・退院サマリー・手術記録・処置記録・死亡時記録)。 LLM/template 経由で生成 |
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
| 6 | **多言語 coding** | Condition/Procedure は primary + interop の dual coding entry を出力 (AD-46) |
| 7 | **Enrichment は言語中立** | narrative 向けデータ抽出は英語で統一。LLM が翻訳。コード→表示名とCRP単位変換のみ locale 依存 (AD-44) |

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

## FHIR R4 出力の詳細

### リソース型一覧

```
<output_dir>/
├── manifest.json                # Bulk Data Export manifest
├── Patient.ndjson               # 患者マスター (de-dup)
├── Encounter.ndjson             # 入院/外来エンカウンタ
├── Condition.ndjson             # 診断 (multilingual coding + 略語 text)
├── AllergyIntolerance.ndjson    # アレルギー (JP: ペニシリン等)
├── Coverage.ndjson              # 保険資格 (JPのみ; JP Core 記号/番号/枝番, AD-54)
├── Observation.ndjson           # ラボ + バイタル + 職業 + 微生物 (referenceRange + interpretation)
├── DiagnosticReport.ndjson      # 微生物培養レポート (感染症, AD-55)
├── Specimen.ndjson              # 培養検体 (血液/尿/喀痰/創部)
├── MedicationRequest.ndjson     # 処方 (protocol prefix stripped)
├── MedicationAdministration.ndjson # MAR (実投与)
├── Procedure.ndjson             # 手技 (multilingual coding: K-code + CPT)
├── Practitioner.ndjson          # スタッフ (de-dup)
├── PractitionerRole.ndjson      # スタッフロール (de-dup)
├── Organization.ndjson          # 病院 + 診療科 + 保険者 (de-dup)
├── Location.ndjson              # 病棟 + ベッド + 手術室 (de-dup)
└── DocumentReference.ndjson     # 臨床文書 (narrative version 指定時)
```

### リソースビルダー・レジストリ (AD-56)

`_build_bundle()` は `_BUNDLE_BUILDERS`(`(BundleContext) -> list[resource]` のリスト)を
順に実行してエントリを生成する。**新しいリソース型は `register_bundle_builder()` で
登録するだけ**で追加でき、`_build_bundle()` 本体の編集は不要。登録順 = 出力順。
opt-in モジュールは CIF(`CIFPatientRecord.extensions[<module>]`)を読んでビルダーを
登録する(`identity` モジュールには非依存 — output が CIF を読む)。

### 多言語 coding (AD-46)

Condition と Procedure は dual coding entry を出力:

```json
{
  "coding": [
    {"system": "http://hl7.org/fhir/sid/icd-10", "code": "J44.1",
     "display": "その他の慢性閉塞性肺疾患"},
    {"system": "http://hl7.org/fhir/sid/icd-10", "code": "J44.1",
     "display": "Other chronic obstructive pulmonary disease"}
  ],
  "text": "COPD（慢性閉塞性肺疾患）"
}
```

- `_build_diagnosis_codeable_concept()` が icd-10/icd-10-cm を cross-system fallback で解決
- `code.text` には `_CONDITION_SHORT_NAME` の臨床略語 (COPD, CHF, CKD, DM, AF 等) を使用 (AD-49)
- display==code は **絶対に出力しない** (fallback: "(display unavailable)")

### Observation referenceRange / interpretation (AD-47)

- **Lab**: `referenceRange` は locale YAML (JCCLS共用基準範囲 for JP, Tietz/Mayo for US) から生成。`interpretation` は value vs referenceRange から再計算 (CIF flag に優先)。0 不整合。
- **Vital**: normal + critical (panic) の 2 referenceRange entry。text は locale 対応 (成人正常範囲 / Normal adult range)。SpO2 は crit_high=None (100%は HH にしない)。

### 薬剤名処理

- `_strip_protocol_prefix()`: `"DVT_prophylaxis: Enoxaparin 2000IU SC daily"` → `"Enoxaparin 2000IU SC daily"` (AD-50)
- JP: `_localize_drug_name()` で `drug_names_ja.yaml` (120+エントリ) + `_localize_dosage_terms()` で用量用語翻訳
- US: 英語のまま pass-through
- 空白の drug_name を持つ MedicationRequest/Administration はスキップ (フィルタ)

### JP 固有の FHIR ローカライズ

| Resource | Field | 変換例 |
|---|---|---|
| Patient | contact.relationship.text | spouse → 配偶者 |
| Encounter | class.display | ambulatory → 外来 |
| Condition | category.display | Encounter Diagnosis → エンカウンター診断 |
| Condition | severity.display | Mild → 軽度 |
| Observation | category.display | Laboratory → 検体検査 |
| Observation | interpretation.display | Normal → 正常, High → 高値 |
| Observation | referenceRange.text | Normal adult range → 成人正常範囲 |
| Organization | type.display | Hospital Department → 診療科 |
| Location | name | Emergency Room → 救急外来 |
| Procedure | code.display | code_lookup("k-codes", code, "ja") |
| MedicationRequest | medication.text | _localize_drug_name() |
| AllergyIntolerance | code.text/display | Penicillin → ペニシリン |

**US 出力時**: 上記全てが英語のまま出力 (日本語混入 0)。

### Procedure code 辞書方式 (AD-48)

CIF には `procedure_name` を格納しない (AD-30)。表示名は出力時に code_lookup:

```python
_procedure_display(code, lang, fallback)  # k-codes.yaml → cpt.yaml → fallback
```

K-code (JP) + CPT (US) の dual coding:
```json
{"coding": [
  {"system": "urn:oid:1.2.392.200119.4.401", "code": "K0461", "display": "大腿骨観血的整復固定術"},
  {"system": "http://www.ama-assn.org/go/cpt", "code": "27236", "display": "Open treatment of femoral fracture..."}
]}
```

## Stage 2: Narrative 生成

### Enrichment アーキテクチャ (AD-44)

```
CIF record
  ↓
Enrichment (言語中立 — 英語テキスト)
  ├── hospital_course_bullets: ["Day 0: Admitted with ...", ...]
  ├── lab_trend_bullets: ["CRP: admission 7.94mg/dL → peak ..."]  ← CRP単位変換のみ locale依存
  ├── treatment_timeline: ["Day 0: Started Ceftriaxone IV", ...]
  ├── home_medications: ["Amlodipine 5mg", ...]  ← 英語のまま
  ├── discharge_medications: ["Amoxicillin 500mg PO tid"]  ← 英語のまま
  ├── admission_diagnosis: "急性心筋梗塞"  ← code_lookup(icd, code, lang)
  └── procedures_performed: ["laparoscopic cholecystectomy ..."]  ← _resolve_procedure_name(en)
  ↓
LLM prompt (prompts/ja/*.yaml or prompts/en/*.yaml)
  ↓
Generated text (JP or EN)
```

**修正する際の注意**: enrichment 関数に language 引数を追加して翻訳しようとしないこと。
A/B テストで LLM が十分に翻訳できることを確認済み (AD-44)。

### 主要ヘルパー関数

| 関数 | ファイル | 役割 |
|---|---|---|
| `_resolve_procedure_name(proc, lang)` | hospital_course_extractor.py | code_lookup で手術名解決 |
| `_home_meds(patient)` | document_generator.py | 常用薬リスト (英語) |
| `_allergies(patient)` | document_generator.py | アレルギーリスト (英語) |
| `_initial_labs(record, language)` | document_generator.py | 異常ラボ抽出 (CRP変換のみ locale) |
| `_pmh(patient, language)` | document_generator.py | 既往歴 (code_lookup で表示名解決) |
| `_resolve_dx(code, system, language)` | document_generator.py | 診断名 (code_lookup) |
| `extract_hospital_course(record, language)` | hospital_course_extractor.py | 入院経過ファクト |
| `format_lab_trends(trends, language)` | hospital_course_extractor.py | ラボ動向 (CRP変換) |
| `extract_treatment_timeline(record)` | hospital_course_extractor.py | 治療タイムライン (英語) |

## 依存関係

- `clinosim.types.output.CIFDataset` — Stage 1 入力型
- `clinosim.codes` — code → display 解決 (FHIR adapter, enrichment)
- `clinosim.locale.loader` — locale 別の用語/コードマッピング/参照範囲
- `clinosim.locale.shared.drug_names_ja.yaml` — JP 薬品名辞書 (FHIR adapter)
- `clinosim.modules.llm_service` — narrative 生成 (AD-11)

本モジュールから他のシミュレーションモジュール (physiology, encounter 等) は **呼び出さない**。

## 修正ガイド

### 新しい薬品の JP 名を追加する

`clinosim/locale/shared/drug_names_ja.yaml` にエントリ追加:
```yaml
NewDrugName: "新薬日本語名"
```
FHIR adapter が自動的に JP 出力時に使用。

### 新しい Condition 略語を追加する

`fhir_r4_adapter.py` の `_CONDITION_SHORT_NAME` にエントリ追加:
```python
"K70": {"en": "Alcoholic liver disease", "ja": "アルコール性肝疾患"},
```

### 新しい Procedure コードを追加する

`clinosim/codes/data/k-codes.yaml` と `cpt.yaml` にエントリ追加:
```yaml
K999:
  en: New procedure name
  ja: 新しい手術名
```
FHIR adapter が `code_lookup` で自動使用。

### 新しい JP ローカライズ項目を追加する

`fhir_r4_adapter.py` の該当辞書に追加:
- `_CLASS_DISPLAY_JA`, `_CATEGORY_DISPLAY_JA`, `_SEVERITY_DISPLAY_JA`
- `_INTERPRETATION_DISPLAY_JA`, `_RELATIONSHIP_DISPLAY_JA`
- `_ORG_TYPE_DISPLAY_JA`, `_LOCATION_TYPE_DISPLAY_JA`

### 新しい Observation referenceRange を追加する

`clinosim/locale/jp/reference_range_lab.yaml` (JP) / `us/reference_range_lab.yaml` (US) にエントリ追加。
sex-specific range は `sex: "M"` / `sex: "F"` で区別。

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
- 薬品名は CIF に英語で格納 (RxNorm 完全連携は未完了)。FHIR JP 出力時は `drug_names_ja.yaml` 辞書で変換
