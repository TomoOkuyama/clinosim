# `clinosim.locale` — locale-specific config bundles

## Purpose

Ships the country-specific data bundles that the rest of the
simulator consumes: name pools, address formats, demographic
distributions, formatting rules, per-country code-mapping tables
(diagnosis / drug / lab / procedure), reference ranges, immunization
schedules, and identity conventions.

Two locales ship out of the box:

- **US** (`us/`) — English names, US address format, RxNorm / LOINC /
  ICD-10-CM code mappings, US-specific reference ranges and
  demographics.
- **JP** (`jp/`) — Japanese names + kana, JP address format
  (都道府県 / 市区町村 / 番地), YJ / JLAC10 / HOT / ICD-10-JP code
  mappings, Japanese identity conventions (マイナンバー) and
  microbiology / susceptibility mappings.

International code registries themselves (ICD, LOINC, RxNorm, …)
were migrated to [`clinosim.codes`](../codes/README.md) and no
longer live here.

## Scope

- **In scope**: name pools, address templates, demographics
  distributions, per-country code-mapping tables (drug / lab /
  procedure / diagnosis / microbiology), reference ranges,
  immunization schedules, formatting rules, and identity-format
  YAMLs consumed by disease / observation / medication modules.
- **Out of scope**: the international code registries themselves
  (`clinosim/codes/`), the modules that consume the locale data
  (`clinosim/modules/*/`), the top-level country configuration YAMLs
  (`clinosim/config/{us,japan}.yaml`).

## Public API

`clinosim/locale/__init__.py` is **empty by design** — callers import
the loader helpers directly:

```python
from clinosim.locale.loader import (
    load_names,                     # (country) -> dict[str, Any]
    load_addresses,                 # (country) -> dict[str, Any]
    load_demographics,              # (country) -> dict[str, Any]
    load_formatting,                # (country) -> dict[str, Any]
    load_reference_ranges,          # (country) -> dict[str, Any]
    load_identity_config,           # (country) -> dict[str, Any]
    load_naming_rules,              # (country) -> dict[str, Any]
    load_terminology,               # (domain, country) -> dict[str, str] (legacy)
    load_code_mapping,              # (domain, country) -> dict[str, str]
    load_chronic_medications,       # () -> dict[str, Any] (shared)
    load_chronic_followup,          # () -> dict[str, Any] (shared)
    load_med_terms_ja,              # () -> dict[str, dict[str, str]] (shared)
    load_drug_names_ja,             # () -> dict[str, str] (shared)
    load_department_display,        # () -> dict[str, dict[str, str]] (shared)
)
from clinosim.locale.text import (
    resolve_text,                   # (value, language, country) -> str
)
```

`load_terminology` and the older `load_formatting` are retained for
backwards compatibility; new code should read the YAMLs directly
through the module that owns them (e.g. drug key → RxNorm / YJ
resolution goes through `clinosim.modules.antibiotic` via
`clinosim/locale/{us,jp}/code_mapping_drug.yaml`).

## Determinism

Not applicable — the package is a data-loader layer. All loaders are
`@lru_cache`-decorated (bounded cache keys: country string), so
repeated calls return the identical `dict` instance. YAML parsing is
via `yaml.safe_load`, which is deterministic byte-in → dict-out.

## Dependencies

- `pyyaml` for YAML loading.
- Standard library `pathlib`, `functools`, `typing`.
- **No dependency on other `clinosim.*` packages** at import time —
  the loaders are pure YAML readers. Consumers pass the returned
  dicts into their own types.

## Constants and configuration

- **`_LOCALE_DIR`** = `Path(__file__).parent` — root of the locale
  bundle at import time.
- **`_COUNTRY_DIR_MAP`** = `{"JP": "jp", "US": "us"}` — country ISO
  code → directory name mapping. Unmapped codes fall through to
  `country.lower()`.
- **P2-14 safeguard** — `_country_dir` rejects any resolved directory
  name that starts with `_`. This prevents `_template/` (the
  new-locale scaffold) from ever being usable as a real country —
  attempting `country="_template"` raises `ValueError`. Adding a new
  country must not use a leading underscore.
- **`@lru_cache`** — all loaders are memoised; the cache key is the
  (country, [domain]) tuple, so cache size stays bounded across a
  run.
- **`resolve_text`** convention: a string value is returned as-is; a
  `{lang: string}` dict returns the requested language with a
  fallback to English. This is the mechanism modules use to keep
  YAML records human-readable in both locales without duplicating
  files.

## Directory contents

```
clinosim/locale/
  __init__.py                     (empty by design — import direct
                                   from .loader / .text)
  loader.py                       @lru_cache YAML loaders (14 public
                                   functions)
  text.py                         resolve_text (multi-language text
                                   resolution helper)
  us/                             US-specific bundle (12 YAMLs):
                                   addresses, code_mapping_{diagnosis,
                                   drug, lab, procedure}, code_status_rates,
                                   demographics, family_history_prevalence,
                                   formatting, immunization_schedule,
                                   names, reference_range_lab
  jp/                             JP-specific bundle (15 YAMLs — the US
                                   set plus care_level_rates, identity,
                                   code_mapping_microbiology,
                                   code_mapping_microbiology_susceptibility)
  shared/                         cross-locale data (6 YAMLs):
                                   chronic_followup, chronic_medications,
                                   department_display, drug_names_ja,
                                   med_terms_ja, naming_rules
  _template/                      new-locale scaffolding — README + all
                                   required YAMLs stubbed. Never resolvable
                                   as a country per the leading-underscore
                                   guard.
```

## Extending — adding a new locale

1. Create `clinosim/locale/<cc>/` (two-letter ISO country code,
   lowercase; **must not start with `_`**). Copy `_template/` as the
   scaffold.
2. Populate the bundle following the shape of `us/` or `jp/`:
   - `names.yaml` — first / family / phonetic name pools.
   - `addresses.yaml` — postal-format templates and city / region
     pools.
   - `demographics.yaml` — age / sex / ethnicity distributions.
   - `code_mapping_{diagnosis,drug,lab,procedure}.yaml` — clinical
     key → national code resolution.
   - `formatting.yaml` — phone / date / currency formatting.
   - `reference_range_lab.yaml` — country-typical lab reference
     intervals.
   - `immunization_schedule.yaml` — country vaccination schedule.
   - Other `code_mapping_*.yaml` files as needed (JP adds
     `microbiology` + `microbiology_susceptibility`).
3. Register the country in `_COUNTRY_DIR_MAP` if the ISO code
   does not map to the lowercase directory name directly.
4. Add a top-level `clinosim/config/<country>.yaml` for the country
   defaults (encounter mix, disease prevalence weights, insurance
   patterns).
5. Extend the country dispatch in the modules that switch on
   `SimulatorConfig.country`.
6. Add integration tests covering the new country.

See also [`docs/add-your-country.md`](../../docs/add-your-country.md).

## Testing

```bash
pytest tests/unit -k locale -q
pytest tests/integration -k locale -q
```

Thirteen test files reference `clinosim.locale`, covering loader
validation, `_template` guard, `resolve_text` fallback chain, and
per-country YAML shape assertions.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
