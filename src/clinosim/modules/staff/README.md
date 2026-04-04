# staff

Healthcare staff generation and assignment. Creates realistic staff rosters with Japanese names and assigns staff to clinical events.

## Public API

```python
from clinosim.modules.staff.engine import (
    generate_roster,   # (hospital_scale, country, rng) -> StaffRoster
    assign_staff,      # (event_type, department, roster, rng) -> dict[str, str]
    StaffMember,
    StaffRoster,
)
```

### `generate_roster(hospital_scale, country, rng) -> StaffRoster`
Generates a complete staff roster for a medium JP hospital: 10 physicians, 30 nurses, 10 lab techs, 4 radiologists, 8 pharmacists. Japanese names from weighted surname/given name lists.

### `assign_staff(event_type, department, roster, rng) -> dict[str, str]`
Assigns appropriate staff to clinical events. Returns `{role: staff_id}` mapping.

## Dependencies
- None (standalone — uses only numpy)

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_staff.py -v
```

## Implementation status
- [x] JP medium hospital roster (62 staff)
- [x] Japanese name generation (top 30 surnames)
- [x] Event-type based staff assignment
- [ ] Shift schedule generation
- [ ] On-call rotation
- [ ] Staff lifecycle (hiring, retirement)
- [ ] Attending physician continuity
- [ ] US hospital roster
