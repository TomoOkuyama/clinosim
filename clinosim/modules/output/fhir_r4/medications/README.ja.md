# `fhir_r4/medications/` — MedicationRequest + MedicationAdministration builder

## 概要

薬剤系 FHIR R4 resource 2 種を emit: `MedicationRequest` (処方
— 入院 inflow、退院 outflow、外来) と `MedicationAdministration`
(投与 dose ごとの MAR entry)。JP path は YJ コード + JP-CLINS
Medication profile の MEDIS `NOCODED` fallback を emit、US path は
RxNorm。JP `MedicationRequest.status='completed'` /
`intent='order'` の pattern 固定 (`JP_MedicationRequest_eCS` が要求)
は builder の後で
[`../post_process/populate.py`](../post_process/populate.py) の
`_populate_condition_ai_mr_ecs_fields` が適用する。builder が設定した
status が異なる場合 (`active`、narrow / 中止された
[`antibiotic`](../../../antibiotic/README.ja.md) regimen の
`stopped` 等)、元の status は
`urn:clinosim:medicationrequest-effective-status` extension と
`note[]` text に保持される (`statusReason` は emit しない)。

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
  ([`order`](../../../order/README.ja.md)、
  [`simulator`](../../../../simulator/)、
  [`antibiotic`](../../../antibiotic/README.ja.md));薬剤 code registry
  ([`clinosim/codes/data/{rxnorm,yj,hot7}.yaml`](../../../../codes/data/));
  退院薬理由 / narrow-target 用量 default
  ([`antibiotic/_narrow_dose_defaults.py`](../../../antibiotic/_narrow_dose_defaults.py))。

### 化学療法サイクル MR + MAR (v0.5 → v0.6.0)

各 `chemo_visit` LifeEvent について、[`order`](../../../order/README.ja.md)
が regimen `cycle_orders` の各薬剤について `MedicationRequest` +
`MedicationAdministration` を **同一 `order_id`** で 1 対 emit する。
これにより本 subpackage の `_bb_medication_requests` /
`_bb_medication_admins` builder が emit 時に自然に対を成す。JP path
は引き続き `MedicationRequest.status = "completed"` を固定 (概要
参照)。MAR
側は `effectiveDateTime` に cycle Day-1 投与 timestamp を持つ。
FOLFOX の 46 時間 5-FU 等の複日 infusion 薬の展開は follow-up slice —
現 MVP は Day-1 薬剤ごとに 1 MAR。

## Public API

各 builder は親 facade (`_BUNDLE_BUILDERS` in
[`../builder.py`](../builder.py)) に `_bb_medication_requests`,
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
    MEDICATION_ADMINISTRATION_ID_PREFIX,  # "mar-"
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
  `build_ucum_quantity`、dosage / route / status helper。
- `clinosim.modules.output.fhir_r4.lib.ids` — `derive_opaque_id` +
  `structural_key_system`。
- `clinosim.modules.output.fhir_r4.conditions.primary_ref` —
  `MedicationRequest.reasonReference` /
  `MedicationAdministration.reasonReference` 用
  `primary_condition_ref_from_codes` (lazy import)。
- `..demographics.patient.patient_ref`、
  `..encounters.encounter.encounter_ref`。
- `clinosim.codes` — RxNorm / YJ / HOT 表示 lookup、
  `clinosim.locale.loader.load_code_mapping`。
- order / MAR record は CIF dict として読み、`clinosim.types` の
  class は import しない。

## 定数と設定

- **ID prefix**: order 由来 MedicationRequest id は opaque な
  `mr-{sha256(order_id)[:12]}` (`_resolve_mr_id`、Issue #853。
  structural key は `identifier[]` に残る)。退院 outflow は
  `DISCHARGE_RX_ID_PREFIX = "rxdc-"`、外来は
  `OUTPATIENT_RX_ID_PREFIX = "rxopd-"`、MedicationAdministration は
  `MEDICATION_ADMINISTRATION_ID_PREFIX = "mar-"`。
  [`antibiotic`](../../../antibiotic/README.ja.md) module は regimen を
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
- **JP `MedicationRequest.status = "completed"`** — JP 出力で
  `post_process/populate.py` (`_populate_condition_ai_mr_ecs_fields`)
  が `JP_MedicationRequest_eCS` に従い固定。builder の status が
  異なる場合 (`active`、`stopped` 等) は
  `urn:clinosim:medicationrequest-effective-status` extension
  (`valueCode`) と日本語 `note[]` text に保持。builder 自体は stop
  order (`MED_STOP_ORDER_ID_MARKER`) に `stopped` を設定する。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/medications/
  __init__.py                        namespace stub (builder は ../builder.py / ../lib/inline_bb.py が import)
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
[`CONTRIBUTING.md`](../../../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
