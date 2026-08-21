# `fhir_r4/procedures/` — Procedure + Immunization + Device + nursing FHIR R4 builder

## 概要

「procedure & device」ファミリの FHIR R4 resource 全てを emit:
`Procedure` (手術 + bedside + rehab)、`Immunization` (接種記録)、
`Device` + `DeviceUseStatement` (ICU デバイス — CVC / catheter /
ventilator)、看護 survey `Observation` (NEWS2 / GCS / Braden /
Morse flowsheet)、酸素療法 `Procedure` (Issue #796 — vitals の
`on_supplemental_oxygen` flag から `performedPeriod` を導出)。

FHIR taxonomy が Immunization を Procedure ファミリに配置している
ため、Immunization は
[`../conditions/`](../conditions/README.md) ではなくここに住む。

## Scope

- **In scope**: `_build_procedure` (Procedure root builder — 手術
  / bedside / rehab dispatch、US は CPT、JP は JJ1017 K-code);
  `_bb_immunizations` (`CIFPatientRecord.immunizations` 由来の
  成人ワクチン接種歴);`_bb_device` + `_bb_device_use`
  (`extensions["device"]` 由来);`_bb_nursing_observations`
  (NEWS2 / GCS / Braden / Morse の survey Observation cluster —
  これは FHIR emit 側。計算関数は
  [`../../../observation/nursing.py`](../../../observation/nursing.py)
  にある);`_bb_oxygen_therapy` (Issue #796 — 継続酸素療法用に
  vitals の per-therapy flag `on_supplemental_oxygen` を read し
  `Procedure` を `performedPeriod` 付きで合成、単一 timestamp event
  は flag sample を挟む `_SINGLE_TIMESTAMP_DWELL =
  timedelta(minutes=15)` の窓で dwell 化);
  `_SNOMED_OXYGEN_THERAPY = "57485005"`。
- **Out of scope**: procedure / device / immunization / nursing の
  **生成**
  ([`clinosim.modules.procedure`](../../../procedure/README.md)、
  [`clinosim.modules.device`](../../../device/README.md)、
  [`clinosim.modules.immunization`](../../../immunization/README.md)、
  看護スコアと vitals flag は
  [`clinosim.modules.observation`](../../../observation/README.md));
  `ImagingStudy` (臨床的には procedural だが
  [`../labs/imaging_study.py`](../labs/imaging_study.py) に住む)。

## Public API

各 builder は親 facade (`_BUNDLE_BUILDERS` in
[`../__init__.py`](../__init__.py)) に登録済み。cross-family
consumer 向け直接 import:

```python
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure
from clinosim.modules.output.fhir_r4.procedures.immunization import _bb_immunizations
from clinosim.modules.output.fhir_r4.procedures.device import _bb_device, _bb_device_use
from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations
from clinosim.modules.output.fhir_r4.procedures.oxygen_therapy import (
    _bb_oxygen_therapy,
    _SINGLE_TIMESTAMP_DWELL,             # timedelta(minutes=15)
    _SNOMED_OXYGEN_THERAPY,              # "57485005"
)
```

## 決定論

該当なし — CIF procedure / immunization / `extensions["device"]`
/ vitals + 看護 observation に対する pure builder。

## 依存

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`。
- `clinosim.modules.output.fhir_r4.lib.common` — `BundleContext`,
  `_coding_with_display`, `loinc_coding`, `survey_category`,
  `to_fhir_datetime`, `attach_ecs_institutional_extensions`。
- `clinosim.modules.output.fhir_r4.conditions.primary_ref` —
  `Procedure.reasonReference` 用 `primary_condition_ref`。
- `clinosim.codes` — CPT / JJ1017 K-code / CVX / SNOMED 表示 lookup。
- `clinosim.types.encounter` — `ProcedureRecord`, `RehabSession`,
  `Device`, `ImmunizationRecord`。
- `datetime`, `timedelta` — 標準ライブラリ (oxygen_therapy の
  `_SINGLE_TIMESTAMP_DWELL` に使用)。

## 定数と設定

- **Procedure code dispatch** — US は CPT
  (`http://www.ama-assn.org/go/cpt`);JP は JP-CLINS Procedure
  profile 経由で JJ1017 K-code。
- **酸素療法** (`oxygen_therapy.py`、Issue #796):
  - `_SNOMED_OXYGEN_THERAPY = "57485005"` — 酸素投与の SNOMED CT
    code。
  - `_SINGLE_TIMESTAMP_DWELL = timedelta(minutes=15)` — 単一
    timestamp の `on_supplemental_oxygen` vitals sample から
    `Procedure.performedPeriod` を組む際の dwell 窓。
  - 専用 Order ではなく vitals の per-therapy flag を read する
    (memory 記載の [`session-derived procedure period`](../../../../..)
    pattern: Order.end_datetime 無しは vitals から導出)。
- **Immunization emit** — CVX system + `ImmunizationRecord.lot_number`
  由来の lot number。SHA-256 base の lot 生成は
  [`../../../immunization/engine.py`](../../../immunization/engine.py)
  (P1-7 fix — Python builtin `hash()` は interpreter 毎に salt される)。
- **Device emit** — `extensions["device"]` を read (POST_ENCOUNTER
  order=70 の
  [`../../../device/enricher.py`](../../../device/enricher.py) が
  populate)。`DeviceUseStatement.timingPeriod` は per-device
  line-days count から導出。
- **看護 survey Observation** — NEWS2 / GCS / Braden / Morse を
  `Observation.category = "survey"` で emit。AGENTS.md AD-64 の
  nursing_flowsheets vs nursing_assignment 曖昧回避に従い、
  これは POST_RECORDS の `enrich_nursing` enricher (order=20) の
  emit 側。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/procedures/
  __init__.py                        空 (builder は親 __init__ が import)
  procedures.py                      _build_procedure (手術 + bedside + rehab)
  immunization.py                    _bb_immunizations (CVX + lot number)
  device.py                          _bb_device + _bb_device_use (extensions["device"] 由来)
  nursing.py                         _bb_nursing_observations (NEWS2 / GCS / Braden / Morse survey Observation)
  oxygen_therapy.py                  _bb_oxygen_therapy + _SINGLE_TIMESTAMP_DWELL + _SNOMED_OXYGEN_THERAPY (Issue #796)
```

## テスト

```bash
pytest tests/unit -k "fhir_procedure or fhir_immunization or fhir_device or fhir_nursing or oxygen_therapy" -q
pytest tests/integration -k "procedure or hai" -q
```

Cross-verification: HAI cascade が `extensions["device"]` line-days を
消費するため、`hai` AD-60 audit
([`../../../hai/audit.py`](../../../hai/audit.py)) の
`lift_firing_proof` が `_bb_device` + `_bb_device_use` を exercise
する。Issue #796 の酸素療法契約は
[`tests/unit/output/test_fhir_oxygen_therapy_procedure.py`](../../../../../tests/unit/output/test_fhir_oxygen_therapy_procedure.py)
が guard する。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
