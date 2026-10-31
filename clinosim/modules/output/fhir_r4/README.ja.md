# `fhir_r4/` — FHIR R4 出力 subsystem

## 概要

生成 CIF から FHIR R4 Bulk-Data NDJSON を emit する (AD-31 —
resource type ごとに 1 NDJSON + `manifest.json`、per-encounter
Bundle wrapping は行わない)。AD-56 の
`register_bundle_builder` / `_BUNDLE_BUILDERS` plug-in 面、domain 別
resource builder (7 臨床 domain subpackage)、共有 FHIR fragment
helper (`lib/`)、timestamp / JP-CLINS profile / specimen / bundle
strip を最終化する post-processing pipeline (`post_process/`) を所有。

`convert_cif_to_fhir` が top-level entry で、全 downstream adapter
がこれを呼ぶ (built-in `FhirR4Adapter` in
[`../adapters_builtin.py`](../adapters_builtin.py) は wrap する)。

## Scope

- **In scope**: `_BUNDLE_BUILDERS` registry + `register_bundle_builder`
  + `available_builders`; `convert_cif_to_fhir` orchestrator
  (`CIFReader` で CIF を read、患者を walk、全 builder を呼び出し、
  post-processing を適用、resource type ごとに NDJSON + manifest を
  書く);`_build_bundle` fan-out;`_fhir_id_is_spec_valid` guard;
  `_sort_ndjson_by_id_inplace` write 後 sort;7 臨床 domain
  subpackage (`conditions/`, `demographics/`, `documents/`,
  `encounters/`, `labs/`, `medications/`, `procedures/`);共有
  library (`lib/`);post-processing pipeline
  (`post_process/`)。
- **Out of scope**: CIF 生成本体;adapter registry
  ([`../adapter.py`](../adapter.py));CIF writer / reader
  ([`../cif_writer.py`](../cif_writer.py) +
  [`../cif_reader.py`](../cif_reader.py));JSON serialization
  (Python `json` に委譲)。

## Public API

```python
from clinosim.modules.output.fhir_r4 import (
    convert_cif_to_fhir,             # (cif_dir, out_dir, country="US", narrative_version="current") -> None
    register_bundle_builder,         # (fn) — AD-56 plug-in 登録
    available_builders,              # () -> list[str] 登録 builder 名
    _fhir_id_is_spec_valid,          # (rid) -> bool  (test + builder 用 guard)
)
from clinosim.modules.output.fhir_r4.lib.common import (
    BundleContext,                   # 各 _bb_* builder に渡される dataclass
    entry,                           # (resource) -> Bundle entry dict
    survey_category,                 # () -> [{coding: [...]}] survey category CodeableConcept
    loinc_coding,                    # (code, lang) -> {system, code, display}
    build_ecs_institution_extension, # JP JP_Organization_eCS institution
    build_ecs_department_extension,
    attach_ecs_institutional_extensions,
)
```

全 `_bb_*` bundle-builder 関数は同 signature:
`_bb_<resource>(ctx: BundleContext) -> list[dict]`。default registry
は 45 builder: 7 domain subpackage に 27、`lib/inline_bb.py` に 11
(Patient, Coverage, Encounter, Condition, Occupation, vitals,
MedicationRequest / 退院時 MedicationRequest, MedicationAdministration,
Procedure, Practitioner)、
[`clinosim/modules/newborn/fhir_emit.py`](../../newborn/fhir_emit.py)
に新生児 builder 7。domain README file が family 別 builder を列挙する。

## 決定論

- FHIR emit は既生成 CIF に対する純粋 serialization。RNG 未使用、
  `ENRICHER_SEED_OFFSETS` にも未登録。
- **byte-identity 契約** (AD-31 + AD-16):
  `(cif_dir, country, narrative_version)` タプル固定で run 間の
  NDJSON が byte-identical。
- `_sort_ndjson_by_id_inplace` が書込後 NDJSON を resource id で
  sort し、traversal 順に関係なく line 順を決定論化する。
- `_fhir_id_is_spec_valid` が FHIR spec の 64 文字 id +
  `[A-Za-z0-9\-\.]` character class を `convert_cif_to_fhir` の
  NDJSON writer で検査する。fail-soft (不正 id は resource type 別に
  count して warning log、write 自体は継続)。

## 依存

- `clinosim.modules._shared` — `is_jp`, `resolve_lang` (個別 builder
  では他 helper も)。
- `clinosim.modules.output.cif_reader` — 構造化 + narrative-version
  merge 済み CIF load 用 `CIFReader`。
- `clinosim.codes` — code-system URI + 表示 lookup。
- `clinosim.locale.loader` — locale scope の code-mapping YAML。
- `clinosim.modules.newborn.fhir_emit` — registry 内の 7 つの
  `_bb_newborn_*` builder。
- `clinosim.simulator.log` — export 進捗 event。
- 各 domain subpackage は `lib.common.BundleContext` + 共有 fragment
  helper を import。`lib/common.py` 自体は domain を import しないが、
  `lib/inline_bb.py` は domain subpackage の builder helper を
  (`lib/ed_reattribution.py` は `encounters/` を) import するため、
  `lib/` 全体は leaf ではない。
- `heapq`, `json`, `os`, `re`, `tempfile`, `uuid` — 標準ライブラリ
  (serialization + 外部 merge による NDJSON sort)。

## 定数と設定

- **Bundle-builder registry** — `builder.py` の
  `_BUNDLE_BUILDERS: list[Callable]` (`__init__.py` が再 export)。
  list 順 = emission 順。`_build_bundle` が使う全 `_bb_*` builder が
  module top で import され list に並ぶ。import 時 assert が `_bb_`
  prefix を強制。`register_bundle_builder` は file 編集なしで新
  builder を末尾追加し (AD-56)、`_bb_` prefix でない名前は
  `ValueError`、同名関数は重複登録しない。
- **FHIR resource-id 形状**: id scheme は各 builder が所有 (例:
  `allergy-{patient_id}-{nn}`、`loc-ward-{ward}`、`sr-…`、`doc-…`。
  `lib/ids.py` が opaque id を導出)。ID prefix 定数は所有 module 側
  ([`clinosim.modules.document`](../../document/README.ja.md) の
  `DOC_REFERENCE_ID_PREFIX` 等、`labs/service_request.py` の
  `SR_ID_PREFIX` / `PLACER_ORDER_NUMBER_SYSTEM` 等)。
- **`BundleContext`** (`lib/common.py`): 各 `_bb_*` builder に
  渡される read-only context。field: `record`, `country`,
  `roster_map`, `hospital_config`, `patient_data`, `patient_id`,
  `is_readmission`, `prior_encounter_id`, `primary_dx_code`,
  `admit_dx_code`, `admit_dx_system`, `primary_enc_id`,
  `patient_sex`, `encounter_resource_index`, `snapshot_date`,
  `emitted_mr_ids`。
- **JP-CLINS extension** (`lib/common.py`):
  `build_ecs_institution_extension`,
  `build_ecs_department_extension`,
  `attach_ecs_institutional_extensions` — JP-CLINS Composition
  profile が要求する eCS (electronic Clinical Statement)
  institution / department extension。
- **Post-processing pipeline** ([`post_process/`](post_process/README.ja.md))
  — bundle-level pipeline (PR3、Issue #556 を fold): timestamp
  正規化、JP-CLINS profile URI、specimen 合成、strip pass。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/
  __init__.py                        薄い再 export facade (public + back-compat private 名)
  builder.py                         convert_cif_to_fhir + _BUNDLE_BUILDERS registry + _build_bundle + snapshot / death reconciliation + NDJSON sort
  lib/                               共有 FHIR fragment helper (common / localization / reference_data / inline_bb / generator_metadata / ids / ed_reattribution)
  demographics/                      Patient / Practitioner / FamilyMemberHistory / smoking + alcohol Observation
  encounters/                        Encounter / CareTeam / CareLevel / Location + Organization (facility) / Endpoint
  medications/                       MedicationRequest + MedicationAdministration
  labs/                              Observation (lab + vitals) / DiagnosticReport / ServiceRequest / microbiology / ImagingStudy / blood_type / anthropometrics / stage_scale_observations / _reference_ranges / coding_package + coding_strategy
  procedures/                        Procedure / Immunization / Device + DeviceUseStatement / nursing (survey Observation) / oxygen_therapy / procedure_name_snomed (.py + .yaml)
  conditions/                        Condition / AllergyIntolerance / ClinicalImpression / HAI Condition / CodeStatus (custom Observation) / primary_ref
  documents/                         Composition / DocumentReference / DocumentReference (checkup / eCheckup) / imaging_report / referral_orgs / jp_clins/ (文書別 JP-CLINS section builder)
  post_process/                      bundle-level pipeline (datetime 正規化 / profile / specimen / strip / populate)
```

## FHIR resource → domain mapping (canonical 表)

| FHIR resource | Domain module |
| --- | --- |
| Patient | `demographics/patient.py` (registry entry `_bb_patient` は `lib/inline_bb.py`) |
| Coverage | `lib/inline_bb.py` (`_bb_coverage`) |
| Observation (occupation) | `lib/inline_bb.py` (`_bb_occupation`) |
| Practitioner + PractitionerRole | `demographics/practitioner.py` |
| FamilyMemberHistory | `demographics/family_history.py` |
| Observation (smoking / alcohol / social) | `demographics/smoking_alcohol.py` |
| Encounter | `encounters/encounter.py` |
| CareTeam | `encounters/care_team.py` |
| CareLevel (custom `jp-care-level` Observation) | `encounters/care_level.py` |
| Location + Organization | `encounters/facility.py` |
| Endpoint | `encounters/endpoint.py` |
| MedicationRequest + MedicationAdministration | `medications/medications.py` (registry entry は `lib/inline_bb.py`) |
| Observation (lab + vitals) | `labs/observations.py` (`_bb_vitals` registry entry は `lib/inline_bb.py`) |
| Observation (身長 / 体重 / BMI / 頭囲) | `labs/anthropometrics.py` |
| Observation (慢性疾患 stage scale) | `labs/stage_scale_observations.py` |
| 新生児 Apgar / bilirubin / CCHD Observation、代謝スクリーニング ServiceRequest / Specimen / Observation / DiagnosticReport | [`clinosim/modules/newborn/fhir_emit.py`](../../newborn/fhir_emit.py) |
| DiagnosticReport | `labs/diagnostic_report.py` |
| ServiceRequest | `labs/service_request.py` |
| Observation (microbiology) | `labs/microbiology.py` |
| ImagingStudy | `labs/imaging_study.py` |
| Observation (ABO + RhD) | `labs/blood_type.py` |
| — (JP-CLINS lab code loader) | `labs/coding_package.py` |
| — (JP-CLINS lab code dispatch) | `labs/coding_strategy.py` |
| Procedure | `procedures/procedures.py` (registry entry `_bb_procedures` は `lib/inline_bb.py`) |
| Procedure (酸素療法 session) | `procedures/oxygen_therapy.py` |
| Immunization | `procedures/immunization.py` |
| Device + DeviceUseStatement | `procedures/device.py` |
| Observation (nursing flowsheet) | `procedures/nursing.py` |
| Condition (primary + secondary + chronic) | `conditions/conditions.py` |
| AllergyIntolerance | `conditions/allergy_intolerance.py` |
| ClinicalImpression | `conditions/clinical_impression.py` |
| Condition (HAI) | `conditions/hai.py` |
| CodeStatus (custom Observation) | `conditions/code_status.py` |
| Composition | `documents/composition.py` |
| DocumentReference | `documents/documents.py` |
| DocumentReference (checkup / eCheckup) | `documents/document_reference_checkup.py` |
| Composition (画像検査報告書) | `documents/imaging_report.py` |

## Enricher 配線

該当なし — serialization 層で enricher ではない。
`register_builtin_enrichers` に登録なく、`ENRICHER_SEED_OFFSETS`
にも seed 未登録。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Built-in FHIR adapter | [`../adapters_builtin.py`](../adapters_builtin.py) (`FhirR4Adapter.convert`) | AD-58 registry のため `convert_cif_to_fhir` を wrap。 |
| Backwards-compat shim | [`../fhir_r4_adapter.py`](../fhir_r4_adapter.py) | pre-migration caller のため公開面全体を再 export (Issue #555 PR1)。 |
| Downstream tools | (外部) | Bulk Data Access spec に沿った NDJSON + manifest.json — HAPI FHIR, InferNo 等。 |

## テスト

```bash
pytest tests/unit -k "fhir or output" -q
pytest tests/integration -k "fhir or export or servicerequest_chain or document_chain or hai_susceptibility" -q
```

各 domain subpackage は独自の README + test を持つ。audit run
(`clinosim audit run`) は AD-60 module audit plug-in (hai /
antibiotic / order / imaging / document / triage) を exercise し、
その一部が FHIR emission 契約を cross-verify する。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
