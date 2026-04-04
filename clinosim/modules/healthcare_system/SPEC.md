# healthcare_system — Healthcare System Configuration

## Purpose
Provide country-specific parameters that influence clinical behavior across all other modules. This module has no dependencies — it is a pure configuration provider. All parameters are backed by real-world data sources where possible.

## Inputs
- Country selection: `"JP"` or `"US"`
- Optional overrides for any parameter

## Outputs
- `HealthcareSystemConfig`: Complete parameter set consumed by all other modules

## Dependencies
- None (leaf dependency — all other modules may depend on this)

## Internal Design

The module is implemented as a **YAML-based configuration system** with one file per country. At initialization, the country file is loaded and any user overrides are applied.

```
modules/healthcare_system/
├── SPEC.md
├── configs/
│   ├── japan.yaml
│   └── us.yaml
└── (implementation files)
```

---

## Confirmed Specifications

### 1. Demographics Reference Data

Parameters used by the `population` module to generate realistic catchment area populations.

#### 1.1 Age-sex distribution

| Parameter | Japan | US | Source |
|---|---|---|---|
| `population_pyramid` | Reference to 5-year age bands, M/F counts | Same format | JP: e-Stat 国勢調査 2020; US: Census Bureau ACS 2020 |
| `median_age` | 48.4 | 38.1 | UN World Population Prospects 2022 |
| `pct_age_65_plus` | 29.1% | 16.8% | Same |
| `pct_age_75_plus` | 15.5% | 7.5% | Same |

#### 1.2 Blood type distribution

| Type | Japan | US (overall) | Source |
|---|---|---|---|
| A | 40% | 36% | JP: Japanese Red Cross; US: Stanford Blood Center |
| O | 30% | 44% | |
| B | 20% | 10% | |
| AB | 10% | 4% | |
| Rh+ | 99.7% | 84% | |

#### 1.3 Household composition

| Type | Japan (%) | US (%) | Source |
|---|---|---|---|
| Single person (< 65) | 18% | 28% | JP: 国民生活基礎調査 2022; US: ACS 2020 |
| Single person (65+) | 15% | 11% | |
| Couple only (no children) | 12% | 25% | |
| Couple + children | 25% | 20% | |
| Single parent + children | 7% | 12% | |
| Three-generation | 8% | 4% | |
| Elderly couple (both 65+) | 12% | — (included in couple) | |
| Other | 3% | — | |

#### 1.4 Chronic disease prevalence (age-standardized)

| Condition | Japan prevalence | US prevalence | Source |
|---|---|---|---|
| Hypertension | 43% (age 40+) | 47% (age 18+) | JP: 患者調査; US: NHANES |
| Diabetes (Type 2) | 12% (age 40+) | 14% (age 18+) | JP: 国民健康・栄養調査; US: CDC |
| Dyslipidemia | 30% (age 40+) | 38% (age 20+) | |
| CKD (stage 3+) | 13% (age 20+) | 15% (age 20+) | |
| COPD | 8.6% (age 40+) | 6.4% (age 18+) | JP: NICE study; US: BRFSS |
| Heart failure | 1–2% (overall) | 2.4% (age 20+) | |
| Atrial fibrillation | 1.4% (overall) | 2.3% (overall) | |
| Osteoporosis | 15% (F age 50+) | 12.6% (F age 50+) | |

Comorbidity co-occurrence multipliers (conditional probability):
- HT → DM: ×2.0
- HT → Dyslipidemia: ×1.8
- DM → CKD: ×2.5
- DM → CVD: ×2.0
- CKD → HF: ×3.0
- Smoking → COPD: ×5.0
- Obesity → DM: ×3.0
- Obesity → HT: ×2.5

#### 1.5 Mortality rates

| Parameter | Source |
|---|---|
| Age/sex-specific all-cause mortality | JP: 人口動態統計; US: CDC WONDER |
| Disease-specific mortality adjustment | Applied per chronic condition |

#### 1.6 Fertility & reproduction

| Parameter | Japan | US | Source |
|---|---|---|---|
| Total fertility rate | 1.20 (2023) | 1.62 (2023) | JP: 厚生労働省; US: CDC |
| Mean maternal age at first birth | 30.9 | 27.3 | National statistics |
| Age-specific fertility rate | By 5-year band, 15–49 | By 5-year band, 15–49 | JP: 人口動態統計; US: NVSS |
| Induced abortion rate (per 1000 women 15–49) | 6.3 | 11.4 | JP: 衛生行政報告例; US: Guttmacher |
| Cesarean section rate | 20–25% | 32% | National statistics |
| Preterm birth rate (< 37 weeks) | 5.7% | 10.5% | JP: 人口動態統計; US: CDC |
| Multiple pregnancy rate | 1.0% | 3.4% | Includes ART-related; JP: lower ART multiple rate due to regulation |
| Gestational diabetes prevalence | 5–8% | 6–9% | Published screening data |
| Preeclampsia prevalence | 3–5% | 3–5% | Literature |

Pregnancy-related healthcare patterns:
- **JP**: Maternity notebook (母子健康手帳) issued by municipality at pregnancy confirmation. 14 subsidized prenatal visits. Delivery cost ~¥500,000, partially subsidized. Postpartum: 1-month checkup standard.
- **US**: Prenatal care varies by insurance. Medicaid covers pregnancy. Delivery covered by most plans. Shorter postpartum stays.

#### 1.7 Smoking & alcohol

| Parameter | Japan | US | Source |
|---|---|---|---|
| Current smoker (M) | 25% | 14% | JP: 国民健康・栄養調査 2022; US: CDC |
| Current smoker (F) | 7% | 11% | |
| Former smoker (M) | 30% | 30% | |
| Heavy alcohol (M) | 14% | 16% | |
| Heavy alcohol (F) | 3% | 8% | |

---

### 2. Insurance System

#### 2.1 Japan — National Health Insurance system

| Insurance type | Target population | Coverage rate | Copay rate | Proportion |
|---|---|---|---|---|
| `NHI_employee` (被用者保険) | Company employees + dependents | 70% | 30% (age < 70), 20% (70–74), 10% (75+) | 60% |
| `NHI_self` (国民健康保険) | Self-employed, unemployed, retirees < 75 | 70% | 30% (age < 70), 20% (70–74) | 25% |
| `late_elderly` (後期高齢者医療) | Age 75+ | 90% | 10% (standard), 20% or 30% (high income) | 13% |
| `public_assistance` (生活保護) | Welfare recipients | 100% | 0% | 2% |

#### 2.2 US — Mixed insurance market

| Insurance type | Target population | Typical copay | Proportion |
|---|---|---|---|
| `commercial_HMO` | Employer-provided, managed care | $20–40 copay, $1000–3000 deductible | 20% |
| `commercial_PPO` | Employer-provided, choice | $20–50 copay, $500–2000 deductible | 30% |
| `Medicare` | Age 65+ or disabled | 20% coinsurance after deductible | 18% |
| `Medicaid` | Low income | Minimal copay | 17% |
| `Medicare_Medicaid` | Dual eligible | Minimal | 5% |
| `uninsured` | No coverage | 100% OOP | 8% |
| `other` (VA, TRICARE) | Military, veterans | Varies | 2% |

---

### 3. Clinical Practice Parameters

Parameters that directly affect clinical behavior simulation.

#### 3.1 Care-seeking behavior

| Parameter | Japan | US |
|---|---|---|
| `care_seeking_threshold_mean` | 0.25 (low — visit easily) | 0.55 (high — delay due to cost) |
| `care_seeking_threshold_sd` | 0.15 | 0.20 |
| `er_visit_threshold` | 0.60 | 0.75 |
| `convenience_er_rate` (mild symptoms to ER) | 15% of ER visits | 5% of ER visits |
| `self_medication_first_rate` | 40% | 60% |
| `family_influence_on_visit` | Strong (0.7) | Moderate (0.3) |

#### 3.2 Hospital practice patterns

| Parameter | Japan | US |
|---|---|---|
| `lab_frequency_multiplier` | 1.3 | 0.8 |
| `imaging_frequency_multiplier` | 1.2 | 1.0 (higher defensive ordering for specific conditions) |
| `discharge_criteria` | `"lab_normalization"` | `"functional_recovery"` |
| `target_los_multiplier` | 1.0 (baseline) | 0.35 (strong early discharge pressure) |
| `readmission_penalty` | `false` | `true` (ACA 30-day penalty) |
| `defensive_medicine_factor` | 0.1 (low litigation risk) | 0.4 (high litigation risk) |
| `prior_authorization_required` | `false` | `true` (for high-cost imaging, procedures) |
| `social_admission_rate` | 5–8% (medically ready but no discharge destination) | 1–2% |

#### 3.3 Post-discharge patterns

| Parameter | Japan | US |
|---|---|---|
| `follow_up_visit_interval_days` | 7–14 | 14–30 |
| `follow_up_compliance_rate` | 85% | 65% |
| `post_discharge_medication_adherence` | 80% | 65% |
| `rehab_transfer_rate` (hip fracture) | 60% (回復期リハ) | 70% (SNF/IRF) |
| `home_healthcare_rate` | 15% | 30% |

---

### 4. Reimbursement System

#### 4.1 Japan — DPC

```yaml
dpc:
  system: "DPC/PDPS"
  los_periods:
    period_I:
      description: "Short stay — high reimbursement"
      multiplier: 1.15  # of base rate
    period_II:
      description: "Standard stay — target discharge here"
      multiplier: 1.00
    period_III:
      description: "Long stay — reduced reimbursement"
      multiplier: 0.85
  # Period boundaries are disease-specific (defined in disease module YAML)
  outpatient_reimbursement: "fee_for_service"  # outpatient is FFS, not DPC
```

#### 4.2 US — DRG

```yaml
drg:
  system: "MS-DRG"
  payment: "flat_per_admission"  # regardless of LOS
  readmission_penalty:
    window_days: 30
    penalty_rate: 0.03  # up to 3% reduction in payments
    applicable_conditions: ["AMI", "HF", "pneumonia", "COPD", "hip_knee_replacement"]
  outlier_payment:
    threshold: "cost > mean + 2SD"
    additional_payment: "80% of excess cost"
```

---

### 5. Coding Systems

| Item | Japan | US |
|---|---|---|
| `diagnosis_code_system` | `"ICD-10"` (2013 version, Japanese extension) | `"ICD-10-CM"` (annual update) |
| `drug_code_system` | `"YJ"` (YJコード, 12-digit) | `"RxNorm"` |
| `lab_code_system` | `"JLAC10"` (17-digit) | `"LOINC"` |
| `procedure_code_system` | `"K-code"` (診療報酬点数表) | `"CPT"` |
| `output_format` | `"HL7_FHIR_R4"` | `"HL7_FHIR_R4"` |

---

### 6. Preventive Care & Screening Programs

(Already documented in detail — see above section "Preventive care & screening programs")

Key parameters:

| Parameter | Japan | US |
|---|---|---|
| `health_checkup_system` | Mandatory (corporate), recommended (municipal) | Covered but not mandated |
| `checkup_season_peak` | May–October | Year-round |
| `corporate_checkup_compliance` | 85% | N/A |
| `municipal_checkup_compliance` | 45% | N/A |
| `annual_wellness_visit_rate` | N/A | 50% (Medicare), 30% (commercial) |
| `abnormal_finding_referral_rate` | 8–12% | 5–8% |

---

### 7. National Calendar

```yaml
# Japan
holidays:
  fixed:
    - {date: "01-01", name: "元日", duration_days: 1}
    - {date: "02-11", name: "建国記念の日", duration_days: 1}
    - {date: "02-23", name: "天皇誕生日", duration_days: 1}
    - {date: "03-21", name: "春分の日", duration_days: 1}  # approximate
    - {date: "04-29", name: "昭和の日", duration_days: 1}
    - {date: "05-03", name: "憲法記念日", duration_days: 1}
    - {date: "05-04", name: "みどりの日", duration_days: 1}
    - {date: "05-05", name: "こどもの日", duration_days: 1}
    - {date: "08-11", name: "山の日", duration_days: 1}
    - {date: "09-23", name: "秋分の日", duration_days: 1}  # approximate
    - {date: "11-03", name: "文化の日", duration_days: 1}
    - {date: "11-23", name: "勤労感謝の日", duration_days: 1}
  variable:
    - {name: "成人の日", rule: "2nd_monday_january"}
    - {name: "海の日", rule: "3rd_monday_july"}
    - {name: "スポーツの日", rule: "2nd_monday_october"}
    - {name: "敬老の日", rule: "3rd_monday_september"}
  extended_closures:
    - {name: "年末年始", start: "12-29", end: "01-03", operation: "emergency_only"}
    - {name: "Golden Week", start: "04-29", end: "05-05", operation: "reduced"}
    - {name: "Obon", start: "08-13", end: "08-16", operation: "reduced"}  # regional
  seasonal_events:
    - {name: "flu_season", start_month: 11, end_month: 3, impact: "surge"}
    - {name: "cedar_pollen", start_month: 2, end_month: 5, impact: "outpatient_increase"}
    - {name: "fiscal_year_start", month: 4, impact: "staff_rotation"}
    - {name: "checkup_peak", start_month: 5, end_month: 10, impact: "equipment_contention"}

# US
holidays:
  fixed:
    - {date: "01-01", name: "New Year's Day", duration_days: 1}
    - {date: "07-04", name: "Independence Day", duration_days: 1}
    - {date: "12-25", name: "Christmas Day", duration_days: 1}
  variable:
    - {name: "MLK Day", rule: "3rd_monday_january"}
    - {name: "Presidents' Day", rule: "3rd_monday_february"}
    - {name: "Memorial Day", rule: "last_monday_may"}
    - {name: "Labor Day", rule: "1st_monday_september"}
    - {name: "Columbus Day", rule: "2nd_monday_october"}
    - {name: "Thanksgiving", rule: "4th_thursday_november"}
    - {name: "Veterans Day", date: "11-11"}
  extended_closures:
    - {name: "Thanksgiving_weekend", rule: "4th_thursday_november + 1 day", operation: "reduced"}
    - {name: "Christmas_NewYear", start: "12-24", end: "01-01", operation: "reduced"}
  seasonal_events:
    - {name: "flu_season", start_month: 10, end_month: 4, impact: "surge"}
    - {name: "academic_year_start", month: 7, impact: "staff_rotation"}  # July effect
    - {name: "allergy_season_spring", start_month: 3, end_month: 6, impact: "outpatient_increase"}
    - {name: "allergy_season_fall", start_month: 8, end_month: 11, impact: "outpatient_increase"}
```

---

### 8. Care Transition Pathways

```yaml
# Japan
care_transitions:
  from_acute_hospital:
    - {destination: "convalescent_rehab", probability: 0.15, typical_conditions: ["hip_fracture", "stroke"]}
    - {destination: "long_term_care_hospital", probability: 0.05, typical_conditions: ["severe_chronic"]}
    - {destination: "home_with_visiting_care", probability: 0.15, conditions: ["elderly_with_support"]}
    - {destination: "home_independent", probability: 0.55}
    - {destination: "geriatric_health_facility", probability: 0.05}
    - {destination: "death_in_hospital", probability: 0.05}

# US
care_transitions:
  from_acute_hospital:
    - {destination: "SNF", probability: 0.20, typical_conditions: ["hip_fracture", "stroke", "elderly"]}
    - {destination: "IRF", probability: 0.05, typical_conditions: ["stroke", "major_trauma"]}
    - {destination: "home_health_agency", probability: 0.15}
    - {destination: "home_independent", probability: 0.50}
    - {destination: "hospice", probability: 0.03}
    - {destination: "death_in_hospital", probability: 0.05}
    - {destination: "LTAC", probability: 0.02, typical_conditions: ["prolonged_ventilation"]}
```

---

## Open Questions
- [ ] Medical cost / claims data generation (DPC/DRG code assignment) — needed? (global open #19)
- [ ] Comorbidity co-occurrence multipliers: validate against published data (Charlson index studies)
- [ ] Regional variation within Japan (e.g., rural vs. urban hospital access)
- [ ] US state-level variation (Medicaid expansion, certificate of need laws)
- [ ] How to handle parameter updates when data sources publish new editions

## Design Notes
- All quantitative parameters must cite their source. Unsourced parameters are flagged as estimates pending validation.
- The YAML configs are the single source of truth for country-specific behavior. No hardcoded country logic in other modules.
- Parameters are organized by consumer module to make it easy to find relevant settings.
- Override mechanism: user can pass a partial YAML that merges over the country defaults.
