# Design Guides — 新規モジュール著者のための読書パス

clinosim にモジュールを追加する新規開発者/実装 AI 向けの索引です。以下の順に読んでください。
(0)〜(4) は全員必読、(5)〜(7) は触る領域に応じて読みます。

| # | ドキュメント | いつ読むか |
|---|---|---|
| 0a | [`project-concept-and-design.md`](project-concept-and-design.md) | **一番最初**。プロジェクトのコンセプト(9 要求)・パイプライン全体像・ナラティブ 2 層設計・現在地とロードマップのキャッチアップ |
| 0b | [`implementation-rules.md`](implementation-rules.md) | **コードを書く前に必ず**。全実装者が守る不変則の蒸留版(workflow 規律 / 決定性 / canonical helpers / silent-no-op 防御 / 検証 gate) |
| 1 | [`MODULES.md`](../../MODULES.md) | 全 30 module(`clinosim/modules/` 配下の package)の俯瞰・依存関係・データフローを 1 ページで把握する |
| 2 | [`docs/CONTRIBUTING-modules.md`](../CONTRIBUTING-modules.md) | 実装前に。Base/Module 判定、正準 layout、loader / sub-seed / registry / 検証 (byte-diff vs DQR) の実践 playbook |
| 3 | [`.github/TEMPLATE_MODULE_README.md`](../../.github/TEMPLATE_MODULE_README.md) | モジュールの skeleton を作るとき。README + パス定数などの boilerplate をここからコピーする |
| 4 | [`DESIGN.md`](../../DESIGN.md) の curated ADR | 設計判断の背景が必要なとき。まず AD-16 / AD-17 / AD-25 / AD-30 / AD-55 / AD-56 / AD-59 / AD-60 / AD-65 の 9 つ(一言サマリは CONTRIBUTING-modules.md「最初に読む ADR」参照)|
| 5 | [`clinosim/modules/output/SPEC.md`](../../clinosim/modules/output/SPEC.md) | 臨床文書 / narrative を触るときのみ。two-pass CIF(structural + narrative 分離、AD-65)の canonical spec |
| 6 | [`docs/design-guides/fhir-data-generation-logic.md`](fhir-data-generation-logic.md) | FHIR builder(`_fhir_*.py`、Layer 4)を追加・拡張するときのみ。code_lookup / URI / multilingual / anti-patterns |
| 7 | [`SCENARIO_FLAGS.md`](../../SCENARIO_FLAGS.md) | lab 値や scenario / medication flag(`causes_X` / `on_warfarin`)を触るときのみ。flag の一覧と追加手順 |
| 8 | [`data-model-and-completeness-conventions.md`](data-model-and-completeness-conventions.md) | FHIR completeness fix-point(重症度統合 / 孤児 YAML キー / `extra="forbid"` / I10 stage / person.age / course_archetypes)を実装するときのみ。C1/C2/C3 不完全状態の禁止規約と as-of-age パターン。台帳 = `docs/design-notes/2026-07-06-fix-point-registry.md` |
