# docs/

`clinosim` ドキュメントフォルダのランディングページ (Issue #568)。

完全なドキュメントサイトは
<https://tomookuyama.github.io/clinosim/> で公開しています。この
README は GitHub フォルダビュー用の伴走ファイル — 各サブディレクトリ
の内容と最初に開くべきファイルの地図です。

## ユーザー向け

clinosim の評価・利用を検討中ならここから:

- **[getting-started/](getting-started/)** — インストール、初回
  コホート生成、30 秒スモークテスト。
- **[getting-started/configuration.md](getting-started/configuration.md)** —
  CLI フラグと環境変数の完全リファレンス。
- **[getting-started/first-cohort.md](getting-started/first-cohort.md)** —
  FHIR 出力の読み方、生理駆動の PT-INR ウォークスルー。
- **[index.md](index.md)** — トッププロジェクト概要 (docs サイトの
  landing page と同内容)。
- **[eval.md](eval.md)** — `clinosim eval` フレームワーク: 何をスコア
  し、レポートをどう解釈するか。
- **[eval-rules.md](eval-rules.md)** — eval エンジンが強制する軸別
  ルール。
- **[jp-clins.md](jp-clins.md)** — 日本 Clinical Information Sharing
  (JP-CLINS) プロファイル対応と JP コホートが US とどう異なるか。
- **[roadmap.md](roadmap.md)** — 今後の作業を追跡する GitHub Issues
  へのポインタ (canonical ライブビュー; 本ファイルはスタブ)。
- **[clinical_documents.md](clinical_documents.md)** — clinosim が
  生成する文書種別と CIF での位置。
- **[fhir-server-ingestion.md](fhir-server-ingestion.md)** — clinosim
  出力を HAPI / IRIS / 他の FHIR サーバーに投入。
- **[synthea-comparison.md](synthea-comparison.md)** — clinosim と
  [Synthea](https://synthetichealth.github.io/synthea/) の違いと
  使い分け。
- **[benchmarks.md](benchmarks.md)** — コホートサイズ / seed / ランタイム
  ベンチマーク。
- **[add-your-country.md](add-your-country.md)** — 新規国追加
  (US-Core / USCDI 等) の提案テンプレート。

## コントリビュータ向け

- **[../AGENTS.md](../AGENTS.md)** — 正式なエージェント + コントリ
  ビュータ向け指示。**PR を開く前に必ずこれを読むこと。**
- **[../CONTRIBUTING.md](../CONTRIBUTING.md)** — 人間向け PR
  ワークフロー、DCO サインオフ、CI マトリクス。
- **[CONTRIBUTING-modules.md](CONTRIBUTING-modules.md)** — 新規
  モジュールが従うべきモジュール境界ルール (AD-55/AD-56)。
- **[design-guides/](design-guides/)** — 長文の設計ガイド。
  `AGENTS.md` が深掘りとしてリンクする project-concept と
  implementation-rules を含む。
- **[design-notes/](design-notes/)** — 特定の判断に紐づく小規模
  設計メモ。
- **[reference/](reference/)** — 安定した小規模リファレンス
  (定数、テーブル、外部システム URL)。
- **[development/](development/)** — リリース / 公開 / 開発
  runbook (例: `publishing-to-pypi.md`)。
- **[governance/](governance/)** — プロジェクトガバナンスモデル。

## 作業メモ

これらのフォルダは進行中および過去のアーティファクトを保持しま
す。最近の作業を確認したいコントリビュータはここに着地します。
安定したリファレンスを探す読者は **ここから開始すべきではありません**。

- **[audit-cycles/](audit-cycles/)** — cycle 別の監査レポート
  (session-N アーティファクト) + by-design レジストリ。
- **[reviews/](reviews/)** — 特定変更に対するデータ品質レビュー
  出力; 履歴。
- **[superpowers/](superpowers/)** — 大規模変更の進行中 + アーカイブ
  済 plan + spec ファイル (agents 駆動計画アーティファクト)。

## アーカイブ

- **[history/](history/)** — 引退したアーティファクト: 旧
  scratchpad コード、初期 PoC ファイル、置き換えられた設計。
  reflog のために保持; コントリビュータが読む必要はありません。

## このフォルダに **ない** もの

- **Root README** — `../README.md` / `../CHANGELOG.md` / `../DESIGN.md`
  (大規模、mixed audience — 分割中、Issue #568 参照)
- **モジュール別ドキュメント** — `../clinosim/modules/` 配下の各
  モジュールは独自の `README.md` を持ち、入出力とモジュール固有の
  不変条件を記述。
- **テスト規約** — `../tests/README.md` (Issue #566 で追加)。

## このドキュメントへの貢献

`AGENTS.md § Documentation naming rule` のファイル接尾辞規則に従う:
英語がデフォルト (接尾辞なし)、日本語 variant は `*.ja.md`。新規
ユーザー向けドキュメントは `reference/` 配下、新規設計ノートは
`design-notes/` 配下、新規アーキテクチャガイドは `design-guides/`
配下に追加。
