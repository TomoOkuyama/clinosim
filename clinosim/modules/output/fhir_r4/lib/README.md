# `fhir_r4/lib/` — shared FHIR R4 builder library

## Purpose

Shared low-level fragment helpers imported by every clinical-domain
builder subpackage under [`fhir_r4/`](../README.md). `common.py`,
`localization.py`, `reference_data.py` and `ids.py` are the leaf
layer — each helper produces a FHIR *fragment* (a Coding, a
CodeableConcept, a Bundle entry, a UCUM quantity, a JP eCS
extension) rather than a top-level resource, so resource-builder
modules import from them without cycling back through the adapter
facade. `inline_bb.py` is the exception: it imports builder helpers
from the domain subpackages (see below).

The former `_fhir_common` compat shim has been removed; import
directly from `clinosim.modules.output.fhir_r4.lib.common` (Issue
#545 rename).

## Scope

- **In scope**:
  - `common.py` — `BundleContext` dataclass (the read-only context
    every `_bb_*` builder receives) + fragment helpers
    (`_coding_with_display`,
    `_escape_html`, `survey_category`, `_social_category`,
    `loinc_coding`, `to_fhir_date`, `entry`, plus many dosage /
    route / diagnosis / datetime helpers), the eCS
    institution / department extensions and
    `attach_ecs_institutional_extensions`;
    `_JST_TZ_SUFFIX = "+09:00"` / `_UTC_TZ_SUFFIX = "Z"`;
    eCS placeholders (`_JP_ECS_INSTITUTION_PLACEHOLDER =
    "1300000000"`, `_JP_ECS_DEPARTMENT_PLACEHOLDER = "総合診療科"`)
    + extension URLs (`_JP_ECS_INSTITUTION_NUMBER_EXT_URL`,
    `_JP_ECS_DEPARTMENT_EXT_URL`,
    `_JP_ECS_INSTITUTION_ID_SYSTEM`).
  - `localization.py` — EN / JA text localisation dispatch (also
    handles the `_RATE_ADJUSTMENT_SUFFIX_RE` regex for lab-value
    display normalisation).
  - `reference_data.py` — profile URIs, canonical URLs, code-system
    URLs including `_JP_CONDITION_SEVERITY_CS`.
  - `inline_bb.py` — legacy inline building-block builders that
    were not yet split into the seven clinical-domain subpackages;
    exports 11 `_bb_*` functions
    (`_bb_patient`, `_bb_coverage`, `_bb_encounters`,
    `_bb_conditions`, `_bb_occupation`, `_bb_vitals`,
    `_bb_medication_requests`, `_bb_discharge_medication_requests`,
    `_bb_medication_admins`, `_bb_procedures`, `_bb_practitioners`)
    that the parent `builder.py` registers alongside the split
    builders. It imports `_build_*` helpers from the clinical-domain
    subpackages and also carries its own copy of `_FHIR_ID_PATTERN`.
    New builders MUST go into the clinical-domain
    subpackages; do not extend `inline_bb.py`.
  - `generator_metadata.py` — sidecar `_generator_metadata.json`
    emission at cohort export time. Constants:
    `_SIDECAR_FILENAME = "_generator_metadata.json"`,
    `_RECENT_MERGES_LIMIT = 30`, `_PR_NUMBER_RE = r"\(#(\d+)\)\s*$"`.
  - `ed_reattribution.py` — the `reattribute_encounter_to_ed_bridge`
    helper used by `convert_cif_to_fhir` when reattributing
    via-ED IMP encounters to a synthetic ED bridge encounter
    (N-3 PR #810 chain).
  - `ids.py` — opaque Resource.id derivation (Issue #349):
    `CLINOSIM_IDENTIFIER_SYSTEM_PREFIX = "urn:clinosim:identifier:"`,
    `structural_key_system(kind)` (returns
    `urn:clinosim:identifier:<kind>`), `derive_opaque_id`,
    `wrap_as_identifier`.
- **Out of scope**: any FHIR-resource-specific builder — those live
  in the sibling clinical-domain subpackages.

## Public API

```python
from clinosim.modules.output.fhir_r4.lib.common import (
    BundleContext,                        # dataclass
    entry,                                # (resource) -> Bundle entry dict
    survey_category,                      # () -> survey CodeableConcept
    loinc_coding,                         # (code, lang) -> {system, code, display}
    build_ecs_institution_extension,      # JP eCS institution
    build_ecs_department_extension,
    attach_ecs_institutional_extensions,
)
from clinosim.modules.output.fhir_r4.lib.localization import (
    localize_drug_name,                   # (drug_name, lang) -> str
    localize_fixed_label,                 # (en_label, country) -> str
)
from clinosim.modules.output.fhir_r4.lib.inline_bb import (
    # 11 legacy _bb_* builders (registered by the parent facade)
    _bb_patient, _bb_coverage, _bb_encounters, _bb_conditions,
    _bb_occupation, _bb_vitals, _bb_medication_requests,
    _bb_discharge_medication_requests, _bb_medication_admins,
    _bb_procedures, _bb_practitioners,
)
from clinosim.modules.output.fhir_r4.lib.generator_metadata import write_generator_metadata
from clinosim.modules.output.fhir_r4.lib.ed_reattribution import reattribute_encounter_to_ed_bridge
from clinosim.modules.output.fhir_r4.lib.ids import (
    CLINOSIM_IDENTIFIER_SYSTEM_PREFIX,    # "urn:clinosim:identifier:"
    structural_key_system,                # (kind) -> URI
    derive_opaque_id,                     # (prefix, structural_key, hash_len=12) -> str
    wrap_as_identifier,                   # (structural_key, system) -> Identifier dict
)
```

## Determinism

Not applicable — pure helpers over passed-in inputs. `generator_metadata`
reads the current git HEAD at export time to record the sidecar
provenance; the sidecar is intentionally not part of the byte-diff
scope (see `write_generator_metadata` docstring).

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `is_us`, `resolve_lang`,
  `strip_protocol_prefix`.
- `clinosim.codes` — `get_system_uri`, `lookup`.
- `clinosim.locale.loader` — locale display maps + code mappings.
- `yaml`, `re`, `datetime`, `dataclasses` — YAML-backed lookup
  tables + standard library.
- `inline_bb.py` / `ed_reattribution.py` import the clinical-domain
  subpackages; nothing in `lib/` imports the `builder.py` facade.

## Constants and configuration

- **`_FHIR_ID_PATTERN`** — the FHIR R4 spec-mandated id pattern
  (`[A-Za-z0-9\-\.]{1,64}`). Not in `common.py`: it is defined in
  `../builder.py` (used by `_fhir_id_is_spec_valid`, a fail-soft
  check in the NDJSON writer), with copies in `inline_bb.py` and
  `../post_process/profile.py`.
- **`_JST_TZ_SUFFIX = "+09:00"`** / **`_UTC_TZ_SUFFIX = "Z"`** —
  timezone-suffix constants for `to_fhir_date` + downstream
  post-processing.
- **`CLINOSIM_IDENTIFIER_SYSTEM_PREFIX = "urn:clinosim:identifier:"`**
  — namespace prefix for every clinosim-internal identifier system
  (`HAI_EVENT_ID_SYSTEM`, staff identifier system, etc.).
- **eCS placeholders** — used when the cohort does not have a real
  institution number / department code (JP eCS profile requires
  the fields; the placeholders satisfy the cardinality without
  claiming a real facility).
- **`_RECENT_MERGES_LIMIT = 30`** (`generator_metadata.py`) — cap on
  the number of recent-merge PR numbers recorded in the sidecar.

## Directory contents

```
clinosim/modules/output/fhir_r4/lib/
  __init__.py                        namespace-only (no re-exports)
  common.py                          BundleContext + fragment helpers + eCS extensions + tz suffix constants
  localization.py                    en / ja text localisation dispatch
  reference_data.py                  profile URIs + code-system URIs
  inline_bb.py                       11 legacy _bb_* builders (do not extend — split to domain subpackages instead)
  generator_metadata.py              _generator_metadata.json sidecar emission
  ed_reattribution.py                reattribute_encounter_to_ed_bridge (N-3 PR #810)
  ids.py                             CLINOSIM_IDENTIFIER_SYSTEM_PREFIX + structural_key_system + derive_opaque_id + wrap_as_identifier
```

## Testing

```bash
pytest tests/unit -k "fhir_common or lib or generator_metadata or ed_reattribution or structural_key" -q
```

The AD-60 audit plug-ins (hai, antibiotic, order, imaging,
document, triage) import many constants from this layer for their
`canonical_constants` cross-checks; a rename here fails those audit
runs.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
