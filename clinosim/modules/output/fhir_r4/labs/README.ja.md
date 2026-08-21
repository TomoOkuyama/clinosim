# `fhir_r4/labs/` — 検査 / vitals / microbiology / imaging + ServiceRequest builder

## 概要

検査 + 観測ファミリの FHIR R4 resource 全てを emit (fhir_r4/
subsystem 内で最も JP-locale 特化が重い): `Observation` (labs +
vitals + ABO/RhD + microbiology)、`DiagnosticReport`、
`ServiceRequest`、`ImagingStudy`、そして emit 時に JLAC10 五軸
コードを解決する JP-CLINS lab-code loader (`coding_package`) +
dispatcher (`coding_strategy`)。

## Scope

- **In scope**: `_bb_labs` (lab + vitals Observation)、
  `_bb_diagnostic_reports`、`_bb_service_requests` (canonical 定数
  `SR_ID_PREFIX` + `PLACER_ORDER_NUMBER_SYSTEM` +
  `LAB_CATEGORY_SNOMED` + `LAB_CATEGORY_V2_0074` を保持、
  `order` AD-60 audit plug-in が cross-verify)、`_bb_microbiology`、
  `_bb_imaging_studies` + `_build_imaging_study` + `_build_series` +
  `DICOM_UID_SYSTEM = "urn:dicom:uid"` (`imaging` AD-60 audit が
  cross-verify)、`_bb_blood_type` + `_build_blood_type_obs` +
  `_LOINC_ABO_GROUP = "883-9"` + `_LOINC_RH_GROUP = "10331-7"`
  (Issue #795 RNG-neutral な ABO/RhD Observation)、`coding_package`
  (JP-CLINS `clinical-information-sharing` package +
  `jpfhir-terminology` package loader、env `CLINOSIM_JP_CLINS_PKG_DIR`
  で override 可)、`coding_strategy` (JP-CLINS lab-code dispatch:
  standard JLAC10 / uncoded / localcode fallback、
  `JP_CLINS_ObsLabResult_*` code system 別);`_reference_ranges`
  (observation builder が消費する vital-sign + BP 成分の
  reference-range 表)。
- **Out of scope**: lab / vitals / microbiology / imaging の **生成**
  ([`observation`](../../../observation/README.md)、
  [`hai`](../../../hai/README.md)、
  [`imaging`](../../../imaging/README.md) 等);Order 発注
  ([`order`](../../../order/README.md))。

## Public API

各 builder は親 facade (`_BUNDLE_BUILDERS` in
[`../__init__.py`](../__init__.py)) に登録済み。直接 import:

```python
from clinosim.modules.output.fhir_r4.labs.observations import _bb_labs
from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _bb_diagnostic_reports
from clinosim.modules.output.fhir_r4.labs.service_request import (
    _bb_service_requests,
    SR_ID_PREFIX,                         # canonical、`order` AD-60 audit が cross-verify
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
    RADIOLOGY_DR_ID_PREFIX,               # RADIOLOGY_REPORT_ID_PREFIX の alias
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

## 決定論

該当なし — CIF + reference-range 表に対する pure builder。

## 依存

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`。
- `clinosim.modules.output.fhir_r4.lib.common` — `BundleContext`、
  fragment helper。
- `clinosim.modules.output.fhir_r4.conditions.primary_ref` — lab /
  microbiology `Observation.encounter` + `basedOn` reference 用の
  `primary_condition_ref`。
- `clinosim.codes` — LOINC / SNOMED / JLAC10 表示 lookup。
- `clinosim.locale.loader` — `code_mapping_lab.yaml`
  (国別 JLAC10 五軸コード mapping)。

## 定数と設定

- **Vital reference range** ([`_reference_ranges.py`](_reference_ranges.py))
  — `observations.py` が消費する HR / 体温 / RR / SBP / DBP の
  `VitalSignReferenceRange` + `BloodPressureComponentReferenceRange`
  instance。
- **`_LOINC_ABO_GROUP = "883-9"`** + **`_LOINC_RH_GROUP = "10331-7"`**
  — ABO group + Rh factor Observation の LOINC 定数
  (Issue #795 RNG-neutral additive-field pattern、値は
  [`population`](../../../population/README.md) で
  `sha256(person_id + salt)` から派生)。
- **`SR_ID_PREFIX`, `PLACER_ORDER_NUMBER_SYSTEM`,
  `LAB_CATEGORY_SNOMED = "108252007"`, `LAB_CATEGORY_V2_0074 = "LAB"`**
  — `order` AD-60 audit plug-in の 7-check `lift_firing_proof` が
  import する canonical 定数。
- **`DICOM_UID_SYSTEM = "urn:dicom:uid"`** — `imaging` AD-60 audit
  plug-in の 15-check `lift_firing_proof` が import。
- **JP-CLINS package 定数** (`coding_package.py`):
  - `_JP_CLINS_PKG_ID = "clinical-information-sharing"` +
    `_JP_CLINS_PKG_VERSION = "1.12.0"`。
  - `_JP_CLINS_TERMINOLOGY_PKG_ID = "jpfhir-terminology"` +
    `_JP_CLINS_TERMINOLOGY_PKG_VERSION = "2.2606.0"`。
  - `_ECS_SD_FILENAME = "StructureDefinition-JP-Observation-LabResult-eCS.json"`。
  - `_SPECIMEN_MATERIAL_CS_FILENAME =
    "CodeSystem-jp-observationsamplematerialcodejlac10-cs.json"`。
  - `_SPECIMEN_MATERIAL_CS_URI =
    "http://jpfhir.jp/fhir/core/CodeSystem/JP_ObservationSampleMaterialCodeJLAC10_CS"`。
  - 環境 override: `CLINOSIM_JP_CLINS_PKG_DIR` (`_ENV_PKG_DIR`)
    が loader を local FHIR package cache に向ける。
- **JP-CLINS lab-code dispatch** (`coding_strategy.py`):
  - 標準 JLAC10 → `code_mapping_lab.yaml` の 17 桁コード。
  - 未標準化 → `_UNCODED_SYSTEM =
    "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_Uncoded_CS"`
    に `_UNCODED_CODE = "99999999999999999"` +
    `_UNCODED_DISPLAY = "未標準化コード項目(JLAC)"`。
  - Local-code fallback → `_LOCALCODE_SYSTEM =
    "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_LocalCode_CS"`。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/labs/
  __init__.py                    空 (builder は親 __init__ が import)
  observations.py                _bb_labs (lab + vitals Observation)
  diagnostic_report.py           _bb_diagnostic_reports
  service_request.py             _bb_service_requests + canonical 定数 (SR_ID_PREFIX / PLACER_ORDER_NUMBER_SYSTEM / LAB_CATEGORY_*)
  microbiology.py                _bb_microbiology (culture + susceptibility)
  imaging_study.py               _bb_imaging_studies + _build_imaging_study + _build_series + DICOM_UID_SYSTEM
  blood_type.py                  _bb_blood_type + ABO/RhD LOINC 定数 (Issue #795)
  coding_package.py              JP-CLINS + jpfhir-terminology package loader
  coding_strategy.py             JP-CLINS lab-code dispatch (standard / uncoded / localcode)
  _reference_ranges.py           VitalSignReferenceRange + BloodPressureComponentReferenceRange 表
```

## テスト

```bash
pytest tests/unit -k "fhir_labs or blood_type or imaging_study or service_request or diagnostic_report or microbiology" -q
pytest tests/integration -k "servicerequest_chain or hai or imaging" -q
clinosim audit run -d <cohort_dir> --module order      # SR_ID_PREFIX / PLACER / LAB_CATEGORY_* を cross-verify
clinosim audit run -d <cohort_dir> --module imaging    # DICOM_UID_SYSTEM + emission count を cross-verify
clinosim audit run -d <cohort_dir> --module hai        # microbiology 上の HAI_EVENT_ID_SYSTEM identifier を cross-verify
```

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
