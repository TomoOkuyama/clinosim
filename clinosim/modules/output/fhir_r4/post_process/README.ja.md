# `fhir_r4/post_process/` — bundle-level FHIR R4 post-processing pipeline

## 概要

per-patient FHIR Bundle emit 済み後に走る最終 transformation
pipeline (PR3、Issue #556 fold): timezone 跨ぎ (JST vs UTC) の
datetime / instant 正規化、JP-CLINS profile URI assertion +
must-support slot population、lab / microbiology Observation 用の
companion Specimen 合成、仕様上 emit 禁止の空 extension / narrative
/ cardinality `0` 削除 strip pass。全 per-resource builder 発火後に
走るため、bundle 全体を一括で見て単一 builder では出来ない
cross-resource fixup を適用できる。

## Scope

- **In scope**:
  - `datetime_normalize.py` — 組立済み bundle を walk し、全
    `_DATETIME_FIELDS` (dateTime / date + Period.start / end +
    instant `issued` / `lastUpdated`) を JP 出力は `+09:00` JST、
    US 出力は `Z` に正規化。
  - `profile.py` — 全 Observation / Composition /
    MedicationRequest / etc. に JP-CLINS profile URI を assert、
    JLAC10 mapping 無しのとき JP eCS `JP_CLINS_ObsLabResult_*`
    must-support slot (uncoded / localcode fallback) を populate、
    JP `_FHIR_ID_PATTERN` (local 再定義: `[A-Za-z0-9\-\.]{1,64}`)
    を強制。
  - `specimen.py` — lab / microbiology Observation ごとに companion
    `Specimen` resource を合成 (`_COMPANION_SPECIMEN_ID_PREFIX =
    "spec-"`、EN + JA display 付き `_SPECIMEN_TYPE_BLOOD` /
    `_SPECIMEN_TYPE_URINE` SNOMED tuple)。
  - `strip.py` — 空 extension / narrative / cardinality `0` field
    を削除。
  - `populate.py` — 大きな per-JP-profile populate pass (~825 LOC)。
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
    `_resolve_mhlw_usage_code(drug_text, freq, period, period_unit)`
    (Issue #817 / PR #836/#837/#838) が (drug, cadence) tuple を
    実 `MedicationUsage_ePrescription` code に mapping できない
    場合の fallback のみ。resolver は薬剤クラス + freq heuristic
    (statin→QD-就寝前、PPI→QD-朝食前、bisphosphonate→QD-起床時、
    ワルファリン→QD-夕食後、biguanide→BID-朝夕食後、抗生剤→TID-
    朝昼夕食後 等) と PRN 条件コード (アセトアミノフェン→発熱時、
    サルブタモール→喘息発作時) を適用し、JP p=10000 s500 sample で
    実 code coverage ~97.6% を達成。残 ~2.4% dummy は hourly cadence
    (Q6H / Q8H — MHLW CS に pure-hourly code 無し) + IV 静注薬
    (生理食塩液等)、period-of-use
    extension URL (`_JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL`)、
    UCUM day code (`_UCUM_SYSTEM_URI`, `_UCUM_DAY_CODE = "d"`,
    `_UCUM_DAY_UNIT_JA = "日"`)、JP resource-instance identifier
    system (`_JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM =
    "http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier"`
    と clinosim 内部 `_CLINOSIM_OBSERVATION_ID_SYSTEM =
    "urn:clinosim:observation-id"`)、JP observation category
    (`_JP_OBSERVATION_CATEGORY_SYSTEM =
    "http://jpfhir.jp/fhir/core/CodeSystem/JP_SimpleObservationCategory_CS"`)
    を fill。resource に自然な `meta.lastUpdated` anchor が無い
    ときに使う `_JP_ECS_LAST_UPDATED_PLACEHOLDER =
    "2026-01-01T00:00:00+09:00"` も所有する。
- **Out of scope**: per-resource builder logic (兄弟 clinical-domain
  subpackage);NDJSON serialization 本体
  ([`../__init__.py`](../__init__.py));FHIR profile 定義本体
  ([`../labs/coding_package.py`](../labs/coding_package.py) が
  load する JP-CLINS + jpfhir-terminology package 内)。

## Public API

各 pass は [`../__init__.py`](../__init__.py) の
`convert_cif_to_fhir` から呼ばれる。外部 caller は直接 import しない。
外部呼び出し可能 entry は各 file の `__all__` (例:
`normalise_datetimes`, `synthesise_specimens`,
`apply_jp_clins_profile`, `strip_empties`,
`populate_jp_extensions`)。

## 決定論

該当なし — 既組立 bundle に対する pure transformation。
`_JP_ECS_LAST_UPDATED_PLACEHOLDER` は決定論的定数
(`"2026-01-01T00:00:00+09:00"`) のため run 跨ぎで cohort
byte-identity を保つ。

## 依存

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`。
- `clinosim.modules.output.fhir_r4.lib.common` — `BundleContext`
  + `_FHIR_ID_PATTERN` (`populate.py` は JP 側 ID check 用に local
  再定義)。
- `clinosim.codes` — LOINC / SNOMED / JP-CLINS code 表示 lookup。
- `re`, `datetime` — datetime + regex pass 用標準ライブラリ。

## 定数と設定

- **Datetime 正規化** (`datetime_normalize.py`):
  - `_DATETIME_FIELDS` — walker が訪問する全 FHIR dateTime / date
    field 名の frozenset。
  - `_PERIOD_FIELDS = frozenset(("start", "end"))`。
  - `_PERIOD_KEYS` — Period wrapping field key 全 frozenset。
  - `_INSTANT_FIELDS = frozenset(("issued", "lastUpdated"))`。
- **Companion specimen** (`specimen.py`):
  - `_COMPANION_SPECIMEN_ID_PREFIX = "spec-"`。
  - `_SPECIMEN_TYPE_BLOOD = {"code": "119297000", "display_en":
    "Blood specimen", "display_ja": "血液検体"}`。
  - `_SPECIMEN_TYPE_URINE = {"code": "122575003", "display_en":
    "Urine specimen", "display_ja": "尿検体"}`。
- **JP-CLINS + MHLW code system** (`populate.py`、Scope の網羅リスト
  参照)。JP 側 downstream builder と `document` AD-60 audit が
  cross-verify のため import する。
- **`_JP_ECS_LAST_UPDATED_PLACEHOLDER = "2026-01-01T00:00:00+09:00"`**
  — resource に実 `meta.lastUpdated` source が無いときのみ使う
  決定論的 anchor。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/post_process/
  __init__.py                       pipeline entry (datetime → specimen → profile → populate → strip の順に dispatch)
  datetime_normalize.py             timezone + Period + instant 正規化
  specimen.py                       companion Specimen 合成 (spec- prefix、blood / urine SNOMED)
  profile.py                        JP-CLINS profile URI assertion + JLAC10 must-support slot population
  populate.py                       JP eCS + MHLW + MEDIS + UCUM populate pass (~825 LOC)
  strip.py                          空 extension / narrative / cardinality-0 field 削除
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
[`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
