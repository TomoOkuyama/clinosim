# validator

Consistency validation and realism benchmarking. Verifies generated data is physiologically plausible and matches real-world statistics.

## Public API

```python
from clinosim.modules.validator.benchmarks import run_benchmarks, BenchmarkReport

report = run_benchmarks(dataset, country="JP")
print(report.summary())
```

### `run_benchmarks(dataset, country) -> BenchmarkReport`
Runs Tier 1 statistical benchmarks against generated data. Currently checks:
- Mean patient age (expected ~72 for JP pneumonia)
- Male ratio (expected ~55%)
- Median and mean LOS (expected ~14 days JP)
- Mean labs per patient
- Mean vitals per patient

## Dependencies
- `clinosim.types.output` (CIFDataset)

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/e2e/test_beta.py::TestBeta::test_benchmarks_pass -v
```

## Implementation status
- [x] Benchmark framework (pass/warn/fail with expected ranges)
- [x] Demographics benchmarks (age, sex ratio)
- [x] LOS benchmarks (median, mean)
- [x] Data volume benchmarks (labs/patient, vitals/patient)
- [ ] Mortality rate benchmark
- [ ] Readmission rate benchmark
- [ ] Lab distribution benchmarks (admission CRP, discharge CRP)
- [ ] Temporal pattern benchmarks (seasonal, time-of-day)
- [ ] Pass 1 rule-based validation (rate-of-change, mutual exclusion)
- [ ] Pass 2 LLM consistency review
