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
| `cpt` | CPT | US procedures | [AMA](https://www.ama-assn.org/practice-management/cpt) |
| `k-codes` | K codes | JP reimbursement procedures | MHLW Medical Fee Schedule |

Clinical document types use the following LOINC codes:

| Document | LOINC | Notes |
|---|---|---|
| History and physical note | `34117-2` | Generated at admission |
| Progress note | `11506-3` | Reserved for future Tier C scope |
| Discharge summary note | `18842-5` | Generated at discharge |
| Death note | `69730-0` | Generated when `deceased=true` |
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
