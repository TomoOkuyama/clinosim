# Oncology + Obstetric Service Lines

*Reference for the oncology (cancer) and obstetric (pregnancy /
delivery) service-line emission in clinosim. Self-contained: every
schema, code, and file path referenced here matches the current
repository state. Where the emission ships in incremental slices,
each slice's scope is stated explicitly along with the follow-up
that carries the rest.*

**Status:** current as of the v0.6.0 release-gate window. Sibling
Japanese doc: [`oncology-obstetric-service-lines.ja.md`](oncology-obstetric-service-lines.ja.md).

---

## 1. What is covered

Both service lines share the same emission-shape pattern:
1. Chronic condition prevalence (`chronic_prevalence` in
   `locale/<c>/demographics.yaml`) puts a marker on the patient.
2. A scheduler in `clinosim/modules/population/engine.py` translates
   the marker into `LifeEvent`s at the correct temporal cadence.
3. A dispatcher in `clinosim/simulator/engine.py` routes each event
   to a builder that emits the resources (Encounter + Condition +
   Procedure + Medication…).

### 1.1 Oncology — covered elements

| Element | Coverage | Where |
|---|---|---|
| Cancer chronic markers (10 sites) | C15 / C16 / C18 / C22 / C25 / C34 / C50 / C61 / C67 / C71 | `locale/jp/demographics.yaml` + `locale/us/demographics.yaml` |
| Male breast cancer (~1 % of C50) | Female primary + male augmentation | `chronic_prevalence.C50.by_sex` (see §3.2) |
| Cancer follow-up outpatient visits | Quarterly, per-cancer visit reason + labs (tumor markers + basic panel) + optional prescription renewal | `locale/shared/chronic_followup.yaml` |
| Tumor marker labs | CEA / CA19-9 / AFP / PIVKA-II / CA15-3 / PSA — reference ranges + baseline normals | `locale/<c>/reference_range_lab.yaml` + `modules/observation/engine.py::BASELINE_LAB_NORMALS` |
| Radiation-therapy Procedure emit | K001 / M001 / M001-2 / M001-3 fired at ~40 % of follow-up visits (for `radiation_therapy_eligible` cancer codes) | `simulator/outpatient.py` (per chronic-followup visit) |
| Cycle-based chemotherapy | Regimen library (FOLFOX q14d / CarboPem q21d / Trastuzumab q3w / LHRH q28d) → `chemo_visit` encounters at correct cadence + delivery Procedure | `locale/shared/chemo_regimens.yaml` + `population/engine.py::_chemo_cycle_events` + `simulator/outpatient.py::_simulate_outpatient_visit` chemo branch |
| Per-cycle chemo drug orders | Each `chemo_visit` emits one `MedicationRequest` + one `MedicationAdministration` per drug on the regimen's `cycle_orders` list (matching `order_id`) | `simulator/outpatient.py` chemo branch (Order emit) |
| Oral chemo (daily home meds) | Capecitabine / Tamoxifen / Anastrozole / Bicalutamide / Sorafenib / Lenvatinib / Osimertinib | `locale/shared/chronic_medications.yaml` (unchanged; oral chemo IS a daily home med) |

### 1.2 Obstetric — covered elements

| Element | Coverage | Where |
|---|---|---|
| Pregnancy chronic marker (Z34) | Female 20-44, ~18 % (JP 20-34) / ~19 % (US 20-34) | `chronic_prevalence.Z34` in `locale/<c>/demographics.yaml` (`sex: F`) |
| Past-birth chronic marker (Z37) | Carried on the problem list of women with obstetric history | Same YAML |
| Prenatal supplement Rx | Folic acid + iron | `locale/shared/chronic_medications.yaml` Z34 block |
| Mother-side delivery inpatient encounter | One IMP encounter per Z34 pregnancy-year, LOS 5d JP / 2d US, admission dx `O80`, discharge dx `Z37.0`, delivery Procedure | `locale/shared/perinatal.yaml` + `population/engine.py::_perinatal_delivery_events` + `simulator/perinatal.py` |
| Delivery Procedure | JP: `K894` 分娩介助 / US: CPT `59400` routine obstetric care | `perinatal.yaml::procedure` |
| Newborn `Patient` chain | Baby id `<mother>-BABY`, household inherited, sex per-mother sub-RNG, birthDate = delivery date | `simulator/perinatal.py` (session 94) |
| Newborn Encounter | IMP, `admit_source = born` (new `AdmitSource.BORN` enum member) + `admit_source_encounter_id` → FHIR `Encounter.partOf` on the newborn side | `simulator/perinatal.py` + `types/encounter.py::AdmitSource.BORN` |
| Z38.0 on newborn | Newborn discharge dx | `simulator/perinatal.py` |
| Postpartum encounters × 2 | ~1 wk + ~4 wk chronic_visit at disease_id `Z39` (encounter for maternal postpartum care) | `locale/shared/chronic_followup.yaml::Z39` |
| Newborn perinatal conditions | P59.9 jaundice ~20 %, P07.3 preterm ~7 % (→ conditional P22.0 RDS ~35 %), L22 diaper dermatitis ~30 %, L20.9 atopic dermatitis ~15 % | `simulator/perinatal.py` (per-newborn sub-RNG) |
| Abortion outcome (age-gated) | Spontaneous O03.9 / induced O04.5 outpatient day-surgery. Age-band probability 15-19: 40 % → 35-44: 7 %. When fired, delivery + newborn chain are skipped for the Z34-year | `locale/shared/perinatal.yaml::abortion` + `population/engine.py::_abortion_outcome_events` |

### 1.3 Explicitly NOT yet covered (follow-up slices)

- **Time-boxed pregnancy state** — Z34 currently sits on the
  problem list for the full sim window rather than a real 40-week
  active state. Follow-up will move it to a `disease_incidence`-style
  event with snapshot-aware clamping. Downgraded from "must" to
  "would be nicer" once the delivery + postpartum + newborn chain
  landed in session 94 — the temporal signature the original scope
  worried about is now supplied.
- **Oncology-specific Composition type** — LOINC 34133-9 for
  cancer treatment notes.
- **Cross-year chemo cycle continuity** — cycles are scheduled fresh
  per calendar year. A patient starting FOLFOX in November restarts
  from cycle 1 in January rather than continuing.
- **Cesarean-section share** — currently every delivery emits as O80
  spontaneous vaginal. Real JP rate is ~20 % C-section (O82); a
  per-mother sub-RNG split is a natural follow-up.

---

## 2. Emission pipeline (data flow)

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
  for each person with a cancer code + regimen assignment:
     _chemo_cycle_events(person, year)  →  LifeEvent(chemo_visit, ...) × N cycles
  for each Z34 woman:
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
CIFPatientRecord written to cif/structural/patients/<enc>.json
                      │
                      ▼
export-fhir → Encounter.ndjson / Procedure.ndjson / Condition.ndjson / ...
```

---

## 3. Schema reference

### 3.1 `chronic_prevalence` — flat form (single-sex or sex-neutral)

The pre-existing form. Used for strictly single-sex codes (BPH,
salpingitis, pregnancy, prostate cancer) and sex-neutral codes:

```yaml
chronic_prevalence:
  N40:                # BPH, male-only
    sex: M            # optional; "" (or absent) = sex-neutral
    "60-99": 0.20     # age-band → target marginal prevalence
  C61:                # Prostate cancer, male-only
    sex: M
    "60-69": 0.025
    "70-99": 0.055
  E11:                # T2DM, sex-neutral
    "40-99": 0.10
```

Sampled from the shared population master RNG. Pre-existing
patients are byte-identical when this form is used.

### 3.2 `chronic_prevalence` — `by_sex` form (asymmetric per-sex bands)

Introduced when the code emits at meaningfully different rates *and*
age profiles for males vs females (currently only C50 breast cancer:
female peak 40-60 at 1.5-3 %, male peak 60+ at ~0.02 %):

```yaml
chronic_prevalence:
  C50:
    by_sex:
      F:                      # primary sex — sampled on master RNG
        "40-59": 0.015
        "60-99": 0.030
      M:                      # augmentation — sampled on per-patient sub-RNG
        "60-99": 0.0002
```

**Parser semantics** (`_parse_chronic_prevalence` in
`modules/population/engine.py`):
- The **first** `by_sex` key becomes the primary sex — folded into
  the flat-form `sex` + `age_ranges` fields and sampled from the
  shared master RNG identically to the flat form.
- Every **remaining** `by_sex` key becomes an entry in
  `ChronicConditionSpec.augment_sex_bands` — sampled from a
  per-`(patient_id, code)` sub-RNG (`chronic_augment_sex_seed` in
  `clinosim/seeding.py`).
- Legacy flat-form `sex` + bands MUST NOT be mixed with `by_sex` in
  the same entry; the parser raises on that shape.

**RNG-neutrality contract:** activating an opposite-sex augmentation
(male C50 was 0 pre-fix, ~0.02 % of male 60+ post-fix) does NOT
shift the master RNG stream. Adding / tuning an `augment_sex_bands`
block preserves byte-identity for every patient except the ~0.02 %
of male 60+ that gain the condition.

### 3.3 `chemo_regimens.yaml`

Located at `locale/shared/chemo_regimens.yaml`. Declares the
regimen library and the per-cancer-code assignment table.

```yaml
regimens:
  FOLFOX:                             # colorectal adjuvant
    cycle_interval_days: 14
    course_cycles: 12                 # ~6 months adjuvant
    cycle_orders:
      - {drug: "Oxaliplatin", drug_ja: "オキサリプラチン", dose: "85mg/m2", route: "IV"}
      - {drug: "Leucovorin",  drug_ja: "ロイコボリン",   dose: "400mg/m2", route: "IV"}
      - {drug: "5-FU",        drug_ja: "フルオロウラシル", dose: "400mg/m2 bolus + 2400mg/m2/46h", route: "IV"}
  CarboPem:                           # lung adjuvant / advanced
    cycle_interval_days: 21
    course_cycles: 4
    cycle_orders: [...]
  Trastuzumab_q3w:                    # breast HER2+ maintenance
    cycle_interval_days: 21
    course_cycles: 18                 # 1 year
    cycle_orders: [...]
  LHRH_q28d:                          # prostate ADT depot
    cycle_interval_days: 28
    course_cycles: 24                 # 2 years continuous
    cycle_orders: [...]

by_cancer:                            # per-code assignment probability
  C18: [{regimen: FOLFOX,          probability: 0.25}]
  C34: [{regimen: CarboPem,        probability: 0.20}]
  C50: [{regimen: Trastuzumab_q3w, probability: 0.15}]
  C61: [{regimen: LHRH_q28d,       probability: 0.35}]

procedure:                            # emitted per chemo_visit
  jp_code: "G003"                     # JP MHLW: 抗悪性腫瘍剤注入
  us_code: "96413"                    # US CPT: Chemotherapy administration
  duration_minutes: 60
```

**Assignment semantics:** for each chronic-cancer carrier the
scheduler rolls a single per-`(patient_id, cancer_code)` sub-RNG
(`chemotherapy_regimen_seed`). Cumulative probability decides which
regimen fires (or none). Residual mass = "no active regimen this
year" — most chronic carriers are in surveillance mode.

**Scheduler behaviour:** on assignment, N cycles fire at
`cycle_interval_days` starting from a random Day-1 offset within
the first cycle window, capped by both `course_cycles` and
`365 / cycle_interval_days`.

**Slice-1 emit scope:** each `chemo_visit` produces one Encounter
+ one Procedure (with the JP/US billing code). Per-cycle drug
`MedicationRequest` / `MedicationAdministration` for the
`cycle_orders` entries is deferred to a follow-up slice.

### 3.4 `perinatal.yaml`

Located at `locale/shared/perinatal.yaml`. Declares delivery
encounter shape + procedure code + scheduling window.

```yaml
encounter:
  visit_reason:
    en: "Delivery (spontaneous vaginal delivery)"
    ja: "分娩 (自然分娩)"
  admission_diagnosis_code: "O80"       # single spontaneous delivery
  discharge_diagnosis_code: "Z37.0"     # single liveborn, mother-side
  length_of_stay_days:
    jp: 5                               # JSOG normal delivery LOS
    us: 2                               # US Medicare/HEDIS 48h stay
  department: "obgyn"                   # falls back to internal_medicine

procedure:
  jp_code: "K894"                       # 分娩介助
  us_code: "59400"                      # CPT routine obstetric care
  duration_minutes: 90

scheduling:
  delivery_month_range: [4, 10]         # month bounds for Day-1 draw
```

**Slice-1 semantics:** one delivery event per Z34 pregnancy-year at
a scheduled month within the config window. Multi-year pregnancy
transitions + newborn Patient generation are the deferred
follow-up slice.

---

## 4. Chronic-medication carryforward semantics

Drugs a patient takes at home are tracked on
`PersonRecord.current_medications` (Layer 1) and mirrored to
`PatientProfile.current_medications` (Layer 2 cache). After every
inpatient discharge, `simulator/helpers.py::_deactivate_to_layer1`
rebuilds this list from `discharge_prescription.items` and syncs
both layers.

To keep acute short-course therapy (7-day antibiotic, 5-day steroid
taper, 14-day PPI eradication) from silently becoming a chronic
home med, `_deactivate_to_layer1` drops any item whose
`duration_days` is in the acute range:

```
drop if 0 < duration_days <= _ACUTE_COURSE_MAX_DAYS  (= 14)
```

**Two key edge cases** the discharge-Rx pipeline honours:
- **`duration_days == 0`** is the disease-YAML convention for
  "long-term / unspecified" (e.g. `atrial_fibrillation_rvr.yaml`
  Apixaban + Metoprolol_succinate on the chronic-continuation
  block). 0 is NOT treated as an acute course — it falls through
  as chronic. The guard is `0 < d <= 14`, not `d <= 14`.
- **`continue_at_discharge` category blocks** (anticoagulation,
  statin, antihypertensive, antiplatelet) are lifelong secondary-
  prevention meds. Items sourced from these blocks default to
  `duration_days = 28` (chronic-renewal length) rather than the
  generic `discharge_oral` default of 7. Otherwise the acute
  filter would drop them and the patient would silently lose
  Apixaban / Warfarin / Atorvastatin between admissions.

Together these guarantee the A' Phase 1 invariant (Issue #440):
**a drug newly started on encounter N appears as a home medication
order on encounter N+1** — as long as the disease-YAML labels it as
long-term.

---

## 5. Chronic-medication monitoring pipeline

`clinosim/modules/monitoring/` (Issue #757) maps chronic
medications to per-visit monitoring labs. On every chronic-followup
outpatient visit, the dispatch block in
`simulator/engine.py::run_beta` (the `elif event.event_type ==
"chronic_visit":` branch) calls
`monitoring_labs_for_patient(patient.current_medications, ev_rng)`
and merges the returned labs into the visit's `visit_labs`.

Current mappings (in `modules/monitoring/reference_data/med_lab_mapping.yaml`):

| Medication | Monitoring lab | Cadence |
|---|---|---|
| Warfarin / Coumadin | PT_INR | every visit |
| Levothyroxine | TSH | ~q6mo |
| Metformin, Insulin | HbA1c | q3-6mo |
| Statins (atorvastatin, rosuvastatin, simvastatin, pravastatin) | AST/ALT/CK | ~q6mo |
| ACE-i / ARB (lisinopril, losartan, valsartan, enalapril) | Creatinine + K | ~q6mo |
| Digoxin | Digoxin level | ~q6mo |
| Lithium | Lithium level | ~q3mo |
| Immunosuppressants (tacrolimus, cyclosporine, azathioprine, methotrexate) | Trough level + CBC + LFT | ~q3mo |

Follows the patient regardless of the visit's primary reason — a
warfarin-treated DVT patient whose only chronic follow-up is for
hypertension still gets INR checks. Data-driven via the YAML;
adding a mapping does not touch Python.

---

## 6. Determinism + RNG-neutrality contracts

Every scheduler added in this service-line work uses a dedicated
per-patient (or per-(patient, key)) deterministic sub-seed so that
adding, tuning, or activating a new emission does not cascade the
master population RNG stream:

| Emission | Sub-seed helper | Key |
|---|---|---|
| Chemo regimen selection + Day-1 offset | `chemotherapy_regimen_seed` | `(patient_id, cancer_code)` |
| Perinatal delivery month + day | `perinatal_delivery_seed` | `(patient_id, year)` |
| Male C50 augmentation sampling | `chronic_augment_sex_seed` | `(patient_id, code)` |
| Chronic-medication selection | `chronic_medication_seed` | `patient_id` |
| Discharge-Rx categorical + Bernoulli | `discharge_prescription_seed` | `(patient_id, encounter_id)` |
| Radiation-therapy per-visit trigger | ad-hoc `sha256("rt:<encounter_id>")` | `encounter_id` |

All live in `clinosim/seeding.py`. See
[`architecture/design-principles.md`](../architecture/design-principles.md)
for the AD-16 pattern that motivates these.

---

## 7. Where to change what

| You want to… | Touch |
|---|---|
| Add a cancer site to the JP or US chronic-carrier cohort | `locale/<c>/demographics.yaml` (`chronic_prevalence`) + `locale/shared/chronic_followup.yaml` (follow-up schedule) + `codes/data/icd-10*.yaml` (display) |
| Add a chemo regimen (or attach one to a new cancer) | `locale/shared/chemo_regimens.yaml` — new entry under `regimens` + a row in `by_cancer` |
| Change delivery LOS or window | `locale/shared/perinatal.yaml` |
| Activate an opposite-sex augmentation on a currently-single-sex chronic code | Convert the entry to `by_sex` form in `demographics.yaml`; check sibling `code_mapping_diagnosis.yaml` for sex-conditional billing codes (see §3.2) |
| Add a chronic-med monitoring rule | `modules/monitoring/reference_data/med_lab_mapping.yaml` — no Python change |
| Change the acute-course cutoff | `simulator/helpers.py::_ACUTE_COURSE_MAX_DAYS` (single constant) |
| Force a specific drug class to always carry forward | Add to a disease YAML's `continue_at_discharge` category block; the discharge-Rx builder defaults its `duration_days` to 28 so the acute filter never fires |

---

## 8. Cross-references

- Simulation walkthrough with the wider event lifecycle:
  [`../design-guides/data-generation-walkthrough.md`](../design-guides/data-generation-walkthrough.md).
- Chronic-condition schema authoring:
  [`../add-your-country.md`](../add-your-country.md) §Required YAML files.
- Diagnosis code coverage (US sex-conditional C50 mapping):
  [`../../AGENTS.md`](../../AGENTS.md) §"Diagnosis code coverage".
- Module registry (monitoring, perinatal helpers,
  chemo_regimens loader):
  [`../../clinosim/modules/README.md`](../../clinosim/modules/README.md).
