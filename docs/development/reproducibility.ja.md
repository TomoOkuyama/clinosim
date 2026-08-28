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

## クロスプラットフォーム byte-identity (v0.5.0+)

上記不変条件は **同じ CPU アーキテクチャ内** の byte-identity を保証する
(Mac ARM 2 runs 同一、x86 Linux 2 runs 同一)。**アーキテクチャ跨ぎ** の
identity には追加保証が必要 — sampling アルゴリズム内部の transcendental
関数が全プラットフォームで同一に丸められること。`numpy.random.Generator.beta`
/ `.normal` / `.exponential` は `libm` の `log` / `exp` / `pow` / `cos` を
経由し、IEEE 754 は基本演算 + `sqrt` に対してのみ正しい丸めを保証する
— transcendental は対象外。Apple Silicon と glibc の `libm` は末尾数 ULP
で異なり、この 1 ULP shift が numpy RNG cursor を全下流サンプリングで
ずらす。

v0.5.0 以降、clinosim は `clinosim.determinism` を提供 — 前述 3 variate の
bit-identical drop-in で、以下 2 primitive のみに依存する:

- `rng.random()` (numpy PCG64 の整数演算)
- `mpmath.{log, exp, cos}` at 128-bit precision (pure Python 整数演算)

小さな proxy が simulator entry で `np.random.default_rng(seed)` を wrap
し、下流 call site は `rng.beta(...)` API のまま。**user 操作不要** —
module は default で有効。

Mac ARM (macOS 26、Python 3.12.7、numpy 2.5.1、mpmath 1.3.0) vs H100
x86 Ubuntu (Python 3.12.3、numpy 2.5.2、mpmath 1.4.1) で再生成検証: US
p=100 s=42 → 24/24 file 一致、US p=500 s=42 → 25/25 file 一致。詳細は
[`docs/reviews/2026-08-28-cross-platform-determinism.md`](../reviews/2026-08-28-cross-platform-determinism.md)
を参照。

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
