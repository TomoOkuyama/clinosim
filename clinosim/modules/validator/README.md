# `clinosim.modules.validator` — realism benchmarks + consistency checks

## Purpose

Two orthogonal validators applied to a generated cohort:

- **Realism benchmarks** (`benchmarks.py`) — cross-check cohort-level
  statistics (LOS distributions, mortality rates, complication rates,
  chronic-condition prevalences) against published clinical
  benchmarks (JAMA / NEJM clinical guideline summaries, AHRQ HCUP for
  US, 厚生労働省 患者調査 for JP, OECD Health Data).
- **Consistency checks** (`consistency.py`) — internal rule-based
  invariants that need no LLM: physiologic value ranges, discharge
  criteria, medication holds, procedure required fields, deceased
  status, lab ↔ physiology trajectory alignment, LOS consistency,
  sex-specific conditions.

Consumed by the `clinosim validate` CLI subcommand. Validators
report only — they do not fix issues.

## Scope

- **In scope**: `run_benchmarks(dataset, country="JP") -> BenchmarkReport`
  with per-row `BenchmarkResult` (name / metric / generated value /
  expected value / expected range / `pass` / `warn` / `fail` status /
  deviation %); `run_consistency_checks(dataset) -> ConsistencyReport`
  with per-issue `ConsistencyIssue` (`error` / `warning` severity);
  eight private consistency helpers (`_check_discharge_hgb`,
  `_check_deceased_status`, `_check_lab_ranges`,
  `_check_medication_holds`, `_check_procedure_fields`,
  `_check_los_consistency`, `_check_vital_ranges`,
  `_check_sex_specific_conditions`).
- **Out of scope**: PR-time module gating (that is
  [`clinosim.audit`](../../audit/README.md) — the AD-60 audit
  framework with per-module plug-ins); downstream cohort scoring
  ([`clinosim.eval`](../../eval/README.md)); fixing detected issues
  (this module reports only).

## Public API

`__init__.py` is empty; consumers import directly from the two
submodules:

```python
from clinosim.modules.validator.benchmarks import (
    BenchmarkResult,             # dataclass: name / metric / generated / expected / range / status / deviation_pct
    BenchmarkReport,             # roll-up per run
    run_benchmarks,              # (dataset, country="JP") -> BenchmarkReport
)
from clinosim.modules.validator.consistency import (
    ConsistencyIssue,            # dataclass: patient_id / severity / check_name / message
    ConsistencyReport,           # roll-up per run
    run_consistency_checks,      # (dataset) -> ConsistencyReport
)
```

`BenchmarkResult.__post_init__` grades each row automatically —
`pass` when the generated value sits inside the expected range,
`warn` when it sits inside a ±50 % expansion, else `fail`.

## Determinism

Not applicable — validators are read-only over an already-generated
cohort. They make no random draws and take no `rng` argument;
running the same cohort through them twice returns identical
reports.

## Dependencies

- `clinosim.modules._shared` — `is_jp` for country dispatch.
- `clinosim.types.output` — `CIFDataset`, `CIFPatientRecord`.
- `clinosim.types.encounter` — encounter records read by the
  consistency helpers.
- Standard library only (no `numpy` / `yaml`).

## Constants and configuration

- Benchmark expected values + acceptance ranges live inline in
  `benchmarks.py` with per-benchmark source citation
  (JAMA / NEJM / HCUP / 患者調査 / OECD). Threshold extraction to a
  `_benchmark_thresholds.py` sibling is tracked in
  [`docs/reviews/2026-08-09-constants-audit.md`](../../../docs/reviews/2026-08-09-constants-audit.md).
- Consistency-check ranges are similarly inline; they anchor
  hemoglobin discharge floors, anticoagulant / ICH holds,
  metformin / DKA holds, and per-vital physiologic bounds.
- No YAML — validation is code-first because ranges are cited from
  named clinical references, not tuned parameters.

## Directory contents

```
clinosim/modules/validator/
  __init__.py                    empty
  benchmarks.py                  BenchmarkResult / BenchmarkReport / run_benchmarks
  consistency.py                 ConsistencyIssue / ConsistencyReport / run_consistency_checks + 8 helpers
  SPEC.md                        extended design reference (not runtime)
```

The module has **no `audit.py`, no `enricher.py`, no
`reference_data/`**.

## Enricher wiring

Not applicable — this module is invoked by the CLI, not by
`register_builtin_enrichers`. It has no seed offset in
`ENRICHER_SEED_OFFSETS`.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| CLI `validate` subcommand | [`clinosim/simulator/cli.py`](../../simulator/cli.py) (`~L224-225`, `~L660-680`) | Argparse subparser + dispatch. Loads the generated dataset, calls `run_benchmarks` + `run_consistency_checks`, prints the roll-up. |
| E2E test | [`tests/e2e/test_beta.py`](../../../tests/e2e/test_beta.py) | Runs `run_benchmarks` on a real cohort to guard the realism envelope end-to-end. |

## Testing

```bash
pytest tests/unit -k validator -q
pytest tests/e2e -k test_beta -q     # runs run_benchmarks on a real cohort
```

Coverage gap: `run_consistency_checks` has no dedicated unit test
file today; it is exercised transitively through the `clinosim
validate` CLI test path. A per-check unit file (each of the eight
`_check_*` helpers with fixture patients that trip each rule) would
be a low-cost follow-up.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
