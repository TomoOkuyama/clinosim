# `clinosim.modules.validator` — realism benchmarks + consistency checks

## Purpose

Two orthogonal validators applied to a generated cohort:

- **Realism benchmarks** (`benchmarks.py`) — six cohort-level
  statistics compared against hard-coded expected values / ranges:
  `mean_age`, `male_ratio`, `median_los` and `mean_los` (inpatient;
  JP and US ranges differ), `mean_labs_per_patient`,
  `mean_vitals_per_patient`.
- **Consistency checks** (`consistency.py`) — internal rule-based
  invariants that need no LLM, run on records whose first encounter
  is inpatient: discharge Hgb (derived from the final
  `anemia_level`), deceased status vs disposition, lab value ranges,
  medication holds (anticoagulant in ICH, metformin in DKA / sepsis /
  pancreatitis / AKI), surgery code / approach fields, LOS
  consistency, vital ranges, sex-specific conditions, and the
  ground-truth namespace (every `ground_truth_diseases` value has a
  declared kind, Issue #2291).

In-repo callers: the `clinosim validate` CLI subcommand
(`simulator/cli_validate.run`), which runs its own quality checks
(`simulator/cli_common._run_quality_checks`) and then
`run_consistency_checks` (Issue #2208), and the e2e test that runs
`run_benchmarks` (see Output surfaces). Validators report only — they
do not fix issues.

## Scope

- **In scope**: `run_benchmarks(dataset, country) -> BenchmarkReport`
  with per-row `BenchmarkResult` (name / metric / generated value /
  expected value / expected range / `pass` / `warn` / `fail` status /
  deviation %); `run_consistency_checks(dataset, country) -> ConsistencyReport`
  (`country` is currently unused)
  with per-issue `ConsistencyIssue` (`error` / `warning` severity);
  nine private consistency helpers (`_check_discharge_hgb`,
  `_check_deceased_status`, `_check_lab_ranges`,
  `_check_medication_holds`, `_check_procedure_fields`,
  `_check_los_consistency`, `_check_vital_ranges`,
  `_check_sex_specific_conditions`, `_check_ground_truth_namespace`).
- **Out of scope**: PR-time module gating (that is
  [`clinosim.audit`](../../audit/README.md) — the AD-60 audit
  framework with per-module plug-ins); downstream cohort scoring
  ([`clinosim.eval`](../../eval/README.md)); fixing detected issues
  (this module reports only).

## Public API

`__init__.py` is empty (no `__all__`); consumers import directly
from the two submodules:

```python
from clinosim.modules.validator.benchmarks import (
    BenchmarkResult,             # dataclass: name / metric / generated / expected / range / status / deviation_pct
    BenchmarkReport,             # roll-up per run
    run_benchmarks,              # (dataset, country) -> BenchmarkReport
)
from clinosim.modules.validator.consistency import (
    ConsistencyIssue,            # dataclass: patient_id / severity / check_name / message
    ConsistencyReport,           # roll-up per run
    run_consistency_checks,      # (dataset, country) -> ConsistencyReport
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

- `clinosim.modules._shared` — `is_jp` for country dispatch
  (benchmarks).
- `clinosim.simulator.complications` — `complication_names`
  (consistency metformin-hold check).
- `clinosim.simulator.event_refs` — `event_ref_kind`
  (ground-truth namespace check).
- `clinosim.modules.observation.engine` — `PHYSIOLOGIC_LIMITS`,
  `canonical_lab_name` (lab / vital range checks).
- `clinosim.codes.drugs` — `has_drug` (medication holds);
  `clinosim.codes.snomed_concepts` — `SURGICAL_PROCEDURE`
  (procedure-field check).
- `clinosim.types.output` — `CIFDataset`, `CIFPatientRecord`.
- Otherwise standard library only (no `numpy` / `yaml`).

## Constants and configuration

- Benchmark expected values + acceptance ranges live inline in
  `benchmarks.py` (no per-benchmark source citations in the code), except
  the country-specific length-of-stay benchmarks, which are
  `reference_data/los_benchmarks.yaml` keyed by country slot
  (`los_benchmarks(country)`, Issue #3184).
- Consistency-check ranges are similarly inline; they anchor
  the hemoglobin discharge floor (7.0 g/dL), anticoagulant / ICH
  holds, metformin holds, and per-vital physiologic bounds.

## Directory contents

```
clinosim/modules/validator/
  __init__.py                    empty
  benchmarks.py                  BenchmarkResult / BenchmarkReport / run_benchmarks
  consistency.py                 ConsistencyIssue / ConsistencyReport / run_consistency_checks + 9 helpers
  reference_data/
    los_benchmarks.yaml          LOS benchmarks by country (Issue #3184)
  SPEC.md                        extended design reference (not runtime)
```

The module has **no `audit.py` and no `enricher.py`**.

## Enricher wiring

Not applicable — this module is imported directly by its callers
(`simulator/cli_validate.py` and `tests/e2e/test_beta.py`), not registered with
`register_builtin_enrichers`. It has no seed offset in
`ENRICHER_SEED_OFFSETS`.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| `clinosim validate` CLI | [`clinosim/simulator/cli_validate.py`](../../simulator/cli_validate.py) (`run`) | Runs `run_consistency_checks` on the generated cohort and prints `ConsistencyReport.summary()`. |
| E2E test | [`tests/e2e/test_beta.py`](../../../tests/e2e/test_beta.py) | Runs `run_benchmarks` on a real cohort to guard the realism envelope end-to-end. |

## Testing

```bash
pytest tests/e2e -k test_beta -q     # runs run_benchmarks on a real cohort
```

`tests/unit/test_unused_code_cleanup_2208.py` checks that
`clinosim validate` calls `run_consistency_checks` (with the checks
monkeypatched). Coverage gap: the individual checks have no unit
test. A per-check unit file (each of the nine
`_check_*` helpers with fixture patients that trip each rule) would
be a low-cost follow-up.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
