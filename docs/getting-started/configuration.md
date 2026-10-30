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
| `--format {cif,fhir-r4,csv}` | `cif` | One or more output formats (`fhir` is an alias of `fhir-r4`); each lands in its own subdirectory (`cif/`, `fhir_r4/`, `csv/`) |
| `--hospital-config PATH` | `clinosim/config/hospital_operations.yaml` | Hospital-shape override YAML |
| `--jp-insurance` / `--no-jp-insurance` | on | (JP only) Emit insurance enrollment / 被保険者番号 as FHIR Coverage |
| `--allow-legacy` | off | (JP only) Continue without the JP-CLINS package, emitting legacy 5-digit JLAC10 codes (otherwise a JP run without the package exits with an error) |
| `--cache-dir PATH` | unset | F4 memoize: reuse a previous snapshot output directory as a cache |
| `--log-file PATH` | `<output>/simulator.log` | Structured JSONL simulator log |

## Key environment variables

| Variable | Default | Meaning |
|---|---|---|
| `CLINOSIM_JP_CLINS_PKG_DIR` | unset | Path to the JP-CLINS package's `package/` directory. Searched first; otherwise the `fhir` CLI cache (`~/.fhir/packages/`) is used. `--country JP` needs the package (see [`jp-clins.md`](../jp-clins.md)) |
| `CLINOSIM_LOG_LEVEL` | `INFO` | Python logging level for the simulator (`DEBUG` / `INFO` / `WARNING` / `ERROR`) |
| `CLINOSIM_ALLOW_LEGACY_JP_CLINS_PKG` | unset | When set to `1`, equivalent to passing `--allow-legacy` (a JP run proceeds without the JP-CLINS package, emitting legacy 5-digit JLAC10 codes) |
| `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | AWS default chain | Only needed for AWS Bedrock narrative provider (`--provider bedrock`) |

## Named-preset datasets

Reproducible releases via preset config bundles:

```bash
clinosim dataset list                           # show available presets
clinosim dataset build jp-100 --output ./jp-100-out
```

## Hospital-config override

The default hospital shape (bed count, ward mix, staff roster) is loaded from `clinosim/config/hospital_operations.yaml`. `hospital_small.yaml` (10 beds) and `hospital_large.yaml` (200 beds) ship alongside it. To use a custom shape, pass `--hospital-config path/to/your.yaml`. See [`clinosim/config/README.md`](https://github.com/TomoOkuyama/clinosim/blob/master/clinosim/config/README.md) for the schema.
