# `clinosim.modules.health_checkup` — JP 事業者健診 opt-in モジュール

## 概要

日本の労働安全衛生法に基づく **事業者健診** (annual employer-provided
health checkup) を JP コホートに追加する opt-in POST_RECORDS enricher。
40 歳以上成人から SHA-256 hash by `patient_id` で決定論的に 30 %
サブセットを選定し、選定患者ごとに 1 件 (simulation snapshot の
90 日前) の `CHECKUP` encounter、法定健診項目 5 種 (BMI、収縮期 BP、拡張期 BP、
HbA1c、LDL コレステロール)、および `HEALTH_CHECKUP_REPORT` の
`ClinicalDocument` stub (narrative は
[`document.narrative`](../document/narrative/README.ja.md) が Stage 2
で populate) を emit する。

**default OFF** — `SimulatorConfig.modules["health_checkup"] == True`
かつ `country == "JP"` のときのみ発火。OFF 時は simulator default の
急性期病院前提が保たれる。

## Scope

- **In scope**: 患者サブセット選定 (年齢 gate + 決定論 hash)、
  snapshot 基点の健診日決定 (snapshot のちょうど 90 日前、snapshot
  未設定時は 2026-12-31 基準。simulation 期間に関わらず患者あたり
  1 回)、年齢層別 checkup type dispatch (40-64 → 事業者健診、
  65-74 → 特定健診、75+ → 広域連合健診 — MVP 単一 tier dispatch、
  保険種別による精緻化は将来 sub-PR)、CHECKUP encounter 構築
  (`CHK-{patient_id}-001`、同日 09:00-11:00、department
  `health_checkup`)、`panel_key="Checkup"` を共有する LAB `Order` 5 件
  (→ ServiceRequest 1 + DiagnosticReport 1 + Observation 5)、これらを
  患者ごとに新規の独立 `CIFPatientRecord` として追加 (narrative pass が
  CHECKUP encounter を `encounters[0]` として認識するため)、per-analyte 測定ノイズ付きの
  法定 5 項目、per-analyte 解釈 (normal / high) + reference-range
  文字列、`HEALTH_CHECKUP_REPORT` の `ClinicalDocument` stub
  (narrative=None、Stage 2 fill 用)。
- **Out of scope**: narrative content —
  [`clinosim.modules.document.narrative`](../document/narrative/README.ja.md)
  が post-simulation で populate (AD-65 Stage 2)、FHIR Composition +
  section text の emit
  ([`clinosim.modules.output.fhir_r4.documents`](../output/fhir_r4/documents/README.ja.md))、
  保険種別ベースの精緻化 (将来 sub-PR)、非 JP コホート。

## Public API

```python
from clinosim.modules.health_checkup import (
    enrich_health_checkup,          # POST_RECORDS enricher entry
    HEALTH_CHECKUP_SUBSET_RATE,     # 0.30 (調整可能なサブセット率)
)
```

内部 helper (`engine.py`) — public surface ではないが test 参照に有用:
`_patient_selected(patient_id)`, `_pick_checkup_type(age)`,
`_pick_checkup_date(snapshot_date)`,
`_derive_checkup_values(patient, rng)`, `_interp_for(loinc, value)`,
`_build_checkup_encounter`, `_build_checkup_lab_results`,
`_build_checkup_document_stub`。`HEALTH_CHECKUP_MIN_AGE = 40` と年齢
tier 閾値 (`CHECKUP_TYPE_SPECIFIC_AGE_MIN = 65`,
`CHECKUP_TYPE_REGIONAL_UNION_AGE_MIN = 75`) は
[`_checkup_thresholds.py`](_checkup_thresholds.py) に定義。

## 決定論

- **患者選定は SHA-256、RNG を使わない**。`_patient_selected` は
  `patient_id` を hash し先頭 8 bytes を fraction に変換、
  `HEALTH_CHECKUP_SUBSET_RATE` 未満の患者を採用する。無関係な
  モジュールが変わっても同一患者は常に採用 / スキップされる。
- サブ seed オフセット `0x4843` (`"HC"`) は
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["health_checkup"]` に登録済み。5 項目の
  per-patient 測定ノイズに使い、population 主 RNG 列は消費しない
  (AD-16)。
- 健診日は snapshot 日からの決定論オフセット (90 日前) であり、
  random draw ではない。

## 依存

- `clinosim.modules._shared` — `is_jp`, `get_attr_or_key`。
- `clinosim.modules.health_checkup._checkup_thresholds` — value 導出
  pipeline が使う全 physiologic bound / 測定ノイズ SD / 解釈 cutoff
  / reference range / 年齢 tier (Issue #637 sweep、`engine.py` の
  scalar を全 lift)。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.types.clinical` — `ClinicalDocument`。
- `clinosim.types.encounter` — `Encounter`, `EncounterStatus`,
  `EncounterType`, `Order`, `OrderResult`, `OrderStatus`, `OrderType`。
- `clinosim.types.output` — `CIFPatientRecord` (新規健診 record)。
- `hashlib.sha256` — 患者選定。
- `numpy` — 測定ノイズ用 `np.random.Generator`。
- 他の `clinosim.modules.*` には依存しない。

## 定数と設定

- module レベル定数 (`engine.py`):
  - `HEALTH_CHECKUP_SUBSET_RATE = 0.30` — 決定論サブセット率。
    MVP 校正、将来 sub-PR で `employment_status = employed` の患者
    に絞る余地あり。
  - `HEALTH_CHECKUP_MIN_AGE = 40` — 受診資格の最低年齢。
- 年齢 tier dispatch (`_pick_checkup_type`):
  - 40-64 歳 → `"occupational"` (事業者健診、労安衛法定)。
  - 65-74 歳 → `"specific"` (特定健診、40-74 保険 base)。
  - 75 歳以上 → `"regional_union"` (広域連合健診、後期高齢者医療)。
- Threshold 表: [`_checkup_thresholds.py`](_checkup_thresholds.py)
  — analyte 別の physiologic min / max、測定ノイズ SD、reference-range
  文字列、high cutoff、DM / non-DM の HbA1c 分岐、性別 × 年齢 の
  LDL base + scaling、statin reduction 係数、dyslipidemia lift、および
  上記 2 つの年齢 tier 閾値を保持。
- checkup type 別 chief-complaint テキスト
  (`_CHECKUP_TYPE_CHIEF_COMPLAINT`): `occupational → "事業者健診"`,
  `specific → "特定健診"`, `regional_union → "広域連合健診"`。

## ディレクトリ構造

```
clinosim/modules/health_checkup/
  __init__.py                     enrich_health_checkup + HEALTH_CHECKUP_SUBSET_RATE を再 export
  engine.py                       enricher + 患者選定 + 値導出 + record builder
  _checkup_thresholds.py          named threshold 定数 (Issue #637)
```

**`reference_data/` / `audit.py` / `enricher.py` は存在しない** —
enricher entry は `engine.py` の `enrich_health_checkup`、reference
値は定数 (YAML ではない)。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`L510-540` 付近) の `register_builtin_enrichers` で登録:

- `name="health_checkup"`, `stage=POST_RECORDS`, `order=70`。
- `enabled=_health_checkup_enabled` —
  `is_jp(config.country)` AND
  `config.module_enabled("health_checkup")` を要求。
  `None`-safe fallback (care_level pattern) により registry-helper
  test の `ctx.config=None` にも耐える。
- POST_RECORDS の全 enricher (nursing 20 / immunization 30 /
  family_history 40 / code_status 50 / care_level 60 /
  medication_monitoring 65) の後に実行し、
  CHECKUP encounter が先行 enricher の RNG stream を乱さないようにする。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Enricher registry | [`clinosim/simulator/enrichers.py:534`](../../simulator/enrichers.py) | POST_RECORDS order=70 登録。 |
| FHIR Composition builder | [`clinosim/modules/output/fhir_r4/documents/jp_clins/echeckup_general.py`](../output/fhir_r4/documents/jp_clins/echeckup_general.py) (`documents/composition.py` 経由) | populate 済み `HEALTH_CHECKUP_REPORT` を JP-eCheckup General `Composition` として emit。 |
| FHIR DocumentReference builder | [`clinosim/modules/output/fhir_r4/documents/document_reference_checkup.py`](../output/fhir_r4/documents/document_reference_checkup.py) | Composition を参照する付随 `DocumentReference` (`drf-<document_id>`) を emit。`narrative` が `None` の間は skip。 |
| Narrative Stage 2 | [`clinosim/modules/document/narrative/`](../document/narrative/README.ja.md) (`registry.py`、`template_generator.py`) | stub の `narrative.sections` を per-value 解釈 + Q4 summary で埋める。 |

## テスト

```bash
pytest tests/unit -k "health_checkup or checkup" -q
```

個別ファイル:

- [`tests/unit/test_health_checkup_enricher.py`](../../../tests/unit/test_health_checkup_enricher.py)
  — enricher gating (opt-in、JP-only、age ≥ 40)、サブセット選定
  決定論、5 measurement emit、snapshot 基点日。
- [`tests/unit/test_health_checkup_personalization.py`](../../../tests/unit/test_health_checkup_personalization.py)
  — per-patient value 導出 (DM / non-DM 分岐、性別 × 年齢 LDL
  scaling、dyslipidemia lift、statin reduction)。
- [`tests/unit/test_checkup_renderer_personalization.py`](../../../tests/unit/test_checkup_renderer_personalization.py)
  — narrative 側 rendering 統合点。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
