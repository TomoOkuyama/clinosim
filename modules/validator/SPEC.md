# validator — Consistency Validation & Realism Benchmarking

## Purpose
Two responsibilities:
1. **Per-patient consistency validation**: Verify that each generated patient record is internally consistent (rate-of-change limits, mutual exclusion, causal ordering, staff plausibility).
2. **Population-level realism benchmarking**: Verify that the aggregate statistics of generated data match real-world published statistics.

## Inputs
- `ObservationTimeline`: Complete sequence of lab results and vital signs for a patient
- `PhysiologicalTimeSeries`: State variable time series (for cross-referencing)
- `ClinicalEvent` timeline: Treatment changes, diagnostic decisions

## Outputs
- `ValidationReport`: List of violations found (if any), with severity and suggested corrections
- Corrected `ObservationTimeline` (if auto-correction is enabled)

## Dependencies
- `observation` (data to validate)
- `physiology` (state reference for cross-checking)
- `clinical_course` (event timeline for causal ordering)

## Confirmed Specifications

### Rate-of-change limits (per hour)

| Marker | Max rise | Max fall |
|---|---|---|
| CRP | 20 mg/L/h | 5 mg/L/h |
| Creatinine | 0.1 mg/dL/h | 0.02 mg/dL/h |
| Temperature | 0.3 °C/h | 0.2 °C/h |
| Hemoglobin (no transfusion) | 0.05 g/dL/h | 0.3 g/dL/h |

### Mutual exclusion rules (cannot co-occur)

- WBC > 15,000 AND CRP < 5 → contradiction
- pH < 7.2 AND respiratory rate < 16 → contradiction
- Shock state (perfusion < 0.3) AND SBP > 110 → contradiction

### Panic values (critical alert triggers)

| Lab value | Threshold | Required action |
|---|---|---|
| K | > 6.5 mEq/L | Immediate physician notification |
| Hb | < 7.0 g/dL | Transfusion consideration order |
| Glucose | > 500 mg/dL | Emergency insulin administration |

## Open Questions
- [ ] Auto-correction strategy: reject and regenerate, or clamp to nearest valid value?
- [ ] Additional mutual exclusion rules to implement
- [ ] Panic value action generation: should validator trigger treatment events?

---

## Internal Design

### Two-pass validation architecture

#### Pass 1: Rule-based (fast, deterministic)

```python
def validate_pass1(record: PatientRecord) -> list[ValidationIssue]:
    issues = []
    
    # 1. Rate-of-change limits
    for i in range(1, len(record.events)):
        prev = get_lab_at(record.events, i-1)
        curr = get_lab_at(record.events, i)
        if prev and curr and prev.lab_name == curr.lab_name:
            dt_hours = (curr.timestamp - prev.timestamp).total_seconds() / 3600
            if dt_hours > 0:
                rate = abs(curr.value - prev.value) / dt_hours
                limit = RATE_LIMITS.get(curr.lab_name)
                if limit and rate > limit:
                    issues.append(ValidationIssue("rate_violation", f"{curr.lab_name} changed too fast"))
    
    # 2. Mutual exclusion checks
    for snapshot in record.state_snapshots:
        for rule in MUTUAL_EXCLUSION_RULES:
            if rule.evaluate(snapshot):
                issues.append(ValidationIssue("mutual_exclusion", rule.description))
    
    # 3. Panic value → action check
    for event in record.events:
        if event.lab_result and is_panic_value(event.lab_result):
            # Verify that an appropriate action followed within reasonable time
            action_found = find_response_action(record, event, max_delay_hours=2)
            if not action_found:
                issues.append(ValidationIssue("panic_no_response", 
                    f"Panic value {event.lab_result.lab_name}={event.lab_result.value} with no documented response"))
    
    # 4. Timestamp ordering
    timestamps = [e.timestamp for e in record.events]
    for i in range(1, len(timestamps)):
        if timestamps[i] < timestamps[i-1]:
            issues.append(ValidationIssue("timestamp_order", "Events out of chronological order"))
    
    # 5. Causal ordering
    # Cultures must be drawn before antibiotics (ideally)
    abx_start = find_first_event(record, "antibiotic_start")
    culture_draw = find_first_event(record, "blood_culture_collection")
    if abx_start and culture_draw and culture_draw.timestamp > abx_start.timestamp + timedelta(hours=1):
        issues.append(ValidationIssue("causal_order_warning",
            "Blood cultures drawn >1h after antibiotic start (reduces sensitivity)"))
    
    # 6. Staff plausibility
    for event in record.events:
        for assignment in event.staff_assignments:
            if not is_plausible_assignment(assignment, event):
                issues.append(ValidationIssue("staff_implausible",
                    f"Staff {assignment.staff_id} assigned to {event.event_type} but not on duty/wrong department"))
    
    return issues
```

#### Pass 2: LLM-based clinical review (optional)

```python
def validate_pass2(record: PatientRecord, pass1_issues: list[ValidationIssue]) -> ConsistencyReviewResponse:
    """LLM-based holistic clinical review. Called once per patient."""
    
    # Condense patient timeline to ~1000 tokens
    timeline_summary = condense_timeline(record)
    
    response = llm_service.generate(
        task_type=LLMTaskType.CONSISTENCY_REVIEW,
        event=ClinicalEventData(
            patient_summary=build_summary(record.patient),
            event_data={
                "timeline_summary": timeline_summary,
                "rule_based_flags": [i.description for i in pass1_issues],
                "diagnosis_evolution": summarize_diagnosis_evolution(record),
                "treatment_changes": summarize_treatment_changes(record),
            },
            language="en",  # JUDGMENT task: always English
        )
    )
    
    return response
```

#### Auto-correction strategy

```python
def correct_issues(record: PatientRecord, issues: list[ValidationIssue]) -> PatientRecord:
    for issue in issues:
        match issue.type:
            case "rate_violation":
                # Clamp the offending value to max allowable rate
                clamp_to_rate_limit(record, issue)
            case "mutual_exclusion":
                # Regenerate the conflicting time step
                regenerate_state_at(record, issue.timestamp)
            case "panic_no_response":
                # Insert an appropriate response event
                insert_panic_response(record, issue)
            case "timestamp_order":
                # Sort events chronologically
                record.events.sort(key=lambda e: e.timestamp)
            case "staff_implausible":
                # Reassign staff
                reassign_staff(record, issue)
    return record
```

---

### Tier 1: Statistical realism benchmarks (population-level)

Run after a full simulation. Compares generated data distributions against published real-world statistics.

```python
def run_statistical_benchmarks(records: list[PatientRecord], population: PopulationRegistry,
                                config: HealthcareSystemConfig) -> BenchmarkReport:
    report = BenchmarkReport()
    
    # === Demographics ===
    report.add(check_age_distribution(records, config))
    report.add(check_sex_ratio(records, config))
    report.add(check_blood_type_distribution(population, config))
    
    # === Disease incidence ===
    report.add(check_admission_rate_per_100k(records, population, config))
    report.add(check_disease_mix(records, config))
    report.add(check_seasonal_variation(records, config))
    
    # === Length of stay ===
    report.add(check_los_distribution(records, config))
    # JP pneumonia: median ~14 days, IQR 10-18
    # US pneumonia: median ~4 days, IQR 3-6
    
    # === Mortality ===
    report.add(check_in_hospital_mortality(records, config))
    # Pneumonia: 5-10%, HF: 3-5%, Hip fracture: 2-5%
    
    # === Readmission ===
    report.add(check_30day_readmission_rate(records, config))
    # HF: 20-25%, Pneumonia: 15-20%
    
    # === Lab value distributions ===
    report.add(check_lab_distributions(records))
    # CRP at admission (pneumonia): median ~80, IQR 30-150
    # WBC at admission: median ~12000, IQR 8000-16000
    # CRP at discharge: median ~10, IQR 3-30
    
    # === Vital sign patterns ===
    report.add(check_vital_sign_distributions(records))
    # Admission temp (pneumonia): mean 38.5, SD 0.8
    # Discharge temp: mean 36.6, SD 0.3
    
    # === Temporal patterns ===
    report.add(check_time_of_day_distribution(records, "admission"))  # peak 18-22h for ED
    report.add(check_day_of_week_distribution(records, "discharge"))  # peak Fri in JP
    report.add(check_monthly_admission_volume(records))  # winter peak
    
    # === Treatment patterns ===
    report.add(check_antibiotic_usage(records, config))
    report.add(check_medication_switch_rate(records))  # ~8-15% switch antibiotics
    
    # === Staffing patterns ===
    report.add(check_attending_continuity(records))  # same attending throughout stay >90%
    report.add(check_night_documentation_sparsity(records))  # fewer notes 22-06
    
    # === Encounter patterns ===
    report.add(check_outpatient_vs_inpatient_ratio(records))
    report.add(check_ed_to_admission_rate(records))  # ~30-50% of ED visits → admission
    report.add(check_icu_transfer_rate(records))  # ~5-10% of inpatients
    
    return report
```

### Benchmark result format

```python
@dataclass
class BenchmarkResult:
    name: str                              # "los_distribution_pneumonia_JP"
    metric: str                            # "median_LOS"
    generated_value: float                 # what the simulation produced
    expected_value: float                  # real-world reference
    expected_range: tuple[float, float]    # acceptable range (e.g., ±2SD)
    source: str                            # "MHLW Hospital Report 2022"
    status: Literal["pass", "warn", "fail"]
    deviation_pct: float                   # % deviation from expected

@dataclass
class BenchmarkReport:
    results: list[BenchmarkResult]
    pass_rate: float                       # % of benchmarks that passed
    warn_count: int
    fail_count: int
    
    def summary(self) -> str:
        return f"Benchmarks: {len(self.results)} total, " \
               f"{self.pass_rate:.0%} pass, {self.warn_count} warn, {self.fail_count} fail"
```

### Benchmark thresholds

| Status | Criteria |
|---|---|
| **pass** | Generated value within ±20% of expected (or within expected range) |
| **warn** | Generated value within ±20-50% of expected |
| **fail** | Generated value deviates >50% from expected |

### Specific benchmarks (Phase 1: Pneumonia, Japan)

| Benchmark | Expected | Source | Acceptable range |
|---|---|---|---|
| Median LOS | 14 days | DPC data | 10-18 |
| In-hospital mortality | 7% | MHLW | 4-12% |
| 30-day readmission | 17% | Literature | 12-22% |
| ICU transfer rate | 7% | Literature | 3-12% |
| CRP at admission (median) | 80 mg/L | Clinical studies | 40-150 |
| CRP at discharge (median) | 8 mg/L | Clinical studies | 3-20 |
| Antibiotic switch rate | 12% | DPC data | 5-20% |
| Blood culture positivity rate | 15% | Literature | 8-25% |
| Mean age (admitted pneumonia) | 72 | Patient survey | 65-80 |
| Male ratio | 55% | Patient survey | 48-62% |
| Time to first antibiotic (median) | 3h | Quality metrics | 1-6h |
| Weekend admission rate | 25% | Expected | 20-30% |
| Saturday outpatient volume (JP) | High | Observation | >weekday Thursday |

### Tier 2: Clinical pattern validation

Checks that individual patient records follow clinically coherent patterns:

```python
def validate_clinical_patterns(record: PatientRecord) -> list[PatternIssue]:
    issues = []
    
    # CRP trajectory: should rise before falling (not monotonic decrease from admission)
    crp_values = get_lab_series(record, "CRP")
    if len(crp_values) >= 3:
        if crp_values[1].value < crp_values[0].value:
            issues.append(PatternIssue("crp_no_initial_rise",
                "CRP should typically rise in first 24-48h before falling"))
    
    # Fever curve: should resolve before CRP normalizes
    fever_resolution_day = find_fever_resolution_day(record)
    crp_normalization_day = find_crp_normalization_day(record)
    if fever_resolution_day and crp_normalization_day:
        if crp_normalization_day < fever_resolution_day:
            issues.append(PatternIssue("crp_before_fever",
                "CRP normalized before fever resolution — unusual sequence"))
    
    # Antibiotic timing: should start within hours of admission, not days
    abx_start = find_first_event(record, "antibiotic_start")
    admission = find_first_event(record, "admission")
    if abx_start and admission:
        delay = (abx_start.timestamp - admission.timestamp).total_seconds() / 3600
        if delay > 8:
            issues.append(PatternIssue("late_antibiotic",
                f"Antibiotic started {delay:.0f}h after admission — should be within 4-6h"))
    
    # Discharge: should not happen with rising CRP
    if record.discharge_datetime:
        last_crp = get_last_lab_before(record, "CRP", record.discharge_datetime)
        prev_crp = get_second_last_lab(record, "CRP")
        if last_crp and prev_crp and last_crp.value > prev_crp.value * 1.1:
            issues.append(PatternIssue("discharge_rising_crp",
                "Discharged with rising CRP — unusual"))
    
    # Lab ordering pattern: admission labs should be STAT, Day 7 labs should be routine
    admission_labs = get_labs_within(record, admission.timestamp, hours=4)
    for lab in admission_labs:
        if lab.urgency != "stat":
            issues.append(PatternIssue("admission_lab_not_stat",
                f"Admission lab {lab.display_name} ordered as {lab.urgency}, expected stat"))
    
    # Vital sign frequency: should match encounter type
    vitals = get_vital_events(record)
    for i in range(1, len(vitals)):
        gap_hours = (vitals[i].timestamp - vitals[i-1].timestamp).total_seconds() / 3600
        encounter_type = get_encounter_at(record, vitals[i].timestamp).encounter_type
        if encounter_type == "inpatient" and gap_hours > 10:
            issues.append(PatternIssue("vital_gap_too_long",
                f"Vital sign gap of {gap_hours:.0f}h on inpatient ward — expected q4-8h"))
    
    return issues
```

### Tier 3: Domain expert blind test protocol

Not automated — a process for human validation:

```
1. Generate N patient records (e.g., N=50)
2. Obtain N real anonymized records (same disease mix, same country)
3. Mix and randomize
4. Present to 3+ clinicians (physicians, nurses with 5+ years experience)
5. For each record, clinician marks: "Real" or "Generated" + confidence (1-5)
6. Calculate:
   - Accuracy: can clinicians distinguish? (target: < 60% accuracy = good)
   - Inter-rater agreement (kappa)
   - Which features gave away generated records (feedback for improvement)
7. Repeat after addressing identified weaknesses
```

### Validation report output

```python
class FullValidationReport:
    per_patient_issues: dict[str, list[ValidationIssue]]  # patient_id → issues
    statistical_benchmarks: BenchmarkReport
    clinical_patterns: dict[str, list[PatternIssue]]
    llm_reviews: dict[str, ConsistencyReviewResponse]     # if LLM mode enabled
    
    def export(self, output_dir: str):
        # validation_summary.json — pass/warn/fail counts
        # benchmark_details.csv — each benchmark with generated vs expected
        # per_patient_issues.csv — all flagged issues
        # pattern_violations.csv — clinical pattern issues
        pass
```

---

## Design Notes
- Pass 1 is always run. Pass 2 is optional (depends on llm_service mode).
- Statistical benchmarks run once per simulation batch, not per patient.
- Clinical pattern validation runs per patient, after Pass 1 and before output.
- Most Pass 1 violations indicate bugs in upstream modules, not expected data variation.
- Some "violations" are actually realistic (cultures after antibiotics happens in ~20% of real cases in ED). The validator should flag but not always correct these.
- Auto-correction is conservative: clamp values rather than regenerate entire records.
- Tier 3 (expert blind test) is a milestone gate: conducted before each major release.

### Cross-module impact
- **simulator**: Calls `run_statistical_benchmarks()` after full simulation run. Includes benchmark report in output.
- **output**: Exports validation report alongside patient data.
- **All modules**: Each module's Open Questions should reference which benchmarks validate its behavior.
