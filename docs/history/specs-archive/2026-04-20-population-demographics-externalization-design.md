# Design: Population Demographics Externalization

**Date:** 2026-04-20  
**Status:** Approved  
**Scope:** Externalize 8 hardcoded population-dynamics fields from engine.py / activator.py into locale demographics YAML files, improving data realism.

---

## Background

Several population attributes are currently hardcoded in Python:

| Field | Location | Issue |
|-------|----------|-------|
| `sex_ratio` | engine.py:201 | Hardcoded 0.49 for all locales |
| `physiology` (BMI/height) | activator.py:122–129 | Country branch with magic numbers |
| `lifestyle_distribution` | activator.py:318–319 | No sex differentiation, hardcoded |
| `lifestyle_risk_multipliers` | — | Not implemented |
| `comorbidity_correlations` | — | Not implemented |
| `insurance_distribution` | activator.py:313 | JP only, age cutoff hardcoded |
| `race_distribution` | — | Not implemented (US FHIR requires it) |
| `occupation_distribution.age_thresholds` | engine.py:472–481 | Hardcoded 15/22/65 |

---

## Key Architectural Decisions

### ADR-1: BMI / smoking / alcohol move to Layer 1 (PersonRecord)

`occupation` already lives in Layer 1 because it drives injury risk during monthly event generation. BMI and smoking have the same dual-phase need:

- **Phase 1 (generate_population):** `lifestyle_risk_multipliers` must modify chronic disease prevalence at sampling time — requires BMI and smoking to be known.
- **Phase 2 (generate_monthly_events):** Same multipliers drive acute event rates — also requires BMI and smoking on the `PersonRecord`.

Generating them in Layer 2 only (activator.py) would make them invisible to Phase 1 and require redundant logic. Layer 1 is the right home.

### ADR-2: `activate_patient(person, rng, demo: dict)` — replace `country: str`

`simulator/engine.py` already calls `load_demographics(config.country)` at multiple points. Loading once and threading `demo` through is cleaner. `activate_patient` gets the full demo dict and reads what it needs. The `country` string is no longer needed as a parameter.

### ADR-3: JP locale changes only after US is confirmed

All code and YAML changes are implemented and tested against US locale first. JP locale (`locale/jp/demographics.yaml`) is updated only after explicit user approval.

---

## New YAML Sections

To be added to `clinosim/locale/us/demographics.yaml` first, then `jp/` after approval.

```yaml
# 1. Sex ratio
sex_ratio:
  male: 0.49

# 2. Physiology
physiology:
  bmi:
    male:   {mean: 29.0, std: 6.0}
    female: {mean: 29.5, std: 6.0}
    clamp:  [15.0, 45.0]
  height_cm:
    male:   {mean: 175.5, std: 7.0}
    female: {mean: 162.0, std: 7.0}
    shrinkage_per_decade_after_60: 0.5

# 3. Lifestyle distribution (sex-specific)
lifestyle_distribution:
  smoking:
    male:   {never: 0.48, former: 0.30, current: 0.22}
    female: {never: 0.58, former: 0.27, current: 0.15}
  alcohol:
    male:   {none: 0.30, social: 0.50, heavy: 0.20}
    female: {none: 0.45, social: 0.43, heavy: 0.12}

# 4. Lifestyle -> disease risk multipliers
lifestyle_risk_multipliers:
  smoking:
    current:
      J44: 10.0
      bacterial_pneumonia: 2.0
      acute_mi: 2.5
      cerebral_infarction: 1.8
      hemorrhagic_stroke: 2.0
      copd_exacerbation: 3.0
    former:
      J44: 3.0
      acute_mi: 1.5
      cerebral_infarction: 1.3
  bmi:
    thresholds: {overweight: 25.0, obese: 30.0}
    overweight:
      I10: 1.5
      E11.9: 2.5
      E78: 1.3
    obese:
      I10: 2.5
      E11.9: 7.0
      E78: 2.0
      acute_mi: 2.0
      acute_cholecystitis: 2.5
      deep_vein_thrombosis: 1.5

# 5. Comorbidity correlations
# Format: condition_A -> {condition_B: multiplier_on_B_prevalence}
# Applied sequentially: after condition_A is sampled, B's prevalence is multiplied.
comorbidity_correlations:
  I10:
    E78:  1.6
    E11.9: 1.4
    I25:  1.5
  E11.9:
    I10:  1.4
    E78:  1.7
    N18:  2.0
    I25:  1.5
  E78:
    I10:  1.5
    E11.9: 1.5
    I25:  1.6

# 6. Insurance distribution (age-band based)
insurance_distribution:
  - age_range: "0-18"
    weights:
      private:       0.55
      medicaid_chip: 0.40
      uninsured:     0.05
  - age_range: "19-64"
    weights:
      private_employer: 0.55
      medicaid:         0.22
      uninsured:        0.11
      other_public:     0.12
  - age_range: "65-99"
    weights:
      medicare:              0.40
      medicare_plus_private: 0.35
      medicare_medicaid_dual: 0.20
      other:                 0.05

# 7. Race / ethnicity (US only; omit in jp/demographics.yaml)
race_distribution:
  white:           0.594
  black:           0.134
  asian:           0.060
  native_american: 0.013
  other:           0.199
ethnicity_distribution:
  hispanic:     0.187
  not_hispanic: 0.813

# 8. Occupation age thresholds (inside occupation_distribution)
occupation_distribution:
  age_thresholds:
    student_max_age:          14
    young_adult_max_age:      21
    young_adult_student_prob: 0.70
    retirement_min_age:       65
  working_age:
    # ...existing entries unchanged...
```

---

## Code Changes

### `clinosim/modules/population/engine.py`

**`PersonRecord` dataclass** — add three fields:
```python
bmi: float = 22.0
smoking_status: str = "never"   # "never" | "former" | "current"
alcohol_use: str = "none"       # "none" | "social" | "heavy"
```

**`generate_population(demo, ...)`** — person-generation loop:
1. Read `sex_ratio.male` (default 0.49) for sex assignment.
2. Generate `bmi` and `height` from `physiology` section.
3. Generate `smoking_status` and `alcohol_use` from `lifestyle_distribution[sex]`.
4. Store all three on `PersonRecord`.
5. In chronic condition sampling, apply:
   - `lifestyle_risk_multipliers.bmi` based on BMI category
   - `lifestyle_risk_multipliers.smoking` based on smoking status
   - `comorbidity_correlations` based on conditions already sampled in this loop

Sampling order for comorbidity correlation: process conditions in fixed YAML order so correlation is deterministic given seed. All multiplied probabilities are capped at 1.0 before the Bernoulli draw (e.g., base 0.10 × 7.0 obese multiplier → 0.70, not 0.70 × further multipliers uncapped).

**`_sample_occupation(demo, age, sex, rng)`**:
- Read `occupation_distribution.age_thresholds` instead of hardcoded 15/22/65.
- Falls back to current hardcoded values if key absent (backward compat).

**`generate_monthly_events(...)`**:
- Apply `lifestyle_risk_multipliers` (smoking + BMI categories) as additional multipliers on monthly event rate, same pattern as existing `disease_risk_multipliers`.
- Source: `person.smoking_status` and `person.bmi` (now available on PersonRecord).

### `clinosim/modules/patient/activator.py`

**`activate_patient(person, rng, demo: dict)`**:
- Replace `country: str` parameter with `demo: dict`.
- Height: read from `demo["physiology"]["height_cm"]`; apply shrinkage from `physiology.height_cm.shrinkage_per_decade_after_60`.
- BMI: use `person.bmi` (already set in Layer 1); do NOT regenerate.
- Smoking/alcohol: use `person.smoking_status` / `person.alcohol_use` (already set in Layer 1).
- Insurance: read `demo["insurance_distribution"]`, find matching age band, sample.
- Race/ethnicity: if `race_distribution` key exists in demo, sample and populate `PatientProfile.race` and `PatientProfile.ethnicity`; otherwise omit (JP).

**`PatientProfile` type** — add optional fields:
```python
race: str = ""       # OMB race category (US only)
ethnicity: str = ""  # "hispanic" | "not_hispanic" (US only)
```

### `clinosim/simulator/engine.py`

- Load `demo = load_demographics(config.country)` once at the top of the simulation entry point.
- Pass `demo` to all `activate_patient(person, rng, demo)` callsites (6 locations).

### `clinosim/simulator/cli.py`

- Same: pass `demo` to `activate_patient` (1 location).

---

## Data Flow After Change

```
generate_population(demo)
  sex_ratio.male            → sex
  physiology                → bmi, height → PersonRecord
  lifestyle_distribution[sex] → smoking_status, alcohol_use → PersonRecord
  comorbidity_correlations  → adjust chronic prevalence per already-sampled conditions
  lifestyle_risk_multipliers (bmi + smoking) → adjust chronic prevalence

generate_monthly_events(registry, demo)
  lifestyle_risk_multipliers → person.bmi / smoking_status → acute event rate multiplier

activate_patient(person, rng, demo)
  person.bmi                → PatientProfile.bmi (copied, not regenerated)
  person.smoking_status     → PatientProfile.smoking_status
  person.alcohol_use        → PatientProfile.alcohol_use
  physiology.height_cm      → PatientProfile.height_cm (still computed here)
  insurance_distribution    → PatientProfile.insurance_type
  race_distribution (US)    → PatientProfile.race, .ethnicity
```

---

## Backward Compatibility

- All new YAML keys have safe defaults in code (missing key = previous hardcoded behavior).
- `activate_patient` signature change requires updating 7 callsites — no external API consumers (internal module only).
- `PatientProfile.race` and `.ethnicity` default to `""` so existing JP FHIR output is unchanged.

---

## Testing

- **Unit tests** (`pytest -m unit`): parametrize `test_activate_patient` with a minimal demo dict; verify BMI/smoking taken from PersonRecord, not regenerated.
- **Unit test**: verify `comorbidity_correlations` increases E11.9 prevalence when I10 already sampled.
- **Unit test**: verify `lifestyle_risk_multipliers` increases acute_mi rate for current smoker.
- **Integration test**: run US population (n=500, seed=42); assert mean BMI is within 1 std of `physiology.bmi.male.mean`.
- **Regression**: `pytest -x -q` full suite must pass before any JP changes.

---

## Implementation Order

1. Add YAML sections to `us/demographics.yaml`
2. Extend `PersonRecord` with `bmi`, `smoking_status`, `alcohol_use`
3. Update `generate_population()` — sex ratio, physiology, lifestyle, comorbidity correlations, lifestyle risk multipliers, occupation thresholds
4. Update `generate_monthly_events()` — lifestyle risk multipliers on acute events
5. Update `activate_patient()` signature + body
6. Update 7 callsites in simulator
7. Add/update `PatientProfile` fields (race, ethnicity)
8. Run tests (US only)
9. **User approval → then** apply YAML sections to `jp/demographics.yaml`
