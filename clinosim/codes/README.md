# `clinosim.codes` — clinical code systems

## Purpose

Provides the **single source of truth for clinical code systems** in
clinosim.

CIF (Clinosim Intermediate Format) stores codes only; display text is
resolved at output time through this module. That gives:

- One code = one entry + multi-language display attributes (English,
  Japanese, …)
- FHIR / HL7 v2 / CDA / CSV output formats all reference the same
  terminology source
- Translation drift is prevented structurally
- Clean separation between locale-independent international standards
  and locale-specific data (which lives under `clinosim/locale/`)

## Scope

- **In scope**: unified lookup for every clinical code system clinosim
  emits, multi-language display resolution, canonical FHIR system-URI
  mapping (79 URIs registered in `_BUILTIN_URIS`), curated code data
  YAMLs, HL7 v2/v3 vocabulary StrEnums for the Encounter resource,
  authoritative-source JSON fragments captured for reproducibility
  (see `authoritative/`).
- **Out of scope**: locale-scoped data such as names, addresses,
  formatting rules (those live in `clinosim/locale/`), disease /
  observation / medication content (in `clinosim/modules/*/`), the
  CIF data schema itself (in `clinosim/types/`).

## Public API

`clinosim.codes.__all__` lists 16 names:

```python
from clinosim.codes import (
    # loader.py — registry lookup
    lookup,                        # (system, code, lang="en") -> str  (never None; falls back to the code)
    display,                       # (system, code, lang="en") -> str | None  (None when unregistered)
    code_exists,                   # (system, code, *, exact=False) -> bool
    code_system,                   # (system_key) -> CodeSystem | None
    system_keys,                   # () -> tuple[str, ...]
    get_system_uri,                # (system) -> str
    system_key_for_uri,            # (uri) -> str | None  (inverse of get_system_uri)
    system_key_for,                # (kind, country) -> str  (e.g. ("diagnosis","JP")→"icd-10-mhlw")
    slug_to_code,                  # (system_key) -> dict[str, str]  (yaml `slug_to_code:` block)
    data_table,                    # (name) -> dict  (copy of codes/data/<name>.yaml)
    is_english_only_system,        # (system_key_or_uri) -> bool
    ENGLISH_ONLY_SYSTEM_PREFIXES,  # tuple of URI prefixes of English-only CodeSystems
    CodeSystem,                    # dataclass: key, name, uri, version, codes, siblings
    # jlac10.py — JP lab codes
    jlac10_display,                # (code, lang) -> str | None
    jp_clins_lab_system,           # (kind) -> str  (JP lab CodeSystem URI)
    # valuesets.py
    has_icd_prefix,                # (chronic_items, prefixes) -> bool
)
```

The per-system accessor modules (`bcp47`, `drugs`, `icd10`, `loinc`,
`medis`, `prefectures`, `procedures`, `snomed`, `snomed_concepts`,
`ucum`, `yj`, the rest of `valuesets`) are imported by module path, e.g.
`from clinosim.codes.drugs import resolve_drug`.

HL7 vocabulary StrEnums for the Encounter resource (Issue #562) —
importable from `clinosim.codes.hl7_encounter`:

```python
from clinosim.codes.hl7_encounter import (
    AdmitSource,          # http://terminology.hl7.org/CodeSystem/admit-source
    DischargeDisposition, # http://terminology.hl7.org/CodeSystem/discharge-disposition
    ActPriority,          # http://terminology.hl7.org/CodeSystem/v3-ActPriority
)
```

`StrEnum` inherits from `str`, so
`encounter.admit_source = AdmitSource.EMD` stays wire-compatible with
the pre-refactor `str` typing (comparisons `== "emd"` continue to
work). `AdmitSource.BORN` (= `"born"`) was added for the perinatal
newborn-Patient chain — the newborn's Encounter carries it plus
`admit_source_encounter_id` pointing at the mother's delivery
Encounter, which becomes `Encounter.partOf` on the FHIR side.

## Determinism

Not applicable — the package is pure lookup. `_load_system` is
`@functools.cache`-decorated so a given system key resolves to the identical
`CodeSystem` instance on every call. Given the same YAML on disk, the
same `(system, code, lang)` triple always resolves to the same string.

## Dependencies

- `clinosim.datafiles` (`load_data_yaml`, `data_metadata`) for YAML
  loading (`pyyaml` underneath).
- `clinosim.countries` (`normalize_lang`, `lang_for`) for language-key
  normalisation.
- `clinosim.locale.localized` (`localized`) for the multi-language name
  fallback in `drugs.py` and `procedures.py` (imported lazily inside
  functions).
- Standard library `pathlib`, `functools`, `dataclasses`, `enum`,
  `json`, `re`, `copy`.

## Constants and configuration

- **`_DATA_DIR`** = `Path(__file__).parent / "data"` — where the
  per-system YAML files live.
- **`_BUILTIN_URIS`** — 79 short-key → canonical URI mappings for
  every code system clinosim emits (ICD variants, LOINC, SNOMED CT,
  RxNorm, JLAC10, YJ, HOT7/9/13, K-codes, JP-Core NamingSystems, HL7
  v2/v3/FHIR terminology CodeSystems, JP-CLINS eCS Nocoded, clinosim-
  owned CodeSystems for gap-filling — see the block-level comments in
  `loader.py` for rationale per URI).
- **`_SYSTEM_DATA_ALIASES`** — Issue #350 mechanism for two keys that
  share the same code data but need distinct canonical URIs (concrete
  case: `icd-10-mhlw` aliases to `icd-10` code data with the JP
  MHLW-2013 registry URI).
- **Language fallback chain** — requested lang → `en` → first
  available language → the code itself.
- **Code lookup fallback chain** — exact match → base code (strip
  trailing subcode) → sub-code prefix scan → the code itself.

## Directory contents

```
clinosim/codes/
  __init__.py                     public API (16 exports)
  loader.py                       CodeSystem dataclass, lookup / display /
                                  code_exists / code_system / system_keys /
                                  get_system_uri / system_key_for(_uri) /
                                  slug_to_code / data_table,
                                  _BUILTIN_URIS, _SYSTEM_DATA_ALIASES
  valuesets.py                    shared value sets (code groups) for
                                  decision logic; has_icd_prefix
  hl7_encounter.py                AdmitSource / DischargeDisposition /
                                  ActPriority StrEnums
  drugs.py                        drug identity catalog loader
                                  (data/drugs.yaml; resolve_drug /
                                  all_drug_ids)
  bcp47.py                        BCP 47 language-tag display
  icd10.py                        ICD-10 displays, condition short names,
                                  MEDIS crosswalk
  jlac10.py                       JLAC10 / JP-CLINS lab accessor
  loinc.py                        LOINC display and coding
  medis.py                        MEDIS disease-name key numbers
  prefectures.py                  JIS X 0401 prefecture codes
  procedures.py                   procedure codes and names
  snomed.py                       SNOMED CT displays and internal-key maps
  snomed_concepts.py              named SNOMED CT concept constants
  ucum.py                         UCUM units for FHIR Quantities
  yj.py                           YJ / HOT JP drug code formats and the
                                  YJ master
  data/                           75 YAMLs: code systems (see
                                  "Supported code systems" below) plus
                                  curated catalogs (drugs, frequency
                                  tokens, FHIR profile maps, value
                                  sets, crosswalks, …)
  authoritative/                  authoritative-source snapshots used
                                  to verify the curated displays (see
                                  authoritative/README.md for the
                                  per-file table)
```

## Testing

```bash
pytest tests/unit -k codes -q
```

Approximately 100 test files reference `clinosim.codes`, covering the
fallback chain, system-URI resolution, `system_key_for` country
dispatch, JP-only-display detection, and per-system data-shape
invariants.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).

---

## Design principles

| # | Principle | Description |
|---|---|---|
| 1 | **English is the primary data** | Every code must carry an `en` field. Other languages are translation options. |
| 2 | **Authoritative source alignment** | Code values and English display follow the latest release of the official body (CMS, NLM, AMA, WHO, MHLW, MEDIS, JCCLS, …). |
| 3 | **Locale-independent** | Code systems are international. `clinosim/locale/` holds only culture-dependent data (names, addresses, …). |
| 4 | **Code is the truth** | CIF stores only `code` + `system`. Display is derived (looked up at output time). |
| 5 | **Fallback chain** | Requested language → English → the code itself (always returns something). |
| 6 | **Alias, don't duplicate** | Two systems that share code data but need distinct canonical URIs use `_SYSTEM_DATA_ALIASES` instead of duplicated YAMLs. |

## Supported code systems

### Core clinical registries (with curated data)

| Key | Name | FHIR system URI | Source |
|---|---|---|---|
| `icd-10-cm` | ICD-10-CM | `http://hl7.org/fhir/sid/icd-10-cm` | CMS / NCHS |
| `icd-10` | WHO ICD-10 | `http://hl7.org/fhir/sid/icd-10` | WHO ICD-10 |
| `icd-10-mhlw` | JP MHLW ICD-10 (2013 registry) | `http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full` | MHLW / JP-Core — code data aliased to `icd-10` |
| `loinc` | LOINC | `http://loinc.org` | Regenstrief LOINC |
| `snomed-ct` | SNOMED CT | `http://snomed.info/sct` | IHTSDO |
| `jlac10` | JLAC10 | `urn:oid:1.2.392.200119.4.1005` | JCCLS |
| `rxnorm` | RxNorm | `http://www.nlm.nih.gov/research/umls/rxnorm` | NLM RxNorm |
| `yj` | YJ code | `http://capstandard.jp/iyaku.info/CodeSystem/YJ-code` | JP Core / capstandard; MHLW YJ master |
| `hot7` | HOT7 (JP MEDIS) | `http://medis.or.jp/CodeSystem/master-HOT7` | MEDIS — URI only, no code data (Issue #2347) |
| `cpt` | CPT | `http://www.ama-assn.org/go/cpt` | AMA CPT |
| `k-codes` | K codes | `urn:oid:1.2.392.200119.4.401` | MHLW reimbursement schedule |
| `cvx` | CVX (vaccine codes) | `http://hl7.org/fhir/sid/cvx` | CDC |

Code counts grow with every new scenario, so they are not listed
here; count a system's entries with
`python -c "from clinosim.codes import code_system; print(len(code_system('loinc').codes))"`
(substitute the system key).

### HL7 terminology CodeSystems (data-backed)

| Key | Codes |
|---|---|
| `hl7-condition-clinical`, `hl7-condition-ver-status` | 6 + 6 |
| `hl7-admit-source`, `hl7-discharge-disposition` | 4 + 4 |
| `hl7-allergyintolerance-clinical`, `hl7-allergyintolerance-verification` | 3 + 5 |
| `hl7-observation-interpretation` | 14 |
| `hl7-practitioner-role`, `hl7-subscriber-relationship` | 6 + 7 |
| `hl7-v3-actreason`, `hl7-v3-administrativegender`, `hl7-v3-maritalstatus` | 4 + 3 + 6 |
| `hl7-endpoint-connection-type`, `hl7-endpoint-payload-type` | 1 + 1 |

### JP-specific gap-fill and structural CodeSystems

| Key | Codes |
|---|---|
| `jp-care-level` | 8 |
| `jpfhir-doc-section` | 42 |
| `jpfhir-doc-typecodes` | 6 |
| `jpfhir-eCheckup-section` | 7 |
| `jpfhir-eCheckup-report-category` | 9 |
| `jpfhir-eCheckup-program-service` | 10 |
| `jpfhir-eCheckup-observation` | 5 |
| `condition-short-name` | 53 |
| `clinosim-nursing-scores` | 1 |
| `bcp-47-language` | 2 |

### URI-only registrations (no YAML data)

`_BUILTIN_URIS` also registers URIs for systems that clinosim references
but does not need to display strings from — HOT9, HOT13, medication-nocoded,
UCUM, additional HL7 v2 / v3 / terminology systems (v2-0092, v2-0131,
v2-0203, v2-0360, service-type, referencerange-meaning, organization-type,
condition-category, location-physical-type, RoleCode, ParticipationType,
ActCode, ObservationCategory, DiagnosticServiceSection), US Core
documentreference-category. Use `get_system_uri()` to resolve; `lookup()`
falls back to returning the code itself.

## YAML schema

```yaml
metadata:
  name: "ICD-10-CM"                              # human-readable name
  uri: "http://hl7.org/fhir/sid/icd-10-cm"       # FHIR canonical URI
  version: "2024"                                # edition / year
  description: "International Classification..." # description

codes:
  N10:                                            # code value (string key)
    en: "Acute tubulo-interstitial nephritis"   # English display (required)
    ja: "急性腎盂腎炎"                          # Japanese display (optional)
  J18.9:
    en: "Pneumonia, unspecified organism"
    ja: "肺炎，詳細不明"
```

### Schema rules

- Set `metadata.uri`. When a YAML exists but has no `metadata.uri`,
  its URI becomes `urn:clinosim:<key>`; `_BUILTIN_URIS[key]` is used
  only for keys with no YAML and for `_SYSTEM_DATA_ALIASES` entries.
- Every entry under `codes` must include at least `en` (or `ja` for
  JP-only display systems such as `icd-10-mhlw`).
- Additional languages use ISO 639-1 two-letter codes (`ja`, `de`,
  `fr`, `zh`, …).
- Code values are strings and preserve source formatting: ICD uses
  `J18.9`, LOINC uses `1988-5`, RxNorm uses `309090`.

## Example: FHIR Observation output

```python
from clinosim.codes import get_system_uri, lookup

lab_result = {"code": "1988-5", "value": 38.2, "unit": "mg/L"}

obs = {
    "resourceType": "Observation",
    "code": {
        "coding": [{
            "system": get_system_uri("loinc"),
            "code": lab_result["code"],
            "display": lookup("loinc", lab_result["code"], "en"),
        }],
        "text": lookup("loinc", lab_result["code"], "en"),
    },
    "valueQuantity": {"value": lab_result["value"], "unit": lab_result["unit"]},
}
```

## Extending

### Add a new code

Edit the matching `data/<system>.yaml`, sorted freely (loader looks
up by dict key; alphabetical is recommended for readability):

```yaml
codes:
  J45.901:
    en: "Unspecified asthma with (acute) exacerbation"
    ja: "喘息急性増悪"
```

### Add a new code system

1. Create `data/<new-system>.yaml` (schema above).
2. Optionally register a short key → URI mapping in
   `loader.py::_BUILTIN_URIS`.
3. Simply dropping the file is enough — the loader resolves
   `data/<key>.yaml` by name on first use and caches it
   (`@functools.cache`).

### Add a new language

Add a new language key to each entry:

```yaml
codes:
  N10:
    en: "Acute tubulo-interstitial nephritis"
    ja: "急性腎盂腎炎"
    de: "Akute tubulointerstitielle Nephritis"
```

Codes that lack the requested language fall back to English via the
lookup fallback chain documented under "Constants and configuration".

## Boundary against the `locale` module

| | `clinosim.codes` | `clinosim.locale` |
|---|---|---|
| **Responsibility** | International code systems + multi-language display | Culture- and country-dependent data |
| **Locale-scoped?** | No (all languages in one file) | Yes (`jp/`, `us/`, …) |
| **Typical data** | ICD / LOINC / RxNorm / SNOMED CT / HL7 vocabularies, … | Names, addresses, phone formats, reference intervals |
| **Held by CIF** | Code value + system key | Concrete fields (Address, PersonName, …) |

`locale/<country>/code_mapping_*.yaml` still exists — it maps
simulator-internal test names (e.g. `"WBC"`) to standard codes (e.g.
`"6690-2"`). Display-text resolution is delegated to `clinosim.codes`.

## Licensing and provenance

Each code system follows its own upstream license:

- **ICD-10-CM**: public domain (CMS).
- **WHO ICD-10**: WHO terms of use.
- **LOINC**: LOINC License (free commercial use, redistribution
  permitted).
- **RxNorm**: NLM Open Use (public domain).
- **SNOMED CT**: SNOMED International terms; clinosim ships only a
  small curated subset that appears in generated data.
- **JLAC10**: published by JCCLS.
- **CPT**: AMA copyright — clinosim ships only a minimal educational
  / research subset.
- **YJ code**: MHLW open data.
- **K codes**: MHLW reimbursement schedule.
- **HL7 terminology (v2 / v3 / condition-clinical / …)**: HL7 IPR
  policy — CC BY-SA 4.0 for HL7 terminology CodeSystems.
- **JP Core / JP-CLINS eCS**: MHLW / JAMI open publications.

`codes/data/` extracts only the subset needed to drive clinosim's
synthetic-data generation. For commercial EHR integration, pull the
full current release from the upstream authority.

**The subset must exhaustively cover "codes that can appear in the
output."** For diagnosis codes,
`tests/unit/test_diagnosis_code_coverage.py` guards the invariant
that "every `icd_codes` entry across all diseases / encounters and
every target of the diagnosis map resolves exactly against the code
data". When adding a new outpatient / disease scenario, adding the
referenced ICD codes here is mandatory (see the "Diagnosis code
coverage" note in AGENTS.md); otherwise the FHIR Condition display
falls back to an approximate prefix match.

`authoritative/` captures raw JSON fragments pulled from tx.fhir.org
and MHLW registries at documented points in time — these are the
byte-exact provenance for the curated subset and are what regression
tests diff against.

## Update policy

- **ICD-10-CM**: CMS ships a new edition every October 1 → clinosim
  tracks.
- **LOINC**: released every six months (June / December) → we absorb
  major changes.
- **SNOMED CT**: international release monthly → we track a stable
  release once a year.
- **RxNorm**: weekly updates every Monday → we track a stable release
  once a year.
- **WHO ICD-10**: seldom updated (current release is 2019).
- **JP Core / JP-CLINS eCS**: track the version pinned in
  `.github/jp-validator-pins.env` (JP Core `1.1.7`) and the
  JP-CLINS package version asserted by
  `.github/workflows/jp-clins-lab-compliance-gate.yml`
  (currently `1.13.0`; the v1.12.0 → v1.13.0 delta is additive
  terminology only — 9 new ValueSets for hepatitis serology + labo
  split — so the StructureDefinition canonical URLs emitted by
  clinosim are unchanged).
- Internal short keys are stable. Any YAML structural change is a
  major version bump.
