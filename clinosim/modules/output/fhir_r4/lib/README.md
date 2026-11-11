# `fhir_r4/lib/` — shared FHIR R4 builder library

## Purpose

Shared low-level fragment helpers imported by every clinical-domain
builder subpackage under [`fhir_r4/`](../README.md). `common.py`,
`context.py`, `dosage.py`, `ecs_extensions.py`, `fhir_time.py`,
`localization.py`, `reference_data.py` and `ids.py` are the leaf
layer — each helper produces a FHIR *fragment* (a Coding, a
CodeableConcept, a Bundle entry, a UCUM quantity, a Dosage, a
datetime string, a JP eCS extension) or the shared `BundleContext`
rather than a top-level resource, so resource-builder modules import
from them without cycling back through the adapter facade.
`inline_bb.py` and `ed_reattribution.py` are the exceptions: they
import builder helpers from the domain subpackages (see below).

The former `_fhir_common` compat shim has been removed; import
directly from the `lib` module that owns a helper (Issue #545
rename).

## Scope

- **In scope**:
  - `context.py` — `BundleContext` dataclass (the read-only context
    every `_bb_*` builder receives).
  - `common.py` — fragment helpers: `entry`, `survey_category(lang)`,
    `build_address`, `build_telecom`, `build_presented_form`,
    `build_reference_range`, `build_diagnosis_codeable_concept`,
    `iter_diagnosis_mapping_targets`, `infer_severity`,
    `severity_coding`, `make_participant`, `map_encounter_status`,
    plus non-exported helpers (`system_coding`, `dual_slot_concept`,
    `display_entry`, `_escape_html`, `_social_category`).
  - `ecs_extensions.py` — the JP-CLINS eCS institution / department
    extensions (`build_ecs_institution_extension`,
    `build_ecs_department_extension`,
    `attach_ecs_institutional_extensions`); the institution number is
    the hospital's 10-digit 医療機関コード (`hospital_institution_code`,
    from `locale/jp/facility_identity.yaml`, Issue #3129);
    `_JP_ECS_DEPARTMENT_PLACEHOLDER` = the JA display of the
    `primary_care` department + extension URLs
    (`_JP_ECS_INSTITUTION_NUMBER_EXT_URL`,
    `_JP_ECS_DEPARTMENT_EXT_URL`, `_JP_ECS_INSTITUTION_ID_SYSTEM`).
  - `jp_profiles.py` — JP Core / JP-CLINS profile and
    identifier-system URIs used in more than one place (`JP_*_PROFILE`,
    `JP_*_SYSTEM`); every builder imports these instead of writing the
    literal (Issue #2842, guarded by
    `tests/unit/output/test_jp_uri_constants_2842.py`).
  - `profile_meta.py` — `profile_meta(resource_type, country, *fhir_profiles)`
    / `declared_profiles(...)`: the `meta.profile` URLs of a resource type
    for the FHIR profiles the country profile applies
    (`profile.uses(name)`), read from
    `clinosim/codes/data/fhir-profiles-<name>.yaml` (Issue #3145). A
    `<ResourceType>/<variant>` key (`Observation/LabResult`,
    `DiagnosticReport/Radiology`, ...) reads the table's `variants`
    section, for a profile variant the builder declares itself (Issue #3201).
  - `dosage.py` — MedicationRequest / MedicationAdministration
    Dosage helpers (`build_dosage_instruction`, `build_route_concept`,
    `canonicalize_route`, `augment_iv_dosage_with_rate`,
    `resolve_iv_infusion_default`, `map_mar_status`, and the
    re-exported `strip_protocol_prefix`). `patientInstruction` is composed
    by the output language's entry in `_PATIENT_INSTRUCTION_COMPOSERS`
    (Japanese: route templates from `locale/jp/patient_instructions_ja.yaml`);
    other languages use the frequency timing phrase (Issue #3216).
  - `fhir_time.py` — FHIR date / dateTime / instant formatting
    (`to_fhir_date`, `to_fhir_datetime`, `to_fhir_instant`,
    `tz_suffix_for_country`, `derive_meta_last_updated`) with
    `_JST_TZ_SUFFIX = "+09:00"` / `_UTC_TZ_SUFFIX = "Z"`.
  - `localization.py` — EN / JA text localisation dispatch
    (`localize_drug_name`, `localize_fixed_label`, `code_lookup`,
    and re-exports of the free-text translator, which now lives in
    `clinosim.locale.free_text` together with the
    `_RATE_ADJUSTMENT_SUFFIX_RE` regex).
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
    subpackages. New builders MUST go into the clinical-domain
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

`lib/__init__.py` is a namespace stub (`__all__ = []`); each module
declares its own `__all__`. The most-used entry points:

```python
from clinosim.modules.output.fhir_r4.lib.context import BundleContext   # dataclass
from clinosim.modules.output.fhir_r4.lib.common import (
    entry,                                # (resource) -> Bundle entry dict
    survey_category,                      # (lang) -> survey category CodeableConcept list
)
from clinosim.modules.output.fhir_r4.lib.ecs_extensions import (
    build_ecs_institution_extension,      # (country) -> JP eCS institution extension
    build_ecs_department_extension,       # (department_text="") -> extension
    attach_ecs_institutional_extensions,
)
from clinosim.modules.output.fhir_r4.lib.dosage import (
    build_dosage_instruction,             # (order, country="US") -> Dosage | None
    build_route_concept,                  # (raw_route, country) -> CodeableConcept | None
    map_mar_status,                       # (status) -> MedicationAdministration.status
)
from clinosim.modules.output.fhir_r4.lib.fhir_time import (
    to_fhir_date, to_fhir_datetime, to_fhir_instant,
    tz_suffix_for_country, derive_meta_last_updated,
)
from clinosim.modules.output.fhir_r4.lib.localization import (
    localize_drug_name,                   # re-exported from clinosim.locale.free_text
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

- `clinosim.modules._shared` — `strip_protocol_prefix`; `clinosim.countries` — `lang_for`.
- `clinosim.codes` — `get_system_uri`, `lookup`, `display`,
  `is_english_only_system`; `codes.icd10`, `codes.prefectures`,
  `codes.ucum`, `codes.snomed`, `codes.procedures`, `codes.drugs`.
- `clinosim.locale` — `loader` (display maps, code mappings,
  reference ranges, frequency tokens, IV-infusion defaults),
  `loaders.medical_display`, `localized`, `table`, `free_text`.
- `clinosim.datafiles` — `load_data_yaml` (`dosage.py`).
- `clinosim.modules.observation.engine` — `therapeutic_range`
  (`common.build_reference_range`, lazy import).
- `clinosim.simulator.log` and `clinosim.__version__`
  (`generator_metadata.py`).
- `re`, `datetime`, `dataclasses`, `hashlib`, `json`, `subprocess` —
  standard library.
- `inline_bb.py` / `ed_reattribution.py` import the clinical-domain
  subpackages (`ed_reattribution.py` also
  `clinosim.modules.document.narrative.registry`); nothing in `lib/`
  imports the `builder.py` facade.

## Constants and configuration

- **`_FHIR_ID_PATTERN`** — the FHIR R4 spec-mandated id pattern
  (`[A-Za-z0-9\-\.]{1,64}`). Not in `lib/`: it is defined only in
  `../builder.py` (used by `_fhir_id_is_spec_valid`, a fail-soft
  check in the NDJSON writer).
- **`_JST_TZ_SUFFIX = "+09:00"`** / **`_UTC_TZ_SUFFIX = "Z"`**
  (`fhir_time.py`) — timezone-suffix constants for the `to_fhir_*`
  formatters + downstream post-processing. A country's own suffix is its
  country profile `timezone` (`clinosim/locale/<cc>/country.yaml`), which
  `tz_suffix_for_country` returns; `Z` only when no country is in scope.
- **`CLINOSIM_IDENTIFIER_SYSTEM_PREFIX = "urn:clinosim:identifier:"`**
  — namespace prefix for every clinosim-internal identifier system
  (`HAI_EVENT_ID_SYSTEM`, staff identifier system, etc.).
- **eCS placeholders** (`ecs_extensions.py`) — used when the cohort
  does not have a real institution number / department code (JP eCS
  profile requires the fields; the placeholders satisfy the
  cardinality without claiming a real facility).
- **`_RECENT_MERGES_LIMIT = 30`** (`generator_metadata.py`) — cap on
  the number of recent-merge PR numbers recorded in the sidecar.

## Directory contents

```
clinosim/modules/output/fhir_r4/lib/
  __init__.py                        namespace-only (no re-exports)
  common.py                          fragment helpers (entry, survey_category, address / telecom / reference range / diagnosis / severity ...)
  context.py                         BundleContext dataclass
  dosage.py                          Dosage / route / IV-rate / MAR-status helpers
  ecs_extensions.py                  JP eCS institution / department extensions + placeholders
  fhir_time.py                       to_fhir_date / datetime / instant + tz suffix constants
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
