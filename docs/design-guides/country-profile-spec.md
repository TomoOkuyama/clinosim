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
| `formats` | Name order, address template, phone patterns, MRN / national-identifier specs. |
| `implementations` | The named implementation per algorithm kind (`egfr_equation`, `triage_scale`, `copay_rule`, `insurer_number`, ...). |

Country-specific **parameters of a module** (for example discharge
criteria or time to surgery) stay in that module's `reference_data/`
or in `clinosim/locale/<cc>/<topic>.yaml`, keyed by country and read
through the module's loader; the profile does not duplicate them.

### 3.3 API

- `country_profile(country) -> CountryProfile` — a validated, cached
  Pydantic model (`extra="forbid"`). An unknown country raises; it never
  falls back to the US silently.
- `profile.uses(profile_name) -> bool`, `profile.feature(name) -> bool`,
  `profile.code_system(kind) -> str`, `profile.language`,
  `profile.implementation(kind) -> str`.
- `implementation(kind, country)` — the callable registered under the
  name the profile selects (§4).

`is_jp` / `is_us` remain only as normalisation inside the profile loader
during the migration; new code calls the profile.

## 4. Named implementations

- An algorithm kind declares its signature once (a `Protocol`) next to the
  generic code that calls it.
- Implementations register explicitly with
  `@register_implementation(kind, name)`. A country-only algorithm lives in
  `clinosim/countries/<cc>/` (for example the JP insurer-number check digit);
  an algorithm several countries may use lives next to the generic code
  (for example the eGFR equations in `clinosim/modules/physiology/`).
- Registration happens at import of those modules; there is no
  entry-point discovery. A profile naming an unregistered implementation
  fails at load.
- An implementation's coefficients follow the constants rule: a formula's
  coefficients in its `_<topic>_thresholds.py`, values that differ by
  country in YAML.

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
