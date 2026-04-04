# clinical_course

Clinical course archetype engine. Selects a trajectory pattern for each patient and generates daily state change directives.

## Public API

```python
from clinosim.modules.clinical_course.engine import (
    select_archetype,      # (severity, profile, rng) -> archetype name
    get_daily_directive,   # (archetype, day, profile) -> StateChangeDirective
    ARCHETYPES,            # dict of all archetype definitions
)
```

### `select_archetype(severity, profile, rng) -> str`
Selects one of 6 archetypes based on disease severity and patient's physiological profile. Severe patients are more likely to deteriorate; high treatment sensitivity favors smooth recovery.

### `get_daily_directive(archetype_name, day, profile) -> StateChangeDirective`
Returns daily deltas for state variables (inflammation, volume, renal, perfusion) interpolated from archetype trajectory, modulated by patient's immune reactivity and treatment sensitivity.

## Archetypes

| Name | Probability | Pattern |
|---|---|---|
| smooth_recovery | 55% | Steady improvement from Day 1-2 |
| dip_then_recovery | 20% | Worsening Day 1-3, then gradual improvement |
| plateau_then_recovery | 10% | No change 3-5 days, then improvement |
| treatment_resistant | 8% | No response to first-line, requires change Day 3-5 |
| gradual_deterioration | 5% | Slow worsening → ICU |
| sudden_deterioration | 2% | Sudden spike Day 2 (sepsis/PE) |

## Dependencies
- `clinosim.types.clinical` (StateChangeDirective)
- `clinosim.types.patient` (PatientPhysiologicalProfile)

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_clinical_course.py -v
```
13 tests covering: archetype selection, daily directives, interpolation, severity/profile modifiers.

## Implementation status
- [x] All 6 archetypes with hardcoded trajectories
- [x] Severity-dependent selection probability
- [x] Patient profile modulation (immune reactivity, treatment sensitivity)
- [x] Linear interpolation between day points
- [x] 13 unit tests passing
- [ ] YAML-driven trajectory definitions (currently hardcoded)
- [ ] Treatment change triggers (Day 3 no improvement → escalation)
