# `fhir_r4/conditions/` — Condition / AllergyIntolerance / ClinicalImpression / HAI / CodeStatus builder

## 概要

「condition + clinical impression」ファミリの FHIR R4 resource
全てを emit する: `Condition` (primary + secondary + chronic + HAI)、
`AllergyIntolerance`、`ClinicalImpression`、CodeStatus survey
`Observation` (custom SNOMED 蘇生方針)。加えて全下流 builder が使う
**canonical primary-Condition reference resolver**
(`primary_ref.primary_condition_ref`) を所有し、
Encounter.reasonReference / diagnosis[].condition、Procedure /
MedicationRequest の reasonReference 等が encounter primary reason
に対して常に同じ `Condition.id` を指すことを保証する。

## Scope

- **In scope**: `_build_conditions` (primary + secondary + chronic
  Condition builder。registry wrapper `_bb_conditions` は
  [`../lib/inline_bb.py`](../lib/inline_bb.py))、`_bb_allergy_intolerances`、
  `_bb_clinical_impressions`、`_bb_hai_conditions`
  (`extensions["hai"]` 由来 HAI Condition)、`_bb_code_status`
  (custom survey `Observation`、JP encounter は
  `meta.profile = JP_Observation_Common`)、`primary_condition_ref`
  + `primary_condition_ref_from_codes` + `is_chronic_primary` +
  `_chronic_index_for_primary` + `_icd_base` (canonical
  primary-Condition resolver)、`_ecs_diagnosis_type_extension`,
  `_bodysite_for`, `_jfagy_coding_for_category` (JP 固有 fragment
  builder)。
- **Out of scope**: `Immunization` (これは
  [`../procedures/immunization.py`](../procedures/immunization.py)
  に住み、conditions/ ではない — immunization は臨床的には condition
  近縁だが FHIR 上は Procedure family)、condition / allergy /
  impression の **生成**
  ([`clinosim.modules.diagnosis`](../../../diagnosis/README.ja.md)、
  [`clinosim.modules.allergy`](../../../allergy/README.ja.md)、
  `ClinicalImpression` は
  [`clinosim.modules.document`](../../../document/README.ja.md)、
  HAI event は [`clinosim.modules.hai`](../../../hai/README.ja.md)、
  [`clinosim.modules.code_status`](../../../code_status/README.ja.md))、
  code registry 本体
  ([`clinosim/codes/`](../../../../codes/))。

## Public API

全 builder は親 facade (`_BUNDLE_BUILDERS` in
[`../builder.py`](../builder.py)) に登録済み。外部 caller が直接
import することは稀。builder 関数名:

```python
from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions  # (record, patient_id, country) -> list[dict]
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_conditions            # registry wrapper
from clinosim.modules.output.fhir_r4.conditions.allergy_intolerance import _bb_allergy_intolerances
from clinosim.modules.output.fhir_r4.conditions.clinical_impression import _bb_clinical_impressions
from clinosim.modules.output.fhir_r4.conditions.hai import _bb_hai_conditions
from clinosim.modules.output.fhir_r4.conditions.code_status import _bb_code_status

# Canonical primary-Condition resolver (他 resource family が import)
from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
    primary_condition_ref,             # (record, patient_id, encounter_id) -> Condition.id
    primary_condition_ref_from_codes,  # (record, patient_id, encounter_id, primary_code, admission_code)
    is_chronic_primary,                # (record) -> bool  (encounter primary が慢性)
    chronic_condition_id,              # (patient_id, idx) -> opaque Condition.id
    encounter_primary_condition_id,    # (patient_id, encounter_id) -> opaque Condition.id
)
```

## 決定論

該当なし — 各 builder は入力 CIF record の純粋関数。RNG 未使用、
run 時刻依存も無し。親 facade が emit 済み NDJSON を resource id で
sort するため line 順は決定論的。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`, `is_jp`,
  `resolve_lang`。
- `clinosim.modules.output.fhir_r4.lib.common` — fragment helper
  (`_coding_with_display`, `build_diagnosis_codeable_concept`,
  `infer_severity`, `map_diagnosis_code`, `severity_coding`,
  `to_fhir_date`, `survey_category`, `BundleContext`)。
- `clinosim.modules.output.fhir_r4.lib.localization` — JP 表示
  localisation helper。
- `clinosim.codes` — ICD-10 / ICD-10-CM / SNOMED / JP-Core
  `jp-core-*` code の `get_system_uri`, `system_key_for`, `lookup`。
- `clinosim.modules.output.fhir_r4.lib.ids` — opaque id 導出
  (`derive_opaque_id`, `structural_key_system`)。
- `..demographics.patient.patient_ref`、
  `..encounters.encounter.encounter_ref` — reference helper。
- `clinosim.modules.document` — `ALLERGY_ID_PREFIX`、
  `CLINICAL_IMPRESSION_ID_PREFIX`。
  `clinosim.modules.code_status.engine.load_reference`、
  `clinosim.modules.diagnosis.nonspecific_codes.is_visit_reason_zcode`、
  `clinosim.codes.stage_to_snomed.resolve_stage_snomed`。
- builder は CIF record を `get_attr_or_key` 経由で dict / 属性
  object として読み、`clinosim.types` の class は import しない。
- 親 `__init__.py` には依存しない (adapter facade への循環無し)。

## 定数と設定

- **Canonical primary-Condition resolver** (`primary_ref.py`) —
  single-source-of-truth ルール:
  - encounter の `clinical_diagnosis.discharge_diagnosis_code`
    (または admission-code fallback) の 3 文字 ICD base を、患者の
    `chronic_conditions[].code` base と比較。
  - **一致** → 患者スコープの chronic Condition id (structural key
    `chronic-{patient_id}-{index:02d}`) を返す。別途
    encounter-primary Condition を emit すると row 重複や ICD 粒度
    drift (I50 vs I50.9) が発生する。
  - **不一致** → encounter スコープ id (structural key
    `{encounter_id}-primary`) を返す。
  - id は opaque (Issue #854): `_resolve_condition_id` により
    `cond-` + sha256(structural key) の先頭 12 hex。
  - encounter primary reason を参照する全下流 builder は必ず
    `primary_condition_ref` を呼び、参照が emit 済み同一
    `Condition.id` を指すよう保証する。
- **ICD-10 dispatch**: US は ICD-10-CM billable、JP は WHO ICD-10
  4 文字 (JP-Core convention)。mapping は
  [`clinosim/locale/jp/code_mapping_diagnosis.yaml`](../../../../locale/jp/code_mapping_diagnosis.yaml)。
- **Allergen coding**: SNOMED CT (アレルゲン + 反応 manifestation)。
  JP-CLINS 出力では `AllergyIntolerance.code` は代わりに
  `_jfagy_coding_for_category` の JFAGY generic category coding
  (medication `00M` / food `00F` / environment + biologic `00N`) を
  持ち、mapping 無しの category は SNOMED に fallback。RxNorm coding
  は emit しない。
- **HAI coding**: ICD-10-CM (US billable) + WHO ICD-10 (JP) +
  SNOMED CT International — AGENTS.md の `dual-slot` 規約に沿う
  dual-code。
- **JP eCS diagnosis-type extension**: `_ecs_diagnosis_type_extension`
  が JP Condition に JP-CLINS `JP_Condition_eCS` の
  diagnosis-type extension (`principal`, `admitting`,
  `differential`, `clinical`) を emit する。
- **CodeStatus profile**: JP encounter は custom survey Observation
  に `meta.profile =
  "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"`
  を付与する。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/conditions/
  __init__.py                    namespace stub (builder は ../builder.py と ../lib/inline_bb.py が import)
  conditions.py                  _build_conditions (primary + secondary + chronic) + JP eCS diagnosis-type / bodySite helper
  allergy_intolerance.py         _bb_allergy_intolerances + JP fagy category coding
  clinical_impression.py         _bb_clinical_impressions
  hai.py                         _bb_hai_conditions (extensions["hai"] 由来)
  code_status.py                 _bb_code_status (custom survey Observation)
  primary_ref.py                 primary_condition_ref + is_chronic_primary + _icd_base + opaque Condition id helper (canonical resolver)
```

## テスト

```bash
pytest tests/unit -k "condition or allergy_intolerance or clinical_impression or hai_condition or code_status" -q
pytest tests/integration -k "document_chain or hai" -q
```

audit run (`clinosim audit run --module hai` / `--module document`)
が本ファミリを間接的に exercise する — HAI Condition emit は `hai`
AD-60 plug-in で、ClinicalImpression + primary-Condition-ref 不変量
は `document` AD-60 plug-in (49-check lift_firing_proof) で guard
されている。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
