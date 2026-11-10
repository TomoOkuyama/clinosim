# Design Guides — 規則と仕様の所在

人とエージェントを問わず、すべての貢献者のための design guides の索引。3 部構成で、すべての変更に適用されるコーディング規則、シミュレータの領域ごとの binding spec、オンボーディング用の背景資料からなる。ガイドとコードが食い違ったら同じ PR でどちらかを直す — ガイドは正しくあるべきものである。

## 1. コーディング規則(コードを書く前に読む)

| 文書 | 内容 |
| --- | --- |
| [`CONTRIBUTING.ja.md` のコーディング規則](../../CONTRIBUTING.ja.md#コーディング規則) | すべての貢献者が従う 5 つの規則(コードとデータの分離・多言語出力・コード・国の扱い・決定性)。各規則から binding spec へリンク。 |
| [`implementation-rules.ja.md`](implementation-rules.ja.md) | **ここから読む。** すべての変更が従う規則(workflow・コーディング標準・アーキテクチャ不変則・決定性・正準ヘルパー・loader・検証 gate・silent-no-op 防御)と、関心事ごとの binding spec への対応表。 |
| [`shared-helpers-catalog.ja.md`](shared-helpers-catalog.ja.md) | X にどの共通ヘルパーを使うか。モジュール横断のヘルパーを関心事別に、パスと governing spec 付きで一覧にしたもの。小さな処理を書く前に引く。 |
| [`documentation-and-code-quality-policy.ja.md`](documentation-and-code-quality-policy.ja.md) | 文書の言語と EN/JA の対、自己完結した OSS 品質、ソースコメントの言語、定数の置き場所、dead code の扱い。 |

## 2. Binding specs(変更する領域の spec を読む)

各 spec は規則・それを実装する正準コード・それを強制するガードテストを示す。その領域の変更は spec に従うか、同じ PR で spec を改める。

| こういう変更の前に | Spec |
| --- | --- |
| コード・表示名・コード対応・名称解決関数・多言語化・fallback を足す/変える | [`code-mapping-and-localization-spec.ja.md`](code-mapping-and-localization-spec.ja.md) |
| 乱数を引く・シードを導く・時計を読む | [`determinism-and-rng-spec.ja.md`](determinism-and-rng-spec.ja.md) |
| 参照データ YAML・年齢区分の表・定数を足す/読む | [`configuration-and-reference-data-spec.ja.md`](configuration-and-reference-data-spec.ja.md) |
| 薬剤をオーダー・保留・投与・中止・処方・コード化する | [`medication-lifecycle-spec.ja.md`](medication-lifecycle-spec.ja.md) |
| 検査をオーダー・導出・フラグ付け・結び付けする | [`lab-orders-and-results-spec.ja.md`](lab-orders-and-results-spec.ja.md) |
| 文書を計画する・セクションを足す・臨床事実を言い表す | [`narrative-and-document-generation-spec.ja.md`](narrative-and-document-generation-spec.ja.md) |
| 受診を作る/終える・スナップショットを当てる・FHIR リソースを仕上げる | [`encounter-lifecycle-and-export-spec.ja.md`](encounter-lifecycle-and-export-spec.ja.md) |
| FHIR 完全性の修正(読まれない YAML キー・消費されない要素・`extra="forbid"`・病期・as-of 年齢)を実装する | [`data-model-and-completeness-conventions.ja.md`](data-model-and-completeness-conventions.ja.md) |
| コード表示名を権威ある出典(LOINC・YJ・ICD-10・厚労省の表)と同期する | [`code-display-authoritative-sync.ja.md`](code-display-authoritative-sync.ja.md) |

## 3. 背景とオンボーディング

| 文書 | いつ読むか |
| --- | --- |
| [`project-concept-and-design.ja.md`](project-concept-and-design.ja.md) | 最初に。プロジェクトのコンセプト(9 要求)・パイプライン全体像・ナラティブ 2 層設計。 |
| [`data-generation-walkthrough.ja.md`](data-generation-walkthrough.ja.md) | コンセプトの次に。1 件の患者データが population から CIF・FHIR まで生まれる流れを、実ファイル/関数名つきで追う。 |
| [`MODULES.ja.md`](../../MODULES.ja.md) | モジュールの地図。`clinosim/modules/` 配下の全 package・依存関係・データフロー・enricher の順序。 |
| [`docs/CONTRIBUTING-modules.ja.md`](../CONTRIBUTING-modules.ja.md) | モジュールを足す前に。Base / Module 判定・正準 layout・loader / sub-seed / registry の使い方・検証(byte-diff と audit)。 |
| [`.github/TEMPLATE_MODULE_README.md`](../../.github/TEMPLATE_MODULE_README.md) | モジュールの skeleton を作るとき。README とパス定数の boilerplate。 |
| [`fhir-data-generation-logic.ja.md`](fhir-data-generation-logic.ja.md) | FHIR builder(`clinosim/modules/output/fhir_r4/<theme>/`)を足す・拡張するとき。表示の規則は code-mapping spec が優先。 |
| [`clinosim/modules/output/SPEC.md`](../../clinosim/modules/output/SPEC.md) | 臨床文書・narrative を触るとき。two-pass CIF(structural + narrative、AD-65)。 |
| [`SCENARIO_FLAGS.ja.md`](../../SCENARIO_FLAGS.ja.md) | 検査値や scenario / medication flag(`causes_X`、`on_warfarin`)を触るとき。 |
| [`docs/architecture/adr-history.md`](../architecture/adr-history.md) | 設計判断の背景が必要なとき(ADR AD-1〜AD-71)。 |

現行でなくなった過去の計画は [`docs/history/`](../history/) にある。

English counterpart: [`README.md`](README.md).
