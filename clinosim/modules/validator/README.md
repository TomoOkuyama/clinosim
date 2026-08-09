# `clinosim.modules.validator` — realism benchmarks and consistency checks

## Purpose

Provides two orthogonal families of validators applied to generated
cohorts:

- **Realism benchmarks** — cross-check cohort-level statistics
  (LOS distributions, mortality rates, complication rates, chronic-
  condition prevalences) against published clinical benchmarks (HCUP,
  厚生労働省 患者調査, OECD Health Data, AHRQ).
- **Consistency checks** — internal-consistency invariants (e.g. no
  patient has a discharge date before admission, no observation is
  emitted outside its encounter window, coded values match their
  display strings).

Both are consumed by the `clinosim validate` CLI subcommand.

## Scope

- **In scope**: benchmark comparison harness, consistency invariant
  checks, `BenchmarkReport` / consistency-check result dataclasses,
  CLI wiring for `clinosim validate`.
- **Out of scope**: PR-time module gating (that is
  [`clinosim.audit`](../../audit/README.md)), public downstream cohort
  scoring (that is [`clinosim.eval`](../../eval/README.md)), fixing
  the issues found — validators report only.

## Public API

```python
from clinosim.modules.validator import (
    run_benchmarks,              # (cohort, country) -> BenchmarkReport
    BenchmarkResult,             # per-benchmark row
    BenchmarkReport,             # roll-up per run
)
from clinosim.modules.validator.consistency import run_consistency_checks
```

## Benchmark sources

- **JAMA / NEJM clinical guideline summaries** — LOS, readmission,
  mortality baselines.
- **AHRQ HCUP** (US) — encounter-mix, procedure frequency, cost.
- **厚生労働省 患者調査** (JP) — inpatient / outpatient mix, chronic-
  condition prevalence.
- **OECD Health Data** — cross-country baselines.

Detailed source citations are attached to each benchmark inside
`benchmarks.py`.

## Dependencies

- `clinosim.types.output` — `CIFDataset`.
- `clinosim.types.encounter` — encounter records.
- Standard library only for benchmark computation (no numpy required).

## Constants and configuration

- Benchmark expected values and their acceptance ranges live inline
  in `benchmarks.py` and are flagged for extraction in
  [`docs/reviews/2026-08-09-constants-audit.md`](../../../docs/reviews/2026-08-09-constants-audit.md).

## Directory contents

```
clinosim/modules/validator/
  __init__.py           public API
  benchmarks.py         benchmark harness + BenchmarkReport
  consistency.py        consistency-invariant checks
  audit.py              per-module audit spec
```

## Testing

```bash
pytest tests/unit -k validator -q
pytest tests/e2e -k test_beta -q     # runs run_benchmarks on a real cohort
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
