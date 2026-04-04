# observation — Lab & Vital Signs Generation Engine

## Purpose
Generate observable clinical data (lab values, vital signs, imaging results) from the hidden physiological state. Implements the 3-layer architecture: physiological state → value derivation → observation noise/missingness.

## Inputs
- `PhysiologicalState`: Current state variables at the measurement time point
- `PatientProfile`: Individual-difference parameters (immune reactivity, etc.)
- `DiseaseProtocol`: Scheduled lab/test ordering protocol
- `HealthcareSystemConfig`: Lab frequency multiplier, test ordering patterns

## Outputs
- `LabResult`: Individual lab result with value, units, timestamp, and optional flags (hemolysis, etc.)
- `VitalSigns`: Vital sign measurements with timestamp
- `ImagingResult`: Imaging findings (structured, e.g., "lobar consolidation")
- `ObservationTimeline`: Complete ordered sequence of all observations for a patient

## Dependencies
- `physiology` (provides state variables — Layer 1)
- `patient` (individual-difference parameters)
- `disease` (lab ordering schedule)
- `healthcare_system` (lab frequency, timing patterns)

## Confirmed Specifications

### 3-layer architecture

#### Layer 1: Physiological state space
(Provided by the `physiology` module — hidden variables, not directly observed)

#### Layer 2: State → observed value derivation

**Inflammation cascade with temporal delays:**
```
Infection → WBC rise (6–12h)
         → CRP rise (24–48h delay)
         → Procalcitonin rise (3–6h, bacterial-specific)
         → ESR rise (48h+, slowest to normalize)
         → Albumin decline (days)
```

**Renal function cascade:**
```
Cr rise → BUN rise (BUN/Cr ratio 10:1–20:1)
       → eGFR decline (CKD-EPI formula)
       → K rise (excretion impairment)
       → HCO3 decline (metabolic acidosis)
       → Ca decline (reduced active VitD production)
       → P rise (accumulation)
```

**Vital sign composite derivation:**
```
Temperature = baseline + inflammation_level × 3.0 + diurnal_variation (sine wave)
Heart rate  = baseline + (temp - 37.0) × 10 + (1 - perfusion) × 40
Blood pressure = baseline + volume_status × 15 + perfusion_effect
```

#### Layer 3: Observation noise & missingness

**Measurement error model:**
- Gaussian noise (CV set per lab item)
- 2% probability of outlier (phlebotomy error, hemolysis, instrument error)

**Context-dependent missingness patterns:**

| Cause | Missing probability |
|---|---|
| Nighttime (22:00–06:00) | 80% missing for non-emergency tests |
| Patient refusal | 30% missing |
| Difficult blood draw (elderly, obese) | 10% failure → re-draw |
| Culture drawn after antibiotic administration | Sensitivity drops to 60% (false negative) |

**Timing offsets:**
```
Order time → draw time (+30–60 min)
          → result report time (+1–2 hours)
          → physician review time (+additional delay)

Blood culture: final result 72 hours after collection
Imaging read: urgent 30 min, routine 2–4 hours
Pathology: 3–7 days
```

**"Explainable anomaly" patterns:**

| Pattern | Affected values | Clue |
|---|---|---|
| Hemolyzed sample | K falsely high, LDH elevated | Specimen note: "hemolyzed" |
| Draw near IV line | Electrolyte dilution | Normalizes on re-draw |
| Postprandial draw (< 2h) | Glucose +30–60, TG markedly elevated | Correlate with draw time |
| High-dose biotin intake | Thyroid hormone / troponin interference | Correlate with medication history |

### Temporal effects on observation values

Lab values and vital signs have natural temporal variation independent of disease progression:

#### Diurnal (circadian) variation in lab values
| Analyte | Pattern | Amplitude |
|---|---|---|
| Cortisol | Peak 06:00–08:00, nadir at midnight | 2–3× variation |
| TSH | Peak at night, nadir afternoon | ~50% variation |
| Iron / TIBC | Higher morning, lower evening | ~30% variation |
| WBC | Lower morning, higher afternoon | ~15% variation |
| Testosterone | Peak early morning | ~30% variation |
| Body temperature | Nadir 04:00, peak 18:00 | ±0.5°C |

These must be layered on top of disease-driven changes.

#### Fasting state effects
- Blood glucose: fasting (8h+) vs. postprandial (2h) → 70–100 vs. 100–160 mg/dL in healthy
- Triglycerides: fasting vs. postprandial → can differ by 2–5×
- Morning lab draws are typically fasting; afternoon draws may not be
- Must correlate specimen collection time with meal schedule

#### Seasonal variation in baseline values
| Analyte | Seasonal effect | Mechanism |
|---|---|---|
| Vitamin D | Lower in winter | Reduced sun exposure |
| Hemoglobin | Slightly higher in winter | Hemoconcentration |
| Blood pressure | Higher in winter | Vasoconstriction |
| Allergic markers (IgE, eosinophils) | Higher in spring/fall | Pollen exposure |

#### Lab processing time variation
- Turnaround time depends on time-of-day, day-of-week, and facility capacity (defined in `order` and `facility`)
- This affects the **result timestamp** but not the **value** (which reflects physiology at collection time)

---

## Internal Design

### Layer 3: Noise, missingness, and artifacts

This is observation's core responsibility. Physiology provides the "true" value; observation makes it "real."

```python
def generate_lab_result(order: Order, state_history: list[PhysiologicalState],
                         patient: PatientProfile, collection_time: datetime) -> OrderResult | None:
    lab_name = order.display_name
    
    # Step 1: Check missingness (may return None = no result)
    if should_be_missing(lab_name, patient, collection_time):
        return None  # specimen not collected or lost
    
    # Step 2: Get time-lagged physiological state
    effective_state = physiology.get_effective_state_for_lab(lab_name, collection_time, state_history)
    
    # Step 3: Derive "true" value from physiology
    true_values = physiology.derive_lab_values(effective_state, patient, collection_time)
    true_value = true_values[lab_name]
    
    # Step 4: Apply measurement noise
    noisy_value = apply_measurement_noise(lab_name, true_value)
    
    # Step 5: Check for explainable anomaly
    anomaly = check_anomaly_pattern(lab_name, patient, collection_time)
    if anomaly:
        noisy_value = apply_anomaly(noisy_value, anomaly)
    
    # Step 6: Round to realistic precision
    final_value = round_to_precision(lab_name, noisy_value)
    
    return OrderResult(value=final_value, unit=get_unit(lab_name), specimen_note=anomaly)
```

### Three-layer variability model

Real lab values vary for three distinct reasons. All three must be modeled independently:

```
Physiological "true" value (from physiology module)
  |
  +-- (1) Biological variation (within-person day-to-day fluctuation)
  |       Same person, same condition, tested on consecutive days → values differ
  |
  +-- (2) Pre-analytical variation (specimen handling)
  |       Tourniquet time, posture, fasting state, sample processing delay
  |
  +-- (3) Analytical variation (instrument precision)
  |       Same specimen measured twice → values differ slightly
  |
  = Observed value (what appears in EHR)
```

```python
def apply_realistic_variability(lab_name: str, true_value: float, 
                                 patient: PatientProfile, collection_context: dict) -> float:
    
    # (1) Biological variation (CVi — within-individual biological CV)
    # This is the natural fluctuation even when the patient's condition is stable.
    # Published data from Ricos et al. (desirable biological variation database)
    cvi = BIOLOGICAL_CV[lab_name]
    bio_noise = Normal(0, true_value * cvi).sample()
    
    # (2) Pre-analytical variation
    pre_noise = apply_pre_analytical_effects(lab_name, true_value, collection_context)
    
    # (3) Analytical variation (CVa — analytical imprecision)
    cva = ANALYTICAL_CV[lab_name]
    analytical_noise = Normal(0, true_value * cva).sample()
    
    observed = true_value + bio_noise + pre_noise + analytical_noise
    return max(0, observed)
```

### Biological variation (CVi) — within-individual, day-to-day

Even in a perfectly stable patient, lab values fluctuate day to day due to normal physiological variation. This is the largest source of variation for many analytes.

```python
# Source: Ricos et al. Desirable Biological Variation Database (2014, updated)
# CVi = within-individual biological coefficient of variation (%)
BIOLOGICAL_CV = {
    # Very stable analytes (low biological variation)
    "Na":          0.006,   # 0.6% — sodium is tightly regulated
    "Cl":          0.012,   # 1.2%
    "Ca":          0.019,   # 1.9%
    "Albumin":     0.032,   # 3.2%
    "TP":          0.028,   # 2.8%
    "Hb":          0.029,   # 2.9%
    "Hct":         0.029,
    "RBC":         0.033,
    "MCV":         0.013,   # 1.3% — very stable
    
    # Moderately variable
    "K":           0.046,   # 4.6%
    "Creatinine":  0.056,   # 5.6%
    "BUN":         0.121,   # 12.1% — highly variable
    "Glucose":     0.056,   # 5.6% (fasting)
    "WBC":         0.110,   # 11.0% — large biological variation
    "Plt":         0.094,   # 9.4%
    
    # Highly variable
    "AST":         0.120,   # 12.0%
    "ALT":         0.195,   # 19.5% — very high biological variation
    "GGT":         0.138,
    "ALP":         0.068,
    "CK":          0.226,   # 22.6% — extremely variable
    "LDH":         0.083,
    "T_Bil":       0.213,   # 21.3%
    "TG":          0.209,   # 20.9% (fasting)
    "Iron":        0.267,   # 26.7% — highest among routine analytes
    
    # Immunoassay / special
    "CRP":         0.423,   # 42.3% — extremely high biological variation
    "PCT":         0.30,    # estimated
    "BNP":         0.40,    # ~40% — known high variation
    "Troponin":    0.14,    # 14% (hs-troponin, healthy subjects)
    "TSH":         0.196,   # 19.6%
    "FT4":         0.068,
    "Ferritin":    0.152,
    "HbA1c":       0.018,   # 1.8% — very stable (reflects 3-month average)
    "D_dimer":     0.30,    # ~30%
    
    # Blood gas (point-of-care, very stable analytically but bio-variable)
    "pH":          0.002,   # 0.2% — tightly regulated
    "pCO2":        0.046,
    "Lactate":     0.278,   # 27.8% — high
}
```

**Realism impact**: CRP has a biological CV of 42%. This means a stable patient with a "true" CRP of 10 mg/L could naturally measure anywhere from 6 to 16 mg/L on different days, even without any change in clinical status. This is why clinicians track CRP *trends*, not single values. Without modeling this, generated CRP curves would be unrealistically smooth.

### Pre-analytical variation

```python
def apply_pre_analytical_effects(lab_name: str, value: float, context: dict) -> float:
    effect = 0
    
    # Tourniquet time > 1 min: K, Ca, TP, Albumin increase
    if context.get("tourniquet_prolonged", False):  # ~10% of draws
        if lab_name == "K": effect += 0.3       # +0.3 mEq/L
        if lab_name == "Ca": effect += 0.1
        if lab_name in ["TP", "Albumin"]: effect += value * 0.05
    
    # Posture: supine vs. sitting affects plasma volume (hemoconcentration)
    if context.get("posture") == "supine":
        # Supine: ~5-8% lower for proteins (Albumin, TP) vs. upright
        if lab_name in ["Albumin", "TP", "Hb", "Hct"]:
            effect -= value * 0.06
    
    # Specimen processing delay (> 2h at room temperature)
    if context.get("processing_delay_hours", 0) > 2:
        if lab_name == "K": effect += 0.2       # K leaks from RBCs
        if lab_name == "Glucose": effect -= value * 0.05  # glycolysis
        if lab_name == "Lactate": effect += 0.3  # continues to rise
    
    # Fasting state (already in physiology circadian model, but pre-analytical also)
    # Non-fasting: TG, Glucose elevated (handled by physiology)
    
    return effect
```

### Analytical variation (CVa) — instrument precision

```python
# CVa = analytical coefficient of variation (instrument imprecision)
# These are separate from biological variation
ANALYTICAL_CV = {
    # Hematology (automated counter): very low
    "WBC": 0.025, "RBC": 0.015, "Hb": 0.015, "Hct": 0.015, "Plt": 0.035, "MCV": 0.010,
    # Chemistry (modern automated analyzer)
    "Na": 0.008, "K": 0.015, "Cl": 0.008, "Ca": 0.015, "P": 0.025,
    "BUN": 0.030, "Creatinine": 0.030, "Glucose": 0.020,
    "AST": 0.050, "ALT": 0.050, "ALP": 0.040, "GGT": 0.050,
    "T_Bil": 0.040, "Albumin": 0.025, "TP": 0.015,
    "LDH": 0.035, "CK": 0.040,
    # Immunoassay: higher
    "CRP": 0.050, "PCT": 0.080, "BNP": 0.070, "Troponin": 0.080,
    "TSH": 0.060, "FT4": 0.050, "Ferritin": 0.060,
    "HbA1c": 0.020,
    # Blood gas (POCT)
    "pH": 0.001, "pCO2": 0.025, "pO2": 0.030, "HCO3": 0.025, "Lactate": 0.040,
    # Coagulation
    "PT_INR": 0.035, "aPTT": 0.040, "Fibrinogen": 0.050, "D_dimer": 0.080,
}
```

### Total variation and clinical significance

The total CV combining biological and analytical variation:

```
Total CV = sqrt(CVi^2 + CVa^2)
```

| Analyte | CVi | CVa | Total CV | RCV (95% ref change) | Interpretation |
|---|---|---|---|---|---|
| Na | 0.6% | 0.8% | 1.0% | 2.8% | Change > 4 mEq/L is clinically significant |
| K | 4.6% | 1.5% | 4.8% | 13.6% | Change > 0.5 mEq/L may be noise |
| Creatinine | 5.6% | 3.0% | 6.4% | 17.7% | Small changes often not meaningful |
| CRP | 42.3% | 5.0% | 42.6% | 118% | Single values nearly meaningless; need trend |
| WBC | 11.0% | 2.5% | 11.3% | 31.2% | Day-to-day variation is large |
| HbA1c | 1.8% | 2.0% | 2.7% | 7.5% | Very stable — good for monitoring |

**RCV (Reference Change Value)**: The minimum change between two consecutive measurements that is statistically significant (95% confidence). Generated data should show changes exceeding RCV only when the physiological state actually changed.
    "TSH": 0.08, "FT4": 0.07, "Ferritin": 0.08,
    "HbA1c": 0.03,
    # Blood gas: low CV (point-of-care, well-calibrated)
    "pH": 0.001, "pCO2": 0.03, "pO2": 0.04, "HCO3": 0.03, "Lactate": 0.05,
    # Coagulation
    "PT_INR": 0.04, "aPTT": 0.05, "Fibrinogen": 0.06, "D_dimer": 0.10,
}

def apply_measurement_noise(lab_name: str, true_value: float) -> float:
    cv = LAB_CV.get(lab_name, 0.05)
    sd = true_value * cv
    noisy = Normal(true_value, sd).sample()
    return max(0, noisy)  # lab values cannot be negative
```

### Missingness model

```python
def should_be_missing(lab_name: str, patient: PatientProfile, collection_time: datetime) -> bool:
    hour = collection_time.hour
    
    # Night: routine labs not collected (80% missing for non-STAT)
    if 22 <= hour or hour < 6:
        if lab_name not in STAT_ALWAYS_AVAILABLE:
            return random() < 0.80
    
    # Patient refusal (correlates with mental health, health literacy)
    refusal_base = 0.01
    if "anxiety" in [m.condition for m in patient.mental_health_conditions]:
        refusal_base = 0.05
    if patient.cognitive_status in ["moderate_dementia", "severe_dementia"]:
        refusal_base = 0.08  # agitation, inability to cooperate
    if random() < refusal_base:
        return True
    
    # Difficult venous access (elderly, obese, dehydrated)
    if patient.age >= 80 or patient.bmi >= 35:
        if random() < 0.05:  # 5% first-attempt failure; usually re-attempted
            return random() < 0.3  # 30% of failures = give up
    
    return False
```

### Explainable anomaly patterns

```python
ANOMALY_PATTERNS = {
    "hemolysis": {
        "probability": 0.02,
        "affected": {"K": "+1.5", "LDH": "*2.0", "AST": "+20"},
        "specimen_note": "hemolyzed",
        "triggers_redraw": True,
    },
    "iv_line_contamination": {
        "probability": 0.01,
        "affected": {"Na": "=iv_fluid_Na", "K": "=iv_fluid_K", "Glucose": "=iv_fluid_glucose"},
        "specimen_note": "suspected IV contamination",
        "triggers_redraw": True,
    },
    "postprandial": {
        "probability_if_within_2h_of_meal": 0.15,
        "affected": {"Glucose": "+40", "TG": "*2.5"},
        "specimen_note": None,  # no flag, just timing correlation
    },
}

def check_anomaly_pattern(lab_name: str, patient: PatientProfile, 
                           collection_time: datetime) -> dict | None:
    for name, pattern in ANOMALY_PATTERNS.items():
        if lab_name in pattern["affected"]:
            prob = pattern["probability"]
            if name == "postprandial":
                # Check meal proximity
                if is_within_meal_window(collection_time):
                    prob = pattern["probability_if_within_2h_of_meal"]
                else:
                    prob = 0
            if random() < prob:
                return pattern
    return None
```

### Imaging result generation

```python
def generate_imaging_result(order: Order, state: PhysiologicalState, 
                             patient: PatientProfile) -> OrderResult:
    modality = get_imaging_modality(order)
    
    # Rule-based finding generation from state
    findings = []
    
    if modality == "chest_xray":
        if state.inflammation_level > 0.3 and patient_has_pneumonia:
            findings.append({"finding": "consolidation", "location": "RLL", "severity": "moderate"})
        if state.volume_status > 0.4:
            findings.append({"finding": "pulmonary_edema", "severity": "mild"})
            findings.append({"finding": "cardiomegaly", "ctr": ">0.50"})
        if state.volume_status > 0.3:
            findings.append({"finding": "pleural_effusion", "side": "bilateral", "amount": "small"})
    
    # LLM generates the narrative interpretation (via llm_service)
    interpretation = llm_service.generate(
        LLMTaskType.PROGRESS_NOTE,  # or a dedicated IMAGING_REPORT type
        ClinicalEventData(
            patient_summary=build_summary(patient),
            event_data={"modality": modality, "findings": findings},
            language=patient.country_language,
        )
    )
    
    return OrderResult(
        value=None,
        interpretation=interpretation.text or format_findings_template(findings),
    )
```

## Open Questions
- [x] ~~CV values per lab item~~: **Resolved** (see LAB_CV table above)
- [ ] Imaging result generation: LLM vs. structured-only (current: hybrid)
- [ ] Reference range tables: need age/sex-specific reference ranges per lab item per country
- [ ] Pregnancy-specific reference ranges (e.g., Hb 10 g/dL is normal in pregnancy)

## Design Notes (continued)

## Design Notes
- Observation values must reflect the patient's state at the **specimen collection time**, not the result reporting time
- Temporal variation (circadian, fasting, seasonal) is an additional layer on top of the 3-layer architecture

### Input from physiology module (Layer 2 derivation)
The observation module's Layer 2 is now implemented in the physiology module as `derive_lab_values()` and `derive_vital_signs()`. The observation module:
1. Calls `physiology.get_effective_state_for_lab(lab_name, collection_time, state_history)` to get the time-lagged state for each lab marker (CRP uses inflammation_level from 24–48h ago, not current)
2. Calls `physiology.derive_lab_values(effective_state, patient, timestamp)` to get the "true" lab value
3. Applies Layer 3: measurement noise (CV per item), missingness, timing offsets, explainable anomalies (hemolysis, etc.)

### Input from disease module
- Disease protocol's `daily_monitoring` defines which labs are measured and how often
- Lab ordering frequency is affected by `lab_frequency_multiplier` (country-specific) and protocol-defined schedule
- For pneumonia example: CRP is ordered daily in Japan, every other day in US

### Layer 3: observation module's own responsibility
The observation module ONLY handles Layer 3 (noise and missingness). It does NOT compute "true" lab values — that is physiology's job. Specifically:
- Gaussian noise per lab item (CV: CBC ~3%, chemistry ~5%, immunoassay ~8%)
- Outlier generation (2%: hemolysis, equipment error)
- Missingness (context-dependent: nighttime, patient refusal, difficult draw)
- Timing offsets (order → collection → result → review)
- Explainable anomaly patterns (hemolysis artifacts, IV line contamination, postprandial effects)
