# `clinosim.modules.document` — clinical document assembly

## Purpose

Always-on Module (AD-55, Tier 1 #3) that generates clinical narrative
documents — admission notes, progress notes, discharge summaries — for
inpatient / outpatient / ED encounters, and emits them as FHIR
`DocumentReference` and `Composition` resources downstream.

Provides the skeleton: the `DocumentTypeSpec` registry that defines
which document types exist and which sections they contain, and the
`NarrativeContext` factory that assembles the input needed by narrative
generators.

## Scope

- **In scope**: document type registry (`DocumentTypeSpec`),
  `NarrativeContext` construction, POST_ENCOUNTER enricher orchestration,
  extraction of narrative-relevant facts from CIF records, coordination
  with the narrative subpackage.
- **Out of scope**: the narrative-text rendering itself (that lives in
  the [`narrative/`](narrative/README.md) subpackage), FHIR
  serialisation (in [`clinosim/modules/output/`](../output/README.md)),
  document storage or retrieval (this module emits records only).

## Public API

```python
from clinosim.modules.document import (
    DOCUMENT_TYPE_REGISTRY,      # {DocumentType → DocumentTypeSpec}
    build_narrative_context,     # (record, encounter, ...) -> NarrativeContext
    enrich_documents,            # AD-56 post_records enricher entry
)
```

Sub-package [`narrative/`](narrative/README.md) exports the two
generator classes (`TemplateNarrativeGenerator`,
`LLMNarrativeGenerator`) and the caching layer.

## Dependencies

- `clinosim.types.document` — `DocumentType`, `FormatType`,
  `DocumentTypeSpec`, `NarrativeContext`, `NarrativeOutput`,
  `NarrativeGenerator` (Protocol).
- `clinosim.types.allergy` — `Allergy` (referenced in
  `NarrativeContext`).
- `clinosim.modules._shared` — `get_attr_or_key` (dict / dataclass
  dual-access helper).
- `clinosim.modules.disease` — `load_disease_protocol` (for
  narrative context enrichment).
- `clinosim.modules.document.narrative` — the actual generators.

## Constants and configuration

- Document type registry is code-level (`DOCUMENT_TYPE_REGISTRY`
  populated at import time).
- `ENRICHER_SEED_OFFSETS["document"]` — sub-seed offset per AD-16
  determinism convention.
- No YAML configuration at this level. Narrative-side configuration
  lives in [`narrative/`](narrative/README.md).

## Directory contents

```
clinosim/modules/document/
  __init__.py                   public API
  engine.py                     document type registry + fact extraction
  enricher.py                   AD-56 post_records enricher
  audit.py                      per-module audit spec
  narrative/                    narrative-generation subpackage (see its README)
  reference_data/               document-type reference data
```

## Testing

```bash
pytest tests/unit -k document -q
pytest tests/integration -k document -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
