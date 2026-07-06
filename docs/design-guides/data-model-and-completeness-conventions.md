# Data-Model & Completeness Conventions — 別セッション遵守規約

**Status:** Active(2026-07-06、session 38 で確立)
**Audience:** FHIR completeness fix-point registry(`docs/design-notes/2026-07-06-fix-point-registry.md`)の
各 chain を実装するセッション/実装 AI。
**位置づけ:** 既存の [`implementation-rules.md`](implementation-rules.md)(全域の不変則)と
[`fhir-data-generation-logic.md`](fhir-data-generation-logic.md)(Layer 4)の**補遺**。ここには
completeness 修正に固有の新規約だけを書く — 既存規約は**再掲せず cross-link**する(重複はこの
プロジェクト自身の禁則)。迷ったら判断 4 軸:**データ品質 / 臨床整合性 / メンテ性 / コンセプト適切性**。

---

## 0. まず読む(前提)

1. [`implementation-rules.md`](implementation-rules.md) — 全域の不変則(canonical helpers / 決定性 /
   silent-no-op 防御 / 検証 gate)。**本補遺の規約はこれを上書きしない、追加する。**
2. [`../design-notes/2026-07-06-fhir-completeness-and-data-model-unification.md`](../design-notes/2026-07-06-fhir-completeness-and-data-model-unification.md) — 考察・ゴール(なぜこの規約が要るか)。
3. `docs/design-notes/2026-07-06-fix-point-registry.md` — 着手する FP の Status/依存/検証。

---

## 1. FHIR Completeness Contract(このプロジェクトの新しい第一原理)

**「著者が YAML に書いた臨床意図は、必ず FHIR 出力に到達する」**を不変則に格上げする。
不完全状態を 3 クラスで定義(考察 §1)、いずれも新規混入禁止:

- **C1 Silent-drop 禁止**: YAML キーが読まれず default に化ける / 破棄されることを許さない。
- **C2 Degenerate 禁止**: FHIR 要素が no-op / placeholder / 全患者同一の退化値を持つことを許さない。
- **C3 Missing-structure 禁止**: 疾患/encounter が期待する resource / event の欠落を許さない。

新機能・修正が新たな C1/C2/C3 を作らないことを、実装者は自分で証明する(§5 チェックリスト)。

---

## 2. YAML キーのライフサイクル規約(C1 対策)

### 2.1 「読まれない YAML キーを ship しない」

新しい YAML キーを追加したら、**同一 PR 内で消費コードを配線するか、追加しない**。
`implementation-rules.md` §9-5「aspirational scaffold 禁止」の YAML 版。

### 2.2 `extra="forbid"` を YAML-loaded Pydantic モデルの既定にする

- `PatientProfile`(`config.py:101`)が前例。新しい YAML-loaded `BaseModel` は
  `model_config = ConfigDict(extra="forbid")` を**最初から**付ける。
- 既存の `extra="ignore"`(= silent-drop)を持つモデルは撤廃対象(FP-YAML-3 が `DiseaseProtocol` を移行)。
- `extra="allow"`(`EncounterConditionProtocol`)+ 生 dict 返しは「意図的無検証」だが、この経路も
  将来 canonical constants 照合(`SUPPORTED_*` 差分検出、`implementation-rules.md` §9-2)で塞ぐのが望ましい。

### 2.3 モデルを通さない生 dict 経路にも防御を効かせる

疾患 YAML には 2 経路がある:(A) `DiseaseProtocol(**data)` 属性アクセス、(B) `order/engine.py` の
生 dict `.get()`。**`extra="forbid"` は経路 A のみ守る。**経路 B は owner module の accessor 経由に寄せ、
未知キーを load 時に fail-loud にする(FP-YAML-3)。「片方の経路だけ守った」は J5 class(1 venue のみ配線)の再来。

### 2.4 キーを削除するときも意図を記録

孤児キーが臨床文献引用(TIMI / ACC-AHA / Tokyo Guidelines 等)を含む場合、削除前に commit message
または DESIGN.md に「なぜ配線せず削除したか」を残す。データ資産の意図の消失を防ぐ。

---

## 3. 重症度 single-source-of-truth 規約(FP-SEV-MODEL 確定後に本節を更新)

> **注意**: 本節は FP-SEV-MODEL の brainstorming で canonical が確定するまで**暫定**。確定後に
> `severity_from_protocol` の正式シグネチャと下限一元化ルールをここに固定する。

- 重症度は **1 つの canonical source**(考察 §3.1 推奨 = 疾患 YAML の分布)から導出する。
  float↔カテゴリ境界・下限を**単一ヘルパ** `severity_from_protocol(protocol, draw)` に集約
  (`scenario_flags_from_protocol` / `classify_lab_specs` 兄弟パターン)。
- **禁止**: `inpatient.py:117` の 0.3/0.7 のような call-site ハードコード閾値。下限を
  `severity_minimum`(float)と `minimum_severity`(str)で二重に持つこと。
- 入院/ED の重症度は同一ヘルパに載せ、経路依存の二重定義を作らない。

---

## 4. 「生成したが機能しない」を作らない(C2 対策)

### 4.1 stage / severity は生理消費者とセットで配線

graded-stage 疾患(CKD/HF/COPD/asthma/IHD は session 37 で配線済、I10 は未 = FP-I10)は、
`STAGE_SEVERITY` エントリ**単独追加を禁止**。必ず (1) stage → severity_score マッピング、
(2) `physiology/engine.py:initialize_state` の消費分岐、(3) vitals/labs/処方への波及、
(4) FHIR resource の適切な code、まで一貫させる。「誰も読まない severity_score」は C2。

### 4.2 as-of-age パターン(FP-AGE の参照実装)

時間依存の属性(age など)を複数年シミュレーションで正しく表示・計算するには、`immunization/
engine.py:36-39 _age_on(dob, on, fallback)` を `_shared` へ昇格した **as-of 日付関数**を使う。
call-site は event 日(`event.timestamp`)を渡す。

- **seed 経路を変えない群**(出力/narrative/LLM/labs)= as-of 化しても golden は表示値のみ差分 → 低リスク。
- **seed 経路を変える群**(incidence 判定 = rng 分岐が変わる)= golden 全再生成 + AD 追記が必須 → 別フェーズ。
- 生成スナップショット時点で確定してよい群(identity / 世帯 / 身長 shrinkage)は as-of 化しない。

**この「seed 経路を変えるか否かで 2 フェーズに割る」判断は、決定論に触る全修正に一般化して適用する。**

### 4.3 FHIR の code は退化流用しない

`Condition.stage` の SNOMED type に "Tumor stage finding"(385356007)を高血圧へ流用するような
「近いから使う」を禁止。適切なコードが codes YAML に無ければ authoritative source(NLM/WHO)で
検証して追加(`implementation-rules.md` §6、捏造禁止)。

---

## 5. clinical authoring 規約(C3 対策)

### 5.1 course_archetypes と complications はセットで考える

急性期疾患に course_archetypes を追加するとき、悪化 event(ICU 転送・DVT・せん妄・SSI)の源は
`complications:` ブロックである(course archetype は trajectory 形状、complications は離散 event)。
外傷/術後系は fallback trajectory(炎症性内科向けチューニング)が臨床不整合なので、**course_archetypes
より先に/併せて complications** を書く。テンプレート = `bacterial_pneumonia.yaml:581-655`。

### 5.2 疾患 authoring の per-disease 検証

新しい course_archetypes / complications を書いたら、その疾患の cohort を生成し (a) 悪化コースが
非ゼロ率で発火、(b) 悪化日の追加 Observation / narrative が実出力に現れることを grep(test green
だけでは C3 を検出できない、`implementation-rules.md` §8「実出力 grep」)。

---

## 6. 実装セッションのチェックリスト(completeness fix 固有)

`implementation-rules.md` §0 の chain workflow に加えて:

1. **着手前**: registry の該当 FP の Status/依存を確認。依存 FP が未 DONE なら順序を守る
   (特に FP-YAML-1 → 2 → 3、FP-SEV-MODEL → archetype_modifiers/I10)。
2. **C1 チェック**: 触った YAML の全キーが消費されているか(経路 A/B 両方)。`extra="forbid"` を
   入れた/入っているモデルで全既存 YAML が load 成功するか。
3. **C2 チェック**: 追加した FHIR 要素が cohort 内で非退化(患者間で分散、default fall-back でない)か。
4. **C3 チェック**: 疾患/encounter が期待する resource が実出力に出るか(grep)。
5. **決定論**: seed 経路を変えるか判定 → byte 保存 refactor か golden 再生成 new-feature かを宣言。
6. **DONE 時**: registry の Status を DONE に更新 + PR/commit を追記。gate(FP-COMPLETENESS-GATE)が
   既に存在するなら audit completeness 軸を green に。

---

## 7. 入出力インターフェース早見(このfix群が触る境界)

| 境界 | 入力 | 出力 | canonical seam |
|---|---|---|---|
| 疾患 YAML → simulation | `reference_data/*.yaml` | `DiseaseProtocol`(属性)/ 生 dict(order) | `load_disease_protocol`(A)/ owner accessor(B、FP-YAML-3 で整備) |
| severity 決定 | `event.severity`(float)/ protocol 分布 | `"mild|moderate|severe"` + score | `severity_from_protocol`(FP-SEV-MODEL で新設) |
| age 参照 | `dob` + event 日 | as-of age(int) | `_age_on`(FP-AGE で `_shared` 昇格) |
| code → display | (system, code, lang) | display 文字列 | `code_lookup` / `system_key_for`(既存) |
| CIF → FHIR | structural + narrative CIF | FHIR R4 NDJSON | `_fhir_*` builders(registry 登録、既存) |
| completeness 検証 | cohort NDJSON | AxisResult | `clinosim/audit/axes/completeness.py`(FP-COMPLETENESS-GATE で新設) |
</content>
