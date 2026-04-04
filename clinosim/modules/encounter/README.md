# encounter

Encounter workflow engine. Creates encounters and generates the daily cycle timeline for inpatient stays.

## Public API

```python
from clinosim.modules.encounter.engine import (
    create_inpatient_encounter,
    generate_daily_cycle,
    generate_encounter_timeline,
    DailyCycleEvent,
)
```

### `create_inpatient_encounter(patient_id, admission_datetime, ...) -> Encounter`
Creates a new inpatient encounter with placeholder staff.

### `generate_encounter_timeline(encounter, total_days) -> list[DailyCycleEvent]`
Generates the full timeline: admission events + daily cycles + discharge events.

### `DailyCycleEvent`
Scheduled event within a day: `morning_vitals`, `morning_labs`, `rounds`, `afternoon_vitals`, `evening_vitals`, `evening_meds`, `night_check`.

## Dependencies
- `clinosim.types.encounter` (Encounter, EncounterType, EncounterStatus)

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_encounter.py -v
```

## Implementation status
- [x] Linear inpatient workflow (admission → daily cycle → discharge)
- [x] Daily cycle event generation (7 event types per day)
- [ ] ED workflow state machine
- [ ] Outpatient workflow
- [ ] ICU workflow (15-min resolution)
- [ ] Health checkup workflow
- [ ] Prenatal/delivery workflows
- [ ] Discharge criteria evaluation
- [ ] Encounter transitions (ward → ICU, etc.)
