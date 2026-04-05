# population

Catchment area population generation and life event engine. The origin of all hospital encounters — no patient exists without first being part of the population.

All demographic data (age distribution, blood type, chronic disease prevalence, disease incidence rates, seasonal modifiers, risk multipliers) is loaded from locale YAML files — no epidemiological data is hardcoded.

## Public API

```python
from clinosim.modules.population.engine import (
    generate_population,       # (size, country, rng) -> PopulationRegistry
    generate_monthly_events,   # (registry, year, month, rng, country) -> list[LifeEvent]
    PersonRecord,
    Household,
    LifeEvent,
    PopulationRegistry,
)
```

### `generate_population(size, country, rng) -> PopulationRegistry`
Creates households and persons with country-appropriate demographics from `locale/{country}/demographics.yaml`:
- Age distribution, blood type distribution, household size
- Chronic condition assignment (16 conditions) by age-specific prevalence
- Names from `locale/{country}/names.yaml` with surname sharing rules

### `generate_monthly_events(registry, year, month, rng, country) -> list[LifeEvent]`
Runs one month of life events across the population using locale epidemiology data:
- Disease incidence (age/sex-specific) from `demographics.yaml`
- Seasonal modifiers (monthly) from `demographics.yaml`
- Chronic condition risk multipliers from `demographics.yaml`
- 3 disease types: bacterial pneumonia, HF exacerbation, hip fracture
- Mixed conditions (dual pathology) and unknown presentations

## Dependencies
- `clinosim.locale.loader` — all demographic/epidemiological data
- `numpy` — random number generation

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_population.py -v
```

## How to add a new country

1. Create `locale/{country}/demographics.yaml` with:
   - `average_household_size`
   - `age_distribution` (age ranges with proportions)
   - `blood_type` (distribution)
   - `chronic_prevalence` (ICD-10 code -> age range -> prevalence)
   - `disease_incidence` (per disease: age_rates, sex_ratio)
   - `seasonal_modifiers` (per disease: monthly multipliers)
   - `disease_risk_multipliers` (per disease: chronic condition -> risk factor)
2. Create `locale/{country}/names.yaml` (surnames + given names with weights)
3. Add naming rules to `locale/shared/naming_rules.yaml`
4. Add country mapping to `locale/loader.py` `_COUNTRY_DIR_MAP`
5. No code changes needed

## How to add a new disease to life events

1. Add incidence data to `demographics.yaml` under `disease_incidence`:
   ```yaml
   disease_incidence:
     my_new_disease:
       age_rates: {0: 10, 45: 50, 65: 200}
       sex_ratio_female: 0.8
   ```
2. Add seasonal curve and risk multipliers:
   ```yaml
   seasonal_modifiers:
     my_new_disease: {1: 1.2, 2: 1.1, ..., 12: 1.2}
   disease_risk_multipliers:
     my_new_disease: {E11.9: 1.5, I10: 1.3}
   ```
3. Add event generation block in `generate_monthly_events()` (follow existing pattern)
4. Add disease YAML in `modules/disease/reference_data/`

## Implementation status
- [x] Household generation with realistic size distribution
- [x] Person generation with country-specific age/sex/blood type distribution
- [x] Chronic condition assignment (16 conditions) by age-specific prevalence
- [x] Care-seeking threshold generation
- [x] 3 disease types: pneumonia, HF exacerbation, hip fracture
- [x] Country-specific disease incidence rates from locale
- [x] Seasonal modifiers from locale
- [x] Risk multipliers from chronic conditions (locale-driven)
- [x] Mixed conditions (dual pathology, ~18% of elderly multi-morbid)
- [x] Unknown presentations (~3% of admissions)
- [x] US and JP fully supported
- [ ] Household-level events (infection transmission)
- [ ] Chronic disease management visits
- [ ] Health checkup scheduling
- [ ] Additional diseases (UTI, stroke, AMI, sepsis, COPD, DKA)
