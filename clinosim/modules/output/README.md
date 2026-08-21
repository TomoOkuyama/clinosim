# `clinosim.modules.output` — output-adapter entry + CIF writer

## Purpose

The output layer that consumes generated CIF and emits every supported
downstream format. Owns the pluggable adapter registry (AD-58), the
CIF writer + reader, the built-in `csv` and `fhir-r4` adapters, and
the `hospital_course_extractor` helper the narrative pipeline uses to
build discharge-summary facts. FHIR R4 emission itself lives in the
[`fhir_r4/`](fhir_r4/README.md) subpackage.

## Scope

- **In scope**: `OutputAdapter` Protocol + `OutputContext` +
  `register_output_adapter` + `get_adapter` + `available_formats` +
  the two built-in adapters (`CsvAdapter`, `FhirR4Adapter`,
  registered lazily by `_ensure_builtins`); `write_cif` (JSON
  writer for structural CIF); `CIFReader` (merges structural CIF +
  a chosen narrative version, `resolve_current_narrative_dir`
  handles the `narratives/current_version.txt` pointer file);
  `HospitalCourseFact` + `extract_hospital_course` +
  the `summarize_*` helpers used by discharge-summary narratives;
  the FHIR-R4 subpackage entry re-exports (`register_bundle_builder`,
  `available_builders`).
- **Out of scope**: FHIR R4 emit logic itself
  ([`fhir_r4/`](fhir_r4/README.md) subpackage — resource builders,
  bundle assembly, post-processing); the CIF format itself
  ([`clinosim.types`](../../types/)); narrative content generation
  ([`document.narrative`](../document/narrative/README.md)).

## Public API

```python
# Adapter registry (AD-58)
from clinosim.modules.output import (
    register_output_adapter,     # (adapter) — plug-in registration
    register_bundle_builder,     # (fn) — FHIR R4 bundle builder registration
    available_builders,          # () -> list of registered builders
)
from clinosim.modules.output.adapter import (
    OutputContext,               # dataclass (country, narrative_version, options)
    OutputAdapter,               # runtime_checkable Protocol (format_id, description, subdir, convert)
    get_adapter,                 # (format_id) -> OutputAdapter (raises KeyError with available list)
    available_formats,           # () -> [(format_id, description), ...]
)

# Built-in adapter classes (registered via _ensure_builtins on demand)
from clinosim.modules.output.adapters_builtin import CsvAdapter, FhirR4Adapter

# CIF writer + reader
from clinosim.modules.output.cif_writer import write_cif                # (dataset, output_dir) -> None
from clinosim.modules.output.cif_reader import CIFReader, resolve_current_narrative_dir

# Narrative-facing extractor
from clinosim.modules.output.hospital_course_extractor import (
    HospitalCourseFact,
    extract_hospital_course,
    summarize_discharge_medications,
    summarize_procedures,
    summarize_admission_vitals,
    summarize_terminal_vitals,
)
```

Registered format identifiers: `"csv"`, `"fhir-r4"` (built-in). A
third-party adapter can register any new `format_id` at import time
without editing this facade.

## Determinism

Not applicable — the output layer is a pure serialiser over an
already-generated CIF. It uses no `rng` argument and no seed offset
in `ENRICHER_SEED_OFFSETS`. The `OutputContext.options` dict is
forward-compatible for format-specific settings but currently unused.

## Dependencies

- `clinosim.modules.output.fhir_r4` (subpackage) — the FHIR R4
  emission surface; re-exported through this package's `__init__`.
- `clinosim.types.output` — `CIFDataset`, manifest types.
- `clinosim.types.clinical` — `ClinicalDocument` +
  `ClinicalDocumentNarrative` (read by `CIFReader`).
- `yaml` — YAML pass-through (CIF is JSON but the CLI accepts
  YAML config).
- Standard library only for `adapter.py` / `adapters_builtin.py` /
  `cif_writer.py`.

## Constants and configuration

- **Adapter registry** (`_ADAPTERS` in `adapter.py`) — dict keyed by
  `format_id`. `_ensure_builtins` imports
  `clinosim.modules.output.adapters_builtin` once so the two
  built-in adapters self-register on first `get_adapter` /
  `available_formats` call.
- **Adapter shape**: `format_id` (registry key + CLI value),
  `description` (shown in CLI help + `available_formats()`),
  `subdir` (output subdirectory name), and a
  `convert(cif_dir, out_dir, ctx: OutputContext) -> None` method.
- **`OutputContext`**: `country` (`"US"` / `"JP"` default `"US"`),
  `narrative_version` (`"current"` resolves
  `cif/narratives/current_version.txt` with fallback to
  `"template"`; the CLI wires this from
  `export-fhir --narrative-version`), `options` (open-ended
  per-format dict).
- **FHIR builder registry**
  (`register_bundle_builder` / `available_builders`) — the AD-56
  plug-in surface for adding a new FHIR resource. Builders are
  callables of shape `(ctx: BundleContext) -> list[resource]`; the
  registry itself lives in
  [`fhir_r4/`](fhir_r4/README.md).
- **Backwards-compat shim**: `fhir_r4_adapter.py` re-exports the
  FHIR subpackage's public surface for the ~100 pre-migration
  callers (Issue #555 PR1). No `DeprecationWarning` — the shim is a
  cleanup rename, not a deprecation.

## Directory contents

```
clinosim/modules/output/
  __init__.py                        register_output_adapter + register_bundle_builder + available_builders
  adapter.py                         OutputAdapter Protocol + OutputContext + registry
  adapters_builtin.py                CsvAdapter + FhirR4Adapter (lazy-registered)
  cif_writer.py                      write_cif (JSON writer for structural CIF)
  cif_reader.py                      CIFReader (merges structural + narrative) + resolve_current_narrative_dir
  csv_adapter.py                     per-domain CSV emission (`convert_cif_to_csv`)
  hospital_course_extractor.py       HospitalCourseFact + extract_hospital_course + summarize_* (narrative helper)
  fhir_r4_adapter.py                 backwards-compat shim (re-exports fhir_r4/)
  fhir_r4/                           FHIR R4 emission subpackage (see fhir_r4/README.md)
  SPEC.md                            extended design reference (not runtime)
```

The module has **no `audit.py`, no `enricher.py`, no
`reference_data/`** at this level; per-family FHIR data lives inside
the `fhir_r4/` subpackage.

## Enricher wiring

Not applicable — the adapters are invoked at CLI export time
(`clinosim export`, `clinosim export-fhir`), not through
`register_builtin_enrichers`. There is no seed offset in
`ENRICHER_SEED_OFFSETS`.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| CLI `export` / `export-fhir` | [`clinosim/simulator/cli.py`](../../simulator/cli.py) | Calls `get_adapter(format_id).convert(cif_dir, out_dir, ctx)`. |
| Narrative pipeline | [`clinosim/modules/document/narrative/passes.py`](../document/narrative/passes.py) | Uses `CIFReader` to load structural + narrative-version-merged CIF. |
| Narrative discharge-summary | [`clinosim/modules/document/narrative/template_generator.py`](../document/narrative/template_generator.py) | Uses `extract_hospital_course` + `summarize_*` helpers to compose discharge-summary facts. |
| Third-party plug-ins | (user code) | Register custom adapters via `register_output_adapter(adapter)`; register custom FHIR bundle builders via `register_bundle_builder(fn)`. |

## Testing

```bash
pytest tests/unit -k "output or cif_reader or hospital_course" -q
pytest tests/integration -k "output or export" -q
```

Coverage: broad — search `tests/unit -k output` for the per-adapter
tests, CIF-reader tests, and hospital-course extractor tests.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
