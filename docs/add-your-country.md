# Add Your Country to clinosim

*P2-14 (session 48). This guide walks you through adding a new country pack
so clinosim can generate locale-appropriate synthetic EHR/EMR data for it.*

## Overview

clinosim's **locale layer** (`clinosim/locale/<country>/`) is designed as a
1-country-1-folder plug-in. Adding a new country means:

1. Creating `clinosim/locale/<xx>/` with a set of YAML data files
2. Registering the ISO 3166-1 code in `_COUNTRY_DIR_MAP`
3. (Optional) Deciding whether locale-specific FHIR profiles apply
4. Testing against the country flag through the standard CLI

Locale data is strictly **culture / regulatory / linguistic**. International
clinical codes (ICD-10, LOINC, RxNorm, SNOMED) stay in `clinosim/codes/` and
require no country-specific work.

## Prerequisites

- **Authoritative statistical sources** for population, blood-type
  distribution, chronic-disease prevalence, and lab reference ranges. Do NOT
  fabricate demographic data — cite public government / medical-society
  publications.
- **Local clinical code system** knowledge (which mapping applies: `icd-10`
  vs `icd-10-cm` vs a national coding scheme).
- **Optional**: national FHIR IG (JP Core / US Core / DE Basisprofil, etc.)
  for downstream profile emission.

## Quick start

```bash
# 1. Copy the JP folder as a starting scaffold
cp -R clinosim/locale/jp clinosim/locale/xx

# 2. Replace each YAML with locale-appropriate values (see schemas below)
# 3. Register in the country map:
#    Edit clinosim/locale/loader.py:_COUNTRY_DIR_MAP
```

Then:

```bash
clinosim simulate --country XX --population 100 --seed 42 --format fhir-r4 \
    --output ./out
```

## Required YAML files

The `xx/` directory MUST contain the following. See the `_template/` scaffold
(`clinosim/locale/_template/`) for schema comments and skeleton values.

| File | Purpose | Authoritative source hint |
|---|---|---|
| `names.yaml` | Family + given names with frequency weights | National statistics office / civil registry |
| `addresses.yaml` | Regions (state / prefecture / province) + postal codes | National postal service |
| `demographics.yaml` | Age distribution, blood type, chronic-disease prevalence, disease incidence, lifestyle | Government census / disease surveillance |
| `formatting.yaml` | Date / time / number formatting | Local convention |
| `code_mapping_diagnosis.yaml` | Internal disease id → national diagnosis code | Local coding scheme |
| `code_mapping_lab.yaml` | Internal lab name → national lab code | Local lab code system (JLAC10 / LOINC / national) |
| `code_mapping_drug.yaml` | Internal drug name → national drug code | Formulary code (YJ / RxNorm / national) |
| `code_mapping_procedure.yaml` | Internal procedure name → national procedure code | Local procedure scheme (K code / CPT / national) |
| `reference_range_lab.yaml` | Sex / age lab reference ranges | Local clinical society standard |

Each file is validated at load time; a missing file falls back to built-in
defaults but that means the generated data is not truly locale-representative.

## Optional YAML files (opt-in modules)

Only add these when your country supports a specific opt-in module:

| File | When to add | Module |
|---|---|---|
| `identity.yaml` | Modeling a national identifier / insurance number | `identity` |
| `code_mapping_microbiology.yaml` | National microbiology coding | `microbiology` |
| `code_mapping_microbiology_susceptibility.yaml` | National susceptibility reporting | `microbiology` |
| `care_level_rates.yaml` | Long-term-care level (JP 要介護度 相当) | `care_level` — JP-specific concept, generally skip |
| `code_status_rates.yaml` | Resuscitation status distribution | `code_status` |
| `family_history_prevalence.yaml` | First-degree relative disease prevalence | `family_history` |
| `immunization_schedule.yaml` | Local vaccination schedule | `immunization` |

## Code registration

### 1. Register the country in `loader.py`

```python
# clinosim/locale/loader.py
_COUNTRY_DIR_MAP = {"JP": "jp", "US": "us", "XX": "xx"}
```

The loader falls back to `country.lower()` when the map does not contain
the requested code, but registering it explicitly is preferred for
completeness / discoverability.

### 2. FHIR profile emission (optional)

If your country has a national FHIR IG (JP Core / US Core / German Basisprofil
/ AU Core / etc.), decide whether to emit its profile URLs. The current code
emits JP Core profiles when `country == "JP"` via
`_apply_jp_core_profile` in `clinosim/modules/output/fhir_r4_adapter.py`.

For a new country you can:

1. Skip country-specific profile emission (safe default; resources are
   base FHIR R4 compliant)
2. Add a `_XX_CORE_PROFILES: dict[str, list[str]]` registry mirroring the
   JP Core one (session 48 g.1 unified the shape) and dispatch via
   `if country == "XX": _apply_xx_core_profile(resource)` in
   `_build_bundle`.

### 3. Country-specific opt-in modules

Some enrichers gate on country in `register_builtin_enrichers`:

- `identity` — active for JP (国民健康保険 numbering); adapt or disable
- `care_level` — JP-only; skip
- `health_checkup` — JP-eCheckup; skip unless designing an equivalent

## Testing checklist

After creating the country folder:

- [ ] `clinosim simulate --country XX --population 10 --seed 42 --format cif`
      runs without errors and creates non-empty CIF output
- [ ] `clinosim simulate --country XX --population 10 --format fhir-r4` emits
      valid FHIR R4 resources
- [ ] Two independent runs with the same seed produce byte-identical output
      (determinism check — clinosim's core invariant, AD-16):
      ```bash
      clinosim simulate --country XX --seed 42 -o /tmp/xx-run1
      clinosim simulate --country XX --seed 42 -o /tmp/xx-run2
      diff -r /tmp/xx-run1 /tmp/xx-run2  # must show only manifest transactionTime
      ```
- [ ] Names / addresses / dates render in the expected local convention
- [ ] Lab reference ranges match the authoritative source
- [ ] Adding a fresh code emitted from your YAML but missing from
      `clinosim/codes/data/` fails
      `pytest tests/unit/test_diagnosis_code_coverage.py` — expected. Register
      the code in the appropriate `codes/data/*.yaml` per
      "Diagnosis code coverage" section of `CLAUDE.md`.

## Common pitfalls

- **Never fabricate demographic data**. All population statistics MUST be
  traceable to a public authoritative source (census / health ministry /
  medical society). Fabricated data is grounds for silent-no-op class bugs
  downstream.
- **Never emit locale-specific codes in the wrong country's bundle**. The
  regression `test_us_p50_has_no_japanese_language_leakage` guards US output
  against JP leakage; write a symmetric guard for your new country.
- **Never mix code systems inside `code_mapping_*.yaml`**. Each file maps
  internal names to a single external system. Split at the file level.
- **Do not translate clinical terminology via LLM**. Reference the country's
  official terminology master. clinosim's AD-27 rule forbids LLM-driven
  clinical translation.
- **Test with population ≥ 100 before deciding a distribution is realistic**.
  Small cohorts hide long-tail sampling problems.

## Where to go next

- Overall project concept: [`docs/design-guides/project-concept-and-design.md`](design-guides/project-concept-and-design.md)
- Locale module reference: [`clinosim/locale/README.md`](../clinosim/locale/README.md)
- Diagnosis code coverage rules: [`CLAUDE.md`](../CLAUDE.md) §"Diagnosis code coverage"
- Reproducibility invariant: [`docs/development/reproducibility.md`](development/reproducibility.md)

## Scaffold template

`clinosim/locale/_template/` contains a placeholder set of YAMLs with schema
comments. **These placeholders are non-functional** — running `clinosim simulate
--country _template` will fail because the values are TODO markers, not data.
The template exists purely to show the required schema shapes for authoring
a real country pack.
