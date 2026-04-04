# order — Order Lifecycle Management

## Purpose
Manage the full lifecycle of clinical orders: from order entry through execution to result reporting. Provides a unified model for lab orders, imaging orders, medication orders, procedure orders, and consultation requests — each with appropriate timing, delays, and status tracking.

## Inputs
- `DiagnosticDecision` / `TreatmentPlan`: Clinical decisions that generate orders
- `EncounterEvent`: Current encounter context (determines ordering patterns and urgency)
- `HealthcareSystemConfig`: Country-specific ordering patterns
- `HospitalProfile`: Available equipment and services (Mode 2: current queue status)
- `StaffRoster`: Ordering physician, executing staff

## Outputs
- `Order`: Structured order with type, urgency, status, timestamps
- `OrderEvent`: State transitions in the order lifecycle (placed → collected → resulted)
- `OrderResult`: Final result linked back to the order (lab value, imaging report, etc.)

## Dependencies
- `encounter` (provides workflow context and urgency level)
- `diagnosis` / `treatment` (generates order requests)
- `staff` (ordering and executing practitioners)
- `facility` (equipment availability)
- `observation` (receives lab/imaging orders, returns results)

## Confirmed Specifications

### Order types

| Order type | Examples | Key lifecycle |
|---|---|---|
| `lab` | CBC, CRP, blood culture, urinalysis | Order → specimen collection → lab processing → result → review |
| `imaging` | X-ray, CT, MRI, ultrasound | Order → scheduling → procedure → image acquisition → interpretation → report |
| `medication` | IV antibiotics, oral meds, PRN | Order → pharmacy verification → dispensing → administration → monitoring |
| `procedure` | Central line, intubation, surgery | Order → consent → scheduling → preparation → execution → documentation |
| `consultation` | Cardiology consult, ID consult | Order → notification → specialist review → consultation note → recommendations |
| `diet` | NPO, clear liquids, regular, diabetic, renal, low-salt, tube feeding | Order → kitchen notification → meal delivery. Diet advancement: NPO→clear→soft→regular |
| `therapy` | PT, OT, speech therapy | Order → scheduling → session → progress note |
| `infection_control` | Standard, contact, droplet, airborne precautions | Order → nursing notification → isolation setup → PPE compliance monitoring |
| `nutrition_consult` | Dietitian consultation | Order → scheduling → assessment → recommendation note |

### Order lifecycle state machine

```
draft → placed → accepted
                    ├── lab:        collecting → processing → resulted → reviewed
                    ├── imaging:    scheduled → in_progress → interpreted → reported → reviewed
                    ├── medication: verified → dispensed → administered → (next dose...)
                    ├── procedure:  consented → scheduled → in_progress → completed → documented
                    ├── consult:    notified → in_progress → completed → reviewed
                    └── ...
                    
Any state → cancelled (with reason)
Any state → modified (creates new version)
```

### Timing model

Each transition has a delay drawn from a distribution that depends on:
- Order urgency (STAT / urgent / routine)
- Time of day (business hours vs. night/weekend)
- Hospital scale (large hospital = faster in-house processing)
- Country norms

| Transition | STAT | Urgent | Routine |
|---|---|---|---|
| Lab: order → collection | 5–15 min | 15–30 min | 30–120 min |
| Lab: collection → result | 30–60 min | 1–2 h | 2–4 h |
| Lab: blood culture → final | — | — | 48–72 h |
| Imaging: order → procedure (X-ray) | 15–30 min | 1–2 h | 2–8 h |
| Imaging: order → procedure (CT) | 30–60 min | 2–4 h | 4–24 h |
| Imaging: procedure → report | 15–30 min | 1–2 h | 2–8 h |
| Medication: order → first dose (IV) | 10–30 min | 30–60 min | 1–2 h |
| Consult: order → initial review | 30–60 min | 2–4 h | 4–24 h |

### Night/weekend effects

| Factor | Impact |
|---|---|
| Night (22:00–06:00) | Only STAT orders processed; routine deferred to morning |
| Weekend | Reduced lab menu; non-urgent imaging deferred; fewer consultants |
| Holiday | Similar to weekend but more severe; skeleton staffing |

### Order sets (bundled orders)

Disease protocols define order sets — groups of orders placed together:
- Admission order set (labs + imaging + meds + diet + activity level)
- Daily monitoring set (vitals schedule + routine labs)
- Pre-op order set
- Discharge order set (prescriptions + follow-up appointments)

These are defined in the `disease` module's protocol YAML and executed by the `order` module.

### Mode 1 vs Mode 2 differences

| Aspect | Mode 1 | Mode 2 |
|---|---|---|
| Processing delays | Drawn from timing distributions | Adjusted by current queue length |
| Equipment availability | Always available | CT/MRI may have wait queue |
| Lab batching | Not modeled | Routine labs batched for morning draw |
| Medication availability | Always in stock | Pharmacy inventory constraints possible |

### Temporal effects on order processing

Order turnaround times are not constant — they vary by time-of-day, day-of-week, season, and equipment load:

| Factor | Effect on turnaround |
|---|---|
| **Night (22:00–06:00)** | Only STAT processed; routine queued for morning. Lab turnaround +30–60 min (skeleton staff) |
| **Weekend** | Reduced lab menu (some tests batched for Monday). Non-urgent imaging deferred. No pathology processing |
| **Monday morning** | Backlog from weekend: lab queue spike, imaging schedule packed |
| **Health checkup season (JP, May–Oct)** | Morning lab and imaging capacity partially consumed by checkup patients; clinical orders may be delayed |
| **Year-end/holidays** | Outsourced labs have longer turnaround (courier schedules). Minimum staffing |
| **Equipment downtime** | Orders rerouted or deferred; STAT imaging may require ambulance transfer to nearby facility (small hospitals) |

### Equipment capacity constraints

Order processing time depends on equipment throughput (defined in `facility`):
- When equipment utilization > 80%: routine orders experience increasing delays
- When utilization > 95%: only STAT orders processed; routine deferred
- Mode 1: delays drawn from distributions that implicitly reflect average load
- Mode 2: actual queue-based processing with real contention

---

## Internal Design

### Core concept: Order as time-bound event stream

The order module converts clinical decisions into a stream of time-stamped events. Each order creates multiple events (placed, collected, resulted, reviewed) with realistic time gaps. This event stream drives the observation module (when to generate lab values) and the nursing module (when to administer medications).

```
Clinical decision (encounter/diagnosis/treatment)
  ↓
order.place_from_protocol(protocol_orders, patient, context)
  ↓
For each order:
  1. Create Order with status=PLACED, timestamp=now
  2. Calculate transition times:
     placed → next_state: sample from timing distribution(urgency, time_of_day, facility)
  3. Schedule future events:
     collection_time, result_time, review_time
  4. At collection_time:
     → nursing module collects specimen (or radiology performs scan)
     → observation module generates value at this timepoint using physiology state
  5. At result_time:
     → Order.result populated with observation-generated value
     → Order.status = RESULTED
  6. At review_time:
     → staff.assign_reviewer → physician reviews result
     → diagnosis/treatment may react to result (feedback loop)
```

### Protocol expansion algorithm

Converts disease protocol YAML into concrete orders:

```python
def place_from_protocol(protocol_section: str, patient: PatientProfile, 
                         encounter: Encounter, disease_protocol: dict,
                         healthcare_config: HealthcareSystemConfig) -> list[Order]:
    """
    Expand a protocol section (admission_orders, daily_monitoring, trigger) 
    into concrete Order instances.
    """
    orders = []
    protocol = disease_protocol["order_protocols"][protocol_section]
    
    # Labs
    for lab_spec in protocol.get("labs", []):
        # Check if this lab is available at this facility
        if not facility_has_lab(lab_spec["test"], encounter.hospital):
            if lab_spec.get("urgency") == "stat":
                # STAT but not available: mark as outsourced with longer turnaround
                lab_spec["outsourced"] = True
            else:
                continue  # skip unavailable routine tests at small hospitals
        
        # Apply country-specific frequency multiplier for daily monitoring
        if protocol_section == "daily_monitoring":
            freq = lab_spec.get("frequency", "daily")
            multiplier = healthcare_config.lab_frequency_multiplier
            if multiplier < 1.0 and freq == "daily":
                # US: some daily labs become every-other-day
                if random() > multiplier:
                    continue  # skip this day
        
        order = Order(
            order_id=generate_id(),
            encounter_id=encounter.encounter_id,
            patient_id=patient.patient_id,
            order_type=OrderType.LAB,
            order_code=lab_spec.get(f"code_{healthcare_config.lab_code_system.lower()}", lab_spec["test"]),
            display_name=lab_spec["test"],
            urgency=lab_spec.get("urgency", "routine"),
            clinical_intent=f"{protocol_section}: {lab_spec['test']}",
            ordered_datetime=encounter.current_time,
            status=OrderStatus.PLACED,
        )
        
        # Calculate timeline
        timeline = calculate_order_timeline(order, encounter, patient.hospital)
        order.scheduled_events = timeline
        orders.append(order)
    
    # Imaging
    for img_spec in protocol.get("imaging", []):
        # Similar expansion logic...
        order = create_imaging_order(img_spec, encounter, patient)
        orders.append(order)
    
    # Medications
    for med_spec in protocol.get("medications", {}).get(healthcare_config.country.lower(), []):
        order = create_medication_order(med_spec, patient, encounter)
        # Allergy check
        if is_allergic(patient, order.medication_details.drug_code):
            # Switch to alternative
            alt = protocol["medications"].get("alternative_" + get_allergy_class(patient))
            if alt:
                order = create_medication_order(alt, patient, encounter)
            else:
                order.note = "ALLERGY - requires physician review"
        orders.append(order)
    
    return orders
```

### Timing generation engine

```python
@dataclass
class TimingDistribution:
    mean_minutes: float
    sd_minutes: float
    min_minutes: float
    max_minutes: float

# Base timing tables (loaded from YAML config)
LAB_TIMING = {
    # (urgency, transition) → TimingDistribution
    ("stat", "placed_to_collected"):     TimingDistribution(10, 5, 3, 20),
    ("stat", "collected_to_resulted"):   TimingDistribution(45, 15, 20, 90),
    ("urgent", "placed_to_collected"):   TimingDistribution(25, 10, 10, 60),
    ("urgent", "collected_to_resulted"): TimingDistribution(90, 30, 40, 180),
    ("routine", "placed_to_collected"):  TimingDistribution(60, 30, 20, 180),
    ("routine", "collected_to_resulted"):TimingDistribution(180, 60, 60, 480),
}

IMAGING_TIMING = {
    ("stat", "xray", "placed_to_performed"):    TimingDistribution(20, 10, 10, 45),
    ("stat", "ct", "placed_to_performed"):      TimingDistribution(45, 20, 15, 90),
    ("stat", "mri", "placed_to_performed"):     TimingDistribution(120, 45, 60, 240),
    ("routine", "xray", "placed_to_performed"): TimingDistribution(180, 90, 60, 480),
    ("routine", "ct", "placed_to_performed"):   TimingDistribution(360, 120, 120, 1440),
    # Interpretation timing
    ("stat", "any", "performed_to_reported"):   TimingDistribution(25, 10, 10, 60),
    ("routine", "any", "performed_to_reported"):TimingDistribution(180, 60, 60, 480),
}

MEDICATION_TIMING = {
    ("stat", "iv", "placed_to_administered"):    TimingDistribution(20, 10, 5, 45),
    ("urgent", "iv", "placed_to_administered"):  TimingDistribution(45, 15, 15, 90),
    ("routine", "iv", "placed_to_administered"): TimingDistribution(90, 30, 30, 180),
    ("routine", "po", "placed_to_administered"): TimingDistribution(60, 20, 20, 120),
}

def calculate_order_timeline(order: Order, encounter: Encounter, 
                              hospital: HospitalProfile) -> OrderTimeline:
    """Generate realistic timestamps for each order state transition."""
    
    placed = order.ordered_datetime
    urgency = order.urgency
    
    # Get base timing
    if order.order_type == OrderType.LAB:
        collect_dist = LAB_TIMING[(urgency, "placed_to_collected")]
        result_dist = LAB_TIMING[(urgency, "collected_to_resulted")]
    elif order.order_type == OrderType.IMAGING:
        modality = get_imaging_modality(order)
        collect_dist = IMAGING_TIMING[(urgency, modality, "placed_to_performed")]
        result_dist = IMAGING_TIMING[(urgency, "any", "performed_to_reported")]
    elif order.order_type == OrderType.MEDICATION:
        route = order.medication_details.route
        collect_dist = MEDICATION_TIMING[(urgency, route, "placed_to_administered")]
        result_dist = None  # medications don't have "results" in the same way
    
    # Apply temporal modifiers
    hour = placed.hour
    is_night = hour < 6 or hour >= 22
    is_weekend = placed.weekday() >= 5
    
    time_modifier = 1.0
    if is_night:
        if urgency == "routine":
            # Routine at night: defer to morning
            next_morning = placed.replace(hour=6, minute=30) + timedelta(days=1 if hour >= 6 else 0)
            return OrderTimeline(
                collection_time=next_morning,
                result_time=next_morning + timedelta(minutes=result_dist.sample()),
                deferred_reason="night_routine_deferred",
            )
        time_modifier *= 1.4  # STAT at night: slower (fewer staff)
    
    if is_weekend:
        time_modifier *= 1.3
    
    # Apply hospital scale modifier
    if hospital.scale == "small":
        time_modifier *= 1.5  # smaller hospitals generally slower
        # Check if test is outsourced
        if order.order_type == OrderType.LAB and order.display_name not in hospital.lab_capacity.in_house_menu:
            # Outsourced: result comes next business day
            next_pickup = get_next_lab_pickup_time(placed, hospital)
            return OrderTimeline(
                collection_time=placed + timedelta(minutes=collect_dist.sample()),
                result_time=next_pickup + timedelta(hours=hospital.lab_capacity.outsource_turnaround_days * 24),
                outsourced=True,
            )
    
    # Sample actual times
    collect_delay = collect_dist.sample() * time_modifier
    collected = placed + timedelta(minutes=collect_delay)
    
    if result_dist:
        result_delay = result_dist.sample() * time_modifier
        resulted = collected + timedelta(minutes=result_delay)
    else:
        resulted = None
    
    # Physician review: typically within 30 min for STAT, 2-4h for routine
    if resulted:
        review_delay = 30 if urgency == "stat" else Normal(120, 60).sample()
        reviewed = resulted + timedelta(minutes=max(10, review_delay))
    else:
        reviewed = None
    
    return OrderTimeline(collected, resulted, reviewed)
```

### Integration with observation module

When a lab order reaches "collecting" state, the observation module is called to generate the actual value:

```python
def on_specimen_collected(order: Order, state_history: list[PhysiologicalState],
                           patient: PatientProfile) -> OrderResult:
    """Called when specimen collection event occurs."""
    
    collection_time = order.scheduled_events.collection_time
    
    # Get the physiological state at collection time (with temporal lag per marker)
    effective_state = physiology.get_effective_state_for_lab(
        order.display_name, collection_time, state_history
    )
    
    # Derive the "true" lab value from state
    true_value = physiology.derive_lab_values(effective_state, patient, collection_time)
    lab_name = order.display_name
    base_value = true_value[lab_name]
    
    # Apply Layer 3: observation noise and artifacts
    final_value = observation.apply_noise(lab_name, base_value, patient, collection_time)
    
    # Determine flags
    ref_range = get_reference_range(lab_name, patient)
    flag = None
    if final_value > ref_range.high:
        flag = "H"
    elif final_value < ref_range.low:
        flag = "L"
    if is_panic_value(lab_name, final_value):
        flag = "critical"
    
    return OrderResult(
        result_datetime=order.scheduled_events.result_time,
        performed_by=staff.get_on_duty_lab_tech(collection_time),
        value=round(final_value, appropriate_precision(lab_name)),
        unit=get_unit(lab_name),
        reference_range=f"{ref_range.low}–{ref_range.high}",
        flag=flag,
    )
```

### Medication order recurring schedule

Medication orders generate recurring administration events:

```python
def expand_medication_schedule(med_order: Order, encounter: Encounter) -> list[MedicationEvent]:
    """Expand a medication order into individual administration events."""
    
    detail = med_order.medication_details
    events = []
    
    # Parse frequency
    schedule = parse_frequency(detail.frequency)
    # "q6h" → every 6 hours
    # "q8h" → every 8 hours
    # "BID" → 08:00, 20:00
    # "TID" → 08:00, 14:00, 20:00
    # "once" → single dose
    # "PRN" → no scheduled events (generated on demand)
    
    if schedule.is_prn:
        return []  # PRN events are generated by nursing based on patient need
    
    # Generate events from first dose until order end
    first_dose_time = med_order.scheduled_events.collection_time  # "collection" for meds = first administration
    current_time = first_dose_time
    
    end_time = calculate_end_time(detail.duration, encounter)
    
    while current_time < end_time:
        events.append(MedicationEvent(
            scheduled_time=current_time,
            order_id=med_order.order_id,
            drug=detail.drug_name,
            dose=detail.dose,
            route=detail.route,
        ))
        current_time += schedule.interval
    
    return events
```

---

## Open Questions
- [ ] Order modification/cancellation rates (estimated 5–10% of orders are modified or cancelled)
- [ ] Verbal orders in ED: physician gives verbal order → nurse enters → physician co-signs within 24h
- [ ] Country-specific workflows: JP 院外処方箋 (external pharmacy prescription) vs US in-house pharmacy
- [ ] PRN medication trigger logic: when does nursing decide to give PRN pain medication?
- [ ] Blood product ordering workflow (type & screen → crossmatch → release → transfusion)

## Design Notes
- The order module is the **time bridge** between clinical decisions and observable data
- The full chain is: diagnosis/treatment decides → order placed → order module calculates timing → at collection_time: physiology provides state, observation adds noise → result recorded → physician reviews → may trigger next clinical decision
- This chain ensures every data point has a traceable origin with realistic timing
- Order timing is one of the strongest realism signals: a CRP result at 03:00 from a routine order placed at 22:00 is unrealistic for a medium hospital
- Outsourced labs at small hospitals create fundamentally different data patterns (results arrive next day, not same day)

### Cross-module impact
- **encounter**: Calls `place_from_protocol()` at admission, during daily rounds, and for trigger orders. Encounter drives the order module.
- **physiology**: Provides state at collection time via `get_effective_state_for_lab()`. The order module tells physiology WHEN to generate a value.
- **observation**: Applies Layer 3 noise to values derived by physiology. Called by order module at collection events.
- **nursing**: Executes medication administration events generated by `expand_medication_schedule()`. Also executes specimen collection (phlebotomy) events.
- **staff**: Assigns ordering physician, collecting nurse/technician, reporting technician, reviewing physician at each order lifecycle event.
- **facility**: Provides equipment capacity and lab menu. Determines if a test is in-house or outsourced.
- **disease**: Provides the protocol definitions that the order module expands into concrete orders.
