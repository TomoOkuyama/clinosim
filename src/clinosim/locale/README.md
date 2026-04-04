# locale

Centralized repository for all country/language-specific data. One folder per country. Adding a new country = adding one folder with YAML files.

## Structure

```
locale/
  loader.py              <- Single access point for all locale data
  japan/                  <- Japan-specific data
    names.yaml            <- Surnames (100+), given names M (40+), F (40+), with kana
    terminology_lab.yaml  <- Lab test display names in Japanese
    code_mapping_lab.yaml <- Internal lab name -> JLAC10 code
    formatting.yaml       <- Date/time/unit formatting rules
  us/                     <- US-specific data
    terminology_lab.yaml  <- Lab test display names in English
    code_mapping_lab.yaml <- Internal lab name -> LOINC code
    formatting.yaml       <- Date/time/unit formatting rules
  shared/                 <- Cross-country shared data
    naming_rules.yaml     <- Naming conventions for 10 countries
```

## Public API

```python
from clinosim.locale.loader import (
    load_names,          # (country) -> name YAML data
    load_naming_rules,   # (country) -> naming convention rules
    load_terminology,    # (domain, country) -> {internal_name: display_name}
    load_code_mapping,   # (domain, country) -> {internal_name: standard_code}
    load_formatting,     # (country) -> formatting rules dict
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
   - `names.yaml` — surname + given name lists with weights
   - `terminology_lab.yaml` — lab display names in local language
   - `code_mapping_lab.yaml` — internal name → national code system
   - `formatting.yaml` — date/time/unit rules
3. Add country section to `shared/naming_rules.yaml`
4. Add country mapping to `loader.py` `_COUNTRY_DIR_MAP`
5. No other code changes needed

## Key rules (AD-25, AD-26, AD-27)

- CIF is language-neutral. Only person names are country-specific at generation time.
- Clinical terminology uses official master data ONLY. Never LLM-translated.
- All locale data lives here. No localization data in other modules.

## Implementation status
- [x] Japan: names (100 surnames, 80 given), terminology, code_mapping, formatting
- [x] US: terminology, code_mapping, formatting
- [x] Shared: naming rules for 10 countries
- [x] Loader with LRU caching
- [ ] US names data (Census surnames, SSA given names)
- [ ] Drug terminology/code_mapping (ja, en)
- [ ] Diagnosis terminology/code_mapping (ja, en)
- [ ] Procedure terminology/code_mapping (ja, en)
