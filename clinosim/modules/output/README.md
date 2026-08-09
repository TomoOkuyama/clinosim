# `clinosim.modules.output` — output-adapters entry point

## Purpose

Public entry point for serialising a generated cohort (`CIFDataset`)
into any supported downstream format. The current formats are FHIR R4
Bulk-Data NDJSON, CIF-JSON, and per-domain CSV. Provider registration
is dynamic, so new formats plug in without changing this facade.

## Scope

- **In scope**: adapter registry (`get_adapter` / `register_adapter`),
  the `Adapter` protocol, top-level `convert()` orchestration, CIF-
  JSON and CSV adapters.
- **Out of scope**: FHIR R4 emit logic (that lives in the
  [`fhir_r4/`](fhir_r4/README.md) subpackage), the CIF format itself
  (defined in [`clinosim.types`](../../types/README.md)), the
  hospital-course extractor used by discharge-summary narratives (see
  `hospital_course_extractor.py` — internal helper for the narrative
  pipeline).

## Public API

```python
from clinosim.modules.output import (
    Adapter,                     # Protocol every adapter satisfies
    get_adapter,                 # (name) -> Adapter
    register_adapter,            # (name, adapter) — plugin registration
    convert,                     # (cif_dataset, format, output_dir, ...) -> None
)
```

Format identifiers currently registered: `"fhir-r4"`, `"cif"`, `"csv"`.

## Dependencies

- `clinosim.types.output` — `CIFDataset` and manifest types.
- `pyyaml` — YAML round-tripping for CIF adapter.
- Subpackage [`fhir_r4/`](fhir_r4/README.md) — FHIR R4 emission.

## Constants and configuration

- Adapter registration happens at import time (see the top of
  `__init__.py`).
- FHIR-specific constants (resource-id prefixes, profile URLs) live
  inside [`fhir_r4/lib/`](fhir_r4/lib/README.md).
- No runtime YAML configuration at this level.

## Directory contents

```
clinosim/modules/output/
  __init__.py                       public API
  adapter.py                        Adapter Protocol + registry
  cif_adapter.py                    CIF-JSON adapter
  csv_adapter.py                    per-domain CSV adapter
  hospital_course_extractor.py      internal narrative helper
  audit.py                          per-module audit spec
  fhir_r4/                          FHIR R4 output subpackage (see its README)
```

## Testing

```bash
pytest tests/unit -k output -q
pytest tests/integration -k output -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
