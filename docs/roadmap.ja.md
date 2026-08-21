# ロードマップ

**clinosim** の正式なロードマップは GitHub 上にあります:

- **Open work**: [`gh issue list --state open`](https://github.com/TomoOkuyama/clinosim/issues) — 予定される全ての変更をここで追跡。
- **優先度**: ラベルで絞り込み
  ([`priority:high`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Apriority%3Ahigh)、
  [`priority:medium`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Apriority%3Amedium)、
  [`priority:low`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Apriority%3Alow))、
  または領域で絞り込み
  ([`data-quality`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Adata-quality)、
  [`refactor`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Arefactor)、
  [`oss-hygiene`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Aoss-hygiene)、
  [`fhir`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Afhir)、
  …)。
- **最近完了した項目**: [CHANGELOG](https://github.com/TomoOkuyama/clinosim/blob/master/CHANGELOG.md) 参照。

設計ノートとアーキテクチャ判断は
[`docs/design-notes/`](https://github.com/TomoOkuyama/clinosim/tree/master/docs/design-notes)、
安定化したものは
[`docs/architecture/`](https://github.com/TomoOkuyama/clinosim/tree/master/docs/architecture)。
session 単位の履歴プロンプトは
[`docs/history/session-prompts/`](https://github.com/TomoOkuyama/clinosim/tree/master/docs/history/session-prompts)
にアーカイブ。

## ロードマップへの貢献

- 新規項目は適切なラベルを付けた GitHub Issue を open してください。
- 実装する design note や PR は Issue 番号を参照してください — 静的
  ファイルでステータスを重複させることなくロードマップとコードを
  接続します。
- PR フローは
  [CONTRIBUTING.md](https://github.com/TomoOkuyama/clinosim/blob/master/CONTRIBUTING.md)
  参照。
