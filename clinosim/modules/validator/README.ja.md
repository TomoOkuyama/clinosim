# `clinosim.modules.validator` — realism benchmark + consistency check

## 概要

生成 cohort に対する 2 系統の直交 validator:

- **Realism benchmark** (`benchmarks.py`) — cohort-level 統計
  (LOS 分布、mortality、合併症率、慢性疾患 prevalence) を公表 clinical
  benchmark と突合 (JAMA / NEJM 臨床ガイドライン、AHRQ HCUP for US、
  厚生労働省 患者調査 for JP、OECD Health Data)。
- **Consistency check** (`consistency.py`) — LLM 不要の内部 rule-based
  不変量: physiologic 値範囲、退院基準、薬剤 hold、procedure 必須
  field、死亡 status、lab ↔ physiology trajectory 整合、LOS 整合、
  性別限定条件。

`clinosim validate` CLI subcommand が消費。validator は報告のみ —
問題を修正しない。

## Scope

- **In scope**: `run_benchmarks(dataset, country="JP") -> BenchmarkReport`
  と per-row `BenchmarkResult` (name / metric / generated / expected /
  range / `pass` / `warn` / `fail` status / deviation %);
  `run_consistency_checks(dataset) -> ConsistencyReport` と
  per-issue `ConsistencyIssue` (`error` / `warning` severity);
  8 private consistency helper (`_check_discharge_hgb`,
  `_check_deceased_status`, `_check_lab_ranges`,
  `_check_medication_holds`, `_check_procedure_fields`,
  `_check_los_consistency`, `_check_vital_ranges`,
  `_check_sex_specific_conditions`)。
- **Out of scope**: PR-time module gating (それは
  [`clinosim.audit`](../../audit/README.md) — AD-60 audit framework
  と per-module plug-in);下流の cohort scoring
  ([`clinosim.eval`](../../eval/README.md));検出 issue の修正
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
    run_consistency_checks,      # (dataset) -> ConsistencyReport
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

- `clinosim.modules._shared` — 国 dispatch 用 `is_jp`。
- `clinosim.types.output` — `CIFDataset`, `CIFPatientRecord`。
- `clinosim.types.encounter` — consistency helper が読む encounter
  record。
- 標準ライブラリのみ (`numpy` / `yaml` 不使用)。

## 定数と設定

- Benchmark 期待値 + 許容範囲は `benchmarks.py` に inline、per-benchmark
  の source 引用付き (JAMA / NEJM / HCUP / 患者調査 / OECD)。sibling
  `_benchmark_thresholds.py` への閾値 lift は
  [`docs/reviews/2026-08-09-constants-audit.md`](../../../docs/reviews/2026-08-09-constants-audit.md)
  で追跡中。
- Consistency check の範囲も同様に inline。Hb 退院 floor、抗凝固剤 /
  ICH hold、metformin / DKA hold、vital 別 physiologic 境界を anchor
  する。
- YAML 無し — 範囲は tuning parameter ではなく named clinical
  reference を引用しているため、validation は code-first。

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

該当なし — 本モジュールは CLI から呼び出され、
`register_builtin_enrichers` に登録なく `ENRICHER_SEED_OFFSETS` にも
seed 未登録。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| CLI `validate` subcommand | [`clinosim/simulator/cli.py`](../../simulator/cli.py) (`L224-225`, `L660-680` 付近) | Argparse subparser + dispatch。生成 dataset を load して `run_benchmarks` + `run_consistency_checks` を呼び、roll-up を print。 |
| E2E test | [`tests/e2e/test_beta.py`](../../../tests/e2e/test_beta.py) | 実 cohort に対して `run_benchmarks` を回し、realism envelope を end-to-end guard。 |

## テスト

```bash
pytest tests/unit -k validator -q
pytest tests/e2e -k test_beta -q     # 実 cohort で run_benchmarks 実行
```

**coverage gap**: `run_consistency_checks` に専用 unit test file は
無く、`clinosim validate` CLI path 経由で間接カバー。8 `_check_*`
helper それぞれについて各 rule を発火する fixture 患者を並べた
per-check unit file は低コストの follow-up。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
