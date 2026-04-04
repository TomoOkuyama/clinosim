# facility — Hospital Facility Definition

## Purpose
Define the structure of a simulated hospital: scale category, departments, bed counts, available equipment, and operating hours. This module provides the institutional context within which all clinical activity takes place.

## Inputs
- `HealthcareSystemConfig`: Country-specific hospital classification rules
- User configuration: hospital scale, optional overrides for department composition

## Outputs
- `HospitalProfile`: Complete facility definition consumed by staff assignment and simulation modules

## Dependencies
- `healthcare_system` (country-specific hospital classification and department norms)

## Internal Design

The module is YAML-driven: one template per (country × scale) combination. At initialization, a template is loaded, randomized within ranges, and any user overrides applied.

```
modules/facility/
├── SPEC.md
├── templates/
│   ├── japan_small.yaml
│   ├── japan_medium.yaml
│   ├── japan_large.yaml
│   ├── us_small.yaml
│   ├── us_medium.yaml
│   └── us_large.yaml
└── (implementation files)
```

---

## Confirmed Specifications

### 1. Hospital Scale Categories

| Scale | Japan | US | Bed range | Catchment pop. |
|---|---|---|---|---|
| Small | 有床診療所 / 小規模病院 | Community hospital | 20–99 | 10,000–30,000 |
| Medium | 地域中核病院 / 総合病院 | Regional medical center | 100–499 | 50,000–200,000 |
| Large | 大学病院 / ナショナルセンター | Academic medical center | 500–1,000+ | 200,000–500,000+ |

### 2. Department Composition (Japan)

#### Small (50-bed example)

| Department | Beds | Staff physicians | Subspecialties | Outpatient clinic |
|---|---|---|---|---|
| Internal Medicine | 20 | 3 | None (general) | Yes (Mon–Sat AM) |
| Surgery | 15 | 2 | None (general) | Yes (Mon/Wed/Fri) |
| Orthopedics | 10 | 1–2 | None | Yes (Tue/Thu) |
| (Overflow/mixed) | 5 | — | — | — |
| **Total** | **50** | **6–7** | | |

- No ED (patients go directly to outpatient or are referred)
- No ICU (critical patients transferred to regional hospital)
- Health checkup: contracted to external facility

#### Medium (300-bed example)

| Department | Beds | Staff physicians | Subspecialties | Outpatient clinic |
|---|---|---|---|---|
| Internal Medicine | 60 | 10–15 | Cardiology, Pulmonology, Gastroenterology, Nephrology, Endocrinology | Yes (daily) |
| Surgery | 40 | 6–8 | General, Breast, Colorectal | Yes |
| Orthopedics | 35 | 4–5 | Joint, Spine, Trauma | Yes |
| Urology | 15 | 2–3 | — | Yes |
| OB/GYN | 20 | 3–4 | Obstetrics, Gynecology. Includes L&D (delivery rooms: 2–3), postpartum beds | Yes |
| Pediatrics / Neonatology | 15 | 2–3 | +NICU (4–6 beds, medium hospital) if Level II | Yes |
| Ophthalmology | 5 | 1–2 | — | Yes |
| ENT | 5 | 1–2 | — | Yes |
| Dermatology | 0 (outpatient only) | 1 | — | Yes |
| Psychiatry | 0 (outpatient only) | 1 | — | Yes |
| Radiology (diagnostic) | 0 | 3–4 | — | — |
| Pathology | 0 | 1–2 | — | — |
| Emergency | 10 | 3–5 | — | 24/7 |
| ICU | 8 | 2–3 (+ rotating) | — | — |
| Rehabilitation | 5 | 1 | PT/OT/ST | Yes |
| Health Checkup Center | 0 | 1 (+ shared) | — | Seasonal |
| **Total** | **~300** | **~40–55** | | |

#### Large (800-bed example)

| Department | Beds | Staff physicians | Notes |
|---|---|---|---|
| Internal Medicine | 120 | 30+ | Full subspecialty divisions (8–10 divisions) |
| Surgery | 80 | 20+ | General, Hepatobiliary, Colorectal, Breast, Vascular, Thoracic |
| Orthopedics | 50 | 10+ | Joint, Spine, Trauma, Sports, Hand |
| Cardiovascular Surgery | 20 | 4–6 | |
| Neurosurgery | 20 | 4��6 | |
| Urology | 25 | 4–6 | |
| OB/GYN | 40 | 8–10 | |
| Pediatrics | 30 | 6–8 | + NICU |
| Ophthalmology | 15 | 3–4 | |
| ENT | 15 | 3–4 | |
| Dermatology | 5 | 2–3 | |
| Psychiatry | 30 | 4–6 | |
| Oral Surgery | 10 | 2–3 | |
| Plastic Surgery | 10 | 2–3 | |
| Radiology | 0 | 8–12 | Diagnostic + Interventional |
| Pathology | 0 | 4–6 | |
| Emergency/Trauma | 20 | 8–12 | 24/7 attending coverage |
| ICU | 20 | 6–8 | |
| CCU | 8 | 2–3 (shared with cardiology) | |
| HCU/SCU | 10 | 2–3 | |
| Rehabilitation | 10 | 3–4 | PT/OT/ST teams |
| Palliative Care | 10 | 2–3 | |
| Health Checkup Center | 0 | 2–3 | Dedicated facility |
| **Total** | **~800** | **~150–200** | |

### 3. Department Composition (US)

#### Medium (250-bed example)

| Department | Beds | Attendings | Notes |
|---|---|---|---|
| Internal Medicine / Hospitalists | 60 | 10–12 | Hospitalist model (no residents) |
| Cardiology | 20 | 3–4 | + cardiac telemetry beds |
| Pulmonology | 15 | 2–3 | |
| Gastroenterology | 10 | 2–3 | |
| General Surgery | 30 | 4–5 | |
| Orthopedics | 25 | 4–5 | |
| OB/GYN | 20 | 3–4 | + L&D |
| Pediatrics | 10 | 2–3 | |
| Emergency | 15 | 6–8 | 24/7 |
| ICU | 12 | 2–3 (intensivists) | |
| Radiology | 0 | 4–6 | |
| Pathology | 0 | 2–3 | |
| Behavioral Health | 15 | 2–3 | |
| Rehabilitation | 5 | 1–2 | |
| **Total** | **~250** | **~50–65** | |

#### Large (700-bed example)

Similar to Japan large but with:
- Stronger hospitalist model (dedicated inpatient physicians)
- Resident/fellow teams (teaching hospital)
- Trauma center designation (Level I/II)
- Transplant programs (organ-specific)
- Cancer center
- Interventional radiology as major service
- ~200+ attending physicians, ~150+ residents

### 4. Diagnostic Equipment Inventory & Capacity

| Equipment | Small | Medium | Large | Throughput/unit/day |
|---|---|---|---|---|
| X-ray (portable + fixed) | 1 | 2–3 | 5–8 | ~40 |
| CT scanner | 0–1 | 1–2 | 3–5 | ~30 |
| MRI | 0 | 0–1 | 2–4 | ~15 |
| Ultrasound | 1–2 | 3–5 | 8–12 | ~20 |
| Endoscopy suite (rooms) | 0 | 1–2 | 4–8 | ~8/room |
| Cath lab | 0 | 0–1 | 2–4 | ~6 |
| Operating rooms | 1–2 | 4–8 | 15–25 | ~4 major |
| Angiography suite | 0 | 0–1 | 2–3 | ~5 |

### 5. Laboratory Capacity

| Capability | Small | Medium | Large |
|---|---|---|---|
| **In-house STAT menu** | CBC, BMP, UA, troponin, blood gas | Full chemistry, hematology, coag, cardiac markers | All + specialized (flow cytometry, toxicology) |
| **Routine processing** | Outsourced → next business day | In-house batched (every 1–2h daytime) | In-house continuous |
| **Blood bank** | Type & hold; RBCs only (2–5 units) | Type & screen; RBCs, FFP, platelets | Full bank; all products; irradiated; massive transfusion protocol |
| **Microbiology** | Outsourced (48–120h) | In-house culture (48h); send-out for sensitivity, PCR | Full in-house; rapid PCR (1–2h); MALDI-TOF |
| **Pathology** | Outsourced (5–10 business days) | In-house routine (2–3 days); send-out for specials | In-house with frozen section (30 min); cytology same-day |

```yaml
# Lab batch schedule example (medium hospital)
lab_schedule:
  stat:
    processing: "immediate"
    turnaround_min: 45
    available_hours: "24/7"
  routine:
    batch_times: ["06:30", "09:00", "11:00", "14:00", "17:00"]
    turnaround_min: 120  # from batch start
    night_policy: "deferred_to_0630"
  outsourced:
    pickup_times: ["10:00", "15:00"]
    turnaround_days: 1  # next business day for routine
    turnaround_days_special: 3  # for specialized tests
```

### 6. Equipment Maintenance & Downtime

| Equipment | Scheduled maintenance | Unscheduled downtime risk |
|---|---|---|
| CT | 1 day/month (usually weekend) | 3% chance/month, duration 1–3 days |
| MRI | 1 day/month | 5% chance/month, duration 1–5 days |
| Lab analyzers | Weekly QC (1h each); annual validation (1 day) | 2% chance/month, backup analyzer if available |
| OR | Annual fire/safety inspection (1 day) | Rare (equipment-specific) |

### 6b. Bedside and Point-of-Care (POCT) Devices

Modern hospitals have devices that automatically measure and transmit data to the EHR. This creates a distinct data pattern — higher frequency, precise timestamps, device-originated (no human transcription).

#### Device inventory by unit type

| Device | General ward | ICU | ED | Data generated | EHR integration |
|---|---|---|---|---|---|
| Bedside monitor (HR, SpO2, RR, ECG) | Per-bed (alarm only, manual charting) | Per-bed (continuous, auto-recording) | Per-bed (continuous) | Vitals q1min (ICU) or alarm events (ward) | ICU: auto-export q15min–q1h. Ward: nurse manually enters from display. |
| Automated BP cuff | Shared (1 per 4–6 beds) | Per-bed (integrated) | Per-bed | BP per measurement | ICU: auto. Ward: nurse-initiated, value transmitted. |
| Pulse oximeter (SpO2) | Shared or per-bed | Integrated in monitor | Integrated | Continuous SpO2 | ICU: auto continuous. Ward: spot-check, transmitted or manual. |
| IV infusion pump | As needed | 2–4 per bed | 1–2 per bed | Rate, volume infused, alarms | Auto-logged: start/stop/rate_change/alarm events |
| Glucometer (POCT) | Shared (1 per ward) | 1 per unit | 1 per area | Blood glucose | Transmitted to EHR via POCT middleware. Includes device ID, operator ID, patient ID scan. |
| Blood gas analyzer (POCT) | 0 (sent to lab) | 1 per unit | 1 per area | pH, pCO2, pO2, electrolytes, lactate, Hb | Auto-transmitted. Result in 2–5 min. |
| Thermometer (electronic) | Per-bed or shared | Per-bed | Per-bed | Temperature | Most: manual entry. Some: wireless transmission. |
| Telemetry monitor | Cardiac ward only | All beds | Selectively | Continuous ECG rhythm | Auto-recorded. Alarm events flagged. |
| Ventilator | 0 | Per intubated patient | As needed | Tidal volume, rate, FiO2, PEEP, pressures | Auto-recorded q15min–q1h |
| Fetal monitor (CTG) | 0 | 0 | 0 | Fetal HR, contractions | L&D: continuous during labor, auto-recorded |
| Syringe pump | As needed | 2–4 per bed | As needed | Micro-infusion rate, drug, volume | Auto-logged |

#### Impact on generated data

The data origin (manual vs. device) affects the characteristics of generated records:

| Characteristic | Manual entry (nurse) | Device auto-recording |
|---|---|---|
| Timestamp precision | Rounded to nearest 5 min (±15 min jitter) | Exact to the second |
| Recording frequency | q4h–q8h (ward) | q1min–q15min (ICU continuous) |
| Value precision | Rounded (e.g., BP "120/80") | Precise (e.g., BP "118/76") |
| Missing data pattern | Context-dependent (busy nurse, night, refusal) | Rare (only device disconnect, motion artifact) |
| Data volume | 3–6 vital sets/day (ward) | 96–1440 data points/day (ICU) |
| Identifier | Nurse ID (who recorded) | Device ID + nurse ID (who verified) |
| Artifact | Rare (nurse judges before recording) | Common (motion artifact in SpO2, electrode disconnect in ECG) |

```python
@dataclass
class DeviceReading:
    """Auto-generated reading from a medical device."""
    device_type: str                       # "bedside_monitor" | "infusion_pump" | "glucometer" | "ventilator" | ...
    device_id: str                         # unique device identifier
    patient_id: str
    timestamp: datetime                    # precise (no jitter — device clock)
    parameters: dict[str, float]           # {"HR": 78, "SpO2": 96.2, "RR": 18}
    alarm_status: str | None               # "high_HR" | "low_SpO2" | "disconnect" | None
    verified_by: str | None                # nurse staff_id (if nurse acknowledged/verified)
    artifact: bool                         # True if motion artifact, electrode disconnect, etc.

# Device artifact rates
DEVICE_ARTIFACT_RATES = {
    "SpO2":  0.05,   # 5% of readings affected by motion/poor signal
    "ECG":   0.03,   # electrode disconnect, patient movement
    "BP":    0.02,   # cuff error, patient moved
    "RR":    0.08,   # impedance-based RR is noisy
}
```

#### Hospital scale differences

| Scale | Ward monitoring | ICU monitoring | POCT devices | EHR integration level |
|---|---|---|---|---|
| Small | Manual only (nurse reads display, types into EHR) | Limited (if ICU exists) | Glucometer only | Minimal auto-integration |
| Medium | Semi-auto (wireless thermometer, some auto-BP) | Full continuous monitoring, auto-charting | Glucometer + blood gas | Moderate (POCT middleware, some device integration) |
| Large | Extensive (barcode-scanned meds, wireless vitals) | Full with advanced hemodynamics | Full POCT suite | High (most devices auto-transmit, nurse validates) |

#### Generation rule

```python
def determine_data_origin(encounter_type: str, parameter: str, hospital_scale: str) -> str:
    """Determine whether a vital sign value is manually entered or device-generated."""
    
    if encounter_type == "icu":
        return "device_auto"  # ICU: nearly all data is device-auto
    
    if encounter_type == "inpatient":
        if hospital_scale == "large" and parameter in ["SpO2", "HR"]:
            return "device_auto" if random() < 0.6 else "manual"  # large hospitals: ~60% auto
        return "manual"  # most ward data is still manually entered
    
    if encounter_type == "emergency":
        return "device_auto" if parameter in ["HR", "SpO2", "BP"] else "manual"
    
    return "manual"  # outpatient: all manual
```

When `data_origin == "device_auto"`:
- Timestamp: exact (no jitter)
- Value: higher precision (e.g., SpO2 96.3 not 96)
- Artifact noise: applied from `DEVICE_ARTIFACT_RATES` instead of nurse judgment noise
- Device ID included in record
- Volume: much higher (ICU generates 60–100+ vital data points/day vs. ward 3–6)

### 7. Bed Management

#### Occupancy targets

| Unit type | Target occupancy | Japan | US |
|---|---|---|---|
| General ward | 75–90% | 80% (DPC pressure to maintain volume) | 65–75% (shorter stays) |
| ICU | 60–80% | 70% | 65–75% |
| ED beds | Variable | Peak 80–120% (overcrowding common) | Peak 90–130% |

#### Bed allocation rules
1. Patient admitted to **primary department** for their condition
2. If primary department full → **overflow** to related department (e.g., cardiology overflow to general medicine)
3. If all related departments full → **hallway bed** (ED boarding) or **admission delay** (Mode 2)
4. ICU patients always get ICU bed or are transferred to another facility
5. Isolation beds: reserved for infectious patients (MRSA, TB, COVID); limited quantity

### 8. Temporal Variation

(Seasonal, day-of-week, time-of-day patterns as previously documented — integrated into facility operating schedule YAML)

### 9. Hospital Generation Algorithm

```
Input: country, scale, optional overrides

1. Load template: templates/{country}_{scale}.yaml
2. Randomize within ranges:
   - bed_count: template range → pick specific value
   - per-department bed distribution: proportional allocation with ±10% jitter
   - equipment counts: pick within range
3. Apply overrides (user can fix specific departments, bed counts, etc.)
4. Generate derived attributes:
   - lab_capacity: determined by scale and equipment
   - operating_schedule: from healthcare_system calendar
   - staff requirements: passed to staff module as requirements specification
5. Output: HospitalProfile
```

### 10. Outpatient Clinic Operating Schedule

| Time slot | Japan | US |
|---|---|---|
| Weekday AM (08:30–12:00) | Full clinic, all departments | Full clinic (08:00–12:00) |
| Weekday PM (13:00–17:00) | Full clinic, all departments | Full clinic (13:00–17:00) |
| **Saturday AM (08:30–12:30)** | **Open** (most JP hospitals). Reduced departments (internal medicine, surgery, orthopedics typically). High volume from working adults. | Generally closed (some walk-in/urgent care) |
| Saturday PM | Closed | Closed |
| Sunday / Holiday | Closed (ED only) | Closed (ED only) |
| Evening clinic (17:00–19:00) | Some JP hospitals offer (limited departments) | Rare for hospitals (urgent care facilities cover this) |

Slots per clinic session per department (medium hospital):
- AM session: ~20–30 patients per physician (JP), ~15–20 (US)
- PM session: ~15–25 patients per physician (JP), ~15–20 (US)
- Saturday AM (JP): ~25–35 (compressed demand)

---

## Open Questions
- [ ] Outpatient clinic capacity modeling (slots per day per department per time period)
- [ ] Emergency department physical layout (triage rooms, treatment bays, resuscitation bay)
- [ ] Ambulance receiving capability (designation levels: JP 救急告示 / US Trauma Level)
- [ ] Hospital accreditation and certification effects on available services
- [ ] Parking, physical plant — not clinically relevant but affects simulation realism?

## Design Notes
- Hospital scale is the single most impactful configuration parameter after country selection
- The same pneumonia generates different data at a small hospital (outsourced labs, no CT, general physician) vs. a large hospital (rapid in-house labs, CT available, pulmonology specialist)
- Templates are intentionally ranges, not fixed values — every simulation run produces a slightly different hospital
- The facility module outputs a `StaffRequirements` hint that the staff module uses to generate appropriate roster
