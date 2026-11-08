# `clinosim.modules.nursing` — 主担当看護師割当 + アセスメント scaffolding

## 概要

入院 / ICU / rehab-inpatient encounter に対して主担当看護師を割り当てる
POST_ENCOUNTER enricher (登録名 **`nursing_assignment`**) と、
将来の narrative / アセスメント作業が消費する参照 scaffolding
(ADL カテゴリ、リスクアセスメント種別、疾患別 nursing focus) を公開する
モジュール。

**命名の曖昧回避 (AGENTS.md, AD-64)**。シミュレータには「nursing」で
始まる enricher が 2 つあり明確に区別する:

- **`nursing_assignment`** — **本パッケージ**
  (`clinosim.modules.nursing.engine.nursing_enricher`)、POST_ENCOUNTER
  order=94、`EncounterRecord.primary_nurse_id` を書き込む。
- **`nursing_flowsheets`** — observation パッケージ
  ([`clinosim.modules.observation.nursing_enricher`](../observation/README.ja.md))、
  POST_RECORDS order=20、NEWS2 / GCS / Braden / Morse スコアを出力。

コードコメント中は常にこの曖昧回避名を使う。本モジュールは前者のみ担当。

## Scope

- **In scope**:
  - `nursing_enricher` — POST_ENCOUNTER で inpatient / ICU /
    rehab-inpatient encounter に `primary_nurse_id` を割当。
    ctx `StaffRoster` から選出 (ctx に roster が無い / roster に
    nurse が居ないときは `""`)。
  - `assign_primary_nurse` —
    `clinosim.modules.staff.engine.scoped_nurses(roster, ward=...,
    department=...)` (encounter の病棟の看護師、無ければ診療科、
    無ければ全看護師、Issue #2700) から uniform sampling。RNG の seed は
    caller 責任。
  - `load_nursing_assessment` — `nursing_assessment.yaml` reference
    データの loader (`NursingAssessment` Pydantic model で検証)。
  - 公開定数: `SUPPORTED_ADL_CATEGORIES` (5 ADL カテゴリ)、
    `SUPPORTED_RISK_ASSESSMENTS` (3 risk 種別)、
    `INPATIENT_ENCOUNTER_TYPES` (enricher が受理する 3 encounter 種別)。
- **Out of scope**:
  - 看護 flowsheet observation (NEWS2 / GCS / Braden / Morse) —
    [`clinosim.modules.observation`](../observation/README.ja.md)。
  - 看護師 identity 生成
    ([`clinosim.modules.staff`](../staff/README.ja.md) が roster 担当)。
  - 看護 narrative 文書
    ([`clinosim.modules.document.narrative`](../document/narrative/README.ja.md))。
  - FHIR CareTeam / performer emission
    ([`clinosim.modules.output.fhir_r4`](../output/README.ja.md))。

## Public API

```python
from clinosim.modules.nursing import (
    INPATIENT_ENCOUNTER_TYPES,   # frozenset {"inpatient", "icu", "rehab_inpatient"}
    SUPPORTED_ADL_CATEGORIES,    # frozenset {eating, bathing, dressing, toileting, mobility}
    SUPPORTED_RISK_ASSESSMENTS,  # frozenset {fall_risk, pressure_ulcer_risk, aspiration_risk}
    assign_primary_nurse,        # (encounter, roster|None, rng) -> staff_id (str、空可)
    load_nursing_assessment,     # () -> dict (キャッシュ、NursingAssessment 検証済)
)
```

POST_ENCOUNTER エントリ `nursing_enricher(ctx) -> None` は `engine.py`
に定義されるが再 export されていない。シミュレータは
[`clinosim.modules.nursing.engine`](engine.py) から直接 import する。

## 決定論

- サブ seed オフセット `0x4E55` (`"NU"`)。
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["nursing"]` に登録済み。
- `nursing_enricher` の encounter 単位 RNG:
  `derive_sub_seed(master_seed, offset, encounter_id)` — 同一
  encounter は常に同じ看護師を選出、主シミュレーション乱数列は消費
  しない (AD-16)。
- `assign_primary_nurse` 自体は pure で RNG 非依存 — caller が seed。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`。
- `clinosim.modules.staff.engine` — `scoped_nurses` (病棟 / 診療科で
  絞った看護師 pool)。
- `clinosim.determinism` — encounter 単位 RNG の構築。
- `clinosim.datafiles` — `load_validated_yaml`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.types.staff` — `StaffRoster`。
- `numpy` — `np.random.Generator`。
- `pydantic` — `NursingAssessment` / `_NursingFocus` model。

## 定数と設定

- 公開 frozenset (`engine.py`):
  - `INPATIENT_ENCOUNTER_TYPES = {"inpatient", "icu", "rehab_inpatient"}`
    — enricher が受理する encounter 種別。他は skip (`primary_nurse_id`
    非設定)。
  - `SUPPORTED_ADL_CATEGORIES = {"eating", "bathing", "dressing",
    "toileting", "mobility"}` — 5 Barthel index カテゴリ。
  - `SUPPORTED_RISK_ASSESSMENTS = {"fall_risk", "pressure_ulcer_risk",
    "aspiration_risk"}` — 3 リスク種別。
- [`reference_data/nursing_assessment.yaml`](reference_data/nursing_assessment.yaml)
  — `load_nursing_assessment()` 経由でのみ読まれる scaffolding。キー:
  - `adl_categories` — `SUPPORTED_ADL_CATEGORIES` の各キー 1:1 対応、
    値は取り得る ADL 状態の順序付き list。
  - `risk_assessments` — `SUPPORTED_RISK_ASSESSMENTS` の各キー 1:1 対応、
    値は取り得るリスク状態の順序付き list。
  - `disease_specific_nursing_focus` — `{disease_id: {focus,
    interventions: {<lang>: list[str]}}}` (看護 focus テキスト)。
  - `baseline` — 疾患別が無いときの fallback。同 `{focus, interventions}`
    形状。
- load 時検証は `NursingAssessment` Pydantic model (`baseline` と各疾患
  エントリは `_NursingFocus`) を `load_validated_yaml` で適用する。
  空 top-level、top-level キー欠落、`focus` / `interventions` の無い
  focus、言語ごとに list でない `interventions`、
  `SUPPORTED_ADL_CATEGORIES` / `SUPPORTED_RISK_ASSESSMENTS` と双方向に
  ずれた `adl_categories` / `risk_assessments` キーを拒否する。drift は
  load 時に raise — 標準 PR-90 silent-no-op 防御。
- **scaffolding 注**: `load_nursing_assessment` には現在 live consumer
  が無く、data は自身の unit test からのみ load される。想定 reader は
  下流の narrative 作業 (β-JP-1)。

## ディレクトリ構造

```
clinosim/modules/nursing/
  __init__.py                     公開定数 + 関数を再 export
  engine.py                       loader / validator / assign_primary_nurse /
                                  nursing_enricher (POST_ENCOUNTER)
  reference_data/
    nursing_assessment.yaml       ADL + リスク + 疾患別 focus scaffolding
```

**専用 `enricher.py` は存在しない** — enricher エントリは `engine.py`。
**`audit.py` は存在しない** — `ModuleAuditSpec` は登録していない。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) の
`register_builtin_enrichers` で登録:

- `name="nursing_assignment"`, `stage=POST_ENCOUNTER`, `order=94`,
  `enabled=lambda c: True`, `run=nursing_enricher`。
- `triage` (order 93) の後、`document` (order 95) の前に実行。
- **もう 1 つの nursing enricher — `nursing_flowsheets` — は同 file 内で
  `name="nursing"`, `stage=POST_RECORDS`, `order=20` として登録され、
  実体は
  [`clinosim.modules.observation.nursing_enricher`](../observation/README.ja.md)。**
  混同しないこと。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| FHIR `CareTeam` builder | [`clinosim/modules/output/fhir_r4/encounters/care_team.py`](../output/fhir_r4/encounters/care_team.py) | `primary_nurse_id` を `CareTeam.participant[1].member` として emit — 非空のときのみ (attending physician が participant[0])。 |
| FHIR 看護 flowsheet performer fallback | [`clinosim/modules/output/fhir_r4/procedures/nursing.py`](../output/fhir_r4/procedures/nursing.py) (`_bb_nursing_observations`) | RM-1: 看護 survey Observation に per-observation performer が無いときの default `performer` として `primary_nurse_id` を使用。 |
| FHIR Practitioner 出力 | [`clinosim/modules/output/fhir_r4/lib/inline_bb.py`](../output/fhir_r4/lib/inline_bb.py) (`_bb_practitioners`) | RM-1: 看護 Observation の performer 参照が解決するよう、各 encounter の `primary_nurse_id` を `Practitioner` として emit。 |
| Enricher registry (`nursing_assignment`) | [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) (`register_builtin_enrichers`) | POST_ENCOUNTER order=94 登録。 |

## テスト

```bash
pytest tests/unit -k nursing -q         # 定数, loader, validator, assign
pytest tests/integration -k nursing -q  # enricher + flowsheet FHIR 出力
```

個別ファイル:

- [`tests/unit/test_nursing.py`](../../../tests/unit/test_nursing.py)
  — cross-package nursing unit test。
- [`tests/unit/modules/nursing/test_engine.py`](../../../tests/unit/modules/nursing/test_engine.py)
  — `assign_primary_nurse` + 定数 + `nursing_enricher` 決定論。
- [`tests/unit/modules/nursing/test_nursing_assessment_yaml.py`](../../../tests/unit/modules/nursing/test_nursing_assessment_yaml.py)
  — `NursingAssessment` validator coverage。
- [`tests/integration/test_nursing_enricher.py`](../../../tests/integration/test_nursing_enricher.py)
  — POST_ENCOUNTER enricher end-to-end。
- [`tests/integration/test_fhir_nursing.py`](../../../tests/integration/test_fhir_nursing.py)
  — FHIR flowsheet Observation 出力 (RM-1 performer fallback 経由で
  本モジュールに触れる)。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
