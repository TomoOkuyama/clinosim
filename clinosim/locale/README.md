# locale

Centralized repository for all country/language-specific data. One folder per country. Adding a new country = adding one folder with YAML files.

## Structure

```
locale/
  loader.py              <- Single access point for all locale data
  jp/                     <- Japan-specific data
    names.yaml            <- Surnames (500), given names M (200), F (200), with kana
    terminology_lab.yaml  <- Lab test display names in Japanese
    code_mapping_lab.yaml <- Internal lab name -> JLAC10 code
    formatting.yaml       <- Date/time/unit formatting rules
    demographics.yaml     <- Age dist, blood type, chronic prevalence, disease incidence
  us/                     <- US-specific data
    names.yaml            <- Surnames (1083), given names M (324), F (377)
    terminology_lab.yaml  <- Lab test display names in English
    code_mapping_lab.yaml <- Internal lab name -> LOINC code
    formatting.yaml       <- Date/time/unit formatting rules
    demographics.yaml     <- Age dist, blood type, chronic prevalence, disease incidence
  shared/                 <- Cross-country shared data
    naming_rules.yaml     <- Naming conventions for 10 countries
    chronic_medications.yaml <- Home meds + monitoring rules for 16 chronic conditions
```

## Public API

```python
from clinosim.locale.loader import (
    load_names,          # (country) -> name YAML data
    load_naming_rules,   # (country) -> naming convention rules
    load_terminology,    # (domain, country) -> {internal_name: display_name}
    load_code_mapping,   # (domain, country) -> {internal_name: standard_code}
    load_formatting,     # (country) -> formatting rules dict
    load_demographics,   # (country) -> age distribution, blood type, chronic prevalence
)

# Examples
names = load_names("JP")             # japan/names.yaml
rules = load_naming_rules("JP")      # shared/naming_rules.yaml → japan section
terms = load_terminology("lab", "JP") # japan/terminology_lab.yaml
codes = load_code_mapping("lab", "JP") # japan/code_mapping_lab.yaml
fmt = load_formatting("JP")          # japan/formatting.yaml
```

## Adding a new country

1. Create `locale/{country}/` folder
2. Add required YAML files:
   - `names.yaml` — surname + given name lists with weights (frequency-proportional)
   - `terminology_lab.yaml` — lab display names in local language
   - `code_mapping_lab.yaml` — internal name → national code system
   - `formatting.yaml` — date/time/unit rules
   - `demographics.yaml` — age distribution, blood type, chronic disease prevalence
3. Add country section to `shared/naming_rules.yaml`
4. Add country mapping to `loader.py` `_COUNTRY_DIR_MAP`
5. No other code changes needed

## Terminology: English as base, translations per locale

English (US) terminology files are the **master/base**. Other languages provide translations:

```
us/terminology_lab.yaml:    CRP: "C-reactive protein"     <- English base (master)
jp/terminology_lab.yaml:    CRP: "C反応性蛋白"              <- Japanese translation
```

When adding a new term: add to US first (English), then translate to each locale.

## Key rules (AD-25, AD-26, AD-27)

- CIF is language-neutral. Only person names are country-specific at generation time.
- Clinical terminology uses official master data ONLY. Never LLM-translated.
- All locale data lives here. No localization data in other modules.

## Implementation status
- [x] Japan: names (500 surnames, 200+200 given), terminology, code_mapping, formatting, demographics
- [x] US: names (1083 surnames, 324+377 given), terminology, code_mapping, formatting, demographics
- [x] Shared: naming rules (10 countries), chronic_medications (16 conditions)
- [x] Loader with LRU caching (8 functions)
- [x] Demographics: age distribution, blood type, chronic prevalence (16 conditions), disease incidence, seasonal modifiers, risk multipliers
- [x] Drug terminology/code_mapping (ja: YJ code, en: RxNorm)
- [x] Diagnosis terminology/code_mapping (ja: ICD-10, en: ICD-10-CM)
- [x] Procedure terminology/code_mapping (ja: K-code, en: CPT)
