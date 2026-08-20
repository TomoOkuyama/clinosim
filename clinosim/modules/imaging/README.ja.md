# `clinosim.modules.imaging` — imaging study + series + radiology report

## 概要

always-on AD-55 module (Tier 1 #2 imaging chain, AD-62)。disease
YAML の `imaging_orders[]` entry を読み、
`ImagingStudyRecord` + view 別 `ImagingSeries` + `RadiologyReport`
を `CIFPatientRecord.extensions["imaging"]` に materialize する。
下流の FHIR builder chain がこの CIF slot から `ImagingStudy` +
`Endpoint` + radiology `DiagnosticReport` + `ServiceRequest` を
emit する。

**imaging-chain DRY rule** (AD-62, AGENTS.md): multi-view →
multi-series 展開ロジックは必ず `engine._expand_views_to_series` に
置くこと。新規 imaging 発注は
[`clinosim.modules.order.engine.place_imaging_orders`](../order/engine.py)
経由 MUST — 呼び出し先で `imaging_modality` / `imaging_body_site_code`
/ `imaging_views` を直接 set してはいけない。

## Scope

- **In scope**: `imaging_enricher` (POST_ENCOUNTER order=90);
  3 YAML loader (`load_modalities`, `load_body_sites`,
  `load_impression_templates`) with per-loader import 時 validator
  (`_validate_modalities`, `_validate_body_sites`,
  `_validate_impression_templates`); multi-view → multi-series 展開
  (`_expand_views_to_series`); procedure コード解決
  (`_resolve_imaging_procedure_code_key`); DICOM UID 導出
  (`_study_uid_from`); body-site key 正規化
  (`_body_site_key_from_snomed`); report template 選択
  (`_select_report_template` + `_build_generic_negative_report`);
  `inference` submodule (case-D fallback、`Order.display_name` から
  modality / body-site を whitelist regex で推論 — 推測しない、
  一致無しは `None` を返し enricher は text-only stub を emit)。
- **In scope (audit)**: [`audit.py`](audit.py) — 4 番目の per-module
  AD-60 plug-in (hai, antibiotic, order の次)。15-check
  `lift_firing_proof` が canonical 定数 (`IMAGING_STUDY_ID_PREFIX`
  / `ENDPOINT_ID_PREFIX` / `RADIOLOGY_REPORT_ID_PREFIX` /
  `IMAGING_CATEGORY_SNOMED` / `IMAGING_CATEGORY_V2_0074` /
  `DICOM_UID_SYSTEM` / `DICOM_WADO_RS_CONNECTION_TYPE`)、3 emission
  count、3 reference-integrity check、Section 3.4 emission matrix
  由来の 5 no-drop 不変量を guard。`imaging_basedon_coverage`
  clinical axis は `ImagingStudy.basedOn` + `ImagingStudy.endpoint`
  の全 ref が resolve することを要求 (n<30 → WARN)。
- **Out of scope**: imaging 発注そのもの (これは
  [`clinosim.modules.order.engine.place_imaging_orders`](../order/engine.py));
  FHIR `ImagingStudy` / `Endpoint` / radiology `DiagnosticReport`
  / `ServiceRequest` emission ([`output/fhir_r4/`](../output/fhir_r4/README.md));
  PACS 側 DICOM store (clinosim scope 外)。

## Public API

```python
from clinosim.modules.imaging import (
    ImagingSeries,                   # dataclass 再 export (types.imaging)
    ImagingStudyRecord,              # dataclass 再 export
    RadiologyReport,                 # dataclass 再 export
)
from clinosim.modules.imaging.engine import (
    imaging_enricher,                # POST_ENCOUNTER enricher entry
    load_modalities,                 # () -> dict (@lru_cache)
    load_body_sites,                 # () -> dict (@lru_cache)
    load_impression_templates,       # () -> dict (@lru_cache)
)
from clinosim.modules.imaging.inference import (
    infer_imaging_metadata,          # (display_name) -> dict | None (whitelist regex)
)
```

## 決定論

- サブ seed オフセット `0x4947` (`"IG"`, Tier 1 #2 PR1) —
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["imaging"]` に登録済み。
- Per-encounter サブ RNG:
  `derive_sub_seed(master_seed, offset, encounter_id)` — 患者主
  RNG 未消費 (AD-16)。
- DICOM Study Instance UID はサブ seed から派生
  (`_study_uid_from(sub_seed, kind="study")`) — 同一 encounter は
  run 跨ぎで同 UID を生成する。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`,
  `get_or_create_container`, `is_jp`, `resolve_lang`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.codes.loader._load_system` — `_code_in_data` validator
  helper (`hai/engine.py` pattern 一致)。
- `clinosim.audit.registry` (`audit.py` 経由) — AD-60 audit 登録。
- `clinosim.types.imaging` — `ImagingSeries`, `ImagingStudyRecord`,
  `RadiologyReport` (`__init__.py` 経由で再 export)。
- `numpy`, `yaml`。

## 定数と設定

- **3 YAML** ([`reference_data/`](reference_data/)):
  - `modalities.yaml` — modality カタログ +
    `default_views_by_body_site` (order module が empty-views
    fallback で参照)。
  - `body_sites.yaml` — SNOMED body-site カタログ。
  - `impression_templates.yaml` — modality × body-site 別 negative
    / abnormal report template。
- 各 YAML は import 時 6-layer `_validate_*` (空 top、必須 key、
  双方向 coverage、per-entry 必須 field、SNOMED / LOINC / body-site
  canonical への cross-reference) を持つ。
- **Canonical id + system 定数** (FHIR builder が所有、audit のため
  import): `IMAGING_STUDY_ID_PREFIX`, `ENDPOINT_ID_PREFIX`,
  `RADIOLOGY_REPORT_ID_PREFIX`, `IMAGING_CATEGORY_SNOMED`,
  `IMAGING_CATEGORY_V2_0074`, `DICOM_UID_SYSTEM`,
  `DICOM_WADO_RS_CONNECTION_TYPE`。
- **Inference whitelist** (`inference.py`): pattern は substring
  match で発火。missed match は `None` を返し、enricher は order を
  silent drop せず text-only stub を emit する。

## ディレクトリ構造

```
clinosim/modules/imaging/
  __init__.py                      3 CIF 型 (ImagingStudyRecord / ImagingSeries / RadiologyReport) を再 export
  engine.py                        imaging_enricher + loader + validator + multi-view 展開
  inference.py                     infer_imaging_metadata whitelist (case-D fallback)
  audit.py                         AD-60 audit plug-in #4 — 15-check lift_firing_proof + basedon_coverage
  reference_data/
    modalities.yaml                modality + default_views_by_body_site
    body_sites.yaml                SNOMED body-site カタログ
    impression_templates.yaml      (modality × body_site) 別 report template
```

**`enricher.py` は存在しない** — enricher entry は `engine.py`、
そこから直接 import される。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`L286-299` 付近) で登録:

- `name="imaging"`, `stage=POST_ENCOUNTER`, `order=90`,
  `enabled=lambda c: True`。`antibiotic` (order=85) の後、
  `triage` (order=93) の前に走る — imaging は HAI cascade とは独立だが
  encounter narrative stage には先行する必要がある。
- `audit.py` module は import 時に AD-60 audit framework に登録される。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:294`](../../simulator/enrichers.py) | POST_ENCOUNTER order=90 登録。 |
| Audit registry | [`clinosim/modules/imaging/audit.py`](audit.py) | AD-60 audit plug-in。 |
| FHIR `ImagingStudy` / `Endpoint` / radiology `DiagnosticReport` / `ServiceRequest` builder | [`clinosim/modules/output/fhir_r4/`](../output/fhir_r4/) | `extensions["imaging"]` から 4 リソースファミリを emit。 |
| Order module | [`clinosim/modules/order/engine.py`](../order/engine.py) | `place_imaging_orders` が modality カタログの `default_views_by_body_site` を empty-views fallback として read。 |

## テスト

```bash
pytest tests/unit -k "imaging" -q
pytest tests/integration -k "imaging" -q
clinosim audit run -d <cohort_dir> --module imaging
```

個別ファイル:

- [`tests/unit/test_types_imaging.py`](../../../tests/unit/test_types_imaging.py)
  — dataclass shape。
- [`tests/unit/test_imaging_audit.py`](../../../tests/unit/test_imaging_audit.py)
  — 15-check audit plug-in unit run。
- [`tests/unit/test_imaging_inference.py`](../../../tests/unit/test_imaging_inference.py)
  — whitelist regex coverage。
- [`tests/unit/output/test_fhir_imaging_study.py`](../../../tests/unit/output/test_fhir_imaging_study.py)
  — FHIR ImagingStudy emission unit。
- [`tests/integration/test_imaging_chain.py`](../../../tests/integration/test_imaging_chain.py),
  [`test_imaging_basedon_coverage.py`](../../../tests/integration/test_imaging_basedon_coverage.py),
  [`test_imaging_snapshot.py`](../../../tests/integration/test_imaging_snapshot.py),
  [`test_imaging_jp_localization.py`](../../../tests/integration/test_imaging_jp_localization.py),
  [`test_imaging_subprocess_fullpipeline.py`](../../../tests/integration/test_imaging_subprocess_fullpipeline.py),
  [`test_imaging_determinism.py`](../../../tests/integration/test_imaging_determinism.py)
  — cross-module + full-pipeline chain、basedOn coverage、snapshot、
  JP localization、determinism。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
