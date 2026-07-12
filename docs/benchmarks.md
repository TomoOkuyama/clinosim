# Prediction benchmarks

*Session 48 P2-15: reproducible baseline eval for sepsis + AKI onset prediction.*

## Purpose

Reproducible **floor numbers** for common early-warning tasks over
clinosim-generated cohorts. Any published model must exceed these before it
can claim clinical value. Because clinosim is deterministic (AD-16), the same
seed + population produces identical label distributions across runs, making
the baseline itself reproducible.

## Supported tasks

| Task | Positive definition | Continuous score for AUROC |
|---|---|---|
| `sepsis` | `condition_event.disease_id == "sepsis"` OR ICD `A41.*` / `R65.2*` | First-window Lactate (mmol/L) |
| `aki` | `condition_event.disease_id == "acute_kidney_injury"` OR ICD `N17.*` / `N19` | Peak SCr − baseline SCr (mg/dL) |

## Baselines shipped

Each task ships with two reference baselines:

- **majority** — predicts the majority class for every row. Sets the floor
  accuracy an informative model must exceed. AUROC is 0.5 (constant scorer).
- **lactate_threshold** (sepsis) — Surviving Sepsis 2021 rule
  `lactate > 2 mmol/L` implies sepsis. Uses raw lactate as continuous score
  for AUROC.
- **creatinine_delta** (AKI) — KDIGO 2012 Stage 1 criterion
  `ΔSCr > 0.3 mg/dL` from baseline defines AKI. Uses raw delta as score.

Both threshold rules are documented, non-trained baselines. They intentionally
use no ML fitting so their performance is invariant to package versions.

## Running

```bash
# 1. Generate a cohort (deterministic per seed)
clinosim simulate --country US --population 500 --seed 42 --format cif \
    --output ./cohort

# 2. Score the sepsis task
clinosim benchmark sepsis --cif-dir ./cohort/cif

# 3. Score AKI, JSON output for downstream analysis
clinosim benchmark aki --cif-dir ./cohort/cif --json > aki_baseline.json
```

## Example output

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

Add a new benchmark by:

1. Create `clinosim/benchmarks/<task>.py` with:
   - `extract_<task>_labels(cif_dir) -> list[LabelRow]`
   - one or more `<baseline_name>_baseline(labels) -> BaselineReport`
2. Update `clinosim/benchmarks/__init__.py` to re-export
3. Update `clinosim/benchmarks/cli.py` to add the new task to `TASKS`
4. Add unit tests under `tests/unit/test_benchmark_harness.py` (or a new file)

## Out of scope (deferred)

- Trained ML models (scikit-learn is not a hard dep; adding trainable
  baselines would require optional-dep gating)
- Cross-validation splits (single-cohort baselines are sufficient for
  floor numbers)
- Time-windowed feature engineering beyond first-window peak
- Multi-endpoint composites (e.g. sepsis-3 SOFA delta)
- Cost-sensitive metrics (calibration, decision curves)

These extensions are natural follow-ups; the harness already exposes
`compute_auroc` and the `BaselineReport` shape for reuse.
