# 歴史的 scratchpad アーカイブ

Repo root の `scratchpad/` からアーカイブされた作業ファイル —
特定過去 PR 調査に使用された byte-diff スクリプト、PR ごと監査
レポート、raw log。runtime または test path の一部ではない。

歴史的トレーサビリティのため保持: `*_results.md` の数値結果は
`bmp_cl_ca` / `cbc_bmp` / `coag_panel` / `hai` / `phase2a` /
`phase2b` / `phase3a` / `pr3` / `refactor_pr1-2` / `device` チェーン
の特定 merge 判断を裏付けた監査エビデンス。スクリプト (`*.py`) は
それらレポートを produce したツール。

ファイルは 2026-08-07 に repo-hygiene シリーズ (PR B of A-G) の
一環として移動された。repo root の `scratchpad/` ディレクトリは
現在 gitignored — 今後のメンテナ作業ファイルはそこに untracked で
存在する。

## 命名規約

- `<feature>_byte_diff.py` — PR ごと byte-diff generator
- `<feature>_byte_diff_results.md` — その generator の出力
- `<feature>_dqr_<country>.md` — Data-Quality Review markdown
- `<feature>_dqr_*.log` — DQR がサマライズする raw pytest / cohort
  出力
- `dqr_<name>_review.py` — adversarial レビュースクリプト

Live docs からの cross-reference なし。監査 findings のいずれかが
permanent documentation に昇格する必要が生じた場合、特定
`*_results.md` を `docs/reviews/` に移動し適切な archive
front-matter を追加する。
