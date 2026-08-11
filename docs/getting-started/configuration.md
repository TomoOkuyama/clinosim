# Configuration

Runtime configuration is loaded from `clinosim/config/*.yaml`. The tables below list the most-used CLI flags and environment variables. For the definitive machine-readable list, run `clinosim simulate --help`.

## Key CLI flags (`clinosim simulate`)

| Flag | Default | Meaning |
|---|---|---|
| `--country {US,JP}` | `US` | Locale — controls names / addresses / insurance / code systems |
| `--population N` | catchment default from hospital config | Population size (persons) |
| `--seed N` | `42` | Deterministic seed (AD-16 invariant) |
| `--start YYYY-MM-DD` / `--end YYYY-MM-DD` | past 1 year ending today | Simulation window |
| `--output PATH` | `./output` | Output directory |
| `--format {cif,fhir-r4,csv}` | `cif` | One or more output formats |
| `--hospital-config PATH` | `hospital_operations.yaml` | Hospital-shape override YAML |

## Key environment variables

| Variable | Default | Meaning |
|---|---|---|
| `CLINOSIM_JP_CLINS_PKG_DIR` | unset | Path to the JP-CLINS package directory (required for JP-CLINS lab-compliance gate; see [`jp-clins.md`](../jp-clins.md)) |
| `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | AWS default chain | Only needed for AWS Bedrock narrative provider (`--provider bedrock`) |

## Named-preset datasets

Reproducible releases via preset config bundles:

```bash
clinosim dataset list                           # show available presets
clinosim dataset build jp-100 --output ./jp-100-out
```

## Hospital-config override

The default hospital shape (bed count, ward mix, staff roster) is loaded from `hospital_operations.yaml`. To use a custom shape, pass `--hospital-config path/to/your.yaml`. See [`../architecture/module-architecture.md`](../architecture/module-architecture.md) for the schema.
