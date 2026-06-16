# clinosim — TODO

## Status (current as of 2026-04-20)

**v0.2 (Simulation realism + Japanese/English documents + Occupational injuries)** — population-driven simulation with full FHIR R4 Bulk Data Export, multi-country (US/JP), 32 diseases + 46 ED/outpatient conditions, occupational injury support (6 work-related conditions + occupation field), snapshot date support, pluggable LLM providers (Ollama/Bedrock/Mock), three-stage CLI pipeline (`generate` → `narrate` → `export-fhir`), FHIR DocumentReference for 5 clinical document types (Tier A+B) in English and Japanese.

Latest generated datasets:

US full run (40K catchment, 50-bed hospital, seed=42):
- 102,485 encounters (1,501 inpatient + 96,114 outpatient + 5,029 ED)
- 3,344 Bedrock EN narrative documents (1,501 H&P + 1,501 DC + 181 Proc + 97 Op + 64 Death)
- 15 in-progress encounters (snapshot date)
- FHIR Bulk Data 2.0GB, 13 resource types + DocumentReference, 0 ID violations

JP full run (5K catchment, 50-bed hospital, seed=42):
- 16,637 encounters (227 inpatient + 15,886 outpatient + 524 ED)
- 499 Bedrock JP narrative documents
- Multilingual FHIR coding (JP primary + EN secondary for Condition/Procedure)
- CRP unit conversion (mg/L→mg/dL) code-side (AD-42)
- FHIR Bulk Data 467MB

Code system coverage:
- 234 ICD-10-CM codes, 133 ICD-10 codes (EN + JA bilingual)
- 65 LOINC, 68 RxNorm, 31 CPT, 25 K-codes, 39 YJ, 31 SNOMED CT
- 120+ drug name JP translations (drug_names_ja.yaml)
- 201 unit tests passing

## Architecture Decisions (current)

| Decision | Date | Description |
|---|---|---|
| AD-1 | 2026-04-04 | Two simulation modes: Mode 1 (Patient Record) and Mode 2 (Hospital Operations). Mode 2 is a superset. Design for Mode 2, implement Mode 1 first. |
| AD-2 | 2026-04-04 | Modular folder structure: each module is a self-contained folder with README.md. |
| AD-3 | 2026-04-04 | Population-driven forward simulation: generate catchment population first, simulate life events, hospital visits are consequences of population dynamics. |
| AD-4 | 2026-04-04 | Two-layer population model: Layer 1 (lightweight registry for all persons) and Layer 2 (detailed clinical profile, activated only on hospital visit). |
| AD-5 | 2026-04-04 | Household-based generation: people belong to households, enabling realistic family history, infection transmission, and shared attributes. |
| AD-6 | 2026-04-04 | Referring clinics as context (not simulation targets): generate referral letters and prior records without full GP simulation. |
| AD-7 | 2026-04-04 | LLM as selective amplifier: enhances narratives and clinical reasoning; all numerical/structural data remains rule-based. |
| AD-8 | 2026-04-04 | Three generation modes: `none` (structured only), `template` (rule-based text), `llm` (full LLM enhancement). System fully functional without LLM. |
| AD-9 | 2026-04-04 | Compact context pattern: pre-summarized `LLMClinicalContext` (~300 tokens) instead of full patient record for each LLM call. |
| AD-10 | 2026-04-04 | Batch + cache strategy: LLM called at key narrative points only (4–11 calls per patient), with pattern caching for common scenarios. |
| AD-11 | 2026-04-04 | All LLM calls go through `llm_service` module. No other module may call LLM directly. |
| AD-12 | 2026-04-04 | Default LLM provider: local Ollama (qwen:7b). Cloud APIs (Anthropic) available as optional fallback. Provider abstraction enables addition of other LLM providers. |
| AD-13 | 2026-04-04 | Two LLM task categories: JUDGMENT (always English) and NARRATIVE (target country language). English judgment = better quality + fewer tokens. |
| AD-14 | 2026-04-04 | Three-tier validation: Tier 1 statistical benchmarks (automated), Tier 2 clinical pattern validation (automated+expert), Tier 3 domain expert blind test (human). |
| AD-15 | 2026-04-04 | Output as pluggable adapter system: each format (FHIR R4, CSV, HL7v2, etc.) is a separate adapter implementing OutputAdapter interface. |
| AD-16 | 2026-04-04 | Reproducibility via hierarchical seed management. Each module gets deterministic sub-seed. LLM outputs cached to disk for reproducible runs. |
| AD-17 | 2026-04-04 | Three-stage output: (1) Sim + JUDGMENT LLM → CIF structural (immutable) → (2) CIF + NARRATIVE LLM → narrative layer (replaceable) → (3) structural + narrative → format adapters. |
| AD-18 | 2026-04-04 | Pydantic for YAML configs (schema validation at load). @dataclass for runtime types. |
| AD-19 | 2026-04-04 | Preset + override config: `SimulatorConfig.preset("japan_medium").override({...})` |
| AD-20 | 2026-04-04 | LLM graceful degradation: retry → template fallback → structured-only. Never halt. |
| AD-21 | 2026-04-04 | Vertical slice: v0.1-alpha (1 patient) → v0.1-beta (population) → v0.1 (full). |
| AD-22 | 2026-04-04 | Three-level testing: unit (<30s) → integration (<5min) → e2e golden file (<30min). |
| AD-23 | 2026-04-04 | Async LLM at patient level. Bounded concurrency. Sync fallback available. |
| AD-24 | 2026-04-04 | JUDGMENT and NARRATIVE use independently configurable LLM providers/models. Local + cloud mix supported. |
| AD-25 | 2026-04-04 | CIF is language-neutral. Person names are country-specific at generation time. All other localization at output/Stage 2. |
| AD-26 | 2026-04-04 | Clinical terminology uses official master data only (JLAC10, LOINC, etc.). Never LLM-translated. |
| AD-27 | 2026-04-04 | All locale data (names, terminology, code mapping, formatting) centralized in `clinosim/locale/`. Adding a country = adding YAML files. |
| **AD-28** | 2026-04-06 | **Diagnosis vs ground truth separation**: `ConditionEvent` (hidden truth) vs `ClinicalDiagnosis` (what hospital concludes). Misdiagnosis is first-class. |
| **AD-29** | 2026-04-06 | **Diagnostic accuracy via likelihood ratios**: Bayesian update with per-disease LR_TABLE. Configurable correctness rates. |
| **AD-30** | 2026-04-08 | **Code is the truth**: CIF stores only codes + system keys. Display text is resolved at output time via `clinosim.codes`. No `*_name` fields in CIF types. |
| **AD-31** | 2026-04-08 | **FHIR Bulk Data Export NDJSON**: replaced per-encounter Bundle JSON with HL7 FHIR Bulk Data Access compliant NDJSON (one file per resource type + manifest.json). Globally unique Resource.id within each type. |
| **AD-32** | 2026-04-08 | **Snapshot date semantics**: `--end` is the snapshot date. Inpatients still admitted at snapshot become `Encounter.status="in-progress"` with no `discharge_datetime`. Enables current-state EHR queries. |
| **AD-33** | 2026-04-08 | **English-first code systems**: every entry in `clinosim/codes/data/*.yaml` MUST have an `en` field. Other languages are translation attributes with English fallback. |
| **AD-34** | 2026-04-08 | **Hospital config-driven physical layout**: `available_departments` + `department_rollup` + `wards` + `ward_capacity` in hospital YAML drives staff generation, ward assignment, bed location resources. |
| **AD-35** | 2026-04-08 | **codes module separated from locale**: international code systems (ICD/LOINC/RxNorm/etc.) live in `clinosim/codes/`, NOT under `locale/`. Codes are international standards; translations are attributes. |
| **AD-36** | 2026-04-09 | **FHIR Procedure structural fields via SNOMED CT**: category (surgical/diagnostic/therapeutic), performer.function (surgeon/anaesthetist), recorder, reasonReference, bodySite, location (OR), outcome, complication. Metadata table `_PROCEDURE_METADATA` in procedure engine. |
| **AD-37** | 2026-04-09 | **Three explicit CLI stages**: `generate` (structural CIF) → `narrate` (clinical documents) → `export-fhir` (FHIR R4 NDJSON). Each stage is independently runnable; Stage 2 can be executed remotely (e.g. EC2 for Bedrock) while Stage 1/3 stay local. |
| **AD-38** | 2026-04-09 | **Clinical documents as FHIR DocumentReference (Tier A+B)**: Discharge Summary (LOINC 18842-5), Death Note (69730-0), Operative Note (11504-8), Admission H&P (34117-2), Procedure Note (28570-0). 5 document types, ~374 documents per 5000-population run. Base64 text/plain attachment with sha1 hash and size. |
| **AD-39** | 2026-04-09 | **LLM provider plugin registry**: `providers/` subpackage with `LLMProvider` Protocol. Registry maps config keys (`ollama`, `bedrock`, `mock`, `local`) to builder callables. `factory.build_from_config_file()` wires providers + cache + registry from YAML. Bedrock uses boto3 lazy import. |
| **AD-40** | 2026-04-09 | **Prompt templates as per-language YAML**: `clinosim/modules/llm_service/prompts/<lang>/<task>.yaml` with `system`, `user_template`, `max_tokens`, `temperature`, `version`. Rendered via `string.Template` (stdlib, zero deps). Language fallback to English (mirrors codes module). |
| **AD-41** | 2026-04-09 | **SHA256 disk cache for LLM responses**: `PromptCache` keys by `SHA256(system ‖ user ‖ model)`. Enables reproducible re-runs, partial re-run recovery, and cost control for Bedrock. Cache stats in `cost_report()`. |
| **AD-42** | 2026-04-13 | **Code-side unit conversion for Japanese locale**: CRP mg/L→mg/dL conversion happens in `hospital_course_extractor` and `document_generator` (not in LLM prompt). `format_lab_trends(language=)` and `_initial_labs(language=)` apply locale-specific conversion factors. |
| **AD-43** | 2026-04-13 | **Japanese narrative prompt quality rules**: All ja prompts include mandatory 「医師」suffix for staff names. Markdown forbidden — use 【】 section headers, ■ subheaders, ・ bullets. |
| **AD-44** | 2026-04-15 | **Enrichment is language-neutral, display at output time**: A/B test confirmed LLM translates drug/procedure names reliably. Enrichment passes English text to LLM; only 2 code-side exceptions: (1) `code_lookup(system, code, lang)` for official short-form diagnosis names, (2) CRP unit conversion (math). |
| **AD-45** | 2026-04-15 | **Occupation field on Patient/PersonRecord**: 12 categories (manufacturing, construction, agriculture, healthcare, service, office, transportation, education, homemaker, student, retired, unemployed). Drives work-related injury incidence via `occupation_risk_multipliers` in demographics.yaml. FHIR Observation (LOINC 11341-5, social-history). |
| **AD-46** | 2026-04-16 | **Multilingual FHIR coding**: Condition and Procedure emit dual coding entries (primary language + interop language). `_build_diagnosis_codeable_concept()` resolves from both `icd-10` and `icd-10-cm` with cross-system fallback. Never emits `display==code`. |
| **AD-47** | 2026-04-16 | **FHIR Observation referenceRange/interpretation consistency**: Both must be present and consistent per FHIR R5 Note 5. Lab interpretation recomputed from value vs referenceRange (not CIF flag alone). Vital signs include normal + critical (panic) reference ranges as separate entries. |
| **AD-48** | 2026-04-16 | **Procedure display via code dictionary (AD-30 strict)**: `procedure_name` removed from ProcedureRecord — display resolved at output time via `code_lookup("k-codes"|"cpt", code, lang)`. Both `procedure_code_jp` and `procedure_code_us` stored in CIF for multilingual FHIR output. |
| **AD-49** | 2026-04-18 | **Condition code.text with clinical abbreviations**: `_CONDITION_SHORT_NAME` maps ICD base codes to search-friendly short names (COPD, CHF, CKD, DM, AF, etc.) in both EN and JA. `coding[].display` keeps official ICD name. |
| **AD-50** | 2026-04-18 | **Medication protocol prefix stripping**: `_strip_protocol_prefix()` separates category prefixes (DVT_prophylaxis:, antipyretic:, etc.) from drug name in `medicationCodeableConcept.text`. Drug name only in text, protocol context in dosageInstruction. |

## Implementation Status

### v0.1-alpha — "Hello World" ✅ COMPLETE

All 12 tasks complete. 1 pneumonia patient end-to-end.

### v0.1-beta — Population + archetypes + multi-country ✅ COMPLETE

| # | Task | Module | Status |
|---|---|---|---|
| 1 | Population generation (households, Layer 1) | `population` | ✅ |
| 2 | Life event engine (monthly loop, disease onset) | `population` | ✅ |
| 3 | Care-seeking decision model | `population` | ✅ |
| 4 | Layer 1→2 activation / deactivation | `patient` | ✅ |
| 5 | Staff roster + assignment (ward-aware) | `staff` | ✅ |
| 6 | All 6 archetypes | `disease`, `clinical_course` | ✅ |
| 7 | Treatment selection + change logic | `clinical_course` | ✅ |
| 8 | Bayesian differential diagnosis | `diagnosis` | ✅ |
| 9 | LLM service — template mode | `llm_service` | ✅ |
| 10 | CIF → FHIR R4 adapter | `output` | ✅ (Bulk Data NDJSON) |
| 11 | CIF → CSV adapter | `output` | ✅ |
| 12 | Multiple patients (10–100,000) | `simulator` | ✅ (tested up to 30k) |

### v0.1 — Foundation hardening ✅ COMPLETE

| # | Task | Module | Status |
|---|---|---|---|
| 1 | clinosim.codes module (EN-first) | `codes` | ✅ |
| 2 | FHIR R4 Bulk Data NDJSON export | `output` | ✅ |
| 3 | Snapshot date semantics | `simulator` | ✅ |
| 4 | Hospital config-driven layout | `facility`, `staff` | ✅ |
| 5 | Bed Location resources (FHIR) | `output` | ✅ |
| 6 | PractitionerRole.location assignment | `staff`, `output` | ✅ |
| 7 | All Resource.id globally unique | `output` | ✅ (0 violations) |
| 8 | UCUM-compliant units | `observation`, `output` | ✅ |
| 9 | NEWS2-compatible vitals (AVPU + O2) | `physiology`, `output` | ✅ |
| 10 | 28 diseases + 44 ED/outpatient conditions | `disease`, `encounter` | ✅ |
| 11 | Module READMEs (all 17 modules) | docs | ✅ |

### Milestone 1 — Clinical documents + pluggable LLM ✅ COMPLETE (2026-04-09)

| # | Task | Module | Status |
|---|---|---|---|
| 1 | FHIR Procedure structural fields (SNOMED) | `procedure`, `output` | ✅ (AD-36) |
| 2 | `snomed-ct.yaml` code system | `codes` | ✅ |
| 3 | Operating room Location resources | `output` | ✅ |
| 4 | LLM provider subpackage (base, ollama, mock, bedrock) | `llm_service` | ✅ (AD-39) |
| 5 | Provider registry + factory (YAML → LLMService) | `llm_service` | ✅ |
| 6 | Prompt templates as per-language YAML | `llm_service` | ✅ (AD-40) |
| 7 | PromptCache (SHA256 disk cache) | `llm_service` | ✅ (AD-41) |
| 8 | `ClinicalDocument` type + CIF extension | `types`, `output` | ✅ |
| 9 | `hospital_course_extractor` (deterministic facts) | `output` | ✅ |
| 10 | `document_generator` (narrative CIF writer) | `output` | ✅ |
| 11 | FHIR `DocumentReference` builder | `output` | ✅ (AD-38) |
| 12 | `clinosim narrate` / `export-fhir` CLI | `simulator` | ✅ (AD-37) |
| 13 | `llm_service.bedrock.yaml` config | `config` | ✅ |
| 14 | 6 LOINC codes for document types | `codes` | ✅ |
| 15 | Unit tests (32 new, 141 total) | tests | ✅ |
| 16 | Tier A+B English prompts (5 YAML files) | prompts | ✅ |

### Milestone 2 — Simulation fixes + Bedrock full run ✅ COMPLETE (2026-04-10)

| # | Task | Module | Status |
|---|---|---|---|
| 1 | EC2 Bedrock 5-type validation (4 rounds, 12 diseases) | infra, `output` | ✅ |
| 2 | YAML-driven `medication_holds` in disease protocols | `disease`, `simulator` | ✅ (hemorrhagic_stroke, pancreatitis, DKA, sepsis, AKI) |
| 3 | Surgery procedure names from disease YAML | `procedure`, `disease` | ✅ (cholecystitis→CPT47562, appendicitis→CPT44970, trauma→CPT49000) |
| 4 | Hip fracture discharge prescription | `disease` | ✅ (oxycodone + enoxaparin + Ca/VitD) |
| 5 | DC Rx Cr-based contraindication check | `simulator` | ✅ (final_renal_function < 0.3 gates nephrotoxic drugs) |
| 6 | BPH sex filter (demographics.yaml) | `population` | ✅ (sex: M field + engine filter) |
| 7 | LLM hallucination prevention (DC Rx prompt) | `llm_service` | ✅ (prompt rule: only listed meds) |
| 8 | Nurse assignment per department (was IM-only) | `simulator` | ✅ (MAR + vitals use patient's dept nurse) |
| 9 | Staff ID → name in narrative prompts | `output` | ✅ (DR-XX-NNN → Dr. Name) |
| 10 | Country-specific recommended_population | `config` | ✅ (US: 40K, JP: 5K) |
| 11 | .gitignore fix (clinosim/modules/output/ was excluded) | repo | ✅ |
| 12 | EC2 Bedrock full 421-document run | infra | ✅ |
| 13 | FHIR Bulk Data with DocumentReference → iris-ai | `output` | ✅ |

### v0.2 — Simulation realism + JP/EN documents + Occupational injuries (CURRENT)

| # | Task | Module | Status |
|---|---|---|---|
| 1 | Severity-based lab frequency modulation | `simulator` | ✅ severe 1.3x, mild 0.6x |
| 2 | Trauma Hgb recovery model / discharge gate | `physiology`, `simulator` | ✅ |
| 3 | HF exacerbation: IV diuretic not in MAR | `simulator`, `order` | ✅ |
| 4 | narrate progress display (patient N/M) | `output` | ✅ |
| 5 | Treatment escalation from disease YAML | `simulator` | ✅ Day 3 escalation when inflammation > 0.3 |
| 6 | Treatment change detection in extractor | `output` | ✅ |
| 7 | JP Bedrock full run (5K pop, 499 docs) | infra | ✅ |
| 8 | Japanese prompts (`prompts/ja/*.yaml`) | `llm_service` | ✅ 5 types, 【】format, 「医師」suffix |
| 9 | Template fallbacks for Tier A+B | `llm_service` | ✅ |
| 10 | Diurnal lab variation | `physiology` | ✅ |
| 11 | Critical patient vitals q2h | `simulator` | ✅ |
| 12 | Consistency validator Tier 2 (8 checks) | `validator` | ✅ 0 errors |
| 13 | AKI complication → metformin cancel | `simulator` | ✅ |
| 14 | CRP mg/L→mg/dL code-side conversion | `output` | ✅ (AD-42) |
| 15 | Staff name 「医師」 suffix | `llm_service` | ✅ (AD-43) |
| 16 | Chronic med base code fallback | `simulator` | ✅ |
| 17 | Empty medication string filter | `simulator`, `patient` | ✅ |
| 18 | JP FHIR full localization | `output` | ✅ (display/text/name 全て JP) |
| 19 | A/B test: enrichment localization strategy | `output` | ✅ (AD-44) English enrichment + LLM translates |
| 20 | Enrichment language-neutral refactor | `output` | ✅ (AD-44) code_lookup + CRP のみ locale依存 |
| 21 | Occupation field (PersonRecord + PatientProfile) | `population`, `patient` | ✅ (AD-45) 12 categories |
| 22 | Work-related injuries (4 inpatient + 2 ED) | `disease`, `encounter` | ✅ (AD-45) occupation_risk_multipliers |
| 23 | Multilingual FHIR coding (Condition + Procedure) | `output` | ✅ (AD-46) primary + interop dual coding |
| 24 | FHIR Observation referenceRange/interpretation | `output` | ✅ (AD-47) 0 inconsistencies |
| 25 | procedure_name removed from CIF (AD-30 strict) | `procedure`, `output` | ✅ (AD-48) code_lookup only |
| 26 | JP drug name dictionary (120+ entries) | `locale` | ✅ drug_names_ja.yaml |
| 27 | JP allergen/procedure/dosage term localization | `output` | ✅ FHIR adapter |
| 28 | Emergency contact real person names | `patient` | ✅ (佐伯 紬, not 佐伯家) |
| 29 | Condition code.text abbreviations (COPD, CHF, CKD) | `output` | ✅ (AD-49) |
| 30 | Medication protocol prefix stripping | `output` | ✅ (AD-50) |
| 31 | US 40K Bedrock full run (3,344 EN docs) | infra | ✅ |
| 32 | JP recommended_population 5K → 10K | `config` | ✅ |
| 33 | Anthropic direct provider (non-Bedrock) | `llm_service` | Open |
| 34 | OpenAI-compatible provider (LiteLLM / vLLM) | `llm_service` | Open |
| 35 | Population demographics externalization (US) — sex_ratio, physiology, lifestyle, comorbidity_correlations, lifestyle_risk_multipliers, insurance_distribution, race_distribution, occupation age thresholds | `population`, `patient`, `locale` | ✅ US complete (2026-04-20) |
| 36 | Population demographics externalization (JP) — apply same sections to `jp/demographics.yaml` | `locale` | 🔲 Pending user approval |
| 37 | CIF smoke run with US demographics externalization — generate 500-patient CIF and verify BMI/smoking/insurance/race fields are realistic | `simulator`, `population` | 🔲 TODO |

## Open Design Questions

### High Priority

| # | Question | Module | Status |
|---|---|---|---|
| 1 | State variable granularity for severe sepsis / MOF | `physiology` | Open (v0.2: may need lactate, MAP, urine output as separate variables) |
| 2 | Pediatric disease modules (currently adult only) | `disease`, `physiology` | Open (v0.2) |
| 3 | OB/GYN encounters (pregnancy, delivery, NICU) | `encounter`, `disease` | Open (v0.2) |
| 4 | Outpatient chronic disease management depth | `encounter`, `population` | Partial (chronic_followup.yaml exists but limited) |
| 5 | LLM judgment phase wiring (currently template only) | `llm_service`, `diagnosis` | Open |
| 6 | Realistic 80% bed occupancy at default population | `facility`, `population` | ✅ Fixed — US 40K / JP 5K recommended_population (was 60K) |
| 7 | Code coverage expansion: more LOINC/RxNorm/CPT codes | `codes` | Continuous (224 ICD, 59 LOINC, 68 RxNorm, 25 CPT currently) |

### Medium Priority

| # | Question | Module | Status |
|---|---|---|---|
| 8 | SNOMED CT integration (clinical findings) | `codes` | Open |
| 9 | Discrete-event simulation engine (Mode 2) | `simulator` | Open (planned for v1.0) |
| 10 | Holiday calendar per country (admission/discharge patterns) | `healthcare_system`, `facility` | Open |
| 11 | Diurnal variation in lab values | `observation` | ✅ Implemented (glucose postprandial, WBC circadian) |
| 12 | Episode-of-care linking (multi-encounter problem tracking) | `encounter` | Open |
| 13 | Consult workflow (specialty consultation requests) | `encounter`, `staff` | Open |
| 14 | Diagnostic drift over hospital stay | `diagnosis` | Open |
| 15 | Anesthesia record detail (intra-op vitals, drugs) | `procedure` | Open |

### Low Priority

| # | Question | Module | Status |
|---|---|---|---|
| 16 | Medical cost / claims data (DPC/DRG codes) | `output` | Open |
| 17 | End-of-life model (DNR/DNAR, palliative care) | `clinical_course` | Open |
| 18 | Teaching hospital resident rotation | `staff`, `facility` | Open |
| 19 | Mental health encounters (psychiatric admission) | `disease`, `encounter` | Open |
| 20 | Equipment throughput real-world validation | `facility` | Open |
| 21 | Seasonal incidence curves per disease per country | `disease` | Partial (basic seasonal mod exists) |
| 22 | Screening program participation rates | `population` | Open |

## Roadmap

### v0.2 — Clinical reasoning + LLM integration (CURRENT)

- [x] Clinical document pipeline (Tier A+B, 5 LOINC-coded types) ← Milestone 1
- [x] Pluggable LLM providers (Ollama / Bedrock / Mock) ← Milestone 1
- [x] Prompt templates as YAML (per-language) ← Milestone 1
- [x] FHIR DocumentReference output ← Milestone 1
- [x] SHA256 prompt cache ← Milestone 1
- [x] EC2 + Bedrock production run (421 documents, Claude Sonnet 4) ← Milestone 2
- [x] 4-round clinical review (35 documents, 12 disease patterns) ← Milestone 2
- [x] 8 simulation fixes (YAML medication_holds, surgery names, Cr check, sex filter, nurse dept, staff names) ← Milestone 2
- [x] Country-specific recommended_population (US:40K, JP:5K) ← Milestone 2
- [x] Japanese prompts with clinician review (5 types, 2 rounds, 8+8 patients) ← Milestone 3
- [x] JP FHIR localization (Location names, Encounter type, dosage, marital status) ← Milestone 3
- [x] CRP unit conversion (mg/L→mg/dL) at code level for ja locale (AD-42)
- [x] Staff name suffix 「医師」 consistency in ja prompts (AD-43)
- [x] Chronic medication base code fallback (E11→E11.9 lookup)
- [x] Empty medication string filter (drug_name key + empty filter)
- [ ] LLM JUDGMENT phase wiring (diagnostic reasoning, treatment rationale)
- [ ] Validator Pass 2 (LLM consistency review)
- [ ] **[TODO] CIF smoke run: US demographics externalization end-to-end verify** — generate 500-patient US CIF, check PatientProfile.bmi/smoking_status/alcohol_use/insurance_type/race/ethnicity are populated realistically
- [ ] **[TODO] JP demographics externalization** — add sex_ratio, physiology, lifestyle_distribution, lifestyle_risk_multipliers, comorbidity_correlations, insurance_distribution, occupation age_thresholds to `jp/demographics.yaml` (pending user approval)
- [ ] Diagnostic drift over hospital stay
- [ ] Pediatric disease modules (start with viral URI, asthma, gastroenteritis)
- [ ] OB/GYN module (pregnancy, delivery, NICU)
- [ ] Performance optimization (async LLM, parallel patient simulation)

### v0.3 — Operational realism + LLM intelligence

- [ ] Resident identifier & insurance numbering — `modules/identity/` (AD-54)
  - [x] P1: module skeleton (base/registry/generators/providers) + JP numbering (employer-level 記号, 社保/国保/後期高齢, 枝番) + representative payer Organizations + snapshot single enrollment + FHIR `Coverage` (JP Core) + sensitive-field chokepoint (`national_id` not emitted) — 22 unit + 5 e2e tests, verified end-to-end
  - [ ] P2: period-bounded enrollment history + deterministic 75-yr → 後期高齢者 transition + encounters reference time-valid `Coverage.period`
  - [ ] P3: light employment transitions (就職/退職/転職) + マイナンバーカード取得日 / マイナ保険証登録日 + qualification verification method (紙/online)
  - [ ] P4: US `_sample_insurance` migration into `providers/us.py` (behavior-compat tests) + docs/ADR finalize
  - [x] Verify JP Core `Coverage` profile (記号/番号/枝番 extensions, subscriberId/dependent, payor namingsystem) — recorded in `locale/jp/identity.yaml:fhir_coverage` + DESIGN §6.9
  - [x] Realism+quality pass: occupation-driven 社保/国保 (emergent <75 ≈ 73:27, MHLW), insurance_type unified with identity.category, マイナ保険証 marginal preserved, payor Organization real names + `organization-type#pay`, Coverage.type text + relationship
  - [ ] Verify (裏取り) remaining: representative 保険者番号 vs official registries · 75-yr transition rules · 保険者番号 検証番号 algorithm · 個人番号 check-digit formula (replace `# TODO: verify` placeholders) · 健保組合 dual-income households (each earner own 社保, Phase 2/3)
- [ ] LLM JUDGMENT phase wiring (diagnostic reasoning, treatment decisions)
- [ ] Progress Note (Tier C, opt-in — daily SOAP notes via LLM)
- [ ] Validator Pass 2 (LLM consistency review)
- [ ] Discrete-event simulation engine (Mode 2)
- [ ] Resource contention (OR scheduling, ICU bed allocation)
- [ ] Multi-day treatment scheduling
- [ ] Consult workflow
- [ ] Episode-of-care multi-encounter tracking
- [ ] Performance: 100k+ patients, parallel sim

### Phase 0 — Extensibility foundation (AD-56, do before the enrichment roadmap)

> Enabling refactors so each AD-55 item is "register a builder/enricher" instead of editing
> central monoliths. Gate with existing golden/e2e + determinism (AD-16).

- [ ] **① FHIR resource-builder registry** — replace the hand-appended `_build_bundle()`
  (`output/fhir_r4_adapter.py`) with a registry of `(record, ctx) -> list[resource]` builders;
  each declares dedup behaviour (patient-level vs per-encounter). Core loops & emits. **Highest leverage.**
- [ ] **② Simulator enricher registry** — replace inlined passes in `run_beta()`
  (`simulator/engine.py`) with enrichers registered as `name`/`order`/`enabled(config)`/`run(...)`;
  iterate in fixed order (determinism). Migrate `assign_identities` to it as the first consumer.
- [ ] **④ CIF extensions slot** — add `CIFPatientRecord.extensions: dict[str, Any]`
  (`types/output.py`). Base = typed fields; Modules write `extensions[<module>]`, never edit core type.
- [ ] **③ Config module-enablement map** — `SimulatorConfig.modules: dict[str, bool]` +
  `module_enabled()` helper (`types/config.py`); keep `jp_insurance_numbers` as back-compat alias.
- [ ] **⑤ (with microbiology)** externalize `observation` lab catalog (CV/precision/units) to YAML.
- Deferred: ⑥ CSV adapter registry (low leverage — new table ≈ 3 lines).

### AD-57 — Unify observation (lab + vital) generation across venues

> Today lab/vital values come from **3 divergent paths**: inpatient = physiology
> `derive_lab_values(state)` (state/comorbidity-aware); ED (`emergency.py`) + outpatient
> (`outpatient.py`) = hardcoded `baseline_values` dicts + a dangerous `default 100`
> fallback, ignoring patient comorbidities. This caused the troponin canonicalization to
> be applied in 3 places and risks venue inconsistency (e.g. a CKD patient's ED creatinine
> reads normal). Unify into one generation service.

- [x] **Phase 1 — ED/outpatient labs → physiology.** `emergency.py` + `outpatient.py` now
  build a baseline `PhysiologicalState` from the patient's chronic conditions
  (`initialize_state`) and derive true values with `derive_lab_values` (comorbidity-aware:
  CKD → high Cr/low eGFR, verified). Dangerous `default 100` replaced with a normal fallback.
  `baseline_values` retained only for analytes physiology doesn't model. Same RNG draw
  count → determinism preserved; integration/e2e green.
- [ ] Extract a single `generate_observations(...)` wrapper so the 3 venues share one
  call (currently they share the physiology functions but duplicate the boilerplate).
- [ ] Encounter scenarios: add optional `initial_state_impact` so ED-only presentations
  (e.g. appendicitis WBC↑) carry acute abnormalities, not just comorbidity baseline.
- [x] **ABG panel expansion + pO2 done.** `observation/reference_data/lab_panels.yaml`
  (data-driven) maps `ABG` → pH/pCO2/pO2/HCO3; panel orders are expanded into component
  lab orders (parent marked resulted) so each resolves via the scalar path. physiology
  derives pO2 (inflammation-proxied hypoxemia). LOINC/JLAC10 codes added. Respiratory
  cohort now gets blood-gas results (was none) — verified COPD pH/pCO2/pO2/HCO3 resolve.
- [ ] Unify vitals generation (ED/outpatient still use `baseline_vitals + noise`, not
  `derive_vital_signs` — fold disease state into ED/outpatient vitals).

### EHR data enrichment roadmap (AD-55 — Base vs Module)

> Benchmarked vs Synthea / USCDI v5 / MIMIC-IV. **Imaging/modality data out of scope**
> (CT/MRI/X-ray/US, echo, ECG tracings, endoscopy, spirometry, pathology) — see DESIGN §6.10.
> **Base** = always-on, extends core (`types`/`population`/`observation`/`simulator`/`output`).
> **Module** = opt-in, **one theme per module** (same pattern as `identity`).
> Cross-cutting for all: types in `types/`, module-independence (deps in README),
> deterministic sub-seed, FHIR built in `output` reading CIF (modules stay output-agnostic).

#### Base — near-essential (always generated; extends existing core)

- [x] **Microbiology & susceptibility** — `observation/microbiology.py` + `types/microbiology.py` + `observation/reference_data/microbiology.yaml` (all codes data-driven). Emits FHIR `DiagnosticReport` + `Specimen` + `Observation` via the AD-56 builder registry; CSV `microbiology.csv`. Sepsis/pneumonia/UTI/cellulitis/aspiration cohort. Encounter-scoped sub-seed (main stream unperturbed). 10 unit tests. `# TODO: verify` SNOMED/LOINC codes + antibiogram rates vs authoritative sources.
- [~] **Blood-based markers**: cardiac troponin + CK-MB **done** — `physiology` derives Troponin_I/CK_MB (ACS flag `causes_myocardial_injury` on the disease scenario → MI-level; other cardiac dysfunction → mild type-2; CKD confounder via renal; sex-specific cutoff). Lab order-name aliases (`observation/reference_data/lab_aliases.yaml`) canonicalize stat/serial/variant orders across inpatient/ED/outpatient; FHIR uses canonical name → LOINC resolves. Lactate already worked. **ABG panel (pH/pCO2/pO2/HCO3 from one "ABG" order) + pO2 deferred** — needs panel-expansion (one order → multiple results), tracked under AD-57.
  - [ ] JP JLAC10 codes for Troponin_I / CK_MB (US LOINC done); serial-troponin intra-day trend
- [ ] **`DiagnosticReport` grouping** — `output` adapter (+ `types/output`): group lab Observations into panels (CBC/BMP/LFT). Structural fidelity, no new clinical data.
- [ ] **Nursing flowsheets** — `observation` / `simulator.inpatient` (+ `types`): I/O & fluid balance (from `volume_status`), NEWS2 (already computable), pain (0-10), GCS, Braden, fall risk → `Observation`.
- [ ] **Immunization history** — `population`/patient-profile attribute (+ `types/patient`); emit `Immunization`. Locale schedules (JP routine + influenza/pneumococcal; US ACIP).
- [ ] **Family history** — `population` attribute (+ `types`); emit `FamilyMemberHistory` (DM/HTN/CAD/cancer). Base-light attribute, not a module.
- [ ] **Code status / advance directive** — inpatient/ICU/death encounter attribute (+ `types/encounter`); emit `Observation`/`Consent`. Base-light.
- [ ] **Extended SDOH incl. JP 要介護度** — `population`/`locale` demographics attributes (extends existing smoking/alcohol/occupation); emit SDOH `Observation`.

#### Modules — specialized / optional (opt-in, one theme each)

- [ ] **`modules/billing/`** — country-pluggable レセプト/claims (JP **DPC** per-diem bundling / US `Claim`+`ExplanationOfBenefit`). Mirrors `identity`: provider registry, deps `types`/`codes`/`locale`, reads CIF, FHIR in `output`, `--billing` flag. **Supersedes the v0.5 "DPC/DRG cost data" item.**
- [ ] **`modules/device/`** — device placement (central line / urinary catheter / ventilator / telemetry) + **HAI risk** (CLABSI/CAUTI/VAP) from dwell time; deps `procedure`/`types`; emit `Device`/`DeviceUseStatement` (+ HAI `Condition`). Flag-gated.
- [ ] **`modules/care_coordination/`** — `CarePlan`/`CareTeam`/`Goal` for USCDI/Synthea interoperability completeness; deps `types`; reads CIF; flag-gated.

Suggested order: microbiology+markers → nursing flowsheets+`DiagnosticReport` → immunization/family-history/code-status/SDOH (Base) → `modules/billing` (JP DPC) → `modules/device` → `modules/care_coordination`.

### v0.4 — Coverage expansion

- [ ] SNOMED CT clinical findings
- [ ] Mental health encounters
- [ ] Long-term care / rehabilitation
- [ ] Home health
- [ ] More countries (UK, EU, China, Korea)
- [ ] Holiday calendars

### v0.5 — Polish

- [ ] DPC/DRG cost data
- [ ] HL7 v2 output adapter
- [ ] CDA output adapter
- [ ] SQL output adapter
- [ ] Tier 3 expert blind test program

### v1.0 — Production-ready

- [ ] 1M+ patient generation in reasonable time
- [ ] Full validation against published benchmarks
- [ ] Comprehensive documentation
- [ ] Stable API contracts

## Recent completions (2026-04-20 — Demographics externalization US)

- ✅ Population demographics externalization (US): 8 hardcoded fields moved to `us/demographics.yaml` — sex_ratio, physiology (BMI/height CDC NHANES), lifestyle_distribution (smoking/alcohol sex-specific CDC NHIS), lifestyle_risk_multipliers (BMI + smoking → chronic + acute events), comorbidity_correlations (I10/E11.9/E78 Framingham), insurance_distribution (age-band KFF 2023), race_distribution (Census 2020), occupation age_thresholds
- ✅ PersonRecord now carries bmi, smoking_status, alcohol_use (Layer-1 lifestyle attributes for risk multipliers)
- ✅ PatientProfile now carries race, ethnicity (US only; empty string for JP)
- ✅ activate_patient() refactored: demo: dict replaces country: str; BMI/lifestyle from Layer-1; insurance/race from YAML
- ✅ load_demographics() injects _country key for downstream locale selection
- ✅ 201 unit tests passing (was 200)
- 🔲 JP locale deployment pending approval
- 🔲 End-to-end CIF smoke run pending

## Recent completions (2026-04-19 — Milestone 4: FHIR standards compliance + occupational injuries)

- ✅ Occupational injuries: 4 inpatient (crush_injury_hand, industrial_burn_severe, fall_from_height, electrical_injury) + 2 ED (eye_foreign_body, chemical_exposure) — with occupation_risk_multipliers in demographics.yaml
- ✅ Occupation field on PersonRecord/PatientProfile: 12 categories with age-based distribution from labor statistics. FHIR output as Observation (LOINC 11341-5, social-history)
- ✅ A/B test: empirically confirmed English enrichment + LLM translation gives equal/better quality vs pre-localization. Reverted over-localization (AD-44)
- ✅ Multilingual FHIR coding: Condition and Procedure emit dual coding (JP primary + EN interop, or vice versa). `_build_diagnosis_codeable_concept()` with cross-system fallback (AD-46)
- ✅ FHIR Observation referenceRange/interpretation consistency: 0 inconsistencies (was 5,522). SpO2 100% HH bug fixed. Vital signs include normal + critical ranges. JP display for all (AD-47)
- ✅ procedure_name removed from ProcedureRecord (AD-48, AD-30 strict): display via code_lookup("k-codes"|"cpt", code, lang). Both procedure_code_jp and procedure_code_us stored
- ✅ k-codes.yaml expanded 2→25 entries, cpt.yaml +6 entries. Procedure display via code dictionary (not hardcoded dict)
- ✅ Comprehensive JP FHIR localization: all display/text/name fields (Encounter class, Condition category/severity, Observation category/interpretation, referenceRange, Organization type, Location name/type, Patient relationship, Procedure code, MedicationRequest/Administration text)
- ✅ Drug name dictionary (120+ entries) + allergen/procedure/dosage term translation for FHIR adapter
- ✅ Condition code.text abbreviations (COPD, CHF, CKD, DM, AF etc.) for search friendliness (AD-49)
- ✅ Medication protocol prefix stripping — DVT_prophylaxis:, antipyretic: etc. removed from medicationCodeableConcept.text (AD-50)
- ✅ Emergency contact person names (佐伯 紬 instead of 佐伯家)
- ✅ JP recommended_population 5K→10K (realistic 70-80% bed occupancy)
- ✅ US 40K full run on EC2: 3,344 Bedrock EN documents, FHIR 2.0GB
- ✅ JP 5K full run on EC2: 499 Bedrock JP documents, FHIR 467MB
- ✅ ICD-10 + ICD-10-CM: 12 missing codes added (J12.9, A08.4, M54.50 etc.)
- ✅ 189 unit tests passing

## Recent completions (2026-04-13 — Milestone 3: Japanese narrative quality + simulation fixes)

- ✅ Japanese narrative prompts (5 types: admission_hp, discharge_summary, death_summary, operative_note, procedure_note)
- ✅ 2-round clinician review with Bedrock Claude Sonnet 4 (8+8 patients, 23+22 documents)
- ✅ 8 diverse diseases validated: sepsis, acute appendicitis, hip fracture, AMI, GI bleed, hemorrhagic stroke, cellulitis, AF-RVR
- ✅ CRP unit conversion moved from LLM prompt to code (AD-42): `format_lab_trends(language=)` + `_initial_labs(language=)` with `_JA_CONVERSION` dict
- ✅ Staff name suffix 「医師」 enforced in all ja prompts (AD-43) — was inconsistent in v1 review
- ✅ Chronic medication base code fallback: `chronic_meds.get(code) or chronic_meds.get(code.split(".")[0])` in `inpatient.py` (was exact-match only)
- ✅ Empty medication string filter in `helpers.py` (`drug_name` key support + empty filter) and `activator.py` (filter before emptiness check)
- ✅ JP FHIR localization: Location names (4E病棟, 4E-01号室), Encounter type (入院), serviceType (内科), maritalStatus (既婚), dosageInstruction (経口, 1日1回)
- ✅ JP staff name format in narratives (佐伯 紬医師, not Dr. 佐伯 紬)
- ✅ JP 5K full Bedrock run initiated on EC2 (CIF + narrative, nohup-safe)
- ✅ 187 unit tests passing (up from 141)

## Recent completions (2026-04-10 — Milestone 2: Simulation fixes + Bedrock full run)

- ✅ 4-round Bedrock clinical validation (35 documents, 12 disease patterns, 5 document types)
- ✅ YAML-driven `medication_holds` in disease protocols (hemorrhagic_stroke, pancreatitis, DKA, sepsis, AKI)
- ✅ Surgery names from disease YAML (cholecystitis→laparoscopic cholecystectomy CPT 47562, appendicitis→CPT 44970, trauma→exploratory laparotomy CPT 49000)
- ✅ Hip fracture discharge prescription (oxycodone/acetaminophen + enoxaparin + calcium/vitamin D)
- ✅ Discharge Rx renal contraindication check (final_renal_function < 0.3 → skip metformin/celecoxib/NSAIDs)
- ✅ BPH sex filter in demographics.yaml (N40 male-only + population engine sex check)
- ✅ LLM hallucination prevention (discharge_summary prompt: "only prescribe listed medications")
- ✅ Nurse assignment per department (was hardcoded to internal_medicine → now uses patient's dept)
- ✅ Staff ID → name resolution in narrative prompts (DR-XX-NNN → Dr. Name, NS-XX-NNN → RN Name)
- ✅ Country-specific recommended_population (US: 40K, JP: 5K based on bed/population ratios)
- ✅ .gitignore fix (clinosim/modules/output/ was accidentally excluded)
- ✅ EC2 Bedrock full run: 421 documents generated (191 H&P + 191 DC + 22 Procedure + 9 Op + 8 Death)
- ✅ FHIR Bulk Data with 13 NDJSON types (incl. DocumentReference 421 + Practitioner 71 all-dept nurses)
- ✅ Full dataset delivered to iris-ai (209MB FHIR Bulk Data)

## Recent completions (2026-04-09 — Milestone 1: Clinical documents)

- ✅ FHIR Procedure structural fields: category, performer.function, recorder, reasonReference, bodySite, location (OR), outcome, complication (all via SNOMED CT subset, AD-36)
- ✅ `clinosim/codes/data/snomed-ct.yaml` — 32-code minimal SNOMED subset for procedures/outcomes/complications/body sites (en + ja)
- ✅ Operating room Location resources in facility bundle (hospital-config-driven)
- ✅ `clinosim/modules/llm_service/providers/` subpackage: `base.py` Protocol, `ollama.py`, `mock.py`, `bedrock.py` (boto3 lazy, Converse API)
- ✅ Provider registry + `register_provider()` extension point (AD-39)
- ✅ `factory.build_from_config_file()` — YAML-driven LLMService construction
- ✅ `PromptRegistry` with `string.Template`-based rendering and English fallback (AD-40)
- ✅ `PromptCache` (SHA256 disk cache) with per-call stats in `cost_report()` (AD-41)
- ✅ 5 English prompt YAML files: `discharge_summary`, `death_summary`, `operative_note`, `admission_hp`, `procedure_note`
- ✅ `ClinicalDocument` type in `clinosim/types/clinical.py` + `CIFPatientRecord.documents` field
- ✅ `clinosim/modules/output/hospital_course_extractor.py` — deterministic event extraction (admission, surgeries, lab peaks, complications, discharge)
- ✅ `clinosim/modules/output/document_generator.py` — Stage 2 narrative CIF writer (Tier A+B)
- ✅ `_build_document_reference()` in `fhir_r4_adapter` — base64 attachment + sha1 hash + related Procedure reference
- ✅ `clinosim narrate` and `clinosim export-fhir` CLI subcommands (AD-37)
- ✅ `clinosim generate --narrative --llm-config PATH --narrative-version ID` integrated pipeline
- ✅ `clinosim/config/llm_service.bedrock.yaml` — EC2 Bedrock config template
- ✅ 6 LOINC codes (34117-2, 11506-3, 18842-5, 69730-0, 11504-8, 28570-0) added to `loinc.yaml` with en + ja
- ✅ 32 new unit tests in `tests/unit/test_clinical_documents.py` (prompts, cache, providers, extractor, document generator E2E, FHIR DocumentReference builder)
- ✅ Total test count: 141 passing
- ✅ Documentation: README.md, DESIGN.md (AD-36 to AD-41 + Part 7/8), TODO.md, new docs/clinical_documents.md, new docs/bedrock_setup.md

## Recent completions (2026-04-06 to 2026-04-08)

- ✅ codes module with 8 international code systems (577 codes total, EN required)
- ✅ FHIR R4 Bulk Data Export NDJSON format (replacing per-encounter Bundle)
- ✅ Snapshot date semantics with in-progress encounters
- ✅ Hospital config-driven department/ward/bed layout
- ✅ Bed Location resources with partOf hierarchy
- ✅ PractitionerRole.location assignment
- ✅ Staff roster scaled to hospital config (ward-aware nurse distribution)
- ✅ All Resource.id globally unique (0 violations across 12 types)
- ✅ UCUM-compliant units with system+code in valueQuantity
- ✅ NEWS2-compatible vitals (AVPU consciousness, supplemental O2)
- ✅ Realistic vital sign measurement patterns (continuous monitoring, event-driven rechecks, per-field offsets)
- ✅ Outpatient vital subset by visit type (HTN visit = BP+HR only)
- ✅ Procedure expansion (15 bedside procedures, disease-driven rules)
- ✅ Condition staging (CKD G/NYHA/GOLD/HbA1c/CCS/asthma severity)
- ✅ Encounter.length, reasonReference, hospitalization, location
- ✅ Patient.identifier (MRN), maritalStatus, communication, contact, telecom
- ✅ MedicationRequest dosageInstruction (timing, route, doseAndRate)
- ✅ MedicationAdministration structured dose + reasonReference
- ✅ Observation.interpretation (lab + vital), referenceRange (vital)
- ✅ Practitioner gender, telecom, qualification, prefix
- ✅ Module READMEs for all 17 modules + main README (EN/JA)
- ✅ CLAUDE.md updated with new architecture rules

## Future design improvements (tracked, not scheduled)

| # | Item | Priority | Notes |
|---|---|---|---|
| F-1 | encounter YAML-ization (workflow as data) | Medium | v0.2 |
| F-2 | clinical_course absorption into physiology | Low | Current separation works well |
| F-3 | DI/Registry pattern for module wiring | Low | Manual wiring is fine for now |
| F-4 | More languages in codes module (de, zh, ko, fr) | Low | Just add language keys to YAML entries |
| F-5 | UCUM module in codes/ for unit display translation | Low | Currently units are bare strings |
