# Shared Helpers Catalog — the one place to look up "which helper do I use for X?"

**Audience:** everyone writing or reviewing clinosim code.
**Positioning:** [`implementation-rules.md`](implementation-rules.md) states the rules ("reuse the canonical helper, never re-implement it"); this catalog lists the helpers those rules refer to. The binding spec named in each section defines the behaviour; this page only tells you where the entry point is.

How to use it:

1. Before writing a small utility (a hash draw, a country check, a dict-or-attribute read, a FHIR coding, a date format), search this page for the concern.
2. If a helper exists, import it from the path shown. Copying its body into your module is a review blocker.
3. If no helper exists and a second module needs the same logic, put it in the owner module (or `clinosim/modules/_shared.py` for cross-module utilities), import it from both places, and add a row here in the same PR.

Paths are relative to the repository root. Symbols marked *(module-internal)* start with `_` but are imported across files inside their package; keep them inside that package.

---

## 1. Determinism and random draws

Governing spec: [`determinism-and-rng-spec.md`](determinism-and-rng-spec.md).

| Helper | Use it for |
|---|---|
| `clinosim/determinism.py` `default_rng(seed)` | The only way to create a random generator (bit-reproducible across platforms). `numpy.random.default_rng` and `random` are forbidden. |
| `clinosim/determinism.py` `normal` / `beta` / `exponential` | Bit-reproducible continuous variates from a generator. |
| `clinosim/determinism.py` `sha_quantile(salt, byte_offset, byte_count)` | A stream-free uniform [0, 1) value from a salt — use it when adding a draw must not shift any other draw (RNG-neutral change). |
| `clinosim/determinism.py` `sha_bernoulli(salt, p)` / `sha_normal(salt, mean, sd)` / `sha_weighted_choice(salt, choices, weights)` | Stream-free yes/no, normal and weighted-choice draws built on `sha_quantile`. |
| `clinosim/determinism.py` `sha_index(salt, n, byte_count)` | A stream-free index in `[0, n)` — pick one entry of a fixed list (a phrase variant, a catalog row). |
| `clinosim/seeding.py` `derive_sub_seed(master_seed, module_offset, key)` + `ENRICHER_SEED_OFFSETS` | Per-module, per-key sub-seeds for enrichers. Register a new offset; never hash a seed inline. |
| `clinosim/seeding.py` `derive_phase_rng(master_seed, phase_salt, key)` | Independent generator per simulation phase and key. |
| `clinosim/seeding.py` `text_seed`, `panel_specimen_seed`, `individual_lab_seed`, `chronic_medication_seed`, `discharge_prescription_seed`, `ambulatory_visit_length_seed`, `issue939_procedure_seed`, `chronic_augment_sex_seed`, `chronic_isolated_seed`, `longitudinal_event_seed`, `perinatal_delivery_seed`, `chemotherapy_regimen_seed`, `daily_output_seed`, `radiation_therapy_seed`, `avpu_day_seed`, `newborn_seed`, `pregnancy_outcome_seed`, `newborn_conditions_seed`, `enumeration_case_seed`, `identity_person_seed` | Named per-entity seeds. Add a new named function here rather than deriving a seed at the call site. |
| `clinosim/seeding.py` `rendezvous_pick(key, ids, hashes)` / `id_hashes(ids)` | Stable, uniform pick of one member of a pool (staff, rooms) that does not move when the pool grows. |
| `clinosim/seeding.py` `morse_fall_history_unit(patient_id, encounter_id)` | The stable per-stay unit used by the Morse fall-history item. |
| `clinosim/modules/_shared.py` `normalize_probabilities(p, fallback="raise")` | Every YAML-sourced probability vector before `rng.choice(p=...)`. |
| `clinosim/modules/_shared.py` `random_day_of_month(rng, year, month)` | A uniform calendar day inside a month (leap-year aware). |
| `clinosim/modules/_shared.py` `select_with_exclusive_classes(drug_specs, exclusive_classes, rng)` | Drug selection where at most one drug of each exclusive class may be chosen. |
| `clinosim/modules/order/placed_order_mar.py` `stable_nurse(roster, key, ward=, department=)` | The giving nurse on an administration row, picked by stable hash (no draw). |

## 2. Reference data, configuration and age bands

Governing spec: [`configuration-and-reference-data-spec.md`](configuration-and-reference-data-spec.md).

| Helper | Use it for |
|---|---|
| `clinosim/datafiles.py` `load_data_yaml(path)` | The one YAML reader: returns the content without the `metadata` header. |
| `clinosim/datafiles.py` `load_validated_yaml(path, model)` | Read a YAML and validate it against a Pydantic model — the default for module reference data. |
| `clinosim/datafiles.py` `data_metadata(path)` | The `metadata` header (source, version, licence) of a data YAML. |
| `clinosim/modules/document/reference_data_loaders.py` `load_document_data_yaml(filename)` | Cached read of a `document/reference_data/` YAML by file name (registries whose reader owns their shape). |
| `clinosim/reference_data.py` `load_reference_yaml(path)` | Cached reader that returns a copy, for callers that reshape the data. |
| `clinosim/age_bands.py` `parse_age_band` / `parse_closed_age_band` / `age_band_covers` | Parse and test age-band keys such as `"18-49"` and `"85+"`. |
| `clinosim/age_bands.py` `find_age_band(keys, age)` / `lookup_age_band(table, age, default)` | Resolve an age to its band key or value. Hard-coded `if age < 18` cut-offs are forbidden. |
| `clinosim/age_bands.py` `find_age_band_or_last(keys, age)` | The band covering `age`, else the last band (tables whose last band is the catch-all). |
| `clinosim/codes/valuesets.py` `has_condition(person, group)` / `concept_group(name)` / `group_names()` / `patient_condition_names()` | Named condition groups (value sets) instead of hand-written ICD prefix lists. |
| `clinosim/codes/valuesets.py` `has_icd_prefix(items, prefixes)` / `code_by_chronic_prefix(mapping, person)` / `iter_chronic_codes(items)` | Matching chronic-condition items of any shape by ICD prefix. |
| `clinosim/codes/valuesets.py` `normalize_icd(code)` / `icd_base(code)` | Canonical ICD formatting and the category part before the dot. |

## 3. Country and language decisions

Governing spec: [`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md) §5.

| Helper | Use it for |
|---|---|
| `clinosim/countries.py` `is_jp(country)` / `is_us(country)` | Country-specific rules (insurance, profiles, code systems). Never compare country strings by hand. Not for choosing a display language. |
| `clinosim/countries.py` `lang_for(country)` / `normalize_lang(lang)` | The output language of a country, and the one normalisation of a language argument. |
| `clinosim/countries.py` `country_code(country)` | `"JP"` / `"US"` from any spelling (`"jp"`, the legacy locale key `"japan"`, ...) for helpers that take the upper-case code. `is_jp` accepts the same spellings. |
| `clinosim/countries.py` `country_slot(country, scheme=...)` | The section key of a per-country YAML block. |
| `clinosim/countries.py` `lang_name(lang, in_lang=)` / `output_language_instruction(lang)` / `has_authored_narrative(lang)` | Language names, the LLM "write in this language" instruction, and whether a language has authored narrative content. |
| `clinosim/modules/_shared.py` `uses_jp_clins_profile(lang)` | Whether FHIR resources are emitted under a JP-CLINS profile family. |

## 4. Codes and display text

Governing spec: [`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md).

| Helper | Use it for |
|---|---|
| `clinosim/codes` `display(system, code, lang)` | Display text of a code; returns `None` when unregistered, so write `display(...) or <explicit fallback>`. `lookup(...)` is legacy and forbidden in new code. |
| `clinosim/codes` `code_exists(system, code)` / `code_system(key)` / `system_keys()` / `data_table(name)` | Registry checks and raw code-table access. |
| `clinosim/codes` `system_key_for(kind, country)` / `get_system_uri(key)` / `system_key_for_uri(uri)` | Which code system a country uses for a data kind, and its canonical URI. Hard-coded URIs are forbidden. |
| `clinosim/codes` `is_english_only_system(key_or_uri)` | Whether a system publishes English-only displays (LOINC, SNOMED): such codings keep the English display and carry the local label in `.text`. |
| `clinosim/codes` `jlac10_display` / `jp_clins_lab_system` | JLAC10 display and the JP-CLINS lab code system. |
| `clinosim/codes/drugs.py` `identify_drug(text)` / `find_drug(ref)` / `get_drug(id)` / `resolve_drug(id)` / `drug_key(ref)` | Identify a catalog drug from an id, name, alias or order string. |
| `clinosim/codes/drugs.py` `same_drug(a, b)` / `has_drug(meds, drug)` / `medication_matches(med, drugs, classes)` / `drug_classes(ref)` | Compare drugs and test medication lists by drug or class — never by string equality. |
| `clinosim/codes/drugs.py` `drug_display(ref, lang)` / `protocol_drug_name(spec)` | Drug names for output and for protocol entries. |
| `clinosim/codes/drugs.py` `drug_system_key(code, country)` / `drug_system_uri(code, country)` | The drug code system (RxNorm for the US, YJ for Japan) of an emitted code. |
| `clinosim/codes/drugs.py` `jp_drug_code(ref, route)` / `jp_drug_code_for_name(name, route)` / `rxnorm_scd_code(drug, route, dose, unit)` / `rxnorm_scd_codes(id)` | Product-level codes (YJ, RxNorm SCD). |
| `clinosim/codes/drugs.py` `route_class(route)` | The route class (oral, injection, inhalation, …) of a route string. |
| `clinosim/codes/bcp47.py` `bcp47_display(tag, profile=)` | Display of a BCP 47 language tag. |
| `clinosim/codes/hl7_encounter.py` `AdmitSource` / `DischargeDisposition` / `ActPriority` | HL7 encounter enumerations; use the enum members instead of string literals. |

## 5. Localization of labels and free text

Governing spec: [`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md) §3–§5.

| Helper | Use it for |
|---|---|
| `clinosim/locale/localized.py` `localized(entry, lang, fallback=)` / `localized_field(record, base, lang)` / `label(catalog, section, key, lang)` | A language map entry in `lang`, then English, then an explicit fallback. |
| `clinosim/locale/localized.py` `language_slot(entry, lang)` | Exactly one language of a map, with no fallback (for checks and dual-slot output). |
| `clinosim/locale/table.py` `localized_table(name)` / `LocalizedTable` | Named display and translation tables keyed by internal slug. |
| `clinosim/locale/i18n.py` `t(key, lang, **params)` | A phrase by key in the target language, with parameters interpolated. |
| `clinosim/locale/text.py` `resolve_text(value, language, country)` | A YAML text field (plain string or language map) in the right language. |
| `clinosim/locale/loaders/narrative.py` `vocab_display(...)` / `load_narrative_display_dict(...)` | Narrative vocabulary displays. |
| `clinosim/locale/loaders/medical_display.py` `load_med_terms_ja()` | Japanese medical term dictionary. |
| `clinosim/locale/free_text.py` `localize_drug_name` / `localize_procedure_name` / `localize_allergen_name` / `localize_free_text` | Translating names and order strings that are not coded. |
| `clinosim/modules/output/fhir_r4/lib/localization.py` `localize_fixed_label(en_label, country)` | Fixed FHIR labels in the country's language. |

## 6. Reading and writing CIF objects

Governing spec: [`implementation-rules.md`](implementation-rules.md) §4.

| Helper | Use it for |
|---|---|
| `clinosim/modules/_shared.py` `get_attr_or_key(obj, name, default)` | Reading a field from a dict or a dataclass. Do not add new `isinstance(x, dict)` branches or local `_get` helpers. |
| `clinosim/modules/_shared.py` `set_attr_or_key(obj, name, value)` / `get_or_create_container(obj, name, factory)` | Writing a field, or getting-or-creating a nested list/dict, on either shape. |
| `clinosim/timeutil.py` `parse_iso_datetime(value, lenient=False)` | Reading a CIF timestamp that may be a `datetime`, a `date` or an ISO 8601 string (trailing `Z`, offsets, date-only); returns `None` when absent or unparseable and never changes the time zone. `lenient=True` also strips whitespace and falls back to the leading date. Do not write a local `_parse_dt`. |
| `clinosim/modules/_shared.py` `strip_protocol_prefix(name)` | Removing the protocol/category prefix from a drug order string. |
| `clinosim/modules/_shared.py` `sanitize_id_token(token, max_len)` | Turning free text into an id-safe token. |
| `clinosim/modules/_shared.py` `practitioner_name(staff_id, roster_map)` | A staff member's roster name. |

## 7. Clinical domain helpers

Governing specs: [`medication-lifecycle-spec.md`](medication-lifecycle-spec.md), [`lab-orders-and-results-spec.md`](lab-orders-and-results-spec.md), [`encounter-lifecycle-and-export-spec.md`](encounter-lifecycle-and-export-spec.md).

| Helper | Use it for |
|---|---|
| `clinosim/modules/disease/severity.py` `sample_severity` / `sample_severity_category` / `category_from_score` | Severity sampling and the score ↔ category boundaries (`SEVERITY_SCORE_RANGES`). |
| `clinosim/modules/physiology/engine.py` `scenario_flags_from_protocol` + `medication_flags_from_context` | The flags passed as `**flags` into lab derivation. |
| `clinosim/modules/observation/engine.py` `canonical_lab_name(name)` / `get_lab_unit(name)` | The canonical lab name and its standard unit. |
| `clinosim/modules/observation/engine.py` `medications_in_effect(home_medications, medication_orders, admission_date, current_day)` | The medications acting on lab values on a given day of a stay. |
| `clinosim/modules/order/panel_grouping.py` `classify_lab_specs(...)` | Grouping lab orders into panels and individual tests. |
| `clinosim/modules/order/engine.py` `place_imaging_orders(...)` | Imaging orders. |
| `clinosim/modules/order/absolute_dose.py` `is_continuous_infusion(text)` | Whether a dose or order text describes a continuous infusion. |
| `clinosim/modules/drug_safety/engine.py` `allergy_entries(allergies)` | The active allergen codes of a patient's allergy records (drops inactive, refuted and "no known allergy" entries) — the input of `check_candidate_against_allergies`. |
| `clinosim/modules/drug_safety/engine.py` `check_candidate_against_allergies(candidate, allergen_codes)` | The non-allowed verdicts of a candidate drug against the patient's allergen codes. Every prescribing path calls this (or `allergy_skip_verdict`) instead of re-implementing an allergy check. |
| `clinosim/modules/drug_safety/engine.py` `allergy_skip_verdict(candidate, allergies)` | The worst allergy verdict that drops a candidate drug for a patient's allergy records, or None when it may be given. |
| `clinosim/modules/drug_safety/engine.py` `conflict_display(verdict)` | The (English, Japanese) text of what a verdict conflicts with, for a `SafetySkipEntry`: the recorded allergy or the active drug. |
| `clinosim/simulator/medication_pipeline.py` `allergy_blocked(patient, drug_name, ...)` | A prescription with no alternative to offer (a renewal, a fixed bundle item): True, with the skip logged, when the patient's allergies rule the drug out. |
| `clinosim/simulator/medication_pipeline.py` `log_allergy_skip(patient, drug_name, verdict, ...)` | Recording a prescription item dropped for an allergy on `patient.safety_skip_log`, with the substitute drug when there is one. |
| `clinosim/modules/order/pediatric_dose.py` `pediatric_order_name(name, age_months, weight_kg)` | Re-dosing an adult fixed-strength order for a child from the weight; None when the child is below the drug's minimum age. |
| `clinosim/simulator/encounter_setup.py` `extend_visit_to_procedures(encounter, procedures)` | Extending a visit so it lasts at least until its last procedure ends. |
| `clinosim/simulator/encounter_setup.py` `fit_procedures_in_stay(procedures, start, end)` | Holding each procedure inside the stay window (`end` None: still in progress). |
| `clinosim/modules/observation/pediatric_ranges.py` `age_in_completed_months(birth, when)` | A child's age in completed months (None when a date is unknown). |
| `clinosim/modules/observation/pediatric_ranges.py` `pediatric_vital_range(vital, age_months)` / `pediatric_vital_range_text` / `age_independent_vital_range_text` | The pediatric vital-sign range for the age and its `referenceRange.text`; None means the adult range applies. |
| `clinosim/modules/observation/pediatric_ranges.py` `pediatric_lab_range(lab_name, age_years, sex)` / `pediatric_lab_center` / `pediatric_lab_band` / `pediatric_lab_range_text` | The pediatric lab reference interval (and its midpoint, band and text) for a child; None means the adult interval applies. |
| `clinosim/modules/staff/engine.py` `scoped_nurses(roster, ward=, department=)` | The nurses of a ward, else of the department, else every nurse. |
| `clinosim/modules/diagnosis/nonspecific_codes.py` `is_visit_reason_zcode(code)` | Whether a Z code is a visit reason rather than a diagnosis. |
| `clinosim/modules/document/engine.py` `_compute_los_days` *(module-internal, also used by the narrative pass)* | Length of stay, including the in-progress proxy. |

## 8. FHIR building (Layer 4)

Governing guide: [`fhir-data-generation-logic.md`](fhir-data-generation-logic.md) (subordinate to the code-mapping spec on display rules).

| Helper | Use it for |
|---|---|
| `clinosim/modules/output/fhir_r4/lib/context.py` `BundleContext` | Shared inputs (record, country, roster, hospital config) for every builder. |
| `clinosim/modules/output/fhir_r4/lib/common.py` `system_coding(system_key, code, lang)` / `dual_slot_concept(system_key, code, lang, text=)` | Every Coding and CodeableConcept: the dual-slot rule for English-only systems is built in. |
| `clinosim/modules/output/fhir_r4/lib/common.py` `display_entry(text)` | `{"display": text}` or `{}` — a Coding never carries an empty display. |
| `clinosim/modules/output/fhir_r4/lib/common.py` `build_diagnosis_codeable_concept`, `severity_coding`, `survey_category`, `make_participant`, `build_reference_range`, `build_address`, `build_telecom`, `build_presented_form`, `map_encounter_status`, `entry` | The standard pieces of Condition, Observation, Encounter, Patient and DiagnosticReport resources. |
| `clinosim/modules/output/fhir_r4/lib/dosage.py` `build_dosage_instruction`, `build_route_concept`, `canonicalize_route`, `resolve_timing_repeat`, `frequency_in_text`, `is_rate_unit`, `augment_iv_dosage_with_rate`, `map_mar_status` | Dosage, route, timing and administration status. |
| `clinosim/modules/output/fhir_r4/lib/reference_data.py` `iter_route_values(data)` / `validate_yaml_route_value(...)` | Walk and validate every route value of a protocol YAML. |
| `clinosim/modules/output/fhir_r4/lib/fhir_time.py` `to_fhir_datetime` / `to_fhir_instant` / `to_fhir_date` / `to_fhir_deceased_datetime` / `tz_suffix_for_country` / `derive_meta_last_updated` | Every FHIR date, dateTime and instant, with the country's time zone. |
| `clinosim/modules/output/fhir_r4/lib/ids.py` `derive_opaque_id` / `structural_key_system` / `wrap_as_identifier` | Resource ids and the identifiers that round-trip structural keys. |
| `clinosim/modules/output/fhir_r4/lib/ecs_extensions.py` `attach_ecs_institutional_extensions` / `build_ecs_institution_extension` / `build_ecs_department_extension` | JP eCS institution and department extensions. |
| `clinosim/modules/output/fhir_r4/demographics/patient.py` `patient_ref` / `clinosim/modules/output/fhir_r4/encounters/encounter.py` `encounter_ref` / `clinosim/modules/output/fhir_r4/conditions/primary_ref.py` `primary_condition_ref` | References to the patient, encounter and primary condition. Never build `"Patient/" + id` by hand. |
| `clinosim/modules/output/fhir_r4/labs/coding_package.py` `load_lab_coding_package(...)` | Lab coding (LOINC / JLAC10) per country. |

## 9. Narrative wording (Stage 2 templates)

Governing spec: [`narrative-and-document-generation-spec.md`](narrative-and-document-generation-spec.md).

| Helper | Use it for |
|---|---|
| `clinosim/modules/document/narrative/_vitals_line.py` `format_vitals_line` | The one vital-signs line used by every document. |
| `clinosim/modules/document/narrative/_narrative_interpretation_thresholds.py` `bmi_band` / `bp_band` | BMI and blood-pressure wording bands. |
| `clinosim/modules/document/narrative/_safety_skips.py` `safety_skip_line` | The sentence for a held or skipped dose (safety event). |
| `clinosim/modules/document/narrative/_template_helpers.py` `allergen_display` | Allergen names in documents. |
| `clinosim/modules/document/narrative/_hedging.py` `hedged_phrase` | Hedged clinical phrasing chosen deterministically. |
| `clinosim/modules/document/narrative/_chronic_soap.py` `resolve_chronic_soap` | Chronic-condition SOAP text for outpatient notes. |
| `clinosim/modules/document/narrative/_replacement_localization.py` `localize_token` | Localizing a token inside a replacement-strategy section. |

Japanese counterpart: [`shared-helpers-catalog.ja.md`](shared-helpers-catalog.ja.md).
