# `clinosim.benchmarks` — 早期警戒ベースライン分類器

## 目的

`clinosim.benchmarks` は clinosim 生成コホートから派生する早期警戒
予測タスクのためにラベルを抽出し、ベースライン分類器の指標を計算
します。「敗血症を予測できる」「AKI を予測できる」と主張する外部
モデルが、多数派クラス予測や単一閾値ルールを超える価値を示すために
超えるべき床を提供します。

clinosim の生成は決定的 (AD-16) なので、ベースライン指標そのものも
再現可能です: 同一 seed + 同一 population → バイト同一の陽性 / 陰性
分布 → 同一のベースラインスコア。

## スコープ

- **In scope**: 入院エンカウンター中の敗血症発症 / AKI 発症ラベル
  抽出 (`extract_sepsis_labels` / `extract_aki_labels`)、多数派クラス
  ベースライン (`majority_baseline`)、単一閾値ルールベースライン
  (`lactate_threshold_baseline` sepsis 用 /
  `creatinine_delta_baseline` AKI 用)、Mann-Whitney U 解釈による
  手書き `compute_auroc`。
- **Out of scope**: 学習済 ML モデル (scikit-learn は defer された
  optional dependency、現在未使用)、クロスバリデーション分割
  (単一コホートベースラインで床値としては十分)、時系列特徴量エンジ
  ニアリング (early-window のみ)、敗血症 / AKI 以外のタスク (必要
  なら新規 label extractor + baseline ペアを追加)。

## 公開 API

```python
from clinosim.benchmarks import (
    extract_sepsis_labels,      # (cif_dir) -> list[LabelRow]
    extract_aki_labels,         # (cif_dir) -> list[LabelRow]
    majority_baseline,          # (labels) -> BaselineReport
    lactate_threshold_baseline, # (labels) -> BaselineReport (sepsis)
    creatinine_delta_baseline,  # (labels, threshold=0.3) -> BaselineReport (aki)
    compute_auroc,              # (y_true, y_score) -> float
    LabelRow, BaselineReport,   # harness.py から再エクスポートされる dataclass
)
```

`cli.py` の `add_benchmark_subparser` / `dispatch_benchmark` は
トップレベル `clinosim` CLI への配線ですが、パッケージレベルでは
再エクスポートされません。

## 決定性

import 時点では該当なし — 本パッケージには乱数生成がありません。
ベースラインは入力ラベルの純関数: 同一ラベル → 同一 `BaselineReport`。
基礎となるラベルの決定性はコホート生成側 (`clinosim.simulator`、
AD-16) から継承します。

## 依存

- `numpy` — ベクトル化 AUROC 用。
- 標準ライブラリ `pathlib` / `dataclasses` / `argparse` / `typing`。
- **外部 ML 依存なし。** scikit-learn は意図的に import しません。

## 定数と設定

- **敗血症検出用 lactate 閾値** — 現状 `sepsis.py::
  lactate_threshold_baseline` にインライン。抽出候補として
  [`docs/reviews/2026-08-09-constants-audit.md`](../../docs/reviews/2026-08-09-constants-audit.md)
  に登録。
- **AKI 検出用 creatinine delta** — `creatinine_delta_baseline` は
  `threshold: float = 0.3` 引数 (エンカウンター初日 baseline
  creatinine と期間中 peak の mg/dL 差) を取ります。これは KDIGO
  Stage 1 の SCr 基準 (≥ 0.3 mg/dL 上昇) — KDIGO の「1.5× baseline」
  variant は適用しません。Stage 1 はいずれかの基準で発火し、典型的な
  入院時 baseline SCr では 0.3 mg/dL のほうが厳しい閾値になるため。
- **`compute_auroc` の degenerate 戻り値** —
  `pos.size == 0 or neg.size == 0` → `0.5` (Mann-Whitney U 慣習と
  してドキュメント化); 空入力 → `0.0` (caller 側で `n > 0` ガード
  必須)。
- **YAML 設定なし。**

## ディレクトリ構成

```
clinosim/benchmarks/
  __init__.py           公開 API (8 export)
  harness.py            LabelRow / BaselineReport dataclass、
                        compute_auroc / majority_baseline
  sepsis.py             敗血症 label extractor + lactate_threshold_baseline
  aki.py                AKI label extractor + creatinine_delta_baseline
  cli.py                `clinosim benchmark` サブコマンド
                        (add_benchmark_subparser / dispatch_benchmark)
```

## テスト

```bash
pytest tests/unit -k benchmarks -q
```

`clinosim.benchmarks` を参照するテストファイルは 1。ベースラインは
安定した数値恒等式なので、テストは意図的に薄めです。意味ある検証は
「任意の生成コホートで完走し、同一 seed で同一 AUROC を返す」こと。
新規ベンチマークタスク追加時は、自身の label extractor + baseline
ペアに加えて「小さな決定的コホートで期待 AUROC を pin する one-shot
テスト」を追加してください。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
