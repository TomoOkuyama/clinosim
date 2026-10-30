# `fhir_r4/post_process/` — bundle-level FHIR R4 post-processing pipeline

## 概要

`_bb_*` builder が返す各 resource に適用する post-emit の
resource 形状 pass 群 (PR3、Issue #556 fold): timezone 跨ぎ (JST vs
UTC) の datetime / instant 正規化、JP Core / JP-CLINS / US Core
profile URI assertion + JP eCS must-support field population、lab
Observation 用の companion Specimen 合成、2 つの strip pass (禁止
`Observation.referenceRange` extension、English-only CodeSystem 上の
日本語 `display`)。各 pass は [`../builder.py`](../builder.py) の
`_build_bundle` 内 (と `convert_cif_to_fhir` の facility bundle) で
builder が resource を返した直後に resource 単位で呼ばれる —
組立済み bundle 全体への別 pass ではない。

## Scope

- **In scope**:
  - `datetime_normalize.py` — emit された各 resource を walk し、全
    `_DATETIME_FIELDS` (dateTime / date + Period.start / end +
    instant `issued` / `lastUpdated`) を JP 出力は `+09:00` JST、
    US 出力は `Z` に正規化。
  - `profile.py` — `meta.profile` に JP Core / JP-CLINS (JP) または
    US Core (US) profile URI を積む (`_apply_jp_core_profile`,
    `_apply_jp_clins_profile`, `_apply_us_core_profile`)。URL
    registry は
    `clinosim/codes/data/fhir-profiles-{jp-core,us-core,jp-clins}.yaml`
    から load。`_JP_OBSERVATION_CATEGORY_SYSTEM`、
    `_JP_ECS_LAST_UPDATED_PLACEHOLDER`、resource-type 判別子
    (`_is_lab_observation`, `_medication_request_satisfies_ecs`) も
    所有。未使用の `_FHIR_ID_PATTERN` local copy を持つ。
  - `specimen.py` — lab Observation (id prefix `lab-` で builder 側
    `specimen` 未設定のもの。microbiology は自前 Specimen を持つ)
    ごとに companion `Specimen` resource を合成。
    `_COMPANION_SPECIMEN_ID_PREFIX = "spec-"` (`lib/ids.py` で opaque
    id)、SNOMED type code `_SPECIMEN_SNOMED_BLOOD = "119297000"` /
    `_SPECIMEN_SNOMED_URINE = "122575003"` (display は
    `clinosim.codes` で解決)。
  - `strip.py` — `_strip_forbidden_observation_reference_range_extensions`
    (`JP_Observation_LabResult_eCS` が `max=0` に固定する
    `Observation.referenceRange[*]` extension を削除) と
    `_strip_japanese_display_on_english_only_systems` (English-only
    CodeSystem 上の日本語 `display` を削除、CodeableConcept の
    `text` は残す)。
  - `populate.py` — 大きな populate module (~1,300 LOC)。
    JP eCS + JP-CLINS extension、MEDIS disease keynumber
    (`_MEDIS_DISEASE_KEYNUMBER_SYSTEM =
    "http://medis.or.jp/CodeSystem/master-disease-keyNumber"`、
    `_MEDIS_UNCODED_DISEASE_CODE = "99999999"` +
    `_MEDIS_UNCODED_DISEASE_DISPLAY = "未コード化傷病名"`)、
    JP MHLW ingredient-strength type
    (`_JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS` +
    `_JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_CODE = "1"` + display
    `"製剤量"`)、medication usage ePrescription
    (`_JP_MHLW_MEDICATION_USAGE_EPRESCRIPTION_CS`)、
    MedicationUsage uncoded fallback
    (`_JP_CLINS_MEDICATION_USAGE_UNCODED_CS`、code
    `"0X0XXXXXXXXX0000"`、display `"用法未指定"`)は
    `_resolve_mhlw_usage_code(drug_text, freq, period, period_unit,
    route_text)` (Issue #817 / PR #836/#837/#838/#840/#841) が
    (drug, cadence, route) tuple を実
    `MedicationUsage_ePrescription` code に mapping できない場合の
    fallback。resolver の dispatch 順序:
    (1) **route filter** — 非経口 route (`_non_oral_route_markers()`、
    `clinosim/codes/data/mhlw-ecs-non-oral-route-markers.yaml` から load:
    静注/皮下注/筋注/吸入/舌下/貼付/塗布/点眼/直腸/経腸/etc.) は
    MHLW oral CS に該当 family 無しのため常に dummy 返却、
    (2) **PRN 条件 code** (アセトアミノフェン→発熱時、サルブタモール
    →喘息発作時) を `_DRUG_PRN_MHLW_CODE` から、
    (3) **固定時間間隔** (Q3H → 1028… のみ、他 hourly は
    meal-context code と衝突) を `_HOURLY_CADENCE_MHLW_CODE` から、
    (4) **日次 cadence + 薬剤別 meal-context** heuristic (statin→QD-
    就寝前、PPI→QD-朝食前、bisphosphonate→QD-起床時、ワルファリン→
    QD-夕食後、biguanide→BID-朝夕食後、抗生剤→TID-朝昼夕食後 等) を
    `_FREQ_CONTEXT_TO_MHLW_CODE` から、(5) **cadence 欠落時の薬剤別
    想定 freq** を `_DRUG_IMPLIED_FREQ_{QD,BID,TID}` set から適用。
    これら dispatch 表は
    `clinosim/codes/data/mhlw-medication-usage-code.yaml` と
    `clinosim/codes/data/clinosim-drug-dosing-conventions.yaml` から
    load される yaml 由来 module 定数。
    JP p=10000 s500 sample で実 code coverage ~85.9% (**100%
    clinically correct** — MHLW oral code は `route.text=="経口"` の
    record のみに emit) を達成。残 ~14.1% dummy は MHLW CS 未収載
    route (吸入 10,175 / 静注 3,022 / 皮下注 2,675 / etc.) で spec-
    legit。前 wave (PR #836/#837/#838 = route filter 前) は ~97.6%
    coverage と報告したが、その内 ~13,796 records に semantic error
    (IV/吸入 drug に oral 服用 code 付与) を含んでいた。現在の低い
    numeric coverage は **semantic correctness win** で regression
    ではない、period-of-use
    extension URL (`_JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL`)、
    UCUM day code (`_UCUM_SYSTEM_URI`, `_UCUM_DAY_CODE = "d"`,
    `_UCUM_DAY_UNIT_JA = "日"`)、JP resource-instance identifier
    system (`_JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM =
    "http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier"`
    と clinosim 内部 `_CLINOSIM_OBSERVATION_ID_SYSTEM =
    "urn:clinosim:observation-id"`)、JP observation category 正規化
    (`_normalize_jp_observation_category`、
    `profile._JP_OBSERVATION_CATEGORY_SYSTEM =
    "http://jpfhir.jp/fhir/core/CodeSystem/JP_SimpleObservationCategory_CS"`
    を使用) を fill し、`_populate_condition_ai_mr_ecs_fields` と
    `_populate_practitioner_reference_display` も持つ。resource に
    自然な `meta.lastUpdated` anchor が無いときの fallback
    `_JP_ECS_LAST_UPDATED_PLACEHOLDER = "2026-01-01T00:00:00+09:00"`
    は `profile.py` 側。
- **Out of scope**: per-resource builder logic (兄弟 clinical-domain
  subpackage);NDJSON serialization 本体
  ([`../builder.py`](../builder.py));FHIR profile 定義本体
  ([`../labs/coding_package.py`](../labs/coding_package.py) が
  load する JP-CLINS + jpfhir-terminology package 内)。

## Public API

各 pass は [`../builder.py`](../builder.py) の `_build_bundle` /
`convert_cif_to_fhir` から呼ばれる。entry は全て underscore
prefix で、`post_process/__init__.py` が atomic-migration 用 facade
として `__all__` で再 export する (例: `_normalize_dt_fields`,
`_normalize_dt_and_fill_practitioner_display`,
`_apply_jp_core_profile`, `_apply_jp_clins_profile`,
`_apply_us_core_profile`, `_lab_observation_needs_specimen`,
`_build_companion_specimen`,
`_strip_forbidden_observation_reference_range_extensions`,
`_strip_japanese_display_on_english_only_systems`,
`_populate_observation_identifier_and_last_updated`,
`_populate_jp_medication_dosage_ecs_fields`,
`_populate_condition_ai_mr_ecs_fields`,
`_normalize_jp_observation_category`)。新 code は concern module
から直接 import する。

## 決定論

該当なし — emit 済み各 resource に対する pure transformation。
`_JP_ECS_LAST_UPDATED_PLACEHOLDER` は決定論的定数
(`"2026-01-01T00:00:00+09:00"`) のため run 跨ぎで cohort
byte-identity を保つ。

## 依存

- `clinosim.modules._shared` — `is_jp`。
- `clinosim.modules.output.fhir_r4.lib.common` —
  `derive_meta_last_updated` (populate)。`lib.ids` —
  `derive_opaque_id` / `structural_key_system` (specimen)。
- `clinosim.codes` — LOINC / SNOMED / JP-CLINS code 表示 lookup と
  上記 `codes/data/*.yaml` 表。
- `re`, `functools`, `pathlib` — 標準ライブラリ。

## 定数と設定

- **Datetime 正規化** (`datetime_normalize.py`):
  - `_DATETIME_FIELDS` — walker が訪問する全 FHIR dateTime / date
    field 名の frozenset。
  - `_PERIOD_FIELDS = frozenset(("start", "end"))`。
  - `_PERIOD_KEYS` — Period wrapping field key 全 frozenset。
  - `_INSTANT_FIELDS = frozenset(("issued", "lastUpdated"))`。
- **Companion specimen** (`specimen.py`):
  - `_COMPANION_SPECIMEN_ID_PREFIX = "spec-"` (alias
    `SPECIMEN_ID_PREFIX`、`SPECIMEN_KEY_SYSTEM =
    structural_key_system("specimen-key")`)。
  - `_SPECIMEN_SNOMED_BLOOD = "119297000"` (Blood specimen / 血液検体)
    と `_SPECIMEN_SNOMED_URINE = "122575003"` (Urine specimen /
    尿検体)。display は `codes/data/snomed-ct.yaml` から。
- **JP-CLINS + MHLW code system** (`populate.py`、Scope のリスト
  参照)。JP 側 downstream builder と `document` AD-60 audit が
  cross-verify のため import する。
- **`_JP_ECS_LAST_UPDATED_PLACEHOLDER = "2026-01-01T00:00:00+09:00"`**
  — resource に実 `meta.lastUpdated` source が無いときのみ使う
  決定論的 anchor。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/post_process/
  __init__.py                       再 export facade (dispatch 無し。呼出順は ../builder.py::_build_bundle)
  datetime_normalize.py             timezone + Period + instant 正規化 (+ Practitioner display fill を融合)
  specimen.py                       companion Specimen 合成 (spec- prefix、blood / urine SNOMED)
  profile.py                        JP Core / JP-CLINS / US Core profile URI stacking + resource-type 判別子
  populate.py                       JP eCS + MHLW + MEDIS + UCUM populate pass (~1,300 LOC)
  strip.py                          禁止 referenceRange extension + English-only system 上の日本語 display を削除
```

## テスト

```bash
pytest tests/unit -k "post_process or datetime_normalize or profile or specimen or strip or populate" -q
pytest tests/integration -k "jp_clins or document_chain" -q
```

Cross-verification: `document` AD-60 audit plug-in
([`../../../document/audit.py`](../../../document/audit.py)) の
49-check `lift_firing_proof` が JP-CLINS profile URI、JP eCS
extension、MEDIS uncoded fallback 存在などの post-process 不変量を
多数 exercise する。JP-CLINS package loader
([`../labs/coding_package.py`](../labs/coding_package.py)) が
`profile.py` の assert に使う profile URI を供給する。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
