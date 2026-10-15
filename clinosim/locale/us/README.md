# `clinosim/locale/us/` — US-locale data files

Country-specific overrides for the US cohort. Loaded by
`clinosim.locale.loader` when `config.country == "US"`.

## Scope

- US-specific demographic distributions, admission mix, chronic
  prevalence tables, and clinical-code mappings.
- Any field whose canonical reference differs between the US and
  JP cohorts (prevalence rates, test-code catalogs, department /
  specialty rollups).

## Shared vs locale-specific

Data that is the same across countries lives under
`clinosim/locale/shared/`; this directory holds **only the US-
specific overrides**. The loader merges `shared/<file>.yaml`
with `us/<file>.yaml` where both exist, with the US file
taking precedence.

## Intentional US-vs-JP asymmetry

Five files exist under `clinosim/locale/jp/` but have no US
sibling by design:

| JP file | Reason the US sibling is absent |
|---|---|
| `care_level_rates.yaml` | Japanese Long-Term Care Insurance (介護保険) specifies five explicit care levels (要支援 1-2 + 要介護 1-5) with national incidence rates. The US Medicare / Medicaid LTC pathway is not level-coded in the same way, so there is no equivalent national rate table to port. |
| `code_mapping_microbiology.yaml` + `code_mapping_microbiology_susceptibility.yaml` | JLAC10 / JSLM pins the Japanese microbiology code mapping. The US cohort reuses the shared LOINC lookups in `clinosim/codes/data/loinc.yaml` directly — no US-specific mapping needed. |
| `external_organizations.yaml` | JP MedicationRequest / Encounter resources often reference external pharmacy / referral practice names explicitly. US cohort encounters do not currently emit this directly. |
| `practitioner_qualifications.yaml` | Japanese 医籍登録番号 / 専門医制度 is a national qualification registry with specific values. The US cohort's practitioner profile does not currently require a parallel structure. |

These absences are intentional — a new US contributor adding
one of these concepts should treat the JP file as a reference
only, not as a mandatory US mirror. If the US cohort grows to
need the concept (e.g. US LTC levels, US-specific microbiology
code system), add the US file explicitly rather than
copy-pasting the JP structure.

## Adding a new file

The loader auto-discovers any new `*.yaml` under this
directory. Mirror the shared / jp sibling if one exists, or
add a leading docstring block in the yaml header explaining
the US-specific origin of the data.

If the data is identical between US and JP, add it to
`clinosim/locale/shared/` instead so both locales pick it up
automatically.
