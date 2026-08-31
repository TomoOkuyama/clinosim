<!-- Extracted from `README.md` (Issue #568 PR A2). Update the pointer in README when this file's heading changes. -->

# Extension Guide

### Add a new disease

1. Create `clinosim/modules/disease/reference_data/<disease_id>.yaml` (use existing disease as template).
2. Add to incidence list in `clinosim/locale/<country>/demographics.yaml`.
3. **Register every `icd_codes` value (primary AND variants) in the code data** — US billable leaves in `clinosim/codes/data/icd-10-cm.yaml`, JP WHO codes in `clinosim/codes/data/icd-10.yaml`, with a mapping entry in `clinosim/codes/data/code_mapping_diagnosis/<country>.yaml` when the disease code needs folding (e.g. CM-granularity → WHO parent). Skipping this makes the FHIR Condition display fall back to approximate prefix-matched text. See `AGENTS.md` → "Diagnosis code coverage".
4. Test: `clinosim test-disease <disease_id>` and `pytest tests/unit/test_diagnosis_code_coverage.py`.

Details: `clinosim/modules/disease/README.md`

### Add a new encounter type (ED/outpatient)

1. Create `clinosim/modules/encounter/reference_data/<condition_id>.yaml`.
2. Include `icd10_code` and `icd10_display`.
3. Register `icd10_code` per "Add a new disease" step 3.
4. Test: `clinosim test-encounter <condition_id>` and `pytest tests/unit/test_diagnosis_code_coverage.py`.

### Add a new country

1. Create `clinosim/locale/<country_code>/` folder
2. Add `names.yaml`, `addresses.yaml`, `demographics.yaml`, `reference_range_lab.yaml`, `formatting.yaml`
3. Add entry in `clinosim/locale/shared/naming_rules.yaml`
4. (Optional) Add country-specific code system to `codes/data/`

### Add a new language

Add a new language key to each entry in `clinosim/codes/data/*.yaml`:

```yaml
N10:
  en: "Acute tubulo-interstitial nephritis"
  ja: "急性腎盂腎炎"
  de: "Akute tubulointerstitielle Nephritis"   # New language
```

Details: `clinosim/codes/README.md`

---
