# `fhir_r4/labs/` — laboratory / vitals / microbiology / imaging + ServiceRequest builders

## Purpose

Emits every FHIR R4 resource in the laboratory + observation family
(the heaviest JP-locale specialisation in the whole `fhir_r4/`
subsystem): `Observation` (labs + vitals + ABO/RhD + microbiology),
`DiagnosticReport`, `ServiceRequest`, `ImagingStudy`, plus the
JP-CLINS lab-code loader (`coding_package`) and dispatcher
(`coding_strategy`) that resolve JLAC10 five-axis codes at emit
time.

## Scope

- **In scope**: `_bb_labs` (lab + vitals Observation), `_bb_diagnostic_reports`,
  `_bb_service_requests` (with the `SR_ID_PREFIX` +
  `PLACER_ORDER_NUMBER_SYSTEM` + `LAB_CATEGORY_SNOMED` +
  `LAB_CATEGORY_V2_0074` canonical constants — cross-verified by
  the `order` AD-60 audit plug-in), `_bb_microbiology`, `_bb_imaging_studies`
  + `_build_imaging_study` + `_build_series` + `DICOM_UID_SYSTEM =
  "urn:dicom:uid"` (cross-verified by the `imaging` AD-60 audit),
  `_bb_blood_type` + `_build_blood_type_obs` +
  `_LOINC_ABO_GROUP = "883-9"` + `_LOINC_RH_GROUP = "10331-7"`
  (Issue #795 RNG-neutral ABO/RhD observations),
  `coding_package` (JP-CLINS `clinical-information-sharing`
  package + `jpfhir-terminology` package loader — env-overridable
  via `CLINOSIM_JP_CLINS_PKG_DIR`), `coding_strategy`
  (JP-CLINS lab-code dispatch: standard JLAC10 / uncoded / localcode
  fallback per `JP_CLINS_ObsLabResult_*` code systems);
  `_reference_ranges` (vital-sign + BP component reference-range
  tables consumed by observation builders).
- **Out of scope**: lab / vitals / microbiology / imaging
  **generation**
  ([`observation`](../../../observation/README.md),
  [`hai`](../../../hai/README.md),
  [`imaging`](../../../imaging/README.md), etc.); Order placement
  ([`order`](../../../order/README.md)).

## Public API

Every builder is registered with the parent facade
(`_BUNDLE_BUILDERS` in [`../__init__.py`](../__init__.py)).
Direct imports:

```python
from clinosim.modules.output.fhir_r4.labs.observations import _bb_labs
from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _bb_diagnostic_reports
from clinosim.modules.output.fhir_r4.labs.service_request import (
    _bb_service_requests,
    SR_ID_PREFIX,                         # canonical, cross-verified by `order` AD-60 audit
    PLACER_ORDER_NUMBER_SYSTEM,
    LAB_CATEGORY_SNOMED,                  # "108252007"
    LAB_CATEGORY_V2_0074,                 # "LAB"
)
from clinosim.modules.output.fhir_r4.labs.microbiology import _bb_microbiology
from clinosim.modules.output.fhir_r4.labs.imaging_study import (
    _bb_imaging_studies,
    _build_imaging_study,
    _build_series,
    DICOM_UID_SYSTEM,                     # "urn:dicom:uid"
    RADIOLOGY_DR_ID_PREFIX,               # alias of RADIOLOGY_REPORT_ID_PREFIX
)
from clinosim.modules.output.fhir_r4.labs.blood_type import (
    _bb_blood_type,
    _build_blood_type_obs,
)
from clinosim.modules.output.fhir_r4.labs.coding_package import load_jp_clins_terminology
from clinosim.modules.output.fhir_r4.labs.coding_strategy import resolve_lab_code
from clinosim.modules.output.fhir_r4.labs._reference_ranges import (
    VITAL_HEART_RATE,
    VITAL_TEMPERATURE,
    VITAL_RESPIRATORY_RATE,
    BP_SYSTOLIC,
    BP_DIASTOLIC,
)
```

## Determinism

Not applicable — pure builders over CIF + reference-range tables.

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`.
- `clinosim.modules.output.fhir_r4.lib.common` — `BundleContext`,
  fragment helpers.
- `clinosim.modules.output.fhir_r4.conditions.primary_ref` —
  `primary_condition_ref` for lab / microbiology
  `Observation.encounter` + `basedOn` references.
- `clinosim.codes` — LOINC / SNOMED / JLAC10 display lookup.
- `clinosim.locale.loader` — `code_mapping_lab.yaml` (JLAC10 five-axis
  code mapping per country).

## Constants and configuration

- **Vital reference ranges** ([`_reference_ranges.py`](_reference_ranges.py))
  — `VitalSignReferenceRange` + `BloodPressureComponentReferenceRange`
  instances for HR / temperature / RR / SBP / DBP consumed by
  `observations.py`.
- **`_LOINC_ABO_GROUP = "883-9"`** + **`_LOINC_RH_GROUP = "10331-7"`**
  — LOINC codes for the ABO group + Rh factor Observations
  (Issue #795 RNG-neutral additive-field pattern; the values are
  derived via SHA-256 on `person_id + salt` in
  [`population`](../../../population/README.md)).
- **`SR_ID_PREFIX`, `PLACER_ORDER_NUMBER_SYSTEM`,
  `LAB_CATEGORY_SNOMED = "108252007"`, `LAB_CATEGORY_V2_0074 = "LAB"`**
  — canonical constants imported by the `order` AD-60 audit plug-in
  for its 7-check `lift_firing_proof`.
- **`DICOM_UID_SYSTEM = "urn:dicom:uid"`** — imported by the
  `imaging` AD-60 audit plug-in for its 15-check
  `lift_firing_proof`.
- **JP-CLINS package constants** (`coding_package.py`):
  - `_JP_CLINS_PKG_ID = "clinical-information-sharing"` + `_JP_CLINS_PKG_VERSION = "1.13.0"`.
  - `_JP_CLINS_TERMINOLOGY_PKG_ID = "jpfhir-terminology"` + `_JP_CLINS_TERMINOLOGY_PKG_VERSION = "2.2606.0"`.
  - `_ECS_SD_FILENAME = "StructureDefinition-JP-Observation-LabResult-eCS.json"`.
  - `_SPECIMEN_MATERIAL_CS_FILENAME = "CodeSystem-jp-observationsamplematerialcodejlac10-cs.json"`.
  - `_SPECIMEN_MATERIAL_CS_URI = "http://jpfhir.jp/fhir/core/CodeSystem/JP_ObservationSampleMaterialCodeJLAC10_CS"`.
  - Environment override: `CLINOSIM_JP_CLINS_PKG_DIR` (`_ENV_PKG_DIR`)
    points the loader at a local FHIR package cache.
- **JP-CLINS lab-code dispatch** (`coding_strategy.py`):
  - Standard JLAC10 → 17-digit code from
    `code_mapping_lab.yaml`.
  - Not-standardised → `_UNCODED_SYSTEM =
    "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_Uncoded_CS"`
    with `_UNCODED_CODE = "99999999999999999"` +
    `_UNCODED_DISPLAY = "未標準化コード項目(JLAC)"`.
  - Local-code fallback → `_LOCALCODE_SYSTEM =
    "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_LocalCode_CS"`.

## Directory contents

```
clinosim/modules/output/fhir_r4/labs/
  __init__.py                    empty (builders imported by parent __init__)
  observations.py                _bb_labs (lab + vitals Observation)
  diagnostic_report.py           _bb_diagnostic_reports
  service_request.py             _bb_service_requests + canonical constants (SR_ID_PREFIX / PLACER_ORDER_NUMBER_SYSTEM / LAB_CATEGORY_*)
  microbiology.py                _bb_microbiology (culture + susceptibility)
  imaging_study.py               _bb_imaging_studies + _build_imaging_study + _build_series + DICOM_UID_SYSTEM
  blood_type.py                  _bb_blood_type + ABO/RhD LOINC constants (Issue #795)
  coding_package.py              JP-CLINS + jpfhir-terminology package loader
  coding_strategy.py             JP-CLINS lab-code dispatch (standard / uncoded / localcode)
  _reference_ranges.py           VitalSignReferenceRange + BloodPressureComponentReferenceRange tables
```

## Testing

```bash
pytest tests/unit -k "fhir_labs or blood_type or imaging_study or service_request or diagnostic_report or microbiology" -q
pytest tests/integration -k "servicerequest_chain or hai or imaging" -q
clinosim audit run -d <cohort_dir> --module order      # cross-verifies SR_ID_PREFIX / PLACER / LAB_CATEGORY_*
clinosim audit run -d <cohort_dir> --module imaging    # cross-verifies DICOM_UID_SYSTEM + emission counts
clinosim audit run -d <cohort_dir> --module hai        # cross-verifies HAI_EVENT_ID_SYSTEM identifier on microbiology
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
