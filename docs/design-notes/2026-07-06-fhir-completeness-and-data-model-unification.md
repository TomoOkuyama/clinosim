# FHIR Completeness Goal & Data-Model Unification — 考察と方針(2026-07-06)

**Status:** Active(session 38 で確立)
**種別:** 分析 + ゴール設定。実行トラッキングは [`2026-07-06-fix-point-registry.md`](2026-07-06-fix-point-registry.md)、
別セッションが従う規約は [`../design-guides/data-model-and-completeness-conventions.md`](../design-guides/data-model-and-completeness-conventions.md)。
**先行文書:** [`2026-07-02-grand-design-review-and-roadmap.md`](2026-07-02-grand-design-review-and-roadmap.md)(基盤 chain の位置づけ、引き続き有効)

本文書は、6 系統の横断調査(重症度二重システム / 孤児 YAML キー / I10 ステージ配線 /
person.age 複数年 / 9 疾患 course_archetypes 欠如 / 共通ロジック統一)の結果を統合し、
ユーザーが設定した **「最終 FHIR 出力の不完全状態をゼロにする」ゴール**を定義する。個別の
修正手順・優先度・セッション割当は fix-point registry に、実装が守る規約は conventions guide に分離した。

---

## 1. ゴール定義 — FHIR Completeness Contract

**「不完全状態(incomplete state)」を 3 クラスに定義し、それぞれのゼロ化をゴールとする。**

| クラス | 定義 | 現状の代表例 |
|---|---|---|
| **C1: Silent-drop(著者意図の消失)** | YAML に著者が書いた臨床意図が、コードに読まれず default 値に化ける / 破棄される | `diagnostic_difficulty` top-level 配置 15 疾患が 0.25/0.5 → 0.3 に化ける(**実害バグ**)。`severity.distribution`/`modifiers` 全 30 疾患が無視される。`archetype_modifiers` 23 疾患が silent-drop |
| **C2: Degenerate element(退化した要素)** | FHIR に要素は出るが、値が no-op / プレースホルダ / 全患者同一で臨床情報を持たない | I10 `Condition.stage` が "Stage 1/2" テキストを出すが生理・vitals・処方に一切効かず、SNOMED type は "Tumor stage finding" の誤流用。person.age が複数年で固定=narrative/CSV に矛盾年齢 |
| **C3: Missing structure(構造の欠落)** | 疾患・encounter に対して本来生成されるべき resource / event が生成されない | 9 疾患が course_archetypes + complications 両欠如 → 悪化日の追加 Observation / ICU 転送 Encounter / 疾患特異的 narrative が生成されない |

**ゴールの達成判定 = 機械化された completeness gate**(registry FP-COMPLETENESS-GATE)。
「著者が YAML に書いた全ての臨床意図が FHIR に到達し(C1=0)、出力される全 FHIR 要素が
非退化の実値を持ち(C2=0)、疾患/encounter が期待する resource が生成される(C3=0)」ことを
audit で証明する。これは既存の silent-no-op 防御文化(canonical constants + `_validate_*` +
`lift_firing_proof`)の疾患 YAML への拡張であり、新しい思想ではない — **疾患 YAML だけが
この防御の唯一の穴になっている**(`DiseaseProtocol` が `extra="ignore"` の無防備)。

---

## 2. 根本原因の統合 — なぜ不完全状態が生まれたか

調査 6 系統は表面上は別問題だが、**3 つの共通根本原因**に収束する。

### 根本原因 R-A: `DiseaseProtocol` の `extra="ignore"`(silent-drop の温床)

`clinosim/modules/disease/protocol.py:107` の `DiseaseProtocol` は `model_config` 未定義 =
Pydantic default `extra="ignore"`。`DiseaseProtocol(**data)`(`:186`)で **モデルに無い
トップレベルキーが load 時に無音破棄**される。これが以下を一括で生んでいる:

- `archetype_modifiers`(23 疾患)/ `rehabilitation`(8)/ `differential_diagnosis`(5)/
  `prerequisite`(1)/ `precipitants`(1)の完全 silent-drop。
- `diagnostic_difficulty` を **top-level に置いた 15 疾患**の値が破棄され、読み取り側
  (`inpatient.py:608` は `protocol.diagnostic.get("diagnostic_difficulty", 0.3)` と**ネスト**で読む)
  が default 0.3 に fall-back = **acute_mi 0.25 / sepsis 0.5 の意図が失われる実害バグ**。

対照的に `EncounterConditionProtocol` は `extra="allow"` + 生 dict 返し、`PatientProfile` は
既に `extra="forbid"`(`config.py:101`、PR-90 class 防御コメント付き)。**疾患 YAML だけが防御外。**

さらに疾患 YAML には**第 2 の消費経路**がある:`order/engine.py` は Pydantic を通さず
生 dict を `.get()` で読む(`:255,260,273,432`)。`extra="forbid"` はモデル経由のみ守るため、
両経路の整合が別途必要。

### 根本原因 R-B: 「重症度」の 3 系統併存 + 定義した意図の死蔵

重症度が 3 つの独立系統で表現され、疾患著者の意図(B)が入院経路で死んでいる:

| 系統 | 定義場所 | 消費 |
|---|---|---|
| **A. 集団統計(連続 float)** | `locale/*/demographics.yaml` `severity_beta` / `severity_minimum` | ✅ 入院経路の唯一のソース(`population/engine.py:362-366`) |
| **B. 疾患 YAML(カテゴリ + modifiers)** | `reference_data/*.yaml` `severity: {distribution, modifiers}` | ❌ **参照ゼロ**(R-A で silent-drop の隣、モデルには載るが誰も読まない) |
| **C. encounter YAML(カテゴリ)** | `encounter/reference_data/*.yaml` `severity_distribution` | ✅ ED/外来経路(`emergency.py:76-83`、A とは無関係に独立サンプル) |

入院経路の唯一の接続点 `inpatient.py:117` が `event.severity`(A の Beta)を **0.3/0.7 ハード
コード閾値**でカテゴリ化。ここで:(i)疾患 YAML の分布・リスク因子補正(modifiers)が無視され、
(ii)下限が `severity_minimum`(float)と `minimum_severity`(str)の二重定義、(iii)閾値が
疾患非依存。**臨床的上流(疾患の重症度分布 × 患者リスク因子)が死に、疫学的だが疾患非依存な
Beta 形状が上流を独占**している。同型の死蔵が `incidence.risk_multipliers`(疾患 YAML、参照ゼロ、
locale 側 `disease_risk_multipliers` が手作業重複)にも存在。

### 根本原因 R-C: 「配線されたが機能しない」パターン(C2 の温床)

生成はされるが下流の消費者が居ないため退化する。I10 stage(生成 → Condition.stage テキスト
まで出るが physiology 消費者ゼロ)、person.age(生成時固定 → 唯一 immunization だけが as-of
再計算、他は固定値を表示)。course_archetypes 欠如 9 疾患(fallback は炎症性内科向けチューニング
=外傷/術後には臨床不整合、かつ complications も欠くため悪化 event 源が枯渇)。

---

## 3. 統合方針 — 判断 4 軸(データ品質 / 臨床整合性 / メンテ性 / コンセプト適切性)

### 3.1 重症度: 疾患 YAML を canonical、集団統計は「発生率 + 分布パラメータ」に役割分離(案 c 発展)

3 案(a: 集団統計を canonical にし疾患 severity 削除 / b: 疾患 YAML を canonical にし population
を切替 / c: hybrid)のうち、**4 軸で最高スコアは案 c の発展形**:

- **臨床整合性**: 重症度分布は疾患固有(AMI は必ず moderate 以上、UTI は mild 中心)であるべき =
  疾患 YAML `severity.distribution` が臨床的上流。患者リスク因子補正(`modifiers`: age_over_75 →
  severe 増)も疾患 YAML が持つのが自然。**→ B を活かす。**
- **コンセプト適切性(population-driven)**: 集団の疾患**発生率**は population 設計の根幹 =
  locale `demographics.yaml` に残す。重症度の**個人内サンプリング**は疾患 YAML 分布から引く。
  `severity_beta` は「疾患ごとの連続重症度の形状パラメータ」として疾患 YAML 側へ移設 or 疾患
  YAML `severity.distribution` から導出し、locale は発生率専任にする。
- **メンテ性**: 重症度の single source of truth = 疾患 YAML。float↔カテゴリ境界・下限を **1 箇所**
  (`scenario_flags_from_protocol` 兄弟の `severity_from_protocol(protocol, draw)` ヘルパ)に集約。
  `inpatient.py:117` のハードコード閾値 + `minimum_severity`/`severity_minimum` 二重定義を撤廃。
- **データ品質**: ED(系統 C)も同ヘルパに載せ、入院/ED の重症度定義を統一。

**これは brainstorming 必須の architecture 決定**(registry FP-SEV-MODEL)。挙動が変わり golden
全再生成を伴う。決定前に `severity.distribution` を削除してはならない(意図の記録なので、
配線するまで残す)。

### 3.2 孤児 YAML キー: 「配線 or 削除」を全キー確定 → `extra="forbid"` で恒久防御

silent-no-op 防御文化の疾患 YAML への適用。キーごとに 4 軸で配線/削除を判定(registry FP-YAML-*):

- **即修正(実害)**: `diagnostic_difficulty` を全疾患でネスト配置に統一(top-level 15 疾患を
  `diagnostic:` 配下へ移動)+ 読み取り側に top-level fallback を一時的に持たせず、移動で解決。
- **配線候補**: `archetype_modifiers`(→ 3.1 の severity model 決定後、`select_archetype` に
  患者プロファイル補正として接続 or 削除。現状 `select_archetype` は独自ハードコード modifier を
  持つので二重管理の解消が要る)。`incidence.risk_multipliers`(locale の手作業重複を疾患 YAML
  から導出に切替 or 削除)。
- **削除候補**: `differential_diagnosis`(live な `diagnostic.differential` の drift 重複)、
  `rehabilitation` / `precipitants` / `prerequisite`(未配線)、死蔵モデルフィールド
  (`expected_vital_distributions` / `reference_ranges` / `drug_interactions` / `readmission`)。
- **最終ゲート**: 全キー確定後に `DiseaseProtocol` へ `extra="forbid"` 導入(`config.py:118-123`
  の PatientProfile 前例と同思想)。同時に `order/engine.py` の生 dict 経路も owner module
  accessor 経由に寄せて両経路を塞ぐ。

### 3.3 course_archetypes 欠如: 臨床価値順に authoring、trauma は complications 優先

9 疾患を臨床価値でランク(registry FP-ARCH-*):
- **高**: `heart_failure_exacerbation`(利尿反応/難治化コース、再入院 0.22)、`subdural_hematoma`
  (再出血/神経悪化、死亡 0.15)。
- **中〜高**: `industrial_burn_severe` / `traffic_accident_severe` / `fall_from_height`
  (多発外傷・感染合併)。
- **低〜中**: `hip_fracture`(せん妄/DVT は complications 化が本筋)/ `crush_injury_hand` /
  `electrical_injury`。
- **低**: `wrist_fracture_surgical`(良性定型経過、fallback で実害小)。

fallback trajectory が炎症性内科向けである以上、外傷系は **course_archetypes より先に/併せて
`complications:` ブロック**(ICU 転送・DVT・せん妄・SSI トリガ)を書くと C3 の欠落が本質的に埋まる。

### 3.4 I10 ステージ: 「生理消費者の新設」とセットでのみ配線(単独 STAGE_SEVERITY 追加は禁止)

I10 を `STAGE_SEVERITY` に足すだけでは「誰も読まない severity_score」を生むだけ(TODO 既述)。
**高血圧の生理モデル(`physiology/engine.py:initialize_state` に I10 分岐 = 血圧状態軸)を新設**し、
stage → severity_score → 血圧/降圧薬強度 → `Condition.stage`(SNOMED type を高血圧適切コードへ
訂正)まで一貫配線する(registry FP-I10)。CKD/HF の session 37 パターンを踏襲。3.1 の severity
model と整合させると綺麗(stage も疾患 severity の一部として扱える)。

### 3.5 person.age 複数年: as-of-age ヘルパ昇格、2 フェーズで seed 経路を保護

`immunization/engine.py:36-39 _age_on(dob, on, fallback)` を `_shared` へ昇格し「as-of 日付関数」化
(registry FP-AGE):
- **Phase A(低リスク、seed 経路不変)**: 出力・narrative・LLM・labs の age を event 日基準に。
  rng 分岐を変えないので golden は age 表示値のみ差分。
- **Phase B(golden 全再生成、要 AD)**: incidence 判定(`population/engine.py:449,597,627,640`)を
  as-of 化。閾値が変わり event 発火が変わる = rng 系列がずれる。40 歳到達で健診/癌検診が発火する
  など臨床的に正しくなるが、AD レビュー + golden 再生成が必須。
- identity / 世帯構成 / 身長 shrinkage は生成スナップショット時点で確定してよい(as-of 不要)。

### 3.6 共通ロジック: 統一済み。残る逸脱は少数、hai の潜在バグを最優先

監査結果、canonical パターンは概ね徹底済み。残る逸脱(registry FP-UNIFY-*):
- **最優先(潜在バグ)**: `_fhir_hai.py:44` が `system_key_for` をバイパスし `country == "US"`
  ハードコード → lowercase country で ICD code system 誤選択。`system_key_for("diagnosis", country)`
  に置換。
- **中**: 日付→ISO 文字列ヘルパ(`_isoformat_or_str`)を `_fhir_common` へ昇格し builder 横断の
  `[:10]`/`isinstance` インライン重複を統一。FHIR 固定 ja ラベルの辞書統合(「社会歴」2 経路重複)。
- **低**: `lang=="ja"` vs `is_jp(country)` idiom 統一、`_o` ラッパ 3 箇所を alias import に、
  `healthcare_system/loader.py` の country map を `is_jp/is_us` 経由に、`device/sdoh/facility`
  loader への `_validate_*` 追加。
- これらは大半が byte-diff 保存可能(hai fix を除く)= refactor PR として安全。

---

## 4. Chain 順序(複数セッションでの進め方)

依存関係と value/risk で順序化。詳細は registry。

| 順 | Chain | 根拠 | golden 影響 |
|---|---|---|---|
| 1 | **FP-UNIFY-1(hai system_key_for)+ FP-YAML-1(diagnostic_difficulty)** | 両者 live/潜在バグ、低リスク高価値。単独で完結 | hai=byte保存 / dd=要再生成(限定) |
| 2 | **FP-SEV-MODEL(brainstorming → 実装)** | 3.1。最大の基盤決定。FP-YAML-*(archetype_modifiers)と FP-I10 が依存 | 全再生成 |
| 3 | **FP-YAML-*(孤児キー triage → extra="forbid")** | 3.2。severity model 決定後に archetype_modifiers を配線/削除できる | 限定 |
| 4 | **FP-I10(高血圧生理モデル)** | 3.4。severity model と整合 | 全再生成 |
| 5 | **FP-ARCH-*(course_archetypes + complications authoring)** | 3.3。独立、並行可。臨床価値順に分割 | 該当疾患のみ |
| 6 | **FP-AGE(as-of-age 2 フェーズ)** | 3.5。独立。Phase A→B | A=表示のみ / B=全再生成 |
| 7 | **FP-COMPLETENESS-GATE** | §1 ゴールの恒久化。C1/C2/C3 の audit 証明。上流の drop が塞がった後に導入 | gate 追加 |
| — | **FP-UNIFY-2..N(機械的共通化)** | 3.6。関連 chain に随伴 | byte保存 |

**FP-COMPLETENESS-GATE を最後に置く理由**: gate は「著者意図が到達したか」を検証するので、
先に上流の silent-drop(FP-YAML/FP-SEV)を塞がないと gate 自体が大量 FAIL で ship 不能になる。
gate を capstone にすることで、以降のセッションが新たな不完全状態を混入したら即検出される
恒久防御になる。

---

## 5. 本セッション(2026-07-06)の成果物

- 本文書(考察 + ゴール定義)
- [`2026-07-06-fix-point-registry.md`](2026-07-06-fix-point-registry.md)(修正ポイント登録簿、
  TODO.md と分離、複数セッション追跡用)
- [`../design-guides/data-model-and-completeness-conventions.md`](../design-guides/data-model-and-completeness-conventions.md)
  (別セッションが従う規約:severity single-source / YAML-key lifecycle / as-of-age / completeness contract)
- 読み取り専用調査のみ。コード変更なし(規約どおり、実装は各 chain の TDD セッションで)。
</content>
