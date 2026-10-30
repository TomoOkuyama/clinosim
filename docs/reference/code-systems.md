<!-- Extracted from `README.md` (Issue #568 PR A2). Update the pointer in README when this file's heading changes. -->

# Code Systems & Authoritative Sources

`clinosim/codes/` centralizes international standard code systems, all with English display (Japanese is optional).

| Key | Name | Use | Authoritative Source |
|---|---|---|---|
| `icd-10-cm` | ICD-10-CM | US diagnoses | [CMS](https://www.cms.gov/medicare/coding-billing/icd-10-codes) |
| `icd-10` | WHO ICD-10 | JP diagnoses | [WHO](https://icd.who.int/browse10/) |
| `loinc` | LOINC | Lab tests, vitals, clinical document types | [Regenstrief](https://loinc.org/) |
| `snomed-ct` | SNOMED CT (subset) | Procedure category, performer role, body site, outcome, complication | [SNOMED International](https://www.snomed.org/) |
| `jlac10` | JLAC10 | JP lab codes | [JCCLS](https://www.jccls.org/) |
| `rxnorm` | RxNorm | US drugs | [NLM](https://www.nlm.nih.gov/research/umls/rxnorm/) |
| `yj` | YJ codes | JP drugs | MHLW Drug Price Standards |
| `hot7` | MEDIS HOT7 | JP drugs (HOT-format codes; the JP medication emitter picks the HOT7 / HOT9 / HOT13 / YJ URI per code format) | [MEDIS](https://www.medis.or.jp/) |
| `medis-disease-keyno` | MEDIS 病名管理番号 | JP Condition `medisRecordNo` slice (JP-CLINS) | [MEDIS](https://www.medis.or.jp/) |
| `cvx` | CVX | Immunizations | [CDC IIS](https://www2.cdc.gov/vaccines/iis/iisstandards/vaccines.asp?rpt=cvx) |
| `cpt` | CPT | US procedures | [AMA](https://www.ama-assn.org/practice-management/cpt) |
| `k-codes` | K codes | JP reimbursement procedures | MHLW Medical Fee Schedule |

Clinical document types use the following LOINC codes (inpatient
physician documents shown; the full per-country list, including nursing,
outpatient / ED and JP-only documents, is in
[`../clinical_documents.md`](../clinical_documents.md#document-scope)):

| Document | LOINC | Notes |
|---|---|---|
| History and physical note | `34117-2` | Generated at admission |
| Progress note | `11506-3` | Generated daily during an inpatient stay |
| Discharge summary note | `18842-5` | Generated at discharge (a death discharge summary with the same code replaces it on deceased encounters) |
| Death certificate | `64297-5` | Generated when the encounter ends in death |
| Surgical operation note | `11504-8` | Generated per surgical procedure |
| Procedure note | `28570-0` | Generated per invasive bedside procedure |

### Using Code Systems (FHIR Observation example)

```python
from clinosim.codes import lookup, get_system_uri

# CIF data is code-only
crp_code = "1988-5"  # LOINC

# Build FHIR Observation
obs = {
    "resourceType": "Observation",
    "code": {
        "coding": [{
            "system": get_system_uri("loinc"),
            "code": crp_code,
            "display": lookup("loinc", crp_code, "en"),
        }],
    },
    "valueQuantity": {"value": 38.2, "unit": "mg/L"},
}
```

See `clinosim/codes/README.md` for details.

---
