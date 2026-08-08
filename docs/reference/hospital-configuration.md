<!-- Extracted from `README.md` (Issue #568 PR A2). Update the pointer in README when this file's heading changes. -->

# Hospital Configuration

`clinosim/config/hospital_*.yaml` defines hospital physical layout and operational parameters:

```yaml
recommended_population: 60000

available_departments:           # Available specialties
  - internal_medicine
  - cardiology
  - gastroenterology
  - general_surgery
  - orthopedics
  - emergency_medicine
  - primary_care

department_rollup:              # Sub-specialty → available department
  pulmonology: internal_medicine
  neurology: internal_medicine
  neurosurgery: general_surgery

wards:                          # Wards per department
  internal_medicine: ["4E", "4W"]
  cardiology: ["5E"]
  general_surgery: ["3E"]
  orthopedics: ["3W"]
  emergency_medicine: ["ER"]
  primary_care: ["OPD"]

ward_capacity:                  # Bed count per ward
  "4E": 10
  "4W": 10
  "5E": 8
  "3E": 8
  "3W": 6

resource_capacity:              # Lab/imaging capacity
  lab_analyzers: 2
  ct_scanners: 1
  mri_scanners: 0
  inpatient_beds: 50

staffing:                       # Staffing ratio per shift
  day:    {hours: [8, 16],  lab_staff: 1.0, nursing_staff: 1.0}
  evening:{hours: [16, 0],  lab_staff: 0.5, nursing_staff: 0.7}
  night:  {hours: [0, 8],   lab_staff: 0.2, nursing_staff: 0.5}
```

This enables:
- Automatic disease → department → ward → bed routing
- M/M/1 queueing model with dynamic test result delays
- Nurses assigned per ward (PractitionerRole.location)
- Switchable hospital templates (large / mid-size / clinic)

See `clinosim/modules/facility/README.md`.

---
