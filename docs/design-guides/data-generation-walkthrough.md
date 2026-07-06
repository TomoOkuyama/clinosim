# Data Generation Walkthrough — 「データはどう生まれるか」

**Status:** Active(2026-07-06、session 38 で確立)
**Audience:** clinosim に初めて触れる開発者/実装 AI。**このプロジェクトが 1 件の患者データを
どう組み立てるか**を、実際のファイル名・関数名・データ構造つきで end-to-end に追う。
**読む順:** `README.md`(索引)→ `project-concept-and-design.md`(コンセプト)→ **本書**
→ `implementation-rules.md`(不変則)。詳細な HOW-TO は `../CONTRIBUTING-modules.md`。

> ひとことで言うと: **人口を作り → その人口から病院受診イベントを発火させ → 受診ごとに生理・
> 検査・処置・文書を日次シミュレーションして中間表現 CIF に書き → CIF から FHIR を組む。**
> 乱数は全て seed 由来で決定的(同 seed = 同一出力)。

---

## 0. 3 段 CLI = 3 つの成果物

データ生成は 3 つの独立した CLI ステージに分かれる(AD-37)。各ステージは前段の成果物だけを読む。

```
clinosim generate      →  CIF(構造化)      cif/structural/patients/<enc>.json
        ↓                                    + cif/hospital.json / metadata.json
clinosim narrate       →  CIF(ナラティブ)  cif/narratives/<version>/documents/<enc>/<doc>.json
        ↓
clinosim export-fhir   →  FHIR R4 NDJSON     fhir_r4/<ResourceType>.ndjson + manifest.json
```

- **なぜ 3 段か**: ナラティブ(問診・経過記録の自然文)を **後から差し替え可能**にするため。
  最初は template でナラティブを作り、後で `narrate --provider bedrock` で LLM 再生成 →
  `export-fhir --narrative-version <id>` で FHIR を作り直す、が独立に回る(コンセプト要求 6)。
- **CIF がシミュレーションの唯一の出力**(AD-17)。FHIR/CSV adapter は CIF だけを読み、
  シミュレーション内部には触れない。
- 他の subcommand: `test-disease <id>`(1 疾患を単体生成してデバッグ表示)/ `test-encounter`
  / `audit run`(4 軸検証)/ `validate` / `regenerate-goldens` / `check-narratives` /
  `list-diseases`。

---

## 1. Stage 1 = `generate`:人口 → イベント → 受診シミュレーション → CIF

エントリは `clinosim/simulator/engine.py:run_beta()`。以下の順に進む。

### 1a. 人口生成(Layer 1)— `modules/population`

`generate_population(size, country, rng)`(`population/engine.py`)が **医療圏の住民集団**を
世帯単位で作る。各 `PersonRecord`(`types/population.py`)は軽量:年齢・性別・住所・
**慢性疾患(ICD コードのリスト)**・BMI・喫煙/飲酒・受診閾値など。疫学データ(年齢分布・
慢性疾患有病率・疾患発生率)は全て `locale/<country>/demographics.yaml` から読む(コードに疫学値を
ハードコードしない)。

### 1b. ライフイベント発火 — `generate_monthly_events`

`run_beta` は `time_range`(既定 1 年)を **年 × 月ループ**で回し、各月
`generate_monthly_events(registry, year, month, rng, country)` を呼ぶ。住民ごとに疾患 incidence
(発生率 × 年齢 × 季節性 × 生活習慣リスク)を評価し、`rng.random() < rate` で疾患発症を判定。
発症したら:

- **重症度**を `disease.severity.sample_severity(load_disease_protocol(disease_id), person, rng)`
  で決定(AD-67)。疾患 YAML の `severity.distribution × modifiers`(年齢・併存症で補正)から
  カテゴリを引き、連続 score も返す。← **重症度の唯一の source は疾患 YAML**(旧 `severity_beta` は撤廃)。
- **入院要否**を連続 score と受診閾値で判定(`severity > care_seeking_threshold`)。
- `LifeEvent`(person_id / disease_id / timestamp / severity / requires_hospital)を生成。

「患者は population から生まれる」— どの患者も最初は住民で、イベントが閾値を超えて初めて
hospital encounter に変換される。これにより疫学が人口レベルで正しくスケールする。

### 1c. 患者の hydrate — `modules/patient`

入院/受診が確定した住民は `activate_patient(person, rng, demo)`(`patient/activator.py`)で
Layer 1 → Layer 2 `PatientProfile` に厚くなる:身長/体重、**慢性疾患の staging**
(`_generate_stage`:CKD G3a / NYHA II / 高血圧 Stage 2 …)、**ステージ由来の生理パラメータ**
(`STAGE_SEVERITY` が stage → severity_score、それが baseline vitals や physiology を駆動 —
例:高血圧 Stage 2 → 高い baseline 血圧、FP-I10)、常用薬、アレルギー、baseline vitals。

### 1d. 受診シミュレーション(daily loop)— `simulator/inpatient.py` ほか

受診タイプ別に分岐:
- **入院**: `inpatient.py:_simulate_patient()` → `_run_daily_loop()`。
- **ED**: `emergency.py`。**外来**: `outpatient.py`。

入院の 1 日ループがデータの中心。おおまかに:

1. **重症度 → コース選択**: `event.severity`(連続 score)を `category_from_score` で
   mild/moderate/severe に。`select_archetype(severity, profile, rng, protocol_archetypes=…,
   protocol_modifiers=…, patient=…)`(`clinical_course/engine.py`)が疾患 YAML の
   `course_archetypes`(6 正準アーキタイプの確率 + 患者リスク因子 `archetype_modifiers` 補正、
   AD-68)から **その患者の経過アーキタイプ**を 1 つ引く(smooth_recovery / dip_then_recovery /
   … / sudden_deterioration)。
2. **初期生理状態**: `apply_disease_onset(state, severity, protocol.initial_state_impact, …)` で
   疾患の onset を physiology 状態(inflammation_level / volume_status / perfusion_status /
   renal_function / cardiac_function …)に反映。
3. **日次で状態を進める**: `get_daily_directive(archetype, day, …)` がアーキタイプの
   `trajectory`(状態変数ごとの日次デルタ)を補間して状態を更新。
4. **合併症**: `evaluate_complications(day, state, patient, protocol.complications, …, severity=…)`
   が疾患 YAML の `complications`(発生率・リスク因子・state_impact・actions)を評価。
   `actions: ["icu_transfer"]` を含む合併症が発火すると ICU 転送。
5. **オーダ/検査/バイタル/投薬**: physiology 状態から `derive_lab_values`(30+ analyte)で検査値、
   vitals、`place_admission_orders` / `place_daily_lab_orders`(panel-aware)/ 画像
   (`place_imaging_orders`)/ MAR を生成。
6. **退院/死亡**: LOS(疾患 YAML `target_los`)と `outcome_benchmarks`(死亡率)で決定。
   `--end`(snapshot)以降は in-progress 扱い(AD-32)。

結果は 1 患者 = 1 `CIFPatientRecord`。**scenario / severity / course / complications / labs は
すべて疾患 YAML 駆動**で、engine コードに臨床値をハードコードしない。

### 1e. Enricher(モジュール拡張)— `simulator/enrichers.py`

Base の受診シミュレーションの前後に、**opt-in / always-on モジュール**が 3 ステージで走る:

- **POST_POPULATION**(人口生成後・シミュレーション前): 例 identity(JP マイナンバー/保険)。
- **POST_ENCOUNTER**(1 受診の daily loop 完了直後、encounter simulator の内側): 臨床カスケード。
  順序固定 `device(70) → hai(80) → antibiotic(85) → imaging(90) → triage(93) →
  nursing_assignment(94) → document(95)`。前段の `extensions[X]` を読んで次段が動く
  (device なしに HAI なし等)。
- **POST_RECORDS**(全患者シミュレーション後): cross-record。nursing flowsheet / immunization /
  family_history / code_status / care_level。

モジュールは `CIFPatientRecord.extensions[<module>]` にだけ書く(コア型への typed field 追加は
Base のみ)。新モジュール追加 = enricher を registry 登録するだけ(dispatch 本体は編集しない、AD-56)。

### 1f. CIF 書き出し

各患者の構造化データを `cif/structural/patients/<encounter_id>.json` に immutable で書く。
この時点で `document` モジュールは `ClinicalDocument` の **stub のみ**(metadata + author +
encounter binding、`narrative=None`)を作る。実際の自然文は Stage 2 で入る(AD-65)。

---

## 2. Stage 2 = `narrate`:ナラティブ生成(差し替え可能層)

`narrate --provider template|mock|ollama|bedrock --version-id <id>` が
`cif/narratives/<version>/documents/<enc>/<doc>.json` を書く。

- `NarrativePass`(`document/narrative/passes.py`、ABC)が structural CIF を読み、患者 profile /
  labs / conditions / medications / scenario spine を入力に narrative を導出。
- **walk 順序 = (doc_type, language) group 単位**で、同 prompt prefix を共有する batch を逐次処理
  → LLM prompt cache hit 率最大化(変更禁止)。
- template と LLM で **同一 base class**。LLM 経路は `LLMService.complete_prompt()` が唯一の
  LLM 呼び出し口(AD-11)、prompt は `llm_service/prompts/{en,ja}/*.yaml`。
- version 化されるので、後で別バージョンを作って FHIR を作り直せる。

---

## 3. Stage 3 = `export-fhir`:CIF → FHIR R4

`export-fhir --narrative-version <id>` が `CIFReader` で structural + narrative を merge し、
`_fhir_*` builder 群(`modules/output/`)が FHIR resource を組む。

- **Bulk Data Access**(AD-31): resource type ごとに 1 NDJSON + `manifest.json`。Bundle でラップしない。
- builder は **CIF を読むだけ**。display は `code_lookup(system, code, lang)`、URI は
  `get_system_uri`、国→コード体系は `system_key_for` で解決(ハードコード禁止)。
- FHIR resource を足す = `register_bundle_builder` で builder を登録(AD-56、dispatch は編集しない)。
- 出力形式を足す = `register_output_adapter`(CSV が実例)。

現在 25+ resource type(Patient / Encounter / Condition / Observation / MedicationRequest /
MedicationAdministration / Procedure / DiagnosticReport / ServiceRequest / ImagingStudy /
DocumentReference / Composition / ClinicalImpression / CareTeam / AllergyIntolerance /
Immunization / FamilyMemberHistory / Coverage / Device / Specimen / Organization / Location /
Practitioner / PractitionerRole / Endpoint …)。

---

## 4. 1 人の入院患者を追う(具体トレース)

```
run_beta(config)                                   # simulator/engine.py
 └ generate_population(40000, "US", rng)            # 医療圏 40k 人
     → PersonRecord(age=78, chronic=["I10","N18"])  # 高血圧+CKD の 78 歳
 └ generate_monthly_events(...) 各月                 # population/engine.py
     → incidence 評価 → acute_mi 発症
     → sample_severity(acute_mi protocol, person)   # 疾患YAML分布×modifiers(高齢→severe寄り)
        = ("severe", 0.82)
     → requires_hospital = 0.82 > threshold = True
     → LifeEvent(acute_mi, severe, requires_hospital)
 └ activate_patient(person)                          # patient/activator.py
     → PatientProfile(stage: "CKD G3a"/"HT Stage 2", baseline BP ↑ by stage)
 └ _simulate_patient(event)                          # inpatient.py
     → category_from_score(0.82) = "severe"
     → select_archetype("severe", …, acute_mi.course_archetypes, .archetype_modifiers)
        = "dip_then_recovery"
     → apply_disease_onset(state, "severe", acute_mi.initial_state_impact)
     └ _run_daily_loop(...)  各日                     # 日次で状態→検査/vitals/orders/MAR
         → derive_lab_values(...)  troponin↑ CK-MB↑ Cr↑(CKD baseline)
         → evaluate_complications(...)  # acute_mi.complications
         → POST_ENCOUNTER enrichers: device→hai→antibiotic→imaging→triage→nursing→document
     → CIFPatientRecord(orders, labs, vitals, mar, documents(stub), extensions{...})
 └ cif/structural/patients/ENC-....json 書き出し
--- narrate ---
 └ TemplateNarrativePass  → cif/narratives/template/documents/ENC-.../hp.json (H&P 本文)
--- export-fhir ---
 └ _fhir_conditions → Condition(acute_mi I21, stage "CKD G3a" …)
    _fhir_observations → Observation(troponin, Cr, …)
    _fhir_medications → MedicationRequest/Administration
    … → fhir_r4/*.ndjson
```

---

## 5. データを増やす/直すときの入口

| やりたいこと | どこを触るか |
|---|---|
| 新しい疾患 | `modules/disease/reference_data/<id>.yaml` を追加(既存疾患を雛形に)+ 発生率を locale に + 診断コードを `codes/data/` に登録。engine コード変更不要。`CONTRIBUTING-modules.md` |
| 新しい ED/外来条件 | `modules/encounter/reference_data/<id>.yaml` |
| 新しい検査値 analyte | `derive_lab_values`(observation)+ code_mapping + `codes/data/loinc.yaml` |
| 新しい FHIR resource | `_fhir_<topic>.py` builder + `register_bundle_builder`(§3) |
| 新しい出力形式 | `OutputAdapter` + `register_output_adapter` |
| 新しいデータ種(モジュール) | `modules/<name>/` + enricher 登録(§1e)+ `extensions[<name>]` に書く |
| コード → 表示名 | `codes/data/<system>.yaml`(EN 必須、JA 任意)。`code_lookup` で解決 |

**必ず守る不変則**(詳細 `implementation-rules.md`):決定性(全乱数 seed 由来)/ CIF は code のみ
(display は出力時解決)/ 疾患 YAML の未知キーは `extra="forbid"` で load 時 raise / 重症度・
course・complications は疾患 YAML 駆動 / silent-no-op 防御(canonical constants + `_validate_*` +
completeness 不変則 test)。

---

## 6. なぜこの形か(設計の背骨)

- **population-driven**: 疫学を人口レベルで正しくスケールさせ、再入院や外来フォローを同一 person_id で
  追跡するため。
- **YAML 駆動**: 臨床値を Python に埋めず、疾患/検査/locale/コードを YAML 定義にすることで、
  「モジュール/疾患を足すだけ」で新データを生成できる(コンセプト要求 4・8)。
- **CIF 2 層 + 3 段 CLI**: ナラティブ品質を後から独立に上げられる(template → LLM)ため(要求 5・6)。
- **決定性**: 同 seed = byte 同一。refactor の byte-diff 検証と regression golden が成立する。
- **silent-no-op 防御**: 「動いているように見えて実は発火していない」バグ(PR-90/J5/C-1)が
  このプロジェクト最大の敵。canonical constants・fail-loud validation・発火 counter・completeness
  不変則 test の多層で防ぐ(`implementation-rules.md` §9)。
</content>
