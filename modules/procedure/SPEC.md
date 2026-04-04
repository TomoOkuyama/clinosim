# procedure — Surgical & Procedural Workflows

## Purpose
Model the workflow of surgeries and invasive procedures: pre-operative assessment, informed consent, the procedure itself, and post-operative recovery. Essential for hip fracture (Phase 1) and any surgical disease module.

## Inputs
- `Order`: Procedure order with type, urgency, indication
- `PatientProfile`: Age, comorbidities, anesthesia risk (ASA class)
- `Encounter`: Current encounter context
- `HospitalProfile`: OR availability, equipment (Mode 2: OR schedule)
- `StaffRoster`: Surgeon, anesthesiologist, OR nurses, assistants

## Outputs
- `ProcedureRecord`: Complete procedure documentation (participants, times, findings, complications)
- `AnesthesiaRecord`: Anesthesia type, induction/emergence times, intraoperative vitals
- `PreOpAssessment`: Pre-operative evaluation record
- `PostOpOrder`: Post-operative order set (pain management, DVT prophylaxis, diet advancement)
- `ProcedureComplication`: Intraoperative or immediate post-op complications

## Dependencies
- `order` (procedure order triggers workflow)
- `patient` (risk assessment)
- `encounter` (encounter context, transition to post-op phase)
- `facility` (OR availability, equipment)
- `staff` (surgical team assignment)
- `physiology` (patient state affects surgical risk and recovery)

## Confirmed Specifications

### Procedure categories

| Category | Examples | Typical setting |
|---|---|---|
| Major surgery | Hip replacement, open reduction internal fixation, CABG | Main OR, general anesthesia |
| Minor surgery | Abscess drainage, skin biopsy, central line placement | Minor procedure room or bedside |
| Endoscopy | Bronchoscopy, upper GI endoscopy, colonoscopy | Endoscopy suite, sedation |
| Interventional | Cardiac catheterization, angioplasty, embolization | Cath lab / angio suite |
| Bedside procedure | Thoracentesis, lumbar puncture, chest tube | Patient bedside |

### Procedure workflow state machine

#### Major surgery
```
procedure_ordered
  → pre_op_assessment (H&P, labs, imaging, anesthesia consult)
  → informed_consent_obtained
  → scheduled (OR date/time assigned)
  → day_of_surgery
      → pre_op_holding (final checks, IV access, marking)
      → in_operating_room
          → anesthesia_induction
          → procedure_in_progress (surgical time)
          → procedure_completed
          → anesthesia_emergence
      → recovery_room (PACU: Post-Anesthesia Care Unit)
      → post_op_ward_transfer (or ICU if complex)
  → post_op_monitoring (wound checks, pain management, drain management)
```

#### Minor/bedside procedure
```
procedure_ordered → consent → preparation → execution → documentation → monitoring
```

### Pre-operative assessment

| Item | Content |
|---|---|
| History & Physical | Updated within 24–48h of surgery |
| Lab work | CBC, coagulation, metabolic panel, type & screen |
| Imaging | Procedure-specific (e.g., hip X-ray for fracture surgery) |
| Anesthesia evaluation | ASA classification, airway assessment, anesthesia plan |
| Informed consent | Procedure, risks, alternatives, patient signature |
| Pre-op checklist | NPO status, allergies, implants, blood products available |

### ASA Physical Status Classification

| Class | Description | Approximate distribution |
|---|---|---|
| ASA I | Healthy | 10% |
| ASA II | Mild systemic disease | 35% |
| ASA III | Severe systemic disease | 35% |
| ASA IV | Life-threatening disease | 15% |
| ASA V | Moribund | 5% |

### Surgical timing

| Phase | Duration (major surgery) |
|---|---|
| Pre-op holding | 30–60 min |
| Anesthesia induction | 15–30 min |
| Surgical time | Procedure-dependent (hip fracture ORIF: 60–120 min) |
| Anesthesia emergence | 10–20 min |
| PACU recovery | 1–3 h |

### Intraoperative events and records

- Anesthesia record: vitals q5min, medications, fluid balance, blood loss
- Surgical note: procedure performed, findings, implants used, specimens sent
- Instrument/sponge count
- Estimated blood loss (EBL)
- Complications: bleeding, nerve injury, anesthesia-related

### Post-operative complications (probabilistic)

| Complication | Risk factors | Timing |
|---|---|---|
| Surgical site infection | Diabetes, obesity, long OR time | Day 3–7 |
| DVT / PE | Immobility, no prophylaxis, hip surgery | Day 2–14 |
| Anesthesia-related nausea | Female, history, volatile anesthetics | 0–24h |
| Urinary retention | Spinal anesthesia, elderly, opioids | 0–24h |
| Delirium | Elderly, ICU, opioids, anticholinergics | Day 1–5 |
| Wound dehiscence | Malnutrition, diabetes, obesity | Day 5–14 |

### Country-specific differences

| Aspect | Japan | US |
|---|---|---|
| Consent process | Family often co-signs; attending explains | Patient-centered; surgeon explains, witness required |
| Surgeon hierarchy | 執刀医 (operator) + 助手 (assistants); senior supervises | Attending surgeon of record (billing); residents may operate |
| Anesthesia staffing | Anesthesiologist (often 1:1) | Anesthesiologist supervising CRNA (1:2–4) possible |
| Post-op monitoring | Longer inpatient recovery accepted | Pressure for same-day or next-day discharge |
| Blood transfusion consent | Separate consent in Japan | Part of surgical consent (usually) |

### Phase 1 relevance: Hip fracture ORIF

```
ED arrival (fracture diagnosed)
  → inpatient admission → pre-op workup (1–2 days Japan, same-day/next-day US)
  → surgery (ORIF or hemiarthroplasty, 60–120 min)
  → post-op ward (pain management, DVT prophylaxis, drain monitoring)
  → rehab initiation (POD 1–2)
  → discharge (Japan: ~30 days; US: ~5 days → SNF/rehab facility)
```

### Mode 1 vs Mode 2 differences

| Aspect | Mode 1 | Mode 2 |
|---|---|---|
| OR scheduling | Immediate (no wait) | Competes with other cases; may be delayed |
| Surgical team | Assigned from specialty-appropriate staff | Actual OR schedule, team availability |
| PACU bed | Always available | May queue if PACU full |
| Emergency vs. elective priority | Not modeled | Emergency cases can bump elective schedule |

## Open Questions
- [ ] Level of detail for anesthesia record generation (full intraoperative vitals or summary?)
- [ ] Implant/device tracking data generation
- [ ] Surgical pathology specimen workflow (specimen → pathology lab → report in 3–7 days)
- [ ] Country-specific surgical coding (K-code vs. CPT) integration detail

### Rehabilitation model

Rehabilitation is critical for hip fracture (Phase 1) and stroke (Phase 2). PT/OT/ST sessions generate significant EHR data.

#### FIM (Functional Independence Measure) scoring

FIM is the standard functional assessment (18 items, each scored 1–7, total 18–126):

```python
@dataclass
class FIMScore:
    # Motor items (13 items, each 1-7)
    eating: int
    grooming: int
    bathing: int
    dressing_upper: int
    dressing_lower: int
    toileting: int
    bladder_management: int
    bowel_management: int
    transfer_bed: int
    transfer_toilet: int
    transfer_tub: int
    locomotion_walk: int
    locomotion_stairs: int
    
    # Cognitive items (5 items, each 1-7)
    comprehension: int
    expression: int
    social_interaction: int
    problem_solving: int
    memory: int
    
    @property
    def motor_total(self) -> int: ...     # 13–91
    @property
    def cognitive_total(self) -> int: ... # 5–35
    @property
    def total(self) -> int: ...           # 18–126
```

FIM assessment timing:
- Admission to rehab (baseline)
- Weekly during rehab stay
- Discharge from rehab
- Follow-up (1 month, 3 months)

#### Rehabilitation session records

```python
@dataclass
class RehabSession:
    session_id: str
    patient_id: str
    encounter_id: str
    therapist_id: str                      # PT, OT, or ST staff_id
    therapy_type: str                      # "PT" | "OT" | "ST"
    session_date: date
    duration_minutes: int                  # typically 20-60 min
    
    # Session content
    activities: list[str]                  # ["gait training", "stair climbing", "balance exercises"]
    patient_participation: str             # "good" | "fair" | "poor" | "refused"
    pain_during_session: int | None        # NRS 0-10
    
    # Progress
    functional_progress: str               # "improved" | "stable" | "declined"
    goals_addressed: list[str]             # ["independent ambulation", "ADL independence"]
    notes: str                             # session narrative
```

Rehab schedule:
- **JP acute hospital**: PT starts POD 1–2 for hip fracture. 20–40 min/day, 5–6 days/week.
- **JP rehab hospital (回復期リハ)**: Up to 3h/day, 7 days/week. Stay: 60–150 days.
- **US acute hospital**: PT consult POD 0–1. Brief sessions (20–30 min). Discharge to SNF/IRF in 3–5 days.
- **US SNF/IRF**: 1–3h/day. Stay: 2–4 weeks.

#### Hip fracture rehab trajectory (FIM progression)

```
Admission (POD 2):   FIM motor ~35/91 (mostly dependent)
Week 1:              FIM motor ~45 (some improvement in transfers)
Week 2:              FIM motor ~55 (walker ambulation emerging)
Week 3:              FIM motor ~65 (walker ambulation functional)
Week 4:              FIM motor ~72 (approaching modified independence)
Discharge (JP ~Day 30): FIM motor ~75 (modified independence with walker)
Discharge (US ~Day 5, to SNF): FIM motor ~45 (still needs significant assist)
```

Rehabilitation goal examples (hip fracture):
1. "Independent ambulation with walker on level surfaces by Week 3"
2. "Independent toilet transfer by Week 2"
3. "Independent stair climbing (4 steps) by Week 4"
4. "Modified independent ADLs by discharge"

---

## Internal Design

### Procedure execution algorithm

```python
def execute_procedure(order: Order, patient: PatientProfile, 
                       state: PhysiologicalState, encounter: Encounter,
                       hospital: HospitalProfile) -> ProcedureRecord:
    
    procedure_type = order.display_name
    
    # Pre-op: ASA classification from patient profile
    asa_class = calculate_asa(patient)
    
    # Surgical timing
    surgical_time = sample_surgical_duration(procedure_type)  # e.g., ORIF: Normal(90, 20) min
    anesthesia_induction = Normal(20, 5).sample()
    anesthesia_emergence = Normal(15, 5).sample()
    
    # Estimated blood loss
    ebl = sample_ebl(procedure_type, patient)  # hip ORIF: Normal(300, 150) mL
    
    # Intraoperative complications (probabilistic)
    complications = []
    for comp_spec in get_intraop_complications(procedure_type):
        risk = comp_spec["base_rate"]
        for rf in comp_spec["risk_factors"]:
            if evaluate_condition(rf["condition"], patient):
                risk *= rf["multiplier"]
        if random() < risk:
            complications.append(comp_spec["name"])
    
    # Intraoperative state changes → feed back to physiology
    intraop_effects = []
    # Blood loss → anemia
    if ebl > 200:
        hb_drop = ebl / 500 * 0.1  # rough: 500mL ≈ 1 unit ≈ Hb drop ~1
        intraop_effects.append(InterventionEffect(type="blood_loss", 
                                details={"anemia_increase": hb_drop}))
    # Fluid administration (typically 1-3L crystalloid during surgery)
    intraop_effects.append(InterventionEffect(type="iv_fluid_bolus",
                            details={"volume_ml": Normal(1500, 500).sample()}))
    # If blood loss > 800mL, transfusion likely
    if ebl > 800:
        units = max(1, int(ebl / 500))
        intraop_effects.append(InterventionEffect(type="blood_transfusion",
                                details={"units": units}))
    
    for effect in intraop_effects:
        physiology.apply_intervention(state, effect)
    
    # Generate record
    record = ProcedureRecord(
        procedure_code=get_procedure_code(procedure_type, patient.country),
        procedure_name=procedure_type,
        category=get_category(procedure_type),
        start_datetime=order.scheduled_events.collection_time,
        end_datetime=order.scheduled_events.collection_time + timedelta(minutes=surgical_time),
        anesthesia_type=select_anesthesia(procedure_type, patient),
        primary_surgeon_id=staff.assign_staff("surgery", encounter, ...)[0].staff_id,
        estimated_blood_loss_ml=int(ebl),
        complications=complications,
        asa_class=asa_class,
    )
    
    # Post-op orders (auto-generated)
    post_op_orders = generate_post_op_orders(procedure_type, patient, record)
    # DVT prophylaxis, pain management, wound care, diet advancement
    
    return record

def calculate_asa(patient: PatientProfile) -> int:
    score = 1  # healthy
    conditions = len(patient.chronic_conditions)
    if conditions >= 1: score = 2
    if conditions >= 2 or any(c.severity == "severe" for c in patient.chronic_conditions): score = 3
    if patient.cardiac_function < 0.4 or patient.renal_function < 0.3: score = 4
    return score
```

## Design Notes
- The procedure module is invoked by the order module when a procedure order reaches the "scheduled" / "in_progress" state
- Intraoperative physiology changes (blood loss → anemia, fluid administration → volume status change) feed back to the physiology module via `InterventionEffect`
- Post-operative orders are auto-generated and placed through the order module
- For Phase 1, hip fracture is the primary driver; pneumonia and heart failure rarely need this module
- Operative note narrative is generated via llm_service (NARRATIVE task type)
