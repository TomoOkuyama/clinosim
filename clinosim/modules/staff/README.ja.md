# `clinosim.modules.staff` — 病院スタッフ roster 生成 + イベント割当

## 概要

シミュレータ内 病院の practitioner roster (医師、看護師、検査技師、
放射線科医、薬剤師、多職種 allied-health) を病院の部門レイアウト +
病床数に応じて scale して生成し、臨床イベント (入院、回診、退院、
検査採取、検査結果、画像読影、投薬) に per-encounter でスタッフを
dispatch する。生成される `StaffRoster` は、simulator が encounter
builder および FHIR `Practitioner` / `PractitionerRole` 出力に渡す
staff identity の単一情報源。

## Scope

- **In scope**: `hospital_config`
  (`available_departments`, `wards`, `resource_capacity.inpatient_beds`)
  からの roster 構築、部門別医師数 (内科 / 一般外科 / 救急は
  bed-scale 公式、その他は固定; 詳細は
  [`_staff_thresholds.py`](_staff_thresholds.py) の divisor + min 表
  を参照)、病棟別看護師数、ED / OPD 看護師プール、検査技師 /
  放射線科医 / 薬剤師 固定数、追加 allied-health 職種
  (β-JP-1 CareTeam 拡張の C5-25 Chain 3)、国別姓名 (JP は kanji +
  kana pair) と電話 / メール生成、`assign_staff` の event-type →
  staff-role dispatch。
- **In scope (fallback ID)**: `FALLBACK_PHYSICIAN_ID = "DR-001"`、
  `FALLBACK_NURSE_ID = "NS-001"`、`FALLBACK_TECH_ID = "TECH-001"`
  (Issue #562) — roster が空 (test fixture / smoke run) のときのみ
  使う grep-alignable sentinel。production 経路では fallback
  `dict.get` が発火する時点で必ず本物 ID が用意されている。
- **Out of scope**: 患者 identifier
  ([`clinosim.modules.identity`](../identity/README.md))、病院 /
  病棟 / ベッド在庫
  ([`clinosim.modules.facility`](../facility/README.md))、看護
  アセスメント scaffolding
  ([`clinosim.modules.nursing`](../nursing/README.md))、入院
  encounter への主担当看護師割当 (これは
  [`clinosim.modules.nursing.engine.nursing_enricher`](../nursing/README.md)
  で走り、**本モジュール**の roster から選ぶ)、FHIR 出力
  ([`clinosim.modules.output`](../output/README.md))。

## Public API

```python
from clinosim.modules.staff import (
    StaffMember,                       # dataclass (types.staff から再 export)
    StaffRoster,                       # dataclass (types.staff から再 export)
    generate_roster,                   # (hospital_scale, country, rng, hospital_config=None) -> StaffRoster
    assign_staff,                      # (event_type, department, roster, rng) -> {role_in_event: staff_id}
)
from clinosim.modules.staff.engine import (
    FALLBACK_PHYSICIAN_ID,             # "DR-001"
    FALLBACK_NURSE_ID,                 # "NS-001"
    FALLBACK_TECH_ID,                  # "TECH-001"
)
```

`assign_staff` は `match event_type` で dispatch:

- `"admission" | "rounds" | "discharge"` → attending physician
  (specialty マッチ、失敗時 graceful fallback) + primary nurse。
- `"lab_collection" | "lab_result"` → performing technician。
- `"imaging_interpretation"` → interpreting radiologist。
- `"medication_administration"` → 発注部門所属の administering nurse。

`StaffRoster.get_by_role(role, department=None)` は module 内部で
使う主要 lookup 形状。

## 決定論

- **`ENRICHER_SEED_OFFSETS` にサブ seed 未登録**。本モジュールは
  enricher を登録せず、encounter simulator から imperative に呼び
  出される。RNG は呼び出し側が握る。
- caller 責務: `generate_roster` / `assign_staff` は渡された `rng`
  に対して純粋。encounter simulator (`inpatient.py`, `outpatient.py`,
  `lab_pipeline.py`) は各々自前のサブ RNG (例: 入院割当用の
  per-encounter seed) を導出してから `assign_staff` を呼ぶため、
  per-event dispatch は再現可能かつ主 clinical stream を乱さない。

## 依存

- `clinosim.modules._shared` — `is_jp` (国別電話フォーマット + JP
  kana name の dispatch)。
- `clinosim.modules.staff._staff_thresholds` — 全 threshold 表
  (divisor / min / count / qualification-year 範囲 / phone 桁範囲 /
  追加 staff roster)。
- `clinosim.locale.loader` — `load_names(country)` で姓 / 名 pool。
- `clinosim.types.staff` — `StaffMember`, `StaffRoster`。
- `numpy` — `np.random.Generator`。
- 他の `clinosim.modules.*` には依存しない。

## 定数と設定

- **Threshold 表**: [`_staff_thresholds.py`](_staff_thresholds.py)
  — magic number をすべて名付けて docstring 付与済 (Issue #562 sweep)。
  含まれるもの:
  - 医師 per-bed divisor (`DOCTORS_PER_INTERNAL_MED_BED_DIVISOR`、
    `DOCTORS_PER_SURGERY_BED_DIVISOR`、
    `DOCTORS_PER_ED_BED_DIVISOR`) と min
    (`MIN_INTERNAL_MED_PHYSICIANS`、`MIN_SURGERY_PHYSICIANS`、
    `MIN_ED_PHYSICIANS`); その他部門は `DOCTORS_PER_DEPT_FIXED`。
  - 看護 scaling: `NURSES_PER_BED_DIVISOR`、`NURSES_PER_BED_BUFFER`、
    `NURSES_PER_WARD_MIN`、`MIN_BEDS_PER_WARD`、
    `FALLBACK_BEDS_PER_WARD`、`ED_OPD_NURSES_PER_AREA`。
  - 補助職 count: `LAB_TECH_COUNT`、`RADIOLOGIST_COUNT`、
    `PHARMACIST_COUNT`。
  - 職種別資格年範囲
    (`{PHYSICIAN,NURSE,PHARMACIST,RADIOLOGIST,TECH,ALLIED_HEALTH}_QUALIFICATION_YEAR_{START,END_EXCLUSIVE}`)。
  - 性比: `PHYSICIAN_MALE_RATIO`、`NURSE_FEMALE_RATIO`。
  - 電話桁範囲 (`JP_PHONE_*`, `US_PHONE_*`)。
  - `STAFF_ID_FALLBACK_{MIN,MAX_EXCLUSIVE}` — locale name pool が
    空の場合の missing-name fallback (`Staff-{n}` id)。
  - `EXTRA_STAFF_ROLES` — C5-25 Chain 3 の allied-health 拡張を
    表す `(role, id_prefix, dept, count, female_ratio)` の tuple。
- **部門 → staff-ID prefix** (`engine.py` の `_DEPT_PREFIX`):
  `internal_medicine → "IM"`, `cardiology → "CA"`,
  `pulmonology → "PU"`, `gastroenterology → "GI"`,
  `nephrology → "NE"`, `endocrinology → "EN"`, `neurology → "NR"`,
  `general_surgery → "GS"`, `orthopedics → "OR"`,
  `neurosurgery → "NS"`, `trauma_surgery → "TS"`,
  `emergency_medicine → "EM"`, `primary_care → "PC"`,
  `obstetrics_gynecology → "OB"`, `pediatrics → "PD"`。未知部門は
  `dept[:2].upper()` に fallback。
- **JP 姓名 pair** (`_generate_name_pair`): `(kanji, kana)` を返す
  ため `StaffMember.name_phonetic` に kana を populate でき、
  JP Core Practitioner の `HumanName` SYL エントリを埋められる
  (C2-19 継続)。非 JP は `(name, "")`。

## ディレクトリ構造

```
clinosim/modules/staff/
  __init__.py                     public API (StaffMember, StaffRoster, generate_roster, assign_staff)
  engine.py                       roster 生成 + assign_staff dispatch + name / phone / email helper
  _staff_thresholds.py            named threshold 定数 (Issue #562)
  SPEC.md                         v1+ 設計参考 (役職 / lifecycle / 資格 — runtime data ではない)
```

**`enricher.py` / `audit.py` / `reference_data/` は存在しない**。

## Enricher 配線

該当なし — 本モジュールは `register_builtin_enrichers` に登録なく、
`ENRICHER_SEED_OFFSETS` にも seed 未登録。roster は CLI / encounter
simulator が run あたり 1 回構築し、`assign_staff` は下記 encounter
経路から imperative に呼ばれる。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Encounter builder (inpatient) | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) (`L45` 付近, `L260` 付近) | `assign_staff("admission", department, roster, rng)` で attending + primary nurse を選出。 |
| Encounter builder (outpatient) | [`clinosim/simulator/outpatient.py`](../../simulator/outpatient.py) (`L21`, `L109`, `L161`, `L177` 付近) | 回診 / 投薬 / 検査採取の割当。 |
| Lab pipeline | [`clinosim/simulator/lab_pipeline.py`](../../simulator/lab_pipeline.py) (`L51`, `L113`, `L131`, `L166` 付近) | `assign_staff("lab_result", …)` で performing / result 技師を選出、roster 空時は `FALLBACK_TECH_ID`。 |
| CLI single-encounter driver | [`clinosim/simulator/cli_test_encounter.py`](../../simulator/cli_test_encounter.py) (`L16`, `L80` 付近) | smoke run で `generate_roster("medium", country, rng)` を呼ぶ。 |
| Nursing 主担当看護師 enricher | [`clinosim/modules/nursing/engine.py`](../nursing/engine.py) | `roster.get_by_role("nurse")` で主担当看護師を選出 (本モジュール生成 roster を transit 消費)。 |
| FHIR `Practitioner` + `PractitionerRole` builder | [`clinosim/modules/output/fhir_r4/`](../output/fhir_r4/) | `StaffMember` field を `Practitioner` (name / kana / telecom / qualification) と `PractitionerRole` (department / specialty) に emit。 |

## テスト

```bash
pytest tests/unit -k staff -q      # types + fallback 定数
```

個別ファイル:

- [`tests/unit/test_staff_types.py`](../../../tests/unit/test_staff_types.py)
  — `StaffMember` / `StaffRoster` dataclass shape。
- [`tests/unit/modules/test_staff_fallback_constants.py`](../../../tests/unit/modules/test_staff_fallback_constants.py)
  — `FALLBACK_*` 定数 + module-level 命名 (Issue #562)。

**coverage gap**: roster 生成と `assign_staff` dispatch に専用 unit
test は無く、integration / e2e で間接カバーされている。`generate_roster`
(scale 不変量、ID 一意性、追加 role 混入) と `assign_staff` (event-type
別 dispatch、empty roster fallback) に対する専用 unit test file の追加は
低コストの follow-up。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
