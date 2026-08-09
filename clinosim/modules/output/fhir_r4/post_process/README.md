# `fhir_r4/post_process/` — bundle-level post-processing pipeline

## Purpose

Runs the final pass over the assembled FHIR bundle right before
NDJSON emission: reference resolution, code-value normalisation,
manifest-metadata attachment, JP-Core profile assertion, and any
cross-resource consistency fix-ups that cannot be done inside a
single per-resource builder.

## Scope

- **In scope**: bundle-level transformations that see every resource
  at once, cross-resource reference resolution, manifest / provenance
  metadata attachment.
- **Out of scope**: per-resource construction (in the sibling clinical-
  domain builder subpackages), NDJSON serialisation itself
  (`fhir_r4/__init__.py`'s emit path).

## Public API

Pipeline entries are dispatched through the parent facade
(`register_bundle_builder`), not called directly from outside.

## Dependencies

- Sibling `lib/` — shared helpers.
- `clinosim.types.output` — bundle-level manifest types.
- No dependency on any specific per-domain builder subpackage; this
  runs *after* they have all emitted their resources.

## Constants and configuration

- Any thresholds / expected-value maps used in the post-process
  pipeline live inside `post_process/` and are documented at their
  definition site.

## Directory contents

```
clinosim/modules/output/fhir_r4/post_process/
  __init__.py               subpackage facade
  (per-transform .py files, one per post-processing pass)
```

## Testing

```bash
pytest tests/unit -k post_process -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
