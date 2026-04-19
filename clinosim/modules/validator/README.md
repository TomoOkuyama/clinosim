# clinosim.modules.validator — Realism Benchmarks Module

## 目的

シミュレーションが生成した CIF データセットの **統計的リアリズム** を、 公表された実世界臨床データと比較検証する。

合成 EHR データの「もっともらしさ」を客観的に保証するため、 平均年齢・性比・LOS (在院日数)・データ密度などのメトリクスを **査読済み文献・公的統計** の期待範囲と照合し、 pass/warn/fail ラベル付きのレポートを返す。

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **CIF-only consumer** | `CIFDataset` のみを入力とする。 シミュレーション内部状態は触らない |
| 2 | **Tier 化検証** | Tier 1 = 集計統計 (本モジュール)、 Tier 2 = 個別患者の生理学的整合性、 Tier 3 = 専門家レビュー (将来) |
| 3 | **権威ソース根拠** | 期待値は JAMA / NEJM / AHRQ / 厚労省 患者調査 等の公表値に基づく |
| 4 | **国別期待値** | LOS 等は US と JP で大きく異なるため、 `country` 引数で参照値を切り替え |
| 5 | **3-段階判定** | pass (期待範囲内) / warn (50%-150% 範囲) / fail (それ以外) |

## ディレクトリ構造

```
clinosim/modules/validator/
├── __init__.py
├── README.md         # 本ドキュメント
├── SPEC.md
└── benchmarks.py     # BenchmarkResult, BenchmarkReport, run_benchmarks
```

## API リファレンス

### `run_benchmarks(dataset: CIFDataset, country: str = "JP") -> BenchmarkReport`

CIF データセットに対して Tier 1 統計ベンチマークを実行する。

```python
from clinosim.modules.validator.benchmarks import run_benchmarks

report = run_benchmarks(dataset, country="JP")
print(report.summary())
# → "Benchmarks: 6 total, 5 pass, 1 warn, 0 fail (83% pass rate)"

for r in report.results:
    print(f"[{r.status.upper():4}] {r.name}: {r.generated_value:.1f} "
          f"(expected {r.expected_value}, range {r.expected_range}, "
          f"deviation {r.deviation_pct:.0f}%)")
```

### `BenchmarkResult`

```python
@dataclass
class BenchmarkResult:
    name: str                              # 内部名 (e.g., "median_los")
    metric: str                            # 人間可読なメトリクス説明
    generated_value: float                 # 実際にシミュレータが生成した値
    expected_value: float                  # 文献ベースの期待中心値
    expected_range: tuple[float, float]    # 許容範囲 (low, high)
    status: str = ""                       # __post_init__ で計算
    deviation_pct: float = 0.0
```

**判定ロジック** (`__post_init__`):

```python
if low <= generated_value <= high:
    status = "pass"
elif low * 0.5 <= generated_value <= high * 1.5:
    status = "warn"
else:
    status = "fail"
```

`deviation_pct` は期待値からの偏差率: `|generated - expected| / expected * 100`

### `BenchmarkReport`

```python
@dataclass
class BenchmarkReport:
    results: list[BenchmarkResult]

    @property
    def pass_count(self) -> int: ...
    @property
    def warn_count(self) -> int: ...
    @property
    def fail_count(self) -> int: ...
    @property
    def pass_rate(self) -> float: ...
    def summary(self) -> str: ...
```

## 実装されているベンチマーク

`run_benchmarks()` が現状チェックする項目:

| Name | Metric | 期待中心 | 期待範囲 | 国差 |
|---|---|---|---|---|
| `mean_age` | 入院肺炎患者の平均年齢 | 72 歳 | 60–82 | — |
| `male_ratio` | 男性比率 | 0.55 | 0.40–0.70 | — |
| `median_los` | LOS 中央値 (日) | JP: 14 / US: 4.5 | JP: 10–20 / US: 3–7 | あり |
| `mean_los` | LOS 平均 (日) | JP: 15 / US: 5 | JP: 10–22 / US: 3–8 | あり |
| `mean_labs_per_patient` | 1 患者あたり検査結果数 | 50 | 20–100 | — |
| `mean_vitals_per_patient` | 1 患者あたりバイタルセット数 | 42 | 15–80 | — |

LOS は **inpatient エンカウンタに限定** して計算し、 `discharge_datetime - admission_datetime > 0` のものだけ集計する。

## 期待値の根拠 (権威ソース)

| メトリクス | 根拠 |
|---|---|
| 入院肺炎患者の年齢分布 | [CDC NCHS Hospital Discharge Survey](https://www.cdc.gov/nchs/nhds/index.htm) / [厚生労働省 患者調査](https://www.mhlw.go.jp/toukei/list/10-20.html) |
| LOS (US) | [AHRQ HCUP Statistical Briefs](https://hcup-us.ahrq.gov/reports/statbriefs/) — pneumonia mean LOS ~5 days |
| LOS (JP) | [厚労省 病院報告 / 患者調査](https://www.mhlw.go.jp/toukei/list/79-1.html) — 平均在院日数 約 16 日 (一般病床) |
| 性比 | [JAMA pneumonia epidemiology reviews](https://jamanetwork.com/) |
| OECD 国際比較 | [OECD Health Statistics](https://www.oecd.org/health/health-statistics.htm) |

## 使用例

### シミュレーション後の品質ゲート

```python
from clinosim.simulator import Simulator
from clinosim.modules.validator.benchmarks import run_benchmarks

dataset = Simulator(country="JP", seed=42).run(n_patients=100)
report = run_benchmarks(dataset, country="JP")

if report.fail_count > 0:
    print("Fail benchmarks:")
    for r in report.results:
        if r.status == "fail":
            print(f"  - {r.name}: {r.generated_value} not in {r.expected_range}")
    raise SystemExit(1)

print(report.summary())
```

### CI 統合 (pass rate しきい値)

```python
report = run_benchmarks(dataset)
assert report.pass_rate >= 0.80, (
    f"Realism degradation: {report.pass_rate:.0%} < 80%\n"
    f"{report.summary()}"
)
```

### カスタム期待値の追加

```python
from clinosim.modules.validator.benchmarks import BenchmarkResult, BenchmarkReport

def my_benchmarks(dataset):
    report = BenchmarkReport()
    mortality = sum(1 for p in dataset.patients if p.deceased) / len(dataset.patients)
    report.add(BenchmarkResult(
        name="inpatient_mortality",
        metric="In-hospital mortality (pneumonia)",
        generated_value=mortality,
        expected_value=0.10,                  # NEJM 文献値
        expected_range=(0.05, 0.15),
    ))
    return report
```

## 依存関係

- `clinosim.types.output.CIFDataset` — 入力型
- 標準ライブラリ `statistics` のみ (numpy 等不要)

シミュレーションモジュールには依存しない (post-hoc 検証専用)。

## 権威ソース一覧

- **JAMA** — [jamanetwork.com](https://jamanetwork.com/)
- **NEJM** — [nejm.org](https://www.nejm.org/)
- **AHRQ HCUP** — [hcup-us.ahrq.gov](https://hcup-us.ahrq.gov/)
- **CDC NCHS** — [cdc.gov/nchs](https://www.cdc.gov/nchs/)
- **厚生労働省 患者調査** — [mhlw.go.jp/toukei](https://www.mhlw.go.jp/toukei/list/10-20.html)
- **OECD Health Data** — [oecd.org/health](https://www.oecd.org/health/)

## 既知の制約・今後

- Tier 1 は集計統計ベンチマーク (肺炎中心)。 疾患別 (HF, hip fracture, sepsis 等) の追加予定
- ✅ Tier 2 (個別患者整合性) 実装済: `consistency.py` — 8 ルールベースチェック (退院 Hgb, 死亡 disposition, ラボ範囲, medication_holds, 処置フィールド, LOS, バイタル範囲, 性別特異的疾患)。 195 患者 / 1,560 チェックで 0 errors, 0 warnings
- Tier 3 (専門家レビュー) は未実装
- 死亡率・再入院率・合併症発生率の検証項目を追加予定
- 期待値は文献の中央値ベース。 患者構成 (重症度・併存疾患) を考慮したリスク調整は未対応

## 修正ガイド

### 新しい Tier 2 チェックを追加する

1. `consistency.py` に `_check_new_rule(record, pid, report)` 関数を追加
2. `run_consistency_checks()` の呼び出しリストに追加
3. `ConsistencyIssue` で `issue_type` を一意な名前にする
4. テスト: `pytest tests/unit/test_validator.py -v`

### Tier 2 既存 8 チェック

| チェック名 | 内容 |
|---|---|
| `discharge_hgb` | 退院時 Hgb < 5.0 なら warning |
| `deceased_disposition` | 死亡患者の disposition が "expired" / "died" か |
| `lab_range` | ラボ値が物理的にあり得ない範囲でないか |
| `medication_holds` | disease YAML の medication_holds に基づく薬剤保留チェック |
| `procedure_fields` | 手術に procedure_code と approach があるか |
| `los_consistency` | 入退院日時から計算した LOS が physiological_states 数と整合するか |
| `vital_ranges` | バイタルが生存可能範囲内か |
| `sex_specific_conditions` | 性別特異的疾患が正しい性別に割り当てられているか |

### 関連モジュール

- **依存なし**: CIFDataset を受け取るだけの post-hoc 検証
- **呼び出し元**: `clinosim validate` CLI、またはテスト内から直接呼び出し

### バリデーション実行方法

```bash
# CLI (全データの Tier 1 + Tier 2 検証)
clinosim validate --cif-dir ./output/cif

# Python API
from clinosim.modules.validator.consistency import run_consistency_checks
report = run_consistency_checks(cif_dataset)
print(f"Errors: {report.error_count}, Warnings: {report.warning_count}")
for issue in report.issues:
    print(f"  [{issue.severity}] {issue.patient_id}: {issue.message}")
```

**結果の解釈**: `error` はデータ品質問題で修正必須。 `warning` は許容範囲内だが調査推奨。
