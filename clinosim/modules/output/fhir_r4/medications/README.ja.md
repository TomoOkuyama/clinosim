# `fhir_r4/medications/` — MedicationRequest + MedicationAdministration builder

## 概要

薬剤系 FHIR R4 resource 2 種を emit: `MedicationRequest` (処方
— 入院 inflow、退院 outflow、外来) と `MedicationAdministration`
(投与 dose ごとの MAR entry)。JP path は YJ コード + JP-CLINS
Medication profile の MEDIS `NOCODED` fallback を emit、US path は
RxNorm。JP `MedicationRequest.status='completed'` invariant
(JP eCS Medication_Common が要求) を emit 時に強制する — memory
[`project_jp_ecs_forces_status_completed`](../../../../../..) 参照。
[`clinosim.modules.antibiotic`](../../../antibiotic/README.md) の
`discontinuation_datetime` slot は narrow / stop 時に
`MedicationRequest.statusReason` に情報を寄せて workaround する。

## Scope

- **In scope**: `_build_medication_request` (処方 root builder —
  入院 / 外来 dispatch)、`_build_discharge_medication_request`
  (退院 outflow、`rxdc-` id prefix)、`_build_medication_admin`
  (dose 別 MAR)、`_build_medication_request_meta` +
  `_build_medication_request_identifiers` (JP eCS meta +
  identifier)、`_build_category_block` + `_build_course_of_therapy_block`
  (terminology.hl7.org CodeSystem を使う category + course-of-therapy
  CodeableConcept)、ID prefix:
  `DISCHARGE_RX_ID_PREFIX = "rxdc-"`,
  `OUTPATIENT_RX_ID_PREFIX = "rxopd-"`,
  `MEDICATION_REQUEST_KEY_SYSTEM =
  structural_key_system("medication-request-key")`;国別 supply
  duration 単位 (`_SUPPLY_DURATION_UNIT_JP = "日"` /
  `_SUPPLY_DURATION_UNIT_US = "d"`、code `_SUPPLY_DURATION_CODE = "d"`);
  JP YJ + MEDIS uncoded 定数 (`_JP_YJ_CODE_URI`,
  `_JP_MEDICATION_CODE_NOCODED_CS`,
  `_JP_MEDICATION_CODE_NOCODED_CODE = "NOCODED"`,
  `_JP_MEDICATION_CODE_NOCODED_DISPLAY = "標準コードなし"`)。
- **Out of scope**: 処方 / MAR の **生成**
  ([`order`](../../../order/README.md)、
  [`simulator`](../../../../simulator/)、
  [`antibiotic`](../../../antibiotic/README.md));薬剤 code registry
  ([`clinosim/codes/data/{rxnorm,yj,hot,jp-medis-drug-uncoded}.yaml`](../../../../codes/data/));
  退院薬理由 / narrow-target 用量 default
  ([`antibiotic/_narrow_dose_defaults.py`](../../../antibiotic/_narrow_dose_defaults.py))。

## Public API

各 builder は親 facade (`_BUNDLE_BUILDERS` in
[`../__init__.py`](../__init__.py)) に `_bb_medication_requests`,
`_bb_discharge_medication_requests`, `_bb_medication_admins` として
登録済み。low-level `_build_*` 関数は `medications.py`:

```python
from clinosim.modules.output.fhir_r4.medications.medications import (
    _build_medication_request,
    _build_discharge_medication_request,
    _build_medication_admin,
    _build_medication_request_meta,
    _build_medication_request_identifiers,
    _build_category_block,
    _build_course_of_therapy_block,
    # ID prefix + system URI
    DISCHARGE_RX_ID_PREFIX,               # "rxdc-"
    OUTPATIENT_RX_ID_PREFIX,              # "rxopd-"
    MEDICATION_REQUEST_KEY_SYSTEM,        # structural key system URI
)
```

登録された `_bb_*` 名は [`../lib/inline_bb.py`](../lib/inline_bb.py)
に住む (`_bb_medication_requests`,
`_bb_discharge_medication_requests`, `_bb_medication_admins`) —
`medications/` subpackage への split は FA-1 phased refactor で
fragment builder のみを移し、`_bb_*` 登録は inline_bb に残した。

## 決定論

該当なし — CIF order + MAR record に対する pure builder。

## 依存

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`,
  `get_attr_or_key`。
- `clinosim.modules.output.fhir_r4.lib.common` — `BundleContext`,
  `_coding_with_display`, `build_ucum_quantity`,
  `attach_ecs_institutional_extensions`。
- `clinosim.modules.output.fhir_r4.lib.ids` — medication-request
  key system URI 用 `structural_key_system`。
- `clinosim.modules.output.fhir_r4.conditions.primary_ref` —
  `MedicationRequest.reasonReference` 用 `primary_condition_ref`。
- `clinosim.codes` — RxNorm / YJ / HOT 表示 lookup。
- `clinosim.types.encounter` — `Order`, `OrderStatus`, `OrderType`,
  `MedicationAdministration`。

## 定数と設定

- **ID prefix**: 入院 MedicationRequest は
  `rx-{encounter_id}-{seq}` 形状。退院 outflow は
  `DISCHARGE_RX_ID_PREFIX = "rxdc-"`、外来は
  `OUTPATIENT_RX_ID_PREFIX = "rxopd-"`。
  [`antibiotic`](../../../antibiotic/README.md) module は regimen を
  `ABX_ORDER_REQ_PREFIX` / `ABX_NARROW_SUFFIX` で追加 emit する
  ([`antibiotic/engine.py`](../../../antibiotic/engine.py))。
- **Terminology system** (`MedicationRequest` metadata 用 HL7
  CodeSystem):
  - `_MR_CATEGORY_SYSTEM =
    "http://terminology.hl7.org/CodeSystem/medicationrequest-category"`。
  - `_MR_COURSE_OF_THERAPY_SYSTEM =
    "http://terminology.hl7.org/CodeSystem/medicationrequest-course-of-therapy"`。
  - 使用する 2 course: `_COURSE_CONTINUOUS =
    ("continuous", "Continuous long term therapy")` と
    `_COURSE_ACUTE = ("acute", "Short course (acute) therapy")`。
- **Supply duration 単位**: JP は `"日"` 表示、US は `"d"` 表示、
  UCUM code は共通 `"d"`。
- **JP YJ code system**: `_JP_YJ_CODE_URI =
  "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code"`。薬剤に YJ
  mapping が無い場合、builder は JP eCS Medication_Common の
  `NOCODED` fallback (`_JP_MEDICATION_CODE_NOCODED_CS`,
  `_JP_MEDICATION_CODE_NOCODED_CODE = "NOCODED"`、表示
  `"標準コードなし"`) を emit。
- **JP `MedicationRequest.status = "completed"`** — JP eCS
  Medication_Common profile が emit 時に強制。`stopped` / `active`
  / `on-hold` 等の意図は enricher が regimen 中断を marking したとき
  `MedicationRequest.statusReason` に寄せる (antibiotic narrowing
  path)。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/medications/
  __init__.py                        空 (builder は親 __init__ が import)
  medications.py                     _build_medication_request + _build_discharge_medication_request + _build_medication_admin + JP eCS fragment
```

## テスト

```bash
pytest tests/unit -k "medication_request or medication_admin or discharge_rx or fhir_medications" -q
pytest tests/integration -k "antibiotic or servicerequest_chain" -q
```

`antibiotic` AD-60 audit plug-in
([`../../../antibiotic/audit.py`](../../../antibiotic/audit.py)) の
`lift_firing_proof` が `_build_medication_request` +
`_build_medication_admin` の emit invariant を cross-verify する。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
