# clinosim モジュールマップ

clinosim の **35 モジュール** (数え方: `clinosim/modules/` 配下の
top-level package。`_shared.py` 等の非 package file は除く。
`nursing_assignment` は observation-layer nursing flowsheet enricher
と `clinosim/modules/nursing/` を共有) を 1 ページで俯瞰する。プロジェクト
初見はここから読む。

**モジュール別詳細**: 各モジュールは canonical 11-section 構造
(Purpose / Scope / Public API / Determinism / Dependencies /
Constants and configuration / Directory contents / Enricher wiring /
Output surfaces / Testing / Ownership) に従う `README.md` +
`README.ja.md` を持つ — モジュール索引は
[`clinosim/modules/README.ja.md`](clinosim/modules/README.ja.md)。

## このドキュメントの読み方

| Goal | Read |
|---|---|
| 初めて見る | top to bottom |
| 特定モジュールを探す | "Module inventory" table |
| 既存コードを変更する | "Typical change impact" |
| 新モジュールを足す | [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) + [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md) |
| PR 検証手段を選ぶ | [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) 「PR 検証ガイド」 |

## TL;DR

clinosim は population 駆動 / physiology ベースの合成 EHR data
simulator。`clinosim/modules/` 配下 **33 テーマ別モジュール**を
4 層に組織:

1. **Foundation** — `clinosim/codes/` + `clinosim/locale/` +
   `clinosim/types/` (clinosim 内相互依存なし)。
2. **Simulation** — physiology → observation → order →
   clinical_course → encounter / patient activation。
3. **Enrichment** — `clinosim/simulator/enrichers.py` に登録された
   POST_POPULATION / POST_ENCOUNTER / POST_RECORDS pass。
4. **Output** — `clinosim/modules/output/` アダプタが CIF を消費し
   FHIR R4 Bulk Data NDJSON / CIF-JSON / CSV に emit。

データフロー: `population → patient activation → encounter loop →
enrichers → CIF (canonical intermediate format) → output adapter`。

**プロジェクト目標**: CIF データを **FHIR R4 + JP Core 準拠**に変換
しつつ、臨床リアリズム + JP localisation 品質を保つ。AD-60 audit
framework (現在 6 per-module plug-in: `hai`, `antibiotic`, `order`,
`imaging`, `document`, `triage`) が本目標を守る load-bearing 検証 gate。

## レイヤー構造

```
┌─ Foundation (clinosim 相互依存なし) ─────────────────────┐
│  clinosim/codes/       国際コード体系                    │
│  clinosim/locale/      国別データ                        │
│  clinosim/types/       共有データ型                      │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Simulation (physiology 駆動) ───────────────────────────┐
│  physiology   patient state + lab/vital 導出             │
│  observation  result 生成 (panel / microbiology / 看護)  │
│  order        lab/medication/imaging 発注                │
│  clinical_course  日次進行 + 合併症                      │
│  diagnosis    Bayesian 鑑別診断                          │
│  procedure    手術 + bedside 処置 + rehab                │
│  encounter    入院 / ED / 外来 YAML protocol             │
│  disease      32 疾患 YAML protocol                      │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Population & activation ────────────────────────────────┐
│  population   demographics + life event                  │
│  patient      Layer 1 → Layer 2 activation               │
│  identity     JP 保険 + national ID (opt-in)             │
│  pediatric    小児 encounter 発生 (Issue #760)           │
│  staff        roster + practitioner assignment           │
│  facility     病院運用 state + queueing                  │
│  healthcare_system  国 config loader                     │
│  family_history  第 1 度近親 疾患歴                      │
│  sdoh         smoking + alcohol 参照 (data-only)         │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Enrichment ─────────────────────────────────────────────┐
│  POST_POPULATION stage (患者単位、demographics 後):      │
│  allergy(10)      15% 全体 gate + category-weighted allergen│
│  identity(10)     JP 保険 + national ID (JP gate)        │
│                                                          │
│  POST_ENCOUNTER stage (encounter 単位、loop 後):         │
│  device(70)       CVC / catheter / ventilator 配置       │
│  hai(80)          CLABSI / CAUTI / VAP + Phase 3a WBC/CRP│
│  antibiotic(85)   HAI empirical + narrow de-escalation   │
│  imaging(90)      ImagingStudy metadata chain (AD-62)    │
│  triage(93)       JTAS/ESI level + arrival_mode (ED-only)│
│  nursing_assignment(94)   主担当看護師                   │
│  document(95)     ClinicalDocument stub + ClinicalImpression│
│                                                          │
│  POST_RECORDS stage (cross-record、全 record 後):        │
│  nursing(20)      NEWS2 / GCS / Braden / Morse           │
│                   (observation-layer の nursing_flowsheets、│
│                   nursing_assignment とは別)             │
│  immunization(30) CVX ワクチン接種歴                     │
│  family_history(40) 第 1 度近親歴                        │
│  code_status(50)  DNR / Full Code 蘇生方針               │
│  care_level(60)   JP 要介護度 (JP 限定)                  │
│  medication_monitoring(65) 慢性薬 → labs (Issue #757)    │
│  health_checkup(70) JP 事業者健診 (JP 限定、opt-in)      │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Output ─────────────────────────────────────────────────┐
│  output       CIF → FHIR R4 NDJSON / CSV アダプタ        │
│  llm_service  optional narrative 生成 (Stage 2)          │
│  validator    realism benchmark + consistency check      │
└──────────────────────────────────────────────────────────┘
```

## モジュール索引

計 35 モジュール (`clinosim/modules/` 配下 top-level package;
下表は追加で foundation の `codes` / `locale` も列挙)。各エントリは
canonical 11-section 構造に従う per-module README にリンクする。

| Module | 役割 | Layer | Sub-seed | Enricher stage / order |
|---|---|---|---|---|
| [codes](clinosim/codes/) | 国際コード lookup (LOINC/SNOMED/ICD/RxNorm/JLAC10/CVX/JJ1017 K-code) | foundation | — | — |
| [locale](clinosim/locale/) | 国別データ (names / addresses / reference range / code_mapping) | foundation | — | — |
| [physiology](clinosim/modules/physiology/README.ja.md) | 14 変数 physiology state + lab/vital 導出 | simulation | — (caller RNG) | — |
| [observation](clinosim/modules/observation/README.ja.md) | lab / vital / microbiology + nursing flowsheet | simulation | nursing `0x4E55` (共有) | POST_RECORDS 20 (`nursing`) |
| [order](clinosim/modules/order/README.ja.md) | lab / medication / imaging 発注 + AD-60 audit | simulation | — (per-order via AD-59) | — (audit 登録) |
| [clinical_course](clinosim/modules/clinical_course/README.ja.md) | trajectory archetype + 日次 `StateChangeDirective` | simulation | — (caller RNG) | — |
| [diagnosis](clinosim/modules/diagnosis/README.ja.md) | Bayesian 鑑別 + Issue #551 非特異コード | simulation | — | — |
| [procedure](clinosim/modules/procedure/README.ja.md) | 手術 + bedside + rehab 生成 | simulation | — (caller RNG) | — |
| [encounter](clinosim/modules/encounter/README.ja.md) | encounter registry (46 YAML) + 入院日次 cycle timeline | simulation | — | — |
| [disease](clinosim/modules/disease/README.ja.md) | 疾患 registry (32 YAML) + 重症度 + acuity + 薬剤 vocabulary | simulation | — | — |
| [population](clinosim/modules/population/README.ja.md) | demographics + life event (Layer 1) | population | — (pipeline 頭) | — |
| [patient](clinosim/modules/patient/README.ja.md) | Layer 1 → Layer 2 activation + 常用薬 | population | — (caller cache) | — |
| [identity](clinosim/modules/identity/README.ja.md) | JP 保険 + national ID (opt-in) | population | `540054` (decimal、grandfathered) | POST_POPULATION 10 (JP gate) |
| [pediatric](clinosim/modules/pediatric/README.ja.md) | 小児 encounter 発生 (Issue #760) | population | — (population calendar hook) | — |
| [staff](clinosim/modules/staff/README.ja.md) | roster + per-event `assign_staff` dispatch | population | — (caller RNG) | — |
| [facility](clinosim/modules/facility/README.ja.md) | 病院運用 state + M/M/1 風 queueing | population | — | — |
| [healthcare_system](clinosim/modules/healthcare_system/README.ja.md) | 国 config loader (leaf) | population | — | — |
| [family_history](clinosim/modules/family_history/README.ja.md) | 第 1 度近親歴 | enrichment | `0x4648` ("FH") | POST_RECORDS 40 |
| [sdoh](clinosim/modules/sdoh/README.ja.md) | smoking + alcohol SNOMED reference (data-only) | enrichment | — | — |
| [allergy](clinosim/modules/allergy/README.ja.md) | SNOMED-coded アレルギーサンプリング (15% gate) | enrichment | `0x414C` ("AL") | POST_POPULATION 10 |
| [device](clinosim/modules/device/README.ja.md) | ICU デバイス配置 | enrichment | `0x4445` ("DE") | POST_ENCOUNTER 70 |
| [hai](clinosim/modules/hai/README.ja.md) | CLABSI / CAUTI / VAP + Phase 3a WBC/CRP lift + AD-60 audit | enrichment | `0x4841` ("HA") | POST_ENCOUNTER 80 |
| [antibiotic](clinosim/modules/antibiotic/README.ja.md) | HAI empirical + narrow ladder + AD-60 audit | enrichment | `0x4142` ("AB") | POST_ENCOUNTER 85 |
| [imaging](clinosim/modules/imaging/README.ja.md) | ImagingStudy metadata chain + AD-60 audit (AD-62) | enrichment | `0x4947` ("IG") | POST_ENCOUNTER 90 |
| [triage](clinosim/modules/triage/README.ja.md) | JTAS / ESI triage サンプリング + AD-60 audit (ED-only、AD-64) | enrichment | `0x5452` ("TR") | POST_ENCOUNTER 93 |
| [nursing](clinosim/modules/nursing/README.ja.md) (`nursing_assignment`) | 主担当看護師割当 (inpatient/ICU/rehab、AD-64) | enrichment | `0x4E55` ("NU") | POST_ENCOUNTER 94 |
| [document](clinosim/modules/document/README.ja.md) | stub emission + AD-60 audit + Stage 2 narrative subpackage | enrichment | `0x444F` ("DO") | POST_ENCOUNTER 95 |
| [immunization](clinosim/modules/immunization/README.ja.md) | CVX 成人ワクチン接種歴 | enrichment | `0x494D` ("IM") | POST_RECORDS 30 |
| [code_status](clinosim/modules/code_status/README.ja.md) | DNR / Full Code SNOMED 蘇生方針 | enrichment | `0x4353` ("CS") | POST_RECORDS 50 |
| [care_level](clinosim/modules/care_level/README.ja.md) | JP 要介護度 (JP 限定) | enrichment | `0x434C` ("CL") | POST_RECORDS 60 (JP gate) |
| [monitoring](clinosim/modules/monitoring/README.ja.md) | 慢性薬 → monitoring labs (Issue #757) | enrichment | `0x4D4D` ("MM") | POST_RECORDS 65 |
| [health_checkup](clinosim/modules/health_checkup/README.ja.md) | JP 事業者健診 (JP 限定 opt-in) | enrichment | `0x4843` ("HC") | POST_RECORDS 70 |
| [drug_safety](clinosim/modules/drug_safety/README.ja.md) | class ベース禁忌併用 gate + 代替薬 substitution (Issue #1066) | foundation | — (deterministic lookup) | — (library, enricher ではない) |
| [prophylaxis](clinosim/modules/prophylaxis/README.md) | DVT/VTE 化学的予防 (48h 以上 IMP、Issue #1071) | enrichment | `0x5052` ("PR") | POST_ENCOUNTER 75 |
| [output](clinosim/modules/output/README.ja.md) | CIF → FHIR R4 NDJSON / CSV アダプタ registry | output | — | — |
| [llm_service](clinosim/modules/llm_service/README.ja.md) | narrative Stage 2 用の単一 LLM gateway (AD-11) | output | — | — |
| [validator](clinosim/modules/validator/README.ja.md) | realism benchmark + consistency check | output | — | — |

Sub-seed offset は [`clinosim/seeding.py`](clinosim/seeding.py) の
`ENRICHER_SEED_OFFSETS` に定義された値。

## 依存関係ツリー

```
codes/  (依存なし)
locale/  └── codes/
types/  (依存なし)

physiology/  └── types/
observation/  ├── physiology/, codes/, locale/
order/        └── observation/, codes/
clinical_course/  └── types/, _shared/  (physiology 非依存、StateChangeDirective で decouple)
diagnosis/    └── codes/
procedure/    └── codes/, locale/, types/, disease/acuity
encounter/    └── codes/, locale/
disease/      └── (自 Pydantic model、types/ 非依存)

population/   └── locale/, disease.severity, disease.protocol, pediatric.calendar
patient/      ├── population/, codes/, locale/, physiology.engine (hba1c_from_glycemic_control)
identity/     └── locale/, types/
pediatric/    └── (population.LifeEvent、generate_pediatric_events 内で遅延 import)
staff/        └── types/, locale.names
facility/     └── types/
healthcare_system/  └── types.HealthcareSystemConfig
family_history/ ├── types/, codes/, locale/
sdoh/           └── codes/  (data-only variant、enricher なし)

allergy/        ├── types/, codes/
device/         ├── types/, codes/
hai/            ├── types/, codes/, modules/device, modules/antibiotic (ANTIBIOTIC_LOINC_LOOKUP), physiology.engine (Phase 3a lift)
antibiotic/     ├── types/, codes/, modules/observation (antibiotic_loinc_lookup)
imaging/        ├── types/, codes/, locale/, modules/order
triage/         ├── types/, codes/, locale/
nursing/        ├── types.staff/, seeding/  (Assignment 側; nursing_flowsheets は observation 側)
document/       ├── types/, codes/, locale/, modules/allergy, modules/triage
immunization/   ├── types.encounter (遅延 import)、codes/, locale/
code_status/    ├── codes/, locale/
care_level/     ├── codes/, locale/
monitoring/    ├── modules/observation.engine (generate_lab_result 等)
health_checkup/ ├── types.clinical + types.encounter、codes/

output/         └── 全 module  (_BUNDLE_BUILDERS + registry 経由)
llm_service/    └── codes/  (leaf; providers/ は任意で boto3/httpx)
validator/      └── types/  (benchmarks は標準ライブラリのみ)

simulator/  (top-level orchestration)
  ├── population/       (Layer 1)
  ├── patient/          (Layer 2 activation)
  ├── encounter/        (ED/外来 YAML)
  ├── disease/          (入院 YAML)
  ├── physiology/       (state + directive 適用)
  ├── observation/      (labs / vitals)
  ├── order/            (orders / MAR + panel_grouping)
  ├── clinical_course/  (日次進行)
  ├── diagnosis/        (working dx)
  ├── procedure/        (手術 / bedside / rehab)
  ├── staff/            (assignment)
  ├── facility/         (beds / wards / queueing)
  ├── enrichers.py      (POST_POPULATION + POST_ENCOUNTER + POST_RECORDS 登録)
  └── output/           (CIF → FHIR / CSV)
```

## Typical call chain

### Chain 1: Population + patient activation

```
simulator/engine.py: run_beta()
  ↓ load_population()          ─ population/engine.py (generate_population)
  ↓ generate_monthly_events()  ─ population/engine.py (per year × month)
  ↓ generate_healthcare_calendar()  ─ population/engine.py (per year)
  ↓ assign_identities()        ─ identity/assign.py  (POST_POPULATION order=10, JP gate)
  ↓ allergy_enricher()         ─ allergy/engine.py   (POST_POPULATION order=10)
  ↓ activate_patient()         ─ patient/activator.py  (per person、cache で exactly-once)
      ├── _derive_home_medications()  ─ locale/shared/chronic_medications.yaml
      └── PatientProfile 完成 (chronic_conditions、smoking_status、alcohol_use 等)
```

### Chain 2: Lab 導出 (最多 touch 経路)

```
simulator/inpatient.py: _run_daily_loop()
  ↓ scenario_flags_from_protocol(protocol)             ─ physiology/engine.py
  ↓ medication_flags_from_context(patient, all_orders, admission_date, day)
                                                        ─ physiology/engine.py
  ↓ flags = {**scenario_flags, **medication_flags}
  ↓ derive_lab_values(state, sex, age, **flags)         ─ physiology/engine.py
  ↓ per-order sub-RNG via individual_lab_seed()         ─ clinosim/seeding.py (AD-59)
  ↓ OrderResult populated → patient_record.lab_results
```

### Chain 3: FHIR export

```
CLI: clinosim export-fhir --format fhir-r4
  ↓ output/fhir_r4/__init__.py: convert_cif_to_fhir()
  ↓ 各 CIF 患者について:
    ↓ BundleContext を組み立て (record + country + roster + narrative merge)
    ↓ _BUNDLE_BUILDERS の各 builder:
        builder(ctx) → list[dict]  (FHIR resource)
    ↓ post_process pipeline (datetime → specimen → profile → populate → strip)
    ↓ 各 resource を <ResourceType>.ndjson に write、id で sort
  ↓ manifest.json + _facility.json + _generator_metadata.json を emit
```

新 FHIR resource 追加: `register_bundle_builder()` (AD-56) で新
builder を登録 — `_BUNDLE_BUILDERS` を直接編集しないこと。詳細は
[`clinosim/modules/output/fhir_r4/README.ja.md`](clinosim/modules/output/fhir_r4/README.ja.md)。

## Typical change impact

| 変更 | 影響 | Notes |
|---|---|---|
| Scenario flag 追加 (`causes_X`) | `physiology.engine` + `derive_lab_values` 呼び出し 4 site | `scenario_flags_from_protocol` helper 経由; [`SCENARIO_FLAGS.md`](SCENARIO_FLAGS.md) 参照 |
| 薬剤駆動 lab effect 追加 | `physiology.engine` + 4 site | `medication_flags_from_context` helper 経由; [`SCENARIO_FLAGS.md`](SCENARIO_FLAGS.md) 参照 |
| 新 code 追加 (LOINC/SNOMED/ICD/…) | `codes/data/<system>.yaml` (`en` + optional `ja`) | [`clinosim/codes/README.md`](clinosim/codes/README.md) 参照 |
| 新 FHIR resource 型 追加 | `output/fhir_r4/<domain>/` 配下に新 builder file + `register_bundle_builder()` | [`clinosim/modules/output/fhir_r4/README.ja.md`](clinosim/modules/output/fhir_r4/README.ja.md) |
| 新疾患追加 | 新 disease YAML + `locale/<country>/demographics.yaml` に登録 | [`clinosim/modules/disease/README.ja.md`](clinosim/modules/disease/README.ja.md) |
| 新モジュール追加 | [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md) を複製、[`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) 手順で登録 | canonical 11-section README 構造に従う |

> **プロジェクト目標: FHIR R4 / JP Core 準拠 + 臨床整合 + JP 言語品質**。
> PR 検証手段 (byte-diff vs 3-axis DQR vs `clinosim audit run`) は
> [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md)
> 「PR 検証ガイド」参照。

## 新モジュール追加 (5-step quick start)

1. **Base か opt-in Module か判断** →
   [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md)
   「判断: Base か Module か」。
2. **テンプレートを複製** →
   [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md)
   を `clinosim/modules/<name>/README.md` に複製、`README.ja.md`
   mirror も作成。
3. **canonical layout でファイル作成** → `__init__.py` +
   `engine.py` + `reference_data/*.yaml` + module に数値 scalar が
   あるなら `_<name>_thresholds.py` (Issue #637 lift ルール) +
   AD-60 audit plug-in を出すなら `audit.py`。
4. **enricher なら**: sub-seed offset を
   [`clinosim/seeding.py`](clinosim/seeding.py)
   `ENRICHER_SEED_OFFSETS` に登録 (16-bit hex-ASCII、例
   `0x4142 = "AB"`)、`clinosim/simulator/enrichers.py` に
   `register_enricher(...)` 呼び出しを追加。
5. **本 `MODULES.md` 索引表**に新行を追加。

## Where to read next

| Doc | Purpose |
|---|---|
| [`README.md`](README.md) / [`README.ja.md`](README.ja.md) | ユーザー向け概要 |
| [`AGENTS.md`](AGENTS.md) | AI エージェント規則 + プロジェクト規約 (`CLAUDE.md` は本 file への pointer) |
| [`DESIGN.md`](DESIGN.md) | landing pointer → `docs/architecture/` (設計原則 / architecture notes / ADR history) |
| [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) | Module 作成 playbook + PR 検証ガイド |
| [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md) | 新 module README ボイラープレート |
| [`SCENARIO_FLAGS.md`](SCENARIO_FLAGS.md) | Scenario / 薬剤 flag 中央 reference |
| [`docs/roadmap.md`](docs/roadmap.md) | Roadmap (GitHub Issues board) |
| [`clinosim/modules/README.ja.md`](clinosim/modules/README.ja.md) | モジュール索引 (本 file の per-module 対応) |

英語版: [`MODULES.md`](MODULES.md)。
