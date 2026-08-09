# `clinosim.config` — runtime configuration YAMLs

## Purpose

`clinosim.config` is a **YAML-only Python package**: `__init__.py` is
empty, and the directory exists to ship a set of runtime configuration
files at a stable import-adjacent path. The YAMLs describe hospital
capacity / operations, country defaults, and LLM-provider settings that
`clinosim.simulator` reads at startup.

Because these files ship inside the `clinosim` Python package, they are
accessible from an installed wheel via `importlib.resources` without
requiring a separate data-file path.

## Scope

- **In scope**: hospital-configuration YAMLs, country-default YAMLs,
  LLM-service YAMLs.
- **Out of scope**: reference clinical data (that lives in
  `clinosim/modules/*/reference_data/`), locale-specific data (that
  lives in `clinosim/locale/`), user-created dataset presets (those
  live at repo-root `datasets/`).

## Public API

There is no Python API. Consumers read the YAMLs via
`importlib.resources` or directly through the loaders in
`clinosim.simulator.helpers` and `clinosim.types.config`.

## Dependencies

None. `__init__.py` is empty.

## Constants and configuration

### `hospital_operations.yaml` (default: 50-bed community hospital)

Defines resource capacity, staffing, and daily patterns that determine
how long patients wait for tests, imaging, and procedures. Copy and
adjust to simulate a different hospital shape.

Key top-level keys:

| Key | Purpose | Example |
|---|---|---|
| `recommended_population` | Default catchment population (`US` / `JP` / `default`) | `40000` (US), `10000` (JP) |
| `imaging.wado_base_url` | WADO base URL for imaging Endpoint emission | `https://pacs.…/dicomweb` |
| `resource_capacity` | Analysers / scanners / OR / ED / inpatient beds | `inpatient_beds: 50` |
| `staffing` | Nursing / physician / pharmacy counts | (see file) |

### `hospital_small.yaml` / `hospital_large.yaml`

Alternate hospital sizes (50-bed community / 200-bed regional). Same
schema as `hospital_operations.yaml`; select via
`clinosim generate --hospital-config`.

### `japan.yaml` / `us.yaml`

Country-default overrides (encounter mix, disease prevalence weights,
insurance patterns, name / address formatting).

### `llm_service.yaml` / `llm_service.bedrock.yaml` / `llm_service.cloud.yaml`

LLM-provider configurations for narrative generation. See
[`clinosim/modules/llm_service/README.md`](../modules/llm_service/README.md)
for provider details.

## Directory contents

```
clinosim/config/
  __init__.py           (empty)
  hospital_operations.yaml   default 50-bed community hospital
  hospital_small.yaml        50-bed community
  hospital_large.yaml        200-bed regional
  japan.yaml                 JP country defaults
  us.yaml                    US country defaults
  llm_service.yaml           default LLM configuration
  llm_service.bedrock.yaml   AWS Bedrock configuration
  llm_service.cloud.yaml     cloud-hosted LLM configuration
```

## Testing

The YAMLs are validated at load time by `clinosim.types.config` and by
`clinosim.simulator`. A malformed YAML will fail unit tests that
instantiate `SimulatorConfig`.

```bash
pytest tests/unit -k config -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).
