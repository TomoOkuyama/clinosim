## 6.1 コードシステムモジュール (`clinosim/codes/`)

### 問題

当初 terminology ファイル (例: ICD コード → 表示名) は
`clinosim/locale/jp/terminology_diagnosis.yaml` 等のパスに配置され
ていた。これは 2 つの問題を生んだ:

1. **誤分類**: ICD-10-CM は国際標準であり文化固有データセットで
   はない。`locale/jp/` に置くと locale-scoped 所有を示唆するが、
   実際には翻訳されているだけで同一のコード値である。
2. **翻訳重複**: JP と US をサポートすると同一 ICD コードが 2 つ
   のファイルに個別エントリを持つ。片方を更新して他方を更新し忘
   れると mismatch につながる。
3. **CIF 冗長性**: `ClinicalDiagnosis` は
   `discharge_diagnosis_code` と `discharge_diagnosis_name` の両方
   を保存していた。name は code + locale の派生物だが、別々に保存
   されているため drift の余地があった。

### 決定 (AD-30、AD-33、AD-35)

**locale-independent** で臨床コードシステムの single source of
truth となる新規 `clinosim/codes/` モジュールを作成する。

```
clinosim/codes/
├── __init__.py          # public API
├── loader.py            # lookup() with language fallback
├── README.md            # module documentation
└── data/
    ├── icd-10-cm.yaml   # 224 コード、全て EN、多くは JA
    ├── icd-10.yaml      # WHO 版 (110 コード)
    ├── loinc.yaml       # 59 コード
    ├── jlac10.yaml      # 30 コード
    ├── rxnorm.yaml      # 68 コード
    ├── yj.yaml          # 39 コード
    ├── cpt.yaml         # 25 コード
    └── k-codes.yaml     # 2 コード
```

### スキーマ

```yaml
metadata:
  name: "ICD-10-CM"
  uri: "http://hl7.org/fhir/sid/icd-10-cm"   # FHIR canonical system URI
  version: "2024"
  description: "..."

codes:
  N10:
    en: "Acute tubulo-interstitial nephritis"   # REQUIRED
    ja: "急性腎盂腎炎"                          # optional
  J18.9:
    en: "Pneumonia, unspecified organism"
    ja: "肺炎，詳細不明"
```

### 原則

1. **English-first**: 全コードは `en` field を必須とする。他言語
   は任意の翻訳属性。ローダーは要求された言語が存在しなければ英語
   に、次にコード自身にフォールバックする。

2. **権威ある情報源**: コード値と英語テキストは CMS (ICD-10-CM)、
   NLM (RxNorm)、Regenstrief (LOINC)、AMA (CPT)、WHO (ICD-10)、
   JCCLS (JLAC10)、MHLW (YJ コード、K コード) の公式定義に従う。

3. **Locale-independent**: `codes/` は `locale/` と同レベルであり、
   その **中には** 置かない。コードシステムは国際標準。

4. **単一 lookup API**:
   ```python
   from clinosim.codes import lookup, get_system_uri
   lookup("icd-10-cm", "N10", "en")  # → "Acute tubulo-interstitial nephritis"
   lookup("icd-10-cm", "N10", "ja")  # → "急性腎盂腎炎"
   get_system_uri("loinc")           # → "http://loinc.org"
   ```

### CIF への影響

`ClinicalDiagnosis` は簡素化 — `*_name` field を除去、`*_system`
を追加:

```python
# Before
@dataclass
class ClinicalDiagnosis:
    admission_diagnosis_code: str
    admission_diagnosis_name: str          # ← 除去
    discharge_diagnosis_code: str
    discharge_diagnosis_name: str          # ← 除去

# After
@dataclass
class ClinicalDiagnosis:
    admission_diagnosis_code: str
    admission_diagnosis_system: str = "icd-10-cm"   # ← 追加
    discharge_diagnosis_code: str
    discharge_diagnosis_system: str = "icd-10-cm"   # ← 追加
```

`ChronicCondition.name` も同様に除去された。表示テキストは出力
時に FHIR / CSV / narrative の adapter が `clinosim.codes.lookup()`
を呼んで解決するようになった。

### migration 後の locale モジュール

`clinosim/locale/` は **文化 / 国依存** データのみを含む:

- `names.yaml` — 氏名生成 (JP は漢字 + 読み、US は given/family)
- `addresses.yaml` — 47 都道府県 / 50 州 + 郵便番号パターン
- `demographics.yaml` — 人口年齢分布、疾患 incidence
- `formatting.yaml` — 日付と単位のフォーマット規則
- `reference_range_lab.yaml` — JCCLS / Tietz 検査基準範囲
- `code_mapping_*.yaml` — 内部検査名 → 標準コード (内部名 "WBC"
  は clinosim 実装詳細で標準ではないため、ここに残る)

古い `terminology_*.yaml` ファイルは削除された。

---

## 6.2 FHIR Bulk Data Export NDJSON (AD-31)

### 問題

元の FHIR R4 adapter は encounter ごとに 1 つの Bundle JSON ファ
イル (`ENC-POP-XXXXXX-NNNNNN.json`) を書いていた。動作はするが
欠点があった:

1. **ファイル爆発**: 60k 医療圏病院で 153,530 ファイル
2. **wrapping オーバーヘッド**: 各 Bundle が冗長な
   `Bundle.entry[]` wrapper を持つ
3. **Resource id 重複**: vital sign ID が患者 encounter 間で衝突
4. **標準形式でない**: 実 EHR ベンダー (Epic、Cerner) は per-patient
   bundle ではなく FHIR Bulk Data Access spec (resource type ごとの
   NDJSON) 経由で export する

### 決定 (AD-31)

per-encounter Bundle 出力を HL7 FHIR Bulk Data Access 準拠の
NDJSON に置き換える:

```
output/fhir_r4/
├── manifest.json                           # Bulk Data manifest
├── _facility.json                          # Org + Location master Bundle
├── Patient.ndjson                          # 1 患者 1 行
├── Encounter.ndjson                        # 1 encounter 1 行
├── Observation.ndjson                      # labs + vitals (LOINC)
├── Condition.ndjson                        # ICD-10-CM
├── MedicationRequest.ndjson                # RxNorm
├── MedicationAdministration.ndjson         # MAR
├── Procedure.ndjson                        # CPT
├── AllergyIntolerance.ndjson               # 患者レベル
├── Practitioner.ndjson                     # スタッフマスタ
├── PractitionerRole.ndjson                 # 専門科 + 病棟
├── Organization.ndjson                     # 病院 + 診療科
└── Location.ndjson                         # 病棟 + ベッド
```

### Resource id 一意性

critical な FHIR R4 不変条件: `Resource.id` はその resource type
内で一意でなければならない。古い per-encounter Bundle 方式は各
Bundle が自己完結だったため違反を隠していた。NDJSON に集約されると
衝突が可視化された。

`encounter_id` を resource id に含めることで修正:

- Lab obs: `lab-{encounter_id}-{seq}` (`lab-{patient_id}-{seq}` から)
- Vital obs: `vs-{encounter_id}-{seq}-{field}`
- MAR: `mar-{encounter_id}-{seq}`
- MedRequest: `{encounter_id}-{order_id}` (プレフィックス付き)
- Procedure: `{encounter_id}-{procedure_id}` (プレフィックス付き)
- Condition (encounter dx): `cond-{encounter_id}-primary`
- Condition (chronic): `cond-{encounter_id}-chronic-{idx}`

患者レベル resource (Patient、Practitioner、AllergyIntolerance)
は再 emit ではなく NDJSON writer 内で重複排除される。

### Manifest 形式

[HL7 FHIR Bulk Data Access spec](https://hl7.org/fhir/uv/bulkdata/)
に従う:

```json
{
  "transactionTime": "2026-04-08T17:30:00",
  "request": "clinosim generate (country=US)",
  "requiresAccessToken": false,
  "output": [
    {"type": "Patient", "url": "Patient.ndjson"},
    {"type": "Encounter", "url": "Encounter.ndjson"},
    ...
  ],
  "error": []
}
```

この形式は Bulk Data export を期待する任意の FHIR クライアント
(Epic や Cerner の統合ツール含む) が consume 可能。

### サイズ影響

US 50 床病院、catchment 30k、1 年:
- 旧形式: 153,530 ファイル、合計 5.7 GB
- 新形式: 13 ファイル、合計 1.3 GB (JSON wrapping 除去で -77%
  サイズ削減)

---

## 6.3 Snapshot 日付セマンティクス (AD-32)

### 問題

シミュレータはシミュレーション期間内に発生する全 encounter を完了
まで生成していた (全 encounter が `discharge_datetime` を持つ)。
これは「全患者退院済」データセットを生成し、現在入院中の患者を
含む実 EHR snapshot を反映しなかった。

現在入院中の患者向け可視化ツールや AI モデル (例: NEWS2 alert
system) にとってこれは大きなギャップだった。

### 決定 (AD-32)

**snapshot 日付** セマンティクスを導入:

- `--end YYYY-MM-DD` フラグ = snapshot 日付 (デフォルトは今日)
- `--start YYYY-MM-DD` デフォルトは `--end - 1 年`
- snapshot 日付以降のライフイベント生成なし
- `discharge_datetime` が snapshot 日付以降になる入院患者は切り
  詰められる:
  - `Encounter.status = "in-progress"`
  - `discharge_datetime = None`
  - `discharge_disposition = ""`
  - `discharging_physician_id = ""`
  - Lab/vital/order/MAR レコードは snapshot 日以下にフィルタ
  - 退院処方は発行されない
- Primary `Condition.clinicalStatus = "active"` (完了したものは
  `resolved` に対して) — in-progress encounter 用
- 死亡はこのルールから免除 (死亡患者は常に `dischargeDisposition = "exp"`
  で「completed」)

### 結果

平均 LOS 5 日、~3 入院/日 の典型的 50 床病院は、任意時点で ~15
in-progress encounter (~30% 稼働率) を produce する。より高い
catchment と長い LOS では現実的な 80% ベッド稼働率に近づく。

これにより以下のリアルな EHR snapshot 生成が可能になる:
- NEWS2 / 早期警戒 alert system
- ベッド管理 dashboard
- リアルタイム臨床意思決定支援訓練データ

---

## 6.4 Hospital 設定駆動レイアウト (AD-34)

### 問題

病院の物理レイアウト (どの診療科が存在するか、どの病棟がどの
専門科に属するか、病棟あたり何ベッドか) は hardcode またはランダム
割り当てだった。これは以下を生んだ:

1. **不整合な FHIR データ**: encounter が存在しない病棟にいると
   主張
2. **スタッフ不整合**: PractitionerRole の専門科が Encounter
   serviceType と一致しない
3. **ベッド容量モデルなし**: 稼働率制限を強制する方法がない

### 決定 (AD-34)

Hospital 設定 YAML が完全な物理・組織レイアウトを定義:

```yaml
# clinosim/config/hospital_operations.yaml (50 床病院)
recommended_population: 60000

available_departments:
  - internal_medicine
  - cardiology
  - gastroenterology
  - general_surgery
  - orthopedics
  - emergency_medicine
  - primary_care

department_rollup:
  pulmonology: internal_medicine    # 疾患 YAML は pulmonology、病院は IM
  neurology: internal_medicine
  neurosurgery: general_surgery
  trauma_surgery: general_surgery

wards:
  internal_medicine: ["4E", "4W"]
  cardiology: ["5E"]
  gastroenterology: ["5W"]
  general_surgery: ["3E"]
  orthopedics: ["3W"]
  emergency_medicine: ["ER"]
  primary_care: ["OPD"]

ward_capacity:
  "4E": 10
  "4W": 10
  "5E": 8
  "5W": 8
  "3E": 8
  "3W": 6
```

### 波及効果

1. **疾患 → 診療科 解決**: `disease.department` は `department_rollup`
   経由で `available_departments` の 1 つに roll-up される。
   pulmonology を持たない病院の pulmonology 疾患は
   `internal_medicine` にルーティングされる。

2. **スタッフ生成**: `generate_roster()` は `available_departments`
   に対してのみ医師を作成する。看護師は `wards` に分散配置
   (`ward_capacity` に比例して各病棟は ~6 名の看護師を持つ)。

3. **ベッド割当**: encounter が作成されると `bed_number` は
   `1..ward_capacity[ward_id]` からサンプリング。「601-3」のよう
   なランダムベッド番号はもうない。

4. **FHIR Location リソース**: `_facility.json` は病棟ごとに 1
   `Location` (physicalType=wa) とベッドごとに 1 (physicalType=bd、
   病棟の `partOf`) を含む。Encounter はベッド Location を参照
   し、それが `partOf` 経由で病棟を参照。

5. **PractitionerRole.location**: 看護師は roster エントリで病棟に
   割り当てられ、PractitionerRole.location reference に反映される。

これにより病院テンプレート (`hospital_operations.yaml` for 50 床、
`hospital_small.yaml` for 10 床) は単なるサイズラベルではなく、
本当に異なる病院になった。

---

## 6.5 モジュール一覧の更新

現行モジュール数は v0.1-alpha を超えて成長した:

```
clinosim/
├── codes/                  ★ NEW (AD-30、AD-33、AD-35)
├── locale/
├── config/
├── types/
├── modules/
│   ├── disease/            (32 疾患 YAML)
│   ├── encounter/          (46 ED/外来 YAML)
│   ├── physiology/
│   ├── clinical_course/
│   ├── diagnosis/
│   ├── observation/
│   ├── order/
│   ├── procedure/          ★ NEW (以前空、現在 15 ベッドサイド手技)
│   ├── population/
│   ├── patient/
│   ├── staff/              (AD-34 以降 ward-aware)
│   ├── facility/           ★ NEW README (M/M/1 待ち行列)
│   ├── healthcare_system/
│   ├── output/             (AD-31 以降 Bulk Data NDJSON)
│   ├── llm_service/
│   └── validator/
└── simulator/              (オーケストレーション: engine、inpatient、emergency、outpatient)
```

各モジュールは API リファレンスと設計ノート付きの独自 README.md
を持つ。

---

## 6.6 現実的な vital sign 測定パターン

### 問題

初期実装は全 6 つの vital sign (T、HR、BP、RR、SpO2) を各測定時刻
に同一タイムスタンプで生成していた。これは非現実的だった:

- 外来 HTN 訪問: BP と HR のみ測定 (全 6 つではない)
- 連続モニタリング: HR と SpO2 は 1-2h 毎、フル vitals は q6h のみ
- 全 6 field が同一タイムスタンプというのは妥当性を欠く

### 決定

1. **入院**: acuity に基づく定期フル vitals (q4h–q8h) と、不安定 /
   呼吸器疾患患者向け連続モニタリング (HR + SpO2 のみ 2h 毎)、
   加えてイベント駆動再測定 (発熱後の T-only 再測定) を分離。

2. **外来**: 訪問タイプと慢性疾患による vital subset:
   - HTN/DM/IHD フォローアップ: BP + HR
   - HF: BP + HR + 体重 + SpO2
   - COPD: BP + HR + SpO2 + RR
   - 定期健診: フル

3. **field 別タイムスタンプオフセット** (FHIR adapter 内):
   - HR / BP 同時 (同じデバイスサイクル)
   - SpO2: +5s
   - 体温: +30s
   - RR: +60s

これは NEWS2 互換の vital データを臨床的に妥当な形で produce する。

---

## 6.7 NEWS2 / 早期警戒 vital データ

NEWS2 (National Early Warning Score 2) alert system をサポート
するため、vitals は以下を含むようになった:

- **AVPU 意識レベル** (Alert / Voice / Pain / Unresponsive)
  - LOINC コード 80288-4
  - SNOMED concept value (Alert は 248234008 等)
  - `state.perfusion_status` と疾患タイプから推論

- **補助酸素流量** (L/min)
  - LOINC コード 3151-8
  - 酸素供給デバイス (nasal_cannula、simple_mask、non-rebreather)
    を含む
  - SpO2 < 92 または呼吸器疾患に基づいてアクティブ化

これら 2 つの追加 Observation type は該当時に標準 vitals とともに
emit される。NEWS2 スコアは任意の in-progress encounter の最新
observation から計算可能。

---

## 6.8 更新 ADR 一覧 (Part 6 追加分)

| ADR | 日付 | タイトル |
|---|---|---|
| AD-28 | 2026-04-06 | 診断 vs ground truth 分離 (ConditionEvent vs ClinicalDiagnosis) |
| AD-29 | 2026-04-06 | 尤度比 (Bayesian update) による診断精度 |
| AD-30 | 2026-04-08 | Code が唯一の真実: CIF はコードのみ保持、表示テキストを持たない |
| AD-31 | 2026-04-08 | FHIR Bulk Data Export NDJSON (encounter ごとの Bundle を置換) |
| AD-32 | 2026-04-08 | 進行中 encounter を含む snapshot 日付セマンティクス |
| AD-33 | 2026-04-08 | Code system の英語第一原則 |
| AD-34 | 2026-04-08 | Hospital 設定駆動の物理レイアウト (診療科、病棟、ベッド) |
| AD-35 | 2026-04-08 | codes モジュールを locale から分離 (国際標準) |
| AD-36 | 2026-04-09 | SNOMED CT による FHIR Procedure 構造化フィールド (category、performer.function、bodySite、outcome、complication) |
| AD-37 | 2026-04-09 | 3 段の明示的 CLI: generate → narrate → export-fhir |
| AD-38 | 2026-04-09 | 臨床文書を FHIR DocumentReference として (Tier A+B スコープ、LOINC コード) |
| AD-39 | 2026-04-09 | LLM プロバイダプラグイン registry + YAML 駆動 factory |
| AD-40 | 2026-04-09 | プロンプトテンプレートを言語別 YAML ファイルとして外部化 |
| AD-41 | 2026-04-09 | LLM 応答の SHA256 ディスク cache (再現性 + コスト制御) |
| AD-42 | 2026-04-13 | 日本 locale 用のコード側単位変換 (CRP mg/L → mg/dL を extractor/generator で、LLM プロンプトではなく) |
| AD-43 | 2026-04-13 | 日本語 narrative プロンプト品質規則 (「医師」接尾辞、【】 節見出し、markdown なし) |
| AD-44 | 2026-04-15 | Enrichment は言語中立 (英語構造化データ; LLM が出力時に翻訳) |
| AD-45 | 2026-04-15 | Patient/PersonRecord の職業フィールド (12 カテゴリ; 労災傷病発生率を駆動) |
| AD-46 | 2026-04-16 | 多言語 FHIR coding (Condition/Procedure は dual coding を emit: primary + 相互運用言語) |
| AD-47 | 2026-04-16 | FHIR Observation referenceRange + interpretation の整合性 (FHIR R5 Note 5) |
| AD-48 | 2026-04-16 | procedure_name を CIF から削除 (display は code_lookup 経由で出力時解決、AD-30 に厳密準拠) |
| AD-49 | 2026-04-18 | Condition code.text に臨床略号 (_CONDITION_SHORT_NAME: COPD、CHF、CKD、DM、AF; coding[].display は公式 ICD 名を維持) |
| AD-50 | 2026-04-18 | Medication プロトコル prefix stripping (_strip_protocol_prefix が DVT_prophylaxis:、antipyretic: を medicationCodeableConcept.text から除去) |
| AD-51 | 2026-04-10 | 疾患プロトコルの YAML 駆動 medication_holds (simulator 内の hardcoded disease_id リストを置換) |
| AD-52 | 2026-04-10 | Hospital 設定の国別 recommended_population (50 床で US: 40K、JP: 10K) |
| AD-53 | 2026-04-10 | Narrative プロンプトでのスタッフ名前解決 (hospital.json roster → display 名) |
| AD-54 | 2026-06-15 | 国プラグイン可能な住民識別子 & 保険番号モジュール (`modules/identity/`) |
| AD-55 | 2026-06-15 | EHR データ enrichment 分割: near-essential データは Base (always-on、core 拡張)、専門的 / optional データは opt-in モジュール。**2026-06-25 PR3b-1 補足** — 第 3 カテゴリが正式追加: **always-on Module = near-essential 臨床カスケード**。省略すると臨床的に不整合な状態 (例: `HAI 発生かつ抗生剤治療なし`) を生じ CLAUDE.md 臨床整合性原則に反するモジュール。これらは `enabled=lambda c: True` で登録され、上流の `extensions[X]` スロットが空のときのみ no-op となる。例: `device` (PR-A)、`hai` (PR-B)、`antibiotic` (PR3b-1)。真に optional なデータ (例: JP `identity` — JP 保険番号が必要な場合のみ) 向けの **opt-in パターン** および core レコード型の typed フィールドを使う元の **Base パターン** とは区別される。新モジュール追加時の選定規則: 上流カスケードから常に期待されるデータなら always-on、simulator レベルの設定フラグ (国、地域、業務取極め) に依存するなら opt-in、ほぼ普遍的に emit される FHIR resource 型を拡張するなら Base typed-field を優先。**2026-06-26 PR3b-2 = HAI 培養 S/I/R 感受性チェイン**: Phase 3b シリーズの 2 番目。`modules/hai/_append_hai_culture()` を `load_hai_antibiogram()` (`modules/hai/__init__` の新 export) を使った antibiogram 駆動感受性サンプリングに拡張。データソース: `reference_data/hai_antibiogram.yaml` (CDC NHSN AR 2018-2020)、形式 `{hai_type: {organism_snomed: {antibiotic_key: [S, I, R]}}}`、import 時に `HAI_TYPES` + `hai_organisms.yaml` + `ANTIBIOTIC_LOINC_LOOKUP` に対して検証。RNG は既存の HAI per-patient sub-rng を使用 (新 RNG stream なし; AD-16 維持)。Forward-compat: `MicrobiologyResult.hai_event_id` backref (培養を PR3b-3 クロスリファレンス用に HAIEvent へリンク) と `AntibioticRegimen.discontinuation_datetime` (PR3b-3 de-escalation 用予約) を typed フィールドとして追加。`ANTIBIOTIC_DRUGS` を tuple → `dict[str, dict[str, str]]` にリファクタし `ANTIBIOTIC_LOINC_LOOKUP` を新 LOINC-lookup 相方として追加。LOINC orphan 修正: `microbiology.yaml` の `ciprofloxacin: "18879-7"` は実際は Cefepime だった → `18906-8` に訂正 (NLM 検証済); `loinc.yaml` 相方修正で Ciprofloxacin `18879-7` を正しいラベルで追加 + Cefepime `18906-8`。`simulator/engine.py` の `run_forced` は `force_hai_event is not None` のとき `config.forced_scenarios` へ `scenario` を注入するよう変更、Task 6 で発見された silent-no-op ギャップを閉じた。DQR: `docs/reviews/2026-06-26-phase-3b-2-hai-susceptibility-data-quality-review.md`。 |
| AD-56 | 2026-06-15 | 拡張性基盤 (Phase 0): FHIR resource-builder registry、simulator enricher registry、モジュール用 CIF extensions スロット、config モジュール有効化マップ。**PR1 2026-06-24 foundation refactor** で `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS` を全 enricher sub-seed オフセットの中央 registry として追加 (7 モジュール: identity + microbiology は decimals として grandfathered; immunization / code_status / family_history / care_level / nursing は 16-bit hex ASCII 慣習を使用)。モジュールレベル assert が偶発的重複オフセットを import 時に catch。新 enricher はここに登録し `ENRICHER_SEED_OFFSETS["my_module"]` 経由で import。CLAUDE.md「AD-55 enricher patterns」節 + `docs/CONTRIBUTING-modules.md` の contributor プレイブック参照。**PR2 2026-06-24 G2 SDOH integrity refactor** で「データ専用モジュール (variant)」パターン (`modules/sdoh/` — reference データ + loader のみ、enricher なし / ENRICHER_SEED_OFFSETS エントリなし — `clinosim/codes/` が既存の先例) を確立。また `_fhir_sdoh.py` を単一責務分離のため `_fhir_smoking_alcohol.py` + `_fhir_care_level.py` に分割し、将来の SDOH builder 再利用のため `_social_category` / `_value` helper を `_fhir_common.py` に昇格。**PR_docs 2026-06-24 包括的ドキュメント更新** で `MODULES.md` (22 モジュール inventory + 依存ツリー + 典型的呼び出しチェーン付きの top-level モジュールマップ)、`SCENARIO_FLAGS.md` (`derive_lab_values` を通じてルーティングされる scenario + medication フラグの中央参照)、`.github/TEMPLATE_MODULE_README.md` (標準化モジュール README テンプレート)、および全 22 モジュール README への「Consumers」節 (逆依存可視化用) を追加。`docs/CONTRIBUTING-modules.md` に PR 検証ガイド (byte-diff vs 3-axis DQR 判定マトリクス; プロジェクトの TRUE 目標は FHIR R4 + JP Core 準拠 + 臨床整合性 + JP language 品質、byte-diff は refactor-PR 手法のみ) を拡張し、元の G4 typed-field-vs-extensions 判定ツリーを吸収。**PR3 2026-06-24 G3 Observation-family split** (foundation refactor シリーズの最終構造ピース) で `_fhir_observations.py` (727 行 / 31 KB) 内の 4 つの無関係 builder を PR2 の先例に沿った 3 つの新テーマ別ファイルに抽出: `_fhir_microbiology.py` (Specimen + Observation + DiagnosticReport)、`_fhir_nursing.py` (NEWS2/GCS/Braden/Morse/Barthel/I&O サーベイ Observation)、`_fhir_immunization.py` (CVX Immunization)。残余 `_fhir_observations.py` (~380 行) は canonical な数値 Observation builder となる (lab helper + vital builder)。純粋機械的リファクタ — US p=2000 + JP p=2000、seed=42 の全 33 NDJSON ファイル (US 16 + JP 17) が master と byte-identical。device + HAI 特徴 builder が multi-theme blob を継承せずクリーンなテーマ別ファイル (`_fhir_device.py` / `_fhir_hai.py`) に landing する道筋を開いた。**PR-A device module 2026-06-24** で device + HAI 4-PR シリーズの Phase 1 を追加: `modules/device/` (AD-55 Module post_records enricher、inpatient ICU encounter に対し state-based 配置基準で CVC + 留置カテーテル + 人工呼吸器を emit)、`_fhir_device.py` builder ファイル (Device + DeviceUseStatement)、`clinosim/types/device.py` (`extensions["device"]` 配下の `DeviceRecord` dataclass)、`ENRICHER_SEED_OFFSETS["device"] = 0x4445`。SNOMED CT コード (`52124006` CVC / `23973005` 留置尿カテーテル / `706172005` Ventilator) は tx.fhir.org `$expand` テキスト検索で検証; spec の暫定 `467021000` は検証済 `23973005` に置換 (PR #80 LOINC `2B010` 捏造前例を適用)。3-axis DQR PASS at US p=10000 + JP p=5000: それぞれ 353 + 20 device、全構造チェック 100%、line-days は妥当なバンド内。byte-diff 補足で既存 NDJSON への回帰ゼロを確認 (AD-16 invariant)。Phase 2 PR-B (`modules/hai`) は `extensions["device"]` を消費して CLABSI/CAUTI/VAP onset サンプリングを行う。**PR-B hai module 2026-06-24** で device + HAI 4-PR シリーズの Phase 2 を追加: `modules/hai/` (AD-55 Module post_records enricher order=80、PR-A `extensions["device"]` line-days を消費し CDC NHSN baseline per-line-day リスクレート 0.0010/0.0014/0.0015 で CLABSI/CAUTI/VAP onset をサンプリング)、`_fhir_hai.py` builder (HAI Condition のみ — 培養は既存 `_fhir_microbiology.py` builder 経由で `record.microbiology.append(...)` で emit、新規配線ゼロ)、`clinosim/types/hai.py` (`extensions["hai"]` 配下の `HAIEvent` dataclass)、`ENRICHER_SEED_OFFSETS["hai"] = 0x4841`。コード検証: 3 ICD-10-CM (T80.211A / T83.511A / J95.851) を NLM API で; 3 WHO ICD-10 (T80.2 / T83.5 / J95.8); 3 HAI SNOMED (736442006 CLABSI / 68566005 UTI generic / 429271009 VAP — spec の暫定 433142000 + 425500004 は SNOMED CT International に存在せず、$expand 検証済の置換)。3-axis DQR PASS at US p=10000 + JP p=5000: US 4 HAI (3 CAUTI + 1 VAP) は expected ~3.2 の Poisson 2σ 内; JP 0 HAI は許容可能な rare-event。cross-module enricher 消費パターンの最初のクリーンな例。**Phase 3a 2026-06-25 POST_ENCOUNTER stage** で `clinosim/simulator/enrichers.py` に第 3 の enricher stage (`POST_POPULATION` および `POST_RECORDS` と並ぶ) を導入: **encounter ごとに、日次ループ完了直後、ただし encounter simulator 内** で実行される。`device` (order=70) と `hai` (order=80) を `POST_RECORDS` から `POST_ENCOUNTER` に移行、これは彼らのサンプリングが日次ループ後にしか分からない完全な clinical course アウトカム (`record.icu_transferred`、GCS、perfusion) に依存し、彼らの出力 (HAI event) が同 encounter の後処理から可視である必要があるため。AD-55 Module 分類は **「encounter-bound Module」** (device/hai — POST_ENCOUNTER) と **「cross-record Module」** (nursing/immunization/family_history/code_status/care_level/sdoh — POST_RECORDS) を区別するようになった。Phase 3a はさらに `clinosim/modules/hai/lab_lift.apply_hai_lab_lift` を追加、これは日次ループ後に `extensions["hai"]` を walk し per-day state_history snapshot を使って既存の WBC + CRP `obs.value` に forward-delta lift を追加; 元の noise + circadian を保持しつつ deterministic HAI 炎症効果を注入。byte-diff PASS: US p=2000 + JP p=2000 で全 37 NDJSON ファイル byte-identical (HAI はこのサイズでは Poisson rare-event); lift は p=10000 DQR で expected 臨床相対デルタで発火。forward-delta パターンは Phase 3b (antibiotic-day decay) と Phase 3c (Lactate / Plt / Temp / SBP sepsis cascade) で再利用可能。 |
| AD-57 | 2026-06-16 | 検査 / vital 生成を venue (inpatient/ED/outpatient) 横断で 1 つの生理駆動サービスに統一 (計画); hardcoded ED/outpatient baseline を置換。**Phase 3a 2026-06-25 forward-delta 拡張** — `modules/hai/lab_lift.apply_hai_lab_lift` が BNP パターン surgical 式アプローチの 4 例目 (BNP 壁ストレス、D-dimer Phase 2a、PT_INR Phase 2b の後): `state` を mutate したり `derive_lab_values` を影響日で再実行するのではなく、encounter 後ステップが per-day state_history snapshot に対して `delta = derive(state_snap, lift>0) - derive(state_snap, lift=0)` を計算し既存 `obs.value` に delta を追加、元の noise + circadian を保持。同 forward-delta パターンで Phase 3b/c sepsis cascade (Lactate / Plt / Temp / SBP) と antibiotic-day decay を future-proof 化。 |
| AD-58 | 2026-06-17 | **出力形式アダプタ registry。** CIF→形式アダプタは `register_output_adapter` (`clinosim/modules/output/adapter.py`) 経由で自己登録; CLI は registry 駆動 (`available_formats()` / `get_adapter()`)。形式追加 (SS-MIX、FHIR R3、HL7 v2) = `OutputAdapter` (`format_id`/`description`/`subdir`/`convert`) を 1 つ追加 — CLI や core の編集なし。組み込み CSV/FHIR-R4 は薄いラッパー (出力不変)。アダプタは CIF + `clinosim.codes` + `clinosim.locale` (AD-17/AD-25) にのみ依存。進化パス: 外部プラグインパッケージ用の setuptools entry-point 発見。 |
| AD-59 | 2026-06-23 | **Per-order lab RNG 分離。** すべての lab order — panel children も個別スカラ order も — specimen-rejection / hemolysis / technician-assignment / observation-noise RNG を patient-scoped master RNG からではなく per-order sub-stream から draw する。Panel children は `panel_specimen_seed(parent_order_id)` を使用 (「parent order 1 つに検体 1 つ」をモデル化); 個別 non-panel order は `individual_lab_seed(order_id)` を使用 (order 1 つに検体 1 つ)。両者とも `clinosim/simulator/seeding.py` に存在。維持される構造的性質: 疾患 / encounter YAML の `{test:"X"}` 行を編集、または `derive_lab_values` を新しい分析対象を produce するよう拡張しても、無関係患者の cohort を master stream 経由で **shift できない** — `inpatient.py` Pass 1、`emergency.py`、`outpatient.py` の全 lab path で AD-16 が要求するものを完遂。段階的に確立: PR #74 で panel children 用の `panel_specimen_seed` を導入; PR #78 で残りの個別 lab path 用に `individual_lab_seed` を追加; Coag panel PR (2026-06-24) がこの分離を通じて新しい分析対象 (APTT / PT / Fibrinogen) を追加する最初のフォローアップ — master @ p=2000 seed=42 vs byte-diff で US と JP 両方で無関係 NDJSON にゼロ shift を確認。Phase 2a (2026-06-24、D-dimer + `causes_vte`) は 2 番目のフォローアップ: byte-diff で 9 個の無関係 NDJSON にゼロ shift を再確認、加えて同 PR で全 `derive_lab_values` scenario-flag read を中央化する `scenario_flags_from_protocol(protocol)` helper を導入し、将来のフラグが 1 つの helper 編集で全 `derive_lab_values` call site (inpatient Pass-1 + lagged + emergency + outpatient) に到達するようにした。Phase 2b (2026-06-24、`on_warfarin` PT_INR 治療域オーバーライド) は flag-helper パターンを兄弟の `medication_flags_from_context(patient, medication_orders, admission_date, current_day)` で拡張、これは慢性 + 入院中のワルファリン使用を RNG draw なしで検出 — AD-59 分離を保持しつつ再利用可能パターンとして薬剤 → lab カップリングを追加 (将来: ステロイド → glucose、利尿薬 → K、抗生剤 → CRP)。Call site は `{**scenario_flags, **medication_flags}` で両 helper dict をマージし、フラグ追加を 1-edit-safe に保つ (J5-prevention を拡張)。master @ p=2000 seed=42 vs byte-diff で 9 個の NDJSON のうち 8 個が sha256-identical; Observation のみ変化 (同カウント、warfarin-detected 患者のみ PT_INR/PT 値 shift)。Integration guards: `tests/integration/test_individual_lab_isolation.py` (analyte) + `tests/integration/test_medication_flags_isolation.py` (medication flag)。 |
| AD-60 | 2026-06-25 | **clinosim 監査フレームワーク。** `clinosim/audit/` パッケージ + CLI サブコマンド (`clinosim audit run/smoke/list`) として構築された統一検証ゲート。従来の 3-axis DQR スクラッチパッドスクリプトを吸収し、PR-90 クラスのバグ (case-mismatch silent no-op、test 緑 + byte-diff PASS + DQR cohort PASS が成立したまま production で Phase 3a HAI lift 全体が no-op となった) を catch するために設計された第 4 の **silent_no_op** axis (canonical-constants クロスチェック + lift-firing 証明) を追加。アーキテクチャ: `clinosim/audit/registry.py` (ModuleAuditSpec dataclass + register_audit_module + discover) + `clinosim/audit/engine.py` (AuditEngine が module × axis マトリクスを orchestrate) + `clinosim/audit/axes/` (4 axes: structural / clinical / jp_language / silent_no_op) + `clinosim/audit/reporter.py` (Markdown)。Per-Module チェックは `clinosim/modules/<name>/audit.py` に存在し、発見時に register_audit_module(spec) を副作用 import; 新 Module は `structural_obs_codes`、`clinical_acceptance`、`canonical_constants` + `yaml_keys_to_validate`、`lift_firing_proof` を宣言することで 4 axes 全てを無料で得る。Phase 1 は `modules/hai/audit.py` のみ ship (scratchpad/phase3a_lift_fired_proof.py の吸収点)。master @ p=2000 seed=42 vs byte-diff で 37/37 NDJSON byte-IDENTICAL を確認 — 監査フレームワークは生成出力の純粋な read-only 消費者、simulation-path import は漏れず AD-16 維持。初回セルフ監査ベースラインレポート: `docs/reviews/2026-06-25-clinosim-audit-baseline.md`。byte-diff は refactor-PR 手法として分離維持; 監査フレームワークは新機能 / リアリズム PR 用。`docs/CONTRIBUTING-modules.md` の「PR 検証ガイド」の判定マトリクス参照。**2026-06-25 PR3b-1 = 第 2 の per-Module プラグイン**: `modules/antibiotic/audit.py` が `hai` に続く 2 番目の具体プラグインを追加。その `lift_firing_proof` は合成 CAUTI HAIEvent に対し実際の enricher path (`enrich_antibiotic`) を駆動し、Ceftriaxone q24h × 7d デルタ (1 regimen、1 MedicationRequest、7 MAR、first/last が期待日時に一致) の closed-form を assert。`clinosim audit list` は 2 モジュールを同 4-axis マトリクスで報告し、フレームワークの再現性を確認。**2026-06-26 PR3b-2 監査フレームワーク拡張**: `modules/antibiotic/audit.py` を以下で拡張: (1) 構造 axis Observation.code カバレッジ用に 8 感受性 LOINC の `_ABX_LOINCS` frozenset; (2) `_NHSN_RESISTANCE_BANDS` メタデータ (CLABSI MRSA 40-55%、CAUTI ESBL 12-22%、VAP MRSA 30-45%) と `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE = 0.05` — PR3b-3 (2026-06-27、per-(hai_type, antibiotic) R-rate ゲート + per-HAI cohort empty-rate ゲート + per-hai_type narrow-rate ゲート、rare-event 安全のため各 `n<30 → WARN`) で clinical axis の active enforcement に配線; **PR3b-3 D1+D2 (2026-06-29、PR #112) がチェーンを完了**、`_organism_per_encounter` (per-(hai_type, organism, antibiotic) R-rate フィルタ) と `_panel_eligible_organisms` (`load_hai_antibiogram()` キー経由の panel-eligible empty-rate 分母 — E.faecalis / C.albicans を自動除外) を追加し、両 `# TODO(post-PR3b-3)` マーカーを削除; (3) PR-94 `equality_checks` フォーマットを使った `antibiogram_firing_proof` — 合成 CLABSI S. aureus レコードに対し `_append_hai_culture()` を駆動し `ANTIBIOTIC_LOINC_LOOKUP["vancomycin"]` 経由 (LOINC hardcode なし) で Vancomycin 感受性 = S を assert、感受性チェーンで同じ silent-no-op クラスのバグを閉じる。 |
| AD-62 | 2026-06-30 | **メタデータのみの Imaging チェーンと WADO-RS プレースホルダ。** |
| AD-63 | 2026-07-01 | **Document narrative + structured event density 基盤。2 つの新 always-on Module (allergy = POST_POPULATION order=10 / document = POST_ENCOUNTER order=95)、3 FHIR builder (DocumentReference / Composition / ClinicalImpression)、17 チェックの lift_firing_proof。Stage 1 document-density ギャップを解消 (DR 0→23,760、Comp 0→9,275、CI 0→23,760 US p=10k)。** |

*番号ギャップ AD-1、AD-2、AD-12、AD-14、AD-15、AD-27 は予約 / 撤回済 — ship された決定に一切割当てられていない。AD-61/AD-64/AD-65/AD-66/AD-67/AD-68/AD-69 はこのコンパクトなテーブルではなく [`adr-history.ja.md`](adr-history.ja.md) の独自 `### AD-6N` セクションでドキュメント化。AD-67 (severity single source of truth)、AD-68 (archetype_modifiers wiring)、AD-69 (DiseaseProtocol extra="forbid") は 2026-07-06 の FHIR-completeness chain — `docs/design-notes/2026-07-06-fix-point-registry.md` 参照。*

---

## 6.9 Resident identifier & 保険番号 (AD-54)

### 問題

Layer-1 の住民と Layer-2 の患者は内部 MRN 以外の payer identity を
持たなかった。現実的な EHR / claims データは患者の **保険加入**
(被保険者番号 / member id、保険者番号 / insurer number、記号 /
group symbol、枝番 / branch number) と、日本の場合はマイナンバー
カード / マイナ保険証状態を要求する。これらは **国固有**、
**世帯相関**、**時間変化** するため hardcode 不可能。

### 主要ドメイン事実 (設計を駆動)

- 12 桁マイナンバー (個人番号) は法律により **臨床 EHR に保存
  されない** (番号使用は社会保障 / 税 / 災害に限定)。マイナ保険証
  提示時も、プロバイダは **保険資格** を受信し、生の個人番号は
  決して受信しない。→ マイナンバーは Layer-1 シミュレーション属性
  のみで、臨床出力 (FHIR/CSV) は emit してはならない。
- EHR / claims 識別子は **被保険者番号 + 保険者番号** であり、
  FHIR では `Patient.identifier` slice ではなく **`Coverage`**
  リソース (`subscriberId`、`payor` → insurer Organization) として
  表現する (JP Core の設計と一致)。
  - **JP Core Coverage マッピング (jpfhir.jp/fhir/core に対して
    検証済):** 記号 / 番号 / 枝番 →
    `JP_Coverage_InsuredPersonSymbol` /
    `…InsuredPersonNumber` / `…InsuredPersonSubNumber` extension
    (valueString); `subscriberId` = `記号:番号`; `dependent` =
    枝番; `identifier.value` = `保険者番号:記号:番号:枝番`
    (system `JP_Insurance_memberID`); `payor` →
    `jp-insurer-number-namingsystem` identifier (= 保険者番号)
    を持つ Organization。必須: `status`、`beneficiary` (1..1)、
    `payor` (1..*)。canonical URI は
    `locale/jp/identity.yaml:fhir_coverage` に保存。
  - **FHIR 準拠詳細:** payor Organization は `type` coding
    `organization-type#pay` と `locale/jp/identity.yaml:payers`
    から解決される実 insurer **name** を持つ (number → name at
    output; AD-30 — display text は決して CIF に保存されない)。
    `Coverage.relationship` = `self` (subscriber) / `other`
    (被扶養者)。`Coverage.type` はテキストのみの CodeableConcept
    (日本語 scheme ラベル; コード捏造なし)。代表的な payer は
    有効な検証番号 / check digit を持つ。US export は
    `Coverage` を **emit しない** (JP 保険 leak なし)。
- 記号共有粒度は scheme により異なる: 社保 (被用者) は **雇用主
  (事業所) レベル** で記号を共有; 国保は **世帯レベル** で共有;
  後期高齢者 (75+) は **個人単位**。
- 長期患者の「マイナンバー割当」は **資格検証方式** (紙 → オン
  ライン) を変えるが **被保険者番号** は変えない。時間とともに
  実際に変化するデータは **payer** (転職 / 退職、および決定的な
  **75 歳 → 後期高齢者** 移行)。したがって保険は **period-bounded
  加入履歴** としてモデル化され、各 encounter はその日付に有効な
  加入を参照する (`Coverage.period`)。

### 決定

新規リーフモジュール `clinosim/modules/identity/` が numbering を
所有:

- `base.py` — `IdentityProvider` Protocol (国プラガブル seam;
  インターフェースのみ)
- `registry.py` — `country → provider` 解決 (`healthcare_system`
  を mirror)
- `generators.py` — check-digit 番号生成器 (国共通純粋関数)
- `providers/jp.py` — JP ルール (雇用主レベル 記号、社保 / 国保
  / 後期高齢者、枝番、カード / 保険証 dated flag、75 歳移行)
- `providers/us.py` — 薄い (既存 `_sample_insurance` 挙動保持)

国追加 = 新規 `providers/<cc>.py` + `locale/<cc>/identity.yaml`;
engine 変更なし (disease/encounter YAML と同じ思想)。

**決定性 (AD-16):** numbering は **population 生成後の separate
pass** として実行、**専用 sub-seed Generator** を使用するため
既存の random stream (と golden ファイル) は無傷。

**プライバシーチョークポイント:** `national_id` は将来のマイナ
ワークフロー拡張性のために CIF/`PersonRecord` に存在しうるが、
出力アダプタは **sensitive-field default-exclude** ポリシーを持つ
— FHIR/CSV は明示的に opt-in しない限り決して `national_id` を
emit しない。

### デフォルト (locale/jp/identity.yaml — 調査済、provisional なら `# TODO: verify`)

- マイナンバーカード保有率 (年齢帯): 0–14 ≈0.70、15–49 ≈0.77、
  50s ≈0.82、60s ≈0.90、70s ≈0.91 (ピーク)、80+ ≈0.72 (総務省
  / デジタル庁 2025)
- マイナ保険証登録率: より低く、同年齢形状 (ピーク 60–70s)
- 世帯内相関は `household_icc` (marginal card rate を保存する
  Gaussian-copula)
- **被用者保険 vs 国保 は職業駆動**: 世帯で最も雇用可能性の高い
  労働年齢メンバーが `employee_probability_by_occupation` 経由で
  被保険者になる (他は被扶養者)。新出 <75 分割が ≈ 73:27 (MHLW
  医療保険基礎資料) になるよう calibrate、`insurance_category_distribution`
  を fallback として。
- **マイナ保険証 marginal**: registration は `ins_rate/card_rate`
  レートでカード保有に条件付き、population linked marginal =
  configured `ins_rate` となる。
- **`insurance_type` 統一**: JP について、`PatientProfile.insurance_type`
  は加入 `category` から設定される (single source of truth →
  一貫した CSV/Coverage; 以前は空だった)。

### フェーズ

1. モジュールスケルトン + JP numbering + snapshot 単一加入 +
   Coverage + payor Org
2. Period-bounded 加入履歴 + 75 歳移行 + `Coverage.period`
3. 雇用移行 (軽い確率的) + カード / 保険証日付 + 検証方式
4. US 互換テスト + docs/ADR 最終化

---

## 6.10 EHR データ enrichment 分割 — Base vs Module (AD-55)

### 原則

EHR データクラスを追加するとき (Synthea / USCDI v5 / MIMIC-IV に
対してベンチマーク):

- **Base** — 現実的 EHR が本質的に *常に* 保持するデータ (かつ
  既存の physiology / clinical-course state から安価に導出可能)。
  **毎回の実行** で **既存コア** (`types/`、`population`、
  `observation`、`simulator/*`、`output`) を拡張することにより
  生成。新規 opt-in モジュールなし、フラグなし。
- **Module** — 専門化または optional データ。**`clinosim/modules/`
  配下の opt-in プラガブルモジュール** として実装 (`identity` と
  同じパターン: 独自 README + Dependencies、`types/` の型、CIF
  を読む `output` モジュール内で FHIR ビルド、専用 sub-seed、CLI
  フラグ / config でゲート)。**テーマごとに 1 モジュール** (例:
  billing、devices、care-coordination) — 既存の one-theme-per-
  module レイアウトと一致し、catch-all「extras」モジュールは決して
  作らない。

過度なモジュール化を避ける: 小さな near-universal *属性* (family
history、code status、拡張 SDOH) は独自モジュールではなく Base の
patient/encounter field に配置する。

### スコープガード (enrichment 研究から carry)

画像 / モダリティ依存データは **スコープ外** (CT/MRI/X-ray/US、
echo、ECG tracing、endoscopy 所見、spirometry、pathology)。Lab /
ベッドサイド / 事務データはスコープ内 (clinosim は既に生理から
lab を導出するので、同じことが microbiology、血液ガス、心臓
マーカー、看護 flowsheet にも適用される)。

### 分類

| Tier | Data | Lives in |
|---|---|---|
| Base | Microbiology + susceptibility; lactate / ABG / cardiac markers; `DiagnosticReport` grouping; 看護 flowsheet (I/O、NEWS2、pain、GCS、Braden); immunization 履歴; family history; code status / advance directive; 拡張 SDOH (JP 要介護度含む) | core: `types`、`population`、`observation`、`simulator`、`output` |
| Module | Billing (`modules/billing/` — JP DPC / US Claim+EOB); Devices + HAI (`modules/device/` — CLABSI/CAUTI/VAP); Care coordination (`modules/care_coordination/` — CarePlan/CareTeam/Goal) | テーマごとに 1 opt-in モジュール |

段階的実装計画は [`docs/roadmap.md`](docs/roadmap.md) 参照 (GitHub
Issues board を指す)。

---

## 6.11 拡張性基盤 — Phase 0 (AD-56)

### 問題

新規 FHIR resource type または opt-in モジュール追加は現在
いくつかの中央ホットスポットの編集を要求するため、AD-55 ロード
マップ (8 Base item + 3 module) は同じモノリスを繰り返し触ることに
なる:

- `output/fhir_r4_adapter.py` `_build_bundle()` (~3,000 行
  ファイル) — 新 resource は 1 関数に手で append + dedup set
  にも追加。
- `simulator/engine.py` `run_beta()` — 各 post-population pass が
  インライン化 (例: `if config.jp_insurance_numbers: assign_identities(...)`)、
  order-sensitive。
- `types/output.py` `CIFPatientRecord` — 固定 dataclass; 新データ
  クラスごとに field 追加。
- `types/config.py` `SimulatorConfig` — opt-in モジュールごとに 1
  ブール。

### 決定 — AD-55 enrichment 作業の *前* にこれらの enabler refactor を実施

1. **FHIR resource-builder registry。** `(record, ctx) -> list[resource]`
   のビルダー registry; コアループが反復して emit。各ビルダーは
   dedup 挙動 (患者レベル vs per-encounter) を宣言。新 resource
   = ビルダー登録 (ドメインと co-locate) — `_build_bundle` 編集
   なし。
2. **Simulator enricher registry。** Post-population pass は
   `name` / `order` / `enabled(config)` / `run(...)` で登録;
   `run_beta` は宣言順で反復。新 module = enricher 登録 —
   `run_beta` 編集なし。**Order は明示的で固定、決定論 (AD-16)
   を保存するため。**
3. **CIF extensions slot。** `CIFPatientRecord.extensions: dict[str, Any]`
   を追加。**Base** データは typed field を保持 (Base *は* core);
   **Module** は `extensions[<module>]` に書き込み、決して core
   type を編集しない — module 独立性が型レベルで強制 (AD-55 と
   一致)。
4. **Config モジュール有効化マップ。** `SimulatorConfig.modules: dict[str, bool]`
   + `module_enabled(name)` ヘルパー; `jp_insurance_numbers` は
   後方互換 alias として保持。Per-module 構造化 config (例:
   billing 国別オプション) は独自ブロックに配置。

Secondary: `observation` lab カタログ (CV / precision / units) を
YAML に外部化 (microbiology Base item と並行して完了)。CSV
アダプタ registry は **deferred** (低レバレッジ — 新テーブルは
~3 行)。

### 制約

これらは動作するコードを refactor する。回帰は既存 golden / e2e
suite と決定論 (AD-16) でゲート: resource emission 順序または
RNG draw 順序の変更は同等であることが証明されなければならず、
真の回帰であってはならない。

---

## 7. FHIR DocumentReference 経由の臨床文書

### 問題

Milestone 1 (2026-04-09 初期) 前、clinosim は narrative 臨床文書を
first-class FHIR リソースとして produce する方法を持たなかった。
レガシー `narrative_generator` は `cif/narratives/<version>/patients/*.json`
配下に緩い JSON ファイルを書いていたが、これらは FHIR Bulk Data
export に到達しなかった。下流 consumer は patient、encounter、
observation、procedure リソースを持つが、退院サマリなし、手術記録
なし、admission H&P なし — 臨床医が患者の物語を read / review する
のに実際に使う文書がなかった。

このギャップは以下をブロックした:
- 再入院予測とアウトカム研究 (退院サマリは主要データソース)
- 死亡レビュー (死亡記録は全入院死亡の法的文書)
- 手術品質分析 (手術記録は CMS §482.51 で必須)
- DocumentReference リソースとして臨床ノートを期待する NLP/LLM
  訓練パイプライン

### 決定 (AD-36、AD-37、AD-38)

**AD-36 — FHIR Procedure が SNOMED CT 経由で構造 field を取得。**
各 `Procedure.ndjson` エントリは以下を含むようになった:
- `category` — SNOMED 387713003 (surgical) / 103693007
  (diagnostic) / 277132007 (therapeutic)
- `performer[].function` — SNOMED 304292004 (surgeon) / 158967008
  (anaesthetist)
- `recorder` — Practitioner 参照 (デフォルトは surgeon)
- `reasonReference` — encounter の primary Condition へリンク
- `bodySite` — SNOMED anatomy コード
- `location` — 手術室 Location 参照 (手術のみ)
- `outcome` — SNOMED 385669000 (successful) / 385670004 (partial)
  / 385671000 (unsuccessful)
- `complication` — `ProcedureRecord.intraop_complications` から
  マップされた SNOMED コード

`clinosim/codes/data/snomed-ct.yaml` はこれらの field に必要な
最小 SNOMED サブセットを含み、English-first 原則 (AD-33) に従う。

**AD-37 — 3 つの明示的 CLI ステージ: `generate` → `narrate` → `export-fhir`。**
Stage 1 (`generate`) は構造化 CIF を produce。Stage 2 (`narrate`)
は既存 CIF から臨床文書を生成し `cif/narratives/<version>/documents/`
に書き出す。Stage 3 (`export-fhir`) は CIF (と任意で narrative
version) を読み、narrative version が提供された場合は
`DocumentReference.ndjson` を含む FHIR NDJSON ファイルを emit。

理由:
- **再現性 (AD-16)** — Stage 1 は seed から決定的。Stage 2 は
  prompt cache (AD-41) 経由で再現性を持つ。Stage 3 は CIF の
  純関数。
- **コスト隔離** — Stage 2 は有料 LLM API を呼び出しうる唯一の
  stage。LLM (例: Bedrock) にネットワークアクセスできないホスト
  (例: 到達できないラップトップ) では、Stage 2 のみのために CIF
  ディレクトリを EC2 インスタンスに送り、Stage 3 のために戻す
  ことができる。
- **実験** — 同一構造化 CIF からの複数 narrative version が共存
  し比較可能 (template vs Ollama vs Bedrock、英語 vs 日本語、
  prompt version 1 vs 2)。
- **CIF は single source of truth を維持 (AD-17、AD-30)** —
  structural/ は immutable、narratives/ は置換可能層。

**AD-38 — FHIR DocumentReference としての臨床文書 (Tier A+B scope)。**
clinosim はこれらの文書を out of the box で produce:

| Tier | 文書 | LOINC | encounter あたり数 | 正当化 |
|---|---|---|---|---|
| A | 退院サマリ | 18842-5 | 入院あたり 1 | CMS §482.24 で全退院に必須 |
| A | 死亡記録 | 69730-0 | 死亡あたり 1 | 法的文書; M&M レビュー |
| A | 手術記録 | 11504-8 | 手術手技あたり 1 | CMS §482.51 で必須 |
| B | Admission H&P | 34117-2 | 入院あたり 1 | 標準 US 入院文書 |
| B | Procedure Note | 28570-0 | 入院あたり 0..N | 臨床的に有意な侵襲的ベッドサイド手技のみ |

Procedure Note スコープは正式なノートを要求する **8 つの侵襲的
ベッドサイド手技** に制限: `central_line`、`lumbar_puncture`、
`thoracentesis`、`paracentesis`、`chest_tube`、`intubation`、
`bronchoscopy`、`cardioversion`。低複雑度ベッドサイド手技 (尿カテ
ーテル、NG チューブ、心エコー、輸血、透析、動脈ライン、創傷
debridement) は看護または補助レコードに文書化され、独立した
DocumentReference を produce しない。

Progress Note (LOINC 11506-3) は **将来の Tier C スコープ用に予約**、
なぜなら実世界の progress note は構造化 vitals/labs/MAR データと
~80% 重複し、全入院日で生成すると最小限の追加研究価値のために
token コストを 1 桁膨張させる。

### 保存形式: narrative CIF

新しい型 `ClinicalDocument` (`clinosim/types/clinical.py`) が 1
臨床文書を表現する。以下の下に文書あたり 1 JSON ファイルとして
書かれる:

```
cif/narratives/<version_id>/documents/<encounter_id>/<task_type>[_suffix].json
```

各ファイルは以下を含む:
- **Identity** — document_id、task_type、LOINC コード
- **References** — patient_id、encounter_id、author_practitioner_id、
  related_procedure_id
- **Timing** — authored_datetime、period_start、period_end
- **Content** — language、content_type、text
- **Provenance** — text_source (llm/template/cache/none)、
  llm_model、llm_provider、input/output tokens、prompt_version、
  cache_hit、generated_at、fallback_reason

document_generator は各 encounter に対して決定的な事実リストを
(`hospital_course_extractor` 経由で) 抽出し、それらを `${variables}`
として LLM prompt に渡す。これは LLM を honest に保つ: それは事実
を捏造するのではなく narrate する。

### FHIR DocumentReference マッピング

```
DocumentReference.id          = <document_id>
  .status                     = "current"
  .docStatus                  = "final" (template fallback には "preliminary")
  .type.coding                = LOINC コード + display (clinosim.codes 経由で解決)
  .category                   = us-core-documentreference-category: clinical-note
  .subject                    = Patient/<patient_id>
  .date                       = authored_datetime
  .author                     = Practitioner/<author_practitioner_id>
  .content[0].attachment
      .contentType            = text/plain; charset=utf-8
      .language               = en | ja
      .data                   = base64(text)
      .size                   = バイト長
      .hash                   = base64(sha1(text))
  .context.encounter          = Encounter/<encounter_id>
  .context.period             = { start, end }
  .context.related            = Procedure/<related_procedure_id>  (operative/procedure)
```

空文書 (Stage 2 テキストなしの Stage 1 stub) は **emit されない**
— 空 attachment データ付き DocumentReference は下流 consumer に
無用で、`clinical-note` category attachment が示唆する FHIR
profile に違反する。

---

## 8. LLM サービスアーキテクチャ: プラガブルプロバイダ + YAML プロンプト

### 問題

Milestone 0 の `llm_service` はローカル Ollama のみをサポートし、
全プロンプトが `engine._build_prompt()` にハードコードされていた。
新プロバイダ追加は `engine.py` 編集を要求し、新言語追加は Python
コード編集を要求し、新文書型追加は両方を要求した。Bedrock は
一切実装されていなかった。レスポンス cache なしで、Stage 2 の
再実行は常に LLM を再呼び出しした。

### 決定 (AD-39、AD-40、AD-41)

**AD-39 — LLM プロバイダプラグイン registry。**
プロバイダは `clinosim/modules/llm_service/providers/` にサブ
パッケージとして存在する。各プロバイダは `LLMProvider` Protocol
を実装する (構造的型付け、継承なし):

```python
class LLMProvider(Protocol):
    def complete(self, prompt, model, max_tokens, system_prompt,
                 temperature=0.4, stop_sequences=None) -> ProviderResponse: ...
    def health_check(self) -> bool: ...
```

`providers/__init__.py` の registry はプロバイダキー (`ollama`、
`bedrock`、`mock`、`local`) をビルダー callable にマップする。
サードパーティコードは `register_provider(name, builder)` 経由で
clinosim ソースを触らずに registry を拡張可能。

新しい `factory.build_from_config_file(path)` は
`llm_service.yaml` を読み、`judgment:` と `narrative:` セクション
用に適切なプロバイダをビルドし、完全に配線された `LLMService` を
返す。Bedrock プロバイダは `boto3` を遅延 import するので、
Bedrock を使わないユーザは install する必要がない。

**AD-40 — 言語別 YAML ファイルとしてのプロンプトテンプレート。**
プロンプトは `clinosim/modules/llm_service/prompts/<language>/<task_type>.yaml`
配下に存在:

```yaml
task_type: discharge_summary
version: 1
max_tokens: 2000
temperature: 0.4
system: |
  You are an attending physician writing a comprehensive discharge summary ...
user_template: |
  Patient: ${age}yo ${sex}
  Admission date: ${admission_date}
  ...
```

`PromptRegistry.get(task_type, language)` は spec を lazy にロード
+ cache する。レンダリングは Python 標準ライブラリの
`string.Template` を使用 (外部依存ゼロ)、user template には
`substitute()` (missing key で raise — fail loud)、system prompt
には `safe_substitute()` (自然言語コンテンツに偶発的な `${...}`
シーケンスが含まれうる)。

言語 fallback は codes モジュールの挙動を mirror: `ja/<task>.yaml`
が missing なら registry は `en/<task>.yaml` にフォールバックし、
PromptSpec の `language` field 経由でログ。

理由:
- **臨床医編集可能** — 非プログラマが Python コードに触らず
  prompt 品質を改善可能。
- **言語追加はフォルダで、PR レビューではない** — ドイツ語追加
  は `prompts/de/*.yaml` 作成のみ、engine 変更なし。
- **バージョニング + A/B テスト** — `version:` field は各生成
  文書に記録され、再現性と制御された rollout を可能にする。
- **JUDGMENT English-only 不変条件 (AD-13)** は yaml-tree レベル
  で強制: 英語プロンプトのみを judgment task 配下に配置。

**AD-41 — LLM レスポンス用 SHA256 disk cache。**
`clinosim/modules/llm_service/cache.py` の `PromptCache` は
cached レスポンスあたり 1 JSON ファイルを保存、
`SHA256(system || user || model)` でキー付け。エントリは成功した
プロバイダ呼び出し後に `LLMService._llm_generate` により書かれ、
cache が有効なとき全プロバイダ呼び出し前に read される。

理由:
- **再現性 (AD-16)** — 同一入力と同一 seed での Stage 2 再実行
  は byte-identical 出力を produce。
- **コスト制御** — Bedrock Claude Sonnet の 5,000 患者データ
  セット実行は 1 実行あたり $1–5 のオーダー; cache hit で
  再実行が無料。
- **部分再実行復旧** — Stage 2 が中断された場合、まだ cache
  されていない文書についてのみ LLM を再呼び出しして再開。

Cache 位置はデフォルトで `<cif>/narratives/<version>/cache/` また
は YAML config の明示的 `cache.directory`。Cache は template と
mock モードで無効化。

### データモデル: LLMService.generate

`LLMService.generate(task_type, event, variables=None)` は全モジュ
ール用の単一エントリポイント。`variables` は PromptRegistry に
ルーティングする新パラメータ; None のとき、レガシー `_build_prompt`
hardcoded path を使用 (admission H&P / 退院サマリテンプレート
コードとの後方互換性のため保持)。

返される `LLMResponse` は現在以下を carry:
- `source` — `llm` | `template` | `cache` | `none`
- `input_tokens` / `output_tokens`
- `prompt_version` — PromptSpec から
- `cache_hit` — `PromptCache` から serve されたとき True
- `fallback_reason` — テンプレート fallback 時に短いエラータグ
  で populate
- `provider` — provenance 用の configured プロバイダキー
  (例: `bedrock`)

これら全ては `ClinicalDocument.generation` ブロックに記録され、
narrative CIF manifest に伝播、per-document コスト分析と audit を
可能にする。

---
