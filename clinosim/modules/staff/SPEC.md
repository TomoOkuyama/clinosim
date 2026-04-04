# staff — Healthcare Staff Generation & Assignment

## Purpose
Generate realistic healthcare staff (physicians, nurses, technicians, pharmacists, etc.) with individual personas, manage their lifecycle (hiring, retirement, transfer), and assign them to clinical events with consistency — ensuring that EHR records carry plausible "who did this" attribution.

## Inputs
- `HospitalProfile`: Department structure, scale, subspecialties
- `HealthcareSystemConfig`: Country-specific staffing norms, title systems, credential types
- Simulation time range: start/end dates (for lifecycle events)

## Outputs
- `StaffRoster`: Complete list of active staff at any point in simulation time
- `StaffProfile`: Individual staff member with persona, specialty, schedule
- `StaffAssignment`: Mapping of staff to clinical events (who ordered, who performed, who supervised)
- `StaffLifecycleEvent`: Hiring, retirement, transfer, leave events

## Dependencies
- `facility` (department structure determines staffing needs)
- `healthcare_system` (country-specific staffing norms and title hierarchy)

## Confirmed Specifications

### Staff categories

| Category | Roles | Records they appear in |
|---|---|---|
| Physician | Attending, fellow, resident, consultant | Orders, notes, discharge summaries, procedures |
| Nurse | RN, charge nurse, NP | Vital signs, medication administration, nursing notes |
| Lab technician | Clinical lab scientist, phlebotomist | Lab result reports (performing technician) |
| Radiology technician | Radiologic technologist | Imaging study metadata |
| Radiologist | Attending radiologist | Imaging interpretation reports |
| Pharmacist | Clinical pharmacist | Medication verification, dispensing records |
| Therapist | PT, OT, ST | Rehabilitation notes (hip fracture, stroke) |
| Midwife | Certified nurse-midwife (JP: 助産師) | Delivery records, prenatal notes, breastfeeding support |
| Neonatologist | NICU attending | NICU admission notes, daily progress, discharge summary |
| Other | Social worker, dietitian, case manager | Consultation notes, discharge planning |

### Staff profile attributes

Each staff member has:
- `staff_id`: Unique identifier
- `name`: Generated name (country-appropriate)
- `role`: Category and specific role
- `department_id`: Primary department assignment
- `specialty` / `subspecialty`: Clinical specialty
- `qualification_year`: Year of qualification (determines seniority)
- `credentials`: Licenses, board certifications
- `schedule_pattern`: Shift pattern (day/night/on-call rotation)
- `active_period`: Date range of employment at this facility
- `expertise_areas`: Specific areas of clinical strength (e.g., "interventional cardiology", "pneumonia in immunocompromised")

### Assignment rules

#### Attending physician assignment
- Each admitted patient is assigned a **primary attending physician** from the relevant department
- The attending remains consistent throughout the stay (unless transfer occurs)
- Assignment considers:
  - Department and subspecialty match to the patient's condition
  - Current patient load (workload balancing)
  - On-call schedule (admissions via ER assigned to on-call physician)
  - Expertise match (e.g., treatment-resistant pneumonia → infectious disease specialist)

#### Consultant assignment
- Consultations are assigned to specialists in the consulted department
- The same consultant follows up on their own consult (continuity)

#### Nursing assignment
- Nurses are assigned per shift, per ward section
- Same nurse may care for a patient across multiple shifts but not guaranteed
- Nurse-to-patient ratio varies by unit:
  - General ward: 1:5–7 (Japan), 1:4–6 (US)
  - ICU: 1:1–2

#### Lab / radiology technician assignment
- Assigned from the pool of on-duty technicians at the time of specimen collection or imaging
- Less continuity expected (different technician each time is normal)
- Radiologist reading assignment: on-duty radiologist at report time

#### Procedure assignment
- Surgeon / proceduralist assigned based on specialty and availability
- Assistants and anesthesiologists assigned from on-duty pool

### Staffing by hospital scale

| Role | Small | Medium | Large |
|---|---|---|---|
| Physicians | 5–15 | 30–100 | 200+ |
| Nurses | 20–50 | 100–300 | 500+ |
| Lab technicians | 2–5 | 10–20 | 30+ |
| Radiologists | 0–1 (outsourced reads) | 3–8 | 15+ |
| Pharmacists | 1–3 | 5–15 | 20+ |

### Staff lifecycle

#### Events
- **Hiring**: New staff joins with generated profile; appears in records from hire date
- **Retirement / resignation**: Staff removed from active roster; no new assignments after departure
- **Transfer**: Staff moves between departments (rare, but occurs)
- **Leave**: Temporary absence (parental leave, sick leave); covered by colleagues
- **Rotation** (residents/fellows): Periodic department rotation on fixed schedule

#### Rates (approximate annual)
- Physician turnover: 5–10%
- Nurse turnover: 10–15%
- Resident rotation: every 1–3 months

### Consistency rules for EHR records

Every clinical event that appears in EHR output must have plausible staff attribution:

| Event type | Required staff | Consistency rule |
|---|---|---|
| Admission order | Attending physician | Must be from relevant department, on duty or on call |
| Daily progress note | Attending or covering physician | Same attending unless weekend/holiday coverage |
| Lab order | Ordering physician | Must be a physician on the patient's care team |
| Lab result | Performing technician | Must be a lab tech on duty at collection time |
| Medication order | Ordering physician | Same care team |
| Medication administration | Administering nurse | Must be a nurse on duty in the patient's ward |
| Imaging order | Ordering physician | Care team physician |
| Imaging interpretation | Radiologist | Must be a radiologist on duty at read time |
| Surgical procedure | Surgeon + assistants | Surgeon must match specialty; all must be on duty |
| Discharge summary | Attending physician | Same attending as admission (or documented handoff) |

### Country-specific differences

**Japan:**
- Title hierarchy: 教授 (Professor) → 准教授 → 講師 → 助教 → 医員 → 研修医
- Attending concept is less formalized; "主治医" (primary physician) is the key role
- Nurses follow a team-nursing model more often
- Pharmacists increasingly involved in ward rounds (病棟薬剤師)

**US:**
- Title hierarchy: Attending → Fellow → Resident (PGY1-5) → Medical Student
- Attending physician of record is a formal legal/billing concept
- Mid-level providers (NP, PA) may write orders under physician supervision
- Strict documentation requirements for billing (who supervised, who performed)

### Temporal variation in staffing

Staffing levels and composition change with time, and this directly affects care delivery realism:

#### Shift patterns

**Japan (typical):**
- Day shift (日勤): 08:30–17:00
- Evening shift (準夜勤): 16:30–01:00
- Night shift (深夜勤): 00:30–09:00
- Or 2-shift: Day 08:30–20:30, Night 20:00–09:00
- Physicians: not shift-based; on-call system (当直)

**US (typical):**
- Day shift: 07:00–19:00
- Night shift: 19:00–07:00
- Physicians: similar on-call; hospitalists may do 7-on/7-off

#### Staffing level variation

| Time period | Staffing level | Impact |
|---|---|---|
| Weekday daytime | Full staffing | Full service |
| Weekday evening | ~70% nursing, on-call physicians | Reduced new orders, delayed non-urgent response |
| Night | ~50% nursing, on-call only physicians | STAT only, routine deferred |
| Weekend daytime | ~60% of weekday | No elective activity, reduced specialist availability |
| Holidays | ~40–50% | Emergency-only, skeleton crew |
| Year-end (JP, Dec 29–Jan 3) | Minimum | Emergency-only |
| Golden Week (JP) | Reduced | Similar to extended weekend |

#### Annual staffing events (Japan-specific)
- **April 1**: New fiscal year — new residents start, staff rotations. Higher supervision needs, potential for slower care and more errors (documented "July effect" equivalent)
- **March**: Year-end rush — discharge push, report completions
- **Bonus periods (June, December)**: Some resignations cluster after bonus

#### Annual staffing events (US-specific)
- **July 1**: New academic year — new interns/residents. "July effect" — documented temporary quality dip
- **Thanksgiving/Christmas**: Holiday coverage with reduced staffing
- **Flu season**: Staff sick leave increases; may need temporary staff

### Staff leave and coverage
- When a physician is on leave, their patients are covered by a colleague in the same department
- Coverage assignments must be recorded (different physician signs notes during coverage period)
- Nursing sick calls: covered by float pool or overtime

---

## Internal Design

### Roster generation algorithm

```python
def generate_roster(hospital: HospitalProfile, config: HealthcareSystemConfig,
                     time_range: tuple[date, date]) -> StaffRoster:
    roster = StaffRoster()
    
    for dept in hospital.departments:
        # Physicians: count from facility template
        for i in range(dept.physician_count):
            physician = generate_physician(dept, config, i)
            roster.add(physician)
        
        # Nurses: based on bed count and nurse-to-patient ratio
        nurse_count = calculate_nurse_count(dept.bed_count, config)
        for i in range(nurse_count):
            nurse = generate_nurse(dept, config, i)
            roster.add(nurse)
    
    # Shared staff (not department-specific)
    for role, count in hospital.shared_staff_counts.items():
        for i in range(count):
            staff = generate_shared_staff(role, config, i)
            roster.add(staff)
    
    # Pre-generate lifecycle events
    roster.lifecycle_events = generate_lifecycle_events(roster, time_range, config)
    
    # Pre-generate shift schedule
    roster.shift_schedule = generate_shift_schedule(roster, time_range, config)
    
    return roster
```

### Name generation

```python
def generate_name(country: str, sex: str) -> PersonName:
    if country == "JP":
        # Japanese names: family_name + given_name
        # Use weighted lists from census surname frequency data
        family = weighted_choice(JP_SURNAME_LIST)    # ~7000 surnames, weighted by frequency
        given = weighted_choice(JP_GIVEN_NAME_LIST[sex])  # ~3000 per sex, weighted by birth year era
        return PersonName(
            family_name=family,       # e.g., "田中"
            given_name=given,         # e.g., "太郎"
            display_name=f"{family} {given}",
            prefix=None,              # JP: no "Dr." prefix in name display
        )
    elif country == "US":
        family = weighted_choice(US_SURNAME_LIST)    # Census surname data
        given = weighted_choice(US_GIVEN_NAME_LIST[sex])
        return PersonName(
            family_name=family,
            given_name=given,
            display_name=f"{given} {family}",
            prefix="Dr." if role.is_physician() else None,
        )
```

### Shift schedule generation

```python
def generate_shift_schedule(roster: StaffRoster, time_range: tuple[date, date],
                             config: HealthcareSystemConfig) -> ShiftSchedule:
    schedule = ShiftSchedule()
    
    for dept in roster.departments:
        nurses = roster.get_nurses(dept)
        physicians = roster.get_physicians(dept)
        
        for day in date_range(time_range):
            is_weekend = day.weekday() >= 5
            is_holiday = config.is_holiday(day)
            
            # Nursing shifts
            if config.country == "JP":
                # 3-shift pattern
                day_nurses = assign_shift(nurses, "day", day, ratio=0.45)
                eve_nurses = assign_shift(nurses, "evening", day, ratio=0.30)
                night_nurses = assign_shift(nurses, "night", day, ratio=0.25)
            else:
                # 2-shift (12h)
                day_nurses = assign_shift(nurses, "day_12h", day, ratio=0.55)
                night_nurses = assign_shift(nurses, "night_12h", day, ratio=0.45)
            
            # Physician on-call
            if is_weekend or is_holiday:
                on_call = select_on_call_physician(physicians, day)
                schedule.set_on_call(dept, day, on_call)
            else:
                # Weekday: all physicians "available" during business hours
                schedule.set_available(dept, day, physicians)
                # Evening/night: one on-call
                on_call = select_on_call_physician(physicians, day)
                schedule.set_on_call(dept, day, on_call, period="after_hours")
    
    return schedule
```

### Assignment algorithm (called per clinical event)

```python
def assign_staff(event_type: str, encounter: Encounter, timestamp: datetime,
                  roster: StaffRoster, schedule: ShiftSchedule) -> list[StaffAssignment]:
    dept = encounter.department_id
    assignments = []
    
    match event_type:
        case "admission":
            # Attending: by department + subspecialty match + workload
            attending = select_attending(dept, encounter, timestamp, roster, schedule)
            assignments.append(StaffAssignment(role="attending_physician", staff_id=attending.staff_id))
            # Nurse: on-duty nurse in the ward section
            nurse = select_on_duty_nurse(dept, timestamp, schedule)
            assignments.append(StaffAssignment(role="primary_nurse", staff_id=nurse.staff_id))
        
        case "daily_progress_note":
            # Same attending as admission (continuity), UNLESS weekend/holiday
            if is_business_hours(timestamp) and not is_weekend_or_holiday(timestamp):
                physician = encounter.attending_physician_id
            else:
                physician = schedule.get_on_call(dept, timestamp.date())
            assignments.append(StaffAssignment(role="note_author", staff_id=physician))
        
        case "lab_collection":
            tech = select_on_duty_staff(StaffRole.LAB_TECHNICIAN, timestamp, schedule)
            assignments.append(StaffAssignment(role="performing_technician", staff_id=tech.staff_id))
        
        case "imaging_interpretation":
            radiologist = select_on_duty_staff(StaffRole.RADIOLOGIST, timestamp, schedule)
            assignments.append(StaffAssignment(role="interpreting_radiologist", staff_id=radiologist.staff_id))
        
        case "medication_administration":
            nurse = select_on_duty_nurse(dept, timestamp, schedule)
            assignments.append(StaffAssignment(role="administering_nurse", staff_id=nurse.staff_id))
        
        case "surgery":
            surgeon = select_surgeon(encounter, roster)
            anesthesiologist = select_on_duty_staff(StaffRole.ANESTHESIOLOGIST, timestamp, schedule)
            scrub_nurse = select_on_duty_nurse("OR", timestamp, schedule)
            assignments.extend([
                StaffAssignment(role="primary_surgeon", staff_id=surgeon.staff_id),
                StaffAssignment(role="anesthesiologist", staff_id=anesthesiologist.staff_id),
                StaffAssignment(role="scrub_nurse", staff_id=scrub_nurse.staff_id),
            ])
        
        case "consultation":
            consultant = select_consultant(encounter.consult_department, timestamp, roster, schedule)
            assignments.append(StaffAssignment(role="consultant", staff_id=consultant.staff_id))
    
    return assignments

def select_attending(dept, encounter, timestamp, roster, schedule):
    """Select attending physician with workload balancing and specialty match."""
    candidates = roster.get_physicians(dept)
    available = [p for p in candidates if schedule.is_available(p, timestamp)]
    
    if not available:
        # After hours: use on-call
        return schedule.get_on_call(dept, timestamp.date())
    
    # Score by: subspecialty match > lower current patient load > seniority
    scored = []
    for p in available:
        score = 0
        if encounter.disease_subspecialty in p.subspecialties:
            score += 100
        score -= roster.current_patient_count(p.staff_id) * 10  # prefer lower load
        score += p.seniority_years  # slight preference for senior
        scored.append((p, score))
    
    scored.sort(key=lambda x: -x[1])
    return scored[0][0]
```

### Lifecycle event generation

```python
def generate_lifecycle_events(roster, time_range, config):
    events = []
    annual_turnover = {"physician": 0.07, "nurse": 0.12, "technician": 0.10}
    
    for year in years_in_range(time_range):
        for staff in roster.all():
            rate = annual_turnover.get(staff.role_category, 0.10)
            
            # Resignation
            if random() < rate:
                resign_month = weighted_choice({3: 0.3, 6: 0.15, 9: 0.15, 12: 0.2, "other": 0.2})
                events.append(LifecycleEvent("resignation", staff.staff_id, date(year, resign_month, 28)))
                # Generate replacement
                replacement = generate_replacement(staff, config)
                events.append(LifecycleEvent("hire", replacement.staff_id, date(year, resign_month + 1, 1)))
                roster.add(replacement)
            
            # Retirement (age-based)
            if staff.age_at(date(year, 4, 1)) >= 65:
                if random() < 0.3:  # not all retire exactly at 65
                    events.append(LifecycleEvent("retirement", staff.staff_id, date(year, 3, 31)))
        
        # April rotation (JP) / July rotation (US) — residents
        if config.country == "JP":
            rotate_residents(roster, events, date(year, 4, 1))
        else:
            rotate_residents(roster, events, date(year, 7, 1))
    
    return events
```

## Open Questions
- [ ] Nurse-to-patient ratio calculation details per unit type
- [ ] Float pool / agency nurse modeling for Mode 2
- [ ] Teaching hospital: how many residents per attending, supervision rules
- [ ] On-call fairness: how to distribute on-call evenly (simple rotation vs. request-based)

## Design Notes
- Staff generation happens once at simulation initialization, producing a roster for the entire simulation period
- Lifecycle events are pre-generated for the simulation timeline, then the roster is queried at each event time
- Assignment logic is called by the simulator whenever a clinical event needs staff attribution
- Temporal staffing variation is critical for realism: a progress note signed at 3 AM must be by the on-call physician, not the attending
- The attending physician assignment has **continuity** — same physician follows the patient throughout the stay. This is one of the strongest realism signals in EHR data.

### Cross-module impact
- **encounter**: Calls `assign_staff()` at every workflow state. Encounter provides the event type and context.
- **order**: Lab/imaging orders carry the ordering physician. Medication administration carries the nurse.
- **nursing**: Shift handoff events are generated from the shift schedule.
- **output**: Staff profiles are exported as FHIR Practitioner resources. Each event's staff_id links to a Practitioner.
