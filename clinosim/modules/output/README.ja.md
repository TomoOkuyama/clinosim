# `clinosim.modules.output` — 出力アダプタ entry + CIF writer

## 概要

生成された CIF を消費し全 downstream フォーマットに emit する出力層。
pluggable adapter registry (AD-58)、CIF writer + reader、bundled
`csv` + `fhir-r4` adapter、narrative pipeline が discharge summary
の fact 構築に使う `hospital_course_extractor` helper を所有する。
FHIR R4 emission 本体は [`fhir_r4/`](fhir_r4/README.md) subpackage に。

## Scope

- **In scope**: `OutputAdapter` Protocol + `OutputContext` +
  `register_output_adapter` + `get_adapter` + `available_formats`、
  2 built-in adapter (`CsvAdapter`, `FhirR4Adapter`、`_ensure_builtins`
  で遅延自己登録);`write_cif` (構造化 CIF 用 JSON writer);
  `CIFReader` (構造化 CIF + 指定 narrative version を merge、
  `resolve_current_narrative_dir` が `narratives/current_version.txt`
  pointer file を解決);`HospitalCourseFact` +
  `extract_hospital_course` + discharge-summary narrative が使う
  `summarize_*` helper;FHIR-R4 subpackage の entry 再 export
  (`register_bundle_builder`, `available_builders`)。
- **Out of scope**: FHIR R4 emit logic 本体
  ([`fhir_r4/`](fhir_r4/README.md) subpackage — resource builder、
  bundle assembly、post-processing);CIF フォーマット本体
  ([`clinosim.types`](../../types/));narrative content 生成
  ([`document.narrative`](../document/narrative/README.md))。

### 縦断サービスラインの emission surface (v0.5 → v0.6.0)

2 種のサービスラインが追加 resource shape を発生させるが、既存 adapter
経由で FHIR に到達する (新規 resource-type builder は不要)。FHIR R4
subpackage は `_BUNDLE_BUILDERS` registry 経由で CIF から拾う:

- **産科 — 母親側分娩 Encounter** (admit dx `O80`、discharge dx
  `Z37.0`、分娩 Procedure JP `K894` / US CPT `59400`) と **新生児
  Encounter** (`admit_source = "born"` — 新
  `AdmitSource.BORN` enum 値、詳細
  [`clinosim/types/encounter.py`](../../types/encounter.py)、
  `admit_source_encounter_id` が母親の分娩 encounter を指し新生児側の
  FHIR `Encounter.partOf` に emit)。新生児側 discharge dx `Z38.0`、
  産褥 (postpartum) 外来 encounter は `chronic_followup.yaml` 経由で
  `Z39`。新生児周産期 conditions P59.9 / P07.3 / P22.0 / L22 / L20.9
  は通常 Condition resource として FHIR 到達。中絶 outcome (O03.9 /
  O04.5) は外来日帰り手術 Encounter として emit。
- **オンコロジー — 化学療法 visit Encounter** に per-cycle
  `MedicationRequest` + `MedicationAdministration` (同一 `order_id`、
  詳細 [`order`](../order/README.md))、放射線治療 `Procedure`、
  腫瘍マーカー `Observation` labs (CEA / CA19-9 / AFP / PIVKA-II /
  CA15-3 / PSA)。

いずれも built-in FHIR R4 adapter 経由で emit され、`country=JP`
コホートについては
[`fhir_r4/labs/README.ja.md`](fhir_r4/labs/README.ja.md) 記載の
JP-CLINS eCS profile URL attachment の対象となる。

## Public API

```python
# Adapter registry (AD-58)
from clinosim.modules.output import (
    register_output_adapter,     # (adapter) — plug-in 登録
    register_bundle_builder,     # (fn) — FHIR R4 bundle builder 登録
    available_builders,          # () -> 登録済み builder list
)
from clinosim.modules.output.adapter import (
    OutputContext,               # dataclass (country, narrative_version, options)
    OutputAdapter,               # runtime_checkable Protocol (format_id, description, subdir, convert)
    get_adapter,                 # (format_id) -> OutputAdapter (未知 format は available list 付き KeyError)
    available_formats,           # () -> [(format_id, description), ...]
)

# Built-in adapter (必要時 _ensure_builtins で登録)
from clinosim.modules.output.adapters_builtin import CsvAdapter, FhirR4Adapter

# CIF writer + reader
from clinosim.modules.output.cif_writer import write_cif                # (dataset, output_dir) -> None
from clinosim.modules.output.cif_reader import CIFReader, resolve_current_narrative_dir

# Narrative 向け extractor
from clinosim.modules.output.hospital_course_extractor import (
    HospitalCourseFact,
    extract_hospital_course,
    summarize_discharge_medications,
    summarize_procedures,
    summarize_admission_vitals,
    summarize_terminal_vitals,
)
```

登録済み format id: `"csv"`, `"fhir-r4"` (built-in)。third-party
adapter は本 facade を編集せず新 `format_id` を import 時に登録できる。

## 決定論

該当なし — 出力層は既に生成された CIF に対する純粋 serialiser。
`rng` 引数無し、`ENRICHER_SEED_OFFSETS` にも未登録。
`OutputContext.options` dict は format 固有設定用の forward-compat
だが現状未使用。

## 依存

- `clinosim.modules.output.fhir_r4` (subpackage) — FHIR R4 emit
  面、本 package `__init__` で再 export。
- `clinosim.types.output` — `CIFDataset`、manifest 型。
- `clinosim.types.clinical` — `ClinicalDocument` +
  `ClinicalDocumentNarrative` (`CIFReader` が read)。
- `yaml` — YAML パススルー (CIF は JSON だが CLI は YAML config
  を受容)。
- `adapter.py` / `adapters_builtin.py` / `cif_writer.py` は
  標準ライブラリのみ。

## 定数と設定

- **Adapter registry** (`adapter.py` の `_ADAPTERS`) — `format_id`
  キーの dict。`_ensure_builtins` が初回 `get_adapter` /
  `available_formats` 呼び出し時に
  `clinosim.modules.output.adapters_builtin` を import し 2
  built-in adapter を自己登録させる。
- **Adapter shape**: `format_id` (registry key + CLI 値)、
  `description` (CLI help + `available_formats()` に表示)、
  `subdir` (出力サブディレクトリ名)、
  `convert(cif_dir, out_dir, ctx: OutputContext) -> None` method。
- **`OutputContext`**: `country` (`"US"` / `"JP"`、default `"US"`)、
  `narrative_version` (`"current"` は
  `cif/narratives/current_version.txt` を解決、fallback `"template"`。
  CLI では `export-fhir --narrative-version` から流れる)、`options`
  (format 別自由 dict)。
- **FHIR builder registry**
  (`register_bundle_builder` / `available_builders`) — 新 FHIR
  resource 追加のための AD-56 plug-in 面。builder は
  `(ctx: BundleContext) -> list[resource]` の callable。registry
  実体は [`fhir_r4/`](fhir_r4/README.md) 内。
- **Backwards-compat shim**: `fhir_r4_adapter.py` は FHIR subpackage
  の公開面を pre-migration の ~100 caller のため再 export する
  (Issue #555 PR1)。`DeprecationWarning` は出さない — shim は
  cleanup rename であり deprecation ではない。

## ディレクトリ構造

```
clinosim/modules/output/
  __init__.py                        register_output_adapter + register_bundle_builder + available_builders
  adapter.py                         OutputAdapter Protocol + OutputContext + registry
  adapters_builtin.py                CsvAdapter + FhirR4Adapter (遅延登録)
  cif_writer.py                      write_cif (構造化 CIF 用 JSON writer)
  cif_reader.py                      CIFReader (構造化 + narrative merge) + resolve_current_narrative_dir
  csv_adapter.py                     per-domain CSV emission (`convert_cif_to_csv`)
  hospital_course_extractor.py       HospitalCourseFact + extract_hospital_course + summarize_* (narrative helper)
  fhir_r4_adapter.py                 backwards-compat shim (fhir_r4/ を再 export)
  fhir_r4/                           FHIR R4 emission subpackage (fhir_r4/README.md 参照)
  SPEC.md                            拡張設計参考 (runtime data ではない)
```

本レベルには **`audit.py` / `enricher.py` / `reference_data/` 無し** —
family 別 FHIR data は `fhir_r4/` subpackage に。

## Enricher 配線

該当なし — adapter は CLI export 時 (`clinosim export`,
`clinosim export-fhir`) に呼び出され、`register_builtin_enrichers`
経由でない。`ENRICHER_SEED_OFFSETS` にも seed 未登録。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| CLI `export` / `export-fhir` | [`clinosim/simulator/cli.py`](../../simulator/cli.py) | `get_adapter(format_id).convert(cif_dir, out_dir, ctx)` を呼び出す。 |
| Narrative pipeline | [`clinosim/modules/document/narrative/passes.py`](../document/narrative/passes.py) | `CIFReader` で構造化 + narrative-version-merged CIF を load。 |
| Narrative discharge-summary | [`clinosim/modules/document/narrative/template_generator.py`](../document/narrative/template_generator.py) | `extract_hospital_course` + `summarize_*` helper で discharge-summary fact を構成。 |
| Third-party plug-in | (user code) | `register_output_adapter(adapter)` で custom adapter、`register_bundle_builder(fn)` で custom FHIR bundle builder を登録。 |

## テスト

```bash
pytest tests/unit -k "output or cif_reader or hospital_course" -q
pytest tests/integration -k "output or export" -q
```

Coverage は広範 — `tests/unit -k output` で adapter 別 test、
CIF-reader test、hospital-course extractor test を検索。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
