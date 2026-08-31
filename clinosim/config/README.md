# `clinosim.config` — runtime configuration YAMLs

## Purpose

`clinosim.config` is a **YAML-only Python package**: `__init__.py` is
empty, and the directory exists to ship a set of runtime configuration
files at a stable import-adjacent path. The YAMLs describe hospital
capacity / operations, country defaults (US / JP), and LLM-provider
settings that `clinosim.simulator` reads at startup.

Because these files ship inside the `clinosim` Python package, they
are accessible from an installed wheel via `importlib.resources` (or
by string path from the source tree) without requiring a separate
data-file path.

## Scope

- **In scope**: hospital-configuration YAMLs, country-default YAMLs
  (`us.yaml` / `japan.yaml`), LLM-service YAMLs (base +
  provider-specific overrides).
- **Out of scope**: reference clinical data (that lives in
  `clinosim/modules/*/reference_data/`), locale-specific data (that
  lives in `clinosim/locale/`), user-created dataset presets (those
  live at repo-root `datasets/`), release-artefact configuration
  (that lives in `pyproject.toml`).

## Public API

There is no Python API. `__init__.py` is empty by design. Consumers
read the YAMLs either through the loaders in
`clinosim.simulator.helpers` and `clinosim.types.config`, or directly
via `importlib.resources.files("clinosim.config") / "<name>.yaml"`.

## Determinism

Not applicable — the package ships static data and holds no runtime
logic. YAMLs are loaded lazily by consumers; a given file's byte
contents produce the same in-memory dict on every load (subject to
YAML library determinism, which is guaranteed for the safe-loader
subset the project uses).

## Dependencies

None at package level. Consumers pull in `pyyaml` themselves.

## Constants and configuration

### `hospital_operations.yaml` — default 50-bed community hospital

Defines resource capacity, staffing, and daily patterns that
determine how long patients wait for tests, imaging, and procedures.
Copy and adjust to simulate a different hospital shape.

Key top-level keys:

| Key | Purpose | Example |
|---|---|---|
| `recommended_population` | Default catchment population per country (`US` / `JP` / `default`) | `US: 40000`, `JP: 10000`, `default: 40000` |
| `imaging.wado_base_url` | WADO base URL for imaging Endpoint emission | `https://wado.clinosim.example/dicomweb` |
| `available_departments` | Departments that exist at this hospital | `internal_medicine`, `cardiology`, … |
| `resource_capacity` | Analysers / scanners / OR / ED / inpatient beds | `inpatient_beds: 50`, `ed_beds: <n>` |
| `staffing` | Nursing / physician / pharmacy counts | (see file) |

### `hospital_small.yaml` / `hospital_large.yaml`

Alternate hospital sizes:

- `hospital_small.yaml` — **10-bed clinic** with inpatient beds,
  recommended catchment `12000`. Suitable for outpatient-heavy
  simulations with occasional short admissions.
- `hospital_large.yaml` — **200-bed regional hospital**, 20 ED beds.
  Full-service teaching / regional referral shape.

Both share the schema of `hospital_operations.yaml`; select at
generation time via `clinosim simulate --hospital-config <path>`.

### `japan.yaml` / `us.yaml`

Country-default overrides. Each declares `country: "JP" | "US"` and
country-specific clinical practice knobs:

- `lab_frequency_multiplier` (JP: 1.3, US: 0.8) — scales the per-day
  lab-order rate for the country's practice pattern.
- `discharge_criteria` (JP: `lab_normalization`, US:
  `functional_recovery`) — the gate the discharge engine watches.
- `target_los_multiplier` (JP: 1.0, US: 0.35) — country-typical LOS
  scaling.
- Coding-system defaults (ICD-10-CM vs ICD-10 for diagnoses, RxNorm
  vs YJ for medications, CPT vs K-codes for procedures).

### `llm_service.yaml` and provider overrides

- `llm_service.yaml` — default LLM configuration.
- `llm_service.bedrock.yaml` — AWS Bedrock provider.
- `llm_service.cloud.yaml` — cloud-hosted LLM provider (e.g. Anthropic
  API direct).
- `llm_service.sakura.yaml` — Sakura Internet GPU provider (see
  [`docs/sakura_gpu_setup.md`](../../docs/sakura_gpu_setup.md)).

See
[`clinosim/modules/llm_service/README.md`](../modules/llm_service/README.md)
for how the LLM service consumes these files and switches between
providers.

## Directory contents

```
clinosim/config/
  __init__.py                   (empty by design)
  determinism.yaml              transcendental-precision knobs
                                (mpmath prec / RNG proxy — see
                                clinosim/determinism.py)
  hospital_operations.yaml      default 50-bed community hospital
  hospital_small.yaml           10-bed clinic
  hospital_large.yaml           200-bed regional hospital
  japan.yaml                    JP country defaults
  us.yaml                       US country defaults
  llm_service.yaml              default LLM configuration (Ollama)
  llm_service.bedrock.yaml      AWS Bedrock provider
  llm_service.cloud.yaml        cloud-hosted LLM provider
                                (Anthropic API direct)
  llm_service.sakura.yaml       Sakura Internet GPU provider
```

## Testing

The package has no direct tests (no test file imports
`clinosim.config`). The YAMLs are exercised indirectly by every
integration test that instantiates `SimulatorConfig`, and are
schema-validated at load time by `clinosim.types.config`. A malformed
YAML fails those tests fast.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
