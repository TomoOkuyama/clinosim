# `fhir_r4/encounters/` — Encounter + CareTeam + CareLevel + facility + Endpoint builder

## 概要

encounter + 運用 context ファミリの FHIR R4 resource 全てを emit:
`Encounter`、`CareTeam` (主治医 + 主担当看護師 — AGENTS.md AD-64 の
2-name scope)、`Endpoint` (imaging study ごとの DICOM WADO base
URL)、`Location` + `Organization` (facility Bundle として CIF write
時に一括生成)、および JP `CareLevel` (要介護度) の custom social-history
`Observation`。

## Scope

- **In scope**: `_build_encounter` (root Encounter builder);
  `_bb_care_teams` + `_build_care_team` + `CARE_TEAM_ID_PREFIX =
  "careteam-"` + `_CARE_TEAM_CATEGORY_EN` / `_JA` — 2-name scope
  契約 (participant[0] = attending、participant[1] = nurse は
  `primary_nurse_id` 非空時のみ、participant[] は決して `[]` にしない);
  `_bb_endpoints` + `_build_endpoint` +
  `DICOM_WADO_RS_CONNECTION_TYPE = "dicom-wado-rs"` +
  `_DEFAULT_WADO_BASE_URL`;`_build_facility_bundle`
  (Location + Organization Bundle、コホート export 時に 1 度生成);
  `_bb_care_level` + `_CARE_LEVEL_LOINC = "80391-6"`
  (PR2 G2 で `_fhir_sdoh.py` から抽出 — JP `jp-care-level`
  valueCodeableConcept を持つ social-history Observation)。
- **Out of scope**: encounter の **シミュレーション**
  ([`clinosim.simulator`](../../../../simulator/));facility 運用状態
  model ([`clinosim.modules.facility`](../../../facility/README.md));
  staff roster + `assign_staff` dispatch
  ([`clinosim.modules.staff`](../../../staff/README.md));`Endpoint`
  が参照する `ImagingStudy` を生成する imaging chain
  ([`clinosim.modules.imaging`](../../../imaging/README.md));
  要介護度付与
  ([`clinosim.modules.care_level`](../../../care_level/README.md))。

## Public API

各 builder は親 facade (`_BUNDLE_BUILDERS` in
[`../__init__.py`](../__init__.py)) に登録済み。cross-family
consumer 向けの直接 import:

```python
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter
from clinosim.modules.output.fhir_r4.encounters.care_team import (
    _bb_care_teams,
    _build_care_team,
    CARE_TEAM_ID_PREFIX,                 # "careteam-"
)
from clinosim.modules.output.fhir_r4.encounters.endpoint import (
    _bb_endpoints,
    _build_endpoint,
    DICOM_WADO_RS_CONNECTION_TYPE,       # "dicom-wado-rs"
)
from clinosim.modules.output.fhir_r4.encounters.facility import _build_facility_bundle
from clinosim.modules.output.fhir_r4.encounters.care_level import _bb_care_level
```

## 決定論

該当なし — CIF に対する pure builder。RNG 未使用。親 facade が
NDJSON を id で sort する。

## 依存

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`,
  `get_attr_or_key`。
- `clinosim.modules.output.fhir_r4.lib.common` — `BundleContext`,
  `_coding_with_display`, `_social_category`, `loinc_coding`,
  `attach_ecs_institutional_extensions`。
- `clinosim.modules.output.fhir_r4.conditions.primary_ref` —
  `Encounter.reasonReference` + `Encounter.diagnosis[].condition`
  の `primary_condition_ref`。
- `clinosim.modules.output.fhir_r4.demographics.smoking_alcohol` —
  `_sdoh_effective_datetime` (care_level が SDOH anchor 再利用)。
- `clinosim.codes` — LOINC + SNOMED 表示 lookup。
- `clinosim.types.encounter` — `Encounter`, `EncounterStatus`,
  `EncounterType`, `TriageData`。

## 定数と設定

- **`CARE_TEAM_ID_PREFIX = "careteam-"`** —
  [`../../../document/audit.py`](../../../document/audit.py) の
  49-check `lift_firing_proof` から import される。
- **CareTeam 2-name scope** (AGENTS.md AD-64): participant[0] は
  常に emit (`attending_physician_id` が空なら `"UNKNOWN"`
  placeholder);participant[1] (nurse) は `primary_nurse_id` 非空時
  のみ emit。attending 単独ケースでも FHIR R4 cardinality を満たすため
  `participant[]` は非空を保つ。
- **`_CARE_LEVEL_LOINC = "80391-6"`** — JP 要介護度 social-history
  Observation の LOINC observation code (JP は `text = "要介護度"`、
  US は `"Long-term care need level"`)。
- **`DICOM_WADO_RS_CONNECTION_TYPE = "dicom-wado-rs"`** —
  `Endpoint.connectionType.code`。encounter が facility 固有 PACS を
  持たないときに emit する placeholder base URL は
  `_DEFAULT_WADO_BASE_URL`
  (`https://wado.clinosim.example/dicomweb`)。
- **Facility Bundle**: `_build_facility_bundle` が
  cohort-export 時に `hospital_config` から Location + Organization
  Bundle を 1 つ組み立て、AD-31 master-bundle 規約に沿って
  `_facility.json` に書く。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/encounters/
  __init__.py                    空 (builder は親 __init__ が import)
  encounter.py                   _build_encounter root builder
  care_team.py                   _bb_care_teams + _build_care_team + CARE_TEAM_ID_PREFIX
  care_level.py                  _bb_care_level (custom Observation、JP 要介護度)
  endpoint.py                    _bb_endpoints + _build_endpoint + DICOM_WADO_RS_CONNECTION_TYPE
  facility.py                    _build_facility_bundle (Location + Organization master Bundle)
```

## テスト

```bash
pytest tests/unit -k "encounter or care_team or care_level or endpoint or facility" -q
pytest tests/unit -k fhir_care_level -q
pytest tests/integration -k "encounter or hai" -q
```

`document` AD-60 audit plug-in
([`../../../document/audit.py`](../../../document/audit.py)) が
`CARE_TEAM_ID_PREFIX` + CareTeam emit 不変量 (2-name scope +
participant[] 非空) を cross-verify する。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
