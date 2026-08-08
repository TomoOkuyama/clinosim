# Population Demographics Externalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Externalize 8 hardcoded population-dynamics fields from Python into `locale/us/demographics.yaml`, making cross-country differences data-driven rather than code-driven.

**Architecture:** BMI/smoking/alcohol move to Layer 1 (`PersonRecord`) so that lifestyle risk multipliers and comorbidity correlations can modify chronic disease prevalence at population-generation time and acute event rates at simulation time. `activate_patient()` receives the full `demo` dict instead of a `country` string. US locale is updated and tested first; JP locale is updated only after explicit user approval.

**Tech Stack:** Python 3.11, numpy, PyYAML, pytest, Pydantic (types), mypy strict

---

## File Map

| File | Change |
|------|--------|
| `clinosim/locale/us/demographics.yaml` | Add 8 new sections |
| `clinosim/modules/population/engine.py` | PersonRecord fields; generation loop; occupation thresholds; monthly events multipliers |
| `clinosim/modules/patient/activator.py` | Signature change; use Layer-1 values; insurance + race from demo |
| `clinosim/types/patient.py` | Add `race`, `ethnicity` to `PatientProfile` |
| `clinosim/simulator/engine.py` | Load demo once; update 6 callsites |
| `clinosim/simulator/cli.py` | Update 1 callsite |
| `tests/unit/test_population_demographics.py` | New test file (create) |

---

## Task 1: Add new YAML sections to `us/demographics.yaml`

**Files:**
- Modify: `clinosim/locale/us/demographics.yaml`

- [ ] **Step 1: Append new sections to the end of `us/demographics.yaml`**

Add these sections after `occupation_risk_multipliers`:

```yaml
# Sex ratio
sex_ratio:
  male: 0.49

# Physiology — body metrics distributions by sex
# Source: CDC NHANES 2017-2020
physiology:
  bmi:
    male:   {mean: 29.0, std: 6.0}
    female: {mean: 29.5, std: 6.0}
    clamp:  [15.0, 45.0]
  height_cm:
    male:   {mean: 175.5, std: 7.0}
    female: {mean: 162.0, std: 7.0}
    shrinkage_per_decade_after_60: 0.5

# Lifestyle distribution — smoking and alcohol by sex
# Source: CDC NHIS 2022, SAMHSA NSDUH 2022
lifestyle_distribution:
  smoking:
    male:   {never: 0.48, former: 0.30, current: 0.22}
    female: {never: 0.58, former: 0.27, current: 0.15}
  alcohol:
    male:   {none: 0.30, social: 0.50, heavy: 0.20}
    female: {none: 0.45, social: 0.43, heavy: 0.12}

# Lifestyle -> disease risk multipliers
# Applied at chronic prevalence sampling AND monthly acute event generation
# Source: CDC, AHA, GOLD guidelines
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

# Comorbidity correlations
# condition_A present -> multiplier on condition_B's prevalence at sampling time
# Source: Framingham, UKPDS, epidemiological meta-analyses
comorbidity_correlations:
  I10:
    E78:   1.6
    E11.9: 1.4
    I25:   1.5
  E11.9:
    I10:   1.4
    E78:   1.7
    N18:   2.0
    I25:   1.5
  E78:
    I10:   1.5
    E11.9: 1.5
    I25:   1.6

# Insurance distribution by age band
# Source: Kaiser Family Foundation 2023, CMS data
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
      medicare:               0.40
      medicare_plus_private:  0.35
      medicare_medicaid_dual: 0.20
      other:                  0.05

# Race and ethnicity distribution (US only)
# Source: US Census Bureau 2020
race_distribution:
  white:           0.594
  black:           0.134
  asian:           0.060
  native_american: 0.013
  other:           0.199
ethnicity_distribution:
  hispanic:     0.187
  not_hispanic: 0.813

# Occupation age thresholds (inside occupation_distribution)
# These control student/retired cutoffs in _sample_occupation()
```

Then update the existing `occupation_distribution` block to add `age_thresholds` as a sibling of `working_age`:

```yaml
occupation_distribution:
  age_thresholds:
    student_max_age:          14
    young_adult_max_age:      21
    young_adult_student_prob: 0.70
    retirement_min_age:       65
  working_age:
    office: 0.32
    service: 0.22
    healthcare: 0.08
    manufacturing: 0.09
    construction: 0.06
    transportation: 0.06
    education: 0.06
    agriculture: 0.01
    homemaker: 0.04
    unemployed: 0.04
    other: 0.02
```

- [ ] **Step 2: Verify YAML is valid**

```bash
python3 -c "
import yaml
with open('clinosim/locale/us/demographics.yaml') as f:
    d = yaml.safe_load(f)
required = ['sex_ratio','physiology','lifestyle_distribution',
            'lifestyle_risk_multipliers','comorbidity_correlations',
            'insurance_distribution','race_distribution',
            'ethnicity_distribution']
for k in required:
    assert k in d, f'Missing key: {k}'
assert 'age_thresholds' in d['occupation_distribution']
print('OK — all sections present')
"
```

Expected: `OK — all sections present`

- [ ] **Step 3: Commit**

```bash
git add clinosim/locale/us/demographics.yaml
git commit -m "data(us): add externalized demographics sections to us/demographics.yaml"
```

---

## Task 2: Add `bmi`, `smoking_status`, `alcohol_use` to `PersonRecord`

**Files:**
- Modify: `clinosim/modules/population/engine.py:32-61`
- Create: `tests/unit/test_population_demographics.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_population_demographics.py`:

```python
"""Unit tests for externalized population demographics."""

import numpy as np
import pytest

from clinosim.modules.population.engine import PersonRecord


def test_person_record_has_lifestyle_fields():
    """PersonRecord must carry bmi, smoking_status, alcohol_use for Layer-1 risk use."""
    p = PersonRecord(person_id="POP-001", household_id="HH-001", age=45, sex="M")
    assert hasattr(p, "bmi"), "bmi field missing from PersonRecord"
    assert hasattr(p, "smoking_status"), "smoking_status field missing"
    assert hasattr(p, "alcohol_use"), "alcohol_use field missing"
    assert isinstance(p.bmi, float)
    assert p.smoking_status in ("never", "former", "current")
    assert p.alcohol_use in ("none", "social", "heavy")
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/unit/test_population_demographics.py::test_person_record_has_lifestyle_fields -v
```

Expected: `FAILED` — `AttributeError` or assertion error.

- [ ] **Step 3: Add three fields to `PersonRecord` in `engine.py`**

In `clinosim/modules/population/engine.py`, after line `occupation: str = "other"` (currently line 53), add:

```python
    # Lifestyle attributes (set at generation time; drive disease risk multipliers)
    bmi: float = 22.0
    smoking_status: str = "never"   # "never" | "former" | "current"
    alcohol_use: str = "none"       # "none" | "social" | "heavy"
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
pytest tests/unit/test_population_demographics.py::test_person_record_has_lifestyle_fields -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/population/engine.py tests/unit/test_population_demographics.py
git commit -m "feat(population): add bmi/smoking_status/alcohol_use to PersonRecord"
```

---

## Task 3: Generate physiology and lifestyle in `generate_population()`

**Files:**
- Modify: `clinosim/modules/population/engine.py` — `generate_population()` loop (~line 197–270)
- Modify: `tests/unit/test_population_demographics.py`

This task generates `bmi`, `smoking_status`, `alcohol_use` from the new YAML sections and stores them on `PersonRecord`.

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_population_demographics.py`:

```python
from clinosim.modules.population.engine import generate_population


def _us_demo_minimal() -> dict:
    """Minimal demo dict with new sections for testing."""
    return {
        "average_household_size": 1.0,
        "age_distribution": {"0-99": 1.0},
        "blood_type": {"O": 1.0},
        "chronic_prevalence": {},
        "disease_incidence": {},
        "seasonal_modifiers": {},
        "disease_risk_multipliers": {},
        "unknown_conditions": {"min_age": 100, "base_rate": 0.0, "age_factor": 0.0, "patterns": []},
        "mixed_conditions": {"min_age": 100, "min_chronic_conditions": 99, "probability": 0.0},
        "ed_visit_not_admitted": {"rate_per_admitted": 0.0},
        "occupation_distribution": {
            "age_thresholds": {
                "student_max_age": 14,
                "young_adult_max_age": 21,
                "young_adult_student_prob": 0.70,
                "retirement_min_age": 65,
            },
            "working_age": {"office": 1.0},
        },
        "occupation_risk_multipliers": {},
        "sex_ratio": {"male": 0.50},
        "physiology": {
            "bmi": {"male": {"mean": 29.0, "std": 0.001}, "female": {"mean": 29.5, "std": 0.001}, "clamp": [15.0, 45.0]},
            "height_cm": {"male": {"mean": 175.5, "std": 0.001}, "female": {"mean": 162.0, "std": 0.001}, "shrinkage_per_decade_after_60": 0.5},
        },
        "lifestyle_distribution": {
            "smoking": {
                "male":   {"never": 0.0, "former": 0.0, "current": 1.0},
                "female": {"never": 1.0, "former": 0.0, "current": 0.0},
            },
            "alcohol": {
                "male":   {"none": 1.0, "social": 0.0, "heavy": 0.0},
                "female": {"none": 1.0, "social": 0.0, "heavy": 0.0},
            },
        },
        "lifestyle_risk_multipliers": {},
        "comorbidity_correlations": {},
        "insurance_distribution": [],
        "race_distribution": {},
        "ethnicity_distribution": {},
    }


def test_bmi_generated_from_physiology_yaml():
    """BMI must come from physiology section, not hardcoded values."""
    rng = np.random.default_rng(42)
    demo = _us_demo_minimal()
    # Force std≈0 so BMI is deterministic
    registry = generate_population(size=10, country="US", rng=rng, demo=demo)
    for p in registry.persons.values():
        if p.sex == "M":
            assert abs(p.bmi - 29.0) < 0.5, f"Male BMI {p.bmi} not near 29.0"
        else:
            assert abs(p.bmi - 29.5) < 0.5, f"Female BMI {p.bmi} not near 29.5"


def test_smoking_status_sex_differentiated():
    """Smoking status must use sex-specific distribution from YAML."""
    rng = np.random.default_rng(42)
    demo = _us_demo_minimal()
    # males forced to current, females forced to never
    registry = generate_population(size=100, country="US", rng=rng, demo=demo)
    for p in registry.persons.values():
        if p.sex == "M":
            assert p.smoking_status == "current", f"Male should be current smoker per demo"
        else:
            assert p.smoking_status == "never", f"Female should be never-smoker per demo"


def test_occupation_age_thresholds_from_yaml():
    """Occupation thresholds must be read from occupation_distribution.age_thresholds."""
    rng = np.random.default_rng(42)
    demo = _us_demo_minimal()
    # Set retirement at 60 instead of default 65
    demo["occupation_distribution"]["age_thresholds"]["retirement_min_age"] = 60
    registry = generate_population(size=200, country="US", rng=rng, demo=demo)
    for p in registry.persons.values():
        if p.age >= 60:
            assert p.occupation == "retired", f"Age {p.age} should be retired (threshold=60)"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_population_demographics.py -k "bmi_generated or smoking_status_sex or occupation_age" -v
```

Expected: all 3 `FAILED` (generate_population doesn't accept `demo` param yet).

- [ ] **Step 3: Update `generate_population()` signature to accept optional `demo`**

In `clinosim/modules/population/engine.py`, change the function signature at line ~152:

```python
def generate_population(
    size: int,
    country: str,
    rng: np.random.Generator,
    base_year: int = 2024,
    demo: dict | None = None,
) -> PopulationRegistry:
    """Generate a catchment area population with households."""
    registry = PopulationRegistry()
    if demo is None:
        demo = _load_demographics(country)
```

Remove the existing line `demo = _load_demographics(country)` that follows (it's now conditional).

- [ ] **Step 4: Generate BMI and height from `physiology` section**

In `generate_population()`, after sex assignment (currently `sex = "M" if rng.random() < 0.49 else "F"`), replace the sex assignment line and add physiology generation:

```python
            # Sex ratio from YAML (default 0.49 male)
            male_prob = (demo.get("sex_ratio") or {}).get("male", 0.49)
            sex = "M" if rng.random() < male_prob else "F"

            # BMI and height from physiology section
            phys = demo.get("physiology") or {}
            bmi_cfg = phys.get("bmi") or {}
            ht_cfg = phys.get("height_cm") or {}
            sex_key = "male" if sex == "M" else "female"

            bmi_mean = (bmi_cfg.get(sex_key) or {}).get("mean", 23.5 if sex == "M" else 22.0)
            bmi_std  = (bmi_cfg.get(sex_key) or {}).get("std", 3.5)
            bmi_clamp = bmi_cfg.get("clamp", [15.0, 45.0])
            bmi = float(np.clip(rng.normal(bmi_mean, bmi_std), bmi_clamp[0], bmi_clamp[1]))

            ht_mean = (ht_cfg.get(sex_key) or {}).get("mean", 170.0 if sex == "M" else 157.5)
            ht_std  = (ht_cfg.get(sex_key) or {}).get("std", 5.5)
            shrink  = ht_cfg.get("shrinkage_per_decade_after_60", 0.5)
            height  = float(rng.normal(ht_mean, ht_std))
            if age > 60:
                height -= (age - 60) / 10 * shrink
```

- [ ] **Step 5: Generate smoking and alcohol from `lifestyle_distribution` section**

Immediately after the height/BMI block:

```python
            # Lifestyle: smoking and alcohol (sex-specific distributions)
            lifestyle = demo.get("lifestyle_distribution") or {}
            smoking_dist = (lifestyle.get("smoking") or {}).get(sex_key, {})
            if smoking_dist:
                sk = list(smoking_dist.keys())
                sp = np.array([smoking_dist[k] for k in sk], dtype=float)
                sp /= sp.sum()
                smoking_status = str(rng.choice(sk, p=sp))
            else:
                smoking_status = str(rng.choice(
                    ["never", "former", "current"], p=[0.55, 0.30, 0.15]
                ))

            alcohol_dist = (lifestyle.get("alcohol") or {}).get(sex_key, {})
            if alcohol_dist:
                ak = list(alcohol_dist.keys())
                ap = np.array([alcohol_dist[k] for k in ak], dtype=float)
                ap /= ap.sum()
                alcohol_use = str(rng.choice(ak, p=ap))
            else:
                alcohol_use = str(rng.choice(
                    ["none", "social", "heavy"], p=[0.60, 0.30, 0.10]
                ))
```

- [ ] **Step 6: Update `_sample_occupation()` to read age thresholds from YAML**

Replace the body of `_sample_occupation()` (currently lines ~463–485):

```python
def _sample_occupation(demo: dict, age: int, sex: str, rng: np.random.Generator) -> str:
    """Sample occupation category from demographics occupation_distribution."""
    occ_cfg = demo.get("occupation_distribution") or {}
    thresholds = occ_cfg.get("age_thresholds") or {}
    student_max   = int(thresholds.get("student_max_age", 14))
    young_max     = int(thresholds.get("young_adult_max_age", 21))
    young_prob    = float(thresholds.get("young_adult_student_prob", 0.70))
    retirement    = int(thresholds.get("retirement_min_age", 65))

    if age <= student_max:
        return "student"
    if age >= retirement:
        return "retired"
    dist = occ_cfg.get("working_age") or {}
    if not dist:
        return "other"
    if age <= young_max and rng.random() < young_prob:
        return "student"
    keys = list(dist.keys())
    weights = np.array([dist[k] for k in keys], dtype=float)
    weights /= weights.sum()
    return str(rng.choice(keys, p=weights))
```

- [ ] **Step 7: Store bmi/smoking/alcohol on PersonRecord in the generation loop**

In the `PersonRecord(...)` constructor call (~line 249), add the three new fields:

```python
            person = PersonRecord(
                person_id=pid,
                household_id=hh_id,
                age=age,
                sex=sex,
                date_of_birth=dob,
                family_name=member_surname.get("kanji", member_surname.get("name", "")),
                given_name=given.get("kanji", given.get("name", "")),
                phonetic=f"{member_surname.get('kana', '')} {given.get('kana', '')}".strip() or None,
                blood_type=blood_type,
                postal_code=hh_addr.get("postal_code", ""),
                state=hh_addr.get("state", ""),
                city=hh_addr.get("city", ""),
                address_line=hh_addr.get("line", ""),
                phone_home=hh_phone_home if has_landline else "",
                phone_mobile=mobile if age >= 15 else "",
                chronic_conditions=conditions,
                occupation=_sample_occupation(demo, age, sex, rng),
                care_seeking_threshold=threshold,
                bmi=bmi,
                smoking_status=smoking_status,
                alcohol_use=alcohol_use,
            )
```

- [ ] **Step 8: Run failing tests to confirm they pass**

```bash
pytest tests/unit/test_population_demographics.py -k "bmi_generated or smoking_status_sex or occupation_age" -v
```

Expected: all 3 `PASSED`

- [ ] **Step 9: Run full unit suite to check for regressions**

```bash
pytest -m unit -x -q
```

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add clinosim/modules/population/engine.py tests/unit/test_population_demographics.py
git commit -m "feat(population): generate BMI/lifestyle from YAML; externalize occupation age thresholds"
```

---

## Task 4: Apply comorbidity correlations and lifestyle risk multipliers to chronic prevalence sampling

**Files:**
- Modify: `clinosim/modules/population/engine.py` — chronic condition sampling loop (~lines 232–240)
- Modify: `tests/unit/test_population_demographics.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_population_demographics.py`:

```python
def test_comorbidity_correlation_raises_prevalence():
    """When I10 is present, E11.9 prevalence should be boosted by comorbidity_correlations."""
    # Force I10 to always trigger, E11.9 just below threshold without correlation
    demo = _us_demo_minimal()
    demo["chronic_prevalence"] = {
        "I10":   {"40-99": 1.0},   # always present for age 40+
        "E11.9": {"40-99": 0.01},  # too low to trigger without boost
    }
    demo["comorbidity_correlations"] = {"I10": {"E11.9": 200.0}}  # 200x boost → should always trigger
    rng = np.random.default_rng(42)
    registry = generate_population(size=200, country="US", rng=rng, demo=demo)
    adults = [p for p in registry.persons.values() if 40 <= p.age <= 99]
    assert len(adults) > 0
    # All adults have I10; with 200x boost, E11.9 should appear in almost all
    e11_count = sum(1 for p in adults if "E11.9" in p.chronic_conditions)
    assert e11_count / len(adults) > 0.95, \
        f"Expected >95% E11.9 with 200x boost, got {e11_count}/{len(adults)}"


def test_lifestyle_risk_multiplier_raises_chronic_prevalence():
    """Obese patients (BMI≥30) should have higher E11.9 prevalence than non-obese."""
    demo = _us_demo_minimal()
    demo["chronic_prevalence"] = {"E11.9": {"0-99": 0.10}}
    demo["lifestyle_risk_multipliers"] = {
        "bmi": {
            "thresholds": {"overweight": 25.0, "obese": 30.0},
            "obese": {"E11.9": 7.0},
            "overweight": {},
        },
        "smoking": {},
    }
    # Force all patients to be obese (BMI mean=35, std≈0)
    demo["physiology"]["bmi"]["male"]   = {"mean": 35.0, "std": 0.001}
    demo["physiology"]["bmi"]["female"] = {"mean": 35.0, "std": 0.001}

    rng_obese = np.random.default_rng(42)
    registry_obese = generate_population(size=500, country="US", rng=rng_obese, demo=demo)

    # Force all patients to be non-obese (BMI mean=22, std≈0)
    demo2 = _us_demo_minimal()
    demo2["chronic_prevalence"] = {"E11.9": {"0-99": 0.10}}
    demo2["lifestyle_risk_multipliers"] = demo["lifestyle_risk_multipliers"]
    demo2["physiology"]["bmi"]["male"]   = {"mean": 22.0, "std": 0.001}
    demo2["physiology"]["bmi"]["female"] = {"mean": 22.0, "std": 0.001}

    rng_thin = np.random.default_rng(42)
    registry_thin = generate_population(size=500, country="US", rng=rng_thin, demo=demo2)

    obese_rate = sum(1 for p in registry_obese.persons.values() if "E11.9" in p.chronic_conditions) / 500
    thin_rate  = sum(1 for p in registry_thin.persons.values() if "E11.9" in p.chronic_conditions) / 500
    assert obese_rate > thin_rate * 2, \
        f"Obese E11.9 rate {obese_rate:.2f} should be >2x thin rate {thin_rate:.2f}"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_population_demographics.py -k "comorbidity or lifestyle_risk_multiplier_raises" -v
```

Expected: both `FAILED`.

- [ ] **Step 3: Apply comorbidity correlations and lifestyle multipliers in the chronic condition loop**

In `generate_population()`, replace the chronic conditions block (~lines 232–240):

```python
            # Build accumulated multipliers from comorbidity correlations and lifestyle
            comorbidity_cfg = demo.get("comorbidity_correlations") or {}
            lifestyle_mults = demo.get("lifestyle_risk_multipliers") or {}
            bmi_cfg_lm = lifestyle_mults.get("bmi") or {}
            bmi_thresholds = bmi_cfg_lm.get("thresholds") or {"overweight": 25.0, "obese": 30.0}
            smoking_cfg_lm = lifestyle_mults.get("smoking") or {}

            bmi_cat: str | None = None
            if bmi >= bmi_thresholds.get("obese", 30.0):
                bmi_cat = "obese"
            elif bmi >= bmi_thresholds.get("overweight", 25.0):
                bmi_cat = "overweight"

            conditions: list[str] = []
            chronic_data = _parse_chronic_prevalence(demo)
            for code, spec in chronic_data.items():
                if spec.sex and spec.sex != sex:
                    continue
                for (lo, hi), base_prev in spec.age_ranges.items():
                    if not (lo <= age <= hi):
                        continue
                    # Comorbidity correlation multiplier (from already-sampled conditions)
                    corr_mult = 1.0
                    for existing_code in conditions:
                        corr_mult *= (comorbidity_cfg.get(existing_code) or {}).get(code, 1.0)
                    # Lifestyle multipliers
                    life_mult = 1.0
                    if bmi_cat:
                        life_mult *= (bmi_cfg_lm.get(bmi_cat) or {}).get(code, 1.0)
                    life_mult *= (smoking_cfg_lm.get(smoking_status) or {}).get(code, 1.0)
                    # Cap combined prevalence at 1.0
                    final_prev = min(1.0, base_prev * corr_mult * life_mult)
                    if rng.random() < final_prev:
                        conditions.append(code)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/unit/test_population_demographics.py -k "comorbidity or lifestyle_risk_multiplier_raises" -v
```

Expected: both `PASSED`.

- [ ] **Step 5: Run full unit suite**

```bash
pytest -m unit -x -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/population/engine.py tests/unit/test_population_demographics.py
git commit -m "feat(population): apply comorbidity correlations and lifestyle risk multipliers to chronic prevalence"
```

---

## Task 5: Apply lifestyle risk multipliers to monthly acute event generation

**Files:**
- Modify: `clinosim/modules/population/engine.py` — `generate_monthly_events()` (~lines 277–430)
- Modify: `tests/unit/test_population_demographics.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_population_demographics.py`:

```python
from clinosim.modules.population.engine import generate_monthly_events, PopulationRegistry, PersonRecord
from datetime import date


def _make_registry_with_person(age: int, sex: str, smoking: str, bmi: float) -> PopulationRegistry:
    r = PopulationRegistry()
    p = PersonRecord(
        person_id="POP-000001",
        household_id="HH-001",
        age=age,
        sex=sex,
        smoking_status=smoking,
        bmi=bmi,
        chronic_conditions=[],
    )
    r.persons["POP-000001"] = p
    return r


def test_lifestyle_risk_multiplier_increases_monthly_event_rate():
    """Current smoker should have higher acute_mi event rate than never-smoker."""
    demo = _us_demo_minimal()
    demo["disease_incidence"] = {
        "acute_mi": {
            "age_rates": {0: 0, 45: 500000},  # very high base rate so events appear in small sample
            "sex_ratio_female": 0.55,
            "event_type": "acute_disease_onset",
            "severity_beta": [3, 3],
            "severity_minimum": 0.3,
            "always_hospitalize": True,
        }
    }
    demo["lifestyle_risk_multipliers"] = {
        "smoking": {"current": {"acute_mi": 10.0}, "former": {}},
        "bmi": {"thresholds": {"overweight": 25.0, "obese": 30.0}, "overweight": {}, "obese": {}},
    }

    smoker_events = 0
    nonsmoker_events = 0
    trials = 50

    for seed in range(trials):
        rng_s = np.random.default_rng(seed)
        reg_s = _make_registry_with_person(55, "M", "current", 24.0)
        events_s = generate_monthly_events(reg_s, 2024, 1, np.random.default_rng(seed), demo=demo)
        smoker_events += len(events_s)

        rng_n = np.random.default_rng(seed)
        reg_n = _make_registry_with_person(55, "M", "never", 24.0)
        events_n = generate_monthly_events(reg_n, 2024, 1, np.random.default_rng(seed), demo=demo)
        nonsmoker_events += len(events_n)

    assert smoker_events > nonsmoker_events, \
        f"Smoker events {smoker_events} should exceed non-smoker {nonsmoker_events}"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/unit/test_population_demographics.py::test_lifestyle_risk_multiplier_increases_monthly_event_rate -v
```

Expected: `FAILED` — generate_monthly_events doesn't accept `demo` or apply lifestyle multipliers yet.

- [ ] **Step 3: Update `generate_monthly_events()` signature and add lifestyle multipliers**

In `clinosim/modules/population/engine.py`, find `generate_monthly_events()` signature (~line 277):

```python
def generate_monthly_events(
    registry: PopulationRegistry,
    year: int,
    month: int,
    rng: np.random.Generator,
    demo: dict | None = None,
    country: str = "JP",
) -> list[LifeEvent]:
```

If `demo` is None, load it from country:
```python
    if demo is None:
        demo = _load_demographics(country)
```

Then inside the per-disease loop, after the existing `occ_mults` block, add lifestyle multiplier application. Locate the section that computes `monthly_rate` (~line 310–330) and add after `occ_mult` application:

```python
        # Lifestyle risk multipliers (smoking + BMI)
        lifestyle_lm = demo.get("lifestyle_risk_multipliers") or {}
        smoking_lm   = lifestyle_lm.get("smoking") or {}
        bmi_lm_cfg   = lifestyle_lm.get("bmi") or {}
        bmi_thresh_lm = bmi_lm_cfg.get("thresholds") or {"overweight": 25.0, "obese": 30.0}

        bmi_cat_lm: str | None = None
        if person.bmi >= bmi_thresh_lm.get("obese", 30.0):
            bmi_cat_lm = "obese"
        elif person.bmi >= bmi_thresh_lm.get("overweight", 25.0):
            bmi_cat_lm = "overweight"

        smoking_mult_lm = (smoking_lm.get(person.smoking_status) or {}).get(disease_id, 1.0)
        bmi_mult_lm     = (bmi_lm_cfg.get(bmi_cat_lm) or {}).get(disease_id, 1.0) if bmi_cat_lm else 1.0
        monthly_rate *= smoking_mult_lm * bmi_mult_lm
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
pytest tests/unit/test_population_demographics.py::test_lifestyle_risk_multiplier_increases_monthly_event_rate -v
```

Expected: `PASSED`.

- [ ] **Step 5: Run full unit suite**

```bash
pytest -m unit -x -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/population/engine.py tests/unit/test_population_demographics.py
git commit -m "feat(population): apply lifestyle risk multipliers to monthly acute event rate"
```

---

## Task 6: Add `race` and `ethnicity` to `PatientProfile`

**Files:**
- Modify: `clinosim/types/patient.py`
- Modify: `tests/unit/test_population_demographics.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_population_demographics.py`:

```python
from clinosim.types.patient import PatientProfile


def test_patient_profile_has_race_ethnicity_fields():
    """PatientProfile must have race and ethnicity fields (empty string default)."""
    p = PatientProfile()
    assert hasattr(p, "race"), "race field missing from PatientProfile"
    assert hasattr(p, "ethnicity"), "ethnicity field missing from PatientProfile"
    assert p.race == ""
    assert p.ethnicity == ""
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/unit/test_population_demographics.py::test_patient_profile_has_race_ethnicity_fields -v
```

Expected: `FAILED`.

- [ ] **Step 3: Add fields to `PatientProfile`**

In `clinosim/types/patient.py`, after line `insurance_type: str = "NHI_employee"` (line 115), add:

```python
    race: str = ""       # OMB race category — US only: "white"|"black"|"asian"|"native_american"|"other"
    ethnicity: str = ""  # "hispanic" | "not_hispanic" — US only
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
pytest tests/unit/test_population_demographics.py::test_patient_profile_has_race_ethnicity_fields -v
```

Expected: `PASSED`.

- [ ] **Step 5: Run full unit suite**

```bash
pytest -m unit -x -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add clinosim/types/patient.py tests/unit/test_population_demographics.py
git commit -m "feat(types): add race and ethnicity fields to PatientProfile"
```

---

## Task 7: Update `activate_patient()` — signature, height, insurance, race

**Files:**
- Modify: `clinosim/modules/patient/activator.py`
- Modify: `tests/unit/test_population_demographics.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_population_demographics.py`:

```python
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from datetime import date


def _make_person(age: int = 45, sex: str = "M", bmi: float = 28.0,
                 smoking: str = "never", alcohol: str = "none") -> PersonRecord:
    return PersonRecord(
        person_id="POP-TEST",
        household_id="HH-TEST",
        age=age,
        sex=sex,
        date_of_birth=date(2024 - age, 1, 1),
        bmi=bmi,
        smoking_status=smoking,
        alcohol_use=alcohol,
    )


def _minimal_demo_for_activate(country_hint: str = "US") -> dict:
    return {
        "_country": country_hint,
        "physiology": {
            "bmi": {"male": {"mean": 29.0, "std": 6.0}, "female": {"mean": 29.5, "std": 6.0}, "clamp": [15.0, 45.0]},
            "height_cm": {"male": {"mean": 175.5, "std": 7.0}, "female": {"mean": 162.0, "std": 7.0}, "shrinkage_per_decade_after_60": 0.5},
        },
        "insurance_distribution": [
            {"age_range": "0-64", "weights": {"private": 1.0}},
            {"age_range": "65-99", "weights": {"medicare": 1.0}},
        ],
        "race_distribution": {"white": 0.6, "black": 0.4},
        "ethnicity_distribution": {"hispanic": 0.2, "not_hispanic": 0.8},
    }


def test_activate_patient_uses_person_bmi_not_regenerate():
    """BMI in PatientProfile must equal person.bmi, not be regenerated."""
    person = _make_person(bmi=33.7)
    rng = np.random.default_rng(0)
    demo = _minimal_demo_for_activate()
    profile = activate_patient(person, rng, demo)
    assert abs(profile.bmi - 33.7) < 0.01, \
        f"PatientProfile.bmi {profile.bmi} should match PersonRecord.bmi 33.7"


def test_activate_patient_uses_person_smoking():
    """smoking_status in PatientProfile must come from PersonRecord."""
    person = _make_person(smoking="current")
    rng = np.random.default_rng(0)
    demo = _minimal_demo_for_activate()
    profile = activate_patient(person, rng, demo)
    assert profile.smoking_status == "current"


def test_activate_patient_insurance_from_yaml():
    """Insurance type should come from insurance_distribution in demo."""
    person_young = _make_person(age=30)
    person_old   = _make_person(age=70)
    rng = np.random.default_rng(0)
    demo = _minimal_demo_for_activate()
    profile_young = activate_patient(person_young, rng, demo)
    profile_old   = activate_patient(person_old,   rng, demo)
    assert profile_young.insurance_type == "private"
    assert profile_old.insurance_type   == "medicare"


def test_activate_patient_race_from_yaml():
    """race and ethnicity must be sampled from demo when race_distribution present."""
    person = _make_person()
    rng = np.random.default_rng(0)
    demo = _minimal_demo_for_activate()
    profile = activate_patient(person, rng, demo)
    assert profile.race in ("white", "black"), f"Unexpected race: {profile.race}"
    assert profile.ethnicity in ("hispanic", "not_hispanic")


def test_activate_patient_no_race_when_missing_from_demo():
    """race and ethnicity should be empty string when race_distribution absent (JP)."""
    person = _make_person()
    rng = np.random.default_rng(0)
    demo = {}  # no race_distribution
    profile = activate_patient(person, rng, demo)
    assert profile.race == ""
    assert profile.ethnicity == ""
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_population_demographics.py -k "activate_patient" -v
```

Expected: all 5 `FAILED`.

- [ ] **Step 3: Rewrite `activate_patient()` signature and body**

In `clinosim/modules/patient/activator.py`, replace the function signature and body sections as follows.

**Signature** (line 111):
```python
def activate_patient(
    person: PersonRecord,
    rng: np.random.Generator,
    demo: dict,
) -> PatientProfile:
    """Convert Layer 1 PersonRecord to Layer 2 PatientProfile."""
    age = person.age
    sex = person.sex
```

**Height calculation** — replace the country-branch block (lines 121–130) with:
```python
    # Height from physiology section; BMI already set in Layer 1
    phys = demo.get("physiology") or {}
    ht_cfg = phys.get("height_cm") or {}
    sex_key = "male" if sex == "M" else "female"
    ht_mean = (ht_cfg.get(sex_key) or {}).get("mean", 170.0 if sex == "M" else 157.5)
    ht_std  = (ht_cfg.get(sex_key) or {}).get("std", 5.5)
    shrink  = ht_cfg.get("shrinkage_per_decade_after_60", 0.5)
    height  = float(rng.normal(ht_mean, ht_std))
    if age > 60:
        height -= (age - 60) / 10 * shrink
    bmi    = person.bmi
    weight = bmi * (height / 100) ** 2
```

**Insurance** — replace the hardcoded line (line 313):
```python
    # Insurance type from insurance_distribution in demo
    insurance_type = _sample_insurance(demo, age, rng)
```

**Smoking / alcohol** — replace lines 318–319:
```python
        smoking_status=person.smoking_status,
        alcohol_use=person.alcohol_use,
```

**Race / ethnicity** — add after `preferred_language` assignment (~line 294):
```python
    # Race and ethnicity (US only; empty string if race_distribution absent)
    race_dist = demo.get("race_distribution") or {}
    if race_dist:
        rk = list(race_dist.keys())
        rp = np.array([race_dist[k] for k in rk], dtype=float)
        rp /= rp.sum()
        race = str(rng.choice(rk, p=rp))
        eth_dist = demo.get("ethnicity_distribution") or {}
        ek = list(eth_dist.keys())
        ep = np.array([eth_dist[k] for k in ek], dtype=float)
        ep /= ep.sum()
        ethnicity = str(rng.choice(ek, p=ep))
    else:
        race = ""
        ethnicity = ""
```

**PatientProfile constructor** — update the return statement to include:
```python
        race=race,
        ethnicity=ethnicity,
```

- [ ] **Step 4: Add `_sample_insurance()` helper function to `activator.py`**

Add before `activate_patient()`:

```python
def _sample_insurance(demo: dict, age: int, rng: np.random.Generator) -> str:
    """Sample insurance type from insurance_distribution age bands."""
    bands = demo.get("insurance_distribution") or []
    for band in bands:
        lo_str, hi_str = str(band.get("age_range", "0-99")).split("-")
        if int(lo_str) <= age <= int(hi_str):
            weights_dict = band.get("weights") or {}
            if weights_dict:
                keys = list(weights_dict.keys())
                probs = np.array([weights_dict[k] for k in keys], dtype=float)
                probs /= probs.sum()
                return str(rng.choice(keys, p=probs))
    # Fallback: keep legacy behavior
    return "late_elderly" if age >= 75 else "NHI_employee"
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest tests/unit/test_population_demographics.py -k "activate_patient" -v
```

Expected: all 5 `PASSED`.

- [ ] **Step 6: Run full unit suite**

```bash
pytest -m unit -x -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/patient/activator.py tests/unit/test_population_demographics.py
git commit -m "feat(patient): update activate_patient to use demo dict; insurance/race from YAML; Layer-1 BMI/lifestyle"
```

---

## Task 8: Update `simulator/engine.py` and `cli.py` callsites

**Files:**
- Modify: `clinosim/simulator/engine.py` — 6 callsites + load demo once
- Modify: `clinosim/simulator/cli.py` — 1 callsite

- [ ] **Step 1: Load `demo` once at the top of `run_beta()`**

In `clinosim/simulator/engine.py`, after `protocols = _load_all_disease_protocols()` (~line 58), add:

```python
    from clinosim.locale.loader import load_demographics
    demo = load_demographics(config.country)
```

- [ ] **Step 2: Replace the 6 `activate_patient(person, rng, config.country)` callsites**

Search for all occurrences:
```bash
grep -n "activate_patient(person, rng, config.country)" clinosim/simulator/engine.py
```

Replace each occurrence with:
```python
activate_patient(person, rng, demo)
```

- [ ] **Step 3: Also update the two `load_demographics` inline calls to reuse `demo`**

Lines 365 and 384 currently call `load_demographics(config.country)` inline. Replace:

Line ~365:
```python
    ed_demo = demo.get("ed_visit_not_admitted", {})
```

Line ~384:
```python
            occ_mult_table = demo.get("occupation_risk_multipliers", {})
```

Remove the `from clinosim.locale.loader import load_demographics` import that was inline at line 359 (it's now loaded at the top of the function).

- [ ] **Step 4: Update `cli.py` callsite**

In `clinosim/simulator/cli.py`, before line 413, add demo loading:

```python
        from clinosim.locale.loader import load_demographics as _ld
        _demo = _ld(args.country)
```

Replace line 413:
```python
        patient = activate_patient(person, rng, _demo)
```

- [ ] **Step 5: Run full test suite**

```bash
pytest -x -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add clinosim/simulator/engine.py clinosim/simulator/cli.py
git commit -m "refactor(simulator): pass demo dict to activate_patient; load demographics once per run"
```

---

## Task 9: Integration smoke test — US full run

**Files:**
- Modify: `tests/unit/test_population_demographics.py`

- [ ] **Step 1: Add integration-style smoke test using real US demographics**

Add to `tests/unit/test_population_demographics.py`:

```python
from clinosim.locale.loader import load_demographics as _load_demo


def test_us_population_bmi_distribution_matches_yaml():
    """End-to-end: generated US population BMI must be within 2 std of YAML mean."""
    demo = _load_demo("US")
    rng = np.random.default_rng(42)
    registry = generate_population(size=500, country="US", rng=rng, demo=demo)
    males   = [p.bmi for p in registry.persons.values() if p.sex == "M"]
    females = [p.bmi for p in registry.persons.values() if p.sex == "F"]
    assert males,   "No male persons generated"
    assert females, "No female persons generated"
    m_cfg = demo["physiology"]["bmi"]["male"]
    f_cfg = demo["physiology"]["bmi"]["female"]
    assert abs(np.mean(males)   - m_cfg["mean"]) < m_cfg["std"] * 2
    assert abs(np.mean(females) - f_cfg["mean"]) < f_cfg["std"] * 2


def test_us_population_comorbidity_clustering():
    """I10+E11.9 co-occurrence in US population must exceed independent expectation."""
    demo = _load_demo("US")
    rng = np.random.default_rng(42)
    registry = generate_population(size=2000, country="US", rng=rng, demo=demo)
    adults = [p for p in registry.persons.values() if p.age >= 40]
    n = len(adults)
    assert n > 0
    has_i10   = sum(1 for p in adults if "I10"   in p.chronic_conditions) / n
    has_e11   = sum(1 for p in adults if "E11.9" in p.chronic_conditions) / n
    has_both  = sum(1 for p in adults if "I10" in p.chronic_conditions
                                      and "E11.9" in p.chronic_conditions) / n
    independent_expected = has_i10 * has_e11
    # With comorbidity correlations, co-occurrence should exceed independent baseline
    assert has_both > independent_expected, \
        f"Co-occurrence {has_both:.3f} should exceed independent {independent_expected:.3f}"
```

- [ ] **Step 2: Run the new smoke tests**

```bash
pytest tests/unit/test_population_demographics.py -k "us_population" -v
```

Expected: both `PASSED`.

- [ ] **Step 3: Run full test suite**

```bash
pytest -x -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_population_demographics.py
git commit -m "test(population): add US smoke tests for BMI distribution and comorbidity clustering"
```

---

## Task 10: Push and request JP approval

- [ ] **Step 1: Push to remote**

```bash
git push origin master
```

- [ ] **Step 2: Confirm all tests pass on clean run**

```bash
pytest -x -q 2>&1 | tail -5
```

Expected: `N passed` with no failures.

- [ ] **Step 3: Report to user**

Show the user:
- Test count and result
- Sample output confirming BMI / comorbidity clustering is working
- Ask: "US 環境の動作を確認できました。JP の `locale/jp/demographics.yaml` に同じセクションを追加してよいですか？"

**Do NOT touch `jp/demographics.yaml` until user says yes.**

---

## Self-Review Checklist

**Spec coverage:**
- [x] sex_ratio → Task 3 (sex assignment line)
- [x] physiology (BMI/height) → Tasks 3, 7
- [x] lifestyle_distribution (sex-specific) → Task 3
- [x] lifestyle_risk_multipliers → Tasks 4 (chronic), 5 (acute)
- [x] comorbidity_correlations → Task 4
- [x] insurance_distribution → Task 7
- [x] race_distribution / ethnicity_distribution → Tasks 6, 7
- [x] occupation_distribution.age_thresholds → Task 3
- [x] PersonRecord fields → Task 2
- [x] activate_patient signature → Task 7
- [x] simulator callsites → Task 8
- [x] US-first / JP gate → Task 10

**Type consistency:** `PersonRecord.bmi` (float), `PersonRecord.smoking_status` (str), `PersonRecord.alcohol_use` (str) defined in Task 2, used in Tasks 3/4/5/7. `PatientProfile.race` / `.ethnicity` (str) defined in Task 6, populated in Task 7. `_sample_insurance()` defined in Task 7, called in Task 7. All consistent.
