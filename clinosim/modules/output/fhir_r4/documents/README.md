# `fhir_r4/documents/` — clinical document FHIR R4 builders

## Purpose

Emits FHIR R4 resources for clinical documents: `Composition`
(structured clinical document), `DocumentReference` (metadata pointer
to the narrative text).

## Scope

- **In scope**: `Composition` builder (per-section assembly, JP-CLINS
  Composition profile compliance for JP), `DocumentReference` builder
  (metadata + content-attached-text emission).
- **Out of scope**: document-type registry (in
  [`clinosim.modules.document/`](../../../document/README.md)),
  narrative-text generation (in
  [`clinosim.modules.document.narrative/`](../../../document/narrative/README.md)),
  narrative version tracking (managed by the CIF-writer, see
  [`clinosim.modules.output/`](../../README.md)).

## Public API

Builders are dispatched through the parent facade
(`register_bundle_builder`), not called directly from outside.

## Constants and configuration

- Composition section IDs and LOINC document-type codes come from
  the `DocumentTypeSpec` registry in
  [`clinosim.modules.document/`](../../../document/README.md).
- Resource-ID prefixes:
  - `DOC_REFERENCE_ID_PREFIX = "doc-"`
  - `COMPOSITION_ID_PREFIX = "comp-"`
  (defined in [`lib/ids.py`](../lib/README.md)).
- JP-CLINS Composition profile URIs for eCS document types come from
  [`lib/reference_data/`](../lib/README.md).

## Dependencies

- `clinosim.types.clinical` — `ClinicalDocument`.
- `clinosim.types.document` — `DocumentType`, `DocumentTypeSpec`.
- Sibling `lib/` — shared helpers.

## Directory contents

```
clinosim/modules/output/fhir_r4/documents/
  __init__.py               subpackage facade
  composition.py            Composition builder
  document_reference.py     DocumentReference builder
```

## Testing

```bash
pytest tests/unit -k documents -q
pytest tests/integration -k composition -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
