# 予測ベンチマーク

*Session 48 P2-15: 敗血症 + AKI 発症予測に対する再現可能なベースライン
評価。*

## 目的

clinosim 生成コホートに対する共通の早期警戒タスクの再現可能な **床値**。
公開されたどんなモデルも臨床価値を主張する前にこれらを超える必要が
あります。clinosim は決定的 (AD-16) なので、同一 seed + 集団は実行間で
同一のラベル分布を生成し、ベースラインそのものが再現可能。

## 対応タスク

| タスク | 陽性定義 | AUROC 用の連続スコア |
|---|---|---|
| `sepsis` | `condition_event.disease_id == "sepsis"` または ICD `A41.*` / `R65.2*` | first-window Lactate (mmol/L) |
| `aki` | `condition_event.disease_id == "acute_kidney_injury"` または ICD `N17.*` / `N19` | peak SCr − baseline SCr (mg/dL) |

## 同梱ベースライン

各タスクは 2 つの参照ベースラインを同梱:

- **majority** — 各行に多数派クラスを予測。情報を持つモデルが超えるべき
  床精度を設定。AUROC は 0.5 (定数スコアラー)。
- **lactate_threshold** (sepsis) — Surviving Sepsis 2021 ルール
  `lactate > 2 mmol/L` が敗血症を示唆。生 lactate を AUROC 用連続
  スコアとして使用。
- **creatinine_delta** (AKI) — KDIGO 2012 Stage 1 基準
  `ΔSCr > 0.3 mg/dL` を baseline から。生 delta をスコアとして使用。

両閾値ルールともドキュメント化された非学習ベースライン。ML fitting を
意図的に使わないため、性能はパッケージ版に不変。

## 実行

```bash
# 1. コホート生成 (seed ごとに決定的)
clinosim simulate --country US --population 500 --seed 42 --format cif \
    --output ./cohort

# 2. 敗血症タスクをスコア化
clinosim benchmark sepsis --cif-dir ./cohort/cif

# 3. AKI をスコア化、下流分析用 JSON 出力
clinosim benchmark aki --cif-dir ./cohort/cif --json > aki_baseline.json
```

## 出力例

```
clinosim benchmark: task=sepsis, n=500, prevalence=0.0620
  == baseline: majority ==
     AUROC     = 0.5000
     accuracy  = 0.9380
     +pred rate = 0.0000
     rationale: Predict majority class. ...
  == baseline: lactate_threshold ==
     AUROC     = 0.8712
     accuracy  = 0.9020
     +pred rate = 0.1080
     rationale: Surviving Sepsis 2021 rule: lactate > 2.0 mmol/L ...
```

## Extending

新規ベンチマーク追加:

1. `clinosim/benchmarks/<task>.py` を作成:
   - `extract_<task>_labels(cif_dir) -> list[LabelRow]`
   - 1 つ以上の `<baseline_name>_baseline(labels) -> BaselineReport`
2. `clinosim/benchmarks/__init__.py` に再エクスポート追加。
3. `clinosim/benchmarks/cli.py` の `TASKS` に新タスクを追加。
4. `tests/unit/test_benchmark_harness.py` (または新規ファイル) に
   単体テストを追加。

## 対象外 (defer)

- 学習済 ML モデル (scikit-learn は hard dep ではない; 学習ベースライン
  追加には optional-dep gating が必要)
- クロスバリデーション分割 (単一コホートベースラインで床値としては十分)
- first-window peak を超える時系列特徴量エンジニアリング
- 複数エンドポイント合成 (例: sepsis-3 SOFA delta)
- コスト sensitive 指標 (calibration、decision curve)

これらの拡張は自然な後続作業; ハーネスは既に `compute_auroc` と
`BaselineReport` 形状を再利用可能に公開しています。
