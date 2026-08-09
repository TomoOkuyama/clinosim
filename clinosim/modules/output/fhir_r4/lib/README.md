# `fhir_r4/lib/` — shared FHIR-R4 builder helpers

## Purpose

Common utilities shared across every builder subpackage under
[`fhir_r4/`](../README.md): reference-data loading, per-locale
localisation dispatch, ID-prefix constants, inline building-block
helpers, generator-metadata emission, and the `common`-namespace
low-level primitives.

## Scope

- **In scope**: shared helpers imported by two or more builder
  subpackages; no domain-specific builders.
- **Out of scope**: any FHIR-resource-specific builder logic — those
  live in the sibling clinical-domain subpackages.

## Public API

```python
from clinosim.modules.output.fhir_r4.lib import (
    common,                      # low-level Coding / CodeableConcept helpers
    localization,                # en / ja text localisation dispatch
    reference_data,              # profile URIs, canonical URLs, code-system URLs
    inline_bb,                   # inline-building-block helpers
    generator_metadata,          # generation-metadata extension emitter
    ids,                         # resource-ID prefix constants
)
```

## Dependencies

- `clinosim.types` — FHIR-adjacent shared dataclasses.
- `clinosim.codes` — code-system lookups.
- `pyyaml` — reference-data loading.

## Constants and configuration

- Resource-ID prefixes (e.g. `DOC_REFERENCE_ID_PREFIX = "doc-"`) are
  defined in `ids.py` and imported by builders.
- JP-Core / JP-CLINS profile URIs and canonical URLs live in
  `reference_data/*.yaml` — the single source of truth referenced by
  every builder that stamps `meta.profile`.

## Directory contents

```
clinosim/modules/output/fhir_r4/lib/
  __init__.py               public API re-exports
  common.py                 Coding / CodeableConcept / Reference helpers
  localization.py           en / ja text dispatch
  reference_data.py         profile URI + canonical URL loader
  inline_bb.py              inline building-block helpers
  generator_metadata.py     Extension emitter for generator metadata
  ids.py                    resource-ID prefix constants
```

## Testing

```bash
pytest tests/unit -k fhir_r4_lib -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
