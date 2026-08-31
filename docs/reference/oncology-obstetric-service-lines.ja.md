# 腫瘍・産科サービスライン

*clinosim の腫瘍 (がん) + 産科 (妊娠・分娩) サービスラインの出力に関する
リファレンス。self-contained: ここで参照するスキーマ・コード・ファイル
パスはすべて現行リポジトリの状態と一致する。増分スライスで出荷される
機能については各スライスのスコープと残りをカバーする follow-up
を明記する。*

**ステータス:** v0.6.0 リリースゲート時点の最新。英語版:
[`oncology-obstetric-service-lines.md`](oncology-obstetric-service-lines.md)。

---

## 1. カバー範囲

両サービスラインは同じ出力パターンを共有する:
1. 慢性疾患保有率 (`locale/<c>/demographics.yaml` の
   `chronic_prevalence`) が患者にマーカーを付ける。
2. `clinosim/modules/population/engine.py` のスケジューラがマーカーを
   正しい時間的頻度で `LifeEvent` に変換する。
3. `clinosim/simulator/engine.py` のディスパッチャが各イベントを
   ビルダに振り分け、リソース (Encounter + Condition + Procedure +
   Medication…) を出力する。

### 1.1 腫瘍 — カバー要素

| 要素 | 内容 | 場所 |
|---|---|---|
| がん慢性マーカー (10 部位) | C15 / C16 / C18 / C22 / C25 / C34 / C50 / C61 / C67 / C71 | `locale/jp/demographics.yaml` + `locale/us/demographics.yaml` |
| 男性乳がん (C50 全体の ~1 %) | 女性 primary + 男性 augmentation | `chronic_prevalence.C50.by_sex` (§3.2) |
| がん follow-up 外来訪問 | 四半期毎、部位別 visit reason + labs (腫瘍マーカー + basic panel) + 処方 renewal | `locale/shared/chronic_followup.yaml` |
| 腫瘍マーカー labs | CEA / CA19-9 / AFP / PIVKA-II / CA15-3 / PSA — 基準範囲 + baseline 正常値 | `locale/<c>/reference_range_lab.yaml` + `modules/observation/engine.py::BASELINE_LAB_NORMALS` |
| 放射線治療 Procedure emit | K001 / M001 / M001-2 / M001-3、`radiation_therapy_eligible` フラグの立ったがんの follow-up visit の ~40 % で発火 | `simulator/outpatient.py` (慢性 follow-up visit 内) |
| サイクル型化学療法 | Regimen library (FOLFOX q14d / CarboPem q21d / Trastuzumab q3w / LHRH q28d) → 正しいケイデンスの `chemo_visit` encounter + 投与 Procedure | `locale/shared/chemo_regimens.yaml` + `population/engine.py::_chemo_cycle_events` + `simulator/outpatient.py::_simulate_outpatient_visit` の chemo 分岐 |
| 経口 chemo (毎日 home meds) | Capecitabine / Tamoxifen / Anastrozole / Bicalutamide / Sorafenib / Lenvatinib / Osimertinib | `locale/shared/chronic_medications.yaml` (変更なし; 経口 chemo は毎日 home med として正しい) |

### 1.2 産科 — カバー要素

| 要素 | 内容 | 場所 |
|---|---|---|
| 妊娠慢性マーカー (Z34) | 女性 20-44、~18 % (JP 20-34) / ~19 % (US 20-34) | `locale/<c>/demographics.yaml` の `chronic_prevalence.Z34` (`sex: F`) |
| 過去分娩マーカー (Z37) | 産科既往のある女性の problem list に保持 | 同 YAML |
| 妊娠中サプリ Rx | 葉酸 + 鉄剤 | `locale/shared/chronic_medications.yaml` の Z34 ブロック |
| 母親側分娩入院 encounter | Z34 妊娠年毎に 1 件の IMP encounter、LOS JP 5d / US 2d、admission dx `O80`、discharge dx `Z37.0`、delivery Procedure | `locale/shared/perinatal.yaml` + `population/engine.py::_perinatal_delivery_events` + `simulator/perinatal.py` |
| 分娩 Procedure | JP: `K894` 分娩介助 / US: CPT `59400` routine obstetric care | `perinatal.yaml::procedure` |

### 1.3 明示的に未カバー (follow-up slice で対応)

- **新生児 Patient 生成** — 新生児自身の `Patient` リソース
  (`birthDate = 分娩日`、性別サンプル)。multi-patient linked-Encounter
  architecture (`Encounter.partOf` 母→児) を要する。
- **新生児 Encounter** (`admitSource = born`)。
- **Z38 (新生児側 birth outcome)** を児レコードに emit。
- **産褥 encounter** — 6 週間で 2-3 AMB visit。
- **時限付き妊娠 state** — 現在 Z34 は sim window 全期間 problem list に
  留まっている。実際の 40 週 active state ではない。follow-up で
  `disease_incidence` 型 event + snapshot-aware clamping に移行予定。
- **サイクル毎 chemo 薬 MedicationRequest / MedicationAdministration**
  — 現在の chemo_visit は Encounter + Procedure のみ emit。実際の
  cycle-day 薬剤投与記録は follow-up slice、経口 chemo は現行の
  chronic-daily MedicationRequest 経路を継続。
- **がん専用 Composition type** — LOINC 34133-9 (がん治療 note)。

---

## 2. 出力パイプライン (data flow)

```
locale/<c>/demographics.yaml
  chronic_prevalence.C50 / .C61 / .Z34 / ...
                      │
                      ▼
population/engine.py::generate_population()
  each PersonRecord gets chronic_conditions = ["C50", "Z34", ...]
                      │
                      ▼
population/engine.py::generate_healthcare_calendar()
  regimen assignment ありのがん患者:
     _chemo_cycle_events(person, year)  →  LifeEvent(chemo_visit, ...) × N cycles
  Z34 女性:
     _perinatal_delivery_events(person, year)  →  LifeEvent(delivery, ...)
                      │
                      ▼
simulator/engine.py::run_beta()
  event_type == "chemo_visit"       →  _simulate_outpatient_visit(...) with chemo spec
                                          → Encounter (AMB, oncology_infusion dept)
                                          → ProcedureRecord (chemotherapy_administration)
  event_type == "delivery"          →  simulate_delivery_encounter(...)
                                          → Encounter (IMP, obgyn dept, LOS 5/2d)
                                          → ProcedureRecord (delivery)
                                          → ClinicalDiagnosis(admission=O80, discharge=Z37.0)
                      │
                      ▼
CIFPatientRecord → cif/structural/patients/<enc>.json に書き出し
                      │
                      ▼
export-fhir → Encounter.ndjson / Procedure.ndjson / Condition.ndjson / ...
```

---

## 3. スキーマリファレンス

### 3.1 `chronic_prevalence` — flat form (単性別または性別非依存)

既存の形式。厳密に単性別のコード (BPH、salpingitis、妊娠、前立腺がん)
および性別非依存コードで使用:

```yaml
chronic_prevalence:
  N40:                # BPH、男性のみ
    sex: M            # 任意; "" (または省略) = 性別非依存
    "60-99": 0.20     # 年齢帯 → target marginal prevalence
  C61:                # 前立腺がん、男性のみ
    sex: M
    "60-69": 0.025
    "70-99": 0.055
  E11:                # T2DM、性別非依存
    "40-99": 0.10
```

共有の population master RNG からサンプリング。既存の患者はこの
形式では byte-identical を保つ。

### 3.2 `chronic_prevalence` — `by_sex` form (性別で非対称な帯域)

同一コードが男女で明確に異なる rate + age profile で emit する
ケースに導入 (現在は C50 乳がんのみ: 女性 peak 40-60 で 1.5-3 %、
男性 peak 60+ で ~0.02 %):

```yaml
chronic_prevalence:
  C50:
    by_sex:
      F:                      # primary sex — master RNG でサンプリング
        "40-59": 0.015
        "60-99": 0.030
      M:                      # augmentation — 患者毎 sub-RNG でサンプリング
        "60-99": 0.0002
```

**Parser の semantics** (`_parse_chronic_prevalence` @
`modules/population/engine.py`):
- **最初** の `by_sex` key が primary sex になる — flat-form の
  `sex` + `age_ranges` フィールドに畳み込まれ、flat form と同一の
  共有 master RNG からサンプリング。
- **残り** の `by_sex` key はすべて
  `ChronicConditionSpec.augment_sex_bands` に入り、
  `(patient_id, code)` 毎の sub-RNG (`chronic_augment_sex_seed` @
  `clinosim/seeding.py`) からサンプリング。
- Legacy flat-form の `sex` + bands を同一エントリ内で `by_sex` と
  混在させることは禁止 — parser がその shape で raise する。

**RNG-neutrality 契約:** 従来単性別だったコードに opposite-sex
augmentation を活性化 (男性 C50 は pre-fix で 0、post-fix で 男性
60+ の ~0.02 %) しても master RNG stream はシフトしない。
`augment_sex_bands` block の追加・調整は、活性化された ~0.02 % の
男性 60+ を除きすべての患者で byte-identical を保つ。

### 3.3 `chemo_regimens.yaml`

場所: `locale/shared/chemo_regimens.yaml`。regimen library と
per-cancer-code assignment table を宣言する。

```yaml
regimens:
  FOLFOX:                             # 大腸がん adjuvant
    cycle_interval_days: 14
    course_cycles: 12                 # ~6 か月 adjuvant
    cycle_orders:
      - {drug: "Oxaliplatin", drug_ja: "オキサリプラチン", dose: "85mg/m2", route: "IV"}
      - {drug: "Leucovorin",  drug_ja: "ロイコボリン",   dose: "400mg/m2", route: "IV"}
      - {drug: "5-FU",        drug_ja: "フルオロウラシル", dose: "400mg/m2 bolus + 2400mg/m2/46h", route: "IV"}
  CarboPem:                           # 肺がん adjuvant / advanced
    cycle_interval_days: 21
    course_cycles: 4
    cycle_orders: [...]
  Trastuzumab_q3w:                    # 乳がん HER2+ maintenance
    cycle_interval_days: 21
    course_cycles: 18                 # 1 年
    cycle_orders: [...]
  LHRH_q28d:                          # 前立腺 ADT depot
    cycle_interval_days: 28
    course_cycles: 24                 # 2 年継続
    cycle_orders: [...]

by_cancer:                            # per-code assignment probability
  C18: [{regimen: FOLFOX,          probability: 0.25}]
  C34: [{regimen: CarboPem,        probability: 0.20}]
  C50: [{regimen: Trastuzumab_q3w, probability: 0.15}]
  C61: [{regimen: LHRH_q28d,       probability: 0.35}]

procedure:                            # chemo_visit 毎に emit
  jp_code: "G003"                     # JP MHLW: 抗悪性腫瘍剤注入
  us_code: "96413"                    # US CPT: Chemotherapy administration
  duration_minutes: 60
```

**Assignment semantics:** 各慢性がん保有者に対しスケジューラは
`(patient_id, cancer_code)` 毎の sub-RNG (`chemotherapy_regimen_seed`)
を 1 回 roll する。累積確率でどの regimen が発火するか (または
発火しないか) を決定。残り mass = 「今年 active regimen 無し」 —
慢性保有者の大半は surveillance mode。

**Scheduler の挙動:** assign 時点で N cycle が `cycle_interval_days`
の間隔で発火する (最初の cycle window 内のランダム Day-1 オフセットから
開始)、`course_cycles` と `365 / cycle_interval_days` の両方で cap。

**Slice-1 emit scope:** 各 `chemo_visit` は 1 Encounter + 1 Procedure
(JP/US 請求コード付き) を生成する。`cycle_orders` エントリ毎の
`MedicationRequest` / `MedicationAdministration` は follow-up slice。

### 3.4 `perinatal.yaml`

場所: `locale/shared/perinatal.yaml`。分娩 encounter shape + procedure
code + scheduling window を宣言する。

```yaml
encounter:
  visit_reason:
    en: "Delivery (spontaneous vaginal delivery)"
    ja: "分娩 (自然分娩)"
  admission_diagnosis_code: "O80"       # 単胎自然分娩
  discharge_diagnosis_code: "Z37.0"     # 単胎生児出生、母親側
  length_of_stay_days:
    jp: 5                               # JSOG 正常分娩 LOS
    us: 2                               # US Medicare/HEDIS 48h stay
  department: "obgyn"                   # 無い場合 internal_medicine に rollup

procedure:
  jp_code: "K894"                       # 分娩介助
  us_code: "59400"                      # CPT routine obstetric care
  duration_minutes: 90

scheduling:
  delivery_month_range: [4, 10]         # Day-1 draw の月 bounds
```

**Slice-1 semantics:** Z34 妊娠年毎に 1 件の分娩 event を config window
内の scheduled 月に発火。多年妊娠 transition + 新生児 Patient 生成は
deferred な follow-up slice。

---

## 4. 慢性薬剤 carryforward semantics

患者が自宅で服用している薬は `PersonRecord.current_medications`
(Layer 1) で追跡し、`PatientProfile.current_medications` (Layer 2
cache) にミラーする。各入院退院後に
`simulator/helpers.py::_deactivate_to_layer1` が
`discharge_prescription.items` からこの list を再構築し、両 layer を
sync する。

acute short-course therapy (7 日抗生剤、5 日 steroid taper、14 日 PPI
eradication) が silently に慢性 home med にならないよう、
`_deactivate_to_layer1` は `duration_days` が acute range に入る item を
drop する:

```
drop if 0 < duration_days <= _ACUTE_COURSE_MAX_DAYS  (= 14)
```

**退院 Rx pipeline が honor する 2 つの重要なエッジケース:**
- **`duration_days == 0`** は disease-YAML の「長期 / 未指定」convention
  (`atrial_fibrillation_rvr.yaml` の Apixaban + Metoprolol_succinate
  の慢性 continuation block 参照)。0 は acute course として扱われず
  chronic として通す。guard は `d <= 14` ではなく `0 < d <= 14`。
- **`continue_at_discharge` category ブロック** (anticoagulation、statin、
  antihypertensive、antiplatelet) は lifelong secondary prevention 薬。
  これらの block から source される item は generic `discharge_oral`
  default 7 ではなく `duration_days = 28` (chronic-renewal length) を
  default とする。そうしないと acute filter が drop し、患者が入院間で
  silently に Apixaban / Warfarin / Atorvastatin を失う。

これらが合わさって A' Phase 1 invariant (Issue #440) を保証する:
**encounter N で新規開始された薬は encounter N+1 で home medication
order として現れる** — disease YAML が long-term として label している
限り。

---

## 5. 慢性薬剤モニタリング pipeline

`clinosim/modules/monitoring/` (Issue #757) が慢性薬剤を per-visit
モニタリング labs に mapping する。各慢性 follow-up 外来 visit で
`simulator/engine.py::run_beta` のディスパッチ block (
`elif event.event_type == "chronic_visit":` 分岐) が
`monitoring_labs_for_patient(patient.current_medications, ev_rng)` を
呼び、返された labs を visit の `visit_labs` にマージする。

現在の mapping (
`modules/monitoring/reference_data/med_lab_mapping.yaml` 内):

| 薬剤 | モニタリング lab | ケイデンス |
|---|---|---|
| Warfarin / Coumadin | PT_INR | 毎回 visit |
| Levothyroxine | TSH | ~q6mo |
| Metformin、Insulin | HbA1c | q3-6mo |
| Statin 系 (atorvastatin、rosuvastatin、simvastatin、pravastatin) | AST/ALT/CK | ~q6mo |
| ACE-i / ARB (lisinopril、losartan、valsartan、enalapril) | Creatinine + K | ~q6mo |
| Digoxin | Digoxin level | ~q6mo |
| Lithium | Lithium level | ~q3mo |
| 免疫抑制剤 (tacrolimus、cyclosporine、azathioprine、methotrexate) | Trough level + CBC + LFT | ~q3mo |

visit の primary reason に関わらず患者に付いてくる — warfarin 服用中の
DVT 患者で慢性 follow-up が高血圧のみでも INR チェックが行われる。
YAML driven; mapping 追加で Python は触らない。

---

## 6. Determinism + RNG-neutrality contracts

このサービスライン作業で追加された scheduler はすべて、per-patient
(または per-(patient, key)) 専用の deterministic sub-seed を使用し、
新規 emit の追加・調整・活性化が master population RNG stream に
cascade しないことを保証する:

| Emit | Sub-seed helper | Key |
|---|---|---|
| Chemo regimen 選択 + Day-1 offset | `chemotherapy_regimen_seed` | `(patient_id, cancer_code)` |
| 分娩 event の月 + 日 | `perinatal_delivery_seed` | `(patient_id, year)` |
| 男性 C50 augmentation サンプリング | `chronic_augment_sex_seed` | `(patient_id, code)` |
| 慢性薬剤選択 | `chronic_medication_seed` | `patient_id` |
| 退院 Rx categorical + Bernoulli | `discharge_prescription_seed` | `(patient_id, encounter_id)` |
| 放射線治療 per-visit trigger | ad-hoc `sha256("rt:<encounter_id>")` | `encounter_id` |

すべて `clinosim/seeding.py` に定義。AD-16 パターンの背景は
[`architecture/design-principles.md`](../architecture/design-principles.md) 参照。

---

## 7. どこで何を変えるか

| やりたいこと | 触る場所 |
|---|---|
| JP または US 慢性がん保有 cohort に部位を追加 | `locale/<c>/demographics.yaml` (`chronic_prevalence`) + `locale/shared/chronic_followup.yaml` (follow-up スケジュール) + `codes/data/icd-10*.yaml` (display) |
| Chemo regimen を追加 (または新がんに attach) | `locale/shared/chemo_regimens.yaml` — `regimens` 下に新規 + `by_cancer` に 1 行 |
| 分娩 LOS または window を変更 | `locale/shared/perinatal.yaml` |
| 現在単性別の慢性コードに opposite-sex augmentation を活性化 | `demographics.yaml` のエントリを `by_sex` form に変換; sex-conditional 請求コード用の sibling `code_mapping_diagnosis.yaml` も要チェック (§3.2 参照) |
| 慢性薬モニタリングルールを追加 | `modules/monitoring/reference_data/med_lab_mapping.yaml` — Python 変更不要 |
| Acute-course cutoff を変更 | `simulator/helpers.py::_ACUTE_COURSE_MAX_DAYS` (単一定数) |
| 特定の薬剤クラスを常時 carry forward させる | disease YAML の `continue_at_discharge` category block に追加; 退院 Rx builder がその `duration_days` の default を 28 にするので acute filter は発火しない |

---

## 8. Cross-references

- Event lifecycle を含む simulation walkthrough:
  [`../design-guides/data-generation-walkthrough.ja.md`](../design-guides/data-generation-walkthrough.ja.md)。
- 慢性疾患 schema authoring:
  [`../add-your-country.ja.md`](../add-your-country.ja.md) §Required YAML files。
- Diagnosis code coverage (US sex-conditional C50 mapping):
  [`../../AGENTS.md`](../../AGENTS.md) §"Diagnosis code coverage"。
- Module registry (monitoring、perinatal helpers、chemo_regimens loader):
  [`../../clinosim/modules/README.md`](../../clinosim/modules/README.md)。
