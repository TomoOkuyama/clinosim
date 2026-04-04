# treatment — Medication & Treatment Model

## Purpose
Model drug selection, dosing, therapeutic response, and medication adherence. Handles guideline-based first-line therapy, alternatives, dose adjustments, and treatment failure/switching logic.

## Inputs
- `PatientProfile`: Weight, renal function, allergies, drug metabolism rate
- `DiagnosticDecision`: Current working diagnosis
- `DiseaseProtocol`: Guideline-based treatment protocol
- `PhysiologicalState`: Current organ function (for dose adjustment)
- `HealthcareSystemConfig`: Country-specific drug codes, formulary constraints

## Outputs
- `TreatmentPlan`: Active medications with dosing schedule
- `TreatmentEvent`: Drug initiation, dose change, switch, or discontinuation (with reason)
- `TreatmentEffect`: Expected physiological effect (fed back to clinical_course)
- `AdherenceRecord`: Post-discharge medication adherence simulation

## Dependencies
- `patient` (weight, allergies, metabolism rate)
- `diagnosis` (determines treatment indication)
- `disease` (treatment protocol definitions)
- `physiology` (organ function for dose adjustment)
- `healthcare_system` (drug coding, cost-related adherence)

## Confirmed Specifications

### Treatment logic
- Guideline-based first-line / alternative drug selection
- Dose adjusted by body weight, renal function, and age
- Allergy and contraindication checks
- Drug interaction checks
- Probabilistic treatment response modeling:
  - Effect onset timing (e.g., antibiotics evaluated at 72 hours)
  - Treatment failure rate and adverse event rate
  - Treatment change triggers

### Medication adherence model (pattern-based)

Inpatient adherence is ~100% (nurse-administered). Post-discharge adherence depends on the patient's `adherence_pattern`:

| Pattern | Mechanism | Effective rate | Outcome impact |
|---|---|---|---|
| `full_compliance` | Takes all medications as prescribed | 95% | Best outcomes |
| `good_when_symptomatic` | Stops medication when feeling well; restarts when symptomatic | 40–60% for maintenance meds | HF/HT: frequent exacerbations due to "drug holidays" |
| `cost_skipping` | Stretches prescriptions (takes every other day, splits pills) | 50–70% | Subtherapeutic levels; common in US uninsured |
| `side_effect_avoidance` | Reduces dose or skips specific medication due to perceived side effects | 60–80% (skips one drug) | e.g., statin discontinued due to myalgia |
| `forgetful` | Random missed doses, especially evening/night doses | 70–85% | Variable drug levels; worse with complex regimens |
| `weekend_holiday` | Skips on weekends or when routine disrupted | 80% (weekday), 30% (weekend) | Anticoagulant: weekend bleeding/clotting events |
| `alternative_substitution` | Replaces prescribed medication with alternative (kampo, supplements) | 20–50% (for substituted drugs) | Drug interactions, subtherapeutic treatment |

```python
def simulate_post_discharge_adherence(patient, medications, days_since_discharge):
    pattern = patient.adherence_pattern
    
    # Depression modifier
    if "depression" in patient.mental_health_conditions:
        effective_modifier = 0.7  # depression reduces all patterns
    else:
        effective_modifier = 1.0
    
    # Time decay: adherence tends to drop over weeks
    time_decay = max(0.7, 1.0 - days_since_discharge * 0.003)  # ~10% drop over 30 days
    
    for med in medications:
        base_adherence = pattern.effective_adherence_rate
        
        if pattern.pattern_type == "cost_skipping" and med.monthly_cost > pattern.cost_threshold_monthly:
            base_adherence *= 0.5
        elif pattern.pattern_type == "good_when_symptomatic" and not med.produces_noticeable_effect:
            base_adherence *= 0.4  # asymptomatic meds (HT, lipids) get skipped
        
        effective = base_adherence * effective_modifier * time_decay
        med.actual_adherence = effective
```

The adherence pattern determines:
1. Whether chronic conditions remain controlled (affects future disease events in population module)
2. Readmission risk (non-adherent HF/COPD patients readmit at 2–3× the rate)
3. Lab values at follow-up visits (HbA1c reflects ~3 months of adherence)

### End-of-life treatment modifications

When a patient has an advance directive with restrictive code status, treatment intensity is modified:

| Code status | Treatment modifications |
|---|---|
| `full_code` | No restrictions. Full ICU, CPR, intubation, all interventions. |
| `DNR` | No CPR. All other treatments continue (antibiotics, surgery, ICU). |
| `DNR_DNI` | No CPR, no intubation. May still receive IV medications, monitoring. |
| `comfort_only` | Symptom management only. Discontinue curative treatments. Focus on pain, dyspnea, anxiety relief. Minimal labs (only if results would change comfort management). |

```python
def apply_advance_directive(treatment_plan, patient):
    ad = patient.advance_directive
    if ad is None or ad.code_status == "full_code":
        return treatment_plan  # no modification
    
    if ad.code_status == "comfort_only":
        treatment_plan.remove_curative_medications()
        treatment_plan.add_palliative_medications()  # morphine, midazolam, scopolamine
        treatment_plan.reduce_monitoring("minimal")
        treatment_plan.discontinue_labs(except_for=["comfort_relevant"])
        treatment_plan.cancel_pending_procedures()
    
    if ad.code_status in ["DNR", "DNR_DNI"]:
        treatment_plan.set_code_status(ad.code_status)
        # Other treatments continue as planned
```

## Open Questions
- [ ] ~~Treatment effect probability model: binary or continuous?~~ **Resolved: continuous** (see clinical_course)
- [ ] Drug interaction database scope and source
- [ ] Country-specific formulary and cost modeling detail level
- [ ] Monthly drug cost data for "cost_skipping" pattern modeling (US)
- [ ] Palliative care medication protocols (comfort care pathway)

---

## Internal Design

### Drug selection algorithm

```python
def select_medication(patient: PatientProfile, diagnosis: DifferentialDiagnosis,
                       disease_protocol: dict, config: HealthcareSystemConfig) -> MedicationOrderDetail:
    """Select appropriate medication based on protocol + patient factors."""
    
    country = config.country.lower()
    med_protocol = disease_protocol["order_protocols"]["admission_orders"]["medications"]
    
    # Start with first-line for this country
    candidate = med_protocol["first_line"][country]
    
    # Allergy check
    if is_allergic(patient, candidate["drug"]):
        allergy_class = get_allergy_class(patient, candidate["drug"])
        alt_key = f"alternative_{allergy_class}_allergy"
        if alt_key in med_protocol:
            candidate = med_protocol[alt_key][country]
        else:
            # No alternative in protocol — flag for physician review
            candidate["requires_review"] = True
    
    # Dose adjustment for renal function
    dose = parse_dose(candidate["dose"])
    egfr = patient.baseline_labs.get("eGFR", 90)
    if egfr < 30:
        dose = adjust_for_renal(candidate["drug"], dose, egfr)  # per drug-specific rules
    elif egfr < 60:
        dose = adjust_for_renal(candidate["drug"], dose, egfr)
    
    # Dose adjustment for weight (pediatric/obese)
    if patient.weight_kg > 100 or patient.weight_kg < 50:
        dose = adjust_for_weight(candidate["drug"], dose, patient.weight_kg)
    
    # CYP metabolism adjustment
    if patient.physiological_profile.drug_metabolism_rate == "poor":
        if drug_is_cyp_dependent(candidate["drug"]):
            dose = reduce_dose(dose, 0.5)  # 50% reduction for poor metabolizers
    elif patient.physiological_profile.drug_metabolism_rate == "ultra_rapid":
        if drug_is_cyp_dependent(candidate["drug"]):
            dose = increase_dose(dose, 1.3)  # may need higher dose
    
    # Drug interaction check against current medications
    interactions = check_interactions(candidate["drug"], patient.current_medications)
    if interactions:
        for interaction in interactions:
            if interaction.severity == "contraindicated":
                # Switch to alternative
                candidate = find_non_interacting_alternative(med_protocol, patient)
            elif interaction.severity == "major":
                candidate["interaction_warning"] = interaction.description
    
    # Pregnancy check
    if patient.pregnancy_state:
        if is_pregnancy_contraindicated(candidate["drug"]):
            candidate = find_pregnancy_safe_alternative(med_protocol, patient)
    
    return MedicationOrderDetail(
        drug_code=candidate.get(f"code_{config.drug_code_system.lower()}", ""),
        drug_name=candidate["drug"],
        dose=dose.value,
        dose_unit=dose.unit,
        route=parse_route(candidate["dose"]),
        frequency=parse_frequency_str(candidate["dose"]),
        duration=candidate.get("duration"),
    )
```

### Treatment response evaluation

Called during daily rounds by encounter module:

```python
def evaluate_response(patient: PatientProfile, state: PhysiologicalState,
                       treatment_plan: list[Order], hospital_day: int,
                       disease_protocol: dict) -> TreatmentDecision:
    """Evaluate whether current treatment is working and decide next action."""
    
    # Check protocol-defined triggers
    for trigger_name, trigger in disease_protocol["order_protocols"]["trigger_orders"].items():
        if evaluate_trigger_condition(trigger["condition"], state, hospital_day):
            # Trigger fired — action needed
            actions = trigger["actions"]
            for action in actions:
                if action["type"] == "medication_change":
                    return TreatmentDecision(
                        decision="change",
                        action=action["action"],  # e.g., "escalate_antibiotic"
                        reason=trigger_name,       # e.g., "no_defervescence_72h"
                    )
            
    # No trigger fired — continue current treatment
    return TreatmentDecision(decision="continue", reason="on_track")
```

### Intervention effect generation

When treatment decisions produce immediate physiological effects:

```python
def generate_intervention_effects(decision: TreatmentDecision, 
                                    patient: PatientProfile) -> list[InterventionEffect]:
    effects = []
    
    match decision.action:
        case "start_iv_fluid":
            effects.append(InterventionEffect(type="iv_fluid_bolus", details={"volume_ml": 500}))
        case "start_vasopressor":
            effects.append(InterventionEffect(type="vasopressor_start", details={"drug": "norepinephrine"}))
        case "give_diuretic":
            effects.append(InterventionEffect(type="diuretic_dose", details={"drug": "furosemide", "dose_mg": 20}))
        case "transfuse_rbc":
            effects.append(InterventionEffect(type="blood_transfusion", details={"units": 2}))
        # Antibiotics: no immediate effect (works through clinical_course over days)
        case "escalate_antibiotic" | "start_antibiotic":
            pass
    
    return effects
```

### Prescription model (outpatient / discharge)

#### Japan: 院外処方箋 (external pharmacy prescription)

Most Japanese hospital prescriptions are dispensed at external pharmacies (院外処方 ~75%).

```python
@dataclass
class PrescriptionJP:
    prescription_id: str
    patient_id: str
    prescriber_id: str                     # physician staff_id
    prescriber_department: str
    issue_date: date
    valid_days: int                        # typically 4 days for outpatient
    
    items: list[PrescriptionItemJP]
    
    dispensing_pharmacy: str | None         # filled after patient visits pharmacy
    dispensing_date: date | None

@dataclass
class PrescriptionItemJP:
    drug_name_generic: str                 # 一般名 (e.g., "アムロジピンベシル酸塩")
    drug_name_brand: str | None            # 商品名 (e.g., "ノルバスク" or "アムロジピンOD錠「サワイ」")
    generic_substitution: str              # "permitted" (変更可) | "not_permitted" (変更不可)
    not_permitted_reason: str | None       # if not_permitted: "narrow_therapeutic_index" | "patient_preference"
    yj_code: str                           # YJ code (12 digits)
    dose: str                              # "5mg"
    frequency: str                         # "1日1回朝食後" / "1日3回毎食後" / etc.
    days_supply: int                       # 14, 28, 56, 90 days
    total_quantity: str                    # "14錠" / "42錠"
    route: str                             # "内服" | "外用" | "注射" | etc.
    instructions: str                      # specific instructions (JP format)

# Generic substitution rates
# JP: ~80% of prescriptions written as generic name; ~78% dispensed as generic (2023)
# Policy: government target 80%+ generic dispensing rate
```

Prescription timing:
- **Inpatient → discharge**: Prescription issued at discharge for 7–14 days of oral medications
- **Outpatient**: Prescription issued at checkout; supply typically 28–90 days (longer for stable chronic conditions)
- **Chronic management (JP)**: Some hospitals do 90-day prescriptions for stable patients (reduces visit frequency)

#### US: Electronic prescription

```python
@dataclass
class PrescriptionUS:
    prescription_id: str
    patient_id: str
    prescriber_id: str
    prescriber_npi: str                    # National Provider Identifier
    
    items: list[PrescriptionItemUS]
    
    pharmacy_id: str                       # designated pharmacy
    sent_electronically: bool              # e-prescribing (required for controlled substances in many states)

@dataclass
class PrescriptionItemUS:
    drug_name: str                         # typically brand or generic
    rxnorm_code: str
    ndc_code: str | None                   # National Drug Code (for dispensing)
    dose: str
    frequency: str                         # "BID" | "TID" | "QHS" | etc.
    route: str
    quantity: int                          # number of units
    days_supply: int                       # 30 or 90
    refills: int                           # 0-11 (controlled: 0-5)
    daw_code: int                          # Dispense As Written (0=sub permitted, 1=brand required)
    prior_authorization_required: bool     # for high-cost drugs
    formulary_tier: int | None             # 1 (generic) to 4 (specialty)
```

Key differences affecting data:
| Aspect | Japan | US |
|---|---|---|
| Generic name prescribing | ~80% written generically | Varies (brand still common) |
| Supply duration | 14–90 days (often 28) | 30 or 90 days |
| Refills | Not applicable (new prescription each visit) | 0–11 refills per prescription |
| Dispensing | 院外薬局 (external pharmacy, ~75%) | Patient's chosen pharmacy |
| Prior authorization | Rare | Common for expensive drugs |
| E-prescribing | Increasingly adopted | Mandated in most states |

## Design Notes
### Input from disease module
- Disease protocol YAML defines first-line and alternative medications per country (`order_protocols.admission_orders.medications`)
- Treatment changes are triggered by protocol-defined conditions (`trigger_orders.medication_change`)
- Discharge medications are specified per country (`discharge_protocol.discharge_medications`)
- The treatment module applies patient-specific adjustments (allergy, renal function, CYP metabolism) on top of the protocol's recommendations
- Treatment response is evaluated using the clinical_course module's state trajectory: if the archetype indicates "treatment_resistant", the encounter triggers the protocol's medication escalation at the specified day

### LLM integration points
All LLM calls below are made via `llm_service.request()`. See `llm_service/SPEC.md` for the centralized LLM interface.
- **Treatment rationale generation** (model: medium): When a treatment decision is made (initiation, change, discontinuation), the LLM generates a rationale text: "Switching from ABPC/SBT to meropenem given persistent fever at 72h, negative cultures, and concern for resistant gram-negative coverage." This becomes part of the progress note.
- **Treatment selection at ambiguous points** (model: medium): When multiple guideline-appropriate options exist (e.g., add fluoroquinolone vs. add macrolide for atypical coverage), the LLM selects based on patient context and generates reasoning that reflects real clinical preference patterns.
- **Discharge medication counseling text** (model: small): Generate patient-facing medication instruction text ("この薬は1日3回食後に服用してください" / "Take this medication three times daily with meals").
- **Template mode fallback**: Treatment rationale is expressed as structured text: "Treatment changed: ABPC/SBT → MEPM. Reason: no_defervescence_72h trigger."
