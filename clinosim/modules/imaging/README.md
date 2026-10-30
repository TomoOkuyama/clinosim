# `clinosim.modules.imaging` — imaging study + series + radiology report

## Purpose

Always-on AD-55 module (Tier 1 #2 imaging chain, AD-62). Reads a
disease YAML's `imaging_orders[]` entries and materialises
`ImagingStudyRecord` + per-view `ImagingSeries` + `RadiologyReport`
under `CIFPatientRecord.extensions["imaging"]`. The FHIR builder
chain later emits `ImagingStudy` + `Endpoint` +
radiology `DiagnosticReport` + `ServiceRequest` from that CIF slot.

The **imaging-chain DRY rule** (AD-62, AGENTS.md): multi-view →
multi-series expansion logic MUST live in
`engine._expand_views_to_series`. New imaging orders MUST go through
[`clinosim.modules.order.engine.place_imaging_orders`](../order/engine.py)
— never set `imaging_modality` / `imaging_body_site_code` /
`imaging_views` directly at a call site.

## Scope

- **In scope**: `imaging_enricher` (POST_ENCOUNTER order=90);
  three YAML loaders (`load_modalities`, `load_body_sites`,
  `load_impression_templates`) with per-loader import-time validators
  (`_validate_modalities`, `_validate_body_sites`,
  `_validate_impression_templates`); the multi-view →
  multi-series expansion (`_expand_views_to_series`);
  procedure-code resolution
  (`_resolve_imaging_procedure_code_key`);
  DICOM UID derivation (`_study_uid_from`); body-site key
  canonicalisation (`_body_site_key_from_snomed`);
  report-template selection (`_select_report_template` +
  `_build_generic_negative_report`); `inference` submodule (case-D
  fallback that infers modality / body-site from `Order.display_name`
  using a whitelist regex — no guessing, missing pattern returns
  `None` and the enricher emits a stub study with no series, carrying
  `description = display_name` and a generic negative-findings
  report); per-encounter duplicate suppression (same start time +
  canonicalised display name, Issue #822) and series-as-studies
  consolidation (same CT / MR / US / XA modality + body site within
  60 min, Issue #918).
- **In scope (audit)**: [`audit.py`](audit.py) — fourth per-module
  AD-60 plug-in (after hai, antibiotic, order). Registers 7
  `canonical_constants` (`IMAGING_STUDY_ID_PREFIX`
  / `ENDPOINT_ID_PREFIX` / `RADIOLOGY_REPORT_ID_PREFIX` /
  `IMAGING_CATEGORY_SNOMED` / `IMAGING_CATEGORY_V2_0074` /
  `DICOM_UID_SYSTEM` / `DICOM_WADO_RS_CONNECTION_TYPE`); its 15-check
  `lift_firing_proof` covers 4 canonical-constant checks, 3 emission
  counts, 3 reference-integrity checks, and 5 no-drop invariants
  from the Section 3.4 emission matrix. `imaging_basedon_coverage`
  clinical axis requires 100 % of `ImagingStudy.basedOn` +
  `ImagingStudy.endpoint` refs to resolve (n<30 → WARN).
- **Out of scope**: imaging order placement itself (that is
  [`clinosim.modules.order.engine.place_imaging_orders`](../order/engine.py));
  FHIR `ImagingStudy` / `Endpoint` /
  radiology `DiagnosticReport` / `ServiceRequest` emission
  ([`output/fhir_r4/`](../output/fhir_r4/README.md)); PACS-side
  DICOM store (out of clinosim scope).

## Public API

```python
from clinosim.modules.imaging import (
    ImagingSeries,                   # dataclass re-export (types.imaging)
    ImagingStudyRecord,              # dataclass re-export
    RadiologyReport,                 # dataclass re-export
)
from clinosim.modules.imaging.engine import (
    imaging_enricher,                # POST_ENCOUNTER enricher entry
    load_modalities,                 # () -> dict (@lru_cache)
    load_body_sites,                 # () -> dict (@lru_cache)
    load_impression_templates,       # () -> dict (@lru_cache)
)
from clinosim.modules.imaging.inference import (
    infer_imaging_metadata,          # (display_name) -> dict | None (whitelist regex)
)
```

## Determinism

- Sub-seed offset `0x4947` (`"IG"`, Tier 1 #2 PR1) — registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["imaging"]`.
- Per-order sub-RNG:
  `derive_sub_seed(master_seed, offset, order_id)` — main patient
  RNG untouched (AD-16).
- DICOM Study Instance UIDs are derived from the sub-seed
  (`_study_uid_from(sub_seed, kind="study")`; series UIDs from
  `sub_seed + i`) so the same order always produces the same UID
  across runs.

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.codes.loader._load_system` — `_code_in_data` validator
  helper (matches `hai/engine.py` pattern).
- `clinosim.audit.registry` (via `audit.py`) — AD-60 audit
  registration.
- `clinosim.modules.output.fhir_r4` (via `audit.py` only) — canonical
  category / DICOM constants and the builders the firing proof
  exercises.
- `clinosim.types.encounter` — `OrderType`, `OrderStatus`.
- `clinosim.types.imaging` — `ImagingSeries`, `ImagingStudyRecord`,
  `RadiologyReport` (re-exported via `__init__.py`).
- `numpy`, `yaml`.

## Constants and configuration

- **Three YAMLs** ([`reference_data/`](reference_data/)):
  - `modalities.yaml` — modality catalog + `default_views_by_body_site`
    (empty-views fallback the order module consults).
  - `body_sites.yaml` — SNOMED body-site catalog.
  - `impression_templates.yaml` — per-modality / per-body-site
    negative and abnormal report templates.
- Each YAML has an import-time 6-layer `_validate_*` (empty top,
  required keys, forward + reverse coverage, per-entry required
  fields, cross-reference to SNOMED / LOINC / body-site canonical
  sets).
- **Canonical id + system constants**: the ID prefixes
  `IMAGING_STUDY_ID_PREFIX` (`"imgst-"`), `ENDPOINT_ID_PREFIX`
  (`"endpoint-"`), `RADIOLOGY_REPORT_ID_PREFIX` (`"imgrpt-"`) are
  owned by `engine.py` (writer side; the FHIR builders import them);
  `IMAGING_CATEGORY_SNOMED`, `IMAGING_CATEGORY_V2_0074`,
  `DICOM_UID_SYSTEM`, `DICOM_WADO_RS_CONNECTION_TYPE` are owned by the
  FHIR builders and imported by `audit.py`.
- **Consolidation** (`engine.py`): `_SERIES_AS_STUDIES_WINDOW_MIN = 60`,
  `_CONSOLIDATABLE_MODALITIES = {CT, MR, US, XA}` (CR is never
  consolidated — same-shift portable films are legitimate).
- **Inference whitelist** (`inference.py`): patterns MUST match on
  substring to fire; a missed match returns `None` so the enricher
  emits a stub study (no series, generic negative report) rather than
  dropping the order silently.

## Directory contents

```
clinosim/modules/imaging/
  __init__.py                      re-exports the three CIF types (ImagingStudyRecord / ImagingSeries / RadiologyReport)
  engine.py                        imaging_enricher + loaders + validators + multi-view expansion
  inference.py                     infer_imaging_metadata whitelist (case-D fallback)
  audit.py                         AD-60 audit plug-in #4 — 15-check lift_firing_proof + basedon_coverage
  reference_data/
    modalities.yaml                modality + default_views_by_body_site
    body_sites.yaml                SNOMED body-site catalog
    impression_templates.yaml      per-(modality × body_site) report templates
```

The module has **no `enricher.py`** — the enricher entry lives in
`engine.py` and is imported directly from there.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`~L380-391`):

- `name="imaging"`, `stage=POST_ENCOUNTER`, `order=90`,
  `enabled=lambda c: True`. Runs after `antibiotic` (order=85) and
  before `triage` (order=93) — imaging is independent of the HAI
  cascade but must precede the encounter-narrative stages.
- The `audit.py` module registers with the AD-60 audit framework at
  import time.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:385`](../../simulator/enrichers.py) | POST_ENCOUNTER order=90 registration. |
| Audit registry | [`clinosim/modules/imaging/audit.py`](audit.py) | AD-60 audit plug-in. |
| FHIR `ImagingStudy` / `Endpoint` / radiology `DiagnosticReport` / `ServiceRequest` builders | [`clinosim/modules/output/fhir_r4/`](../output/fhir_r4/) | Emit the four resource families from `extensions["imaging"]`. |
| Order module | [`clinosim/modules/order/engine.py`](../order/engine.py) | `place_imaging_orders` reads modality catalog's `default_views_by_body_site` for empty-views fallback. |

## Testing

```bash
pytest tests/unit -k "imaging" -q
pytest tests/integration -k "imaging" -q
clinosim audit run -d <cohort_dir> --module imaging
```

Individual files:

- [`tests/unit/test_types_imaging.py`](../../../tests/unit/test_types_imaging.py)
  — dataclass shape.
- [`tests/unit/test_imaging_audit.py`](../../../tests/unit/test_imaging_audit.py)
  — 15-check audit plug-in unit run.
- [`tests/unit/test_imaging_inference.py`](../../../tests/unit/test_imaging_inference.py)
  — whitelist regex coverage.
- [`tests/unit/output/test_fhir_imaging_study.py`](../../../tests/unit/output/test_fhir_imaging_study.py)
  — FHIR ImagingStudy emission unit.
- [`tests/integration/test_imaging_chain.py`](../../../tests/integration/test_imaging_chain.py),
  [`test_imaging_basedon_coverage.py`](../../../tests/integration/test_imaging_basedon_coverage.py),
  [`test_imaging_snapshot.py`](../../../tests/integration/test_imaging_snapshot.py),
  [`test_imaging_jp_localization.py`](../../../tests/integration/test_imaging_jp_localization.py),
  [`test_imaging_subprocess_fullpipeline.py`](../../../tests/integration/test_imaging_subprocess_fullpipeline.py),
  [`test_imaging_determinism.py`](../../../tests/integration/test_imaging_determinism.py)
  — cross-module + full-pipeline chain, basedOn coverage, snapshot,
  JP localization, determinism.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
