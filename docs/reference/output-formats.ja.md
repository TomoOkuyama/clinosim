<!-- README.md から抽出 (Issue #568 PR A)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# 出力形式

### CIF (Clinosim Intermediate Format)

```
output/cif/
├── metadata.json                             # 生成情報、snapshot_date 等
├── hospital.json                             # スタッフ roster + 病院設定
├── structural/                               # Stage 1 出力 (immutable)
│   └── patients/
│       └── ENC-POP-XXXXXX-NNNNNN.json        # encounter ごとに 1 ファイル
└── narratives/                               # Stage 2 出力 (再実行可能)
    ├── current_version.txt                   # 最新 version id へのポインタ
    ├── <version_id>/
    │   ├── manifest.json                     # LLM config、model、コストレポート、count
    │   └── documents/
    │       └── ENC-POP-XXXXXX-NNNNNN/
    │           ├── admission_hp.json
    │           ├── discharge_summary.json
    │           ├── death_summary.json        # 死亡時のみ
    │           ├── operative_note_001.json   # 手術ごと
    │           └── procedure_note_<type>.json
    └── <another_version_id>/                 # 複数 version が共存可能
        └── ...
```

- `structural/` はシミュレーションの **immutable な中間形式**。全
  structural FHIR/CSV リソースはこれから派生。
- `narratives/<version>/documents/` は **narrative レイヤ** — 臨床
  文書ごとに 1 JSON、`clinosim/types/clinical.py` の
  `ClinicalDocument` 型に準拠。各ファイルは LOINC code、プレーン
  テキスト内容、references、provenance (LLM model、tokens、cache
  hit、prompt version、generated_at) を含む。
- 複数 narrative version が共存可能: 例 `template_v1`、
  `ollama_en_v1`、`bedrock_sonnet_en_v1` — 全て同じ structural CIF
  から生成。

### FHIR R4 — Bulk Data Export NDJSON 形式

[HL7 FHIR Bulk Data Access](https://hl7.org/fhir/uv/bulkdata/) 準拠:

```
output/fhir_r4/
├── manifest.json                    # Bulk Data manifest (transactionTime、output[])
├── Patient.ndjson                   # 1 患者 1 行
├── Encounter.ndjson                 # 1 encounter 1 行
├── Observation.ndjson               # labs + vitals + AVPU + O2 + microbiology + nursing scores
│                                    #   (NEWS2/GCS/Braden/Morse) + social history (occupation、
│                                    #   smoking、alcohol、JP 要介護度) + code status (LOINC/SNOMED)
├── ServiceRequest.ndjson            # Lab オーダー (panel-aware: CBC/BMP/LFT 等ごとに 1 SR; stand-alone オーダーは各 1 SR) [AD-61]
│                                    # + 画像オーダー (imaging Order ごとに 1 SR、SNOMED 363679005 + v2-0074 RAD) [AD-62]
├── ImagingStudy.ndjson              # 放射線検査 (urn:dicom:uid、DCM modality、multi-series) [AD-62]
├── Endpoint.ndjson                  # ImagingStudy ごとに WADO-RS URL プレースホルダ (将来 PACS / 画像生成 AI 統合) [AD-62]
├── DiagnosticReport.ndjson          # Lab panel レポート (CBC/BMP/LFT/Lipid/Coag/UA/ABG、LOINC) + microbiology culture レポート (+ Specimen)
│                                    # + 放射線レポート (findings + impression を text.div に、conclusion) [AD-62]
├── Specimen.ndjson                  # Culture 検体 (blood/urine/sputum/wound)
├── Condition.ndjson                 # Encounter dx + chronic conditions + HAI (CLABSI/CAUTI/VAP) (ICD-10-CM / ICD-10 / SNOMED dual)
├── FamilyMemberHistory.ndjson       # 一親等家族疾患歴 (v3-RoleCode + ICD)
├── Immunization.ndjson              # 成人ワクチン歴 (CVX; US/JP スケジュール)
├── Device.ndjson                    # ICU デバイスレコード (CVC / indwelling catheter / ventilator; SNOMED CT)
├── DeviceUseStatement.ndjson        # デバイス使用期間 (配置 → 抜去; ICU 入院 encounter ごと)
├── MedicationRequest.ndjson         # 処方 (RxNorm / YJ)
├── MedicationAdministration.ndjson  # MAR 記録
├── Procedure.ndjson                 # 手術 + ベッドサイド手技 (CPT / K-code + SNOMED CT メタデータ)
├── DocumentReference.ndjson         # 臨床文書 (narrative version 指定時のみ)
├── AllergyIntolerance.ndjson        # 患者レベル (重複排除済み)
├── Coverage.ndjson                  # 保険加入 (JP のみ; JP Core 被保険者番号/記号/番号/枝番)
├── Practitioner.ndjson              # 医師、看護師、技師
├── PractitionerRole.ndjson          # 専門科 + organization + 病棟位置
├── Organization.ndjson              # 病院 + 診療科 + 保険者 (保険者、JP)
└── Location.ndjson                  # 病棟 + ベッド + 手術室
```

各行 = 1 FHIR リソース。`Resource.id` は全 resource type 横断で一意。
Reference integrity を維持。

`DocumentReference.ndjson` は `--narrative-version` が version
ディレクトリに解決される時 (default: `current`、Stage 1 の
`TemplateNarrativePass` が維持する `current_version.txt` ポインタ
経由) に emit される。narrative version が存在しないときは残りの
リソース型は通常通り生成。`Coverage.ndjson` (+ 保険者
`Organization`) は JP かつ保険有効時のみ emit
(`--jp-insurance`、デフォルト on)。

### 縦断サービスライン emit (v0.5 → v0.6.0)

いずれのサービスラインも上記標準リソースファイルを通じて emit —
新規リソース型は追加していない。サービスラインのスキーマ詳細は
[`oncology-obstetric-service-lines.ja.md`](oncology-obstetric-service-lines.ja.md)
参照。

- **腫瘍** (10 部位: C15 / C16 / C18 / C22 / C25 / C34 / C50 /
  C61 / C67 / C71、C50 の ~1 % 男性乳がん含む):
  - がん慢性マーカー → `Condition` (ICD-10)。
  - `chemo_visit` LifeEvent (config: `locale/shared/chemo_regimens.yaml`
    — FOLFOX q14d、CarboPem q21d、Trastuzumab q3w、LHRH q28d) →
    外来 `Encounter` + regimen の各薬剤について per-cycle
    `MedicationRequest` + `MedicationAdministration`。
  - 放射線治療 → `Procedure`。
  - 腫瘍マーカー labs (CEA / CA19-9 / AFP / PIVKA-II / CA15-3 /
    PSA) → `Observation` (LOINC laboratory)。
- **産科** (config: `locale/shared/perinatal.yaml`):
  - 妊娠は時限 `TemporalStatePeriod` (`state_type="pregnancy"`)
    として `PersonRecord.state_periods` にモデル化 —
    `perinatal.yaml::lifecycle.annual_conception_rate` (MHLW 2022 /
    CDC NVSR 2022) に対する年齢帯別 conception Bernoulli で open、
    planned delivery date (LMP + 280 d ± 7 d jitter) を含む年で
    `outcome="delivered"` として close、中絶時は abortion date で
    `outcome="aborted"` として close。cross-year 妊娠は
    `state_periods` 経由で carry — 詳細は
    [architecture-notes §9](../architecture/architecture-notes.ja.md)。
  - 妊婦健診 `Encounter` (AMB、obgyn) は妊娠週 12 / 24 / 36 で
    encounter reason Z34。Z34 は problem-list-item Condition を
    emit しない (妊娠は state、慢性状態ではない)。
  - 母親側分娩 `Encounter` (IMP 入院、admit dx O80、discharge dx
    Z37.0、分娩 `Procedure` — JP K894 / US CPT 59400)。
  - 産褥 `Encounter` × 2 (分娩後 7 d と 28 d、encounter reason
    `Z39`、obgyn)。
  - 中絶 outcome (age-gate 15-19 → 35-44) — 外来日帰り手術
    `Encounter` with O03.9 (自然) or O04.5 (人工)。発火時は
    delivery + newborn chain を skip、period は `outcome="aborted"`
    で close。
  - 新生児 `Patient` (id `<mother>-BABY`) を delivery ごとに生成、
    世帯 + 出生日を母親から継承、性別は per-mother sub-RNG から
    サンプリング。新生児 `Encounter` は
    `admit_source = born` (新規 `AdmitSource.BORN` enum member) と
    `Encounter.partOf → Encounter/<母親側 delivery encounter>` で
    link back、discharge dx は `Z38.0`。
  - 過去出産 `Condition` — delivered pregnancy period ごとに Z37
    `problem-list-item` 1 件、`onsetDateTime = delivery_date`
    (emit 時に `state_history("pregnancy")` から導出;
    生物学的整合、多産で複数 Z37)。
  - 新生児 perinatal `Condition`: P59.9 黄疸 ~20 %、P07.3 早産
    ~7 % (→ 条件付き P22.0 RDS ~35 %)、L22 おむつかぶれ ~30 %、
    L20.9 アトピー ~15 %。

### 含まれる FHIR R4 フィールド (主要リソース)

| Resource | Fields |
|---|---|
| Patient | identifier (MRN、type=MR)、name (JP 用漢字+カナ拡張)、gender、birthDate、address、telecom、maritalStatus、communication (BCP-47)、contact (緊急) |
| Encounter | class、type (SNOMED)、serviceType、priority、period、length、participant (ATND/ADM/DIS)、diagnosis ref、hospitalization (admitSource、dischargeDisposition)、location (bed → ward via partOf)、serviceProvider (診療科 Org) |
| Observation | code (LOINC)、valueQuantity (UCUM 単位 + system + code)、referenceRange (low/high/text/source extension for JP Core)、interpretation (N/H/L/HH/LL)、encounter、performer |
| Condition | code (ICD-10-CM with display)、category (encounter-diagnosis / problem-list-item)、severity (SNOMED)、stage (NYHA、CKD G、GOLD 等)、clinicalStatus (active/resolved)、onsetDateTime、recordedDate、encounter |
| MedicationRequest | medicationCodeableConcept (RxNorm)、dosageInstruction (text + doseAndRate + timing repeat + route SNOMED)、encounter、requester、reasonReference |
| MedicationAdministration | dosage (dose SimpleQuantity + route + rateQuantity for continuous)、context、performer、reasonReference |
| Procedure | code (CPT / K-code)、category (SNOMED: surgical/diagnostic/therapeutic)、encounter、performedPeriod、performer[] with function (surgeon/anaesthetist)、recorder、reasonReference、bodySite (SNOMED)、location (手術室)、outcome (SNOMED)、complication (SNOMED) |
| DocumentReference | type (LOINC: 18842-5 / 69730-0 / 11504-8 / 34117-2 / 28570-0)、category (clinical-note)、subject、date、author、content.attachment (base64 text/plain、size、sha1 hash)、context (encounter period、related Procedure) |
| Practitioner | name (with prefix)、gender、telecom、qualification |
| PractitionerRole | practitioner、organization (dept)、location (ward)、specialty (SNOMED) |
| Location | physicalType (wa=ward、bd=bed、area、ro=operating room)、partOf (bed→ward)、managingOrganization |
| Organization | hospital-main + dept-{specialty} (partOf 階層) |

### CSV

```
output/csv/
├── patients.csv
├── encounters.csv
├── conditions.csv
├── lab_results.csv
├── vital_signs.csv
├── orders.csv
├── medication_administrations.csv
├── procedures.csv
└── ...
```

---
