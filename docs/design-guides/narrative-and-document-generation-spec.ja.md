# ナラティブと文書生成 — 仕様

位置づけ: **規範**。臨床文書を計画する・セクションを足す・臨床事実をナラティブで言い表す・LLM に渡す事実を用意する変更は、すべて本書に従う。従えない変更は、同じ PR で理由とともに本書を改訂する。

英語版: [`narrative-and-document-generation-spec.md`](narrative-and-document-generation-spec.md)。

関連仕様と契約:
- 文書種別のコード(文書種別ごとの LOINC)と、あらゆる表示名: [`code-mapping-and-localization-spec.ja.md`](code-mapping-and-localization-spec.ja.md) §4.1。
- 2 段階 CIF(構造スタブの後にナラティブ。AD-65): [`clinosim/modules/output/SPEC.md`](../../clinosim/modules/output/SPEC.md)。
- ナラティブパスの決定性(走査順・時刻): [`determinism-and-rng-spec.ja.md`](determinism-and-rng-spec.ja.md) §7。

## 1. 原則

1. **一つの事実に一つの言い方。** 文章に読み込む臨床事実は一つの関数が言い表し、テンプレート経路と LLM 経路の両方がそれを呼ぶ。両経路の違いは言葉の使い方だけ(テンプレートは配置し、LLM は事実として受け取る)で、事実を別の言い方にしない。
2. **文書の判断は一か所。** 受診ごとにどの文書を作るかは、文書種別の生成頻度をキーにした一つの planner 表で決める。Composition の各セクションには登録済みの作成関数が一つある。
3. **表示と解釈を一致させる。** 値は表示どおり(先に丸めて)に分類し、印字した数値と横に書く区分・解釈が食い違わないようにする。
4. **規則には必ずガードがある。** 各規則はそれを強制するテストを示す。テストの無い規則は §5 に挙げる。

## 2. 文書とセクションの計画

| 規則 | 正準コード | ガード |
|---|---|---|
| 受診ごとの文書は `_PLANNERS[spec.generation_frequency]` で決める。頻度ごとに planner が一つある(入院時 1 回、毎日、3 交代、退院時 1 回、手術ごと …)。新しい頻度は表に planner を足して表す。表の外で計画する文書種別は無い。 | `clinosim/modules/document/engine.py::_PLANNERS` | `tests/unit/modules/document/test_document_planners_2532.py` |
| Composition の各セクションは `@section(name)` で登録した関数がちょうど一つ作る。同じ名前の二重登録は import 時に失敗する。ある文書種別だけ書き方が異なるセクションは、その種別の関数を `@section(name, document_type=...)` で登録し(文書種別とセクションの組ごとに一つ。例: 救急外来記録の評価)、描画は共通の関数よりそちらを優先する。Composition の描画はこの登録表からセクションを引く。 | `clinosim/modules/document/narrative/renderers/section_builders/_registry.py`(`section`, `section_builder`, `section_builders`, `document_section_builders`) | `tests/unit/modules/document/narrative/test_section_registry_2531.py`、`test_ed_note_protocol_2871.py::test_document_type_builders_name_a_section_of_that_document` |
| 文書のコンテキストは、その文書の受診で記録されたデータだけを持つ。記録のバイタル・検査結果・オーダー・投与・処置・終了時処方は記録の受診 (`encounters[0]`) に属する。記録の他の受診(予防接種 enricher が追加する接種受診)では、その受診の ID を持つか受診期間内の時刻を持つものだけを残し、他の受診のバイタルや処方を記載しない。 | `clinosim/modules/document/narrative/passes.py::scope_record_to_encounter` | `tests/unit/modules/document/narrative/test_vaccination_visit_own_data_2869.py` |
| 死亡で終わった入院(退院時転帰 `exp`)は一つの判定で見分け、planner(退院時サマリーに代えて死亡退院サマリーと死亡診断書)と、入院の終わりを言い表すすべてのセクションがそれを使う。この入院にも看護サマリーは残し、退院基準・患者指導・退院可能性の代わりに死亡確認時刻、家族への連絡、死後の処置を記す。最後の 2 日の経過記録の安定日フレーズは退院準備のプールではなく `terminal` プールから取る。 | `clinosim/modules/document/narrative/_narrative_utils.py::encounter_died` | `tests/unit/modules/document/narrative/test_death_stay_documents_2875.py` |
| LLM には `LLMService.complete_prompt` を通してのみ届く(AD-11)。 | `clinosim/modules/llm_service/` | `implementation-rules.ja.md` §2(レビュー) |

## 3. 臨床事実の言い表し

| 規則 | 正準コード | ガード |
|---|---|---|
| 薬剤安全上の事象(回避・保留・代替・切替・de-escalation)は、両経路とも一つの関数が言い表す。テンプレートでは計画の行(`safety_skips.*`)、LLM プロンプトでは箇条(`safety_skips_prompt.*`)になる。回避した薬剤は、それを外した規則の種類(判定の規則 id の `drug_safety.rule_kind`)で言い表す。記録済みのアレルギーはアレルギーとして書き(`avoid_allergy_*`、"not given: Penicillin allergy" / 「ペニシリンアレルギーのため…は投与せず」)、併用の衝突としては書かない。薬物間・薬剤と疾患の回避は `avoid_*` のフレーズのまま。 | `clinosim/modules/document/narrative/_safety_skips.py::safety_skip_line` | `tests/unit/modules/document/narrative/test_safety_skip_line_2519.py`, `test_safety_skip_event_types.py`, `test_allergy_skip_wording_2930.py` |
| バイタルの一行要約(身体所見、経過記録の O、看護記録、LLM の来院時・日々の事実)はすべて一つのフォーマッタで描く。各記述面はスタイル(項目順・区切り・単位・整数か生値か・室内気の表記)を名指しする。新しい記述面はスタイルを足し、フォーマッタを足さない。 | `clinosim/modules/document/narrative/_vitals_line.py::format_vitals_line`(スタイル `PHYSICAL_EXAM`, `PROGRESS_OBJECTIVE`, `NURSING_SHIFT`, `LLM_ARRIVAL`, `LLM_DAY`) | `tests/unit/modules/document/narrative/test_vitals_line_2523.py`, `test_narrative_spec_guards.py::test_vitals_lines_only_through_format_vitals_line`(他の書式文字列が 3 つ以上のバイタルを含まない。高血圧の管理状況のような単一バイタルの解釈と、LLM 向けの最小〜最大の範囲要約はバイタルの一行要約ではない) |
| BMI の区分(やせ・普通・過体重・肥満。WHO / 日本肥満学会の境界 18.5 / 25 / 30、境界値は上の区分)は、表示する値で一つの関数が決める。 | `clinosim/modules/document/narrative/_narrative_interpretation_thresholds.py::bmi_band` | `tests/unit/modules/document/narrative/test_narrative_spec_guards.py::test_bmi_bands_only_through_bmi_band`, `test_template_generator_nutrition_care_plan.py` |
| 血圧の区分(高血圧・正常高値・正常。JSH 2019 の診察室閾値 140/90 と 130/85、どちらか一方で判定)は一つの関数が決める。ナラティブの解釈の閾値は `_narrative_interpretation_thresholds.py` の名前付き定数とし、比較はそこでだけ行う。 | `_narrative_interpretation_thresholds.py::bp_band` | `test_narrative_spec_guards.py::test_blood_pressure_bands_only_through_bp_band`, `test_each_bp_boundary_belongs_to_the_upper_band` |
| `facts_used` のタグは、それが示す文章の出所を一つの語彙の接頭辞で名指す。構造 CIF の項目(`ctx.`, `patient.`, `encounter.`, `profile.`, `chronic.`, `physical_exam_findings`, `discharge_instructions`)、静的な参照データ(`disease_protocol.`, `encounter_protocol.`, `chief_complaint_variants.`)、CIF の状態から組み立てた文章(`composed:`)、静的なテンプレート(`generic:`, `outpatient_soap_template.`)のいずれか。語彙の外のタグは `check-narratives` が捏造された出所として報告する。 | `clinosim/modules/document/narrative/semantic_check.py::_ALLOWED_FACT_PREFIXES` | `tests/unit/modules/document/narrative/test_narrative_spec_guards.py::test_every_facts_tag_literal_is_in_the_facts_vocabulary`, `tests/integration/test_check_narratives_mock.py` |
| ナラティブの表示名(薬剤・検査・診断・診療科・文書種別)は、コードマッピング仕様の表示関数で解決する。 | `clinosim.codes.display`, `clinosim.locale.loader.lab_display` など | コードマッピング仕様 §10 |

## 4. 本書の対象外

- **測定値からの臨床コード付け**(BMI から E66 過体重・肥満コード、`modules/metabolic/engine.py` など)は診断の規則で、ナラティブの言い表しではない。そのモジュール自身の閾値に従う。

## 5. 未対応

既知のものは無い。新たな例外は、それを許すガードとともにここに記す。
