<!-- Extracted from `README.md` (Issue #568 PR A2). Update the pointer in README when this file's heading changes. -->

# Extension Guide

### Add a new disease

1. Create `clinosim/modules/disease/reference_data/<disease_id>.yaml` (use existing disease as template).
2. Add to incidence list in `clinosim/locale/<country>/demographics.yaml`.
3. **Register every `icd_codes` value (primary AND variants) in the code data** — US billable leaves in `clinosim/codes/data/icd-10-cm.yaml`, JP WHO codes in `clinosim/codes/data/icd-10.yaml`, with a mapping entry in `clinosim/locale/<country>/code_mapping_diagnosis.yaml` when the disease code needs folding (e.g. CM-granularity → WHO parent). Skipping this makes the FHIR Condition display fall back to approximate prefix-matched text. See `AGENTS.md` → "Diagnosis code coverage".
4. If the disease YAML has both `target_los.japan` and `target_los.us` for a severity, add the disease's row to `clinosim/modules/clinical_course/reference_data/course_time_scale.yaml`: the bounded ratio of the Japan mean to the US mean per severity. `tests/unit/test_course_time_scale_3931.py` fails when the table differs from that ratio (a disease with no row runs at the authored speed, scale 1.0).
5. Check the Python disease-id sets in [`AGENTS.md`](../../AGENTS.md) → "Disease protocol YAML files": a disease that should be an emergency admission, get q1-2h vitals, continuous SpO2 or imaging needs an edit to a core file, so "data only" is true only for the other diseases.
6. Test: `clinosim test-disease <disease_id>` and `pytest tests/unit/test_diagnosis_code_coverage.py tests/unit/test_course_time_scale_3931.py`.

Details: `clinosim/modules/disease/README.md`

### Add a new encounter type (ED/outpatient)

1. Create `clinosim/modules/encounter/reference_data/<condition_id>.yaml`.
2. Include `icd10_code` and `icd10_display` (for an `emergency` condition, set `min_age` / `max_age` to bound who can present — the ED draw gates on age in the visit year).
3. Register `icd10_code` per "Add a new disease" step 3.
4. Test: `clinosim test-encounter <condition_id>` and `pytest tests/unit/test_diagnosis_code_coverage.py`.

### Add a new country

1. Create `clinosim/locale/<country_code>/` with `country.yaml` — the country profile; a country exists when this file exists (there is no country-to-directory map)
2. Add `names.yaml`, `addresses.yaml`, `demographics.yaml`, `reference_range_lab.yaml`, `formatting.yaml`, `care_practice.yaml`, `population_genetics.yaml` and the `code_mapping_*.yaml` files
3. Create the healthcare-system config `clinosim/config/<stem>.yaml` named by `healthcare_system` in `country.yaml`
4. Add the entries that live outside the country folder: `clinosim/locale/shared/naming_rules.yaml`, the `pediatric_growth` block of `clinosim/modules/population/reference_data/anthropometric_reference.yaml`, and the `codes` of the `diagnosis_variants` in `clinosim/modules/encounter/reference_data/minor_burn.yaml` and `minor_laceration.yaml` (each fails loudly when missing)
5. (Optional) A named implementation for an algorithm no country has (registered in a module listed in `IMPLEMENTATION_MODULES`, `clinosim/country_profile.py`) or a FHIR profile clinosim does not know (`FHIR_PROFILES` plus a builder gate): these edit core files
6. (Optional) Add a country-specific code system to `codes/data/`

Full checklist: [`../add-your-country.md`](../add-your-country.md).

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
