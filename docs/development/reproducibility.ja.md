# 再現性

clinosim は所与の `(seed, config, country, start, end, population)`
タプルに対して **byte-identical 出力** を MINOR release line 内で保証
します — 壁時計メタデータ (`fhir_r4/manifest.json` /
`cif/metadata.json` / narrative-pass `manifest.json`) は差分あり想定、
それ以外は完全一致でなければなりません。

## いつでも検証

```bash
bash scripts/reproduce.sh
```

スクリプトは locale ごと (デフォルト US + JP) に
`clinosim simulate --format fhir` を 2 つの分離した temp ディレクト
リへ 2 回実行、各 NDJSON + CIF JSON を sha256 化し、hash リストを
diff します。exit 0 = byte-identical、exit 1 = 決定性回帰 (該当
ファイル名が出力)。

## 環境変数 override

| 変数 | デフォルト |
|---|---|
| `CLINOSIM_REPRO_COUNTRIES` | `US JP` |
| `CLINOSIM_REPRO_POPULATION` | `50` |
| `CLINOSIM_REPRO_SEED` | `42` |
| `CLINOSIM_REPRO_START` | `2026-01-01` |
| `CLINOSIM_REPRO_END` | `2026-03-31` |
| `CLINOSIM_REPRO_KEEP_OUTPUT` | (未設定) — 成功時 temp dir を残すなら設定 |

## CI 強制

[`.github/workflows/ci.yml`](https://github.com/TomoOkuyama/clinosim/blob/master/.github/workflows/ci.yml)
の `reproducibility` ジョブが全 push + PR に対して
`scripts/reproduce.sh` を実行。決定性回帰があればコードがランドする
前に merge gate を trip。

## 基礎となる不変条件

[AD-16](../reference/design.md) より:

- 各モジュールは master seed から sub-seed を派生; `random.random()`
  やグローバル RNG state 禁止。
- Per-order lab RNG isolation (AD-59): 検体拒否 / 溶血 / 技師 /
  ノイズは per-order sub-RNG なので、あるパネルの YAML 編集が無関係
  患者のコホートをシフトさせられない。
- seeded code path を触る全 commit は merge 前に
  `bash scripts/reproduce.sh` で検証必須。

## 決定性が壊れたとき

`scripts/reproduce.sh` が回帰を報告したら:

1. diff を読む — 該当ファイル名と `+/-` sha256 行が出力される。
2. 2 つの temp 出力を直接 diff して実コンテンツ差を確認
   (`export CLINOSIM_REPRO_KEEP_OUTPUT=1` して再実行)。
3. 最頻の原因は Python 組み込み `hash()` の文字列適用
   (`PYTHONHASHSEED` によるソルト) — `hashlib.sha256(...).hexdigest()`
   に置換。session 46 P1-7 で immunization モジュールの synthetic
   lot 番号生成器がまさにこの欠陥を持っていた。

追加背景:
[feedback / determinism ストーリー](https://github.com/TomoOkuyama/clinosim/blob/master/CHANGELOG.md)。
