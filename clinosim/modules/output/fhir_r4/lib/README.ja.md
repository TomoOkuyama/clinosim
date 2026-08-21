# `fhir_r4/lib/` — 共有 FHIR R4 builder ライブラリ

## 概要

[`fhir_r4/`](../README.md) 配下の全 clinical-domain builder
subpackage が import する共有 low-level fragment helper。FHIR
subsystem の leaf 層 — 各 helper は top-level resource ではなく
FHIR *fragment* (Coding, CodeableConcept, Bundle entry, UCUM
quantity, JP eCS extension) を生成するため、resource-builder
module は adapter facade を循環せず `lib.*` から import できる。

`_fhir_common` compat shim (in
[`../../_fhir_common.py`](../../_fhir_common.py)) は
`DeprecationWarning` 付きで動作。新 code は
`clinosim.modules.output.fhir_r4.lib.common` を直接 import する
(Issue #545 rename)。

## Scope

- **In scope**:
  - `common.py` — `BundleContext` dataclass (各 `_bb_*` builder が
    受け取る read-only context)、fragment helper
    (`_coding_with_display`, `build_ucum_quantity`,
    `_escape_html`, `survey_category`, `_social_category`,
    `loinc_coding`, `to_fhir_date`, `entry`)、eCS 機関 / 部門
    extension と `attach_ecs_institutional_extensions`、
    `_FHIR_ID_PATTERN = re.compile(r"^[A-Za-z0-9\-\.]{1,64}$")`、
    `_JST_TZ_SUFFIX = "+09:00"` / `_UTC_TZ_SUFFIX = "Z"`、
    eCS placeholder (`_JP_ECS_INSTITUTION_PLACEHOLDER =
    "1300000000"`, `_JP_ECS_DEPARTMENT_PLACEHOLDER = "総合診療科"`)
    と extension URL (`_JP_ECS_INSTITUTION_NUMBER_EXT_URL`,
    `_JP_ECS_DEPARTMENT_EXT_URL`,
    `_JP_ECS_INSTITUTION_ID_SYSTEM`)。
  - `localization.py` — EN / JA テキスト localisation dispatch
    (lab 値表示正規化用の `_RATE_ADJUSTMENT_SUFFIX_RE` regex も所有)。
  - `reference_data.py` — profile URI、canonical URL、code-system
    URL。`_JP_CONDITION_SEVERITY_CS` と
    `CLINOSIM_IDENTIFIER_SYSTEM_PREFIX = "urn:clinosim:identifier:"`
    を含む。
  - `inline_bb.py` — まだ 7 clinical-domain subpackage に split され
    ていない legacy inline building-block builder。11 `_bb_*` 関数
    (`_bb_patient`, `_bb_coverage`, `_bb_encounters`,
    `_bb_conditions`, `_bb_occupation`, `_bb_vitals`,
    `_bb_medication_requests`, `_bb_discharge_medication_requests`,
    `_bb_medication_admins`, `_bb_procedures`, `_bb_practitioners`)
    を export し、親 facade が split 済 builder と並列に登録する。
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
  - `ids.py` — 構造 key system の ID-prefix 定数
    (`structural_key_system(name)` が canonical URI を返す)。
- **Out of scope**: FHIR-resource 固有の builder — 兄弟
  clinical-domain subpackage 側。

## Public API

```python
from clinosim.modules.output.fhir_r4.lib.common import (
    BundleContext,                        # dataclass
    entry,                                # (resource) -> Bundle entry dict
    build_ucum_quantity,                  # (value, unit) -> {value, unit, system, code}
    survey_category,                      # () -> survey CodeableConcept
    loinc_coding,                         # (code, lang) -> {system, code, display}
    build_ecs_institution_extension,      # JP eCS 機関
    build_ecs_department_extension,
    attach_ecs_institutional_extensions,
)
from clinosim.modules.output.fhir_r4.lib.localization import (
    localize_text,                        # (text_map, lang) -> str
)
from clinosim.modules.output.fhir_r4.lib.reference_data import (
    CLINOSIM_IDENTIFIER_SYSTEM_PREFIX,    # "urn:clinosim:identifier:"
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
from clinosim.modules.output.fhir_r4.lib.ids import structural_key_system
```

## 決定論

該当なし — 渡された入力に対する pure helper。`generator_metadata`
は export 時に現 git HEAD を read して sidecar provenance を記録
するが、sidecar は意図的に byte-diff scope 外
(`write_generator_metadata` docstring 参照)。

## 依存

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`。
- `clinosim.codes` — `get_system_uri`, `lookup`。
- `clinosim.locale.loader` — locale 表示 map。
- `re`, `datetime`, `dataclasses` — 標準ライブラリ。
- adapter facade への循環無し。

## 定数と設定

- **`_FHIR_ID_PATTERN`** (`common.py`) — FHIR R4 仕様の id pattern
  (`[A-Za-z0-9\-\.]{1,64}`)。全 emission site は本 regex を使う
  `_fhir_id_is_spec_valid` (親 facade) で gate される。
- **`_JST_TZ_SUFFIX = "+09:00"`** / **`_UTC_TZ_SUFFIX = "Z"`** —
  `to_fhir_date` と下流 post-processing 用の timezone suffix 定数。
- **`CLINOSIM_IDENTIFIER_SYSTEM_PREFIX = "urn:clinosim:identifier:"`**
  — clinosim 内部 identifier system の名前空間 prefix
  (`HAI_EVENT_ID_SYSTEM`、staff identifier system 等)。
- **eCS placeholder** — cohort に実機関番号 / 部門コードが無いとき
  に使う (JP eCS profile が field を要求するため、実 facility を
  主張せず cardinality を満たす)。
- **`_RECENT_MERGES_LIMIT = 30`** (`generator_metadata.py`) —
  sidecar に記録する recent-merge PR 番号の上限。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/lib/
  __init__.py                        namespace のみ (再 export 無し)
  common.py                          BundleContext + fragment helper + eCS extension + _FHIR_ID_PATTERN
  localization.py                    en / ja テキスト localisation dispatch
  reference_data.py                  profile URI + code-system URI + clinosim identifier prefix
  inline_bb.py                       11 legacy _bb_* builder (拡張しない — 新規は domain subpackage へ)
  generator_metadata.py              _generator_metadata.json sidecar emission
  ed_reattribution.py                reattribute_encounter_to_ed_bridge (N-3 PR #810)
  ids.py                             structural_key_system + ID-prefix helper
```

## テスト

```bash
pytest tests/unit -k "fhir_common or lib or generator_metadata or ed_reattribution or structural_key" -q
```

AD-60 audit plug-in (hai, antibiotic, order, imaging, document) が
本層から多くの定数を `canonical_constants` cross-check のため import
する。ここでの rename は該当 audit run を fail させる。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
