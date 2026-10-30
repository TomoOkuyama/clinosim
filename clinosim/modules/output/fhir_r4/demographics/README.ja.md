# `fhir_r4/demographics/` — Patient / Practitioner / FamilyMemberHistory / 社会歴 builder

## 概要

demographics + 社会歴ファミリの FHIR R4 resource 全てを emit:
`Patient`、`Coverage` + payor `Organization` と occupation
`Observation` (いずれも `patient.py` で構築。registry wrapper
`_bb_patient` / `_bb_coverage` / `_bb_occupation` は
[`../lib/inline_bb.py`](../lib/inline_bb.py))、`Practitioner` +
`PractitionerRole`、`FamilyMemberHistory`、smoking / alcohol
社会歴 `Observation`。standalone allergy path は
[`../conditions/`](../conditions/README.ja.md) の `AllergyIntolerance`
builder が唯一の emit path で、`patient.py` 内の legacy
`_build_allergy_intolerance` は残っているが呼ばれない。

## Scope

- **In scope**: `_build_patient` (Patient + birthDate / sex /
  address / telecom / marital + language) + Coverage / payor
  Organization 構築 (`_build_coverage_resources`) + occupation
  Observation (`_build_occupation_observation`);
  `_build_practitioner` + `_build_practitioner_role`;
  `_bb_family_history` + `_resolve_family_history_code` +
  `_build_relationship_codeable`; `_bb_smoking_status` +
  `_bb_alcohol_use` + `_obs` + `_sdoh_effective_datetime` +
  `_sdoh_performer_ref`。
- **Out of scope**: patient / practitioner / family-history / SDOH
  の **生成**
  ([`clinosim.modules.population`](../../../population/README.ja.md)、
  [`clinosim.modules.identity`](../../../identity/README.ja.md)、
  [`clinosim.modules.staff`](../../../staff/README.ja.md)、
  [`clinosim.modules.family_history`](../../../family_history/README.ja.md)、
  [`clinosim.modules.sdoh`](../../../sdoh/README.ja.md));JP 保険番号
  (`identity` module 内)。

### 新生児 (Newborn) Patient (v0.5 → v0.6.0)

周産期分娩 LifeEvent は CIF 上に対の新生児 `PatientProfile` を生成する
(詳細:
[`../../../patient/README.ja.md`](../../../patient/README.ja.md) —
`id = "<mother_id>-BABY"` (多胎の 2 人目以降は
`<mother_id>-<N>-BABY`)、`birthDate` = 分娩日、世帯は母親から継承)。
新規 Patient builder は不要 — 既存 `_build_patient` が CIF から他の
患者と同様に新生児を拾う。母親↔新生児のリンクは新生児側の Encounter
(`Encounter.partOf` → 母親の分娩 encounter) で表現され、これは兄弟の
[`../encounters/`](../encounters/README.ja.md) builder が扱う (本
subpackage は関与しない)。

## Public API

各 builder は親 facade (`_BUNDLE_BUILDERS` in
[`../builder.py`](../builder.py)) に登録済み。直接 import は稀:

```python
from clinosim.modules.output.fhir_r4.demographics.patient import (
    _build_patient,                     # (patient_dict, country) -> Patient dict
    _build_coverage_resources,          # (patient_dict, country, encounters=None, snapshot_date=None) -> [Coverage, payor Organization, ...]
    _build_occupation_observation,      # -> occupation Observation
    _build_allergy_intolerance,         # legacy、呼ばれない (emit path は conditions/)
)
from clinosim.modules.output.fhir_r4.demographics.practitioner import (
    _build_practitioner,                # (staff_id, roster_map, country) -> Practitioner dict
    _build_practitioner_role,           # (staff_id, roster_map, country) -> PractitionerRole dict
)
from clinosim.modules.output.fhir_r4.demographics.family_history import (
    _bb_family_history,                 # bundle-builder (ctx) -> [FamilyMemberHistory, ...]
    _resolve_family_history_code,       # (code, country) -> 解決済み ICD/JP コード
    _build_relationship_codeable,       # (rel, display_map, lang) -> CodeableConcept
)
from clinosim.modules.output.fhir_r4.demographics.smoking_alcohol import (
    _bb_smoking_status,                 # bundle-builder
    _bb_alcohol_use,                    # bundle-builder
    _sdoh_effective_datetime,           # (ctx) -> SDOH anchor の ISO datetime 文字列
    _sdoh_performer_ref,                # (ctx) -> Practitioner reference 文字列
)
```

## 決定論

該当なし — 各 builder は入力 CIF の pure 関数。`_identity_cfg` は
`@lru_cache` で国別 lookup 反復コストゼロ。親 facade が emit 済み
NDJSON を id で sort する。

## 依存

- `clinosim.modules._shared` — `is_jp`, `is_us`, `resolve_lang`。
- `clinosim.modules.output.fhir_r4.lib.common` — `_coding_with_display`,
  `_social_category`, `build_address`, `build_telecom`, `to_fhir_date`,
  `BundleContext`、および fragment helper。
- `clinosim.modules.output.fhir_r4.lib.localization` — JP 表示
  localisation。
- `clinosim.modules.output.fhir_r4.lib.reference_data` — Practitioner
  資格 / role の reference-data lookup。
- `clinosim.codes` — LOINC / SNOMED / ICD / JP-Core / HL7 v3-RoleCode
  の `get_system_uri`, `lookup`。
- `clinosim.locale.loader` — JP payor + coverage 定数の
  `load_identity_config`、`load_practitioner_qualifications`。
- `clinosim.modules.family_history.engine.load_reference`、
  `clinosim.modules.sdoh.load_social_history` — 表示 / code の
  reference data。

## 定数と設定

- **Patient identifier** — JP payor / coverage 定数は
  [`clinosim/locale/jp/identity.yaml`](../../../../locale/jp/identity.yaml)
  から `load_identity_config` 経由で load。`_identity_cfg` cache が
  lookup を free に保つ。
- **Marital / language / coverage 表示** — `patient.py` に inline
  (`clinosim.codes` 標準 lookup pattern に収まらない 2 enum resource
  の国別 display map)。
- **Profile URI** — JP 出力では `practitioner.py` が
  `JP_Practitioner` / `JP_PractitionerRole` を inline で付与。他の
  JP Core / JP-CLINS / US Core profile URI は
  [`../post_process/profile.py`](../post_process/profile.py) が積む。
  US Patient は US Core race / ethnicity / birthsex extension を持つ。
- **Family-history relationship coding** — HL7 v3-RoleCode
  ([`family_history` module README](../../../family_history/README.ja.md)
  に記載の Issue #369 v23 regression ルール — per-code JA 表示は
  load-bearing)。
- **社会歴 SDOH anchor**: `_sdoh_effective_datetime` が smoking /
  alcohol / care-level の `effectiveDateTime` を最古 encounter 入院
  時刻から導出し標準化する (`fhir_r4/encounters/care_level.py` C2-10 pattern と一致)。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/demographics/
  __init__.py                    namespace stub (builder は ../builder.py / ../lib/inline_bb.py が import)
  patient.py                     _build_patient + Coverage + payor Org + occupation + patient_ref + legacy allergy (~1,200 LOC)
  practitioner.py                _build_practitioner + _build_practitioner_role
  family_history.py              _bb_family_history + _resolve_family_history_code + _build_relationship_codeable
  smoking_alcohol.py             _bb_smoking_status + _bb_alcohol_use + _sdoh_effective_datetime + _sdoh_performer_ref
```

## テスト

```bash
pytest tests/unit -k "patient or practitioner or family_history_relationship or smoking or alcohol" -q
```

個別 test file: `test_fhir_family_history_*.py`,
`test_fhir_family_history_relationship.py` (Issue #369 guard)、
`test_fhir_sdoh.py` (integration)、そして `tests/unit/output/` 下の
patient / coverage test。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
