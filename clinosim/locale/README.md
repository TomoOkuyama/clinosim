# `clinosim.locale` — locale-specific config bundles

## Purpose

Ships the country-specific data bundles that the rest of the simulator
consumes: name pools, address formats, terminology mappings, code-
mapping tables, and locale-specific YAML overrides.

Two locales ship out of the box:

- **US** (`us/`) — English names, US address format, RxNorm / LOINC /
  ICD-10-CM code mappings.
- **JP** (`jp/`) — Japanese names + kana, JP address format
  (都道府県 / 市区町村 / 番地), YJ / JLAC10 / HOT / ICD-10-JP code
  mappings.

## Scope

- **In scope**: name pools, address templates, per-country code-
  mapping tables (drug / lab / procedure), locale-specific YAML
  overrides consumed by disease / observation / medication modules.
- **Out of scope**: the code registries themselves
  (`clinosim/codes/`), the modules that consume the locale data
  (`clinosim/modules/*/`), the top-level country configuration
  (`clinosim/config/{us,japan}.yaml`).

## Public API

```python
from clinosim.locale import (
    load_names,                  # (country) -> NamePool
    load_addresses,              # (country) -> AddressPool
    load_terminology,            # (domain, country) -> dict[str, str] (deprecated; see notes)
    load_formatting,             # (country) -> dict[str, Any] (deprecated; see notes)
)
```

`load_terminology` and `load_formatting` are legacy loaders retained
for backwards compatibility; new code should read the YAMLs directly
through the module that owns them (e.g. drug key → RxNorm / YJ
resolution goes through `clinosim.modules.antibiotic` via
`clinosim/locale/{us,jp}/code_mapping_drug.yaml`).

## Adding a new locale

1. Create `clinosim/locale/<cc>/` (two-letter country code, lowercase).
2. Populate the bundle following the shape of `us/` or `jp/`:
   - `names.yaml` — first / family / phonetic name pools.
   - `addresses.yaml` — postal-format templates and city / region pools.
   - `code_mapping_drug.yaml` — drug-key → national drug code
     resolution.
   - other `code_mapping_*.yaml` files as needed.
3. Add a top-level `clinosim/config/<country>.yaml` for the country
   defaults (encounter mix, disease prevalence weights, insurance
   patterns).
4. Extend the country dispatch in the modules that switch on
   `SimulatorConfig.country`.
5. Add integration tests covering the new country.

## Dependencies

- `clinosim.types` for the locale-related dataclasses.
- `pyyaml` for YAML loading.

## Constants and configuration

- Locale YAMLs are loaded via `@lru_cache` in `loader.py`; each
  loader has explicit `country` arguments so cache keys stay bounded.
- Bundle contents live under `clinosim/locale/<cc>/` and
  `clinosim/locale/shared/`.

## Directory contents

```
clinosim/locale/
  __init__.py           public API
  loader.py             @lru_cache YAML loaders
  us/                   US-specific bundle
    names.yaml
    addresses.yaml
    code_mapping_drug.yaml
    ...
  jp/                   JP-specific bundle
    names.yaml
    addresses.yaml
    code_mapping_drug.yaml
    ...
  shared/               data shared across locales (rare)
  _template/            new-locale scaffolding template
    README.md
```

## Testing

```bash
pytest tests/unit -k locale -q
pytest tests/integration -k locale -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
