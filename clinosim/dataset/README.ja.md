# `clinosim.dataset` — 名前付きプリセットデータセットビルダー

## 目的

`clinosim.dataset` は名前付きプリセット (例: `jp-100`, `us-1000`) を
対応する `clinosim generate` 実行に変換する薄い CLI ラッパーです。
プリセットを再現可能なリリースにするための 6 個のフラグを覚える代わり
に、ユーザーが 1 つの短いコマンドで実行できるようにするために存在
します。

プリセットは **データセットリリースのバージョン付き公開 API** です。
新規プリセットの追加は、メンテナが country / population / seed / date
range / output format の新しい公式サポート組み合わせを宣言する手段。

## スコープ

- **In scope**: プリセット列挙 (`list_presets`)、プリセットのロード
  と検証 (`load_preset`)、`clinosim dataset build <name>` CLI サブ
  コマンド。
- **Out of scope**: 自前の生成機能なし — ビルダーは同じ
  `SimulatorConfig` パイプライン経由で `clinosim generate` に委譲。
  新規シミュレーション機能追加時にこのパッケージは触りません。

## 公開 API

```python
from clinosim.dataset import (
    list_presets,           # () -> list[str]
    load_preset,            # (name) -> PresetSpec
    add_dataset_subparser,  # (argparse.ArgumentParser) -> None
    dispatch_dataset,       # (argparse.Namespace) -> int
)
```

CLI 使用例:

```bash
clinosim dataset list                     # 利用可能プリセット表示
clinosim dataset build jp-100 --output ./jp-100-out
```

## 依存

- `pyyaml` — プリセット YAML ロード。
- `clinosim.simulator` (`clinosim generate` 経由) — 実行本体。
- `clinosim.modules.*` パッケージへの依存なし。

## 定数と設定

- プリセットファイルは `<repo-root>/datasets/<name>/spec.yaml` に配置。
  各 spec が宣言する内容:
  - `country`: `US` / `JP`
  - `population`: 患者数 (整数)
  - `seed`: RNG シード (整数)
  - `start` / `end`: ISO 日付範囲
  - `output_format`: `cif` / `fhir` / `csv` / 組み合わせ
- 出荷プリセット一覧は
  [`datasets/README.md`](../../datasets/README.md) を参照。

## ディレクトリ構成

```
clinosim/dataset/
  __init__.py           公開 API + CLI
```

単一ファイルパッケージ。プリセット自体はリポジトリルートの
`datasets/` にあり、`clinosim/` 内には含まれません。

## テスト

```bash
pytest tests/unit -k dataset -q
```

`clinosim.dataset` を参照するテストファイルは約 1。カバレッジは
プリセット YAML 検証に集中。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。
