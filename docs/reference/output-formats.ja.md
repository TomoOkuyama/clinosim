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

`DocumentReference.ndjson` は `clinosim export-fhir` に
`--narrative-version` を指定した時 (または
`clinosim simulate --narrative --format fhir` で full pipeline を
実行した時) のみ emit。narrative version なしでは、残りのリソース
型は通常通り生成。`Coverage.ndjson` (+ 保険者 `Organization`) は
JP かつ保険有効時のみ emit (`--jp-insurance`、デフォルト on)。

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
