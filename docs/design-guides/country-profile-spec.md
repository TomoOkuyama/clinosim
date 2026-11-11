# Country Profile Spec — how country differences are expressed

**Status:** Active (design adopted 2026-11-10; migration tracked by Issues).
**Audience:** everyone adding a country, changing country-specific
behaviour, or touching code that branches on country.
**Governs:** the grand design in
[`implementation-rules.md`](implementation-rules.md#grand-design-code-and-data-are-separated)
as it applies to countries. Code systems, display text and localization
stay governed by
[`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md);
YAML loading and validation by
[`configuration-and-reference-data-spec.md`](configuration-and-reference-data-spec.md).

## 1. Principle

Country differences are **data**, selected by a **country profile**. Code
holds generic logic and, where a country needs its own algorithm, a named
implementation that the profile selects. The common flow never asks "is
this Japan?"; it asks the profile for a value, a capability or an
implementation.

| What differs between countries | Where it lives | Example |
|---|---|---|
| a value: code, display text, threshold, rate, age cut-off, unit, format, list | YAML (`clinosim/locale/<cc>/`, a module's `reference_data/`, `clinosim/codes/data/`) | discharge criteria, time to surgery, name order, phone format, insurer table |
| an algorithm only some countries use | code, as a named implementation | the JSN eGFR equation, an insurer-number check digit, JTAS vs ESI triage |
| which algorithm, profile, feature or code system a country uses | the country profile (YAML) | `implementations.egfr_equation: jsn`, `fhir_profiles: [jp_core, jp_clins]` |

Adding a country is a data change (a profile and its locale YAML); code
changes only when the country needs an algorithm no country has yet.

## 2. Established patterns this follows

- **Locale data with inheritance and fallback** (Unicode CLDR, Babel): a
  root holds defaults and each locale stores only its overrides; a missing
  value resolves through the parent to the root.
- **Defaults overridden per country** (Synthea international): country
  resources and settings replace the defaults without editing them.
- **Formats as metadata** (Google libaddressinput / libphonenumber): one
  formatter, per-country templates and patterns as data.
- **Per-country code by ISO code** (django-localflavor `localflavor.jp`,
  Odoo `l10n_jp`, Faker locale providers): country-specific algorithms live
  in a package named by the country code.
- **Named implementations selected by explicit configuration** (strategy
  registry): implementations register under a name; configuration names
  the one to use; nothing is discovered implicitly.

## 3. The country profile

### 3.1 Files

- `clinosim/locale/_root/country.yaml` — the defaults every country
  inherits.
- `clinosim/locale/<cc>/country.yaml` — one country's overrides only,
  deep-merged over the root (maps merge key by key; lists and scalars
  replace).
- The supported countries are the directories that have a `country.yaml`.
  `_root` and `_template` are not countries.

### 3.2 Contents

| Key | Meaning |
|---|---|
| `code` | ISO 3166-1 alpha-2 code (`US`, `JP`). |
| `language`, `timezone` | Output language (ISO 639-1) and the UTC offset or zone used for FHIR timestamps. |
| `code_systems` | The code-system key per kind (`lab`, `diagnosis`, `drug`, `procedure`, `microbiology`), resolved by `clinosim.codes`. |
| `fhir_profiles` | The FHIR profiles applied to output (`us_core`, `jp_core`, `jp_clins`, `jp_echeckup`). |
| `features` | Country features switched on or off (`health_checkup`, `care_level`, `maternal_tdap`, ...). |
| `formats` | Name order (`given_family` / `family_given`, applied by `formats.name_parts(family, given)`), date, time and date-time formats, and the physician name prefix (`physician_name_prefix`). |
| `healthcare_system` | Stem of the country's healthcare-system YAML in `clinosim/config/` (`us`, `japan`); no root default. |
| `implementations` | The named implementation per algorithm kind (`egfr_equation`, `triage_scale`, `copay_rule`, `insurer_number`, ...). |

Address and phone formats are patterns in `clinosim/locale/<cc>/addresses.yaml`
(`street_line`, `apartment_line`, `phone.{mobile,landline,staff_work,ward}`,
`fhir_address`), drawn and formatted by one generic formatter,
`clinosim/locale/patterns.py` (libaddressinput / libphonenumber style). The
Patient's MRN system and national identifier are in
`clinosim/locale/<cc>/identity.yaml` (`fhir_patient`).

Country-specific **parameters of a module** (for example discharge
criteria or time to surgery) stay in that module's `reference_data/`
or in `clinosim/locale/<cc>/<topic>.yaml`, keyed by country and read
through the module's loader; the profile does not duplicate them.

### 3.3 API

All of it lives in `clinosim/country_profile.py`.

- `country_profile(country) -> CountryProfile` — a validated, cached
  Pydantic model (`extra="forbid"`, frozen). The country code is matched
  case-insensitively; legacy spellings (`"japan"`) map through a data table
  in the loader, not through `is_jp` / `is_us`. An unknown country raises
  `KeyError`; it never falls back to the US silently.
- `profile.code`, `profile.language`, `profile.language_tag` (BCP 47
  `<language>-<code>`, e.g. `ja-JP`), `profile.timezone` (`"Z"` or a
  `+HH:MM` / `-HH:MM` UTC offset), `profile.formats`.
- `profile.uses(profile_name) -> bool`, `profile.feature(name) -> bool`,
  `profile.code_system(kind) -> str`, `profile.implementation(kind) -> str`.
  Each raises `KeyError` on an unknown name (a FHIR profile outside the
  known set, or a feature or kind the profile does not carry), so a typo
  fails instead of reading as "off".
- `implementation(kind, country)` — the callable registered under the
  name the profile selects (§4).
- `supported_countries()` — the upper-case codes of the locale directories
  that hold a `country.yaml`, excluding `_root` and `_template`.
- `load_profile_data(country)` — the merged, unvalidated mapping (root
  deep-merged with the country file); `deep_merge(base, override)` is the
  merge itself.
- `validate_implementations(profile)` — imports the registering modules
  (§4) and raises `ValueError` if the profile names an unregistered
  implementation. `country_profile` calls it before returning.

Validation at load: every code system is a key of `clinosim.codes` and the
five kinds are covered exactly; every FHIR profile name is known; feature
and implementation kinds must be declared in `_root/country.yaml`; the
`code` in `locale/<cc>/country.yaml` must equal `<cc>`.

`is_jp` / `is_us` are not used by the profile loader; new code calls the
profile.

## 4. Named implementations

- An algorithm kind declares its signature once (a `Protocol`) next to the
  generic code that calls it.
- Implementations register explicitly with
  `@register_implementation(kind, name)`; registering the same kind and name
  twice raises `ValueError`. An algorithm several countries may use lives
  next to the generic code (for example the eGFR equations in
  `clinosim/modules/physiology/egfr.py`).
- A country-only algorithm lives in a country package
  `clinosim/countries/<cc>/` (django-localflavor style). The country
  helpers (`is_jp`, `lang_for`, `country_code`, ...) are the package's
  `clinosim/countries/__init__.py` (formerly a single module, same
  API). `clinosim/countries/jp/` holds the JP identity provider, the
  JP-CLINS lab coding, the JP drug code-format dispatch, the YJ drug order
  code, the JP copay rule and JTAS (Issue #3194).
- Registration is explicit: every module that registers an implementation
  is listed in `IMPLEMENTATION_MODULES` in `clinosim/country_profile.py`,
  and those modules are imported before a profile is validated. There is no
  entry-point or package-scan discovery. A profile naming an unregistered
  implementation fails at load.
- An implementation's coefficients follow the constants rule: a formula's
  coefficients in its `_<topic>_thresholds.py` or reference YAML, values
  that differ by country in YAML.

## 5. Branches that remain

A branch on the profile is allowed only to decide whether a structure
that a FHIR profile or spec mandates is emitted (`if profile.uses("jp_core"):`
add the JP Core slice). The values inside that structure come from YAML.
A branch that selects a value is a table written as code and moves to
YAML (policy §5.1).

## 6. Enforcement

- A shrink-only ratchet counts country / language branches and numeric
  literals in comparisons per file and fails when a file exceeds its
  baseline (Issue #3137).
- The profile model forbids unknown keys and validates every code system,
  profile, feature and implementation name it references.

## 7. Migration

The migration runs as one PR per step, each byte-identical in output
unless the step fixes a defect:

1. Profile files, model, loader and API; the ratchet.
2. Language, timezone, name / address / phone formats and identifiers read
   from the profile and locale YAML.
3. Country parameters hard-coded in Python moved to YAML.
4. Code-system policy and the supported-country list read from the
   profile.
5. Country features read from `profile.feature(...)`.
6. Country algorithms registered and selected by the profile.
7. The remaining `is_jp` branches in FHIR output replaced by
   `profile.uses(...)` structural gates, one resource family per PR.

Splitting FHIR builders into per-profile plugins is not part of this
migration; it is reconsidered after step 7 for any resource family whose
profile-specific code is still large.
