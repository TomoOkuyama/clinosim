# docs/superpowers/

進行中ワークストリームの in-flight brainstorming / spec / plan
ファイル置き場。ここのファイルは進行中の PR で参照される作業
文書。

ワークストリームが ship する (PR merge、Issue close) と、その spec
と plan ファイルは `docs/history/{specs,plans}-archive/` に移動、
このフォルダを signal-heavy に保つ。

## レイアウト期待値

- ほとんどの時間空 — アクティブな作業のみ。
- ファイル名規約: `YYYY-MM-DD-<issue-or-topic>-{design,plan}.md`。
- 完了ファイル: `../history/{specs,plans}-archive/` に移動。

## 歴史的アーカイブ

2026-04 以降の全 spec + plan は以下に存在:

- `docs/history/specs-archive/` — 歴史的設計文書 (Issue #568 PR E
  時点で 66 ファイル)
- `docs/history/plans-archive/` — 歴史的実装 plan (Issue #568 PR E
  時点で 62 ファイル)

## 関連

- Issue #568 PR E (2026-08-09): 128 ファイルをここにアーカイブ。
