# `clinosim.modules.healthcare_system` — country-specific configuration loader

## Purpose

Single loader for the country-specific configuration bundle
(`HealthcareSystemConfig`) that other modules consult to switch
country-dependent behaviour: lab-order frequency, discharge criterion,
target length of stay, and the four code-system identifiers
(diagnosis / drug / lab / procedure). The YAML files live under
[`clinosim/config/`](../../config/), not under the module — this
module owns the load, cache, and country-dispatch contract.

## Scope

- **In scope**: reading `clinosim/config/{japan,us}.yaml` into a
  Pydantic `HealthcareSystemConfig`, per-country `@lru_cache`,
  country-string normalisation (`"JP"` → `japan.yaml`, `"US"` →
  `us.yaml`, anything else → `ValueError`).
- **Out of scope**: hospital-level layout / bed count / department
  operations (in [`clinosim/config/hospital_*.yaml`](../../config/)
  and consumed by [`clinosim.modules.facility`](../facility/README.md)),
  patient demographics / lab reference ranges / drug-code mapping
  (locale-scoped, in [`clinosim/locale/<country>/`](../../locale/)),
  cross-facility referral or scheduling (not modelled today),
  FHIR `Organization` emission (in
  [`clinosim.modules.output`](../output/README.md)).

## Public API

The module exposes a single function via the `loader` submodule; the
package's `__init__.py` is empty and callers import the loader
directly:

```python
from clinosim.modules.healthcare_system.loader import load_healthcare_config

cfg = load_healthcare_config("JP")
# cfg.lab_frequency_multiplier  -> 1.3
# cfg.discharge_criteria        -> "lab_normalization"
# cfg.diagnosis_code_system     -> "ICD-10"
```

`load_healthcare_config` is `@lru_cache(maxsize=2)`, so repeated
lookups within a run are free. The returned model is treated as
read-only by every consumer — do not mutate the shared instance.

## Determinism

The module makes no random draws; the loaded config is a pure
function of the country string (plus the on-disk YAML).

## Dependencies

- `yaml` — YAML parser.
- `clinosim.types.config` — `HealthcareSystemConfig` (Pydantic
  BaseModel).
- No dependency on any other `clinosim.modules.*` — this is a
  **leaf module** so every other module may depend on it without
  cycles.

## Constants and configuration

- [`clinosim/config/japan.yaml`](../../config/japan.yaml) and
  [`clinosim/config/us.yaml`](../../config/us.yaml) — the two config
  files. Fields (all documented in
  [`clinosim/types/config.py`](../../types/config.py)):
  - `country`: `"JP"` or `"US"`.
  - `lab_frequency_multiplier` (float, default `1.0`) — scales lab
    ordering rate downstream. JP config = `1.3`, US = `0.8`.
  - `discharge_criteria` (string, default `"lab_normalization"`)
    — `"lab_normalization"` (JP) or `"functional_recovery"` (US).
  - `target_los_multiplier` (float, default `1.0`) — JP = `1.0`,
    US = `0.35` (short LOS).
  - `diagnosis_code_system` (default `"ICD-10"`) — `"ICD-10"` (JP)
    or `"ICD-10-CM"` (US).
  - `drug_code_system` (default `"YJ"`) — `"YJ"` (JP) or
    `"RxNorm"` (US).
  - `lab_code_system` (default `"JLAC10"`) — `"JLAC10"` (JP) or
    `"LOINC"` (US).
  - `procedure_code_system` (default `"K-code"`) — `"K-code"` (JP)
    or `"CPT"` (US).
- Country dispatch table (in `loader.py`):
  `{"JP": "japan.yaml", "US": "us.yaml"}`. To add a country, add
  the YAML, extend the dict, and (if applicable) extend downstream
  modules that switch on the string values above.
- Extended reference material for future fields — comorbidity
  multipliers, insurance system tables, DPC / DRG parameters,
  screening programmes — is documented in the module's
  [`SPEC.md`](SPEC.md). The runtime `HealthcareSystemConfig` today
  is intentionally the minimal v0.1 subset.

## Directory contents

```
clinosim/modules/healthcare_system/
  __init__.py                     empty
  loader.py                       load_healthcare_config only
  SPEC.md                         extended v1+ design reference (not runtime data)
```

The module has **no `engine.py`, no `enricher.py`, no `audit.py`,
and no `reference_data/`** — its entire runtime surface is
`loader.py`.

## Enricher wiring

Not applicable — this is a loader, not an enricher. It is not
registered with `register_builtin_enrichers` and has no seed offset
in `ENRICHER_SEED_OFFSETS`.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Simulator boot | [`clinosim/simulator/engine.py`](../../simulator/engine.py) (`~L17`) | Imports `load_healthcare_config` and caches the result once per country per run; the `HealthcareSystemConfig` then reaches every module through `SimulatorConfig` propagation. |
| `HealthcareSystemConfig` field consumers | [`clinosim/types/config.py`](../../types/config.py) | Downstream modules read `discharge_criteria`, the `*_code_system` string, and the multipliers off the shared model. Search: `grep -rn "hc_config\." clinosim/`. |

## Testing

No dedicated tests today. The loader is exercised transitively by
any test that boots the simulator (e.g. `pytest tests/integration -q`).
Coverage gap tracked as a follow-up — a small unit test asserting
JP → `japan.yaml`, US → `us.yaml`, and `ValueError` on an unknown
code would be a low-cost win.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
