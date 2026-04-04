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

## How to add a new country's demographic data

### 1. Age distribution and chronic disease prevalence

Age distribution and chronic disease prevalence are currently hardcoded in `engine.py` as
`JP_AGE_DISTRIBUTION` and `JP_CHRONIC_PREVALENCE`. To add a new country:

1. Add a new constant in `engine.py` following the existing pattern:
   ```python
   US_AGE_DISTRIBUTION = {
       (0, 14): 0.18, (15, 24): 0.13, ...
   }
   US_CHRONIC_PREVALENCE = {
       "I10": {(40, 99): 0.45},   # Hypertension (US rate ~45%)
       "E11.9": {(40, 99): 0.11}, # Type 2 DM
       ...
   }
   ```
2. In `generate_population()`, dispatch on `country` to select the correct constants:
   ```python
   age_dist = JP_AGE_DISTRIBUTION if country == "JP" else US_AGE_DISTRIBUTION
   chronic_prev = JP_CHRONIC_PREVALENCE if country == "JP" else US_CHRONIC_PREVALENCE
   ```
3. Add the country's name data as `clinosim/locale/{country}/names.yaml`
   (see `clinosim/locale/jp/names.yaml` for the schema: `surnames`, `given_names_male`,
   `given_names_female`, each entry having `kanji`/`name`, and a `weight` field).
4. Add naming rules to `clinosim/locale/shared/naming_rules.yaml` under the new country
   code. The required fields are `household_surname_rule`, `name_order`, and
   `has_phonetic`.

### 2. How to add new life event types

Each life event type requires:

1. **Incidence function** — age/sex-specific rate per 100,000/year:
   ```python
   def _my_disease_incidence(age: int, sex: str = "M") -> float:
       base = {0: 10, 45: 50, 65: 200, 75: 600}
       rate = 10.0
       for a, r in sorted(base.items()):
           if age >= a:
               rate = r
       return rate
   ```
2. **Seasonal curve** — monthly multiplier dict (key = month 1–12):
   ```python
   _MY_SEASONAL = {1: 1.2, 2: 1.1, ..., 12: 1.2}
   ```
3. **Risk multipliers** — ICD-10 code → float:
   ```python
   _MY_RISK = {"E11.9": 1.5, "I10": 1.3}
   ```
4. **Event generation block** in `generate_monthly_events()` — use `_disease_monthly_rate()`
   and append a `LifeEvent` with the appropriate `event_type`
   (`"acute_disease_onset"`, `"chronic_exacerbation"`, or `"trauma"`).

The `LifeEvent.condition_type` field supports `"known_disease"`, `"mixed"`, and `"unknown"`;
set it to reflect ground-truth causal category (AD-28).

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
