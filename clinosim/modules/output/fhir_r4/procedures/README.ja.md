# `fhir_r4/procedures/` — Procedure + Immunization + Device + nursing FHIR R4 builder

## 概要

「procedure & device」ファミリの FHIR R4 resource 全てを emit:
`Procedure` (手術 + bedside + rehab)、`Immunization` (接種記録)、
`Device` + `DeviceUseStatement` (ICU デバイス — CVC / catheter /
ventilator)、看護 survey `Observation` (NEWS2 / GCS / Braden /
Morse / Barthel score + 摂取 / 尿 / 排液 flowsheet 行)、酸素療法 `Procedure` (Issue #796 — vitals の
`on_supplemental_oxygen` flag から `performedPeriod` を導出)。

FHIR taxonomy が Immunization を Procedure ファミリに配置している
ため、Immunization は
[`../conditions/`](../conditions/README.ja.md) ではなくここに住む。

## Scope

- **In scope**: `_build_procedure` (Procedure root builder — 手術
  / bedside / rehab dispatch、US は CPT、JP は厚労省 診療報酬 K-code
  (`k-codes`)。registry wrapper `_bb_procedures` は
  [`../lib/inline_bb.py`](../lib/inline_bb.py));
  `resolve_procedure_snomed` (`procedure_name_snomed.py` +
  `procedure_name_snomed.yaml`、order 由来 Procedure の表示名 →
  SNOMED、Issue #1282);
  `_bb_immunizations` (`CIFPatientRecord.immunizations` 由来の
  成人ワクチン接種歴);`_bb_device` + `_bb_device_use`
  (`extensions["device"]` 由来);`_bb_nursing_observations`
  (NEWS2 / GCS / Braden / Morse / Barthel + 摂取 / 排出 の survey
  Observation cluster —
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
  ([`clinosim.modules.procedure`](../../../procedure/README.ja.md)、
  [`clinosim.modules.device`](../../../device/README.ja.md)、
  [`clinosim.modules.immunization`](../../../immunization/README.ja.md)、
  看護スコアと vitals flag は
  [`clinosim.modules.observation`](../../../observation/README.ja.md));
  `ImagingStudy` (臨床的には procedural だが
  [`../labs/imaging_study.py`](../labs/imaging_study.py) に住む)。

### 縦断サービスライン Procedure emission (v0.5 → v0.6.0)

以下 2 種の Procedure code set は、標準の `_build_procedure` path を
経由して FHIR 到達する (新規 resource-type builder は不要)。兄弟モジュール
[`clinosim.modules.procedure`](../../../procedure/README.ja.md) が
両者について `ProcedureRecord` を構築し、FHIR post-process pipeline
が code + display を追加配線なしで拾う:

- **分娩 Procedure** — JP `K894` (経腟分娩、MHLW 診療報酬点数表
  K-code) / US CPT `59400` (routine obstetric care incl. vaginal
  delivery)。母親側分娩 encounter (emit 元:
  [`clinosim/simulator/perinatal.py`](../../../../simulator/perinatal.py))
  に付与。
- **放射線治療 Procedure** — modality / dose / site は disease YAML
  の放射線ブロックから取得。code + display は標準 Procedure builder
  経由で emit され、code system の違いのみで区別される。

## Public API

各 builder は親 facade (`_BUNDLE_BUILDERS` in
[`../builder.py`](../builder.py)) に登録済み。cross-family
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
  `survey_category`, `to_fhir_datetime`、fragment helper。
  `lib.ids` — opaque id。
- `clinosim.modules.output.fhir_r4.conditions.primary_ref` —
  酸素療法 `Procedure.reasonReference` 用 `primary_condition_ref`。
- `..demographics.patient.patient_ref`、
  `..encounters.encounter.encounter_ref`。
- `clinosim.codes` — CPT / K-code / CVX / SNOMED 表示 lookup、
  `clinosim.codes.oxygen_device_to_snomed`。
- `clinosim.modules.diagnosis.nonspecific_codes` (procedures)。
- CIF record は `get_attr_or_key` で dict として読み、
  `clinosim.types` の class は import しない。
- `datetime`, `timedelta` — 標準ライブラリ (oxygen_therapy の
  `_SINGLE_TIMESTAMP_DWELL` に使用)。

## 定数と設定

- **Procedure code dispatch** — US は CPT
  (`http://www.ama-assn.org/go/cpt`);JP は厚労省 診療報酬 K-code
  (`k-codes`、`urn:oid:1.2.392.200119.4.401`)。record 単位の
  `procedure_system_key` override (例 `snomed-ct`) が優先。
- **酸素療法** (`oxygen_therapy.py`、Issue #796):
  - `_SNOMED_OXYGEN_THERAPY = "57485005"` — 酸素投与の SNOMED CT
    code。
  - `_SINGLE_TIMESTAMP_DWELL = timedelta(minutes=15)` — 単一
    timestamp の `on_supplemental_oxygen` vitals sample から
    `Procedure.performedPeriod` を組む際の dwell 窓。
  - encounter 中心: `on_supplemental_oxygen=True` の vitals を持つ
    encounter ごとに O2 Order の有無に関わらず Procedure を 1 つ
    emit。session 期間は vitals flag から導出 (Order がある場合は
    SpO2 目標の `note[]` のみ寄与)。
- **Immunization emit** — CVX system + `ImmunizationRecord.lot_number`
  由来の lot number。SHA-256 base の lot 生成は
  [`../../../immunization/engine.py`](../../../immunization/engine.py)
  (P1-7 fix — Python builtin `hash()` は interpreter 毎に salt される)。
- **Device emit** — `extensions["device"]` を read (POST_ENCOUNTER
  order=70 の
  [`../../../device/enricher.py`](../../../device/enricher.py) が
  populate)。`DeviceUseStatement.timingPeriod` は per-device
  line-days count から導出。
- **看護 survey Observation** — NEWS2 / GCS / Braden / Morse /
  Barthel と摂取 / 尿 / 排液を
  `Observation.category = "survey"` で emit。AGENTS.md AD-64 の
  nursing_flowsheets vs nursing_assignment 曖昧回避に従い、
  これは POST_RECORDS の `enrich_nursing` enricher (order=20) の
  emit 側。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/procedures/
  __init__.py                        namespace stub (builder は ../builder.py / ../lib/inline_bb.py が import)
  procedures.py                      _build_procedure (手術 + bedside + rehab)
  procedure_name_snomed.py (+ .yaml) resolve_procedure_snomed (表示名 → SNOMED、Issue #1282)
  immunization.py                    _bb_immunizations (CVX + lot number)
  device.py                          _bb_device + _bb_device_use (extensions["device"] 由来)
  nursing.py                         _bb_nursing_observations (NEWS2 / GCS / Braden / Morse / Barthel / intake-output survey Observation)
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
[`CONTRIBUTING.md`](../../../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
