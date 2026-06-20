# physiology — Physiological State Variables & State Space

## Purpose
Define the hidden physiological state variables that represent a patient's clinical condition, manage their evolution over time, and provide the mapping from state variables to observable values (lab results, vital signs). This is the core realism engine — all clinical observations are derived from this state, not generated independently.

## Inputs
- `PatientProfile`: Baseline state and individual-difference parameters
- `StateChangeDirective` from `clinical_course`: Disease progression, treatment effects, complications
- `InterventionEffect` from `treatment`: Immediate effects of medications, fluids, procedures

## Outputs
- `PhysiologicalState`: Snapshot of all state variables at a given point in time
- `DerivedLabValues`: Lab values computed from current state (consumed by observation module)
- `DerivedVitalSigns`: Vital signs computed from current state (consumed by nursing module)

## Dependencies
- `patient` (determines baseline values)
- `clinical_course` (drives state changes via disease trajectory)
- `treatment` (immediate intervention effects)

---

## Internal Design

### State variables

| Variable | Range | Description | Key lab correlates |
|---|---|---|---|
| `inflammation_level` | 0.0–1.0 | 0 = normal, 1 = critical | CRP, WBC, PCT, ESR, Albumin, Ferritin |
| `renal_function` | 0.0–1.0 | 1 = eGFR > 90, 0 = anuria | Creatinine, BUN, eGFR, K, Ca, P, HCO3 |
| `cardiac_function` | 0.0–1.0 | 1 = EF > 60%, 0 = shock | BNP/NT-proBNP, troponin (if acute), EF |
| `hepatic_function` | 0.0–1.0 | 1 = normal, 0 = failure | AST, ALT, ALP, GGT, T-Bil, Albumin, PT-INR |
| `anemia_level` | 0.0–1.0 | 0 = normal, 1 = severe | Hb, Hct, RBC, MCV, reticulocyte |
| `coagulation_status` | 0.0–1.0 | 0 = normal, 1 = DIC | PT-INR, aPTT, fibrinogen, D-dimer, platelets |
| `volume_status` | -1.0–+1.0 | -1 = dehydration, +1 = overload | BUN/Cr ratio, urine specific gravity, Na, Hct (hemoconcentration) |
| `perfusion_status` | 0.0–1.0 | 1 = normal, 0 = shock | Lactate, base excess, urine output |
| `ph_status` | -1.0–+1.0 | -1 = acidosis, +1 = alkalosis | pH, pCO2, HCO3, base excess, anion gap |

---

### Baseline state initialization

```python
def initialize_state(profile: PatientPhysiologicalProfile, 
                     conditions: list[ChronicCondition],
                     pregnancy: PregnancyState | None) -> PhysiologicalState:
    state = PhysiologicalState()
    
    # Start from organ reserves
    state.renal_function = profile.renal_reserve
    state.cardiac_function = profile.cardiac_reserve
    state.hepatic_function = profile.hepatic_reserve
    
    # Chronic condition adjustments
    for c in conditions:
        state = apply_chronic_condition(state, c)
    
    # Healthy baseline for other variables
    state.inflammation_level = 0.03       # trace CRP ~0.5 mg/L
    state.anemia_level = 0.0
    state.coagulation_status = 0.0
    state.volume_status = 0.0
    state.perfusion_status = min(1.0, state.cardiac_function * 1.1)  # tracks cardiac
    state.ph_status = 0.0
    
    # Pregnancy adjustments (if applicable)
    if pregnancy:
        state = apply_pregnancy_offsets(state, pregnancy)
    
    return state

def apply_chronic_condition(state, condition):
    severity = condition.severity_score  # 0.0–1.0
    
    match condition.category:
        case "CKD":
            state.renal_function *= (1.0 - severity * 0.5)
            # CKD causes secondary effects
            if severity > 0.5:  # stage 4+
                state.anemia_level += 0.15      # renal anemia
                state.ph_status -= severity * 0.1  # metabolic acidosis tendency
        case "heart_failure":
            state.cardiac_function *= (1.0 - severity * 0.4)
            if severity > 0.3:
                state.volume_status += severity * 0.3  # fluid overload tendency
        case "cirrhosis":
            state.hepatic_function *= (1.0 - severity * 0.5)
            state.coagulation_status += severity * 0.2  # coagulopathy
            state.anemia_level += severity * 0.1
        case "anemia":
            state.anemia_level = severity * 0.6
        case "COPD":
            state.ph_status -= severity * 0.05  # chronic respiratory acidosis compensation
        case "diabetes":
            pass  # affects labs directly (glucose, HbA1c) but not state variables much
        case "atrial_fibrillation":
            state.cardiac_function *= 0.9  # mildly reduced efficiency
    
    return state
```

### Multiple chronic conditions affecting the same variable

**Resolution rule: multiplicative, then clamp.**

```python
# Example: patient with CKD stage 3 + diabetes nephropathy + dehydration on admission
# CKD: renal_function *= 0.75
# Diabetes nephropathy: already reflected in CKD severity
# Dehydration (volume_status = -0.3): causes pre-renal component → handled by coupling rules
# Result: renal_function = base_reserve * 0.75, then coupling further reduces based on perfusion
```

This avoids double-counting while allowing multiple conditions to compound.

---

### Inter-variable coupling rules

After each `update()` call, coupling rules propagate changes between state variables. These represent physiological dependencies that are always active.

```python
def apply_coupling_rules(state: PhysiologicalState):
    """
    Apply physiological coupling between state variables.
    Order matters: upstream variables affect downstream ones.
    """
    
    # === Perfusion depends on cardiac function and volume ===
    # Low cardiac output or severe dehydration → poor perfusion
    volume_effect = 0.0
    if state.volume_status < -0.5:      # severe dehydration
        volume_effect = state.volume_status * 0.3  # negative → reduces perfusion
    elif state.volume_status > 0.5:     # severe overload with failing heart
        if state.cardiac_function < 0.5:
            volume_effect = -0.1        # pulmonary edema worsens perfusion
    
    state.perfusion_status = clamp(
        state.cardiac_function * 0.8 + 0.2 + volume_effect,
        0.0, 1.0
    )
    
    # === Renal function depends on perfusion (pre-renal) ===
    # Poor perfusion → acute kidney injury
    if state.perfusion_status < 0.5:
        pre_renal_hit = (0.5 - state.perfusion_status) * 0.3
        state.renal_function = clamp(state.renal_function - pre_renal_hit, 0.0, 1.0)
    
    # === pH depends on renal function and perfusion ===
    # Poor renal function → metabolic acidosis (can't excrete acid)
    # Poor perfusion → lactic acidosis
    renal_acid = 0.0
    if state.renal_function < 0.3:
        renal_acid = -(0.3 - state.renal_function) * 0.5
    
    lactic_acid = 0.0
    if state.perfusion_status < 0.4:
        lactic_acid = -(0.4 - state.perfusion_status) * 0.6
    
    state.ph_status = clamp(state.ph_status + (renal_acid + lactic_acid) * 0.1, -1.0, 1.0)
    
    # === Coagulation worsens with severe inflammation (DIC pathway) ===
    if state.inflammation_level > 0.7:
        dic_drive = (state.inflammation_level - 0.7) * 0.15
        state.coagulation_status = clamp(state.coagulation_status + dic_drive, 0.0, 1.0)
    
    # === Hepatic function affects coagulation ===
    if state.hepatic_function < 0.4:
        state.coagulation_status = clamp(
            state.coagulation_status + (0.4 - state.hepatic_function) * 0.1,
            0.0, 1.0
        )
    
    # === Severe inflammation causes anemia (anemia of chronic disease) ===
    # This is a slow effect — only matters over days
    if state.inflammation_level > 0.5:
        state.anemia_level = clamp(
            state.anemia_level + (state.inflammation_level - 0.5) * 0.005,  # very gradual
            0.0, 1.0
        )
```

### Coupling dependency graph

```
cardiac_function ──→ perfusion_status ──→ renal_function ──→ ph_status
                           ↑                                      ↑
                     volume_status                         (lactic acid from perfusion)
                                                                  
inflammation_level ──→ coagulation_status ←── hepatic_function
                  └──→ anemia_level (slow)
```

---

### State → Lab Value Derivation (Layer 2 mapping)

The observation module calls `derive_lab_values(state, patient)` to get observable lab results from hidden state. Here are the key mappings:

```python
def derive_lab_values(state: PhysiologicalState, patient: PatientProfile,
                      timestamp: datetime) -> dict[str, float]:
    labs = {}
    
    # === INFLAMMATION ===
    infl = state.inflammation_level
    
    # CRP: exponential relationship with inflammation
    # Normal: 0–0.3 mg/dL. Peak in severe sepsis: 30+ mg/dL
    labs["CRP"] = 0.1 * math.exp(infl * 5.8)  # 0→0.1, 0.5→9, 0.8→50, 1.0→180
    
    # WBC: 4,000–10,000 normal. Rises with inflammation, but can drop in severe sepsis
    if infl < 0.8:
        labs["WBC"] = 7000 + infl * 12000  # up to ~16,600
    else:
        # Severe sepsis: may see leukopenia
        labs["WBC"] = 7000 + 0.8 * 12000 - (infl - 0.8) * 30000  # drops
        labs["WBC"] = max(1500, labs["WBC"])
    
    # Procalcitonin: highly specific for bacterial infection
    # Normal: < 0.05 ng/mL. Bacterial sepsis: 2–100+
    labs["PCT"] = 0.03 * math.exp(infl * 7)  # steeper curve than CRP
    
    # Albumin: drops with inflammation (negative acute phase reactant) and hepatic dysfunction
    labs["Albumin"] = 4.2 - infl * 2.0 - (1 - state.hepatic_function) * 1.5
    labs["Albumin"] = max(1.0, labs["Albumin"])
    
    # === RENAL ===
    renal = state.renal_function
    
    # Creatinine: inversely related to renal function
    # Normal: 0.6–1.1 (M), 0.4–0.8 (F). Renal failure: 5–15+
    base_cr = 0.9 if patient.sex == "M" else 0.7
    if renal > 0.5:
        labs["Creatinine"] = base_cr / renal  # 1.0→0.9, 0.5→1.8
    else:
        labs["Creatinine"] = base_cr / 0.5 + (0.5 - renal) * 15  # accelerates in failure
    
    # BUN: rises with renal dysfunction, also with dehydration
    labs["BUN"] = 15 / max(renal, 0.1)  # 1.0→15, 0.5→30, 0.2→75
    if state.volume_status < -0.3:  # dehydration elevates BUN disproportionately
        labs["BUN"] *= 1.0 + abs(state.volume_status) * 0.5
    
    # eGFR: directly from renal_function
    labs["eGFR"] = renal * 120  # 1.0→120, 0.5→60, 0.25→30
    
    # Potassium: rises with renal failure, acidosis
    labs["K"] = 4.0 + (1 - renal) * 3.0 + max(0, -state.ph_status) * 1.0
    labs["K"] = clamp(labs["K"], 2.5, 8.0)
    
    # === CARDIAC ===
    cardiac = state.cardiac_function
    
    # BNP: ventricular wall stress = volume/pressure load ON a stressed ventricle.
    # The volume term is gated by cardiac dysfunction, so HF (low cardiac x high volume)
    # rises sharply while uncomplicated MI (low cardiac, normal volume) stays moderate.
    labs["BNP"] = 30 * math.exp((1 - cardiac) * 2.0 + max(0, volume) * (1 - cardiac) * 5.0)
    # HF exacerbation (cardiac~0.27, volume~0.56) -> ~1000; MI (cardiac~0.19) -> ~150; normal -> ~37
    
    # === HEPATIC ===
    hepatic = state.hepatic_function
    
    # AST/ALT: rise with hepatic damage
    labs["AST"] = 25 + (1 - hepatic) * 500  # normal ~25, liver failure ~500
    labs["ALT"] = 20 + (1 - hepatic) * 400
    labs["T_Bil"] = 0.8 + (1 - hepatic) * 15  # normal ~0.8, failure ~15
    
    # PT-INR: affected by both hepatic and coagulation
    labs["PT_INR"] = 1.0 + (1 - hepatic) * 2.0 + state.coagulation_status * 1.5
    
    # === ANEMIA ===
    anemia = state.anemia_level
    
    # Hemoglobin
    base_hb = 15.0 if patient.sex == "M" else 13.0
    labs["Hb"] = base_hb * (1 - anemia * 0.7)  # 0→15, 0.5→9.75, 1.0→4.5
    labs["Hct"] = labs["Hb"] * 3  # approximate
    
    # === PERFUSION ===
    perfusion = state.perfusion_status
    
    # Lactate: rises with poor perfusion
    labs["Lactate"] = 1.0 + (1 - perfusion) * 12  # normal ~1.0, shock ~13
    
    # === pH / BLOOD GAS ===
    ph = state.ph_status
    
    labs["pH"] = 7.40 + ph * 0.20  # -1→7.20, 0→7.40, +1→7.60
    labs["HCO3"] = 24 + ph * 12    # -1→12, 0→24, +1→36
    
    # === GLUCOSE (from patient conditions, not a state variable) ===
    if patient.has_condition("diabetes"):
        dm_control = patient.get_condition("diabetes").controlled
        if dm_control:
            labs["Glucose"] = Normal(130, 30).sample()  # controlled but not perfect
        else:
            labs["Glucose"] = Normal(200, 60).sample()
    else:
        labs["Glucose"] = Normal(95, 10).sample()
    # Stress hyperglycemia from inflammation
    labs["Glucose"] += state.inflammation_level * 50
    
    # === Apply temporal modifiers ===
    labs = apply_circadian_variation(labs, timestamp)
    
    return labs
```

### State → Vital Signs Derivation

```python
def derive_vital_signs(state: PhysiologicalState, patient: PatientProfile,
                        baseline: BaselineVitals, timestamp: datetime) -> VitalSignRecord:
    
    infl = state.inflammation_level
    perf = state.perfusion_status
    vol = state.volume_status
    
    # Temperature: driven by inflammation + circadian rhythm
    circadian = 0.3 * math.sin((timestamp.hour - 4) * math.pi / 12)  # peak at 16:00, nadir at 04:00
    temperature = baseline.temperature + infl * 3.0 + circadian
    temperature = clamp(temperature, 35.0, 42.0)
    
    # Heart rate: rises with fever, low perfusion, pain, anemia
    temp_effect = max(0, (temperature - 37.0)) * 10  # +10 bpm per °C above 37
    perfusion_effect = max(0, (1.0 - perf)) * 40     # compensatory tachycardia
    anemia_effect = state.anemia_level * 15           # compensatory
    hr = baseline.heart_rate + temp_effect + perfusion_effect + anemia_effect
    hr = int(clamp(hr, 40, 180))
    
    # Blood pressure: drops with poor perfusion and dehydration, rises with overload
    sbp = baseline.systolic_bp
    sbp += vol * 15               # fluid overload raises, dehydration lowers
    sbp -= (1 - perf) * 40        # shock drops BP
    sbp = int(clamp(sbp, 60, 220))
    
    dbp = baseline.diastolic_bp
    dbp += vol * 8
    dbp -= (1 - perf) * 20
    dbp = int(clamp(dbp, 30, 130))
    
    # Respiratory rate: rises with acidosis, inflammation, fluid overload
    rr = baseline.respiratory_rate
    rr += max(0, -state.ph_status) * 10    # acidosis → compensatory hyperventilation
    rr += infl * 4                          # inflammation/fever
    if vol > 0.5:
        rr += (vol - 0.5) * 8              # pulmonary edema
    rr = int(clamp(rr, 8, 45))
    
    # SpO2: drops with lung pathology (inflammation in pneumonia), fluid overload, anemia
    spo2 = baseline.spo2
    # Pneumonia-specific: inflammation directly affects gas exchange
    if infl > 0.3:
        spo2 -= (infl - 0.3) * 10          # moderate pneumonia: SpO2 93-95
    if vol > 0.3:
        spo2 -= (vol - 0.3) * 5            # pulmonary edema
    spo2 = clamp(spo2, 60, 100)
    
    return VitalSignRecord(
        temperature_celsius=round(temperature, 1),
        heart_rate=hr,
        systolic_bp=sbp,
        diastolic_bp=dbp,
        respiratory_rate=rr,
        spo2=round(spo2, 1),
    )
```

### Circadian variation overlay

```python
def apply_circadian_variation(labs: dict, timestamp: datetime) -> dict:
    hour = timestamp.hour
    
    # Cortisol: peak 06–08, nadir midnight
    if "Cortisol" in labs:
        cortisol_factor = 1.0 + 0.5 * math.cos((hour - 7) * math.pi / 12)
        labs["Cortisol"] *= cortisol_factor
    
    # WBC: lower morning, higher afternoon (~15% variation)
    labs["WBC"] *= (1.0 + 0.07 * math.sin((hour - 6) * math.pi / 12))
    
    # Iron: higher morning
    if "Iron" in labs:
        labs["Iron"] *= (1.0 + 0.15 * math.cos((hour - 8) * math.pi / 12))
    
    return labs
```

---

### Treatment intervention immediate effects

Some treatments have immediate effects on state variables that don't wait for the daily clinical_course cycle:

```python
def apply_intervention(state: PhysiologicalState, intervention: InterventionEffect):
    """Called by encounter/treatment when an intervention has an immediate physiological effect."""
    
    match intervention.type:
        case "iv_fluid_bolus":
            # 500mL NS bolus: immediate volume effect
            state.volume_status += 0.15
            # If dehydrated, also improves perfusion
            if state.volume_status < 0:
                state.perfusion_status = clamp(state.perfusion_status + 0.05, 0, 1)
        
        case "blood_transfusion":
            # 1 unit RBC: Hb rises ~1 g/dL → anemia_level decreases
            state.anemia_level = clamp(state.anemia_level - 0.07, 0, 1)
        
        case "vasopressor_start":
            # Norepinephrine: immediate perfusion improvement
            state.perfusion_status = clamp(state.perfusion_status + 0.15, 0, 1)
        
        case "diuretic_dose":
            # Furosemide: volume reduction over 2-4 hours
            state.volume_status -= 0.10  # immediate effect; further reduction over time
        
        case "oxygen_therapy":
            # SpO2 improvement is handled in vital sign derivation (not state variable)
            pass
        
        case "antibiotic_start":
            # No immediate state change — effect comes through clinical_course over 24-72h
            pass
        
        case "intubation":
            # Mechanical ventilation: immediate gas exchange support
            # Handled in vital sign derivation (SpO2 improvement)
            state.ph_status = clamp(state.ph_status + 0.05, -1, 1)  # improved ventilation
    
    # Always reapply coupling after intervention
    apply_coupling_rules(state)
```

---

### Temporal lag model for lab markers

Different lab markers respond to physiological changes at different speeds:

```python
LAB_TEMPORAL_LAGS = {
    # marker: (rise_lag_hours, fall_lag_hours)
    "WBC":       (6, 24),       # rises in 6-12h, normalizes over days
    "CRP":       (24, 72),      # rises in 24-48h, slow to normalize
    "PCT":       (3, 24),       # fastest inflammatory marker
    "ESR":       (48, 168),     # slowest to rise, slowest to normalize
    "Albumin":   (72, 168),     # drops slowly, recovers very slowly
    "Creatinine": (12, 48),     # reflects GFR with ~12h delay
    "BNP":       (4, 48),       # relatively rapid response
    "Lactate":   (1, 4),        # nearly real-time perfusion marker
    "Troponin":  (3, 72),       # rises 3-6h after myocardial injury, peaks at 12-24h
}
```

The observation module uses these lags when generating lab values. For example, if `inflammation_level` dropped at 08:00, the CRP value at 10:00 still reflects the higher inflammation from 24 hours ago, not the current lower state.

```python
def get_effective_state_for_lab(lab_name: str, current_time: datetime,
                                 state_history: list[PhysiologicalState]) -> float:
    """Look back in state history by the lag amount to find the effective state for this lab."""
    lag_hours = LAB_TEMPORAL_LAGS.get(lab_name, (0, 0))
    # Use rise_lag if state is worsening, fall_lag if improving
    # (simplified: use average lag)
    avg_lag = (lag_hours[0] + lag_hours[1]) / 2
    target_time = current_time - timedelta(hours=avg_lag)
    
    # Find closest state snapshot to target_time
    return interpolate_state_at_time(state_history, target_time)
```

---

### Open Questions resolved / remaining

- [x] ~~Time step granularity (global open #2)~~: **Resolved** — variable per encounter type
- [x] ~~Inter-variable coupling rules~~: **Resolved** — see coupling rules above
- [x] ~~Multiple chronic conditions on same variable~~: **Resolved** — multiplicative then clamp
- [ ] State variable granularity (global open #1): current organ-level design works for Phase 1 diseases. May need subdivision for Phase 2 (e.g., separate systolic/diastolic cardiac function for AMI)
- [ ] ICU-specific rapid interventions: 15-min steps + `apply_intervention()` for immediate effects should be adequate. Validate with ICU physician.
- [ ] Full quantitative validation of state→lab mapping coefficients against clinical reference ranges
- [ ] Pregnancy-specific lab reference ranges in observation module (not in physiology, but flagged here)

## Design Notes
- Baseline state is computed once at encounter start by combining patient constitution with chronic condition impact
- The disease event then _adds_ its effect on top of this baseline (e.g., pneumonia raises inflammation_level from the patient's starting point)
- Time resolution is a property of the encounter, not the physiology module itself
- The temporal lag model is critical for realism: CRP peaking 48h after infection onset, not immediately, is one of the strongest realism signals
- Lab derivation functions use exponential curves for most markers because the relationship between organ function and lab values is typically nonlinear (small dysfunction = small lab change; severe dysfunction = dramatic lab change)

### Cross-module impact
- **observation**: Calls `derive_lab_values()` and `derive_vital_signs()`. Must also apply Layer 3 noise (measurement error, missingness) on top of derived values. Must use `get_effective_state_for_lab()` for temporal lag.
- **nursing**: Calls `derive_vital_signs()` for vital sign measurement events. The temporal pattern of vitals (fever curve, HR trend) comes directly from the state trajectory.
- **clinical_course**: Drives state changes via `StateChangeDirective`. The archetype trajectory (from disease module) produces daily deltas that feed into `update()`.
- **treatment**: Calls `apply_intervention()` for immediate effects (fluid bolus, transfusion, vasopressor). Longer-term treatment effects (antibiotics) go through clinical_course.
- **validator**: Uses state history to verify that generated lab values are consistent with the state trajectory. If observation module produces a CRP of 5 but inflammation_level is 0.8, that's a bug.

### Pediatric physiological model

Children are NOT small adults. Lab values, vital signs, and physiological responses differ fundamentally by age.

#### Age-dependent baseline vitals

| Age | HR (bpm) | RR (/min) | SBP (mmHg) | Temp (C) |
|---|---|---|---|---|
| Neonate (0-28d) | 120-160 | 30-60 | 60-80 | 36.5-37.5 |
| Infant (1-12m) | 100-150 | 25-40 | 70-90 | 36.5-37.5 |
| Toddler (1-3y) | 90-130 | 20-30 | 80-100 | 36.5-37.5 |
| Preschool (4-5y) | 80-120 | 18-25 | 85-105 | 36.5-37.5 |
| School age (6-12y) | 70-110 | 16-22 | 90-115 | 36.5-37.5 |
| Adolescent (13-17y) | 60-100 | 14-20 | 100-130 | 36.5-37.5 |

#### Age-dependent lab reference ranges

| Lab | Neonate | Infant | Child (1-12y) | Adolescent |
|---|---|---|---|---|
| WBC (/uL) | 9,000-30,000 | 6,000-17,000 | 5,000-14,000 | 4,500-13,000 |
| Hb (g/dL) | 14-24 (drops to 10 at 2m) | 10-14 | 11.5-14.5 | 12-16 |
| Creatinine (mg/dL) | 0.2-0.5 | 0.2-0.4 | 0.3-0.7 | 0.5-1.0 |
| ALP (U/L) | 100-400 | 100-400 | 100-350 | 50-400 (growth spurt) |
| Glucose (mg/dL) | 40-100 | 60-100 | 70-100 | 70-100 |

The `derive_lab_values()` and `derive_vital_signs()` functions check `patient.age` and apply pediatric ranges when age < 18.

```python
def get_baseline_vitals_pediatric(age_years: int, sex: str) -> BaselineVitals:
    if age_years < 1:
        return BaselineVitals(temperature=37.0, heart_rate=130, systolic_bp=75,
                               diastolic_bp=45, respiratory_rate=35, spo2=97)
    elif age_years < 4:
        return BaselineVitals(temperature=37.0, heart_rate=110, systolic_bp=90,
                               diastolic_bp=55, respiratory_rate=25, spo2=97)
    elif age_years < 12:
        return BaselineVitals(temperature=36.8, heart_rate=90, systolic_bp=100,
                               diastolic_bp=65, respiratory_rate=20, spo2=98)
    else:  # adolescent
        return BaselineVitals(temperature=36.6, heart_rate=80, systolic_bp=110,
                               diastolic_bp=70, respiratory_rate=16, spo2=98)

def derive_lab_values_pediatric_adjustment(labs: dict, age_years: int) -> dict:
    """Adjust adult-derived lab values for pediatric normal ranges."""
    if age_years >= 18:
        return labs  # no adjustment for adults
    
    # Creatinine: much lower in children (less muscle mass)
    if age_years < 1:
        labs["Creatinine"] *= 0.3
    elif age_years < 6:
        labs["Creatinine"] *= 0.5
    elif age_years < 12:
        labs["Creatinine"] *= 0.7
    
    # WBC: higher normal in young children
    if age_years < 1:
        labs["WBC"] *= 1.5  # higher baseline
    elif age_years < 5:
        labs["WBC"] *= 1.3
    
    # Hb: varies significantly (physiological nadir at 2 months)
    if age_years < 1:
        labs["Hb"] = max(10.0, labs["Hb"] * 0.8)  # lower baseline
    
    return labs
```

#### Pediatric drug dosing
- All medications use mg/kg (or mg/m2 for some chemotherapy)
- Max dose capped at adult dose
- Many adult drugs are contraindicated (fluoroquinolones, tetracyclines in < 8y)
- Formulation matters: liquid for children who cannot swallow tablets

#### Pediatric disease mix

The diseases that bring children to the hospital are fundamentally different:

| Disease | Age group | Incidence pattern |
|---|---|---|
| Acute upper respiratory infection | All pediatric | Extremely common, usually outpatient |
| Acute gastroenteritis | 0-5y | Common, admission if dehydrated |
| Bronchiolitis (RSV) | 0-2y | Winter seasonal, admission ~3% of cases |
| Asthma exacerbation | 3-15y | Common, admission if severe |
| Febrile seizure | 6m-5y | ~3% of children experience at least once |
| Kawasaki disease | 6m-5y | JP: 300/100k < 5y (highest in world); US: 25/100k |
| Acute otitis media | 1-5y | Very common, usually outpatient |
| Croup | 6m-3y | Fall/winter, usually outpatient |
| Appendicitis | 5-15y | Surgical |
| Fractures | All (peak 10-14y) | Sports/play injuries |

These require separate disease protocol YAMLs under `disease/protocols/pediatric/`.

#### Pediatric encounter differences
- Parent/guardian always present (consent, history, decision-making)
- Pediatric wards (not mixed with adults)
- Child life specialist involvement
- Pain assessment: FLACC scale (pre-verbal) vs. NRS (older children)
- JP: 乳幼児医療費助成 (child medical expense subsidy) → near-zero copay
