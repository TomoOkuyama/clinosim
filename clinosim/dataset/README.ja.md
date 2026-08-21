# `clinosim.dataset` — 名前付きプリセットデータセットビルダー

## 目的

`clinosim.dataset` は名前付きプリセット (`jp-100` / `us-1000` …) を
対応する `clinosim generate` 呼び出しに変換する薄い CLI ラッパーで
す。ユーザーが 6 つのフラグを覚える代わりに 1 つの短いコマンドを実行
すれば、そのプリセットが再現可能なリリースとなるように存在します。

プリセットは **データセットリリースの版付き公開 API** です。新規プリ
セット追加は、国 / 人口 / seed / 日付範囲 / 出力形式の新しい公式
サポート組合せをメンテナが宣言する方法です。

## スコープ

- **In scope**: プリセット発見 (`list_presets`)、プリセットロード
  + バリデーション (`load_preset`)、`DatasetPreset` 値型、argv 変換
  (`DatasetPreset.as_generate_args`)、`clinosim dataset list` /
  `clinosim dataset build <name>` CLI サブコマンド。
- **Out of scope**: 自前の生成能力 — ビルダーは `sys.argv` を書き
  換えてプロセス内で `clinosim.simulator.cli.main` を呼び出すことで
  `clinosim generate` に委譲し、生成コードパスを single-source に
  保ちます。新しいシミュレーション機能追加時にこのパッケージを触る
  必要はありません。

## 公開 API

```python
from clinosim.dataset import (
    DatasetPreset,          # frozen dataclass: name / description / country /
                            #   population / seed / start / end / format
                            #   + .as_generate_args(output) -> list[str]
    list_presets,           # (presets_dir=None) -> list[str]
    load_preset,            # (name, presets_dir=None) -> DatasetPreset
    add_dataset_subparser,  # (argparse._SubParsersAction) -> None
    dispatch_dataset,       # (argparse.Namespace) -> int (プロセス exit code)
)
```

CLI 使用:

```bash
clinosim dataset list                       # 利用可能プリセット表示
clinosim dataset build jp-100 -o ./jp-100   # プリセット 1 件をビルド
```

`add_dataset_subparser` は
`clinosim/simulator/cli.py::build_parser` から呼び出され、
`dispatch_dataset` はユーザーが `dataset` サブコマンドを選択した
ときにメイン CLI dispatch パスから呼び出されます。

## 決定性

パッケージレベルでは該当なし。このパッケージはレコードを一切生成せ
ず、argv を書き換えて委譲するのみです。ビルド済データセットの決定性
は完全に `clinosim.simulator` (AD-16) から継承されます: あるプリセット
(固定の country + population + seed + 日付範囲 + format) は毎回
バイト同一のコホートを生成します。

## 依存

- `pyyaml` — `datasets/<name>/spec.yaml` ロード用。
- `clinosim.simulator.cli.main` (CLI 解析時の循環 import 回避のため
  `dispatch_dataset` 内部で遅延 import)。
- **`clinosim.modules.*` パッケージへの依存なし。**

## 定数と設定

- **プリセットファイル** は `<repo-root>/datasets/<name>/spec.yaml`
  に配置。各 spec は 8 つの必須キー (`load_preset` で検証) を宣言:
  `name` / `description` / `country` / `population` / `seed` /
  `start` / `end` / `format`。いずれか欠けている `spec.yaml` は
  ロード時に `ValueError`。
- **ディレクトリ名は `name` と一致必須** — `jp-100/` ディレクトリの
  `spec.yaml` が `name: jp-1000` を宣言していると設定エラーでロード
  時に例外。
- **プリセットルート発見** — `_PRESETS_DIR` は import 時に
  `Path(__file__).resolve().parents[2] / "datasets"` に解決される
  ので、subprocess 呼び出し・テスト caller もインタラクティブ CLI と
  同じ場所を参照します。`list_presets` と `load_preset` はテスト用
  に `presets_dir` override を受け付けます。
- **同梱プリセット** (執筆時点): `jp-100` / `jp-1000` / `us-100` /
  `us-1000`。正式なリストと各プリセットの説明は
  [`datasets/README.md`](../../datasets/README.md) 参照。

## ディレクトリ構成

```
clinosim/dataset/
  __init__.py           パッケージ全体 — DatasetPreset dataclass、
                        list_presets / load_preset /
                        add_dataset_subparser / dispatch_dataset
                        (約 180 行)
```

単一ファイルパッケージ。プリセット本体は `clinosim/` 内ではなく
repo root の `datasets/` に配置。

## テスト

```bash
pytest tests/unit -k dataset -q
```

`clinosim.dataset` を参照するテストファイルは 2。カバレッジは
プリセット YAML バリデーション (`load_preset` エラーパス) と CLI
配線 (`add_dataset_subparser` が期待するサブコマンドを期待する必須
引数で登録すること) が中心。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
