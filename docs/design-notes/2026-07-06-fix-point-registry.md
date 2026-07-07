# Fix-Point Registry — FHIR Completeness & Data-Model Unification

**Status:** Active(session 38 開設)
**役割:** TODO.md とは**別**の、複数セッションで消化する修正ポイント台帳。各セッションは着手した
FP の **Status 列を更新**(OPEN → IN-PROGRESS → DONE)し、DONE 時に PR/commit を追記する。
**背景・考察:** [`2026-07-06-fhir-completeness-and-data-model-unification.md`](2026-07-06-fhir-completeness-and-data-model-unification.md)
**遵守規約:** [`../design-guides/data-model-and-completeness-conventions.md`](../design-guides/data-model-and-completeness-conventions.md)

> TODO.md との使い分け: TODO.md は「機能ロードマップ + β/γ/δ/ε phase の deferred backlog」。
> 本 registry は「**既存データモデルの不完全状態(C1/C2/C3)を塞ぐ**構造修正」専用。両者は独立に進む。

---

## Status サマリ

| FP | 見出し | クラス | 優先 | 依存 | Status |
|---|---|---|---|---|---|
| FP-UNIFY-1 | `_fhir_hai.py` system_key_for バイパス(潜在バグ) | — | 高 | なし | **DONE**(89e616a43f) |
| FP-YAML-1 | `diagnostic_difficulty` top-level silent-drop(実害バグ) | C1 | 高 | なし | **DONE**(7910813fe6) |
| FP-SEV-MODEL | 重症度 single-source-of-truth 再設計 | C1 | 高 | brainstorming | **DONE**(c2, AD-67) |
| FP-YAML-2 | 孤児キー triage(配線 or 削除) | C1 | 中 | FP-SEV-MODEL(archetype_modifiers 分) | **DONE**(archetype_modifiers 配線 AD-68 / 4 孤児キー削除)|
| FP-YAML-3 | `DiseaseProtocol` に `extra="forbid"` + 生 dict 経路封鎖 | C1 | 中 | FP-YAML-1/2 | **DONE**(extra="forbid"、残: 生 dict 経路 + 死蔵 field 3 件)|
| FP-I10 | 高血圧生理モデル新設 + stage 一貫配線 | C2 | 中 | FP-SEV-MODEL 推奨 | **DONE**(stage→BP baseline 消費)/ 残: FHIR stage SNOMED コード |
| FP-ARCH-1 | course_archetypes 高優先(HF / subdural) | C3 | 中 | なし | **DONE**(session 38、下記詳細参照)|
| FP-DELTA-VALIDATE | `initial_state_impact` / `complications[].state_impact` / `course_archetypes[].trajectory` state-var silent-drop の author-time gate | C1 | 高 | FP-CLAMP-RANGE | **DONE**(session 40)|
| FP-ARCH-2/3 | course_archetypes + complications 残 7 trauma 疾患 | C3 | 中〜低 | なし | **DONE**(全32疾患 course_archetypes 完備) |
| FP-AGE | person.age as-of 化(2 フェーズ) | ~~C2~~ **非FHIR** | 低 | なし | OPEN(再分類、下記) |
| FP-UNIFY-2 | 日付→ISO ヘルパ共通化 | — | 中 | なし | DONE |
| FP-UNIFY-3 | FHIR 固定 ja ラベル辞書統合 + idiom 統一 | — | 低 | なし | **DONE**(session 40)|
| FP-UNIFY-4 | case-sensitive `country == "US"` 比較の一掃(lowercase バグ class) | — | 中 | なし | **DONE**(session 39、output 7 + identity/patient 2 sibling)|
| FP-CLAMP-RANGE | 状態変数 clamp が canonical `_variable_range` をバイパス(inpatient 手術/合併症) | C2 | 中 | なし | **DONE**(session 39、`apply_state_delta` 単一化)|
| FP-COMPLETENESS-GATE | C1/C2/C3 を検証する audit completeness 軸 | — | 高(capstone) | 上流 FP 完了後 | **DONE**(不変則 test suite)/ cohort 統計 audit 軸は残 |
| FP-FH-CODE-RESOLUTION | `FamilyMemberHistory` の I64 / E11 表示 fallback + Z-code 誤 map | C1+C2 | 中 | なし | **DONE**(session 40)|

---

## FP-UNIFY-1 — `_fhir_hai.py` の code system バイパス(潜在バグ)【高・低リスク】

- **現状**: `clinosim/modules/output/_fhir_hai.py:44` が
  `icd_sys_key = "icd-10-cm" if country == "US" else "icd-10"` と単一真実源をバイパス。
  他の diagnosis builder は全て `system_key_for("diagnosis", country)`(`_fhir_conditions.py:47` 他)。
  `country == "US"`(大文字固定)なので HAI enricher が lowercase `"us"` を渡すと `icd-10`(誤り)に落ちる。
- **修正**: `system_key_for("diagnosis", country)` に置換。
- **検証**: HAI cohort で ICD system URI が US=icd-10-cm / JP=icd-10 になることを grep。byte-diff は
  現行 country 値が大文字なら保存されるはず(確認すること)。
- **Status:** DONE(session 38、commit 89e616a43f)。lowercase "us"/"jp" 双方の unit test 追加
  (`tests/unit/output/test_fhir_hai_code_system.py`)。残る sibling 比較は FP-UNIFY-4 に分離。

## FP-YAML-1 — `diagnostic_difficulty` top-level silent-drop(実害バグ)【高】

- **現状**: 読み取りは `inpatient.py:608` が `protocol.diagnostic.get("diagnostic_difficulty", 0.3)` と
  **ネスト**。しかし **15 疾患が top-level に配置** → R-A で silent-drop → 意図値(acute_mi 0.25 /
  sepsis 0.5 等)が **0.3 に化ける**。17 疾患はネスト配置で正常、5 疾患はどちらにも無く 0.3。
- **修正**: top-level 配置の 15 疾患で `diagnostic_difficulty` を `diagnostic:` 配下へ移動
  (両方に在る移行途中ファイルは top-level を削除)。読み取り側は変更不要(既にネスト読み)。
- **検証**: 各疾患の実効 diagnostic_difficulty を dump し、YAML 記載値と一致することを確認。
  golden は該当疾患のみ差分(diagnostic 難易度が working diagnosis 生成に効く)。AD-66 で再生成。
- **注意**: FP-YAML-3(`extra="forbid"`)を先に入れると 15 疾患が load 不能になるので、**FP-YAML-1
  → FP-YAML-2 → FP-YAML-3 の順序厳守**。
- **Status:** DONE(session 38、commit 7910813fe6)。実測分類 = top-only 10(うち値≠0.3 が 8:
  acute_mi 0.25 / sepsis 0.5 / pulmonary_embolism 0.45 / gi_bleeding 0.35 / DKA・pancreatitis・
  cholecystitis 0.2 / appendicitis 0.25、cerebral_infarction・ileus は 0.3 で値不変)+ both 5(冗長
  top-level 削除)。sepsis golden のみ RNG 経路変化で再生成(AD-66 妥当性確認済)。top-level キー残存ゼロ
  = FP-YAML-3 の diagnostic_difficulty 分の障害は解消。他の孤児キー(FP-YAML-2)が残る。

## FP-SEV-MODEL — 重症度 single-source-of-truth 再設計【高・brainstorming 必須】

- **現状(3 系統併存)**: A=locale `severity_beta`(入院、`population/engine.py:362-366`)、
  B=疾患 YAML `severity.distribution`/`modifiers`(**死蔵**)、C=encounter `severity_distribution`
  (ED、`emergency.py:76-83`)。橋渡し `inpatient.py:117` に 0.3/0.7 ハードコード閾値、下限が
  `severity_minimum`(float)と `minimum_severity`(str)の二重定義。同型死蔵 =
  `incidence.risk_multipliers`(疾患 YAML)vs `disease_risk_multipliers`(locale 手作業重複)。
- **決定事項(brainstorming で確定)**:
  1. canonical をどこにするか(考察 §3.1 推奨 = 疾患 YAML を重症度分布の source、locale は発生率専任)。
  2. float↔カテゴリ表現の統一と境界の所在。
  3. 下限定義の一元化。
  4. 入院/ED 重症度系統の統一 or 分離維持。
  5. `severity_from_protocol(protocol, draw)` 兄弟ヘルパ(`scenario_flags_from_protocol` パターン)の新設。
- **成果物**: `docs/superpowers/specs/` に design spec。実装は挙動変更 = golden 全再生成 + AD 追記。
- **依存先**: FP-YAML-2(archetype_modifiers)/ FP-I10 がこの決定に乗る。
- **Status:** DONE(session 38、c2、AD-67)。`clinosim/modules/disease/severity.py` 新設
  (`sample_severity` / `sample_severity_category` / `category_from_score` /
  `_validate_severity_block`)、population→disease 配線、inpatient/emergency 統一、locale
  `severity_beta`/`severity_minimum` 撤廃(dangling reader 0 確認)。modifier 66 種を
  EVALUABLE(person 由来 ~34)/ RESERVED_INTRINSIC(疾患内在 ~32)に分割。profile golden は
  forced-severity で byte 不変、cohort は疾患YAML分布へシフト(acute_mi severe ~0.11→~0.5)。
  spec/plan: `docs/superpowers/{specs,plans}/2026-07-06-severity-single-source-c2*`。
  **残 follow-up**: 疾患内在 modifier の scenario-flag 評価機構(下記 §deferred)。

## FP-YAML-2 — 孤児キー triage(配線 or 削除)【中】

キーごとに「配線 or 削除」を確定(考察 §3.2)。**削除する場合も、著者意図が臨床文献引用を
含むなら commit message / DESIGN.md に記録してから消す**(意図の消失防止)。

| キー | 出現 | 判定候補 | 備考 |
|---|---|---|---|
| `archetype_modifiers` | 23 | **DONE = 配線**(AD-68) | `select_archetype` に配線しハードコード modifier を置換。式条件パーサ + severity 語彙再利用 + 自己整合検証。`plateau` は typo でなく疾患固有 archetype 名と判明(recon 修正)。疾患内在条件 ~22 は RESERVED（scenario-flag 機構待ち、AD-67 と共通 follow-up）|
| `incidence.risk_multipliers` | 複数 | 配線 or 削除 | locale `disease_risk_multipliers` の手作業重複を疾患 YAML から導出に切替 or 削除。`F10` は両 locale で永久 dead(chronic_prevalence に無い) |
| `differential_diagnosis`(top) | 5 | 削除 | live な `diagnostic.differential` の drift 重複 |
| `rehabilitation` | 8 | 削除 or 配線 | 未配線。`rehabilitation_plan` 文書とは無関係 |
| `precipitants` / `prerequisite` | 各1 | 削除 | 未配線(prerequisite は別キー `prerequisite_condition` が live) |
| `expected_vital_distributions` / `reference_ranges` / `drug_interactions` | 各23 | **triage 済(session 39)**: reference_ranges=削除(locale 重複)、他2=将来配線 seed として保持 | drug_interactions→DetectedIssue seed、expected_vital_distributions→completeness audit target |
| `readmission`(model field) | 0 | 削除 | YAML 投入ゼロ + 消費ゼロの二重死蔵 |

- **Status:** OPEN

## FP-YAML-3 — `DiseaseProtocol` に `extra="forbid"` + 生 dict 経路封鎖【中】

- **現状**: `DiseaseProtocol`(`protocol.py:107`)は `extra` 未定義 = ignore。`PatientProfile`
  (`config.py:101`)は既に forbid = 前例。
- **修正**: FP-YAML-1/2 完了後に `model_config = ConfigDict(extra="forbid")` 追加。加えて
  `order/engine.py` の生 dict `.get()` 経路(`:255,260,273,432`)は owner module accessor 経由に寄せ、
  両消費経路で未知キーを fail-loud に。
- **検証**: 全 32 疾患 YAML が load 成功 + 意図的に未知キーを足すと ImportError。
- **Status:** DONE(session 38、`extra="forbid"` 導入 + 死蔵 `readmission` field 除去 +
  byte-diff 一致確認)。**残 follow-up 2 件**(別 chain 化):
  (1) 生 dict 経路(`order/engine.py` の `.get()`)は Pydantic を通らず forbid の保護外 —
  owner accessor 経由化 or 別途 validation が要る。
  (2) 死蔵モデル field 3 件 triage 済(session 39、user 判断)= **`reference_ranges` のみ除去**
  (locale-side live の重複 = 真の drift、model field + 23 block/1184 行を byte-clean 削除、
  profile golden byte 不変)。`drug_interactions`(FHIR `DetectedIssue` の計画済み seed、
  master-plan)+ `expected_vital_distributions`(cohort completeness audit 軸の検証 target 候補)
  は **将来配線 seed として保持**(authored 臨床 content の損失回避)。DESIGN.md AD-69 節に記録。

## FP-I10 — 高血圧生理モデル新設 + stage 一貫配線【中】

- **現状(C2)**: `activator.py:70-71` が I10 stage("Stage 1/2")生成、`_fhir_conditions.py:191-202`
  が `Condition.stage` テキスト出力。しかし `STAGE_SEVERITY`(`activator.py:37-44`)に I10 が無く、
  `physiology/engine.py:initialize_state` に I10 分岐が無く、vitals bump(`activator.py:262-263`)は
  stage 非依存フラット。**stage は完全 no-op**。Condition.stage の SNOMED type は
  "Tumor stage finding" 385356007 の誤流用。
- **修正(CKD/HF session 37 パターン踏襲)**: (1) `STAGE_SEVERITY` に I10、(2)
  `physiology/engine.py:initialize_state` に I10 分岐 = 血圧状態軸(**本質的欠落**)、(3) vitals bump
  を severity_score 連動化、(4) Condition.stage の SNOMED type を高血圧適切コードへ、(5) 任意で
  降圧薬 stage 段階化。**単独の STAGE_SEVERITY 追加は禁止**(誰も読まない値になる)。
- **依存**: AD-16 決定論 — RNG 消費本数を変えない in-place 再解釈パターン厳守。FP-SEV-MODEL と整合推奨。
- **Status:** DONE(session 38)。`STAGE_SEVERITY["I10"]={"Stage 1":0.30,"Stage 2":0.60}` +
  activator の vitals bump を severity_score 連動(flat +10/+5 → stage 連動 systolic +14/+20)。
  generic uniform は据え置き(値のみ substitute)= RNG 不変・非I10患者不変・golden byte 不変
  (6 profile に I10 併存なし)。unit で stage-graded BP を実証。US audit 0 FAIL。
  **残 follow-up(別 chain、broader bug)**: FHIR `Condition.stage.type` の SNOMED コード
  385356007 "Tumor stage finding" は **全 6 staged 疾患(N18/I50/J44/J45/I25/I10)で誤流用** =
  非がん stage に tumor-staging コード。staging system ごとの authoritative SNOMED 検証 or
  optional `.type` 省略が必要(`_fhir_conditions.py:197`)。I10 単独でなく横断修正。

## FP-ARCH-1/2/3 — course_archetypes + complications authoring【中〜低】

9 疾患欠如(全て `complications:` も欠如)。fallback は炎症性内科向けで外傷に不整合(考察 §3.3)。

- **FP-ARCH-1(高)**: `heart_failure_exacerbation`(利尿反応/難治化 course、再入院 0.22)
  = **DONE**(session 38: 6 diuresis-driven archetypes[volume_status↓/cardiac_function↑]
  + cardiorenal AKI/afib-RVR/cardiogenic shock/respiratory failure complications。audit 0 FAIL、
  golden byte 不変[HF は profile 疾患でない])。`subdural_hematoma`(再出血/神経悪化、死亡 0.15)
  = **DONE**(session 38: 6 post-evacuation archetypes[perfusion/inflammation/anemia 回復、再出血=
  sudden_deterioration]+ recurrent_hematoma/postoperative_delirium/seizure/cerebral_herniation/VTE
  complications。risk condition は `_evaluate_risk_condition` 対応分に限定[silent-no-op 回避]。
  lift-firing 実証 500 severe×10d 全5発火。US+JP audit 0 FAIL、golden byte 不変)。**FP-ARCH-1 完了**。
  **follow-up**: HF `initial_state_impact` の `sodium_status` は認識 state var 10 種に無く silent-drop
  (別 latent issue)+ HF/subdural `daily_trajectory` narrative 未 author(generic fallback)。
- **FP-ARCH-2(中)**: `industrial_burn_severe` / `traffic_accident_severe` / `fall_from_height`。
  **course_archetypes より先に/併せて `complications:`**(ICU 転送・DVT・せん妄・SSI)。
- **FP-ARCH-3(低)**: `hip_fracture`(せん妄/DVT は complications 主体)/ `crush_injury_hand` /
  `electrical_injury` / `wrist_fracture_surgical`(良性定型、実害小)。
- **スキーマ**: `bacterial_pneumonia.yaml:581-655` がテンプレート。正準 archetype 6 種(engine.py:22-60)。
  消費キー = `probability` / `trajectory.<state_var>`(認識 10 種)/ `order_modifications.day_N` /
  `treatment_modifications.day_N` / `daily_trajectory.day_N`。
- **Status:** DONE(session 38 で全完了)。**FP-ARCH-1**(HF + subdural)+ **FP-ARCH-2/3**(残 7 trauma:
  hip_fracture / fall_from_height / traffic_accident_severe / industrial_burn_severe /
  crush_injury_hand / electrical_injury / wrist_fracture_surgical)を authoring、**全 32 疾患が
  course_archetypes + complications 完備**。trauma 7 は 7-way 並列 subagent authoring + 中央テスト
  (`test_trauma_course_archetypes.py`: 正準6/認識 state var/対応 risk condition のガード)で検証、
  lift-firing 実証(burn 4/4・hip 5/5)。risk_factor condition は `_evaluate_risk_condition` 対応分
  (severity_severe / age_over_N / perfusion_status<X / delirium_susceptibility>X / immobility_days>N)
  に限定 = silent-no-op 回避。completeness gate の backlog allowlist を空に更新(gate が drift を検出)。
  **残 follow-up**: `daily_trajectory`(SOAP narrative)は全 9 疾患で未 author(generic fallback)。

## FP-AGE — person.age as-of 化(2 フェーズ)【中】

- **現状(C2)**: `population/engine.py:141` が `dob = date(base_year - age, ...)`、base_year=2024 固定。
  `run_beta`(`engine.py:113`)が base_year を渡さない。`activate_patient` が固定 age をキャッシュ
  (`activator.py:151`)。唯一 `immunization/engine.py:36-39 _age_on` が as-of 計算(**参照実装**)。
  FHIR Patient は birthDate のみ(矛盾は表面化せず)だが CSV(`csv_adapter.py:68`)/ narrative
  (`fact_extractor.py:20`)/ LLM(`llm_service/engine.py:*`)が固定 age を出力 = 複数年で矛盾年齢。
- **修正**: `_age_on` を `_shared` へ昇格。
  - **Phase A(低リスク・seed 経路不変)**: 出力/narrative/LLM/labs を event 日基準に。golden は
    age 表示値のみ差分。
  - **Phase B(要 AD・golden 全再生成)**: incidence 判定(`population/engine.py:449,597,627,640`)を
    as-of 化。40 歳到達で健診/癌検診が発火するなど臨床的に正しくなるが rng 系列が変わる。
  - identity / 世帯 / 身長 shrinkage は as-of 不要。
- **★ 再分類(2026-07-06、session 38 末)**: FP-AGE は **FHIR 要素の completeness ゴールには
  該当しない**。FHIR Patient は `birthDate` のみ emit(`_fhir_patient.py:195`)、**age を emit する
  FHIR builder はゼロ**(grep 確認)。よって FHIR 要素は完全・正しい(consumer は birthDate + 受診日で
  age 算出可)。固定 age が矛盾するのは **CSV `age` 列 / narrative / LLM テキスト**(= 非FHIR)で、
  かつ**複数年シミュレーション(既定の単年運用では非発生)でのみ**。したがって当初ゴール(FHIR 要素
  不完全ゼロ化)の直接対象ではなく、「CSV/narrative データ品質 + 複数年対応」の別カテゴリ。優先度低。
- **Status:** OPEN(完成ゴール外、別カテゴリ扱い)

## Condition.stage.type SNOMED 誤流用 — DONE(FP-I10 follow-up)

- 全 6 staged 疾患(N18/I50/J44/J45/I25/I10)の `Condition.stage.type.coding` が SNOMED
  385356007 "Tumor stage finding"(がん staging コード)を非がん stage に誤流用していた
  (`_fhir_conditions.py`)。**これは実際に FHIR 要素上の誤り = completeness ゴール直結**。
- **修正(session 38)**: 誤 coding を除去、`summary.text`(stage 値)保持 + `type.text="Clinical stage"`
  のみ(コード捏造なし)。cohort 実測: 5717 staged Conditions で tumor コード 0(旧: 全件)。
  golden byte 不変(narrative golden は FHIR Condition を含まない)、unit 8 guards。
- **Status:** DONE(session 38 で誤 coding 除去)。**追加完全化(session 39)**: `stage.summary.coding` に
  per-system の正 SNOMED を付与 — **CKD G1-G5(431855005 / 431856006 / 700378005 / 700379002 /
  431857002 / 433146000)+ NYHA I-IV(420300004 / 421704003 / 420913000 / 422293003)を tx.fhir.org
  `$lookup` で 10 コード全数 authoritative 検証**して `snomed-ct.yaml`(en+ja)へ登録、`_STAGE_SUMMARY_SNOMED`
  マップ経由で emit(JP は ja display)。**GOLD / asthma-severity / hypertension-stage / CCS は verified
  SNOMED 無しのため text-only 維持**(捏造回避)。drift guard `test_every_ckd_nyha_generated_stage_is_mapped`
  で activator の stage 語彙と map の乖離を fail-loud 化(whitelist-drift bug class 対策)。additive
  (FHIR unit 24 + output 272 + FHIR integration 64 green、profile golden 不変)。残: GOLD/CCS 等の
  authoritative code 発見時に順次追加 / `stage.type` の per-system 正コード。

## FP-UNIFY-2 — 日付→ISO 文字列ヘルパ共通化【中・byte 保存】

- `_fhir_imaging_study.py:57 _isoformat_or_str` を `_fhir_common`(or `_shared`)へ昇格し、
  `_fhir_conditions`(7)/ `_fhir_observations`(:236/346/397)/ `_fhir_nursing`(:63/86/142/159)/
  `_fhir_patient:195` / `_fhir_service_request:504` の `[:10]`/`isinstance` インライン重複を置換。
- **Status:** DONE(session 40)。`clinosim/modules/output/_fhir_common.py` に
  `to_fhir_datetime(v)` / `to_fhir_date(v)` 2 helper 新設(FHIR R4 `dateTime` 正規表現準拠、
  空白区切り str も `T` 化)。observations(3)/ care_team(1)/ diagnostic_report(1)/
  immunization(1)/ service_request(2)/ conditions(4)/ patient(1)/ allergy_intolerance(1)/
  clinical_impression(1)= **7 file / 14 emission site** を helper 経由に統一。
  `_fhir_imaging_study._isoformat_or_str` は既に `.isoformat()` のみで文字列 fallback を持たず
  今回 sweep 対象外(byte 保存のため後日別 sweep で置換可)。guard:
  `tests/unit/test_fhir_datetime_helpers.py`(24 test、FHIR R4 dateTime regex compliance
  sweep 含む)。unit 2279 + integration 289 + regression 12 + e2e 37 全 PASS。
  production CIF は既に ISO 保存済で latent trap(空白区切り str→FHIR spec 不適合)防御が主目的。

## FP-UNIFY-3 — FHIR 固定 ja ラベル辞書統合 + idiom 統一【低・byte 保存】

- 「社会歴」2 経路重複(`_fhir_common.py:117` 正道 vs `_fhir_patient.py:288` 直書き)解消。
- 固定 ja ラベル(`_fhir_encounter:187` / `_fhir_diagnostic_report:429` / `_fhir_service_request:317,497`
  / `_fhir_microbiology:139` / `_fhir_facility:29,134` 他)を `_fhir_localization` 辞書へ。
- `lang=="ja"` vs `is_jp(country)` を `resolve_lang`/`is_jp` に統一。`_o` ラッパ 3 箇所
  (`_fhir_observations:33` / `_fhir_service_request:74` / `_fhir_diagnostic_report:56`)を
  `get_attr_or_key as _o` alias import に。`healthcare_system/loader.py:24-27` の country map を
  `is_jp/is_us` 経由に。`device`/`sdoh`/`facility` loader に `_validate_*` 追加。
- **Status:** DONE(session 40)。**主要 sub-item 完了**:
  1. 「社会歴」2 経路重複 → `_fhir_patient._build_occupation_observation` を
     `_fhir_common._social_category(country)` へ delegate、inline 直書き削除。
  2. 固定 ja ラベル → `_fhir_localization._FIXED_LABEL_JA` 辞書 +
     `localize_fixed_label(en_label, country)` helper 新設。4 emission site を helper 経由に
     (`_fhir_diagnostic_report:429` "Radiology" / `_fhir_microbiology:139` "No growth" /
     `_fhir_service_request:317` "Imaging procedure" / `_fhir_service_request:497`
     "Laboratory procedure")。`_build_sr_skeleton` + `_build_panel_sr` に `country` 引数追加
     で `lang=="ja"` idiom 消去。
  3. 残る `lang=="ja"` 参照(`_fhir_care_team:87` の `_CARE_TEAM_CATEGORY_JA/_EN` dispatch +
     `_fhir_diagnostic_report:407-418` の `findings_text_ja` / `impression_text_ja` フィールド
     selector)は data-field 選択(literal label emission ではない)なので intentional にそのまま。
  - **Out-of-scope**(low value、別 backlog): `_o` ラッパ 3 箇所を `get_attr_or_key as _o` alias
    import に統一 / `healthcare_system/loader.py:24-27` country map の `is_jp/is_us` 経由化
    (現状 `.get(country)` の case-sensitivity で fail-loud、silent-no-op ではない)/
    `device`/`sdoh`/`facility` loader の `_validate_*` 追加(現状 offender 0)。
  - 検証: byte-preserving。unit 2312 + integration 289 + regression 12 + e2e 37 全 PASS。

## FP-UNIFY-4 — case-sensitive `country == "US"` 比較の一掃【中・byte 保存】

- **現状(FP-UNIFY-1 実装中に発見)**: production は `--country` を正規化せず素通しするため
  (`cli.py:44` default "US"、`config.py` に `.upper()` なし)、lowercase を渡すと `is_us`/`is_jp`/
  `system_key_for`(すべて case-insensitive)を経由しない生比較が誤動作する。output 層に 7 箇所:
  `_fhir_common.py:237`(`_map_diagnosis_code`、lowercase で JP マッピング誤選択)/ `_fhir_conditions.py:45`
  / `_fhir_medications.py:68,137` / `_fhir_observations.py:52` / `_fhir_procedures.py:63` /
  `_fhir_localization.py:63`。いずれも `country_code = "JP" if country != "US" else "US"` 系。
- **修正**: `is_us(country)` / `is_jp(country)` へ置換(canonical helper、`implementation-rules.md` §4)。
  `_fhir_common._map_diagnosis_code` は複数 builder が使う共有 helper なので優先。
- **検証**: uppercase では byte 保存(production 不変)。lowercase cohort で US/JP の code system・
  mapping が正しく分岐することを確認。恒久防御は config 境界での country 正規化 or validation も検討。
- **由来**: FP-UNIFY-1(hai)は `system_key_for` 化で解消済。本項は残る sibling 比較の sweep。
- **Status:** DONE(session 39)。output 層 7 箇所を `is_us(country)` へ置換(commit b11f67b281、uppercase
  byte 保存、guard `test_fhir_country_case_insensitive.py`)。**「1 バグ見つけたら他 module も確認」**の
  cross-module sweep(user 指示)で output 層外に **同 class 2 件を追加検出+修正**(commit 8d82c04285):
  `identity/registry.py:get_provider`(lowercase で `ValueError` = fail-loud 不整合)+
  `patient/activator.py:347`(emergency-contact fallback、lowercase "us" で日本語「家」suffix)。
  全コードベース掃引で残存生比較ゼロを確認(`.lower()` idiom 群は正規化済で問題なし)。恒久防御
  (config 境界での country 正規化)は別 backlog。

## FP-CLAMP-RANGE — 状態変数 clamp が canonical `_variable_range` をバイパス【中・実害】

- **由来(session 39、anion_gap 修正の cross-module sweep)**: `apply_disease_onset`/`update` は
  `_variable_range(var)` で clamp するが、`inpatient.py:262`(手術 impacts)と `:1013`(合併症
  `state_impact`)は **ハードコード `max(-1.0, min(1.0, cur+delta))`** で適用。0..1 軸
  (cardiac_function / perfusion_status / renal_function 等)に大きな負 delta(例 cardiogenic-shock
  合併症 `cardiac_function: -0.30`)が乗ると **負値化**(生理学的に無効)。`apply_coupling_rules` は
  cardiac_function を再クランプしないため持続し、derived perfusion / lactate / BP を歪める。
- **修正**: 公開ヘルパ `physiology.engine.apply_state_delta(state, var, delta)` を新設(clamp range を
  `_variable_range` から取得)= clamped delta 適用の single edit point。`apply_disease_onset`/`update`
  を byte-identical に載せ替え + inpatient 2 箇所を経由化。
- **検証**: profile golden 12 件 byte 不変(該当 seed で 0..1 軸が負に到達せず)= 低 blast-radius の
  防御修正。guard `TestApplyStateDelta`。
- **Status:** DONE(session 39、commit f8090ddde0)

## FP-DELTA-VALIDATE — 状態変数 delta の author-time silent-drop gate【高・実害あり class】

- **由来(session 40、`FP-UNIFY-2` に続く「FHIR データ品質・臨床整合性」観点の候補洗い出し
  中に検出)**: `physiology.engine.apply_state_delta` は `getattr(state, var, None)` で存在しない
  state 属性を **silent no-op** にする。session 39 の `anion_gap_status` 追加(GI acidosis 実害)
  と同 class の C1 silent-drop が YAML author 側に **3 sink × 25 entry** 残存していた:
  1. `initial_state_impact.<severity>.<state_var>` — 5 件(DKA `electrolyte_status` moderate/severe
     + DKA `consciousness` severe + hemorrhagic_stroke `neurological_status` moderate/severe)。
     `apply_disease_onset → apply_state_delta` 経由で silent-drop。
  2. `complications[].state_impact.<state_var>` — 9 件(DKA hypokalemia/hypoglycemia/cerebral_edema/
     AKI の `electrolyte_status` × 2 + `consciousness` × 2、hemorrhagic_stroke hematoma_expansion/
     cerebral_edema/brain_herniation/hydrocephalus/seizure の `neurological_status` × 5)。
     `inpatient.py:1009 apply_state_delta` 経由で silent-drop。
  3. `course_archetypes.<name>.trajectory.<state_var>` — 11 件(DKA `electrolyte_status` × 4 +
     `consciousness` × 1、hemorrhagic_stroke `neurological_status` × 6)。
     `clinical_course.engine.get_state_changes` の ハードコード whitelist ループで silent-drop。
- **修正(3 層 fail-loud gate + canonical single source of truth)**:
  1. `physiology.engine._VARIABLE_RANGES` を module-level 定数化(以前は関数内 local dict)+ 公開
     `canonical_state_vars() -> frozenset[str]` helper(single source of truth)。
  2. `physiology.engine._validate_initial_state_impact` + `_validate_complications_state_impact`
     新設(disease_id / severity / 該当 state_var を含む詳細 error message)。
  3. `clinical_course.engine.TRAJECTORY_STATE_VARS` を `canonical_state_vars() - {respiratory_fraction}`
     由来の pinned tuple 化(順序は AD-16 で load-bearing — 内部 RNG 消費順に影響、e2e で検証済)+
     module-level `assert` で drift catch。`_validate_course_archetypes` 新設。
  4. `disease.protocol.load_disease_protocol` に 3 validator を wire(既存 severity / archetype_modifiers
     validator と同 pattern)= YAML load 時 fail-loud。
- **既存 25 entry の triage**: 全て「delete + NOTE コメント(将来 state 軸拡張 TODO)」で clinical
  actions は unchanged。fabrication 回避(delete)を salvage-mapping(不完全マッピング)より優先。
  Consciousness/GCS は nursing flowsheet enricher で独立生成済のため clinical 情報 loss なし。
  Electrolyte/K axis + neurological_status axis は本格的な physiological-model 拡張として別 brainstorming。
- **横展開 sibling sweep(session 39 の user 明示ルール適用)**: 3 sink 全てを再スイープし、全 32
  disease YAML で残存 silent-drop = 0 を確認(集計スクリプト `python` 使用、CI 不採用)。
  encounter YAML の `initial_state_impact` は現状 0 件、course_archetypes trajectory も 0 件。
- **検証**: unit 2299 + integration 289 + regression 12 + e2e 37 全 PASS(regression の初回失敗
  = `TRAJECTORY_STATE_VARS = sorted(frozenset(...))` へ変更したことで RNG 順序ズレ → 復元して解決、
  AD-16 教訓を order-pin unit test に追加)。guard: `tests/unit/test_initial_state_impact_validation.py`
  (20 test)。
- **恒久防御**: 今後の新 physiology 軸追加は `_VARIABLE_RANGES` + `PhysiologicalState` + 必要なら
  `TRAJECTORY_STATE_VARS` の 3 点更新で完成。validator が自動的にカバー。
- **Status:** DONE(session 40)。

## FP-FH-CODE-RESOLUTION — `FamilyMemberHistory` の I64 / E11 表示 fallback + Z-code 誤 map【中・実害】

- **由来(session 40、`FP-UNIFY-2` に続く「FHIR データ品質」観点の候補洗い出し中に検出)**:
  US p=1000 cohort probe で `FamilyMemberHistory.condition[].coding[0].display` に
  `"(display unavailable)"` を出力。3 defect が converge:
  1. **I64 missing**: `family_history.yaml.conditions.I64`("Stroke, not specified as
     haemorrhage or infarction"、WHO ICD-10 leaf)が `codes/data/icd-10-cm.yaml` にも
     `code_mapping_diagnosis/us.yaml` にも未登録 → US emit で `code=I64` + `display=
     "(display unavailable)"`(FHIR display 完全 fallback)。JP emit も `display=I64`
     (icd-10.yaml にも未登録)。
  2. **E11 prefix-child fallback misdisplay**: E11(category header、CM 未 billable)が
     `icd-10-cm.yaml` に無く、`code_lookup` の prefix-child 探索が E11.10 を拾って
     `"Type 2 diabetes mellitus with ketoacidosis without coma"` を返す = family-of-DM
     には臨床的に誤 display。
  3. **Personal-history Z-code overreach**: chronic-history 用 `_map_diagnosis_code` が
     I63 → Z86.73("Personal history of TIA / cerebral infarction")に fold。これは
     患者本人の既往を表す Z-code で、`FamilyMemberHistory.condition.code`
     (relative の疾患そのもの)には意味論的に不適合。
- **修正**:
  1. `codes/data/icd-10.yaml` に **WHO I64**(WHO ICD-10 authoritative、
     icd.who.int/browse10 JsonGetChildrenConcepts で権威検証)追加。EN/JA。
  2. `locale/us/code_mapping_diagnosis.yaml` に `E11 → E11.9` + `I64 → I63.9` 追加
     (CM billable leaf)。CMS ICD-10-CM に I64 は存在しない事実を NLM Clinical Tables
     API で確認、CLAUDE.md 規則に従う。
  3. `_fhir_family_history._resolve_family_history_code(code, country)` 新設 =
     `_map_diagnosis_code` をラップし **Z-code target を reject**(family-history
     文脈では personal-history 変換を skip、原コードで disease 側 display を保持)。
  4. FH builder が新 helper 経由で code 変換 → `_build_diagnosis_codeable_concept`
     (`_fhir_conditions` の chronic condition 経路と同じ pattern に到達)。
- **coverage test 拡張**: `test_diagnosis_code_coverage.py` に **4th source =
  `family_history.yaml.conditions`** を追加(既存の disease icd_codes + encounter icd10_code
  + engine differential/progression の 3 source と同じ resolve 検証を掛ける)= 未登録 code の
  追加を unit gate で catch する恒久防御。
- **横展開 sibling sweep**: `_build_diagnosis_codeable_concept` を使う他 builder
  (`_fhir_conditions` — 既に `_map_diagnosis_code` 適用済)+ ICD 直接 emit する builder
  (`_fhir_hai` — HAI コードは全 billable leaf、prefix-child 罠回避)を全て確認。他 gap 無し。
- **検証**: unit 2312 + integration 289(既存 `test_builds_one_resource_per_relative`
  の `assert "E11" in codes` を `assert "E11.9" in codes` に更新 — 修正が反映された
  ことの逆側 guard)+ regression 12 + e2e 37 全 PASS。US p=1000 cohort 再 probe で
  `(display unavailable)` = **0 件**、E11 → "Type 2 diabetes mellitus without complications"
  正しく表示。
- **恒久防御**: 今後 family_history.yaml.conditions に追加された code は
  `test_diagnosis_code_coverage.py` の 4-source sweep で自動 catch。unit で fail-loud。
- **Status:** DONE(session 40)。

## FP-COMPLETENESS-GATE — C1/C2/C3 検証 audit 軸【高・capstone】

- **目的**: §1 ゴールの恒久化。上流 FP が drop を塞いだ後、新たな不完全状態の混入を即検出する gate。
- **設計案**:
  - **C1(silent-drop)**: `extra="forbid"`(FP-YAML-3)が author-time 防御。加えて「YAML に書いた
    severity.distribution / diagnostic_difficulty 等の意図値が、生成された cohort の分布に反映されて
    いるか」を audit で統計検証(lift_firing_proof 拡張)。
  - **C2(degenerate)**: FHIR resource ごとに「no-op/placeholder/全患者同一」でないことを検査。
    例: Condition.stage が生理に効いている(cohort 内で stage 別に vitals 分布が分離)、person.age が
    encounter 日で変動する。
  - **C3(missing structure)**: 各疾患が期待する resource(悪化日 Observation / course narrative /
    complications 由来 Encounter)が生成されているかの per-disease 期待マトリクス。
  - **成果物**: `clinosim/audit/axes/completeness.py` + 疾患ごとの期待宣言。DESIGN.md に AD 追記。
- **依存**: 上流 FP 完了後(先に導入すると大量 FAIL で ship 不能)。
- **Status:** DONE(pragmatic capstone、session 38)= **不変則 test suite**
  `tests/unit/test_completeness_invariants.py`(7 guards、sub-second、production 変更なし)。
  C1: `extra="forbid"` 維持 / top-level diagnostic_difficulty 0 / severity_beta reader 0 /
  全 severity.distribution well-formed。**C2 一般クラス guard**: 全 graded-stage 疾患
  ({N18,I50,J44,J45,I10,I25})が STAGE_SEVERITY 消費者を持つ(I10-class no-op 再発防止)。
  C3: HF/subdural closures 維持 + course_archetypes backlog allowlist の drift 検出。
  regression 捕捉を実証(I10 除去で guard fail)。spec:
  `docs/superpowers/specs/2026-07-06-completeness-gate-design.md`。
  **残(別 chain)**: cohort-level 統計 audit 軸(`audit/axes/completeness.py`、authored 分布の
  cohort 反映 / stage 別 vitals 分離 / per-disease 期待 resource マトリクス)= audit framework 統合が要る大工事。
</content>
