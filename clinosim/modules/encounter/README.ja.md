# `clinosim.modules.encounter` — encounter 条件 protocol + 日次 cycle timeline

## 概要

入院 / ED / 外来 encounter に関する 2 つの関連責務を持つ:

1. **encounter-condition protocol registry** —
   [`reference_data/`](reference_data/) 配下の 52 YAML。外来 / ED 短期
   条件 (asthma attack、migraine、minor laceration、screening visit、
   allergic reaction、syncope、viral gastroenteritis、annual health
   screening、dialysis session、rehab outpatient 等) を扱う。
   [`clinosim.modules.disease`](../disease/README.ja.md) が担当する
   入院 / 外傷 protocol の兄弟 registry。
2. **入院日次 cycle timeline** — 1 入院 encounter に対する
   決定論的 admission → daily cycle → discharge の event 順序と、
   cursor / snapshot 境界を跨いで encounter id を安定化する
   決定論的 hash-based encounter-id suffix。

## Scope

- **In scope**: `EncounterConditionProtocol` Pydantic schema + child
  model (`OutpatientSoapTemplate`, `EdNoteTemplate`, `EdPhysicalExam`,
  `EdTriageTemplate`, `EncounterNarrativeSpec`, `SymptomOnset`,
  `ScreeningSchedule`, `ScreeningLab`, `VisitProcedure`、および型付きの
  workup / treatment / prescription / scenario 節)、per-protocol loader
  + 全 registry loader (共に `@lru_cache`)、`screening_schedule` と
  `protocol_min_age` / `AGE_DISTRIBUTION_MIN_AGE`、F1 cross-cursor 安定 id
  式付き `create_inpatient_encounter`、`generate_daily_cycle`
  (日次 event 骨格、日本の中規模病院 cadence — morning vitals
  06:00、morning labs 06:30、rounds 09:00、afternoon vitals
  14:00、evening vitals 18:00、evening meds 18:30、night check
  22:00)、`generate_encounter_timeline` (admission + daily × N +
  discharge を時系列 sort)。
- **Out of scope**: 入院 / 外傷 / 労災 protocol
  ([`clinosim.modules.disease`](../disease/README.ja.md))、narrative
  rendering
  ([`clinosim.modules.document.narrative`](../document/narrative/README.ja.md))、
  encounter simulation / stateful daily loop
  ([`clinosim.simulator`](../../simulator/))、FHIR `Encounter`
  emission ([`clinosim.modules.output`](../output/README.ja.md))。

### 縦断サービスライン encounter shape (v0.5 → v0.6.0)

上記 52 YAML protocol は ED / 外来主訴 episode を対象とする。以下 2
縦断サービスラインは `reference_data/` protocol 非依存で、shape は
[`clinosim/locale/shared/perinatal.yaml`](../../locale/shared/perinatal.yaml)
と
[`clinosim/locale/shared/chronic_followup.yaml`](../../locale/shared/chronic_followup.yaml)
に直接持つ:

- **周産期分娩 Encounter** (母親側、IMP admission、admit dx `O80`、
  discharge dx `Z37.0`、LOS JP 5 日 / US 2 日、部門は `obstetrics_gynecology`、
  `department_rollup` で集約 (同梱の病院設定では `primary_care`)。delivery Procedure
  US CPT `59400`、JP は正常分娩が保険外のため K コードなし)。
- **新生児 Encounter** (IMP admission、`admit_source = "born"` —
  [`clinosim/codes/hl7_encounter.py`](../../codes/hl7_encounter.py) の
  `AdmitSource.BORN` の値で、
  [`clinosim/types/encounter.py`](../../types/encounter.py) の `str` 型
  `Encounter.admit_source` に格納、`admit_source_encounter_id` が母親の
  分娩 encounter を指し新生児側の FHIR `Encounter.partOf` に emit、
  LOS は母親から継承、discharge dx `Z38.0`)。
- **産褥 (postpartum) 外来 encounter × 2** — 分娩後 ~1 週間 / ~4 週間の
  `chronic_visit` event、disease_id `Z39`、`chronic_followup.yaml` に
  entry。
- **中絶外来日帰り手術 Encounter** (O03.9 spontaneous / O04.5 induced、
  15–19 → 35–44 の年齢帯 gate)、config は `perinatal.yaml::abortion`。
  中絶 outcome が発火した場合は delivery / newborn chain は emit しない。
- **化学療法 Encounter** (`chemo_visit` 外来 event) — 各 regimen
  cycle につき 1 件、cadence は
  [`clinosim/locale/shared/chemo_regimens.yaml`](../../locale/shared/chemo_regimens.yaml)
  から。Encounter は分娩 / 化学療法 Procedure と、([`order`](../order/README.ja.md)
  経由の) regimen `cycle_orders` 各 Day-1 薬剤に対する per-cycle
  MedicationRequest + MedicationAdministration を持つ。放射線治療
  encounter も同様。

## Public API

`__init__.py` は空。呼び出し側は 2 submodule から直接 import:

```python
from clinosim.modules.encounter.engine import (
    DailyCycleEvent,                 # dataclass (timestamp, event_type, data)
    create_inpatient_encounter,      # (patient_id, admission_datetime, chief_complaint="…", department_id="internal_medicine", visit_number=1) -> Encounter
    generate_daily_cycle,            # (encounter, day_number) -> list[DailyCycleEvent]
    generate_encounter_timeline,     # (encounter, total_days) -> list[DailyCycleEvent]
)

from clinosim.modules.encounter.protocol import (
    EncounterConditionProtocol,      # Pydantic BaseModel
    EncounterNarrativeSpec,          # narrative wrapper (α-min-2 Task 6)
    OutpatientSoapTemplate,          # SOAP note field
    EdNoteTemplate,                  # ED physician note field
    EdPhysicalExam,                  # ED physical exam sub-model
    EdTriageTemplate,                # ED triage sub-model
    load_encounter_condition,        # (condition_id) -> dict  (@lru_cache=64)
    load_all_encounter_conditions,   # () -> dict[condition_id, dict]  (@lru_cache=1)
    SymptomOnset,                    # 症状の発症時期 (unit + range)
    DEFAULT_SYMPTOM_ONSET,           # onset 未指定時の既定値 (days, 1-3)
    ScreeningSchedule,               # screening の受診間隔 / 対象年齢 / 受診率
    ScreeningLab,                    # 年齢 / 性別 / BMI で追加する検査
    VisitProcedure,                  # 受診ごとに実施する処置 (code / SNOMED / 名称 / 所要時間)
    AGE_DISTRIBUTION_MIN_AGE,        # age_distribution → 最低年齢
    protocol_min_age,                # (spec) -> int | None  (min_age、なければ age_distribution の下限)
    screening_schedule,              # (condition_id) -> ScreeningSchedule  (screening protocol の schedule (無ければ ValueError))
    discharge_instructions_for_age,  # (protocol, age_months) -> 退院指導; 年齢条件付きの項目は `min_age_months` 未満で `younger` を返す (12か月未満に蜂蜜を勧めない)
)
from clinosim.modules.encounter.discharge_outcome import discharge_outcome
# (encounter, *, deceased) -> 終了した入院の退院時転帰キー (improved / remission /
# unchanged / worsened / death_from_condition / death_other / other)。DPC 様式1 の
# 退院時転帰で、locale/shared/discharge_outcomes.yaml の順序付き規則で経過から導く
# (Issue #3150)。国ごとの符号化は locale/<cc>/code_mapping_discharge_disposition.yaml。
```

## 決定論

- **Encounter ID は counter 派生ではなく hash 派生** (F1 fix)。
  `_encounter_id_suffix(patient_id, admission_datetime,
  chief_complaint, department_id, visit_number)` は 5 入力を
  SHA-256 digest に折り込み先頭 6 bytes を取り
  `_ENCOUNTER_SUFFIX_MODULUS = 10**12` (12 桁 10 進) で mod する。
  cursor 独立 — `snapshot_date` のみが異なる 2 run は上流で処理された
  無関係 encounter 数によらず同一 encounter に同 id を割り当てる。
  12 桁幅は p=500 の cohort で 6 桁幅が単一患者内衝突を起こした
  実測から選定。
- 日次 cycle + timeline 生成は pure: `rng` 引数無し、cadence 時刻
  (06:00 / 06:30 / 09:00 / 14:00 / 18:00 / 18:30 / 22:00) は固定。
- Protocol loader は pure。`EncounterConditionProtocol` は必須 field
  (`condition_id`, `icd10_code`, `chief_complaint`, `encounter_type`,
  `department`) を求め、optional section (workup, treatment, discharge
  prescriptions, narrative 等) をすべて型付き field で宣言し、未知の
  key を拒否する (`extra="forbid"`)。load 時に全 `route:` 値を共有
  route 語彙でも検査する。

## 依存

- `pydantic` — schema (`extra="forbid"`)。
- `yaml` — YAML パーサ。
- `clinosim.types.encounter` — `Encounter`, `EncounterStatus`,
  `EncounterType`。
- `hashlib.sha256` — encounter-id 導出。
- `clinosim.modules.output.fhir_r4.lib.reference_data.validate_yaml_route_value`
  — loader 内で lazy import (`route:` 語彙検査)。
- `clinosim.modules.observation.engine` — `canonical_lab_name`、
  `lab_panel_components` (lazy。`ScreeningLab` の検査名検証)。
- `clinosim.codes.code_exists` (lazy。`VisitProcedure` の code 検証)、
  `clinosim.locale.loader.load_code_mapping` (lazy)、
  `clinosim.age_bands.parse_closed_age_band` (lazy)、
  `clinosim.datafiles.load_data_yaml`。

## 定数と設定

- **encounter-condition YAML registry**: [`reference_data/`](reference_data/)
  — 52 file (1 condition = 1 file、filename = condition_id +
  `.yaml`)。外来慢性フォロー、ED 短期、screening (mammography /
  colonoscopy / diabetic retinopathy / annual health screening)、
  rehab、dialysis、cardiac rehab、smoking cessation、mental health
  follow-up の condition class をカバー。各 entry は chief-complaint、
  physical-exam template、narrative section (SOAP / ED-note /
  triage)、臨床 metadata を保持。
- **出生ごとの新生児 ED condition** (Issue #3063): `neonatal_fever.yaml` は
  ED 受診 mix からは引かれない (`probability: 0`)。各乳児は最大 1 回、
  確率 `incidence_per_1000_births` (US 4.56、JP は出典が無いため無し) で、
  日齢 `min_age_days`-`max_age_days` のいずれかの日に受診する。person id の
  hash で決まる (`phases/_ed_slot.py::neonatal_ed_onsets`)。この期間内の
  乳児には他の ED condition を当てない (`neonate_excluded`)。受診では重症
  細菌感染症の検査、`procedures_by_age_days` (日齢 8-21 の腰椎穿刺)、
  体重あたりの抗菌薬初回投与を行い、`transfer_pediatric` (HL7
  `other-hcf`) で転院搬送する。小児病棟のある病院ではこの ED 受診は生じない
  (`admitted_with_inpatient_unit`)。
- **Encounter-id 形状** (`engine.py`):
  - `_ENCOUNTER_SUFFIX_MODULUS = 10**12` — 12 桁 suffix modulus。
  - Encounter id: `ENC-{patient_id}-{suffix:012d}`。
  - Episode id: `EP-{patient_id}-{suffix:012d}`。
  - Disease-event id: `DE-{patient_id}-001`。
- **日次 cycle cadence** (`generate_daily_cycle`、hard-coded):
  06:00 morning vitals · 06:30 morning labs · 09:00 rounds ·
  14:00 afternoon vitals · 18:00 evening vitals · 18:30 evening
  meds · 22:00 night check。「日本の中規模病院」を前提とし、他の
  cadence は per-country 拡張余地。

## ディレクトリ構造

```
clinosim/modules/encounter/
  __init__.py                     空
  engine.py                       入院 encounter 生成 + 日次 cycle timeline
  protocol.py                     EncounterConditionProtocol + child model + loader
  reference_data/
    <condition_id>.yaml           52 file (外来 / ED / screening condition ごと 1 file)
  SPEC.md                         拡張設計参考 (runtime data ではない)
```

**`enricher.py` / `audit.py` は存在しない**。

## Enricher 配線

該当なし — 本モジュールは data + primitives 層であり enricher では
ない。`register_builtin_enrichers` に登録なく、`ENRICHER_SEED_OFFSETS`
にも seed 未登録。simulator が必要なものを直接 import する。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Simulator boot + 全 encounter simulator | [`clinosim/simulator/{inpatient,outpatient,emergency,perinatal,unknown_condition,enumerate,cli_test_encounter,cli}.py`](../../simulator/), [`clinosim/simulator/phases/_ed_slot.py`](../../simulator/phases/_ed_slot.py) | `create_inpatient_encounter` と condition-protocol loader を import。 |
| Triage | [`clinosim/modules/triage/engine.py`](../triage/engine.py) | `load_all_encounter_conditions` を読む。 |
| Narrative | [`clinosim/modules/document/narrative/passes.py`](../document/narrative/passes.py) | 外来 / ED template flow で `EncounterConditionProtocol.narrative` を read。 |
| Encounter-type FHIR mapping | [`clinosim/modules/output/fhir_r4/encounters/`](../output/fhir_r4/encounters/) | protocol が持つ encounter class + type 文字列を消費。 |

## テスト

```bash
pytest tests/unit -k encounter -q
```

個別ファイル:

- [`tests/unit/test_encounter_protocol_validation.py`](../../../tests/unit/test_encounter_protocol_validation.py)
  — 52 YAML 全体に対する Pydantic schema 検証 (必須 field、未知 key の拒否)。
- [`tests/unit/test_encounter_archetype_severity.py`](../../../tests/unit/test_encounter_archetype_severity.py)
  — archetype × severity coverage。
- [`tests/unit/test_encounter_features.py`](../../../tests/unit/test_encounter_features.py)
  — condition ごとの期待 feature キー。
- [`tests/unit/test_cli_test_encounter_format.py`](../../../tests/unit/test_cli_test_encounter_format.py)
  — CLI encounter-id 形式 guard (F1 安定性)。
- [`tests/unit/output/test_fhir_encounter_*`](../../../tests/unit/output/)
  — FHIR 側統合 guard (encounter reason code JP、ED delegation、
  type codes YAML)。
- [`tests/unit/modules/encounter/`](../../../tests/unit/modules/encounter/)
  — module-scoped unit test。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
