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
| サイクル毎 chemo 薬 order | 各 `chemo_visit` で regimen の `cycle_orders` に列挙された薬剤ごとに `MedicationRequest` + `MedicationAdministration` を 1 件ずつ emit (`order_id` 一致) | `simulator/outpatient.py` chemo 分岐 (Order emit) |
| 経口 chemo (毎日 home meds) | Capecitabine / Tamoxifen / Anastrozole / Bicalutamide / Sorafenib / Lenvatinib / Osimertinib | `locale/shared/chronic_medications.yaml` (変更なし; 経口 chemo は毎日 home med として正しい) |

### 1.2 産科 — カバー要素

| 要素 | 内容 | 場所 |
|---|---|---|
| 時限付き妊娠 lifecycle state (META #957 Incr 1) | 15-49 歳女性に対して MHLW 2022 (JP) / CDC NVSR 2022 (US) の年齢帯別出生率で年次 conception Bernoulli。受精すると `TemporalStatePeriod(state_type="pregnancy")` を `PersonRecord.state_periods` に open (metadata: `{lmp, edd, planned_delivery_date}`)、planned_delivery_date を含む年で close (`outcome="delivered"`)、または abortion date で close (`outcome="aborted"`)。 | `perinatal.yaml::lifecycle.annual_conception_rate` + `population/engine.py::_pregnancy_lifecycle_events` + `types/patient.py::TemporalStatePeriod` |
| 過去分娩 Z37 problem-list-item | delivered pregnancy period 毎に 1 件、onsetDateTime = 分娩日。生物学的整合 — 複数出産で複数 Z37。FHIR emit 時に `state_history("pregnancy")` から導出、**Incr 1 前の chronic-sample proxy を置換**。 | `modules/output/fhir_r4/conditions/conditions.py::_build_conditions` (past-pregnancies adapter) |
| 妊娠中サプリ Rx | 葉酸 + 鉄剤。pregnancy 履歴のある patient にのみ home medication として付与。emit path は不変 (`chronic_medications.yaml::Z34`)、gate が `chronic_conditions` から `state_periods` へ移動 — activator で仮想 Z34 `ChronicCondition` を med-derivation 入力に注入。 | `locale/shared/chronic_medications.yaml` の Z34 block + `modules/patient/activator.py` (state 起点 hook) |
| 妊婦健診 encounter | AMB encounter、妊娠週 12/24/36 (Incr 1 は簡易版、q4w/q2w/q1w cadence は Incr 1.5)、`disease_id="Z34"`、`_CHRONIC_DISEASE_SPECIALTY` で obgyn に routing。 | `perinatal.yaml::lifecycle.prenatal_visit_gestational_weeks` + `population/engine.py::_pregnancy_lifecycle_events` |
| 母親側分娩入院 encounter | delivered pregnancy period 毎に 1 件 IMP encounter、planned delivery date (EDD ± 7 d jitter) を含む年で発火。LOS JP 5 d / US 2 d、admission dx `O80`、discharge dx `Z37.0`、delivery Procedure。 | `locale/shared/perinatal.yaml::encounter` + `population/engine.py::_pregnancy_lifecycle_events` + `simulator/perinatal.py` |
| 分娩 Procedure | JP: `K894` 分娩介助 / US: CPT `59400` routine obstetric care | `perinatal.yaml::procedure` |
| 新生児 `Patient` チェーン | Baby id `<mother>-BABY`、世帯継承、性別は per-mother sub-RNG、birthDate = 分娩日 | `simulator/perinatal.py` (session 94) |
| 新生児 Encounter | IMP、`admit_source = born` (新規 `AdmitSource.BORN` enum member) + `admit_source_encounter_id` → 新生児側 FHIR `Encounter.partOf` | `simulator/perinatal.py` + `types/encounter.py::AdmitSource.BORN` |
| 新生児側 Z38.0 | 新生児 discharge dx | `simulator/perinatal.py` |
| 産褥 encounter × 2 | 分娩日 + 7 d / + 28 d、`chronic_visit` with `disease_id="Z39"`、obgyn routing。12 月分娩の場合は Dec 31 に year-boundary clamp。 | `perinatal.yaml::lifecycle.postpartum_visit_offsets_days` + `population/engine.py::_pregnancy_lifecycle_events` |
| 新生児 perinatal condition | P59.9 黄疸 ~20 %、P07.3 早産 ~7 % (→ 条件付き P22.0 RDS ~35 %)、L22 おむつかぶれ ~30 %、L20.9 アトピー ~15 % | `simulator/perinatal.py` (per-newborn sub-RNG) |
| 中絶 outcome (age-gate) | 自然 O03.9 / 人工 O04.5 外来日帰り手術。年齢帯別確率 15-19: 40 % → 35-44: 7 %。発火時は妊娠週 ~10 (LMP+70±14 d) で period を `outcome="aborted"` close、delivery + newborn chain skip。 | `locale/shared/perinatal.yaml::abortion` + `population/engine.py::_pregnancy_lifecycle_events` (abortion 分岐) |

### 1.3 明示的に未カバー (Incr 1.5 以降)

- **妊婦健診の per-encounter サプリ MedicationRequest** — Incr 1 は
  葉酸 + 鉄剤を activator hook 経由で `current_medications` に永続
  attach (妊娠履歴 non-empty を gate)。妊婦健診 encounter 単位で
  MedicationRequest を emit する方がクリーン。Incr 1.5 で対応。
- **Trimester 別 Z34.0X emit** — 現状すべての妊婦健診が
  `Z34` (trimester 未指定) を emit。妊娠週帯で
  `Z34.00 / Z34.01 / Z34.02 / Z34.03` に細分化するのは yaml + emit
  の小改修、Incr 1.5 で対応。
- **完全な妊婦健診 cadence** — Incr 1 は 12 / 24 / 36 週の 3 回
  簡易版。実臨床は 28 週まで q4w、36 週まで q2w、以降 q1w — Incr 1.5。
- **妊娠中合併症** — O24 妊娠糖尿病、O14 妊娠高血圧、O99 妊娠に
  合併する既存疾患。`state_periods` に妊娠中 comorbidity hook を
  必要とする。
- **多年 TFR calibration** — Incr 1 は LMP を暦年内 uniform で
  seed するため、単年 sim では delivery が過少 emit (前年 conception
  分の cross-year pregnancy が欠落するため「実 annual」の ~25 %
  程度)。多年 sim で steady-state 収束。population 生成時の
  pre-warm pass は Incr 1.5。
- **死産 / 早産 outcome variation** — 現状すべての非中絶妊娠は
  正期産の生児 delivery。
- **帝王切開シェア** — 現状全 delivery が O80 自然経腟分娩として
  emit。実際の JP 帝王切開率は ~20 % (O82)。
- **がん専用 Composition type** — LOINC 34133-9 (がん治療 note)。
- **年跨ぎ chemo cycle continuity** — 現在 cycle は暦年ごとに fresh
  scheduling。11 月 FOLFOX 開始患者は 1 月に cycle 1 から再開する。

---

## 2. 出力パイプライン (data flow)

```
locale/<c>/demographics.yaml                 locale/shared/perinatal.yaml
  chronic_prevalence.C50 / .C61 / ...           lifecycle.annual_conception_rate
  (Z34 / Z37 は no-op-consume、append しない)   lifecycle.gestation_days
                      │                         lifecycle.prenatal_visit_gestational_weeks
                      ▼                         lifecycle.postpartum_visit_offsets_days
population/engine.py::generate_population()                        │
  each PersonRecord gets chronic_conditions = ["C50", ...]         │
  person.state_periods = []  (生成時は空)                          │
                      │                                            │
                      ▼                                            │
population/engine.py::generate_healthcare_calendar()               │
  active pregnancy なしの 15-49 女性:                              │
     _pregnancy_lifecycle_events(person, year, country) ◄──────────┤
        rng.random() < annual_conception_rate(country, age)?       │
          → TemporalStatePeriod(state_type="pregnancy",             │
                lmp=..., edd=lmp+280, planned_delivery_date=...) open
          → person.state_periods に append                          │
     active pregnancy period ごと:                                  │
        → LifeEvent(chronic_visit, condition_type="prenatal_visit", disease_id="Z34") × 3
        planned_delivery が当該年:
          → LifeEvent(delivery, disease_id="Z34")
          → LifeEvent(chronic_visit, condition_type="postpartum", disease_id="Z39") × 2
          → period を outcome="delivered", end_date=delivery_date で close
  regimen assignment ありのがん患者:
     _chemo_cycle_events(person, year)  →  LifeEvent(chemo_visit, ...) × N cycles
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
                                          → 新生児 Patient chain
  event_type == "abortion"          →  simulate_abortion_encounter(...) (period 既に close)
  event_type == "chronic_visit" with condition_type == "prenatal_visit" or "postpartum"
                                    →  outpatient dispatch 経由、
                                        specialty = obgyn (via _CHRONIC_DISEASE_SPECIALTY)
                      │
                      ▼
activator.py::activate_patient() [patient_cache に per-person]
  PatientProfile.state_periods = person.state_periods の shallow copy
  state_history("pregnancy") が non-empty:
     current_meds に葉酸 + 鉄剤 (med-derivation 入力に仮想 Z34 経由)
                      │
                      ▼
CIFPatientRecord → cif/structural/patients/<enc>.json に書き出し
  record["patient"]["state_periods"] に妊娠履歴が carry
                      │
                      ▼
export-fhir → conditions/conditions.py::_build_conditions
  chronic loop: chronic_conditions を iterate (Z34 なし → Z34 problem-list-item も無し)
  past-pregnancies adapter: state_periods を outcome="delivered" で filter
                            → delivered period 毎に Z37 problem-list-item を emit
                              (onsetDateTime = end_date)
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
code + abortion outcome テーブル + **pregnancy lifecycle block**
(META #957 Incr 1) を宣言する。

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

# Legacy block — abortion 分岐の date placement で backward-compat のため
# 保持。Incr 1 lifecycle generator はこれを参照せず、delivery date は
# EDD ± jitter から導出する。
scheduling:
  delivery_month_range: [4, 10]

# META #957 Incr 1: 完全な妊娠 lifecycle (年次 conception → LMP/EDD →
# 妊婦健診 / 分娩 / 産褥 → close)。MHLW 2022 (JP) / CDC NVSR 2022 (US)
# の年齢帯別出生率で per-woman-per-year Bernoulli。
lifecycle:
  annual_conception_rate:
    jp:
      "15-19": 0.003
      "20-24": 0.023
      "25-29": 0.075
      "30-34": 0.099
      "35-39": 0.051
      "40-44": 0.008
      "45-49": 0.0002
    us:
      "15-19": 0.014
      "20-24": 0.059
      "25-29": 0.096
      "30-34": 0.097
      "35-39": 0.056
      "40-44": 0.012
      "45-49": 0.001
  gestation_days: 280                          # Naegele の法則
  delivery_jitter_days: [-7, 7]
  prenatal_visit_gestational_weeks: [12, 24, 36]
  postpartum_visit_offsets_days: [7, 28]
```

**Incr 1 semantics:** 各 sim 年で generator は per-`(person_id, year)`
sub-RNG (`perinatal_delivery_seed`) を roll する。女性が 15-49 で
active pregnancy period が無ければ年次 conception Bernoulli を roll。
hit したら `TemporalStatePeriod(state_type="pregnancy")` を open (LMP
は年内 uniform、EDD = LMP + 280 d、jitter 付きの planned delivery
date)。cross-year 妊娠 (LMP が年 N 後半、EDD が年 N+1) は
`person.state_periods` 経由で carry — 年 N+1 の call は
`get_active_state` short-circuit で Bernoulli を skip する。planned
delivery が当該年に到達すると、generator は delivery + postpartum
event を emit し、period を `outcome="delivered"` で close する。
中絶 outcome は妊娠週 ~10 (LMP + 70 ± 14 d) で period を
`outcome="aborted"` close し外来 1 件を emit する。

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
| 妊娠 lifecycle (受精 Bernoulli + LMP + jitter) | `perinatal_delivery_seed` | `(patient_id, year)` |
| 中絶 outcome (自然 / 人工 split) | `_abortion_outcome_sub_seed` | `(mother_id, year)` |
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
| 分娩 LOS または delivery Procedure code を変更 | `locale/shared/perinatal.yaml::encounter` / `::procedure` |
| 年齢帯別 conception rate を調整 | `locale/shared/perinatal.yaml::lifecycle.annual_conception_rate.{jp,us}` |
| 妊婦健診の cadence / 産褥 offset を変更 | `locale/shared/perinatal.yaml::lifecycle.prenatal_visit_gestational_weeks` / `::postpartum_visit_offsets_days` |
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
