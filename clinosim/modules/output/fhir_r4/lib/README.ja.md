# `fhir_r4/lib/` — 共有 FHIR R4 builder ライブラリ

## 概要

[`fhir_r4/`](../README.ja.md) 配下の全 clinical-domain builder
subpackage が import する共有 low-level fragment helper。`common.py`、
`context.py`、`dosage.py`、`ecs_extensions.py`、`fhir_time.py`、
`localization.py`、`reference_data.py`、`ids.py` は leaf 層 — 各
helper は top-level resource ではなく FHIR *fragment* (Coding,
CodeableConcept, Bundle entry, UCUM quantity, Dosage, datetime 文字列,
JP eCS extension) か共有 `BundleContext` を提供するため、
resource-builder module は adapter facade を循環せずこれらから
import できる。例外は `inline_bb.py` と `ed_reattribution.py` で、
domain subpackage の builder helper を import する (下記)。

旧 `_fhir_common` compat shim は削除済み。helper を所有する `lib`
module から直接 import する (Issue #545 rename)。

## Scope

- **In scope**:
  - `context.py` — `BundleContext` dataclass (各 `_bb_*` builder が
    受け取る read-only context)。
  - `common.py` — fragment helper: `entry`、`survey_category(lang)`、
    `build_address`、`build_telecom`、`build_presented_form`、
    `build_reference_range`、`build_diagnosis_codeable_concept`、
    `iter_diagnosis_mapping_targets`、`infer_severity`、
    `severity_coding`、`make_participant`、`map_encounter_status`、
    ほか非 export helper (`system_coding`、`dual_slot_concept`、
    `display_entry`、`_escape_html`、`_social_category`)。
  - `ecs_extensions.py` — JP-CLINS eCS 機関 / 部門 extension
    (`build_ecs_institution_extension`、
    `build_ecs_department_extension`、
    `attach_ecs_institutional_extensions`)、施設番号は病院の 10 桁
    医療機関コード (`hospital_institution_code`、
    `locale/jp/facility_identity.yaml`、Issue #3129)、
    `_JP_ECS_DEPARTMENT_PLACEHOLDER` = `primary_care` 診療科の JA
    表示、extension URL (`_JP_ECS_INSTITUTION_NUMBER_EXT_URL`、
    `_JP_ECS_DEPARTMENT_EXT_URL`、`_JP_ECS_INSTITUTION_ID_SYSTEM`)。
  - `jp_profiles.py` — 複数箇所で使う JP Core / JP-CLINS の
    profile / identifier system URI (`JP_*_PROFILE`、`JP_*_SYSTEM`)。
    各 builder はリテラルを書かずこれを import する (Issue #2842、
    `tests/unit/output/test_jp_uri_constants_2842.py` で guard)。
  - `profile_meta.py` — `profile_meta(resource_type, country, *fhir_profiles)`
    / `declared_profiles(...)`: 国プロファイルが適用する FHIR profile
    (`profile.uses(name)`) について、resource type の `meta.profile` URL を
    `clinosim/codes/data/fhir-profiles-<name>.yaml` から返す (Issue #3145)。
    `<ResourceType>/<variant>` キー (`Observation/LabResult`、
    `DiagnosticReport/Radiology` など) は表の `variants` 節を読み、builder
    自身が宣言する profile variant に使う (Issue #3201)。
    `language_uses(lang, fhir_profile)`: 出力言語で動く builder 向けに、その
    言語の出力が FHIR profile を適用するかを返す (Issue #3203)。
  - `dosage.py` — MedicationRequest / MedicationAdministration の
    Dosage helper (`build_dosage_instruction`、`build_route_concept`、
    `canonicalize_route`、`augment_iv_dosage_with_rate`、
    `resolve_iv_infusion_default`、`map_mar_status`、再 export の
    `strip_protocol_prefix`)。
  - `fhir_time.py` — FHIR date / dateTime / instant 整形
    (`to_fhir_date`、`to_fhir_datetime`、`to_fhir_instant`、
    `tz_suffix_for_country`、`derive_meta_last_updated`)、
    `_JST_TZ_SUFFIX = "+09:00"` / `_UTC_TZ_SUFFIX = "Z"`。
  - `localization.py` — EN / JA テキスト localisation dispatch
    (`localize_drug_name`、`localize_fixed_label`、`code_lookup`、
    および free-text 翻訳器の再 export。翻訳器本体と
    `_RATE_ADJUSTMENT_SUFFIX_RE` regex は `clinosim.locale.free_text`
    に移動済み)。
  - `reference_data.py` — profile URI、canonical URL、code-system
    URL。`_JP_CONDITION_SEVERITY_CS` を含む。
  - `inline_bb.py` — まだ 7 clinical-domain subpackage に split され
    ていない legacy inline building-block builder。11 `_bb_*` 関数
    (`_bb_patient`, `_bb_coverage`, `_bb_encounters`,
    `_bb_conditions`, `_bb_occupation`, `_bb_vitals`,
    `_bb_medication_requests`, `_bb_discharge_medication_requests`,
    `_bb_medication_admins`, `_bb_procedures`, `_bb_practitioners`)
    を export し、親 `builder.py` が split 済 builder と並列に登録する。
    domain subpackage から `_build_*` helper を import する。
    新 builder は必ず clinical-domain subpackage に置き、
    `inline_bb.py` を拡張してはならない。
  - `generator_metadata.py` — cohort export 時の sidecar
    `_generator_metadata.json` emission。定数:
    `_SIDECAR_FILENAME = "_generator_metadata.json"`,
    `_RECENT_MERGES_LIMIT = 30`,
    `_PR_NUMBER_RE = r"\(#(\d+)\)\s*$"`。
  - `ed_reattribution.py` — `convert_cif_to_fhir` が via-ED IMP
    encounter を合成 ED bridge encounter に再帰属する際に使う
    `reattribute_encounter_to_ed_bridge` helper (N-3 PR #810 chain)。
  - `ids.py` — opaque Resource.id 導出 (Issue #349):
    `CLINOSIM_IDENTIFIER_SYSTEM_PREFIX = "urn:clinosim:identifier:"`、
    `structural_key_system(kind)` (`urn:clinosim:identifier:<kind>`
    を返す)、`derive_opaque_id`、`wrap_as_identifier`。
- **Out of scope**: FHIR-resource 固有の builder — 兄弟
  clinical-domain subpackage 側。

## Public API

`lib/__init__.py` は namespace stub (`__all__ = []`)。各 module が
自前の `__all__` を宣言する。主な entry point:

```python
from clinosim.modules.output.fhir_r4.lib.context import BundleContext   # dataclass
from clinosim.modules.output.fhir_r4.lib.common import (
    entry,                                # (resource) -> Bundle entry dict
    survey_category,                      # (lang) -> survey category CodeableConcept list
)
from clinosim.modules.output.fhir_r4.lib.ecs_extensions import (
    build_ecs_institution_extension,      # () -> JP eCS 機関 extension
    build_ecs_department_extension,       # (department_text="") -> extension
    attach_ecs_institutional_extensions,
)
from clinosim.modules.output.fhir_r4.lib.dosage import (
    build_dosage_instruction,             # (order, country="US") -> Dosage | None
    build_route_concept,                  # (raw_route, country) -> CodeableConcept | None
    map_mar_status,                       # (status) -> MedicationAdministration.status
)
from clinosim.modules.output.fhir_r4.lib.fhir_time import (
    to_fhir_date, to_fhir_datetime, to_fhir_instant,
    tz_suffix_for_country, derive_meta_last_updated,
)
from clinosim.modules.output.fhir_r4.lib.localization import (
    localize_drug_name,                   # clinosim.locale.free_text からの再 export
    localize_fixed_label,                 # (en_label, country) -> str
)
from clinosim.modules.output.fhir_r4.lib.inline_bb import (
    # 11 legacy _bb_* builder (親 facade が登録)
    _bb_patient, _bb_coverage, _bb_encounters, _bb_conditions,
    _bb_occupation, _bb_vitals, _bb_medication_requests,
    _bb_discharge_medication_requests, _bb_medication_admins,
    _bb_procedures, _bb_practitioners,
)
from clinosim.modules.output.fhir_r4.lib.generator_metadata import write_generator_metadata
from clinosim.modules.output.fhir_r4.lib.ed_reattribution import reattribute_encounter_to_ed_bridge
from clinosim.modules.output.fhir_r4.lib.ids import (
    CLINOSIM_IDENTIFIER_SYSTEM_PREFIX,    # "urn:clinosim:identifier:"
    structural_key_system,                # (kind) -> URI
    derive_opaque_id,                     # (prefix, structural_key, hash_len=12) -> str
    wrap_as_identifier,                   # (structural_key, system) -> Identifier dict
)
```

## 決定論

該当なし — 渡された入力に対する pure helper。`generator_metadata`
は export 時に現 git HEAD を read して sidecar provenance を記録
するが、sidecar は意図的に byte-diff scope 外
(`write_generator_metadata` docstring 参照)。

## 依存

- `clinosim.modules._shared` — `is_jp`, `is_us`,
  `strip_protocol_prefix`。`clinosim.countries` — `lang_for`。
- `clinosim.codes` — `get_system_uri`, `lookup`, `display`,
  `is_english_only_system`。`codes.icd10`、`codes.prefectures`、
  `codes.ucum`、`codes.snomed`、`codes.procedures`、`codes.drugs`。
- `clinosim.locale` — `loader` (表示 map、code mapping、基準範囲、
  頻度 token、IV 持続投与 default)、`loaders.medical_display`、
  `localized`、`table`、`free_text`。
- `clinosim.datafiles` — `load_data_yaml` (`dosage.py`)。
- `clinosim.modules.observation.engine` — `therapeutic_range`
  (`common.build_reference_range`、lazy import)。
- `clinosim.simulator.log` と `clinosim.__version__`
  (`generator_metadata.py`)。
- `re`, `datetime`, `dataclasses`, `hashlib`, `json`, `subprocess` —
  標準ライブラリ。
- `inline_bb.py` / `ed_reattribution.py` は clinical-domain
  subpackage を import する (`ed_reattribution.py` は
  `clinosim.modules.document.narrative.registry` も)。`lib/` のどれも
  `builder.py` facade は import しない。

## 定数と設定

- **`_FHIR_ID_PATTERN`** — FHIR R4 仕様の id pattern
  (`[A-Za-z0-9\-\.]{1,64}`)。`lib/` には無く、`../builder.py` に
  のみ定義 (`_fhir_id_is_spec_valid` が使用、NDJSON writer での
  fail-soft 検査)。
- **`_JST_TZ_SUFFIX = "+09:00"`** / **`_UTC_TZ_SUFFIX = "Z"`**
  (`fhir_time.py`) — `to_fhir_*` 整形と下流 post-processing 用の
  timezone suffix 定数。国ごとの suffix は country profile の `timezone`
  (`clinosim/locale/<cc>/country.yaml`) で、`tz_suffix_for_country` が
  返す。国が無いときだけ `Z`。
- **`CLINOSIM_IDENTIFIER_SYSTEM_PREFIX = "urn:clinosim:identifier:"`**
  — clinosim 内部 identifier system の名前空間 prefix
  (`HAI_EVENT_ID_SYSTEM`、staff identifier system 等)。
- **eCS placeholder** (`ecs_extensions.py`) — cohort に実機関番号 /
  部門コードが無いときに使う (JP eCS profile が field を要求するため、
  実 facility を主張せず cardinality を満たす)。
- **`_RECENT_MERGES_LIMIT = 30`** (`generator_metadata.py`) —
  sidecar に記録する recent-merge PR 番号の上限。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/lib/
  __init__.py                        namespace のみ (再 export 無し)
  common.py                          fragment helper (entry、survey_category、住所 / telecom / 基準範囲 / 診断 / 重症度 ...)
  context.py                         BundleContext dataclass
  dosage.py                          Dosage / route / IV 速度 / MAR status helper
  ecs_extensions.py                  JP eCS 機関 / 部門 extension + placeholder
  fhir_time.py                       to_fhir_date / datetime / instant + tz suffix 定数
  localization.py                    en / ja テキスト localisation dispatch
  reference_data.py                  profile URI + code-system URI
  inline_bb.py                       11 legacy _bb_* builder (拡張しない — 新規は domain subpackage へ)
  generator_metadata.py              _generator_metadata.json sidecar emission
  ed_reattribution.py                reattribute_encounter_to_ed_bridge (N-3 PR #810)
  ids.py                             CLINOSIM_IDENTIFIER_SYSTEM_PREFIX + structural_key_system + derive_opaque_id + wrap_as_identifier
```

## テスト

```bash
pytest tests/unit -k "fhir_common or lib or generator_metadata or ed_reattribution or structural_key" -q
```

AD-60 audit plug-in (hai, antibiotic, order, imaging, document, triage) が
本層から多くの定数を `canonical_constants` cross-check のため import
する。ここでの rename は該当 audit run を fail させる。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
