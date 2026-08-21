# 歴史的ドキュメント

トレーサビリティのために保存されているが、現在のシステム状態を
記述していない文書。新規 contributor はここから始めるべきではない
— [docs root](../index.ja.md) と
[`docs/getting-started/`](../getting-started/) 参照。

## 内容

- [`spec-2026-04.md`](spec-2026-04.md) — 2026 年 4 月に書かれた元の
  フルシステム仕様書 (「医療ダミーデータ生成システム 仕様書
  v0.3」)。[`DESIGN.md`](../../DESIGN.md) (アーキテクチャ + ADR
  表) と [`clinosim/modules/output/SPEC.md`](../../clinosim/modules/output/SPEC.md)
  (FHIR 出力仕様) に superseded された。
- [`des-migration-audit.md`](des-migration-audit.md) — discrete-event
  エンジン分割の pre-migration クリーンアップ監査。記述された
  refactor は完了 (`simulator.py` は `simulator/{engine,inpatient,
  outpatient,emergency,helpers,cli}.py` に分割済、
  `simulator/des_engine.py` 配置済)。設計継続性のため retained。
- [`session-prompts/`](session-prompts/) — メンテナの長期実行開発
  context 用の session ごと resume prompt。sub-README 参照。
- [`scratchpad-archive/`](scratchpad-archive/) — 過去の調査チェーン
  からの PR ごと byte-diff スクリプトと Data-Quality Review レポート。

ファイルは session 82 repo-hygiene シリーズ (PRs A-G) の一環として
このディレクトリに移動された。
