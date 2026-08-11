# `clinosim.codes` — clinical code systems

## Purpose

Provides the **single source of truth for clinical code systems** in
clinosim.

CIF (Clinosim Intermediate Format) stores codes only; display text is
resolved at output time through this module. That gives us:

- One code = one entry + multi-language display attributes (English,
  Japanese, …)
- FHIR / HL7 v2 / CDA / CSV output formats all reference the same
  terminology source
- Translation drift is prevented structurally
- Clean separation between locale-independent international standards
  and locale-specific data (which lives under `clinosim/locale/`)

## Design principles

| # | Principle | Description |
|---|---|---|
| 1 | **English is the primary data** | Every code must carry an `en` field. Other languages are translation options. |
| 2 | **Authoritative source alignment** | Code values and English display follow the latest release of the official body (CMS, NLM, AMA, WHO, …). |
| 3 | **Locale-independent** | Code systems are international. `clinosim/locale/` holds only culture-dependent data (names, addresses, …). |
| 4 | **Code is the truth** | CIF stores only `code` + `system`. Display is derived (looked up at output time). |
| 5 | **Fallback chain** | Requested language → English → the code itself (always returns something). |

## Directory layout

```
clinosim/codes/
├── __init__.py            # public API (lookup, get_system_uri, get_display)
├── loader.py              # YAML loader + lookup functions
├── README.md              # this file
├── README.ja.md           # Japanese companion
└── data/
    ├── icd-10-cm.yaml     # ICD-10-CM (US diagnoses)
    ├── icd-10.yaml        # WHO ICD-10 (JP diagnoses)
    ├── loinc.yaml         # LOINC (labs, vitals)
    ├── jlac10.yaml        # JLAC10 (JP labs)
    ├── rxnorm.yaml        # RxNorm (US medications)
    ├── yj.yaml            # YJ codes (JP medications)
    ├── cpt.yaml           # CPT (US procedures)
    └── k-codes.yaml       # K codes (JP reimbursement procedures)
```

## Supported code systems + authoritative sources

| Key | Name | FHIR system URI | Source | Purpose |
|---|---|---|---|---|
| `icd-10-cm` | ICD-10-CM | `http://hl7.org/fhir/sid/icd-10-cm` | [CMS / NCHS](https://www.cms.gov/medicare/coding-billing/icd-10-codes) | US diagnoses + problem list |
| `icd-10` | WHO ICD-10 | `http://hl7.org/fhir/sid/icd-10` | [WHO ICD-10](https://icd.who.int/browse10/) | WHO international + JP diagnoses |
| `loinc` | LOINC | `http://loinc.org` | [Regenstrief LOINC](https://loinc.org/) | Labs, vitals, observations |
| `jlac10` | JLAC10 | `urn:oid:1.2.392.200119.4.1005` | [JCCLS](https://www.jccls.org/) | JP clinical-lab codes |
| `rxnorm` | RxNorm | `http://www.nlm.nih.gov/research/umls/rxnorm` | [NLM RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/) | US medications (generic + brand) |
| `yj` | YJ code | `urn:oid:1.2.392.100495.20.2.74` | [MHLW YJ code (drug pricing)](https://www.mhlw.go.jp/topics/2018/04/dl/yakkasanteibasis.pdf) | JP medications |
| `cpt` | CPT | `http://www.ama-assn.org/go/cpt` | [AMA CPT](https://www.ama-assn.org/practice-management/cpt) | US procedures |
| `k-codes` | K codes | `urn:oid:1.2.392.200119.4.401` | [MHLW reimbursement schedule](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000188411.html) | JP reimbursement procedures |

Additional system URIs registered in the loader (referenceable but not
backed by a YAML file):

| Key | URI | Purpose |
|---|---|---|
| `snomed-ct` | `http://snomed.info/sct` | SNOMED CT clinical findings (future) |
| `ucum` | `http://unitsofmeasure.org` | Units of measure |
| `hl7-v3-actcode` | `http://terminology.hl7.org/CodeSystem/v3-ActCode` | HL7 v3 act code |
| `hl7-v3-maritalstatus` | `http://terminology.hl7.org/CodeSystem/v3-MaritalStatus` | Marital status |

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
  # ...
```

### Schema rules

- If `metadata.uri` is missing the loader infers it from the key
  (`icd-10-cm` → CMS URI, …).
- Every entry under `codes` must include at least `en`.
- Additional languages use ISO 639-1 two-letter codes (`ja`, `de`, `fr`,
  `zh`, …).
- Code values are strings and preserve the source formatting: ICD
  uses `J18.9`, LOINC uses `1988-5`, RxNorm uses `309090`.

## API reference

### `lookup(system: str, code: str, lang: str = "en") -> str`

Returns the display text for a code in the requested language.

**Resolution order**:

1. Exact match (e.g., `J18.9`).
2. Base code (e.g., `J18.9` → `J18`).
3. Sub-code prefix (e.g., `I63` → `I63.9`).
4. The code itself (fallback).

**Language fallback**: requested lang → `en` → first available
language → the code itself.

```python
from clinosim.codes import lookup

lookup("icd-10-cm", "N10", "en")
# → "Acute tubulo-interstitial nephritis"

lookup("icd-10-cm", "N10", "ja")
# → "急性腎盂腎炎"

lookup("icd-10-cm", "I63", "en")  # base code
# → "Cerebral infarction, unspecified"  (resolved via sub-code)

lookup("icd-10-cm", "X99.99", "ja")  # does not exist
# → "X99.99"  (fallback to code itself)
```

### `get_display(system: str, code: str, country: str = "US") -> str`

Convenience helper that picks the language from country
(`US` → `en`, `JP` → `ja`).

```python
from clinosim.codes import get_display

get_display("icd-10-cm", "N10", "JP")
# → "急性腎盂腎炎"
```

### `get_system_uri(system: str) -> str`

Returns the FHIR canonical system URI from the short key.

```python
from clinosim.codes import get_system_uri

get_system_uri("icd-10-cm")
# → "http://hl7.org/fhir/sid/icd-10-cm"

get_system_uri("loinc")
# → "http://loinc.org"
```

### `CodeSystem` (dataclass)

```python
@dataclass
class CodeSystem:
    key: str                              # short key (e.g., "icd-10-cm")
    name: str                             # human-readable name
    uri: str                              # FHIR system URI
    version: str                          # edition
    codes: dict[str, dict[str, str]]      # code → {lang: display}
```

## Example: FHIR Observation output

```python
from clinosim.codes import get_system_uri, lookup

# CIF data (codes only)
lab_result = {
    "code": "1988-5",       # LOINC: CRP
    "value": 38.2,
    "unit": "mg/L",
}

# Build FHIR Observation
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
    "valueQuantity": {
        "value": lab_result["value"],
        "unit": lab_result["unit"],
    },
}
```

Same data yields the Japanese display in the JP locale:

```python
display_ja = lookup("loinc", "1988-5", "ja")
# → "C反応性蛋白"
```

## Relationship to the CIF data model

CIF (`clinosim/types/`) holds **only the code and the system key**:

```python
@dataclass
class ClinicalDiagnosis:
    admission_diagnosis_code: str = ""              # e.g., "N10"
    admission_diagnosis_system: str = "icd-10-cm"   # code-system key
    discharge_diagnosis_code: str = ""
    discharge_diagnosis_system: str = "icd-10-cm"
    # display text is not stored (looked up at output time)


@dataclass
class ChronicCondition:
    code: str = ""
    system: str = "icd-10-cm"
```

The FHIR R4 adapter
(`clinosim/modules/output/fhir_r4_adapter.py`) resolves display at
output time:

```python
display = code_lookup(
    record["clinical_diagnosis"]["discharge_diagnosis_system"],
    record["clinical_diagnosis"]["discharge_diagnosis_code"],
    lang="en" if country == "US" else "ja",
)
```

## Extension

### Add a new code

Edit the matching `data/<system>.yaml`:

```yaml
codes:
  J18.9:
    en: "Pneumonia, unspecified organism"
    ja: "肺炎，詳細不明"
  # existing entries…
  J45.901:                              # new entry
    en: "Unspecified asthma with (acute) exacerbation"
    ja: "喘息急性増悪"
```

Sort order is free (the loader looks up by dict key). Alphabetical
order is recommended for readability.

### Add a new code system

1. Create `data/<new-system>.yaml` (schema above).
2. Optionally register a short key → URI mapping in
   `loader.py::_BUILTIN_URIS`.
3. Simply dropping the file is enough — the loader autodetects it
   (`@lru_cache(maxsize=32)`).

### Add a new language

Add a new language key to each `codes` entry:

```yaml
codes:
  N10:
    en: "Acute tubulo-interstitial nephritis"
    ja: "急性腎盂腎炎"
    de: "Akute tubulointerstitielle Nephritis"   # new
```

Call site:

```python
lookup("icd-10-cm", "N10", "de")
# → "Akute tubulointerstitielle Nephritis"
```

Codes that lack the requested language fall back to English:

```python
lookup("icd-10-cm", "Z99.2", "de")
# → "Dependence on renal dialysis"  (no de → en fallback)
```

## Coverage

| Code system | Codes | Languages | Coverage focus |
|---|---|---|---|
| icd-10-cm | 234 | en, ja | Every disease clinosim generates + common Z-codes / ED symptoms |
| icd-10 | 133 | en, ja | WHO ICD-10 base codes (JP-compatible) |
| loinc | 65 | en, ja | Vitals + core hematology/chemistry + coagulation + cardiac markers |
| jlac10 | 30 | en, ja | JP clinical-lab standard codes (JCCLS common reference intervals) |
| rxnorm | 68 | en, ja | Antibiotics / anticoagulants / cardiovascular / emergency drugs |
| yj | 39 | en, ja | JP medications (major prescriptions) |
| cpt | 31 | en, ja | Major surgical procedures + bedside procedures + imaging |
| k-codes | 25 | en, ja | JP reimbursement procedures (K codes) |
| snomed-ct | 31 | en, ja | Procedure-structured fields (category, performer role, body site, outcome, complication) |

Total: **656 codes** (at time of writing).

## Boundary against the `locale` module

| | `clinosim.codes` | `clinosim.locale` |
|---|---|---|
| **Responsibility** | International code systems + multi-language display | Culture- and country-dependent data |
| **Locale-scoped?** | No (all languages in one file) | Yes (`jp/`, `us/`, …) |
| **Typical data** | ICD/LOINC/RxNorm, … | Names, addresses, phone formats, reference intervals |
| **Held by CIF** | Code value + system key | Concrete fields (Address, PersonName, …) |

`locale/<country>/code_mapping_*.yaml` still exists — it maps
simulator-internal test names (e.g., `"WBC"`) to standard codes
(`"6690-2"`). Display-text resolution is delegated to this module.

## Licensing and provenance

Each code system follows its own upstream license:

- **ICD-10-CM**: public domain (CMS)
- **WHO ICD-10**: WHO terms of use
- **LOINC**: LOINC License (free commercial use, redistribution
  permitted)
- **RxNorm**: NLM Open Use (public domain)
- **JLAC10**: published by JCCLS
- **CPT**: AMA copyright — clinosim ships only a minimal educational /
  research subset
- **YJ code**: MHLW open data
- **K codes**: MHLW reimbursement schedule

`codes/data/` extracts only the subset needed to drive clinosim's
synthetic-data generation. For commercial EHR integration, pull the
full, current release from the upstream authority.

**The subset must exhaustively cover "codes that can appear in the
output."** For diagnosis codes,
`tests/unit/test_diagnosis_code_coverage.py` guards the invariant that
"every `icd_codes` entry across all diseases/encounters and every
target of the diagnosis map resolves exactly against the code data".
When adding a new outpatient / disease scenario, adding the referenced
ICD codes here is mandatory (see the "Diagnosis code coverage" note in
CLAUDE.md); otherwise the FHIR Condition display falls back to an
approximate prefix match.

## Update policy

- ICD-10-CM: CMS ships a new edition every October 1 → clinosim tracks.
- LOINC: released every six months (June / December) → we absorb major
  changes.
- RxNorm: weekly updates every Monday → we track a stable release once
  a year.
- WHO ICD-10: seldom updated (current release is 2019).
- Internal short keys are stable. Any YAML structural change is a major
  version bump.
