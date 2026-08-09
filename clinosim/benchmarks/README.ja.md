# `clinosim.benchmarks` — 早期警戒ベースライン分類器

## 目的

`clinosim.benchmarks` は clinosim 生成コホートから、早期警戒予測タスク
向けのラベル抽出とベースライン分類指標の計算を行います。ベースライン
の存在意義は、外部モデルが「敗血症予測」「AKI 予測」を謳う場合、
自明なルール以上の性能を示すことを要求するためです。

clinosim 生成は決定的 (AD-16) なので、ベースライン指標自身も再現可能:
同じ seed + 同じ population → byte-identical な陽性/陰性分布 → 同じ
ベースラインスコアが得られます。

## スコープ

- **In scope**: 入院 encounter 中の敗血症 onset ・ AKI (KDIGO Stage 1+)
  onset のラベル抽出、多数派ベースライン、単一閾値ルールベースライン
  (敗血症は lactate、AKI は creatinine delta)、単一コホートでの AUROC
  計算。
- **Out of scope**: 学習済 ML モデル (scikit-learn は将来検討の optional
  dependency)、交差検証分割 (単一コホートで下限値としては十分)、時系列
  特徴エンジニアリング (early-window のみ)、敗血症・AKI 以外のタスク
  (新規ラベル抽出器の追加で対応可能)。

## 公開 API

```python
from clinosim.benchmarks import (
    extract_sepsis_labels,      # (cif_dir) -> list[LabelRow]
    extract_aki_labels,         # (cif_dir) -> list[LabelRow]
    majority_baseline,          # (labels) -> BaselineReport
    lactate_threshold_baseline, # (labels, records) -> BaselineReport (sepsis)
    creatinine_delta_baseline,  # (labels, records) -> BaselineReport (AKI)
    compute_auroc,              # (y_true, y_score) -> float
)
```

`LabelRow` / `BaselineReport` はラベル・結果の dataclass。詳細スキーマ
は `types.py` を参照。

## 依存

- `clinosim.types` — CIF レコード形状。
- `pathlib` — 標準ライブラリのみ。外部 ML 依存なし。

## 定数と設定

- 敗血症検出 lactate 閾値: 現在 `sepsis.py` にインライン。
  [`docs/reviews/2026-08-09-constants-audit.md`](../../docs/reviews/2026-08-09-constants-audit.md)
  で抽出候補として記録。
- AKI 検出 creatinine delta: KDIGO Stage 1 = 48 時間以内に ≥ 0.3 mg/dL
  上昇。現在 `aki.py` にインライン。
- YAML 設定なし。

## ディレクトリ構成

```
clinosim/benchmarks/
  __init__.py           公開 API
  types.py              LabelRow / BaselineReport
  harness.py            ベースラインランナーの共有ハーネス
  sepsis.py             敗血症ラベル抽出器 + ベースライン
  aki.py                AKI ラベル抽出器 + ベースライン
```

## テスト

```bash
pytest tests/unit -k benchmarks -q
```

`clinosim.benchmarks` を参照するテストファイルは約 1。ベースラインは
安定した数値恒等式なので、カバレッジは意図的に軽量。意味のあるテスト
は「任意の生成コホートで完走し、同じ seed で同じ AUROC を返す」こと。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。
