# locale

Centralized repository for all country/language-specific data. Every module that needs localized content reads from here via `locale.loader`.

## Structure

```
locale/
  loader.py           <- Single access point (load_names, load_terminology, etc.)
  names/
    japan.yaml        <- JP surnames (100+), given names M (40+), given names F (40+)
    us.yaml           <- US surnames, given names (planned)
  terminology/
    lab_ja.yaml       <- Lab test display names in Japanese
    lab_en.yaml       <- Lab test display names in English
    (future: diagnosis_ja.yaml, drug_ja.yaml, procedure_ja.yaml, ...)
  code_mapping/
    internal_to_jlac10.yaml  <- Internal lab name -> JLAC10 code
    internal_to_loinc.yaml   <- Internal lab name -> LOINC code
    (future: internal_to_yj.yaml, internal_to_rxnorm.yaml, ...)
  formatting/
    japan.yaml        <- Date/time/unit formatting rules for Japan
    us.yaml           <- Date/time/unit formatting rules for US
```

## Public API

```python
from clinosim.locale.loader import (
    load_names,          # (country) -> name YAML data
    load_terminology,    # (code_system, language) -> {code: display_name}
    load_code_mapping,   # (from_system, to_system) -> {internal: standard_code}
    load_formatting,     # (country) -> formatting rules
)
```

## Key design rules (AD-25, AD-26)

1. **CIF is language-neutral.** Only person names are country-specific in CIF.
2. **Clinical terminology uses official master data ONLY.** Never LLM-translated.
3. **All localized data lives here.** No localization data in other modules.
4. **Adding a new country/language = adding YAML files here.** No code changes.

## Data sources (authoritative)

| Data | Japan source | US source |
|---|---|---|
| Person names | Census surname frequency, birth registration | US Census, SSA baby names |
| Lab names | JLAC10 master (日本臨床検査標準協議会) | LOINC (Regenstrief) |
| Lab codes | JLAC10 | LOINC |
| Drug names | 医薬品マスター (PMDA) | RxNorm (NLM) |
| Diagnosis names | 標準病名マスター (厚労省) | ICD-10-CM (CMS) |

## Dependencies
- `pyyaml` (YAML loading)

## Implementation status
- [x] Japanese names (100 surnames, 40 male, 40 female given names, with kana readings)
- [x] Lab terminology (ja, en — 30 items each)
- [x] Lab code mapping (internal → JLAC10, internal → LOINC)
- [x] Formatting rules (japan, us)
- [x] Loader with caching (lru_cache)
- [ ] US names data
- [ ] Drug terminology (ja, en)
- [ ] Diagnosis terminology (ja, en)
- [ ] Procedure terminology (ja, en)
- [ ] Drug code mapping (internal → YJ, internal → RxNorm)
