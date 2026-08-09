# `clinosim.modules.imaging` — imaging metadata chain

## Purpose

Opt-in Module (AD-55, Tier 1 #2) that populates
`extensions["imaging"]: list[ImagingStudyRecord]` at the POST_ENCOUNTER
stage. Sits alongside the `device` / `hai` / `antibiotic` always-on
cascade (order 90 in the enricher pipeline).

Produces metadata only — no DICOM pixel data. Downstream FHIR builders
emit `ImagingStudy` + `Endpoint` (WADO base URL placeholder) +
`DiagnosticReport` (radiology variant).

## Scope

- **In scope**: enrichment of inpatient / ED encounters whose disease
  protocol calls for imaging, choice of modality + body site from the
  disease and encounter context, generation of a `RadiologyReport`
  (normal or abnormal impression per disease × modality template).
- **Out of scope**: DICOM pixel data (metadata only), MRI / ultrasound /
  fluoroscopy modality classes beyond PR1 scope (currently CR + CT),
  body sites beyond PR1 scope (currently chest + head), FHIR
  serialisation (in [`clinosim/modules/output/`](../output/README.md)).

PR1 scope in detail:

- **Modalities**: CR (plain X-ray), CT.
- **Body sites**: chest, head.
- **Diseases**: `bacterial_pneumonia` / `aspiration_pneumonia` /
  `hemorrhagic_stroke`.

## Public API

```python
from clinosim.modules.imaging import (
    enrich_imaging,                  # AD-56 post_records enricher entry
    load_modalities,                 # @lru_cache YAML loader
    load_body_sites,                 # @lru_cache YAML loader
    load_impression_templates,       # @lru_cache YAML loader
)
```

## Data types

- `ImagingStudyRecord` — the top-level per-study record
  (`clinosim/types/imaging.py`).
- `ImagingSeries` — a series inside a study.
- `RadiologyReport` — the impression / findings text (English +
  Japanese variants).

## Dependencies

- `clinosim.types.imaging` — `ImagingStudyRecord`, `ImagingSeries`,
  `RadiologyReport`.
- `clinosim.types.encounter` — `Order.imaging_modality`,
  `.imaging_body_site_code`, `.imaging_views`.
- `clinosim.simulator.helpers` (formerly `seeding`) —
  `ENRICHER_SEED_OFFSETS["imaging"] = 0x494D`, `derive_sub_seed`.
- `clinosim.simulator.enrichers` — POST_ENCOUNTER stage registration.

## Constants and configuration

- `ENRICHER_SEED_OFFSETS["imaging"] = 0x494D` (`"IM"`) — sub-seed
  offset.
- Modality definitions (DCM codes for CR / CT) live at
  `reference_data/modalities.yaml`.
- Body site definitions (SNOMED body-site codes + procedure codes for
  LOINC / CPT / JP-K) live at `reference_data/body_sites.yaml`.
- Impression templates (disease × modality × normal / abnormal) live
  at `reference_data/impression_templates.yaml`.

JJ1017 (JP procedure code system) references may appear in the
Japanese-language sections of the report templates; per policy §4 the
Japanese text of JJ1017 code entries is retained inline.

## Directory contents

```
clinosim/modules/imaging/
  __init__.py                    public API
  engine.py                      core pure functions
  enricher.py                    AD-56 post_records enricher (enrich_imaging)
  audit.py                       per-module audit spec
  reference_data/
    modalities.yaml              DCM modality definitions (CR + CT)
    body_sites.yaml              SNOMED body site + procedure codes (LOINC + CPT + JP-K)
    impression_templates.yaml    disease × modality × normal/abnormal templates
```

## Consumers

- `clinosim/modules/output/` — `_fhir_service_request`,
  `_fhir_imaging_study`, `_fhir_endpoint`, `_fhir_diagnostic_report`
  (radiology variant).

## Testing

```bash
pytest tests/unit -k imaging -q
pytest tests/integration -k imaging -q
```

## Related

- [DESIGN.md](../../../DESIGN.md) AD-62 — Imaging metadata-only chain
  with WADO-RS placeholder.
- Historical design spec:
  `docs/history/specs-archive/2026-06-30-tier1-imaging-chain-design.md`.
- [`docs/CONTRIBUTING-modules.md`](../../../docs/CONTRIBUTING-modules.md).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
