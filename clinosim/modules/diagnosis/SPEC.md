# diagnosis — Diagnostic Reasoning Engine

## Purpose
Simulate the clinical diagnostic process: generate a differential diagnosis list, update probabilities via Bayesian reasoning as test results arrive, and converge (or fail to converge) on a final diagnosis.

## Inputs
- `PatientProfile`: Age, sex, medical history, presenting symptoms
- `DiseaseProtocol`: Prior probabilities and likelihood ratios from disease definitions
- `ObservationResults`: Lab results, imaging findings, culture results as they become available
- `HealthcareSystemConfig`: Country-specific diagnostic behavior (defensive medicine, test ordering patterns)

## Outputs
- `DifferentialDiagnosis`: Probability distribution over candidate diagnoses at each time step
- `DiagnosticDecision`: Confirmed/working diagnosis with timestamp and basis
- `TestOrderRequest`: Ordered tests with clinical intent (sent to observation module)
- `DiagnosticNarrative`: Evolving diagnosis codes over time (e.g., "Pneumonia, unspecified" → "Pneumonia due to S. pneumoniae")

## Dependencies
- `patient` (patient context for prior probability adjustment)
- `disease` (likelihood ratio tables, diagnostic criteria)
- `observation` (receives test results)
- `healthcare_system` (country-specific diagnostic behavior)

## Confirmed Specifications

### 3-phase diagnostic process

#### Phase 1: Hypothesis generation (differential diagnosis list)
- Enumerate candidate diseases from chief complaint
- Set prior probability for each candidate
  - Adjusted by age, sex, season, medical history, exposure history

#### Phase 2: Hypothesis testing (Bayesian update)
- Update each disease's probability as test results arrive:
```
P(Disease|Test) ∝ P(Test|Disease) × P(Disease)
                   ↑ likelihood ratio   ↑ prior
```

#### Phase 3: Diagnostic convergence
- Diagnosis is confirmed when probability exceeds a threshold (or remains unconfirmed if never reached)

### Therapeutic trial

| Trial | Indication | Evaluation window | Positive meaning |
|---|---|---|---|
| Antibiotic trial | Suspected pneumonia, unknown pathogen | 72 hours | Likely bacterial infection |
| Diuretic trial | Heart failure vs. pneumonia unclear | 4–6 hours | Cardiogenic pulmonary edema |
| Steroid trial | Unexplained inflammation/fever | 48–72 hours | Suggests autoimmune/inflammatory disease |

### Diagnostic "drift" patterns

| Pattern | Probability | Example |
|---|---|---|
| Initial misdiagnosis → correction | 15% | Pneumonia → lung cancer with obstructive pneumonia (CT reveals mass) |
| Multiple concurrent diseases | 20% | Pneumonia + heart failure exacerbation (common in elderly) |
| Unresolved diagnosis at discharge | 10% | Fever workup incomplete → continued in outpatient |
| Incidental finding | 8% | Renal mass found on CT during pneumonia admission |

### Impact on generated data
- Test ordering has traceable intent (Day 0: broad screening → Day 3: confirmatory tests)
- Treatment changes have documented triggers ("no improvement in 3 days → antibiotic switch")
- Diagnosis codes evolve over time
- Narrative records align with test results

---

## Internal Design

### Bayesian update engine

```python
def initialize_differential(patient: PatientProfile, disease_event: DiseaseEvent,
                             referral: ReferralContext | None,
                             disease_protocol: dict) -> DifferentialDiagnosis:
    """Create initial differential from disease protocol + patient context."""
    
    candidates = []
    for dx in disease_protocol["diagnostic"]["differential"]:
        prior = dx["prior"]
        
        # Adjust prior by patient demographics
        if patient.age >= 75:
            # Elderly: higher probability of multiple concurrent diseases
            if dx["disease"] in ["heart_failure_pulmonary_edema", "lung_cancer_with_obstruction"]:
                prior *= 1.5
        
        # Referral data adjusts priors
        if referral and referral.prior_findings:
            for finding in referral.prior_findings:
                lr = get_lr(dx["disease"], finding, disease_protocol)
                if lr:
                    prior *= lr["positive_LR"] if finding_is_positive(finding) else lr["negative_LR"]
        
        candidates.append(DiagnosisCandidate(
            disease_code=dx["disease"],
            icd_code=get_icd(dx["disease"]),
            display_name=get_display_name(dx["disease"]),
            probability=prior,
            evidence=[],
        ))
    
    # Normalize
    total = sum(c.probability for c in candidates)
    for c in candidates:
        c.probability /= total
    
    return DifferentialDiagnosis(
        candidates=sorted(candidates, key=lambda c: -c.probability),
        working_diagnosis=candidates[0].disease_code if candidates[0].probability > 0.5 else None,
        confirmed=False,
    )

def update_differential(current: DifferentialDiagnosis, new_results: list[OrderResult],
                         disease_protocol: dict) -> DifferentialDiagnosis:
    """Bayesian update on new test results."""
    
    lr_table = disease_protocol["diagnostic"]["likelihood_ratios"]
    
    for result in new_results:
        finding_key = result_to_finding_key(result)  # e.g., "chest_xray_consolidation"
        
        if finding_key not in lr_table:
            continue  # no LR data for this finding
        
        is_positive = interpret_result(result)  # True/False
        
        for candidate in current.candidates:
            dx = candidate.disease_code
            if dx in lr_table[finding_key]:
                lr = lr_table[finding_key][dx]
                if is_positive:
                    candidate.probability *= lr["positive_LR"]
                else:
                    candidate.probability *= lr["negative_LR"]
                
                candidate.evidence.append(f"{finding_key}: {'(+)' if is_positive else '(-)'}")
    
    # Normalize
    total = sum(c.probability for c in current.candidates)
    if total > 0:
        for c in current.candidates:
            c.probability /= total
    
    # Sort by probability
    current.candidates.sort(key=lambda c: -c.probability)
    
    # Check confirmation
    threshold = disease_protocol["diagnostic"]["confirmation_threshold"]  # e.g., 0.90
    if current.candidates[0].probability >= threshold:
        current.confirmed = True
        current.working_diagnosis = current.candidates[0].disease_code
    elif current.candidates[0].probability >= 0.5:
        current.working_diagnosis = current.candidates[0].disease_code
    
    return current
```

### Diagnosis code evolution

As confidence increases, the diagnosis code becomes more specific:

```python
def get_current_diagnosis_code(differential: DifferentialDiagnosis, 
                                disease_protocol: dict) -> tuple[str, str]:
    """Returns (ICD code, display name) based on current confidence."""
    
    progression = disease_protocol["diagnostic"]["diagnosis_progression"]
    confidence = differential.candidates[0].probability if differential.candidates else 0
    
    if differential.confirmed:
        # Use most specific code
        stage = progression[-1]  # e.g., {"code": "J13", "name": "Pneumonia due to S. pneumoniae"}
    elif confidence > 0.7:
        stage = progression[1]   # e.g., {"code": "J18.1", "name": "Lobar pneumonia, unspecified"}
    else:
        stage = progression[0]   # e.g., {"code": "J18.9", "name": "Pneumonia, unspecified"}
    
    return stage["code"], stage["name"]
```

### Diagnostic "drift" implementation

```python
def apply_diagnostic_drift(differential: DifferentialDiagnosis, patient: PatientProfile,
                            hospital_day: int) -> DifferentialDiagnosis:
    """Simulate misdiagnosis, dual pathology, incidental findings."""
    
    # Initial misdiagnosis → correction (15% probability, typically discovered Day 3-7)
    if hospital_day >= 3 and not differential.confirmed:
        if random() < 0.03:  # ~15% spread over days 3-7
            # Reveal the "true" diagnosis was different
            # Swap top two candidates or introduce a new one
            pass  # implementation depends on specific drift pattern
    
    # Dual pathology (20% in elderly)
    if patient.age >= 70 and hospital_day == 0:
        if random() < 0.20:
            # Add second active diagnosis
            secondary = generate_secondary_diagnosis(patient)
            differential.secondary_diagnosis = secondary
    
    # Incidental finding (8%)
    if hospital_day >= 2:
        if random() < 0.02:  # spread across hospital days
            incidental = generate_incidental_finding(patient)
            differential.incidental_findings.append(incidental)
    
    return differential
```

## Open Questions
- [ ] Confirmation threshold: 90% for pneumonia, but may be lower for empiric treatment decisions
- [ ] LR database: populated per disease YAML. Need comprehensive LR values from clinical literature.
- [ ] Dual pathology interaction: how two concurrent diseases affect each other's state trajectories

## Design Notes
### Call timing (from encounter module)
- `initialize_differential()`: Called at admission (inpatient) or assessment (ED). Receives patient context + presenting symptoms + referral data.
- `update()`: Called during daily morning rounds (inpatient) or when new results arrive (ED). Receives new lab/imaging results.
- `review_status()`: Called at outpatient follow-up. Reviews current diagnosis state against latest data.
- The encounter module determines WHEN these are called; the diagnosis module determines WHAT happens at each call.

### LLM integration points
All LLM calls below are made via `llm_service.request()`. See `llm_service/SPEC.md` for the centralized LLM interface.
- **Diagnostic reasoning narrative** (model: medium): At each `update()` call, the rule engine updates probabilities. The LLM then generates a clinical reasoning text explaining WHY the differential changed ("CXR shows lobar consolidation (LR+ 8.0), raising bacterial pneumonia probability from 45% to 78%"). This becomes the assessment section of the progress note.
- **Ambiguous differential resolution** (model: large): When the rule engine cannot clearly distinguish between top candidates (e.g., pneumonia 52% vs. heart failure 38%), the LLM is consulted via `ClinicalJudgmentRequest` to decide which additional tests to order and provide reasoning that reflects real clinical thinking.
- **Template mode fallback**: Without LLM, diagnostic reasoning is expressed as structured text: "Updated differential: Pneumonia 78% (↑ from 45% based on CXR consolidation)."
