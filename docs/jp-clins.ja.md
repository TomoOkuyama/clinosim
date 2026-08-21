# JP-CLINS プロファイル対応

clinosim は `country=JP` コホートに対し **JP-CLINS (電子カルテ情報
共有サービス) プロファイル URL** 付きの FHIR R4 リソースを emit
します。本ドキュメントは PR1 で有効化された 6 情報項目を対象とし
ます; 3 種類の Composition (退院時サマリー / 診療情報提供書 / opt-in
健康診断結果報告書) は PR2 と PR3 で追加されます。

jpfhir.jp JP-CLINS **v1.12.0** (2026-02-16) に対して検証済。
<https://jpfhir.jp/fhir/clins/igv1/artifacts.html> 参照。

## スコープ

急性期病院 EHR/EMR データ生成、`country=JP`。

### 6 情報項目 / 5 プロファイル (PR1)

JP-CLINS v1.12.0 は「6 情報項目」ドメイン概念をカバーする
**5 StructureDefinition プロファイル** を公開しています — 傷病名と
感染症は同じ `JP_Condition_eCS` プロファイルを共有 (別個の感染症
プロファイルなし)、DiagnosticReport は JP-CLINS スコープに **含まれ
ない** (検査結果は Observation.LabResult としてのみ emit)。

country=JP コホートの各リソース型は、既存の JP Core プロファイルと
ともに `meta.profile[]` に JP-CLINS eCS プロファイル URL を保持:

| 情報 | Resource | JP-CLINS プロファイル URL |
|---|---|---|
| 傷病名 + 感染症 | Condition | `.../JP_Condition_eCS` |
| アレルギー | AllergyIntolerance | `.../JP_AllergyIntolerance_eCS` |
| 検査 | Observation (category=laboratory) | `.../JP_Observation_LabResult_eCS` |
| 処方 | MedicationRequest | `.../JP_MedicationRequest_eCS` |
| 処置 | Procedure | `.../JP_Procedure_eCS` |

URL ルート: `http://jpfhir.jp/fhir/eCS/StructureDefinition/`

**フィルタ:**

- Observation: `category.coding[].code == "laboratory"` の場合のみ —
  vital sign は JP Core プロファイルのみ保持。

**JP-CLINS v1.12.0 対象外** (JP Core プロファイルのみで emit、
JP-CLINS URL 非追加):

- DiagnosticReport (全 category)
- Observation vital-signs / social-history / survey / imaging
- Encounter / Patient / Organization / Practitioner / Coverage /
  Immunization / FamilyMemberHistory 等 (JP Core が適用基底)

## 例

```json
{
  "resourceType": "MedicationRequest",
  "meta": {
    "profile": [
      "http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationRequest",
      "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_MedicationRequest_eCS"
    ]
  },
  "medicationCodeableConcept": {
    "coding": [{
      "system": "urn:oid:1.2.392.100495.20.1.72",
      "code": "6113005F1023",
      "display": "セフトリアキソンナトリウム注1g"
    }]
  }
}
```

## JP-CLINS 退院時サマリー Composition (PR2a)

`country=JP` の inpatient / icu / rehab_inpatient 退院エンカウンター
全てに対し、clinosim は `JP_Composition_eDischargeSummary` (v1.12.0)
準拠の Composition リソースを emit:

- `Composition.meta.profile` に
  `http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/JP_Composition_eDischargeSummary`
  を含める
- `Composition.type.coding[0].system` =
  `http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes`、
  code = `18842-5`、display = `退院時サマリー`。LOINC coding は US
  ツール互換用に secondary エントリとして保持。
- `Composition.section` は 1 つの nested tree:
  - **300** 構造情報セクション
    - **312** 入院理由セクション
    - **322** 入院時詳細セクション
    - **342** 入院時診断セクション
    - **352** 主訴セクション
    - **360** 現病歴セクション
- `section.code.system` =
  `http://jpfhir.jp/fhir/clins/CodeSystem/jp-codeSystem-clins-document-section`
- `section.text.div` はテンプレート narrative パスにより日本語で
  生成。β-JP-1 で任意に LLM 生成コンテンツに置換可能 (drop-in seam)。

**US パスは不変。** 英語 6 セクション退院サマリー Composition
(`admission_summary` / `hospital_course` / `discharge_diagnoses` /
`discharge_medications` / `discharge_instructions` / `follow_up`、
LOINC-only type coding、JP-CLINS URL なし) は `country=US` で不変
emit。

**多 locale 分離。** US NDJSON 出力には JP CodeSystem URI、
`http://jpfhir.jp/fhir/*` URL prefix、日本語テキストは一切含まれない。
統合テスト
`tests/integration/test_jp_clins_composition_ds_end_to_end.py::test_us_p50_has_no_japanese_language_leakage`
が全 US NDJSON ファイルを byte-by-byte で JP シグナルをスキャン — この
check が本 PR で修正された既存の `_build_reference_range` JP Core
extension leak を浮上させた。

## JP-CLINS 診療情報提供書 Composition (PR2b)

`country=JP` の inpatient / icu / rehab_inpatient 退院エンカウンター
の決定的 20% サブセットに対し、clinosim は
`JP_Composition_eReferral` (v1.12.0) 準拠の **診療情報提供書
(referral note)** Composition を emit:

- Emission 率: 20% (実務急性期病院ベンチマーク)。
  `(encounter_id, patient_id)` の安定 hash で制御 (同 seed → 同一
  referral-note 発行サブセット、新規 RNG allocation なし)。
- `Composition.meta.profile` に
  `http://jpfhir.jp/fhir/eReferral/StructureDefinition/JP_Composition_eReferral`
  を含める
- `Composition.type.coding[0]` = `{system: doc-typecodes, code: 57133-1,
  display: 診療情報提供書}`。LOINC coding は secondary。
- `Composition.section` は 2 レベル tree:
  - Top-level: **920** 紹介元 / **910** 紹介先 / **300** 構造情報
  - 300 の下: **950** 紹介目的 / **340** 傷病名・主訴 /
    **360** 現病歴

シミュレーション近似:
- **紹介元** = 当院 (clinosim は単一施設をシミュレート)。
- **紹介先** = "他院" (汎用プレースホルダ; clinosim は施設間紹介先を
  モデル化しない — 将来作業として妥当な受入病院の小プールからサンプ
  リング可能)。
- **紹介目的** = `encounter_id` ハッシュに基づく `{継続加療 / 精査
  依頼 / 他科紹介 / リハビリテーション継続}` の決定的選択。
- **傷病名・主訴** = エンカウンター診断リスト (code + 日本語 display)
  と疾患 YAML の chief complaint を結合。
- **現病歴** = `disease_protocol.narrative.hpi_template` 由来の HPI
  (退院時サマリーの present_illness セクションと同ソース)。

**US パス**: 診療情報提供書は `country=US` で emit しない
(`countries_supported: [jp]`)。US 臨床実践では通常の紹介状を使用し、
JP-CLINS eReferral プロファイルは使わない。

## JP-eCheckup 健診結果報告書 Composition (PR3、opt-in)

`country=JP` かつ `SimulatorConfig.modules["health_checkup"]=True` の
場合、健診エンカウンターに対し **健診結果報告書 (health checkup
report)** Composition を `JP_Composition_eCheckupGeneral`
(JP-eCheckup General v1.7.0) 準拠で emit。急性期病院想定を維持する
ため **default off**。

Note: 健診 IG は JP-CLINS と別に発行 (JP-eCheckup General v1.7.0、
2026-02-16)。canonical URL は `/fhir/eCheckup/` 配下で、CodeSystem
も別 (section-code は 5 桁数値、JP-CLINS の 3 桁とは異なる)。

- `Composition.meta.profile` =
  `http://jpfhir.jp/fhir/eCheckup/StructureDefinition/JP_Composition_eCheckupGeneral`
- `Composition.type.coding[0]` = `{system: doc-typecodes, code: 53576-5,
  display: 検診・健診報告書}`。LOINC coding も secondary で併存。
- `Composition.section` は flat 2 個 (nesting なし):
  - **01031** 事業者健診検査結果セクション
  - **01032** 事業者健診問診結果セクション
- `section.code.system` =
  `http://jpfhir.jp/fhir/eCheckup/CodeSystem/section-code`

**対象範囲 (scope)**:
- 3 健診種別すべて対応 (sub-PR-D、session 47):
  - **事業者健診** (occupational、40-64 歳): section 01031 + 01032
  - **特定健診** (specific、65-74 歳): section 01011 + 01012
  - **広域連合健診** (regional_union、75 歳以上): section 01021 + 01022

  種別選定は `_pick_checkup_type(age)` による age-based 決定的マッピ
  ング。MVP は年齢帯単一 dispatch (実務では 40-64 歳の保険加入者は
  特定健診対象になる場合もあるが、simulation では単純化)。将来:
  保険種別 / 就業状態を参照した精緻化余地あり。ClinicalDocument に
  `checkup_type: str` field を追加 (sub-PR-D)、Composition builder
  が dispatch。
- section content は個別化済 (sub-PR-B、session 47):
  - **01031 検査結果**: record.lab_results から 5 項目 (BMI /
    収縮期 BP / 拡張期 BP / HbA1c / LDL) の実測値を拾い、法定健診
    基準で A/B/C/D 判定を組み立てる。総合判定は各項目の最悪 grade。
  - **01032 問診結果**: PatientProfile 参照で個別化
    (chronic_conditions → 既往歴、current_medications → 服薬、
    smoking_status/alcohol_use → 生活習慣)。慢性疾患保有時は
    「継続経過観察を要す」判定。
- **健診 encounter 生成 module** (sub-PR-A、session 47 で追加):
  `clinosim/modules/health_checkup/` の POST_RECORDS enricher が
  `SimulatorConfig.modules["health_checkup"]=True` + country=JP 時に
  発火。40 歳以上の成人患者から SHA-256 hash-based 決定的 30% サブ
  セットを選び、各患者に 1 CHECKUP encounter (1 日完結) + 法定健診
  5 項目 ObservationRecord + HEALTH_CHECKUP_REPORT stub を追加する。
  narrative content は Stage 2 の TemplateNarrativePass が populate、
  FHIR emit は `_build_jp_eCheckup_general_composition` が担う。
- **法定健診 5 項目の実測値個別化 (sub-PR-B 高度化、session 48)**:
  かつては固定値 (BMI 22.5 / SBP 118 / DBP 76 / HbA1c 5.4 /
  LDL 118) だったが、`_derive_checkup_values(patient, rng)` が
  PatientProfile と chronic_conditions を反映するよう改修:
  - **BMI** = `patient.bmi` + 測定日変動 (sd 0.3 kg/m²)
  - **SBP/DBP** = `patient.baseline_vitals` を base に日間変動
    (sd 5.0/3.5 mmHg)。高血圧 (I10) は FP-I10 (session 38) で
    baseline_vitals に反映済み
  - **HbA1c** = 糖尿病 (E10/E11) 保有時は
    `hba1c_from_glycemic_control` を reuse (physiology 経路と一貫)、
    非 DM は `HBA1C_NONDM_BASE` + 年齢係数 0.003 + noise
  - **LDL** = 年齢/性別 baseline + 脂質異常症 (E78) で +40 mg/dL +
    スタチン系薬 (`-statin` 末尾) で -30 mg/dL
  - RNG は `ENRICHER_SEED_OFFSETS["health_checkup"] = 0x4843` から
    `derive_sub_seed(master, offset, patient_id)` で per-patient に
    確定。同 seed + 同 patient で byte-identical (AD-16 準拠)
  - `OrderResult.interpretation` ("N"/"H") と `reference_range` も
    LOINC 別に `_interp_for` で付与、"H" フラグは renderer の
    A/B/C/D 判定と整合

**US path**: 健診 opt-in flag は US では発火しない
(`countries_supported: [jp]` により spec 側で JP に限定)。

### DocumentReference wrapper (sub-PR-E、session 48)

HEALTH_CHECKUP_REPORT の Composition と併存する DocumentReference
を追加発行:

- **対象**: `ClinicalDocument.task_type == "health_checkup_report"`
  かつ `format_type == "composition"` (discharge_summary /
  referral_note は emit しない)
- **id 命名**: `drf-<document_id>` (Composition の id と衝突しない
  prefix)
- **参照**: `relatesTo=[{code:"transforms", target: Composition/<id>}]`
- **content**: narrative.text (空なら sections 値 join) を base64
  で添付
- **category**: JP-eCheckup doc-typecodes `eCheckupGeneral` (健診
  結果報告書)
- **encounter context**: `Encounter/CHK-<pid>-<seq>` に紐付け
- **custodian**: `Organization/hospital-main`
- **byte-diff invariant**: JP かつ opt-in 有効時のみ emit、
  reproduce.sh の default runs は影響なし (既に確認済み)

実 EHR 交換シナリオ: Composition = 構造化 (section で保持)、
DocumentReference = portable な wrapper。事業所 ⇄ 保険者 ⇄ 実施機関
間の交換で DocumentReference を使うことが多いため、両者併存が
JP-eCheckup interchange の標準形。

## JP FHIR Validator Bridge (PR3 sub-PR-C、session 48 高度化)

session 47 で `scripts/validate_jp.sh` と
`.github/workflows/jp-validate.yml` を追加、session 48 で **SHA256
pin + auto-fail gate 化** に高度化しました。**JP 出力を HL7 公式
FHIR Validator で JP Core / JP-CLINS / JP-eCheckup に適合検証** し、
pin mismatch や validation failure で CI が自動 fail します。

### Pin ファイル (session 48 追加)

`.github/jp-validator-pins.env` に validator と IG package の
バージョン / SHA256 が集約:

```env
VALIDATOR_VERSION=6.4.3
VALIDATOR_SHA256=

JP_CORE_PACKAGE_ID=jp-core.r4
JP_CORE_PACKAGE_VERSION=1.1.7
JP_CORE_PACKAGE_URL=
JP_CORE_PACKAGE_SHA256=

JP_CLINS_PACKAGE_URL=
JP_CLINS_PACKAGE_SHA256=

JP_ECHECKUP_PACKAGE_URL=
JP_ECHECKUP_PACKAGE_SHA256=
```

- SHA256 空欄 + STRICT モード = fail (bootstrap 指示メッセージを出力)
- SHA256 記入済 = 実測との一致確認 → mismatch で fail

### 初回 pin bootstrap

```bash
bash scripts/pin_jp_validator.sh
git diff .github/jp-validator-pins.env  # ← 差分確認
git commit -m "chore(jp-validate): pin validator + IG SHA256"
```

`PIN_FILE=<path>` / `DRY_RUN=1` で挙動を上書き可能。

### Local 実行

```bash
# サンプル抽出のみ (validator jar 未指定なら skip)
./scripts/validate_jp.sh

# 実際の validator 実行 + pin gate (要 Java 11+)
VALIDATOR_JAR=/path/to/validator_cli.jar \
CLINOSIM_JP_VAL_PINS=.github/jp-validator-pins.env \
CLINOSIM_JP_VAL_STRICT=1 \
./scripts/validate_jp.sh
```

環境変数:
- `VALIDATOR_JAR` (必須): HL7 公式 validator jar のパス。
- `CLINOSIM_JP_VAL_PINS`: pin file 参照 (未指定なら IG resolve は
  skip)。
- `CLINOSIM_JP_VAL_STRICT`: `1` で SHA256 mismatch / sample 0 抽出
  → exit 1。
- `CLINOSIM_JP_VAL_POPULATION`: default 10
- `CLINOSIM_JP_VAL_SEED`: default 42
- `CLINOSIM_JP_VAL_END`: default 2026-06-30
- `CLINOSIM_JP_VAL_HEALTH`: default "1" (health_checkup opt-in)

### 検証対象 (MVP)

小規模 JP コホート生成後、以下 profile 対応 resource から代表 1 件
を抽出して検証:

- `JP_Condition_eCS`
- `JP_AllergyIntolerance_eCS`
- `JP_Observation_LabResult_eCS` (laboratory category)
- `JP_MedicationRequest_eCS`
- `JP_Procedure_eCS`
- `JP_Composition_eDischargeSummary`
- `JP_Composition_eReferral`
- `JP_Composition_eCheckupGeneral` (health_checkup opt-in 時)

### CI 実行 (auto-fail gate、session 48 高度化)

`.github/workflows/jp-validate.yml`:

- **workflow_dispatch**: `run_validator=true` (default) +
  `strict_pins=true` (default) → SHA256 mismatch / validator FAIL /
  sample 0 抽出のいずれかで **job が自動 fail**
- **PR label**: `jp-validate` ラベルを付けた PR で自動実行 (default
  STRICT)

CI 時間の浪費を防ぐため、通常の PR CI パイプラインには組み込まず、
必要時のみ手動 or label で回す設計です。

### 将来の高度化余地

- 全 resource 検証 (現状 profile あたり 1 サンプルのみ)
- packages.fhir.org 登録前の JP-CLINS / JP-eCheckup の direct .tgz
  URL 確定と `_PACKAGE_URL` フィールドへの反映
- JP profile violation の granular reporting (現状は tail 5 行のみ)

## 再現性

本レイヤは決定的 — `scripts/reproduce.sh` は country=JP 出力が
独立実行間でバイト同一のまま継続 pass。

## PR1 対象外

spec §1.3 (`docs/history/specs-archive/2026-07-12-p2-13-jp-clins-design.md`)
参照:

- 3 種類の Composition (退院時サマリー / 診療情報提供書 / 健康診断
  結果報告書) — PR2 + PR3
- 健診 encounter 生成 — PR3 opt-in
- 機関間連携 workflow simulation — non-goal

## Deferred improvement candidates

Session 47 preflight review で浮上した将来 PR で再訪する価値のある
3 項目。session 88k 時点の状況:

- ✅ CLI 動詞 `generate` → `simulate` リネーム + deprecation alias —
  landed; `clinosim/simulator/cli.py` で `generate` は alias として
  残存。
- ✅ `_JP_CORE_PROFILES` shape 統一 (`dict[str, str]` →
  `dict[str, list[str]]`) — landed; JP-CLINS eCS profile dispatch と
  ともに `clinosim/modules/output/fhir_r4_adapter.py` に反映。
- ⏳ CIF `orders` リスト分割 `medication_orders` / `lab_orders`
  (FHIR resource-type 分離との整合) — 未着手; 候補として継続。

各々は小規模独立リファクタ — P2-13 に折り込むより自身の PR として
届ける方が適切。
