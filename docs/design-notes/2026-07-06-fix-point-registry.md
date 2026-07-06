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
| FP-ARCH-1 | course_archetypes 高優先(HF / subdural) | C3 | 中 | なし | OPEN |
| FP-ARCH-2 | course_archetypes + complications 中優先(burn / trauma 系) | C3 | 中 | なし | OPEN |
| FP-ARCH-3 | course_archetypes 低優先(hip / crush / electrical / wrist) | C3 | 低 | なし | OPEN |
| FP-AGE | person.age as-of 化(2 フェーズ) | ~~C2~~ **非FHIR** | 低 | なし | OPEN(再分類、下記) |
| FP-UNIFY-2 | 日付→ISO ヘルパ共通化 | — | 中 | なし | OPEN |
| FP-UNIFY-3 | FHIR 固定 ja ラベル辞書統合 + idiom 統一 | — | 低 | なし | OPEN |
| FP-UNIFY-4 | case-sensitive `country == "US"` 比較の一掃(lowercase バグ class) | — | 中 | なし | OPEN |
| FP-COMPLETENESS-GATE | C1/C2/C3 を検証する audit completeness 軸 | — | 高(capstone) | 上流 FP 完了後 | **DONE**(不変則 test suite)/ cohort 統計 audit 軸は残 |

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
| `expected_vital_distributions` / `reference_ranges` / `drug_interactions` | 各23 | 削除 | モデルに在るが消費ゼロ。reference_ranges は locale 側が live |
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
  (2) 死蔵モデル field 3 件(`expected_vital_distributions` / `reference_ranges` /
  `drug_interactions`、各 23 YAML に block あり・消費 0)は forbid が受理するため未除去。
  除去は model field + 23×3 YAML block 削除の機械作業(byte 保存)。

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
- **Status:** OPEN(3 件)

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
- **Status:** DONE(session 38)。より完全化(CKD stage finding / NYHA class 等の per-system 正 SNOMED
  付与)は authoritative 検証を要する任意の後続改善。

## FP-UNIFY-2 — 日付→ISO 文字列ヘルパ共通化【中・byte 保存】

- `_fhir_imaging_study.py:57 _isoformat_or_str` を `_fhir_common`(or `_shared`)へ昇格し、
  `_fhir_conditions`(7)/ `_fhir_observations`(:236/346/397)/ `_fhir_nursing`(:63/86/142/159)/
  `_fhir_patient:195` / `_fhir_service_request:504` の `[:10]`/`isinstance` インライン重複を置換。
- **Status:** OPEN

## FP-UNIFY-3 — FHIR 固定 ja ラベル辞書統合 + idiom 統一【低・byte 保存】

- 「社会歴」2 経路重複(`_fhir_common.py:117` 正道 vs `_fhir_patient.py:288` 直書き)解消。
- 固定 ja ラベル(`_fhir_encounter:187` / `_fhir_diagnostic_report:429` / `_fhir_service_request:317,497`
  / `_fhir_microbiology:139` / `_fhir_facility:29,134` 他)を `_fhir_localization` 辞書へ。
- `lang=="ja"` vs `is_jp(country)` を `resolve_lang`/`is_jp` に統一。`_o` ラッパ 3 箇所
  (`_fhir_observations:33` / `_fhir_service_request:74` / `_fhir_diagnostic_report:56`)を
  `get_attr_or_key as _o` alias import に。`healthcare_system/loader.py:24-27` の country map を
  `is_jp/is_us` 経由に。`device`/`sdoh`/`facility` loader に `_validate_*` 追加。
- **Status:** OPEN

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
- **Status:** OPEN

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
