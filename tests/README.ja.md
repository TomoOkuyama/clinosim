# tests/ の規約

`clinosim` のテストスイートの基準文書。ここにあるのは規則のみで、理由は各リンク先の
後続ドキュメントにある。規則とこのファイルが食い違う場合はこのファイルが優先する。
英語版 [`README.md`](README.md) と内容を揃えて保つこと。

## ディレクトリ構成 — `clinosim/` をミラーする

`tests/` 配下のパスは `clinosim/` 配下のパスをミラーする。

| テストファイル                           | 対象                                  |
| ---------------------------------------- | ------------------------------------- |
| `tests/unit/output/test_foo.py`          | `clinosim/modules/output/foo.py`      |
| `tests/unit/simulator/test_bar.py`       | `clinosim/simulator/bar.py`           |
| `tests/integration/test_baz_chain.py`    | `clinosim/` の複数モジュールにまたがる連鎖 |

トップレベルの `tests/unit/*.py` は旧来の領域である (Issue #567 のレイアウト整理を参照)。
**新しいテストはミラーされたサブディレクトリに置く**。`clinosim/modules/<module>/` には
`tests/unit/modules/<module>/`、それ以外のパッケージには `tests/unit/<package>/`、複数モジュールに
またがる連鎖には `tests/integration/` を使う。`tests/unit/` 直下に新しいファイルを追加しない。

ガード `tests/unit/docs/test_test_layout_guard.py` がこれを強制する。`tests/unit/test_*.py` 直下のファイル数と、
ローカルの `_patient`・`_stay`・`_record` ビルダーの数を現状で凍結する
(合計と内容キーは `tests/unit/layout_ratchet_baseline.json` にあり、形式は
`tests/unit/ratchet_baseline.py` の共有ラチェット形式)。直下に新しいファイルを足す、または
ローカルビルダーを新設するとテストが失敗し、使うべきディレクトリまたは fixture が表示される。
ファイルをミラー先のディレクトリへ移すことは新規追加とは数えず、削除にベースライン編集は不要である。
合計は `python -m tests.unit.layout_ratchet --write` で下げる (nightly ジョブまたはメンテナが実行し、
機能変更の中では行わない)。

## 1 つのモジュールのテストを実行する

1 つのモジュールのテストは複数の場所に分かれている: `tests/unit/<m>/`、`tests/unit/modules/<m>/`、
`tests/modules/<m>/`、直下の `tests/unit/test_*<m>*.py`、`tests/simulator/`、`tests/integration/`。
次の 1 コマンドで全てを実行できるので、どこに存在するかを知る必要はない。

```bash
python -m pytest tests/unit tests/modules tests/simulator tests/integration -k <m> -q -n 3
```

`<m>` は `clinosim/modules/` 配下のモジュールディレクトリ名 (例: `drug_safety`)。`-k` はテストの
ファイル名・ディレクトリ名・クラス名・関数名に対する大文字小文字を区別しない部分一致なので、短い名前は
それを含む他のテストも選ぶ (`hai` は `hai` モジュール以外にも一致する)。また名前に含まれない
モジュールのテストは選ばれない。必要に応じて `-k "<m> or <関連語>"` で組み合わせる。ツリー全体の収集には
最初のテストが走るまでに約 16 秒かかる。省くには、そのモジュールに存在するディレクトリだけ
(`ls -d tests/unit/<m> tests/unit/modules/<m> tests/modules/<m>` で確認) を `python -m pytest` に渡す。

14 コアの Mac で `-n 3` (スレッド変数は 1) として測定した値:

| モジュール | テストがあるディレクトリ | コマンド | テスト数 | 実時間 |
| --- | --- | --- | --- | --- |
| `drug_safety` | `tests/unit/drug_safety/`、`tests/unit/modules/drug_safety/`、`tests/modules/drug_safety/`、直下のファイル、`tests/integration/` | 上記コマンドの `-k drug_safety` | 328 | 20.9 秒 |
| `drug_safety` | 上の 3 ディレクトリのみ | `python -m pytest tests/unit/drug_safety tests/unit/modules/drug_safety tests/modules/drug_safety -q -n 3` | 242 | 3.6 秒 |
| `immunization` | `tests/unit/modules/immunization/`、直下のファイル、`tests/integration/` | 上記コマンドの `-k immunization` | 343 | 23.7 秒 |
| `immunization` | 1 つのディレクトリのみ | `python -m pytest tests/unit/modules/immunization -q -n 3` | 248 | 4.8 秒 |

ディレクトリのみの形式は速いが、直下のファイルと integration のテストを含まない。プルリクエストを出す前には
完全なコマンドを実行すること。CI は変わらず全ディレクトリを実行する。

## マーカー方針 — パスが正

現状の pytest マーカー (`unit` 約 745 件、`integration` 約 221 件) は飾りである。CI はマーカーではなく
ディレクトリ (`tests/unit/**` → unit など) で選択する。モジュールごとの
`pytestmark = pytest.mark.unit` の定型句は追加しない (ディレクトリが同じ事実を表す)。
マーカーはパスで表せない横断的な選択にだけ使う。

## マーカーの語彙

`pyproject.toml [tool.pytest.ini_options] markers` で宣言する。

| マーカー      | 意味                                                               |
| ------------- | ------------------------------------------------------------------ |
| `unit`        | 高速、fixture 以外のファイルシステムを使わない                     |
| `integration` | 複数モジュールの連鎖、tmp ファイルシステムを使ってよい             |
| `e2e`         | シミュレーション全体の実行、低速                                   |
| `regression`  | AD-66 α-min narrative regression スイート (opt-in)                 |
| `serial`      | 共有ファイルシステム/グローバル状態を変更する — xdist は単一ワーカーで実行 |

`slow` はマーカーではない。シャーディングはマーカーではなく `.test_durations` による実行時間ベースで行う。
PR の CI は unit と integration のスイートを、`scripts/ci_split_by_file.py` でテストファイル単位の
シャードに分割する (ファイルの重みは `.test_durations` 内のそのテスト群の実行時間の合計で、
ファイルは長い順に最も負荷の小さいシャードへ詰める)。`pytest.mark.slow` は追加しない。

同じファイルに `unit` と `integration` のマーカーを混在させない。integration のケースは
`tests/integration/` に置く。

## Fixture 方針

- **患者 fixture**: 新しいテストで `PatientProfile` を作るには、標準の `patient_factory` fixture
  (`tests/conftest.py`、Issue #567 で追加) を使う。`tests/fixtures/patient_profiles/` の 6 つの YAML
  プロファイルには `load_patient_profile(profile_id)` を使う (ローダーは現在 `tests/regression/` に限定、
  unit からの利用は Issue #567 の後続対応待ち)。新しいローカルの `_patient()`・`_stay()`・`_record()` ヘルパーを
  追加してはならない (上記のレイアウトガードが新規追加を失敗させる)。既存の重複は後続 PR で移行する。
- **Bundle-context**: `BundleContext` が必要な integration テストでは、`tests/integration/_sr_helpers.py` の
  共有ビルダーを使う。
- **国/ロケール**: 既定は US (`AGENTS.md § Country / locale convention` に従う)。JP 固有の fixture は
  `is_jp(country)` で分岐し、コホート生成には環境変数 `CLINOSIM_JP_CLINS_PKG_DIR` が必要。

## 数値許容誤差

`abs(x - y) < eps` より `pytest.approx(value, abs=…)` を優先する。複数のテストが同じ不変条件
(例: 「分布の合計は 1」) を検証する場合は、ファイル間で**同じ**許容誤差を使う。合計 1 の既定の絶対
許容誤差は `1e-9` で、正当な理由なしに緩めない。

後続 (Issue #567 関連): `tests/_numerics.py` が `assert_sums_to_one(seq, atol=1e-9)` と
`assert_close(a, b, rel_tol=1e-9)` を公開する予定。入ったらそちらへ移行する。

## アサーションメッセージ

`assert x, "msg"` は、失敗した行だけでは何の不変条件か分からない場合にだけ付ける。自明なアサーション
(`assert result == expected`) にはメッセージを付けない (pytest が十分な差分を出す)。

## `.test_durations` の更新

リポジトリ直下の実行時間ファイルが PR CI のシャード分割を決める (`scripts/ci_split_by_file.py` が
テストファイルごとに合計する)。nightly ワークフロー (`.github/workflows/nightly.yml`) が `ci.yml` と
同じ構成でシャードごとに測定し、更新用の PR を作成 (または更新) する。この PR は `GITHUB_TOKEN` で
作られるため、その `pull_request` の実行 (`ci.yml`、`dco.yml`) は承認待ちになる。nightly ジョブが
これらを承認し (トークンに承認権限がない場合は、承認の代わりにブランチ上で両ワークフローを起動し)、
auto-merge を設定する。チェックが通ればメンテナの作業なしに更新が入る。
エントリのない新しいテストファイルは、次の nightly 実行まで平均的なファイルの重みで扱われるので、
PR 自身がこのファイルを更新する必要はない。

## 関連バックログ

- **レイアウト整理** (トップレベル → ミラー): Issue #567
- **`patient_factory` fixture**: `tests/conftest.py` に追加済み (Issue #567)
- **`_patient()` ヘルパーの移行** (既存の別々の複製 → 標準 fixture): Issue #567 後続
- **unit での `load_patient_profile(profile_id)` 公開** (現在は `tests/regression/` に限定): Issue #567 後続
- **数値許容誤差ヘルパーモジュール**: Issue #567 後続
- **マーカー強制 `conftest.py`** (パスから自動付与): Issue #567 後続

後続のいずれかが入ったら、上の該当節を更新する。
