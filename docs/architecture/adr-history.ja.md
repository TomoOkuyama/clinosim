## Part 9: 日本語 narrative localization (2026-04-13)

### AD-42: 日本語 locale 用のコード側単位変換

CIF は lab 値を SI 単位で保持 (CRP は mg/L)。日本の臨床慣習は CRP を
mg/dL で扱う。LLM に変換を依頼すると (一貫性がなかったため) コード
側で変換する:

- `hospital_course_extractor.format_lab_trends(trends, language="ja")`
  は `_JA_CONVERSION` factor を適用
- `document_generator._initial_labs(record, language="ja")` も同一
  変換を適用
- `_JA_CONVERSION = {"CRP": 0.1}` — mg/L に 0.1 を掛けて mg/dL に
  変換
- プロンプトは「input の単位をそのまま使う」と指示 — LLM 側変換なし

この機構は拡張可能: `_JA_CONVERSION` と `_UNIT_MAP_JA` にエントリを
追加すれば他の locale 固有単位にも対応可能。

### AD-43: 日本語 narrative プロンプト品質規則

5 つの日本語プロンプト全て (`prompts/ja/*.yaml`) が以下を強制:

1. **医師名接尾辞**: 「医師名には必ず「医師」を付けてください」 —
   Dr./接頭辞なしの不整合出力を防止
2. **単位パススルー**: 「検査値の単位は入力データのまま使用してくだ
   さい」 — LLM が「(換算値)」等の注釈を追加したり変換過程を表示
   したりするのを防止
3. **捏造禁止**: 全プロンプトが入力に存在しないデータの捏造を禁止
   (EN プロンプトと一致)

### 慢性薬剤 base code フォールバック

`chronic_medications.yaml` のキーは specific ICD コード (例:
`E11.9`)。退院後、`_deactivate_to_layer1()` はコードを base 形式
(`E11`) に正規化する。`inpatient.py` の薬剤 lookup は base コードに
フォールバックする:

```python
spec = chronic_meds.get(code) or chronic_meds.get(code.split(".")[0])
```

これは `activator.py:326` の既存フォールバックと一致し、再入院時の
薬剤消失を防止する。

### JP FHIR localization 概要

FHIR R4 アダプタは `country="JP"` のとき日本語 localization を適用:

| Resource | Field | JP value |
|---|---|---|
| Location | name | `4E病棟`, `4E-01号室` |
| Encounter | type | `入院`, `外来`, `救急` |
| Encounter | serviceType | `内科`, `外科`, etc. |
| Patient | maritalStatus | `既婚`, `未婚` |
| MedicationRequest | dosageInstruction.route | `経口`, `静注`, `皮下注` |
| MedicationRequest | dosageInstruction.timing | `1日1回`, `1日2回`, `6時間毎` |
| Practitioner | qualification | `医師` |

全 localization は FHIR 出力時に行う (AD-30)。CIF は language-neutral
のまま。

---

## Part 10: FHIR 標準準拠 + 労働災害 (2026-04-19)

### AD-44: enrichment は language-neutral

患者 8 名 × 2 文書種別 (admission_hp, discharge_summary) の A/B
テストが以下を確認:

| 観点 | A (事前 JP 化) | B (英語、LLM が翻訳) |
|--------|---------------------|---------------------------|
| 薬剤/手技名 | 両方正しい | 両方正しい |
| 自然な日本語の流れ | やや機械的 | より自然 |
| CRP 単位 | 正しい (mg/dL) | **誤り** (mg/L 混入) |
| 診断短縮名 | 正しい | ICD フルネーム (不自然) |
| Token 使用 | 9,219 | 9,231 (≈ 同一) |

**結論**: LLM は自由文の翻訳は得意だが、計算 (CRP) やコード正規化
(ICD display) は失敗する。code_lookup + CRP 変換のみ残す。それ以外
は全て英語。

### AD-45: 職業モデル

```
PersonRecord.occupation: str  →  PatientProfile.occupation: str
                                  ↓
                         FHIR Observation (LOINC 11341-5, social-history)
```

Category: manufacturing / construction / agriculture / healthcare /
service / office / transportation / education / homemaker / student /
retired / unemployed / other。

`demographics.yaml` が以下を提供:
- `occupation_distribution.working_age` — 国別労働統計
- `occupation_risk_multipliers` — 職業別 injury type risk (例:
  crush_injury_hand × 6.0 for manufacturing)

### AD-46: 多言語 FHIR coding

Condition + Procedure リソースは dual `coding[]` エントリを emit:

```json
{
  "coding": [
    {"system": "icd-10", "code": "J44.1", "display": "その他の慢性閉塞性肺疾患"},
    {"system": "icd-10", "code": "J44.1", "display": "Other chronic obstructive pulmonary disease"}
  ],
  "text": "COPD（慢性閉塞性肺疾患）"
}
```

`_build_diagnosis_codeable_concept()` は `icd-10` を試行 → `icd-10-cm`
→ `"(display unavailable)"` にフォールバック。`code.text` は
`_CONDITION_SHORT_NAME` を用いて search-friendly な省略形にする
(AD-49)。

### AD-47: Observation referenceRange + interpretation 一貫性

FHIR R5 Note 5 より: "the interpretation should be consistent with
the reference range when both are provided"。

- Lab interpretation は value vs normal range から再計算 (CIF flag
  を単独では信用しない)
- Critical flag (H*/L*/critical) → directional LL/HH (generic AA で
  はない)
- vital sign は 2 つの referenceRange エントリを emit: `type=normal`
  と `type=treatment` (critical/panic)
- SpO2: `crit_high=None` (上側 critical なし — 100% は normal で HH
  ではない)

### AD-48: procedure_name を CIF から除去

厳密 AD-30 準拠: `ProcedureRecord` はもはや `procedure_name` field
を持たない。display は出力時に
`code_lookup("k-codes"|"cpt", code, lang)` で解決。多言語出力の
ため `procedure_code_jp` と `procedure_code_us` の両方を保存する。
`_resolve_procedure_name(proc_dict, lang)` は全 consumer 共通の
共有ヘルパー。

### 労働災害 YAML

4 入院 (disease/reference_data/):
- `crush_injury_hand.yaml` (S67.2, ICD)
- `industrial_burn_severe.yaml` (T31.2, ICD)
- `fall_from_height.yaml` (T07, ICD)
- `electrical_injury.yaml` (T75.4, ICD)

2 ED (encounter/reference_data/):
- `eye_foreign_body.yaml` (T15.0, ICD)
- `chemical_exposure.yaml` (T54.9, ICD)

全て `probability` (ED weighted selection 用) と age_rates/sex_ratio
(入院 incidence 用) を持つ。職業リスクマルチプライヤは industrial
worker に event を集中させる。

---

### AD-61: Lab ServiceRequest emission、panel-aware grouping

**Status:** Accepted (PR1, 2026-06-29)
**Context:** EHR/EMR サンプルデータセット target (Tier 1 #1) は
lab order lifecycle 用の FHIR ServiceRequest を要求する。JP Core
/ US Core の慣用的 emission は panel-level (WBC/Hb/Hct/Plt ごと
ではなく CBC あたり 1 SR)。
**Decision:** `Order.panel_key` 1 field を追加 (空 = stand-alone)。
Order エンジンは lab_panel_groups.yaml (canonical loader は
`order/panel_grouping.py` に統一) を再利用して panel_key + 共有
ordered_datetime を panel member に割り当てる。新しい
`_fhir_service_request.py` builder は Order を
`(encounter_id, panel_key, ordered_datetime)` でグループ化して
panel instance あたり 1 SR を emit; stand-alone Order は各 1 SR
を emit。JP Core 準拠は HL7 v2-0203 PLAC identifier type +
dual category coding (SNOMED 108252007 + v2-0074 LAB) 経由。
**Consequences:** lab order の rng draw count 変化 (per-test draw
ではなく per-panel draw)。e2e attribute-based test は変化なし
(run_alpha golden patient FORCED-0001 に影響なし)。プロダクション
スケール US p=10k + JP p=5k で検証済 (362k+42k SR、dangling ref 0、
audit silent_no_op 7/7 PASS)。ServiceRequest は Tier 1 #2-#7
(Imaging / NutritionOrder / ADT / DocumentReference / Appointment /
CarePlan) の基盤。

### AD-62: 画像 metadata-only chain + WADO-RS placeholder

**Status:** Accepted (Tier 1 #2, 2026-06-30)
**Context:** Tier 1 #2 EHR/EMR サンプルデータセット拡張は放射線
NLP/IE/CDSS/revenue-cycle/PACS-migration 評価用の画像 metadata
基盤を要求。DICOM pixel データ生成は外部 image-gen AI に defer。

**Decision:** always-on Module パターン (device/hai/antibiotic 先例)
を採用し、`ImagingStudyRecord` を `extensions["imaging"]` に配置。
4 FHIR resource を emit: ServiceRequest (imaging category、
SNOMED 363679005 + v2-0074 RAD)、ImagingStudy (urn:dicom:uid
identifier、DCM modality、multi-series)、DiagnosticReport (放射線
バリアントで findings + impression を `text.div` に + `conclusion`)、
Endpoint (`hospital_config.imaging.wado_base_url` 経由の WADO-RS
placeholder URL)。ポリモーフィック `_fhir_service_request` が
1 builder から LAB + IMAGING category を dispatch。

**Consequences:**
- CIF → FHIR no-drop 不変条件を強制 (emission matrix: 各
  `ImagingStudyRecord` は ImagingStudy + Endpoint + 放射線 DR +
  imaging SR に 1:1 で map)
- 将来の image-gen AI 統合点: Endpoint.address 置換 +
  urn:dicom:uid lookup
- AD-55 always-on Module 数は 4 に増加 (device、hai、antibiotic、
  imaging)。POST_ENCOUNTER order=90 (antibiotic=85 の後)
- 15-check `lift_firing_proof` (AD-60 audit) は ImagingStudy +
  Endpoint + 放射線 DR + imaging SR の非ゼロ emission と JP locale
  display 正確性 (modality display / bodySite display / DR.code /
  conclusion) を検証
- レガシー IMAGING order (`imaging_modality` メタデータのない
  Chest_Xray / CT_abdomen_pelvis) は enricher に silent に skip
  され ImagingStudy なしの Order-only レコードとして残る
  (TODO.md の migration 追跡対象)

### AD-63: 文書 narrative + 構造化イベント密度基盤

**Status:** Accepted (Tier 1 #3 α-min-1, 2026-07-01)
**Context:** Tier 1 #3 EHR/EMR サンプルデータセット拡張は臨床
文書密度基盤を要求。chain 前 baseline: DocumentReference = 0
(Stage 1 `generate` のみ; Stage 2 `narrate` は別 LLM step が必要)、
Composition = 0、ClinicalImpression = 0。目標: 全 inpatient/ICU/rehab
encounter に対して 3 コア文書種別を Stage 1 テンプレート駆動で
デフォルト emit する。AllergyIntolerance schema は 3-field
(allergen 文字列のみ) だったが、JP Core Allergy profile に沿って
8-field SNOMED-coded schema (allergen code + reaction manifestation
+ category + criticality + clinical status + verification status +
onset period + note) にアップグレードした。

**Decision:** 2 つの新しい always-on Module (device/hai/antibiotic/imaging
と同じ `enabled=lambda c: True` パターン):
- `allergy` (POST_POPULATION order=10): activator.py の inline 15%
  allergy sampling を、`PersonRecord.allergies: list[Allergy] | None`
  (None = 未 enrich sentinel; [] = sampling 後 allergy なし) を書き
  込む proper enricher に置換。新しい `_fhir_allergy_intolerance.py`
  builder が SNOMED-coded `AllergyIntolerance` を生成する。
- `document` (order=95): `TemplateNarrativeGenerator` の 5-step
  fallback chain 経由で `ClinicalDocument` レコード (DR + CI 用
  free_text、Composition 用 composition) を emit。LLM 駆動生成は
  defer (Task 15 で既存 LLM provider integration を配線)。

CIF 保存: `CIFPatientRecord.documents` (typed field) が
`list[ClinicalDocument]` を保存;
`extensions["clinical_impressions"]` が
`list[ClinicalImpressionRecord]` を保存。コア型 `ClinicalDocument`
は 2 field を追加: `sections: dict[str, str]` (section 名 → text、
Composition.section[] 再構成に必須) と `format_type: str` (builder
選択 dispatch key: "free_text" vs "composition")。

3 新規 FHIR builder:
- `_fhir_documents.py` (DOC_REFERENCE_ID_PREFIX = "doc-")
- `_fhir_composition.py` (COMPOSITION_ID_PREFIX = "comp-")
- `_fhir_clinical_impression.py` (CLINICAL_IMPRESSION_ID_PREFIX = "ci-")

**Consequences:**
- Stage 1 `generate` が 3 文書 class の FHIR resource type をデフォ
  ルト emit するようになり、`narrate` を要求せずに EHR サンプル
  データセットの文書密度ギャップを閉鎖
- Task 15 (同 branch) が migration を完了: レガシー
  `narrative_generator.py` / `document_generator.py` は削除;
  activator.py の allergy inline sampling は除去。共存 path が残ら
  ないため dedup guard 不要。
- CIF→FHIR no-drop 不変条件は `ClinicalDocument.sections` field
  経由で強制: Composition builder は raw_text を再解析せず
  sections を直接読む (Task 8 fix の教訓 — 「sections が
  COMPOSITION の authoritative source; raw_text は FREE_TEXT のみ」)
- AD-55 always-on Module 数は 6 に増加 (device、hai、antibiotic、
  imaging、allergy、document)。stage: allergy (POST_POPULATION order=10)
  → document (POST_ENCOUNTER order=95)
- 17-check `lift_firing_proof` (AD-60 audit) は 4 canonical ID
  prefix、4 emission gate、3 ID-prefix format check、5 no-drop
  不変条件 (spec §3.4) を検証
- 将来の phase: α-min-3 (outpatient/ED POST_ENCOUNTER gap fix +
  Practitioner roster 拡張)、β-JP-1 (完全 JP localization /
  QuestionnaireResponse / 厚労省必須文書)、β-2 (手術記録 /
  MedicationDispense / Procedure 密度)

### AD-64: Nursing + Outpatient + ED + CareTeam 密度基盤

**Status:** Accepted (Tier 1 #3 α-min-2, 2026-07-01)
**Context:** α-min-1 (AD-63) は入院 encounter のみに Stage 1 文書
emission インフラを確立。3 つの大きなギャップが残った: (1) CareTeam
= 0 (全 encounter type)、(2) 看護ドメイン文書 = 0 (看護ドメイン
always-on Module なし)、(3) 外来 / 救急 encounter 文書 = 0 (外来
SOAP / ED note / triage note なし)。EHR/EMR サンプルデータセット
目標は全 encounter type に対して看護師 authored 文書密度と
primary team allocation を要求。

**Decision:** 3 つの新しい always-on POST_ENCOUNTER Module
(device/hai/antibiotic/imaging 先例と同じ `enabled=lambda c: True`
パターン):

1. **`triage` (POST_ENCOUNTER order=93)**: ED-only enricher。JTAS
   (JP) / ESI (US) triage level、arrival_mode (救急車 / 徒歩)、
   `triage_protocols.yaml` から acuity_score を sample。
   `EncounterRecord.triage_data` (新 field) を書き込む。
   document_enricher が `ED_TRIAGE_NOTE` LOINC 54094-8 dispatch に
   consume。

2. **`nursing_assignment` (POST_ENCOUNTER order=94)**: 入院 / ICU /
   rehab enricher。encounter の病棟の StaffRoster から primary
   nurse を assign。`EncounterRecord.primary_nurse_id` (新 field)
   を書き込む。`_fhir_care_team.py` builder が
   CareTeam.participant[1] に consume。**命名注**: モジュール
   ディレクトリは `modules/nursing/` だが、enricher 関数は
   `nursing_enricher` (POST_ENCOUNTER)。既存の POST_RECORDS
   nursing モジュール (`observation/nursing.py`) は
   NEWS2/GCS/Braden/Morse を処理 — 同ディレクトリ下の別 stage に
   登録された **異なる** モジュール。

3. **`_fhir_care_team.py` builder**: `_bb_care_teams` として
   `register_bundle_builder()` で登録された新 FHIR builder。全
   encounter type について encounter あたり 1 CareTeam resource を
   emit。2 名 scope: participant[0] = 主治医、participant[1] =
   primary nurse (assign 済のとき)。CareTeam ID =
   `careteam-{encounter_id}` (CARE_TEAM_ID_PREFIX canonical
   constant)。

4. **6 新 DocumentType spec** — `document_type_specs.yaml`:
   - `admission_nursing_assessment` (78390-2, Composition,
     admission_once, inpatient)
   - `nursing_shift_note` (34746-8, DocumentReference free_text,
     daily, inpatient)
   - `nursing_discharge_summary` (34745-0, Composition,
     discharge_once, inpatient)
   - `outpatient_soap` (34131-3, Composition, encounter_once,
     outpatient)
   - `ed_note` (34878-9, Composition, encounter_once, emergency)
   - `ed_triage_note` (54094-8, DocumentReference free_text,
     encounter_once, emergency)

   `DocumentTypeSpec.encounter_types_supported` field (α-min-2
   Task 10 で導入) は encounter_type ごとの dispatch を制御。
   α-min-1 spec は明示的 `[inpatient, icu, rehab_inpatient]`
   allowlist を持つ (Task 10 データ品質 fix: 外来 / ED への入院
   文書 leak を防止)。

5. **46 encounter YAML narrative 拡張**: 全 46 encounter YAML
   ファイルが outpatient_soap / ed_note / ed_triage テンプレート
   の `narrative:` ブロックを受領 (outpatient_soap + ED encounter
   type 向け)。5 priority condition が詳細 narrative を持ち、41 は
   baseline テンプレートテキストを使う。

6. **Task 8 LOINC 検証**: 6 候補 LOINC の 3 つを NLM 検証経由で
   訂正 (ADMISSION_NURSING_ASSESSMENT 34820-1→78390-2、
   OUTPATIENT_SOAP 11488-4→34131-3、ED_NOTE 51841-6→34878-9)。
   全 code が `codes/data/loinc.yaml` に登録 (EN + JA bilingual)。

**Consequences:**
- CIF → FHIR no-drop 不変条件: CareTeam (Encounter と 1:1) + 3
  看護文書タイプ (入院 encounter と 1:1) は
  lift_firing_proof equality_checks 18-25 で強制
- AD-55 always-on Module 数は 8 に増加 (device、hai、antibiotic、
  imaging、triage、nursing_assignment、allergy、document)。
  POST_ENCOUNTER ordering: 70/80/85/90/93/94/95
- **既知のプロダクションギャップ**: outpatient.py + emergency.py
  は POST_ENCOUNTER enricher を **invoke しない** (inpatient.py
  のみ実施)。OUTPATIENT_SOAP / ED_NOTE / ED_TRIAGE_NOTE は
  プロダクションで 0 リソースしか生成しない。dispatch ロジックは
  正しい (audit proof checks 22-25 で検証済); fix は outpatient.py
  + emergency.py に `run_stage(POST_ENCOUNTER, ...)` を追加すること
  (α-min-3 に予定)。
- **命名衝突ガード**: `modules/nursing/` は `nursing_enricher`
  (POST_ENCOUNTER order=94、primary_nurse assign) と
  `nursery_enricher` (POST_RECORDS observation) の両方を含む。
  参照時は必ず enricher 名を指定。`nursing_assignment` =
  POST_ENCOUNTER。`nursing` (observation) = POST_RECORDS。
- **CareTeam 2 名 scope**: β-JP-1 で 6 名の多職種チーム (薬剤師 /
  栄養士 / リハ / MSW / charge nurse) に拡張。AD-64 scope = 医師
  + 看護師のみ。
- 25-check `lift_firing_proof` (17 α-min-1 + 8 α-min-2)。
  silent_no_op PASS (US + JP コホート両方)。臨床軸 PASS:
  158,811 US / 16,046 JP CareTeam、0 unknown_attending。
- プロダクションコホート: US p=10k (158,811 CareTeam + 46,558 DR
  + 17,946 Composition) + JP p=5k (16,046 CareTeam + 7,416 DR +
  970 Composition)。DQR:
  `docs/reviews/2026-07-01-tier1-3-document-density-alpha-min-2-dqr.md`

### AD-65: Structural + Narrative CIF ファイル分離 (two-pass generation)

**Status:** Accepted (Tier 1 #3 α-min-2b, 2026-07-02, session 28)

**Context:**
- clinosim の initial アーキテクチャ (`clinosim/modules/output/SPEC.md`)
  は 3 段パイプラインを定義: structural CIF Stage 1 (immutable) /
  narrative Stage 2 (別 version dir) / Stage 3 (adapter merge)。
- α-min-1 Task 15 (commit `2c09b6a099`) はレガシー narrative
  サブシステム (`document_generator.py` 951 行、
  `narrative_generator.py` 205 行) を削除し、narrative 生成を
  `document_enricher` に折り込んだ。当時、Stage 1 デフォルト
  emission ギャップの閉鎖としては正しかったが、長期的な Stage 2
  置換アーキテクチャとしては premature deletion となり、
  `clinosim/modules/output/SPEC.md` の Stage 2 設計から drift が
  生じた。
- Session 27 Clinical Integrity review が 3 つの Critical narrative
  bug を発見。inline-only パターンは修正のためにフルコホート再生成
  を要求し、開発速度を破壊する。
- ユーザが (session 27→28 で) 明示的に示した: original design は
  structural CIF と narrative CIF を separate file として想定して
  いた = SPEC.md original design の復元。

**Decision:**
1. `ClinicalDocument` を stub-only にリファクタ: metadata + author
   + encounter binding、`narrative: ClinicalDocumentNarrative | None`
   field (新型) を持つ。narrative content (text/sections/facts_used)
   の populate は Stage 1 では禁止。
2. two-pass CIF 生成パイプラインを復元 (SPEC.md original design
   intent の完全復元)。
3. `clinosim narrate` CLI verb を復活 (フォールバックとして template
   mode; LLM の実際の呼び出しは β-JP-1 に defer)。
4. Bedrock prompt-cache 対応の walk order contract を確立:
   `NarrativePass` base class が `(doc_type, language)` group の
   serial iteration を保証。
5. `NarrativeContext` を 3 つの拡張で拡大: `NarrativeSpine`
   (scenario anchoring)、`materialized_facts` (fact-first generation)、
   `section_facts` (COMPOSITION section extraction)。
6. silent CLI override (Bug D) を修正: `-p` 明示値がもはや
   `recommended_population` に silent に上書きされない。
7. dev iteration facility を追加: `test-disease --format` +
   `test-encounter --format` + `--output` flag + standalone
   `narrate` verb により narrative bug 検証サイクルを 10–30 秒に
   短縮 (フル generate の 5–50 分に対して)。

**Consequences:**
- narrative bug 検証: `narrate --tasks <task>` (~30 秒) +
  `test-disease --format all` (~10 秒) 経由の structural = 100 倍
  高速な開発サイクル。
- FHIR builder はもはや `doc.narrative.*` 経由でのみ narrative
  content にアクセス → 唯一の source of truth (`document_enricher`
  と Stage 2 pass の競合を防止)。
- β-JP-1 は `LLMNarrativePass` を `NarrativePass` base class の
  drop-in サブクラスとして実装可能、Bedrock walk-order contract を
  無変更で継承。
- 全 39 既存 e2e goldens が完全再生成要 (後方互換性なし)。
- CLAUDE.md に 5 つの新 AD-65 rule を追加 (next-session drift 防止:
  two-pass 不変条件、stub-only enricher、narrative post-simulation、
  walk order、FHIR builder wrapper)。

**Alternatives considered:**
- **Approach A** (Inline populate + writer split): silent-no-op
  risk が低い; Stage 2 置換対称性が弱い → 却下。
- **Approach B** (Explicit two-pass、auto-invoke なし): UX 変更が
  大きい → inline default (`clinosim generate` ユーザ体験を保持) を
  優先して却下。
- **Approach C** (Flat field + wrapper なしの物理分割): 多層防御が
  弱い → `ClinicalDocumentNarrative` wrapper 型を優先して却下。

**Related ADRs:** AD-30 / AD-55 / AD-56 / AD-60 / AD-63 / AD-64

---

### AD-66 · narrative 回帰用の canonical patient profile fixture library

**Date:** 2026-07-03 (α-min-2c chain)

**Status:** Accepted

**Context:**
AD-65 の two-pass CIF アーキテクチャにより、template narrative 出力
を canonical baseline と比較できるようになった。β-JP-1 は
`LLMNarrativePass` を導入し、非決定的な LLM 出力を produce する。
narrative 回帰 (テンプレート drift、LLM drift、semantic 変化) を
検出するために、決定的な patient profile 集合 + 期待される
narrative 出力を diff 対象として持つ必要がある。

**Decision:**
6 つの canonical patient profile YAML fixture を
`tests/fixtures/patient_profiles/` に同梱し、それぞれに seed 42
での期待される template narrative 出力を含む `<profile>.golden.json`
ファイルを付随させる。`pytest -m regression` suite が subprocess で
`clinosim test-disease --patient-profile <id>` を invoke し、
生成された narrative を golden と byte-diff する。

新規 `PatientProfile` Pydantic 型を `clinosim/types/config.py` に
`.to_forced_scenario()` transform 付きで導入、bootstrap + 再生成
用の `clinosim regenerate-goldens` CLI subcommand を追加。

α-min-2c での scope-in: 6 疾患ベースの入院/ICU profile のみ。
scope-out (β-JP-1 以降に defer): ED/外来 encounter profile
(対称的な `test-encounter --patient-profile` 拡張要)、LLM
semantic diff メカニズム、GitHub Actions CI 統合、臨床レビュー
ループ。

**Consequences:**

Positive:
- β-JP-1 のブロック解除 — テンプレート vs LLM narrative 回帰用の
  決定的 canonical patient
- 新規 profile 追加は documented workflow (regenerate + review +
  commit)
- 決定性は既存 AD-16 discipline 経由で seed 42 に強制

Negative:
- template narrative logic 変更時の追加メンテナンス負担 (全 golden
  再生成要)
- fixture ライブラリが疾患 YAML と分離 (contributor は両方を理解
  する必要)

Neutral:
- 6 profile × ~10-76 文書/profile × N section = ~100-500 KB の
  golden JSON が git に checkin (許容)

**Alternatives considered:**

- **入力 + narrative 期待値を単一 YAML に**: 却下 — LLM 出力は
  semantic diff engine (β-JP-1 scope に defer) なしでは期待部分
  文字列として表現できない
- **入力 + リファレンス golden narrative 埋め込み (YAML 内 base64)**:
  却下 — YAML が profile あたり 100-500 行に膨張、git diff が
  noisy、LLM parallel storage 困難
- **既存 AD-60 `audit run` framework への統合**: 却下 — fixture
  regression は per-profile 決定的 byte-diff で、cohort 統計では
  ない; audit 目的の overload

**Related ADRs:** AD-16 / AD-56 / AD-63 / AD-65

**Related documents:**
- Spec: `docs/history/specs-archive/2026-07-03-tier1-3-alpha-min-2c-fixture-library-design.md`
- Plan: `docs/history/plans-archive/2026-07-03-tier1-3-alpha-min-2c-fixture-library-plan.md`

---

### AD-67 · Severity single source of truth (disease YAML canonical、hybrid c2)

**Date:** 2026-07-06 (session 38、FP-SEV-MODEL)

**Status:** Accepted

**Context:**

3 つの disconnected severity system が共存: (A) locale
`demographics.yaml` の per-disease `severity_beta` 連続 draw
(唯一の live inpatient source、hospitalization gate にも load-bearing)、
(B) disease-YAML `severity.distribution` + `modifiers` (全 30 疾患
に臨床文献引用付きで存在するが code に read されず — dead)、
(C) encounter-YAML `severity_distribution` for ED path。float→
category 境界は hardcode (`inpatient.py`、`> 0.7`/`> 0.3`)、
minimum は 2 箇所定義 (`severity_minimum` float + `minimum_severity`
str、別々に clamp)。System B が dead であるため、authored された
comorbidity-aware severity 分布が FHIR 出力に到達しなかった — これは
FHIR 完全性目標における最大の C1 (silent-drop) instance。

**Decision:**

Disease-YAML `severity.distribution` × `modifiers` を single canonical
severity source とする (hybrid **c2**)。新しい
`clinosim/modules/disease/severity.py` が severity sampling と
canonical category↔score 境界 (`SEVERITY_SCORE_RANGES`、
`category_from_score`) を所有。`sample_severity(protocol, person, rng)`
は distribution × person-derived comorbidity modifier (年齢/併存症)
から category を sample、`minimum_severity` に clamp、category を
uniform 連続 score にマップ; score はまだ population-time
hospitalization gate に feed し同 category を re-derive する。
`population/engine.py` がこれを呼ぶ (新規 population→disease 依存);
`inpatient.py` は `category_from_score` を使用; `emergency.py` は
categorical primitive を共有。locale `severity_beta`/`severity_minimum`
は撤廃 (incidence-only)。import-time `_validate_severity_block` は
malformed distribution / unknown modifier condition / bad minimum /
non-positive multiplier に fail-loud (silent-no-op 防御)。

Modifier condition は 30 YAML から列挙 (66 種)、EVALUABLE
(person-derived、~34: 年齢/併存症/BMI/喫煙) と RESERVED_INTRINSIC
(疾患サブタイプ / シナリオ固有、~32: `anterior_wall_MI`、
`gcs_below_8` 等) に分割、後者は KNOWN (validation は raise しない)
だが本 chain では skip。

**Consequences:**

Positive:
- authored された comorbidity-aware severity 分布が生成を駆動する
  ようになる (例: acute_mi severe rate ~0.11 → older/comorbid MI
  コホートで ~0.5)。
- category↔score 境界と minimum の owner が単一 (duplicate clamp
  なし)。
- silent-no-op 防御が disease-YAML severity block まで拡張。

Negative / neutral:
- 新機能クラス変更: 入院コホート構成 (hospitalization rate /
  severity mix) が disease-YAML 分布に shift; golden 再生成
  (profile golden は forced-severity なので byte-unchanged;
  cohort output は shift)。
- 疾患内在 modifier は defer (scenario-flag メカニズム) — TODO。

**Related ADRs:** AD-16 / AD-55 / AD-57 (scenario flags sibling pattern)

**Related documents:**
- Spec: `docs/history/specs-archive/2026-07-06-severity-single-source-c2-design.md`
- Plan: `docs/history/plans-archive/2026-07-06-severity-single-source-c2.md`
- Registry: `docs/design-notes/2026-07-06-fix-point-registry.md` (FP-SEV-MODEL)

---

### AD-68 · archetype_modifiers 配線 (dead YAML activation、AD-67 sibling)

**Date:** 2026-07-06 (session 38、FP-YAML-2b)

**Status:** Accepted

**Context:**

`archetype_modifiers` (23 疾患 YAML) は load 時に silent drop
(`extra="ignore"`) され read されなかった; `select_archetype` は
代わりに自身の hardcode `immune_reactivity` / `treatment_sensitivity`
ヒューリスティックを適用していた。YAML block は superset (年齢、
併存症、疾患要因を追加) — C1 (silent-drop) instance であり、AD-67
が severity に対処したのと同じ dead-authored-YAML class。

**Decision:**

`archetype_modifiers` を `select_archetype` (owner:
`clinical_course/engine.py`) に配線、hardcode profile modifier を
置換。`_eval_archetype_condition` は各 modifier の condition を評価
— expression form (`<var> <op> <number>` for age / immune_reactivity /
treatment_sensitivity、eval() ではなく strict regex 経由) と named
form (併存症語彙が重複するため `disease.severity._evaluate_condition`
を再利用; 疾患内在 condition は reserved/skip)。
`_apply_archetype_modifiers` は effect delta を単一 `rng.choice`
の前に archetype 確率に追加 (新 rng draw なし)。`DiseaseProtocol` は
`archetype_modifiers` を追加; `_validate_archetype_modifiers` は
load 時に fail-loud (effect が疾患が定義しない archetype を対象と
するとき、condition が unknown のとき、delta が non-numeric のとき —
silent-phantom guard)。

NOTE: `plateau` は正当な per-disease archetype **NAME** (該当疾患の
`course_archetypes` で定義されている)、`plateau_then_recovery` の
typo ではない — validation は fixed canonical set ではなく
per-disease 自己一貫性 (effect key ⊆ 疾患自身の archetype) を強制。

**Consequences:**

Positive: authored per-disease archetype 調整 (年齢/併存症 →
deterioration share) が course selection を駆動; 単一
silent-no-op-guarded path。
Negative/neutral: 新機能クラス変更 (archetype 分布が shift、
golden 再生成; profile golden は forced-archetype なので
byte-unchanged)。疾患内在 condition は defer (AD-67 の reserved set
と共有 scenario-flag メカニズム)。

**Related ADRs:** AD-16 / AD-67 (severity sibling)

**Related documents:**
- Spec: `docs/history/specs-archive/2026-07-06-archetype-modifiers-wiring-design.md`
- Plan: `docs/history/plans-archive/2026-07-06-archetype-modifiers-wiring.md`
- Registry: `docs/design-notes/2026-07-06-fix-point-registry.md` (FP-YAML-2)

---

### AD-69 · DiseaseProtocol extra="forbid" (author-time silent-drop 防御)

**Date:** 2026-07-06 (session 38、FP-YAML-3)

**Status:** Accepted

**Context:** `DiseaseProtocol` は Pydantic の default `extra="ignore"`
を使用していたため、model field と一致しない top-level YAML キーは
load 時に silent drop されていた。これは C1 (silent-drop) 欠陥
全 class の根本原因 — `diagnostic_difficulty` が top-level に
配置 (0.3 に fallback)、`archetype_modifiers` (23 file 未読)、
`severity.distribution` が read されない — であり、新規 typo を
検出不可能にしていた。

**Decision:** 全孤児キーを解決した後 (diagnostic_difficulty を nested
化、archetype_modifiers を wire、4 未読 key —
differential_diagnosis / rehabilitation / precipitants / prerequisite
— を削除)、`DiseaseProtocol` に `model_config = ConfigDict(extra="forbid")`
を有効化し、認識されない top-level キーが load 時に raise するように
する。`EncounterConditionProtocol` は既に `extra="allow"` (raw dict
を返す); `PatientProfile` は既に forbid を使用 — 本変更は disease
protocol をこれに合わせる。vestigial `readmission` model field
(0 YAML、0 reader) も削除。

**Consequences:** master と byte-diff 同一 (削除された key は決して
consume されなかった) — refactor クラス変更。新規 disease-YAML
author は新 top-level key に対して model field を追加する必要あり
(でなければ fail-loud)。

**Dead-field triage (session 39、registry FP-YAML-3 follow-up):**
宣言されているが consume されない 3 field のうち、`reference_ranges`
のみを削除 — live locale 側 lab reference range を duplicate して
いた (locale が single source of truth、AD-30) ため、disease-YAML
copy は純粋な drift。model field + 23×3 YAML block (banner + body、
1184 行) が byte-cleanly に削除 (all-deletion diff; 6 profile
golden は byte-identical)。残り 2 つは **future-wiring seed として
保持、削除しない**、なぜならどちらも authored 臨床 content で
下流計画をドキュメント化しているため: `drug_interactions` (実
interaction pair + 臨床 action) は計画中の FHIR `DetectedIssue`
resource
(`docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`)
の seed、`expected_vital_distributions` は cohort-level 完全性 audit
軸 (FP-COMPLETENESS-GATE) の候補検証対象。これらを削除すると計画中
機能の authored seed が破壊される。1 つの follow-up が残る (registry
FP-YAML-3): `order/engine.py` の raw-dict consumption path が
Pydantic を bypass (forbid でカバーされていない)。

**Related ADRs:** AD-67 / AD-68 (これがブロック解除/強化する severity
+ archetype activation)

**Related documents:**
`docs/design-notes/2026-07-06-fix-point-registry.md` (FP-YAML-3);
`docs/design-guides/data-model-and-completeness-conventions.md` §2


---

### AD-70 · JP-CLINS lab coding: JLAC10 primary + LOINC secondary (国際相互運用性)

**Date:** 2026-07-26 (session 68、migration PR 4)

**Status:** Accepted

**Context:**

JP-CLINS 検体検査 migration (PR #396–#404) は 1,898 CoreLabo
analyte 用の primary coding system として JLAC10 を確立 (session
67 axis 100% completion)。secondary coding system のアーキテクチャ
判断が発生: LOINC を JLAC10 primary と併存する secondary coding
として保持するか、あるいは JP-only 純粋主義のために完全に削除するか?

3 つの option を検討:

- **Option A (JP 純粋主義):** LOINC secondary coding を完全削除、
  JLAC10 primary のみを emit。Rationale: JP-CLINS は JP 固有データ
  交換標準; LOINC は国内 JP context では redundant。exam instance
  あたり ~0.5 KB の FHIR オーバーヘッドを削除。

- **Option B (相互運用性):** dual coding を保持 — JLAC10 primary
  (discriminator + Fixed coding)、LOINC secondary。Rationale:
  下流の国際対応システム (cloud EHR、研究統合、学術医療データ
  パイプライン) が JLAC10 traceability を失わずに LOINC に正規化
  可能; 「任意の JP clinic が必要なら international viewer に
  export 可能」という暗黙の contract をサポート。

- **Option C (branching):** country-flag ベース dispatch —
  `_fhir_observations.py` が `country == "JP"` を check して JP
  のみ LOINC を省略。Rationale: US 出力を最適に compact に保つ、
  JP に選択を与える。

**Decision:** **Option B** — dual coding を保持 (JLAC10 primary
+ LOINC secondary)。

**Rationale:**

1. **束縛制約:** JP Core `JP_Observation_LabResult.code` は binding
   strength `example` (FHIR 用語: 最弱束縛、「推奨だが必須ではない」)
   で定義されている。これは **single-system coding** (JLAC10 のみ)
   と **multi-system coding** (JLAC10 + LOINC) の両方が spec-compliant
   であることを意味する。

2. **国際相互運用性:** LOINC は事実上の global lab code standard。
   dual coding により下流システム (research DB、cloud EHR
   プラットフォーム、国際医療ネットワーク) がカスタムマッピング
   コードなしで clinosim export を受け入れ可能。LOINC を削除すると、
   それらのシステムが JLAC10→LOINC マッピングテーブルを外部で保守
   することを強制し、統合摩擦を増加させる。

3. **メタデータコストは許容範囲:** 各 lab Observation は ~30–50
   バイト (LOINC coding[] slice + system + code + display) を追加。
   p=100 JP データセットで ~90–150 KB 累積 — マルチ GB export
   footprint 内では無視可能。`example` binding level は追加 coding
   にペナルティを課さない。

4. **traceability と可逆性:** LOINC を保持することでデータ損失なし
   の完全 round-trip マッピング (JLAC10↔LOINC) が可能。削除すると
   後の use case で reverse-mapping が必要になった場合の下流可能性
   を閉ざす。

5. **FA-1 原則 (AD-56) との整合:** アダプタ (FHIR builder) は
   single-responsibility (CIF が提供するものを emit); CIF は
   language-neutral にコードを保存 (AD-30)。dual-coding 選択は
   データモデル選択ではなく **FHIR presentation 選択** — データと
   アダプタの分離と完全に整合。

**Consequences:**

Positive:
- 下流システムがカスタムマッピングなしで clinosim export を統合可能。
- JP と US 出力が 100% 同一のまま (保守すべき branching ロジック
  なし)。
- 将来の JP-CLINS プロファイル進化 (binding が `required` に強化
  される場合) と forward-compatible。

Negative/neutral:
- 僅かな FHIR サイズ増加 (per-dataset NDJSON の ~0.2–0.5%)。
- LOINC code coverage のオーサリング負担 (既に完了; PR #396 で全
  20 CoreLabo analyte が `codes/data/loinc.yaml` に LOINC code を
  持つことを保証済)。

Alternative deferred:
- JP-CLINS 2.1 / JP FHIR プロファイルが binding を `required` に
  制限 + 非 JLAC10 coding を明示的に禁止する場合、この ADR を
  再訪し option A/C を再評価 (LOINC secondary 削除の別 migration
  chain 付き)。それまでは `example` binding が支配的制約。

**Related ADRs:** AD-30 (CIF language-neutral) / AD-31 (Bulk Data
準拠) / AD-56 (adapter 単一責任) / AD-58 (output adapter 登録
パターン)

**Related documents:**
- Migration PR: #396 (dispatcher refactor) / #398 (shared pkg
  loader) / #400 (analyte classifier) / #402 (CoreLabo emit) /
  #404 (Uncoded + LocalCode + sanitize)
- Session note: `project_session_67_end_state.md` (axis completion、
  decision B 採用)
