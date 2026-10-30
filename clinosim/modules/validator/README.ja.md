# `clinosim.modules.validator` — realism benchmark + consistency check

## 概要

生成 cohort に対する 2 系統の直交 validator:

- **Realism benchmark** (`benchmarks.py`) — 6 つの cohort-level 統計を
  hard-coded の期待値 / 範囲と比較: `mean_age`、`male_ratio`、
  `median_los` と `mean_los` (入院、JP と US で範囲が異なる)、
  `mean_labs_per_patient`、`mean_vitals_per_patient`。
- **Consistency check** (`consistency.py`) — LLM 不要の内部 rule-based
  不変量 (最初の encounter が入院の record が対象): 退院時 Hb (最終
  `anemia_level` から導出)、死亡 status と転帰、lab 値範囲、薬剤 hold
  (ICH の抗凝固薬、DKA / sepsis / 膵炎 / AKI の metformin)、手術の
  code / approach field、LOS 整合、vital 範囲、性別限定条件。

repo 内の呼び出し元は e2e test のみ (Output surface 参照)。
`clinosim validate` CLI subcommand は独自のチェック
(`simulator/cli_common._run_quality_checks`) を実行し、本モジュールは
呼ばない。validator は報告のみ — 問題を修正しない。

## Scope

- **In scope**: `run_benchmarks(dataset, country="JP") -> BenchmarkReport`
  と per-row `BenchmarkResult` (name / metric / generated / expected /
  range / `pass` / `warn` / `fail` status / deviation %);
  `run_consistency_checks(dataset, country="US") -> ConsistencyReport`
  (`country` は現状未使用) と
  per-issue `ConsistencyIssue` (`error` / `warning` severity);
  8 private consistency helper (`_check_discharge_hgb`,
  `_check_deceased_status`, `_check_lab_ranges`,
  `_check_medication_holds`, `_check_procedure_fields`,
  `_check_los_consistency`, `_check_vital_ranges`,
  `_check_sex_specific_conditions`)。
- **Out of scope**: PR-time module gating (それは
  [`clinosim.audit`](../../audit/README.ja.md) — AD-60 audit framework
  と per-module plug-in);下流の cohort scoring
  ([`clinosim.eval`](../../eval/README.ja.md));検出 issue の修正
  (本モジュールは報告のみ)。

## Public API

`__init__.py` は空。呼び出し側は 2 submodule から直接 import:

```python
from clinosim.modules.validator.benchmarks import (
    BenchmarkResult,             # dataclass: name / metric / generated / expected / range / status / deviation_pct
    BenchmarkReport,             # run 単位 roll-up
    run_benchmarks,              # (dataset, country="JP") -> BenchmarkReport
)
from clinosim.modules.validator.consistency import (
    ConsistencyIssue,            # dataclass: patient_id / severity / check_name / message
    ConsistencyReport,           # run 単位 roll-up
    run_consistency_checks,      # (dataset, country="US") -> ConsistencyReport
)
```

`BenchmarkResult.__post_init__` が各 row を自動採点 — 生成値が
expected range 内なら `pass`、±50 % 拡大範囲内なら `warn`、それ以外は
`fail`。

## 決定論

該当なし — validator は既に生成された cohort に対する read-only
操作。乱数は引かず `rng` 引数も無い。同一 cohort に対する再実行は
同一 report を返す。

## 依存

- `clinosim.modules._shared` — 国 dispatch 用 `is_jp` (benchmark)。
- `clinosim.simulator.complications` — `complication_names`
  (consistency の metformin hold check)。
- `clinosim.types.output` — `CIFDataset`, `CIFPatientRecord`。
- その他は標準ライブラリのみ (`numpy` / `yaml` 不使用)。

## 定数と設定

- Benchmark 期待値 + 許容範囲は `benchmarks.py` に inline (コード内に
  per-benchmark の出典引用は無い)。
- Consistency check の範囲も同様に inline。Hb 退院 floor (7.0 g/dL)、
  抗凝固剤 / ICH hold、metformin hold、vital 別 physiologic 境界を
  anchor する。
- YAML 無し。

## ディレクトリ構造

```
clinosim/modules/validator/
  __init__.py                    空
  benchmarks.py                  BenchmarkResult / BenchmarkReport / run_benchmarks
  consistency.py                 ConsistencyIssue / ConsistencyReport / run_consistency_checks + 8 helper
  SPEC.md                        拡張設計参考 (runtime data ではない)
```

**`audit.py` / `enricher.py` / `reference_data/` は存在しない**。

## Enricher 配線

該当なし — 本モジュールは呼び出し側 (現状 `tests/e2e/test_beta.py` のみ)
が直接 import し、
`register_builtin_enrichers` に登録なく `ENRICHER_SEED_OFFSETS` にも
seed 未登録。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| E2E test | [`tests/e2e/test_beta.py`](../../../tests/e2e/test_beta.py) | 実 cohort に対して `run_benchmarks` を回し、realism envelope を end-to-end guard。 |

## テスト

```bash
pytest tests/e2e -k test_beta -q     # 実 cohort で run_benchmarks 実行
```

**coverage gap**: 本モジュールの unit test は無く、
`run_consistency_checks` には現状呼び出し元も test も無い。8 `_check_*`
helper それぞれについて各 rule を発火する fixture 患者を並べた
per-check unit file は低コストの follow-up。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
