# population

Catchment area population generation and life event engine. The origin of all hospital encounters — no patient exists without first being part of the population.

## Public API

```python
from clinosim.modules.population.engine import (
    generate_population,       # (size, country, rng) -> PopulationRegistry
    generate_monthly_events,   # (registry, year, month, rng) -> list[LifeEvent]
    PersonRecord,
    Household,
    LifeEvent,
    PopulationRegistry,
)
```

### `generate_population(size, country, rng) -> PopulationRegistry`
Creates households and persons with age/sex/blood type distribution matching published JP demographics. Assigns chronic conditions by age-specific prevalence.

### `generate_monthly_events(registry, year, month, rng) -> list[LifeEvent]`
Runs one month of life events: disease onset (pneumonia with seasonal modifier), with severity and care-seeking decision per person.

## Dependencies
- None (standalone — uses only numpy)

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_population.py -v
```

## Implementation status
- [x] Household generation with realistic size distribution
- [x] Person generation with JP age/sex/blood type distribution
- [x] Chronic condition assignment by age-specific prevalence
- [x] Care-seeking threshold generation
- [x] Monthly pneumonia life events with seasonal modifier
- [x] Risk multiplier from comorbidities (COPD ×3, DM ×1.5, HF ×2)
- [ ] Household-level events (infection transmission)
- [ ] Chronic disease management visits
- [ ] Health checkup scheduling
- [ ] Pregnancy events
- [ ] Staff lifecycle events
- [ ] Migration (population churn)
