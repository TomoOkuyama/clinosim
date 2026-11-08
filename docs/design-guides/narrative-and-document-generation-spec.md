# Narrative and document generation — specification

Status: **normative**. Every change that plans a clinical document, adds a section, words a clinical fact in a narrative, or prepares facts for the LLM follows this document. A change that cannot follow it updates this document in the same PR, with the reason.

Japanese counterpart: [`narrative-and-document-generation-spec.ja.md`](narrative-and-document-generation-spec.ja.md).

Related specs and contracts:
- Document type codes (LOINC per document type) and every display name: [`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md) §4.1.
- Two-pass CIF (structural stubs, then narratives; AD-65): [`clinosim/modules/output/SPEC.md`](../../clinosim/modules/output/SPEC.md).
- Determinism of the narrative pass (walk order, timestamps): [`determinism-and-rng-spec.md`](determinism-and-rng-spec.md) §7.

## 1. Principles

1. **One wording per fact.** A clinical fact read into prose is worded by one function, and the template path and the LLM path both call it. The two paths differ in what they do with the words: the template places them, the LLM receives them as facts. They never word the fact differently.
2. **One decision per document.** Which documents an encounter gets is decided by one table of planners keyed by the document type's generation frequency. Each Composition section has one registered builder.
3. **The display and its interpretation agree.** A value is classified as it is shown (rounded first), so a printed number never contradicts the band or interpretation printed beside it.
4. **Every rule has a guard.** Each rule names the test that enforces it; a rule without one is listed in §5.

## 2. Planning documents and sections

| Rule | Canonical code | Guard |
|---|---|---|
| Which documents an encounter gets is decided by `_PLANNERS[spec.generation_frequency]`, one planner per frequency (admission once, daily, three shifts, discharge once, per surgical encounter, ...). A new frequency is a new planner in the table; no document type is planned outside it. | `clinosim/modules/document/engine.py::_PLANNERS` | `tests/unit/modules/document/test_document_planners_2532.py` |
| Each Composition section is built by exactly one function registered with `@section(name)`; registering a name twice fails at import. A section that one document type writes differently registers that type's builder with `@section(name, document_type=...)` (one per document type and section, e.g. the ED note's assessment), and the renderer prefers it over the shared builder. The composition renderer looks sections up in the registry. | `clinosim/modules/document/narrative/renderers/section_builders/_registry.py` (`section`, `section_builder`, `section_builders`, `document_section_builders`) | `tests/unit/modules/document/narrative/test_section_registry_2531.py`, `test_ed_note_protocol_2871.py::test_document_type_builders_name_a_section_of_that_document` |
| A document's context holds only the data recorded at its own encounter. A record's vitals, lab results, orders, administrations, procedures and closing prescription belong to the record's encounter (`encounters[0]`); for any other encounter of the record (the vaccination visit the immunization enricher appends) they are kept only when they carry that encounter's id or a timestamp inside its period, so its note never prints another visit's vitals or prescription. | `clinosim/modules/document/narrative/passes.py::scope_record_to_encounter` | `tests/unit/modules/document/narrative/test_vaccination_visit_own_data_2869.py` |
| A stay that ended in death (discharge disposition `exp`) is recognised by one test, used by the planner (death summary and death certificate instead of the discharge summary) and by every section that words the end of a stay. Such a stay keeps its nursing discharge summary, which records the time of death, the family's notification and post-mortem care in place of discharge criteria, patient teaching and discharge readiness; the last two days' progress notes take their stable-day phrase from the `terminal` pool, not from the discharge-preparation pools. | `clinosim/modules/document/narrative/_narrative_utils.py::encounter_died` | `tests/unit/modules/document/narrative/test_death_stay_documents_2875.py` |
| The LLM is reached only through `LLMService.complete_prompt` (AD-11). | `clinosim/modules/llm_service/` | `implementation-rules.md` §2 (review) |

## 3. Wording clinical facts

| Rule | Canonical code | Guard |
|---|---|---|
| A drug-safety event (avoided, held, substituted, switched, de-escalated) is worded by one function for both paths: the template's plan line (`safety_skips.*` phrases) and the LLM prompt bullet (`safety_skips_prompt.*` phrases). | `clinosim/modules/document/narrative/_safety_skips.py::safety_skip_line` | `tests/unit/modules/document/narrative/test_safety_skip_line_2519.py`, `test_safety_skip_event_types.py` |
| Every vital-signs one-liner (physical exam, progress note objective, nursing shift note, LLM arrival and day facts) is rendered by one formatter. Each surface names its style (field order, separators, units, integer or raw values, room-air marker). A new surface adds a style, not a formatter. | `clinosim/modules/document/narrative/_vitals_line.py::format_vitals_line` with the styles `PHYSICAL_EXAM`, `PROGRESS_OBJECTIVE`, `NURSING_SHIFT`, `LLM_ARRIVAL`, `LLM_DAY` | `tests/unit/modules/document/narrative/test_vitals_line_2523.py`, `test_narrative_spec_guards.py::test_vitals_lines_only_through_format_vitals_line` (no other formatted string holds three or more vital signs; a single-vital interpretation such as the hypertension control line, and the LLM's min-max range summary, are not vitals lines) |
| A BMI is classified (underweight / normal / overweight / obese, WHO and Japan Society for the Study of Obesity boundaries 18.5 / 25 / 30, each boundary in the upper band) by one function, on the value as displayed. | `clinosim/modules/document/narrative/_narrative_interpretation_thresholds.py::bmi_band` | `tests/unit/modules/document/narrative/test_narrative_spec_guards.py::test_bmi_bands_only_through_bmi_band`, `test_template_generator_nutrition_care_plan.py` |
| A blood pressure is classified (hypertension / high-normal / normal, JSH 2019 office thresholds 140/90 and 130/85, either reading) by one function. Interpretation thresholds of narrative wording are named constants in `_narrative_interpretation_thresholds.py`, compared only there. | `_narrative_interpretation_thresholds.py::bp_band` | `test_narrative_spec_guards.py::test_blood_pressure_bands_only_through_bp_band`, `test_each_bp_boundary_belongs_to_the_upper_band` |
| Every `facts_used` tag names the source of the text it marks, with a prefix of one vocabulary: a structural-CIF field (`ctx.`, `patient.`, `encounter.`, `profile.`, `chronic.`, `physical_exam_findings`, `discharge_instructions`), static reference data (`disease_protocol.`, `encounter_protocol.`, `chief_complaint_variants.`), text composed from the CIF state (`composed:`), or a static template (`generic:`, `outpatient_soap_template.`). A tag outside it is reported by `check-narratives` as fabricated provenance. | `clinosim/modules/document/narrative/semantic_check.py::_ALLOWED_FACT_PREFIXES` | `tests/unit/modules/document/narrative/test_narrative_spec_guards.py::test_every_facts_tag_literal_is_in_the_facts_vocabulary`, `tests/integration/test_check_narratives_mock.py` |
| Every displayed name in a narrative (drug, lab, diagnosis, department, document type) is resolved through the display functions of the code-mapping spec. | `clinosim.codes.display`, `clinosim.locale.loader.lab_display`, ... | the code-mapping spec §10 |

## 4. Not in scope here

- **Clinical coding from a measurement** — e.g. the E66 overweight / obesity code from BMI (`modules/metabolic/engine.py`) — is a diagnosis rule, not narrative wording, and follows its module's own thresholds.

## 5. Gaps

None known. A new exception is listed here with the guard that allows it.
