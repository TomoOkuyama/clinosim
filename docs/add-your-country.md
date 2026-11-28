# Add Your Country to clinosim

*P2-14 (2026-07-13); rewritten 2026-11-28 from the
[country profile spec](design-guides/country-profile-spec.md). This guide walks
you through adding a new country so clinosim can generate locale-appropriate
synthetic EHR/EMR data for it.*

## Overview

A country exists in clinosim when `clinosim/locale/<cc>/country.yaml` exists
(`<cc>` is the lower-case ISO 3166-1 alpha-2 code). That file is the country
profile; `clinosim.country_profile.supported_countries()` lists the locale
directories that have one, and every `--country` value, `SimulatorConfig.country`
and `country_profile(...)` call is checked against that list. There is no
separate registration step and no country-to-directory map
(`clinosim/locale/_io.py::_country_dir` derives the directory from the code).

Adding a country is mostly data:

1. `clinosim/locale/<cc>/country.yaml` (the profile) and the rest of the locale
   YAML files of that directory
2. A healthcare-system config in `clinosim/config/`
3. Entries for the new country in a few shared and module reference-data files
   that are keyed by country (listed below; some fail loudly when missing)
4. Code only when the country needs an algorithm no existing country has
   (a named implementation) or a FHIR profile clinosim does not know yet — both
   edit core files, as described below
5. Testing against the country flag through the standard CLI

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
# 1. Copy the US folder as a working scaffold (it is complete and runnable;
#    clinosim/locale/_template/ holds schema comments only and is not runnable)
cp -R clinosim/locale/us clinosim/locale/xx

# 2. Edit clinosim/locale/xx/country.yaml: set `code: XX`, the healthcare
#    system, language, timezone, code systems, FHIR profiles and features
# 3. Replace each YAML with locale-appropriate values (see below)
# 4. Add the entries that live outside locale/xx/ (see "Entries outside
#    locale/<cc>/")
```

Then:

```bash
clinosim simulate --country XX --population 100 --seed 42 --format fhir-r4 \
    --output ./out
```

## The country profile: `country.yaml`

`clinosim/locale/<cc>/country.yaml` holds only the values that differ from
`clinosim/locale/_root/country.yaml`; the two are deep-merged (maps merge key by
key, lists and scalars replace). Start from `clinosim/locale/_template/country.yaml`
or from the `us` / `jp` file. The keys are specified in
[`design-guides/country-profile-spec.md`](design-guides/country-profile-spec.md) §3.2:

| Key | What to set |
|---|---|
| `code` | Upper-case ISO code; it must equal the directory name (`locale/qq/country.yaml` declaring `US` raises `ValueError`) |
| `healthcare_system` | Stem of the healthcare-system config in `clinosim/config/` (`us` → `us.yaml`, `japan` → `japan.yaml`). **No root default**: create `clinosim/config/<stem>.yaml` (validated as `HealthcareSystemConfig`, `clinosim/types/config.py`) |
| `language`, `timezone` | Output language (ISO 639-1) and the UTC offset used for FHIR timestamps |
| `code_systems` | Exactly the five kinds `lab`, `diagnosis`, `drug`, `procedure`, `microbiology`; each value must be a key of `clinosim.codes` |
| `fhir_profiles` | A list drawn from `us_core`, `jp_core`, `jp_clins`, `jp_echeckup` (`FHIR_PROFILES` in `clinosim/country_profile.py`); `[]` means base FHIR |
| `features` | Switches declared in the root (`health_checkup`, `care_level`, `maternal_tdap`); a country cannot add a new feature name by itself |
| `formats` | Name order, date / time / date-time formats, physician name prefix |
| `implementations` | The named implementation per algorithm kind (`egfr_equation`, `triage_scale`, `identity_provider`, `lab_coding`, `drug_system`, `drug_order_code`, `copay_rule`, ...) |

What fails when the profile is wrong (all observed):

- no `country.yaml`: `KeyError: no country profile for 'XX'; supported: [...]`
  from `country_profile(...)`, and a `simulate --country XX` run stops with it;
- `code` different from the directory: `ValueError`;
- `healthcare_system` missing: `KeyError: country XX names no healthcare_system`
  when the healthcare config is loaded; the named file missing:
  `FileNotFoundError: Healthcare config not found`;
- an unknown code system, FHIR profile, feature or implementation kind: a
  validation error at load;
- an implementation name nobody registered:
  `ValueError: country XX: unregistered implementations {...}`.

### Implementations

By default a new country inherits the root implementations (the US ones:
`ckd_epi_2021` eGFR, `esi` triage, `us` identity provider, `loinc` lab coding,
`category_rate` copay, ...). To select another registered implementation, name
it in `implementations:`. The registered names are the `@register_implementation(kind, name)`
decorators in the modules listed in `IMPLEMENTATION_MODULES`
(`clinosim/country_profile.py`); `clinosim/locale/jp/country.yaml` shows every kind.

If the country needs an algorithm that does not exist yet, write it as a named
implementation (a country-only one lives in `clinosim/countries/<cc>/`), decorate
it with `@register_implementation(kind, name)`, and **add its module to
`IMPLEMENTATION_MODULES`** — there is no discovery, and an unlisted module is
never imported, so the profile fails with "unregistered implementations".
This edits `clinosim/country_profile.py`, a core file.

## Required YAML files

Create these under `clinosim/locale/xx/`. See the `_template/` scaffold
(`clinosim/locale/_template/`) for schema comments and skeleton values;
`_template/demographics.yaml` follows the same schema as the us/jp files.

| File | Purpose | Authoritative source hint |
|---|---|---|
| `country.yaml` | The country profile (above); it is what makes the country exist | — |
| `names.yaml` | Family + given names with frequency weights | National statistics office / civil registry |
| `addresses.yaml` | Regions (state / prefecture / province) + postal codes + phone patterns | National postal service |
| `demographics.yaml` | Age distribution, blood type, chronic-disease prevalence (see schema note below), disease incidence, lifestyle, ED-only visit rate (`ed_visit_not_admitted.rate_per_1000_person_years`) | Government census / disease surveillance / national ED utilization survey |
| `formatting.yaml` | Date / time / number formatting | Local convention |
| `code_mapping_diagnosis.yaml` | Internal disease id → national diagnosis code | Local coding scheme |
| `code_mapping_lab.yaml` | Internal lab name → national lab code | Local lab code system (JLAC10 / LOINC / national) |
| `code_mapping_drug.yaml` | Internal drug name → national drug code | Formulary code (YJ / RxNorm / national) |
| `code_mapping_procedure.yaml` | Internal procedure name → national procedure code | Local procedure scheme (K code / CPT / national) |
| `reference_range_lab.yaml` | Sex / age lab reference ranges | Local clinical society standard |
| `care_practice.yaml` | Inpatient care practice: discharge criteria, time to surgery, rehabilitation minutes | National practice survey / clinical guideline |
| `population_genetics.yaml` | Rh fraction, ABO allele frequencies, drug-metabolism phenotypes | Population genetics publications |

`care_practice.yaml` and `population_genetics.yaml` exist in `us/` and `jp/`
but not in `_template/`; copy them from `us/` and replace the values.

### What fails loudly and what falls back

Observed by deleting one file at a time from a copy of `us/` registered as
`XX` and running `clinosim simulate --country XX --population 5 --seed 42
--format fhir-r4`:

| Missing | Result |
|---|---|
| `addresses.yaml` | The run stops (`KeyError: 'phone'`) |
| `care_practice.yaml`, `population_genetics.yaml` | The run stops (`FileNotFoundError: locale/xx/<file> is missing or empty`, `clinosim/locale/loaders/country_parameters.py`) |
| `names.yaml`, `formatting.yaml`, `demographics.yaml` | The run does not stop: the loader falls back to the neutral built-in defaults of `clinosim/locale/shared/fallback_defaults.yaml`, so the data are not locale-representative |
| `code_mapping_*.yaml`, `reference_range_lab.yaml`, and the optional files below | The run does not stop: the loader returns an empty table and the corresponding values are simply absent or uncoded in the output. Check the output; a five-person run does not exercise every code path |

A file that is present but malformed is validated at load and raises.

## Entries outside `locale/<cc>/`

Some reference data are keyed by country inside files that are not in the
country folder. Adding the country means adding its key there too. Observed by
running the cohort command above with only the files of `locale/xx/`:

| File | Entry to add | If missing |
|---|---|---|
| `clinosim/locale/shared/naming_rules.yaml` | A top-level `xx:` block (name order, middle-name and surname rules) | The run stops: `KeyError: 'xx'` (`load_naming_rules`) |
| `clinosim/modules/population/reference_data/anthropometric_reference.yaml` | An `XX:` block under `pediatric_growth` (height / weight / head circumference by age and sex) | Import-time `ValidationError`: "pediatric_growth countries must be the supported countries" |
| `clinosim/modules/encounter/reference_data/minor_burn.yaml`, `minor_laceration.yaml` | An `xx:` key in each `codes:` mapping of `diagnosis_variants` (every supported country needs a code) | `ValueError: Invalid encounter condition YAML` |
| `clinosim/locale/shared/actuarial_life_table.yaml` | An `xx:` entry under both `annual_mortality_qx` and `community_death_share` | Falls back to the US block (`clinosim/modules/population/mortality.py::_locale_key`) |
| `clinosim/locale/shared/country_language.yaml` | `xx: <language>` | The language falls back to `en` |
| Disease YAMLs (`clinosim/modules/disease/reference_data/*.yaml`) | `target_los` is keyed `japan` / `us` | A country without its own block uses the `us` one (`clinosim/modules/disease/localization.py::target_los_config`) |
| `clinosim/modules/drug_safety/` hyperkalemia `treatment` and `clinosim/modules/order/label_dose.py` `limits` | Optional upper-case country keys | A key that is not a supported country code is rejected at load; these are subsets, not required for every country |

The first three rows are edits to files owned by other modules; there is no
single place that lists them, so run the cohort command and fix the error it
names until it completes.

### `demographics.yaml::chronic_prevalence` schema variants

Two accepted shapes per entry:

- **Flat form** (single-sex or sex-neutral): `sex: F|M|""` +
  `"<lo>-<hi>": <target_marginal>` age-band pairs. Sampled from
  the shared population master RNG.

  ```yaml
  chronic_prevalence:
    N40:                  # BPH, male-only
      sex: M
      "60-99": 0.20
    E11:                  # T2DM, sex-neutral
      "40-99": 0.10
  ```

- **`by_sex` form** (asymmetric per-sex bands, e.g. male breast
  cancer at ~1 % of C50 total with a later age peak than female
  BC). The first sex key becomes the primary (sampled on the
  master RNG identically to the flat form); every remaining sex
  key becomes an entry in `augment_sex_bands` sampled from a
  per-`(patient_id, code)` sub-RNG so opposite-sex activation
  does not cascade the master stream.

  ```yaml
  chronic_prevalence:
    C50:                  # Breast cancer — F primary + M ~0.02 %
      by_sex:
        F:
          "40-59": 0.015
          "60-99": 0.030
        M:
          "60-99": 0.0002
  ```

Full behavior + downstream sex-conditional billing-code mapping:
[`reference/oncology-obstetric-service-lines.md`](reference/oncology-obstetric-service-lines.md) §3.

### `demographics.yaml::ed_visit_not_admitted`

Rate of ED visits that end without admission, per 1,000 person-years.
The forward month loop draws the month's ED-visit count from it
(`clinosim/simulator/phases/_ed_slot.py`). A missing key means a rate
of 0 — the cohort gets no ED-only visits.

```yaml
ed_visit_not_admitted:
  rate_per_1000_person_years: 380   # US value; JP ships 150
```

### Mortality (`locale/shared/actuarial_life_table.yaml`)

Community deaths (outside the simulated inpatient stays) are drawn
forward per person per year by `clinosim/modules/population/mortality.py`:
life-table `qx` (age band × sex) × the person's relative chronic-condition
SMR × `community_death_share`. Both `annual_mortality_qx` and
`community_death_share` are keyed by locale (`us`, `jp`) in the shared
yaml. Add an `xx` entry under both keys for your locale; a locale with
no entry falls back to the US block.

## Optional YAML files (opt-in modules)

Only add these when your country supports a specific opt-in module; without
the file the run does not stop (see the table above):

| File | When to add | Module |
|---|---|---|
| `identity.yaml` | Modeling a national identifier / insurance number | `identity` |
| `code_mapping_microbiology.yaml` | National microbiology coding | `microbiology` |
| `code_mapping_microbiology_susceptibility.yaml` | National susceptibility reporting | `microbiology` |
| `care_level_rates.yaml` | Long-term-care level (JP 要介護度 相当) | `care_level` — JP-specific concept, generally skip |
| `code_status_rates.yaml` | Resuscitation status distribution | `code_status` |
| `family_history_prevalence.yaml` | First-degree relative disease prevalence | `family_history` |
| `immunization_schedule.yaml` | Local vaccination schedule | `immunization` |
| `ambulatory_visit_length.yaml` | Outpatient visit-length distributions per visit type | outpatient simulator (falls back to a flat 15/25/45-minute triangle) |

## FHIR profiles

Whether a national FHIR profile is applied is declared in the country profile:
list it under `fhir_profiles:` in `country.yaml`. The output builder gates on the
profile, not on the country: `_finalize_resource`
(`clinosim/modules/output/fhir_r4/builder.py`) calls
`profile.uses("jp_core")`, `profile.uses("jp_clins")` and `profile.uses("us_core")`
and applies `_apply_jp_core_profile`, `_apply_jp_clins_profile` and
`_apply_us_core_profile` (helpers in
`clinosim/modules/output/fhir_r4/post_process/profile.py`; URL registries
`clinosim/codes/data/fhir-profiles-{jp-core,us-core,jp-clins}.yaml`). A country
with `fhir_profiles: []` gets base FHIR; a third country is never given a
foreign profile.

So for a country that uses US Core or the JP profiles, setting `fhir_profiles`
is all that is needed. For a profile clinosim does not know (DE Basisprofil,
AU Core, ...) you must edit core files: add the name to `FHIR_PROFILES` in
`clinosim/country_profile.py`, add a registry YAML mirroring the existing ones,
add an `_apply_<name>_profile` helper, and add an `if profile.uses("<name>"):`
gate in `_finalize_resource`. Per the spec (§5) such a branch only decides
whether the structure the profile mandates is emitted; the values inside it
come from YAML.

## Country features (opt-in modules)

Country-specific modules are switched by `features:` in the profile, not by a
country check:

- `identity` — always on (JP honours `--no-jp-insurance`); `assign_identities`
  no-ops when the locale has no `identity.yaml`
- `care_level` — `features.care_level` (JP only today); skip
- `health_checkup` — `features.health_checkup` (JP-eCheckup); skip unless
  designing an equivalent
- `maternal_tdap` — `features.maternal_tdap` (on for the US)

## Testing checklist

After creating the country folder:

- [ ] `python -c "from clinosim.country_profile import country_profile; print(country_profile('XX'))"`
      loads the profile without an error
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
      "Diagnosis code coverage" section of `AGENTS.md`.
- [ ] `pytest tests/unit tests/modules tests/simulator` (the directories CI
      runs) still passes; load-time checks such as the diagnosis-rule code check
      (`clinosim/simulator/diagnosis_rules.py`) iterate `supported_countries()`, so
      the new country is validated by them

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
- **Do not copy `jp/country.yaml` or `us/country.yaml` unchanged**: the copied
  `code` fails validation, and the copied profiles, features and implementations
  describe that country, not yours.

## Where to go next

- Country profile specification: [`docs/design-guides/country-profile-spec.md`](design-guides/country-profile-spec.md)
- Overall project concept: [`docs/design-guides/project-concept-and-design.md`](design-guides/project-concept-and-design.md)
- Locale module reference: [`clinosim/locale/README.md`](../clinosim/locale/README.md)
- Diagnosis code coverage rules: [`AGENTS.md`](../AGENTS.md) §"Diagnosis code coverage"
- Reproducibility invariant: [`docs/development/reproducibility.md`](development/reproducibility.md)

## Scaffold template

`clinosim/locale/_template/` contains a placeholder set of YAMLs with schema
comments. **These placeholders are non-functional** — running `clinosim simulate
--country _template` will fail because `_template` is not a country (the
directory starts with an underscore, so `country_profile` rejects it), and the
values are TODO markers, not data. The template exists purely to show the
required schema shapes for authoring a real country pack.
