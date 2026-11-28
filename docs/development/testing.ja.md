<!-- README.md から抽出 (Issue #568 PR A2)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# テスト

```bash
source .venv/bin/activate

# 全テスト (unit ~1 min, integration ~30 min, e2e ~8 min)
pytest -x

# カテゴリ別
pytest -m unit                   # `unit` マーク付きテスト (~5200 ケース。tests/unit/ 配下は ~5600 test 関数、~7700 collected ケース)
pytest -m integration            # cross-module (reproduce.sh gate 含む)
pytest -m e2e                    # E2E + golden テスト

# カバレッジ
pytest --cov=clinosim
```

### 再現性

clinosim は所与の `(seed, config, country, start, end, population)`
タプルに対して **byte-identical 出力** を MINOR release line 内で
保証します — 壁時計 / git 依存メタデータ (`fhir_r4/manifest.json` /
`fhir_r4/_generator_metadata.json` / `cif/metadata.json` /
narrative-pass `manifest.json`) は差分あり想定、
それ以外は完全一致でなければなりません。

いつでも検証:

```bash
bash scripts/reproduce.sh
```

スクリプトは locale ごと (デフォルト US + JP。JP は `--allow-legacy`
付きなので JP-CLINS パッケージ不要) に
`clinosim simulate --format fhir` を 2 つの分離した temp ディレクト
リへ 2 回実行、各 NDJSON + CIF JSON を sha256 化し、hash リストを
diff します。exit 0 = byte-identical、exit 1 = 決定性回帰 (該当
ファイル名が diff に出力)。環境変数 `CLINOSIM_REPRO_COUNTRIES` /
`CLINOSIM_REPRO_POPULATION` / `CLINOSIM_REPRO_SEED` /
`CLINOSIM_REPRO_START` / `CLINOSIM_REPRO_END` でデフォルトを上書き
可能。

CI は全 push + PR で `tests/integration/test_full_reproducibility.py`
(integration ジョブ) 経由で実行し、`nightly.yml` の `reproducibility`
job も毎日実行するので、回帰がコードのランド前に merge gate を trip
します。

### リファクタリングの検証 (`scripts/refactor-diff.sh`)

リファクタリングは出力を一切変えてはならず、その証明は移したコードが実際に
実行された実行結果でしか成り立ちません。数百人のコホートは、1000 入院に 1 回
しか通らない経路に一度も到達しないまま byte-identical になり得ます。次の 3 つで
検証します (Issue #3976)。

- **強制シナリオのコーパス** — `tests/refactor_corpus/scenarios.yaml`: リファクタ
  リングで移しうる経路ごとに 1 つの強制入院 (合併症アクションの各種別、昇圧薬の
  開始、DKA の皮下注への移行、高カリウム血症 / AKI / 腎代替療法 / 乳酸への対応、
  各退院基準、院内感染、分娩様式、救急外来経由の入院) を US と JP で生成します。
  `run_forced` の上に作られ、合併症はテスト専用の
  `ForcedScenario.force_complications` で指定日に発症させます (これを読むのは
  `run_forced` だけです)。`tests/refactor_corpus/run_corpus.py` が生成します
  (CIF、テンプレート narrative、FHIR R4。シナリオごとに 1 ディレクトリ)。
- **発火カウンタ** — `clinosim/fired_counters.py`: 各経路が作用する箇所に
  `count("<path>")` を 1 つ置きます。カウンタは乱数を消費せず、CIF にも FHIR に
  も書かれず、実行の開始ごとにリセットされます。ランナーが出力ツリーの外の JSON
  サイドカーに書き出します。各シナリオは発火すべき経路を `expect` に列挙し、
  1 つでも発火しなければ `run_corpus.py check` が失敗します。
- **比較** — `scripts/refactor-diff.sh <base> <head>` は 2 つのコミットを
  detached worktree に展開し、それぞれでコーパスと US / JP コホート (seed 42、
  人口は既定 200・上限 300、2025-07-01..2026-06-30、CIF と FHIR) を生成し、全
  ファイルを比較し (ログ、`_generator_metadata.json`、メタデータファイルの壁時計
  キーを除く)、差分と両コミットの発火カウンタを表示します。差分があるか、
  `<head>` で期待された経路が発火しなければ非ゼロで終了します。

```bash
scripts/refactor-diff.sh origin/master HEAD   # ノート PC で約 3 分
```

コーパス定義とランナーは `<head>` のものを両方のコミットに対して実行するので、
両者は同じシナリオを生成します。`<base>` はコーパスを含んでいる必要があります
(発火カウンタの無い base はカウンタ列に `-` を表示します)。CI ワークフロー
`refactor-diff.yml` は `refactoring` ラベルの付いたプルリクエストごとに、merge
base に対してこのスクリプトを実行します。リファクタリング PR は移す経路を挙げ、
その回数を引用します (「経路 X はコーパスで N 回、US コホートで M 回、JP コホート
で K 回発火し、両コミットで同一」)。0 回の経路は証明されていないので、先にそれ
を発火させるシナリオを追加します。

---
