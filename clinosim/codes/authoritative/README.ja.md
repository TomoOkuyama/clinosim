# 権威コードシステム snapshot

権威コードシステム display の機械可読 snapshot。
`clinosim/codes/data/*.yaml` を元の terminology ソースに対して検証
するために使用。これらは **検証リファレンス** であり、source of
truth ではない — clinosim が emit する内容の source of truth は
`clinosim/codes/data/*.yaml` に留まり、これは小さな意図的な臨床
override を許容する (下の allowlist に登録)。

同伴ドキュメント: [`docs/design-guides/code-display-authoritative-sync.ja.md`](../../../docs/design-guides/code-display-authoritative-sync.ja.md)。

## ファイル

| File | Source | Fetched | Notes |
|---|---|---|---|
| `yj_tx_fragment.json` | `jpfhir-terminology 2.2606.0` / `CodeSystem-jp-medicationcodeyj-cs.json` (`http://capstandard.jp/iyaku.info/CodeSystem/YJ-code`) | 2026-07-19 | Fragment (tx-server 上 2000 concept)、clinosim が現在 emit する 9 コードにフィルタ。 |
| `loinc_2_82_tx.json` | LOINC 2.82 公式マスター (`Loinc_2.82/LoincTable/Loinc.csv`) を `tx-server-build/loinc-src/` 経由で | 2026-07-19 | clinosim emit の 167 コード; `display` (LONG_COMMON_NAME) + `short_display` (SHORTNAME) + `status` を含む。フル display cross-check は Issue #270 (Phase 3-b) で有効化 — 75 の正当略記 + 17 の追跡セマンティック mismatch override を allowlist に登録。 |

後続 snapshot (SNOMED / ICD-10 / MEDIS / BCP-47 / LOINC etc.) は
design guide で追跡され、各 Chain がフレームワークに移行するたびに
後続 PR で landing する。

## Content mode: `fragment`

各 snapshot はソース CodeSystem の `content` セマンティクスを継承。
`content == "fragment"` の場合、snapshot に無いコードでもソース
terminology 上では **valid でありうる** — tx-server の partial リス
ティングが単にそれを持たないだけ。cross-check テストは欠落コードを
*検証不能* (SKIP) として扱い、*invalid* (FAIL) とはしない。
`metadata.clinosim_codes_missing_from_fragment` フィールドが fragment
の外にある clinosim コードを正確に記録し、将来の snapshot refresh で
fetch を広げるかを判断できるようにする。

## Cross-check セマンティクス

権威 snapshot にエントリを持つ全 `(system, code)` ペアについて、
cross-check テストは clinosim-curated display が以下のいずれかに一致
することを assert:

- 権威 `display` (preferred term)、または
- 権威 `designation[].value` エントリのいずれか (synonym)、または
- ドキュメント化された臨床根拠を持つ override allowlist のエントリ。

Drift (curated display ≠ 権威 かつ allowlist に無し) は CI fail。
これは silent-no-op 防御の 5 層目。

## Refresh workflow

1. 最新の `../fhir-jp-validator/tx-server-build/` (または上流
   terminology パッケージ) を pull。
2. 抽出スクリプトを再実行 (per-code-system スクリプトを `scripts/`
   に配置、各 system の移行に伴い TBD)。
3. snapshot ファイルの diff を検査。
4. 変更エントリごと:
   - Now 一致 → curated データが既に正しく、clinosim 変更不要。
   - Now 一致、curated が古い → `clinosim/codes/data/*.yaml` を更新。
   - 意図的な divergence (臨床略記 override) → 臨床根拠付きで
     allowlist に追加。
5. PR: snapshot diff + allowlist / YAML 編集 + cross-check テスト
   refresh。

## ここに **属さない** もの

- 完全な CodeSystem 定義 (structure、filter、hierarchy) — これらは
  clinosim ではなく tx-server に存在。
- 権威ソースが持たない locale 翻訳 — これらは
  `clinosim/codes/data/*.yaml` の `ja` / 他言語キー下に存在し、
  clinosim-curated と見なされる (上流に対する検証不可)。
- clinosim が決して emit しないコード — fragment は shipped snapshot
  を小さく保つため clinosim の emit surface に意図的にスコープ限定。
