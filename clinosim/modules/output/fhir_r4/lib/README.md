# `fhir_r4/lib/` — shared FHIR R4 builder library

## Purpose

Shared low-level fragment helpers imported by every clinical-domain
builder subpackage under [`fhir_r4/`](../README.md). This is the
leaf layer of the FHIR subsystem — each helper produces a FHIR
*fragment* (a Coding, a CodeableConcept, a Bundle entry, a UCUM
quantity, a JP eCS extension) rather than a top-level resource, so
resource-builder modules import from `lib.*` without cycling back
through the adapter facade.

The `_fhir_common` compat shim in
[`../../_fhir_common.py`](../../_fhir_common.py) still works via a
`DeprecationWarning` — new code imports directly from
`clinosim.modules.output.fhir_r4.lib.common` (Issue #545 rename).

## Scope

- **In scope**:
  - `common.py` — `BundleContext` dataclass (the read-only context
    every `_bb_*` builder receives) + fragment helpers
    (`_coding_with_display`, `build_ucum_quantity`,
    `_escape_html`, `survey_category`, `_social_category`,
    `loinc_coding`, `to_fhir_date`, `entry`), plus the eCS
    institution / department extensions and
    `attach_ecs_institutional_extensions`;
    `_FHIR_ID_PATTERN = re.compile(r"^[A-Za-z0-9\-\.]{1,64}$")`;
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
    URLs including `_JP_CONDITION_SEVERITY_CS` +
    `CLINOSIM_IDENTIFIER_SYSTEM_PREFIX = "urn:clinosim:identifier:"`.
  - `inline_bb.py` — legacy inline building-block builders that
    were not yet split into the seven clinical-domain subpackages;
    exports 11 `_bb_*` functions
    (`_bb_patient`, `_bb_coverage`, `_bb_encounters`,
    `_bb_conditions`, `_bb_occupation`, `_bb_vitals`,
    `_bb_medication_requests`, `_bb_discharge_medication_requests`,
    `_bb_medication_admins`, `_bb_procedures`, `_bb_practitioners`)
    that the parent facade still registers alongside the split
    builders. New builders MUST go into the clinical-domain
    subpackages; do not extend `inline_bb.py`.
  - `generator_metadata.py` — sidecar `_generator_metadata.json`
    emission at cohort export time. Constants:
    `_SIDECAR_FILENAME = "_generator_metadata.json"`,
    `_RECENT_MERGES_LIMIT = 30`, `_PR_NUMBER_RE = r"\(#(\d+)\)\s*$"`.
  - `ed_reattribution.py` — the `reattribute_encounter_to_ed_bridge`
    helper used by `convert_cif_to_fhir` when reattributing
    via-ED IMP encounters to a synthetic ED bridge encounter
    (N-3 PR #810 chain).
  - `ids.py` — ID-prefix constants for structural key systems
    (`structural_key_system(name)` returns the canonical URI).
- **Out of scope**: any FHIR-resource-specific builder — those live
  in the sibling clinical-domain subpackages.

## Public API

```python
from clinosim.modules.output.fhir_r4.lib.common import (
    BundleContext,                        # dataclass
    entry,                                # (resource) -> Bundle entry dict
    build_ucum_quantity,                  # (value, unit) -> {value, unit, system, code}
    survey_category,                      # () -> survey CodeableConcept
    loinc_coding,                         # (code, lang) -> {system, code, display}
    build_ecs_institution_extension,      # JP eCS institution
    build_ecs_department_extension,
    attach_ecs_institutional_extensions,
)
from clinosim.modules.output.fhir_r4.lib.localization import (
    localize_text,                        # (text_map, lang) -> str
)
from clinosim.modules.output.fhir_r4.lib.reference_data import (
    CLINOSIM_IDENTIFIER_SYSTEM_PREFIX,    # "urn:clinosim:identifier:"
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
from clinosim.modules.output.fhir_r4.lib.ids import structural_key_system
```

## Determinism

Not applicable — pure helpers over passed-in inputs. `generator_metadata`
reads the current git HEAD at export time to record the sidecar
provenance; the sidecar is intentionally not part of the byte-diff
scope (see `write_generator_metadata` docstring).

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`.
- `clinosim.codes` — `get_system_uri`, `lookup`.
- `clinosim.locale.loader` — locale display maps.
- `re`, `datetime`, `dataclasses` — standard library.
- No cycle back through the adapter facade.

## Constants and configuration

- **`_FHIR_ID_PATTERN`** (`common.py`) — the FHIR R4 spec-mandated
  id pattern (`[A-Za-z0-9\-\.]{1,64}`); every emission site is
  gated by `_fhir_id_is_spec_valid` (which lives in the parent
  facade) using this regex.
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
  common.py                          BundleContext + fragment helpers + eCS extensions + _FHIR_ID_PATTERN
  localization.py                    en / ja text localisation dispatch
  reference_data.py                  profile URIs + code-system URIs + clinosim identifier prefix
  inline_bb.py                       11 legacy _bb_* builders (do not extend — split to domain subpackages instead)
  generator_metadata.py              _generator_metadata.json sidecar emission
  ed_reattribution.py                reattribute_encounter_to_ed_bridge (N-3 PR #810)
  ids.py                             structural_key_system + ID-prefix helpers
```

## Testing

```bash
pytest tests/unit -k "fhir_common or lib or generator_metadata or ed_reattribution or structural_key" -q
```

The AD-60 audit plug-ins (hai, antibiotic, order, imaging,
document) import many constants from this layer for their
`canonical_constants` cross-checks; a rename here fails those audit
runs.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
