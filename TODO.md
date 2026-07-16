# clinosim — TODO / Roadmap

This file is the **shared, contributor-facing** roadmap and backlog for
clinosim:

- **Architecture Decisions** — the numbered ADs the codebase enforces
  (`AD-1`, `AD-2`, …). New PRs cite the AD they extend or preserve.
- **Implementation Status** — completed milestones (v0.1-alpha … v0.2 …).
- **Open Design Questions** — decisions still open for discussion.
- **Roadmap** — planned work per version (v0.2 → v1.0).
- **Recent completions** — merged milestones with dates.
- **Future design improvements** — tracked but not yet scheduled.
- **Topical backlogs** — per-chain deferred items and OOS notes.

Past-session commit-by-commit history lives in `git log` and the GitHub
Releases page — not here. Personal per-session continuation notes are
kept out of the shared repo.

For contribution workflow (Issue → PR → CI → squash merge) see
[`CLAUDE.md § Development workflow`](CLAUDE.md).

---

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
| **AD-51** | 2026-06-23 | **Panel-children RNG isolation (one specimen, one RNG)**: every lab `Order` produced by panel expansion (`_run_daily_loop`'s Pass 2) draws specimen-rejection / hemolysis / staff-assignment / result-timing from a per-parent sub-RNG seeded by `panel_specimen_seed(parent_order_id)` (in `clinosim/simulator/seeding.py`), not from the patient-scoped master RNG. Two consequences: (a) editing `lab_panels.yaml` (e.g. registering CBC or BMP) cannot cascade into unrelated patients' cohorts — the master stream stays exactly the same length regardless of which panels are registered (AD-16 compliance). (b) Specimen rejection becomes per-specimen (one parent → all-or-nothing on children) rather than per-analyte, which is clinically correct because a panel order is one tube. PR #74. Tested by `tests/integration/test_panel_expansion_cbc_bmp.py::test_panel_children_cancellation_is_per_specimen` and `tests/unit/test_seeding.py::TestPanelSpecimenSeed::test_formula_is_pinned`. |

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
| 7 | Code coverage expansion: more LOINC/RxNorm/CPT codes | `codes` | Continuous (349 ICD-10-CM, 306 ICD-10, 83 LOINC, 68 RxNorm, 31 CPT currently) |

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
| 23 | Narrative/discharge text referencing HbA1c + glycemic control | `enrichment`, `output` | Open (HbA1c now modeled via `glycemic_control` axis; narratives don't yet mention it) |
| 24 | Non-diabetic HbA1c patient spread + prediabetes cohort | `physiology`, `population` | Open (non-DM HbA1c currently ~5.1–5.3, low-variance) |
| 25 | Remove dead `ChronicCondition.controlled` field (superseded by `glycemic_control`) | `types`, `patient` | Open (kept to preserve RNG stream; clean up in a determinism-aware pass) |

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
- [x] **Encounter scenarios carry acute physiology.** ED encounter YAMLs gained an optional
  `initial_state_impact` (per severity, same schema as disease protocols) + `acid_base_type`;
  `emergency.py` applies it via `apply_disease_onset` after `initialize_state`, so BOTH labs
  and vitals reflect the acute illness, not just comorbidity baseline. Populated for the
  conditions with a clear physiological signature: infections (UTI/viral URI → WBC/CRP/temp),
  dehydration (gastroenteritis/food poisoning → volume↓ → BUN↑, BP↓/HR↑), hyperventilation
  (asthma/panic → respiratory alkalosis), local→systemic (animal bite/minor burn).
  Trivial presentations (screening, suture removal) carry no impact (no-op). Audit (pop 30k):
  UTI WBC median 10,177 (vs ~7,500 baseline), gastroenteritis dehydration, panic pCO2 < 38.
  Data-driven (user principle: lab changes from scenario/profile). 4 unit tests.
- [x] **ABG panel expansion + pO2 done.** `observation/reference_data/lab_panels.yaml`
  (data-driven) maps `ABG` → pH/pCO2/pO2/HCO3; panel orders are expanded into component
  lab orders (parent marked resulted) so each resolves via the scalar path. physiology
  derives pO2 (inflammation-proxied hypoxemia). LOINC/JLAC10 codes added. Respiratory
  cohort now gets blood-gas results (was none) — verified COPD pH/pCO2/pO2/HCO3 resolve.
- [x] **Unify vitals generation.** ED (`emergency.py`) + outpatient (`outpatient.py`) now
  derive vitals from the comorbidity-adjusted `PhysiologicalState` via the same path as
  inpatient. New shared helper `physiology.derive_observed_vitals(state, baseline, ts, rng)`
  = `derive_vital_signs` + measurement noise; inpatient `_make_raw` delegates to it (output
  unchanged — identical RNG draws). ED temp/SpO2/HR now track physiology (e.g. febrile up to
  39.1 °C, hypoxia to 87 %, shock SBP to 66) instead of a fixed normal template; outpatient
  keeps its measured-subset (`fields`) logic. Determinism preserved (same draw count/order);
  unit/integration/e2e green. **Acute-presentation injection** (folding ED scenario severity
  into the state so labs+vitals reflect the acute illness, not just comorbidity baseline)
  deferred — see the `initial_state_impact` item above.
- [x] FHIR code-mapping cleanup (from CIF/FHIR eval): US LOINC for lipids/TSH/ESR
  (+ loinc displays), outpatient lipid/ESR baselines (was 1.0 garbage), ECG/non-analyte
  guard in ED/outpatient (was fabricated empty-code lab). US empty-code labs 328→0.
- [x] **JP JLAC10 codes verified & corrected.** Added Troponin_I (5C094), CK_MB (3B015),
  LDL (3F077), HDL (3F070), TG (3F015), TC (3F050), TSH (4A055), ESR (2Z010) — all verified
  against the official **JSLM JLAC10 master v137 (2026-06)** (`jslm.org/committees/code/`),
  lipids cross-checked vs jpfhir.jp JP-CLINS/eCheckup. **Audit also exposed ~13 pre-existing
  fabricated/mismapped codes** in `jlac10.yaml` (Hb/Hct/BUN/Na/K/Cl/Ca/T_Bil/LDH/PCT/BNP/
  Lactate were off, blood gas pH/pCO2/pO2/HCO3 pointed at the 6A0xx **microbiology** range) —
  all corrected to the master codes. Source cited in both files; integrity guard test added
  (`test_codes_jlac10.py`, 28 cases). JP FHIR audit: 31 correct JLAC10 codes + 和名 emitted.
- [x] **US LOINC verified.** All 38 US-mapped LOINC codes confirmed vs NLM Clinical Tables
  LOINC API (no fabrication). Fixed 4 duplicate YAML keys + normalized verbose display
  (PR #10). Cross-system dup-key guard added (`test_codes_integrity.py`).
- [x] **Authoritative-source comments** added to every code-data file (icd-10-cm, icd-10,
  rxnorm, cpt, k-codes, yj + earlier jlac10/loinc/snomed) and locale code_mapping files.
- [x] **ICD diagnosis-code review (2026-06 finding) — FIXED.** `code_mapping_diagnosis.yaml`
  was dead config (`load_code_mapping` never called for "diagnosis") so US emitted
  non-billable 3-char category codes (I50, I21, ...) and WHO-only codes (F00). Now wired into
  the FHIR adapter (`_build_conditions`, both primary + chronic dx via `_map_diagnosis_code`).
  US translates every internal chronic/history base code + non-billable primary to a billable
  ICD-10-CM leaf (chronic→unspecified leaf; past-acute-as-chronic→"history of/old" e.g.
  I21→I25.2; primary specificity/7th-char e.g. R05→R05.9, S72.00→S72.009A, T07→T07.XXXA).
  All targets verified vs NLM ICD-10-CM API (no fabrication) + added to `icd-10-cm.yaml`.
  Audit (US 10k): 91/91 distinct Condition codes billable, 0 non-billable.
- [x] **Used-but-missing diagnosis codes — FIXED (PR #19).** Disease/encounter scenarios
  referenced 19 ICD codes absent from code-data (display fell back to approximate prefix
  match). Registered after NLM/WHO verification; fixed miscode K57.11 (small-intestine) →
  K57.31 (large-intestine diverticular bleeding). Coverage invariant added
  (`test_diagnosis_code_coverage.py`).
- [x] **JP diagnosis output → true WHO ICD-10 granularity — FIXED (PR #20).** JP previously
  emitted ICD-10-CM-granularity codes (7th-char `S06.0X0A`, 5-char `A41.01`, `Z00.00`) under
  the WHO `icd-10` system URI, resolving only via cm-fallback. `code_mapping_diagnosis/jp.yaml`
  now folds every internal code to WHO 3-4 char (+110 WHO codes verified vs icd.who.int/
  browse10/2019; R65 axis differs in WHO so severe-sepsis R65.20/.21→R65.1, SIRS R65.10→R65.2).
  `icd-10.yaml` is now 100% WHO format. Structural guards: `test_jp_never_emits_cm_granular_code`,
  `test_icd10_who_file_has_no_cm_granular_codes`. Generation: 0 CM-granular codes emitted.
- [x] **engine.py differential codes registered — FIXED (PR #21).** The `DIFFERENTIALS` table +
  LR tuples in `modules/diagnosis/engine.py` are a third emittable Condition-code source; ~65
  codes were unregistered (prefix-fallback). Added after NLM/WHO verification (+58 CM, +58 WHO,
  +35 us_map, +2 jp_map incl. K56.9→K56.7). Coverage test now ranges over `ALL_EMITTABLE`
  (disease + encounter + engine.py). Generation (US 51k + JP 28k Conditions): 0 prefix-fallback.
- [ ] **engine.py diagnosis tables → YAML (data-driven, follow-up #2).** `DIFFERENTIALS`,
  `LR_TABLE`, `DIAGNOSIS_PROGRESSION` + display `name`s are hard-coded in Python (violates the
  YAML-driven AD). Move to `reference_data` YAML and resolve `name` via `clinosim.codes` lookup.
  Output-logic adjacent → must preserve determinism/golden output.
- [ ] **RxNorm / CPT / SNOMED / YJ / K-code** — authoritative-source comments added but codes
  not yet machine-verified (RxNorm verifiable via NLM RxNav API; others need licensed masters).
- [ ] **ECG as a proper diagnostic** (currently skipped from labs; model as Procedure/
  diagnostic order so the "ECG was done" fact is recorded).
- [x] **Acid-base model** (eval finding): pH/HCO3/pCO2 derived from a single `ph_status`
  axis couldn't distinguish metabolic vs respiratory acidosis or show correct compensation.
  **Fixed** with a two-axis model: `ph_status` (disturbance magnitude) + new
  `PhysiologicalState.respiratory_fraction` (0 = metabolic → HCO3, 1 = respiratory → pCO2).
  Blood gas now follows Henderson-Hasselbalch with partial compensation (Winter's for
  metabolic acidosis → Kussmaul low pCO2; ~0.35 mEq/mmHg renal compensation for respiratory
  acidosis → raised HCO3). Axis is **scenario/profile-driven** (same pattern as
  `causes_myocardial_injury`): disease `acid_base_type` field (`metabolic` default,
  `respiratory` for COPD/asthma) + chronic J44/J45 in `initialize_state`. Audited (pop 30k):
  DKA pCO2 34.8 (Kussmaul ✓), COPD HCO3 26.7 / pCO2 47.5 (compensation ✓). 6 unit tests.
- [ ] ED non-cardiac troponin now reflects cardiac comorbidity (median ~0.095, can exceed
  the 0.04 cutoff) — decide comorbidity-baseline vs rule-out-negative semantics.

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
  - [x] JP JLAC10 codes for Troponin_I (5C094) / CK_MB (3B015) verified vs JSLM master v137.
    Serial-troponin intra-day trend still open.
- [ ] **`DiagnosticReport` grouping** — `output` adapter (+ `types/output`): group lab Observations into panels (CBC/BMP/LFT). Structural fidelity, no new clinical data.
- [x] **Nursing flowsheets** — `observation/nursing.py` (純粋関数 NEWS2/GCS/Braden/Morse) + `nursing_enricher.py` (AD-56 Base post_records, 専用 hashlib サブシード → メインストリーム不変)。CIF: `VitalSignRecord.news2_score`/`gcs_score` + `NursingRiskAssessment` (Braden 6 サブスケール + Morse)。FHIR `category=survey` Observation 7 件 (NLM 照合済み LOINC: GCS 9269-2, Braden 38227-5, Morse 59460-6, Barthel 96761-2, 輸液 9108-2/9192-6/9262-7; NEWS2 は権威 LOINC なし → `code.text` のみ)。CSV: `nursing_risk.csv` 新規 + `vital_signs.csv` に NEWS2/GCS 列追加。thresholds はすべて `reference_data/nursing_scores.yaml` データ駆動。
- [x] **Immunization history** — `modules/immunization/engine.py` (純粋関数 `load_schedule`/`generate_immunizations`) + `enricher.py` (AD-56 Base post_records, 専用 hashlib サブシード 0x494D → メインストリーム不変, AD-16)。CVX コード 10 件を CDC IIS で照合済み (`codes/data/cvx.yaml`、FHIR URI `http://hl7.org/fhir/sid/cvx`)。US adult schedule 5 ワクチン (Influenza/COVID-19/PPSV23/Tdap/Zoster-RZV) + JP 3 ワクチン (Influenza/COVID-19/PPSV23)。各ワクチンは `available_from` + `coverage_by_age_sex` (年齢帯×性別 接種率) 付き。AS-OF = snapshot_date または最新入院日 (AD-32)。CIF: `ImmunizationRecord` (vaccine_cvx/occurrence_date/status/primary_source)。FHIR R4 `Immunization` (US英語/JP日本語 display)。CSV: `immunizations.csv`。接種率出典: CDC FluVaxView/MMWR (US), MHLW 接種率統計 (JP) — 概数モデリングパラメータ。
- [x] **Family history** — `modules/family_history/` (engine 純粋関数 + `reference_data/family_history.yaml` 遺伝倍率/続柄) + `locale/{us,jp}/family_history_prevalence.yaml` (国別有病率)。AD-56 post_records enricher (person_id サブシード 0x4648 → メインストリーム不変, AD-16)。本人 chronic_conditions × locale 有病率 × 遺伝倍率で第1度近親 (母 MTH/父 FTH/兄弟姉妹 NSIB) の疾患を合成。心血管代謝系 (E11/I10/I25/I63/I64/E78) + 主要がん (C50/C18/C34/C61、性別制限)。FHIR `FamilyMemberHistory` (v3-RoleCode + ICD)、CSV `family_history.csv`。`CIFPatientRecord.family_history` typed field。PR #63。
- [x] **Code status / resuscitation status** — `modules/code_status/` + `locale/{us,jp}/code_status_rates.yaml`。AD-56 post_records enricher (encounter_id サブシード 0x4353 → 主乱数列不変)。4 段階 (Full Code/DNR/DNR+DNI/Comfort)、入院=全例 + ED=`deceased`/`icu_transferred` のみ + 外来=なし。年齢×acuity (terminal>icu>routine) で確率割当。FHIR survey `Observation` (SNOMED resuscitation-status)、CSV `code_status.csv`。`CIFPatientRecord.code_status`。SNOMED は環境制約で `# TODO: verify`。PR #64。
- [x] **Extended SDOH (smoking/alcohol/JP 要介護度)** — 喫煙 (US Core Smoking Status, LOINC 72166-2 + SNOMED) と飲酒 (LOINC 11331-6) を social-history `Observation` 化 (既存属性を読むだけ)。JP **要介護度** は新規 `modules/care_level/` (JP-only post_records enricher, person_id サブシード 0x434C, 年齢駆動) + `jp-care-level` ローカルコード体系 (MHLW 介護保険 区分)。新 `modules/output/_fhir_sdoh.py` (3 builder)、CSV `care_level.csv` + `alcohol_use` 列。`CIFPatientRecord.care_level`。alcohol SNOMED は `# TODO: verify`。PR #65。

#### Modules — specialized / optional (opt-in, one theme each)

- [ ] **`modules/billing/`** — country-pluggable レセプト/claims (JP **DPC** per-diem bundling / US `Claim`+`ExplanationOfBenefit`). Mirrors `identity`: provider registry, deps `types`/`codes`/`locale`, reads CIF, FHIR in `output`, `--billing` flag. **Supersedes the v0.5 "DPC/DRG cost data" item.**
- [ ] **`modules/device/`** — device placement (central line / urinary catheter / ventilator / telemetry) + **HAI risk** (CLABSI/CAUTI/VAP) from dwell time; deps `procedure`/`types`; emit `Device`/`DeviceUseStatement` (+ HAI `Condition`). Flag-gated.
- [ ] **`modules/care_coordination/`** — `CarePlan`/`CareTeam`/`Goal` for USCDI/Synthea interoperability completeness; deps `types`; reads CIF; flag-gated.

Suggested order: ~~microbiology+markers~~ ✅ → ~~nursing flowsheets~~ ✅ → ~~immunization~~ ✅ → ~~family-history~~ ✅ → ~~code-status~~ ✅ → ~~extended SDOH (要介護度)~~ ✅ → `DiagnosticReport` grouping → `modules/billing` (JP DPC) → `modules/device` → `modules/care_coordination`. **AD-55 Base roadmap complete** (only `DiagnosticReport` panel grouping remains, structural-only).

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

---

## PR1 ServiceRequest follow-ups (Tier 1 backlog)

### PR2 — ServiceRequest for PROCEDURE
- Procedure orders currently flow through ProcedureRecord (no Order intermediate).
- Path: extend `_fhir_procedures.py` builder to emit ServiceRequest preceding each Procedure,
  link via ProcedureRecord.procedure_id.

### PR3 — ServiceRequest for REFERRAL / CONSULTATION
- New CIF data required (no current source).
- Path: extend disease YAML with `referrals:` field, generate Orders with
  OrderType.REFERRAL (or CONSULTATION), new SR category (SNOMED 308540006 + HL7 v2-0074 REF).

### Tier 1 #2 — ServiceRequest for IMAGING [DONE 2026-06-30]
- ~~Bundled with full Imaging chain (ImagingStudy + DiagnosticReport(rad) + Endpoint stub).~~
- **COMPLETED**: Imaging chain α-min delivered (AD-62). ImagingStudy + Endpoint + radiology DR +
  imaging SR. US p=10k + JP p=5k production cohort generated and audited. DQR: 4 axes PASS.

### Tier 1 #3 — Document Density α-min-1 [DONE 2026-07-01]
- ~~Stage 1 default template-based document emission (DocumentReference / Composition / ClinicalImpression) + AllergyIntolerance schema upgrade.~~
- **COMPLETED**: Document Density chain α-min-1 delivered (AD-63). DocumentReference 0 → 23,760
  (US) / 3,909 (JP); Composition 0 → 9,275 / 474; ClinicalImpression 0 → 23,760 / 3,909.
  AllergyIntolerance 8-field SNOMED upgrade. 2 always-on POST_ENCOUNTER modules (`allergy` (POST_POPULATION) + `document` (POST_ENCOUNTER)).
  3 new FHIR builders. silent_no_op 17/17 PASS. US p=10k + JP p=5k cohorts verified.
  DQR: `docs/reviews/2026-07-01-tier1-3-document-density-alpha-min-1-dqr.md`.
  Task 15 (generator migration / cleanup) completed on same branch.

### Tier 1 #3 — Document Density α-min-2 [DONE 2026-07-01]
- ~~Nursing domain narratives (admission nursing assessment / nursing shift note / discharge nursing summary) + CareTeam + triage infrastructure + 46 encounter YAML narrative extensions.~~
- **COMPLETED**: Document Density chain α-min-2 delivered (AD-64). CareTeam 0 → 158,811 US /
  16,046 JP (1:1 with Encounter, ★ GAP CLOSED). DocumentReference +22,798 (nursing shift daily
  notes). Composition +8,671 (nursing admission + nursing discharge). 3 new always-on POST_ENCOUNTER
  Modules (`triage` order=93 + `nursing_assignment` order=94 + extended `document` order=95).
  CareTeam FHIR builder. 6 new DocumentType specs (78390-2/34746-8/34745-0/34131-3/34878-9/54094-8).
  silent_no_op 25/25 PASS. clinical axis PASS (CareTeam 1:1 with Encounter). 27 integration tests.
  DQR: `docs/reviews/2026-07-01-tier1-3-document-density-alpha-min-2-dqr.md`.
  **Known gap → RESOLVED (α-min-2 Task 14 fix, verified 2026-07-02)**: outpatient.py +
  emergency.py DO invoke `run_stage(POST_ENCOUNTER)` (both carry the "α-min-2 Task 14 fix"
  block). Production-verified at US p=500 seed=42: OUTPATIENT_SOAP 1,841 Composition +
  ED_NOTE 210 Composition + ED_TRIAGE_NOTE 210 DocumentReference. The α-min-3 section
  below no longer contains this item.

### β-JP-1: LLMNarrativePass 実装(AD-65 base 上に drop-in)

- `LLMNarrativePass(NarrativePass)` subclass 実装 — AD-65 `NarrativePass` base の上に Bedrock/Ollama LLM integration を layer
- Bedrock Sonnet-4 provider + Ollama qwen:7b provider 対応 + localhost fallback
- Bedrock prompt cache(5 分 TTL)発火の実測 verify + cost reduction report
- `facts_used` gate 有効化 — template facts vs LLM-rephrased facts の audit diff
- `docStatus` 4 状態化:
  - `"final"` (template完全生成)
  - `"final"` (LLM完全生成)
  - `"preliminary"` (LLM fallback to template)
  - `"amended"` (human reviewed)
- `Composition.author` extension で AI-assisted attribution 明示
- Section-level LLM replacement 発火の条件化 (section 例外リスト + LLM-capable section list by doctype)
- `clinosim narrate --patient-filter POP-000001` 対応 — single-patient iterative loop for testing

#### β-JP-1 chain 1a adv-1 deferred (2026-07-03)

Findings triaged out of the chain-1a adv-1 fix PR (scope discipline rule):

- **Small-p roster export gap**: p=100 cohort audit shows 5 dangling nurse
  Practitioner references in CareTeam. PROVEN pre-existing (same refs dangle
  in the α-min-2-era p=100 cohort; US p=10k / JP p=5k production audits
  pass). Needs a roster-export-at-small-p fix decision (export full staff
  roster regardless of cohort size vs. clamp assignments to exported staff).
- **outpatient.py chronic-followup severity**: the chronic-followup path
  leaves `encounter.severity=""` (no value in scope). Decide a severity
  source (condition state? stable default?) and wire it.
- **`narrative/context.py:build_narrative_context` delete-or-unify**: the
  parallel ctx factory has ZERO production callers and diverges from
  `NarrativePass._build_context` (e.g. no `discharge_medications` /
  MAR-only split from adv-1 I-1). Delete it or unify both on a single
  factory before β-JP-1 builds on the ctx contract.
- **Remaining encounter-template placeholders** (chain 1b T4 shipped the
  vitals subset — `{sbp}` / `{dbp}` / `{hr}` / `{temp}` / `{spo2}` / `{rr}`
  now resolve from `ctx.vitals`): everything else in the encounter YAML
  inventory still triggers the whole-section generic fallback (adv-1 I-2
  follow-up; `_KNOWN_PLACEHOLDERS` / `_VITAL_PLACEHOLDER_FIELDS` in
  `template_generator.py` are the extension points). Remaining inventory
  (grep over `modules/encounter/reference_data/*.yaml`, 2026-07-03):
  high-frequency `{disposition_display_*}` (28) / `{lab_summary_*}` (27) /
  `{imaging_summary_*}` (26) / `{primary_dx_display_*}` (17) /
  `{workup_summary_*}` (16) / `{follow_up_*}` (16); low-frequency
  `{weight}` `{severity_desc_*}` `{last_lab_date}` `{duration_days}`
  `{cxr_result_*}` + ~25 one-off condition-specific tokens
  (`{ua_result_*}`, `{troponin_result_*}`, `{ottawa_result_*}`, ...).
- **ctx.medications MAR dedupe for LLM constraint lists** (adv-1 M-3): MAR
  entries repeat per administration; LLM prompt constraint lists built from
  `ctx.medications` may want per-drug dedupe (+ merge with discharge rx
  where the prompt needs "all meds this stay").
- **`KNOWN_JA_ONLY_FALLBACK_SECTIONS` blanket-name exemption** (adv-1 M-2):
  the ja-leak audit gate exempts whole section names; a section that later
  gains proper en templates keeps its exemption silently. Future: tag-based
  matching (exempt only sections actually rendered via `ja_only_fallback`
  facts_used tags).

#### β-JP-1 chain 1b adv-1 deferred (2026-07-03)

Findings triaged out of the chain-1b adv-1 fix PR (scope discipline rule):

- **MockProvider call_count couples llm-mock goldens to global walk order**
  (adv-1 M-1): the mock stub text embeds a per-run `call_count`, so ANY
  change to the (doc_type, language, patient) walk order — or adding a doc
  type — shifts every subsequent mock golden byte. Consider
  order-insensitive stubs keyed on a prompt hash (e.g.
  `[Mock:{sha1(prompt)[:8]}]`) so goldens only change when the prompt for
  THAT document changes.
- **Vitals placeholder per-field nearest-reading can mix timepoints**
  (adv-1 M-4): `_resolve_vital_placeholders` picks the nearest non-null
  reading PER placeholder, so one sentence can combine `{sbp}` from day 2
  with `{hr}` from day 3 when readings are sparse. Prefer single-reading
  resolution: pick the best reading for the stub's day once, resolve all
  placeholders from it, and fall back whole-section if it lacks any wanted
  field.
- **ja-leak check gaps** (adv-1 M-5, known data gap): the semantic-check
  ja-leak axis is disabled for mixed-language cohorts, and free-text
  (non-composition) document bodies are not checked for language leaks at
  all.
- **I-1 residual — export-time partial-version guard**: `export-fhir` on a
  partial "current" version still emits with a per-doc WARN only (narrate
  now guards set-current and merge writes; manifest carries
  `partial: true`). Consider a version-level guard at export time: read
  `manifest.json.partial` and require an explicit flag (or hard-fail) when
  exporting a partial narrative version.

### Post-AD-65 fixture library (α-min-2c) — ✅ COMPLETED (session 30, PR #132)

Shipped in α-min-2c chain (AD-66):
- `tests/fixtures/patient_profiles/` with 6 canonical disease-based inpatient/ICU profiles
- `PatientProfile` Pydantic type in `clinosim/types/config.py`
- `test-disease --patient-profile` CLI + `regenerate-goldens` CLI
- `pytest -m regression` suite (opt-in, marker=regression)
- Determinism at seed 42 verified for narrative output

### Post-α-min-2c fixture library extensions (β-JP-1 or later)

- Encounter-based profiles (ED / outpatient) — requires symmetric
  `test-encounter --patient-profile` extension + `PatientProfile.condition_id`
  field, or unified `test-profile` verb
- Additional disease-based profiles beyond α-min-2c 6 (as β-JP-1 LLM
  regression scope grows)
- LLM semantic diff mechanism — byte-diff insufficient for LLM output
  (fuzzy match, tolerance thresholds, expected phrase substrings)
- Clinical review loop — per-profile physician + nurse validation
- CI GitHub Actions workflow for automated regression at PR time
- LLM parallel goldens (`<profile>.llm-<model>.golden.json`) alongside
  `<profile>.golden.json`
- Re-add `PatientProfile.chronic_medications` / `time_range` WITH actual
  consumption (removed in adv-1 F-1 as unwired fields — they were declared but
  nothing consumed them, defeating the extra=forbid typo defense)

### Imaging chain OOS formal entries (Tier 1 #2 PR1 scope-out)

The following FHIR fields / features were **explicitly out of scope** for the α-min imaging chain
(per spec Section 11). Each is a valid future extension:

#### ImagingStudy field-level OOS

- **ImagingStudy.numberOfSeries / numberOfInstances**: field values deferred; always-present
  `series[]` array is the canonical count source at α-min.
- **ImagingStudy.series[].instance[]**: DICOM SOP Instance UID expansion. Each series contains
  one conceptual instance at α-min; real PACS integration will expand to per-slice.
- **ImagingStudy.series[].number**: DICOM series number (integer) — ordinal within study.
- **ImagingStudy.interpreter**: radiologist practitioner reference. Deferred to Phase 2 when
  radiology staff roster is added.
- **ImagingStudy.referrer**: ordering clinician reference — already available as
  `Order.ordered_by`; FHIR wire deferred.
- **ImagingStudy.availability**: ONLINE / OFFLINE / NEARLINE / UNAVAILABLE. Deferred; Endpoint
  presence implies ONLINE semantics.
- **ImagingStudy.encounter**: explicit Encounter reference on the ImagingStudy. Deferred; can
  be derived from basedOn SR's encounter.
- **ImagingStudy.location**: imaging suite Location resource. Deferred to Location hierarchy PR.
- **ImagingStudy.reason**: clinical indication reference (Condition). Deferred; reason text is
  present in the imaging SR.
- **ImagingStudy.procedureCode**: SNOMED CT procedure code for the imaging study type. Tier 2.
- **ImagingStudy.series[].performer**: technician who acquired the series. Tier 2 (radiology
  staff roster).
- **ImagingStudy.series[].laterality**: body laterality SNOMED code (right/left/bilateral).
  Tier 2; body site only at α-min.
- **ImagingStudy.note**: free-text annotation at study level. Tier 3.

#### Endpoint field-level OOS

- **Endpoint.connectionType**: hardcoded to DICOM WADO-RS at α-min. Future: DICOMweb STOW-RS
  for push-based upload integration.
- **Endpoint.payloadMimeType**: DICOM media type list deferred. Tier 2.
- **Endpoint.header**: HTTP auth headers for PACS auth. Out of scope for placeholder URL.

#### DiagnosticReport (radiology) field-level OOS

- **DiagnosticReport.resultsInterpreter**: radiologist practitioner. Tied to interpreter on
  ImagingStudy — both deferred to Phase 2 staff roster.
- **DiagnosticReport.presentedForm**: base64-encoded PDF or HTML for structured radiology
  report export. Deferred; text.div + conclusion covers α-min needs.
- **DiagnosticReport.media**: key images as Attachment. Deferred until image-gen AI integration.
- **DiagnosticReport.effectiveDateTime**: date of imaging procedure. Wire from
  `ImagingStudyRecord.study_datetime` — deferred to pass 2.

#### Disease YAML imaging coverage OOS

- **aspiration_pneumonia.yaml**: imaging_orders exists for CR (Chest_Xray) but no YAML
  for aspiration pneumonia → imaging chain skips it (legacy order path). Tier 2.
- Additional diseases (COPD / sepsis / hip fracture / etc.): imaging_orders not yet in YAML.
  Bundle with legacy migration sweep PR (see "Legacy IMAGING order emission sites" item below).

### imaging chain JP language axis
- **ModuleAuditSpec** lacks `jp_language_checks` field. `clinosim/modules/imaging/audit.py` deferred 6 JP language audit checks (modality / bodySite / DR.code / conclusion / text.div / SR.code displays in ja for JP cohort). When framework gains the field, wire these checks. Spec Section 9.4 brief includes the full list.

### Legacy IMAGING order emission sites need migration to Task 3 path
- **Issue:** `clinosim/simulator/inpatient.py` lines 852, 1737, 1781 + `clinosim/simulator/emergency.py` line 183 emit Order(OrderType.IMAGING) without `imaging_modality` / `imaging_body_site_code`.
- **Current workaround:** Task 4 imaging_enricher silently skips these via filter (test_enricher_skips_legacy_orders_without_imaging_metadata) to avoid breakage.
- **Fix path:** Migrate these emission sites to use `place_imaging_orders` so they emit ImagingStudy + radiology DiagnosticReport + Endpoint resources through the normal Task 3/4 pipeline.
- **Scope:** Out of scope for Tier 1 #2 PR1 (imaging chain α-min), track for follow-up sweep PR.
- **TODO #1 (whole-branch review, 2026-06-30):** Legacy `bacterial_pneumonia.yaml:152-153` style
  entries (`imaging: [Chest_Xray_PA_Lateral]`) still emit `Order(IMAGING)` without metadata, causing
  ~17,691 orphan SRs in US p=10k cohort (98% of SR(RAD)). Migration plan:
  (a) Extend imaging_chain audit module to flag orphan ratio > N% as WARN.
  (b) Log a warning in enricher when IMAGING order lacks metadata (currently silent skip).
  (c) Disease YAML migration sweep: replace `imaging: [name]` with `imaging_orders: [...]` for all
  30 disease YAMLs. Sites: `bacterial_pneumonia.yaml` + all diseases with legacy `imaging:` field.

### TODO #2 (whole-branch review, 2026-06-30): JP language audit gate
- **ModuleAuditSpec** lacks `jp_language_checks` field. `clinosim/modules/imaging/audit.py` deferred
  6 JP language audit checks (modality / bodySite / DR.code / conclusion / text.div / SR.code
  displays in ja for JP cohort). When framework gains the field, wire these checks.
  Spec Section 9.4 brief includes the full list. Extension proposal:
  (a) Add `jp_language_checks: list[str]` field to `ModuleAuditSpec`.
  (b) Wire into JP language axis dispatcher.
  (c) Implement imaging_chain JP checks + add to other always-on Modules.

### TODO #3 (whole-branch review, 2026-06-30): Adversarial fan-out chain deferred
- Per memory `feedback_iterative_adversarial_review`, PR-class precedent calls for post-impl
  5-lens parallel adversarial fan-out review. Imaging chain ran per-task reviews + 1 final
  whole-branch review. Adversarial fan-out (5 reviewers × silent-no-op / data unification /
  FHIR-JP Core / AD-16 + scale / spec adherence) deferred to post-merge per chain length +
  user roadmap re-evaluation timing (memory `project_ehr_sample_dataset_roadmap`).

### TODO #4 (whole-branch review, 2026-06-30): Spec deviations to document
- Update spec `docs/superpowers/specs/2026-06-30-tier1-imaging-chain-design.md`:
  (a) `ENRICHER_SEED_OFFSETS["imaging"] = 0x4947 ("IG")` — actual vs spec's 0x494D ("IM").
  (b) `Order.imaging_spec_meta: dict[str, Any]` — 4th imaging field not in original spec.
  (c) `RadiologyReport.findings_text_ja` / `impression_text_ja` — lang-keyed fields.

### TODO #5 (whole-branch review, 2026-06-30): `views=[]` fallback edge in place_imaging_orders
- `place_imaging_orders` increments `sequence_counter["I"]` even when views=[] and
  `default_views_by_body_site` lookup fails for a modality+body_site combo. Future modality
  additions could trip silently. Add `_validate_modalities` Layer-5 invariant: every
  (modality, supported body_site) pair has a `default_views_by_body_site` entry.

### TODO #6 (whole-branch review, 2026-06-30): Integration test population size
- `run_generate("US", 100, 42, ...)` integration tests skip when no studies emit. n=100 is
  fragile — raise to 200 where DQR shows enough disease distribution for stable coverage.
  Files: `tests/integration/test_imaging_chain.py`, `test_imaging_basedon_coverage.py`, etc.

### TODO #7 (whole-branch review, 2026-06-30): DQR phrasing "1/4 PASS" is misleading
- DQR Axis 4 summary had "1/4 PASS" when structural/jp_language axes are N/A (not applicable).
  Replace with explicit "clinical PASS + silent_no_op PASS (structural/jp_language N/A — no
  module-specific gates)" to clarify the 4-axis accounting. Fixed to "2/4 PASS" post I-3 fix.

### Out-of-scope permanent — ServiceRequest for MEDICATION
- FHIR `MedicationRequest` is the correct resource; ServiceRequest not used.

### Tier 2 — ServiceRequest for HAI microbiology culture
- MicrobiologyResult is a separate type from Order; bundle with general microbiology ordering
  refactor.
- Note: PR1 audit gate (`clinical.py:_check_lab_obs_basedon`) excludes mb-org-* / mb-sus-*
  Observations via MB_ORG_ID_PREFIX / MB_SUS_ID_PREFIX. Re-include when microbiology SR lands.

### Tier 1 #6 — ServiceRequest.requisition (Identifier) for cross-resource grouping
- Defer until Appointment/Schedule introduces multi-SR batch requisition.

### Tier 1 #5 — Lab requisition workflow narrative
- Defer to DocumentReference Stage 2.

### Tier 2 — ServiceRequest.performer (lab technician/department)
- Bundle with CareTeam.

### Tier 2 — Filler order number `FILL` identifier
- Lab interface specifics; placer alone sufficient for PR1.

### M-6 — Disease YAML `code_loinc:` field backfill
- Many disease YAMLs lack `code_loinc:` on lab entries → `order_code` ends up as internal
  test name ("CRP", "WBC") or empty string → JP cohort SR.code.coding[].display falls back
  to English. Affects ~105 of 42k JP SRs (~0.25%).
- Backfill `code_loinc:` field on every lab entry in
  `clinosim/modules/disease/reference_data/*.yaml`. Touches ~30 disease YAMLs; source LOINC
  codes via NLM API per CLAUDE.md authoritative-source rule.

### M-7 — Order status not updated on last simulation day at snapshot boundary
Some stand-alone Orders retain `OrderStatus.PLACED` even after a result Observation is
written, when the simulation truncates at the snapshot boundary. Discovered as pre-existing
bug during PR1 Stage 2 adversarial review (commit 57285e2126). The expected invariant:
PLACED Orders MUST have no result Observation (and conversely, RESULTED Orders MUST have a
result Observation).

**Fix path:** Update Order.status during snapshot truncation in `clinosim/modules/inpatient.py`
(or wherever the snapshot day handling lives) — propagate the order_status transition
consistently with the result emission.

**Currently gated by:** `tests/integration/test_servicerequest_snapshot.py::test_snapshot_placed_orders_have_no_observation`
marked `pytest.mark.xfail(strict=False)`. When the bug is fixed, remove the xfail marker.

**Discovered:** PR1 stage 3 Minor fixes (2026-06-30).

### `_code_in_data` LOINC-existence helper — promote to public API
- Now exists in 3 places: `hai/engine.py`, `panel_grouping.py`, and this TODO.
- Path: promote to `clinosim/codes/loader.py:code_exists(system, code)` and migrate all 3
  consumers.

### `_o` dual-access helper — promote to `_shared.py` public API
- Now exists in `_fhir_service_request.py` + `_fhir_observations.py` (PR1 added second+third
  consumers).
- Path: promote to `clinosim/modules/_shared.py` as `o(obj, name, default)` and migrate.

### Audit framework — `_BUNDLE_BUILDERS` dict-compat sweep
- `test_device_fhir_output.py::test_device_extension_through_fhir_pipeline` progresses past
  AttributeError post-fix but fails for a different reason (device count = 0 at p=300).
  Sweep all builders for dict-compat (dataclass vs dict dual-access pattern).

## SS-MIX2 output adapter(セッション25 deferred)

**Decision:** User deferred SS-MIX2 implementation 2026-06-30 セッション25。実 EHR データ density 充実(問診 / 検査 / 手術 / 処方の event 記録)を先に進めるため。

**Scope:**
- 新 output adapter via AD-58 `register_output_adapter`(FHIR と並行出力、CIF read-only consume)
- HL7 v2.5 segment-based、厚労省 SS-MIX2 標準準拠
- 主要 message types:
  - **ADT**(Admit/Discharge/Transfer):A01 admit、A03 discharge、A02 transfer、A04 register
  - **OML**(Order Lab):検査依頼 message
  - **OUL**(Observation Unsolicited Lab):検査結果 message
  - **ORM**(Order Pharmacy):処方依頼 message
  - **RDE**(Pharmacy/Treatment Encoded Order):処方詳細 message
  - **MDM**(Medical Document Management):文書 message
- 既存 `hospital_config` の各 hospital identifier(MEDIS / JANIS / etc.)を SS-MIX2 hospital ID にマップ

**Target consumers(JP EHR vendor debug datasets):**
- 富士通 HOPE LifeMark / EGMAIN-GX
- NEC MegaOakHR
- SSI Hyper-S
- IBM HOPE / IBM 医療情報システム
- 厚労省 医療情報連携基盤 connectivity test

**推定 PR:** 4-6 PR(adapter skeleton + 主要 6 message types + 厚労省仕様検証 + 既存 hospital_config 連動)

**Precondition:**
- ★ Event density 5 chain(Document / MAR / Procedure / LabDR / Nursing)完了後に着手推奨
- 理由:SS-MIX2 は CIF を消費するだけなので CIF の event records 充実が直接 SS-MIX2 dataset 価値に反映

**関連 memory:**
- `project_event_density_strategy.md` — セッション25 戦略軸転換
- `project_ehr_event_emphasis.md` — セッション25 戦略再確認

**Discovered:** セッション25(2026-06-30)。User goal が 病院 event 記録充実 = 並行 SS-MIX2 出力より優先。

---

## Tier 1 #3 α-min-1 Document Density Chain — OOS formal entries (2026-07-01)

These items were **explicitly out of scope** for the α-min-1 document density chain
(per spec §11). Each has a formal phase assignment for the master plan phases:
[docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md](docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md)

### α-min-2 phase (COMPLETED 2026-07-01) — Document types

- ~~看護 narrative (Admission nursing assessment / Nursing shift note / Discharge nursing summary)~~ — **DONE** (AD-64: 78390-2/34746-8/34745-0, inpatient-only)
- ~~CareTeam (2-name: attending + primary nurse)~~ — **DONE** (AD-64: 1:1 Encounter, 158,811 US)
- ~~Triage infrastructure (JTAS/ESI + arrival_mode)~~ — **DONE** (AD-64: triage module POST_ENCOUNTER order=93)
- ~~46 encounter YAML narrative extensions~~ — **DONE**

## Tier 1 #3 α-min-2 Document Density Chain — OOS formal entries (2026-07-01)

These items were **explicitly out of scope** for the α-min-2 document density chain.

### α-min-3 phase — status audit 2026-07-02 (all 3 items closed)

- ~~**CRITICAL: outpatient.py + emergency.py do NOT call POST_ENCOUNTER enrichers**~~ —
  **STALE / RESOLVED**: the α-min-2 Task 14 fix already wired both simulators
  (`outpatient.py` + `emergency.py` "POST_ENCOUNTER stage" blocks). Production-verified
  2026-07-02 at US p=500 seed=42: OUTPATIENT_SOAP 1,841 / ED_NOTE 210 / ED_TRIAGE_NOTE 210.

- ~~**Nursing shift 3-per-day**~~ — **DONE (α-min-3 PR, 2026-07-02)**: `daily_3shift`
  generation_frequency implemented in `document/engine.py` + `document_type_specs.yaml`
  (day 08:00 / evening 16:00 / night 00:00, shift key on the stub, ja labels
  日勤/準夜/深夜 in Stage 2). Production-verified: NURSING_SHIFT_NOTE = exactly 3× per
  LOS day (US p=200: 750 vs 250 progress notes). 6 profile goldens regenerated (AD-66 Rule 1).

- ~~**Composition.author wiring**~~ — **RESOLVED earlier than documented**:
  `_fhir_composition.py` emits `author[]` from `ClinicalDocument.author_practitioner_id`
  (populated by `_pick_document_author` at every emission site); `Practitioner/UNKNOWN` is a
  defensive fallback only — production count 0 at US p=500 + JP p=300 (2026-07-02). The
  remaining design question (whether the UNKNOWN fallback should raise instead) stays in
  "AD-65 adv-1 deferred" (Practitioner/UNKNOWN dangling ref).

### β-JP-1 phase — CareTeam multi-disciplinary expansion

- **CareTeam 6-name multi-disciplinary** — attending physician / attending nurse / pharmacist /
  nutritionist / rehab therapist / MSW roles. Requires expanding StaffRoster to include non-MD
  non-nursing roles. Prerequisite: Practitioner roster expansion (Practitioner count 85 → 150+).

- **JP section.title locale mapping** — `Composition.section[].title` currently uses English
  section key (e.g. `"nursing_history"`) for JP output. Add JP locale dict mapping to Japanese
  titles (e.g. `"看護歴"`) in `_fhir_composition.py` section builder.

- **JTAS/ESI system URI formalization** — `triage_protocols.yaml` uses LOINC 54094-8 for triage
  level coding but does not formalize JTAS (`http://hl7fhir.jp/standards/jtas`) or ESI
  (`http://acep.org/esi`) system URIs as canonical constants. Add to a new `triage_constants.py`
  (mirrors `CARE_TEAM_ID_PREFIX` / `DOC_REFERENCE_ID_PREFIX` pattern).

### β-JP-1 phase — JP localization + 厚労省必須文書

- **QuestionnaireResponse active emission** — `_fhir_questionnaire_response.py` builder for
  structured intake forms. Currently a stub; no CIF data source for questionnaire answers.
- ~~**入院診療計画書** (Admission care plan document)~~ — **DONE (chain 2, 2026-07-03)**:
  LOINC 18776-5, Composition, 10 sections per MHLW 別紙２, JP-only,
  inpatient/icu only (rehab_inpatient uses the 別紙２の２ variant, out of
  scope). `special_nutrition_management` is hardcoded "無" pending a future
  nutrition subsystem chain (see below) — no NutritionOrder/nutritionist
  data source exists yet to derive a real value.
- ~~**栄養管理計画書** (Nutrition care plan)~~ — **DONE (chain 2, 2026-07-03)**:
  LOINC 80791-7, Composition, 12 sections per MHLW 別紙23, JP-only,
  inpatient/icu only, emitted only for admissions with LOS > 7 days (new
  `admission_once_los_gt_7` generation_frequency). Only 3/12 sections are
  data-driven (ward/physician from Encounter, nutrition_risk from
  PatientProfile.bmi, nutrition_supply energy/protein estimate from
  PatientProfile.weight_kg); the other 9 are MVP fixed fallbacks — see
  deferred entries below.
- **重症度、医療・看護必要度に係る評価票**(TODO.mdの旧記載「看護必要度D表」は誤記 — 正式名称は
  A項目/B項目/C項目の評価票、"D表"という区分はMHLW公式には存在しない、chain 2調査で訂正
  2026-07-03)— DPC/診療報酬算定用の国内専用スコアリング様式。**適切なLOINCコードなし**
  (検証済み:LOINC 80346-0 "Nursing physiologic assessment panel"は米国の一般看護身体
  アセスメントパネルで別物、誤用不可)。ローカルコード体系でのQuestionnaireResponse実装が
  必要(現状は`FormatType.QUESTIONNAIRE_RESPONSE`のinfrastructure stubのみ)。GCS/ADLデータは
  `nursing_enricher.py`に既存だが、評価票のA/B/C項目粒度とは一致しない。
- ~~**リハビリテーション計画書** (Rehabilitation plan)~~ — **DONE (chain 2, 2026-07-04)**:
  LOINC 34823-5, Composition, 9 sections per MHLW 別紙様式21 (base form only —
  variants 21の2〜21の5 out of scope), JP-only, inpatient-only (icu/rehab_inpatient
  both verified-unreachable EncounterType values — see status-audit finding in
  design spec §1). Gated on existing RehabSession data (post-surgical rehab for
  `requires_surgery: true` diseases), NOT the never-implemented rehab_inpatient
  ward-transfer subsystem the original TODO entry envisioned. 6/9 sections are
  data-driven.
- **JP section text full localization** — `past_medical_history` / `medications_at_home` /
  `discharge_medications` sections currently English-only in α-min-1. Full JP: condition names
  via `code_lookup(..., "ja")`, drug names via `_localize_drug_name()`.
- **ClinicalImpression.description JP localization** — currently English-only.
- **多職種 staff allocation** — 主治医 / 担当看護師 / 薬剤師 / 栄養士 / リハ / MSW per
  encounter, required for CareTeam + Composition.author wiring.

### chain 2 deferred: admission_care_plan real nutrition-need derivation

`_build_acp_special_nutrition_management` (`template_generator.py`) always
renders "無" (no special nutritional management needed) — an MVP
simplification, not a real clinical derivation. When the 栄養管理計画書
(nutrition care plan) subsystem chain lands (NutritionOrder + nutritionist
staff role), revisit this section to derive a real yes/no signal (e.g. from
BMI, albumin lab values, or disease-specific nutrition risk flags) instead
of the hardcoded default.

### chain 2 deferred: `section_builders` dict lacks cross-spec key-collision validation

`TemplateNarrativeGenerator._render_composition_sections`'s `section_builders`
dict (`template_generator.py`) is one flat global namespace shared by every
COMPOSITION document type; each new doc type adds more string keys into it
(chain 2 added `ward_and_room` / `diagnosis` / `symptoms` / `test_schedule` /
etc.). `registry.py`'s Layer 1-9 validators check per-spec coherence (e.g.
`llm_enabled_sections ⊆ composition_sections`) but nothing validates that a
NEW doc type's `composition_sections` keys don't collide with an EXISTING,
unrelated doc type's key already registered in this dict — a plain Python
dict literal silently keeps the last definition on a duplicate key, so a
colliding key would silently steal another doc type's renderer with no
error (adv-1 finding on PR #138, not a live bug today — verified no
collision currently exists across all registered specs — but the
architecture has no guard against a future one). Add an import-time
uniqueness check (mirrors the `registry.py` Layer 1-9 pattern) that walks
every `DocumentTypeSpec.composition_sections` list and asserts each section
key maps to at most one doc type's intended semantics, OR restructure
`section_builders` to be keyed by `(doc_type, section)` instead of bare
`section` so collisions become structurally impossible.

### chain 2 deferred: nutrition_care_plan real data derivation

`_build_ncp_dietitian` / `_build_ncp_nutrition_assessment` /
`_build_ncp_nutrition_goals` / `_build_ncp_dysphagia_diet` /
`_build_ncp_dietary_content` / `_build_ncp_nutrition_counseling` /
`_build_ncp_other_issues` / `_build_ncp_reassessment_timing` (8 of 12
sections) render MVP fixed fallback strings — no CIF data source exists for
dietitian staff, real nutrition assessment/counseling content, or dysphagia
screening. Revisit when a richer nutrition-assessment data model + dietitian
staff role are built. `nutrition_risk`'s BMI-threshold heuristic is a coarse
screening proxy (not GLIM/MUST-validated) — acceptable for synthetic-data
MVP but should not be treated as clinically authoritative if reused
elsewhere.

### chain 2 deferred: nutrition_care_plan discharge-time revision

`_build_ncp_discharge_evaluation` always renders a fixed "pending" phrase —
this system has no mechanism to re-render a Stage-1 document stub at a later
encounter phase. If discharge-time nutrition evaluation becomes a priority,
this would need either a second document type (mirroring the
`nursing_discharge_summary` vs `admission_nursing_assessment` split
precedent) or a new Stage-2 revision mechanism.

### chain 2 deferred: LOS-gated document_enricher pattern (final review, PR #139)

`nutrition_care_plan` introduced `admission_once_los_gt_7`, the first
`generation_frequency` that bakes a numeric threshold into the enum string
itself (`document/engine.py`'s `document_enricher` dispatch). This is fine
for one gated doc type, but before a **third** LOS-gated document lands,
consider parameterizing instead of adding `admission_once_los_gt_14` etc.
ad hoc — e.g. keep `generation_frequency: admission_once` plus an optional
`min_los_days: int | None` field on `DocumentTypeSpec`, read once by a
single `admission_once` branch. Relatedly, `document_enricher` now has 3
near-identical 10-field `ClinicalDocument(...)` constructions
(`admission_once` / `admission_once_los_gt_7` / the per-day loop body in
`daily`) — a small local `_make_doc_stub(spec, encounter_id, doc_seq,
authored_dt, pid, lang, author)` helper would collapse the duplication and
make the LOS guard the only visible difference between branches.

### chain 2 deferred: rehab_inpatient / EncounterType.ICU ward-transfer subsystem

Both `EncounterType.REHAB_INPATIENT` and `EncounterType.ICU` are defined in the
enum and referenced in downstream module allowlists (`document`, `nursing`) but
are **never actually assigned** anywhere in the simulator — verified empirically
(JP p=500 cohort produced zero occurrences of either value; `create_inpatient_encounter()`
hardcodes `EncounterType.INPATIENT`, `icu_transferred` is a boolean flag on that
same encounter, not a distinct one). The rehabilitation_plan chain (2026-07-04)
deliberately built against the already-firing `RehabSession` data on ordinary
`inpatient` encounters instead of this subsystem — see design spec
`docs/superpowers/specs/2026-07-04-rehabilitation-plan-design.md` §1. If a rehab
ward transfer / distinct ICU encounter is ever prioritized, it is a
simulator-level feature (transfer trigger in `inpatient.py` or
`encounter/engine.py` + disease YAML trigger conditions), not a document-module
change — and every downstream module currently declaring `rehab_inpatient`/`icu`
support (`document`, `nursing`) would need re-verification against real data at
that point, since none of it has ever been exercised in production.

### chain 2 deferred: rehabilitation_plan OT/ST therapy types + named therapist

`generate_rehab_sessions` (`modules/procedure/engine.py`) hardcodes
`therapy_type="PT"` — the `rehabilitation_plan` document's `rehab_team` section
will only ever show PT until that module (procedure module, out of scope for
the document-module chain) is extended to produce OT/ST sessions. Separately,
no PT/OT/ST staff role exists in the roster (mirrors the `nutrition_care_plan.dietitian`
gap), so the named-therapist sub-field is a permanent fixed fallback until a
therapist staff role is built.

### chain 2 deferred: rehabilitation_plan patient/family goals data source

`goals` and `policy` sections are fixed fallbacks with no CIF data source — no
field represents a patient's stated rehab goals or family wishes. This is why
`stage2_strategy=template_only` (no LLM) was chosen even though these two
sections read as narrative-shaped (design spec §3d): an LLM asked to fill them
would fabricate entirely. Revisit `stage2_strategy` for these two sections only
if a patient-goals data model is ever built.

### chain 2 deferred: RehabSession.activities free-text localization

`RehabSession.activities` (`types/procedure.py`) holds hardcoded English phrases
(e.g. "bed exercises") with no JP mapping. `rehabilitation_plan`'s
`basic_movement` section avoids this entirely by re-deriving a phase
(early/mid/late) from `day_post_op` instead of rendering the raw activity list.
If a future consumer needs the raw activities in JP output, add a proper
activity-key → {en, ja} lookup table then — do not hardcode ad hoc translations
at that call site.

### chain 2 deferred: rehabilitation_plan SDD review ride-along findings (final review, PR #141)

Minor, non-blocking items surfaced during the rehabilitation_plan chain's
per-task and final whole-branch reviews, recorded here since the SDD
`.superpowers/sdd/progress.md` ledger they originated in is git-ignored
scratch (deleted with the worktree after merge):

- **No multi-encounter isolation test**: `document_enricher`'s
  `admission_once_if_rehab_sessions` branch correctly filters
  `record.rehab_sessions` by `encounter_id`, but no test proves a
  two-encounter patient record (e.g. a readmission) only emits the stub for
  the encounter that actually has rehab sessions. Separately,
  `NarrativeContext.rehab_sessions` (populated in `passes.py`) stays
  record-wide/unfiltered — mirroring the pre-existing `procedures` field's
  scope — so a rehab-plan document's *narrative content* for one encounter
  could in principle describe session counts/dates from a different
  encounter's rehab sessions on the same patient. Low real-world risk
  (post-surgical rehab today only occurs within a single inpatient
  encounter), but untested.
- **`_build_rp_basic_movement` phase-boundary values untested**: only
  `day_post_op=1` (early) and `=20` (late) are covered; the exact threshold
  boundaries (3/4, 14/15) that would catch an off-by-one aren't.
- **`document`/`nutrition_care_plan`/`admission_care_plan`/`rehabilitation_plan`
  test files lack `pytest.mark.unit`**: `pytest -m unit` silently skips
  `tests/unit/modules/document/**` entirely (confirmed: marker-agnostic
  `pytest tests/unit -q` finds ~800 more tests than `pytest -m unit -q`).
  Pre-existing gap, not introduced by any chain-2 sub-project — worth a
  dedicated sweep to add the marker across the document module's test tree.

None of these block correctness; the final whole-branch review (opus)
returned "Ready to merge: Yes" with zero Critical/Important findings.

### β-2 phase — Clinical event density

- **手術記録** (Operative note) — LOINC 11504-8, existing Stage 2 LLM path; Stage 1 template
  for surgical encounters via `_simulate_surgery` path.
- **麻酔記録** (Anesthesia record) — intra-op vital signs, drug administration. Requires
  anesthesiologist staff role.
- **IC document** (Informed consent documentation) — pre-procedure consent form.
  LOINC 64280-2. Triggered by procedure scheduling.
- **薬剤管理指導記録** (Pharmaceutical care record) — pharmacist intervention notes per
  encounter day. Requires pharmacist staff role.
- **リハビリ実施記録** (Rehabilitation session record) — per-session narrative linked to
  ProcedureRecord of type rehab.
- **多職種カンファレンス記録** (Multidisciplinary conference note) — weekly MDT note.
  Triggered by LOS > 7 days or HAI + antibiotic cascade.
- **家族説明記録** (Family explanation / consent note) — end-of-life / ICU transition.
  Linked to code_status enricher.
- **MedicationDispense (pharmacy 払出)** — pharmacy dispense records per MAR cycle.
  Requires pharmacy staff role.
- **Procedure density 強化** — bedside procedures (central line insertion, intubation,
  lumbar puncture) + surgical catalog for OR encounters.

### γ phase — Transitions + communication

- **MSW / Discharge planning document** — social work assessment + discharge plan.
  LOINC 18776-5 variant.
- **紹介状** (Referral letter / Reply letter) — inter-facility communication.
  LOINC 57133-1 / 57134-9.
- **主治医意見書** (Physician's opinion report for long-term care assessment) — JP 介護保険
  mandatory document.
- **初診時記録** (Initial visit record) — first outpatient encounter narrative.
- **Appointment + AppointmentResponse** — outpatient scheduling cycle.
- **Communication** — patient/provider messaging. FHIR R4 Communication resource.
- **Flag** — clinical alert flags (allergy / fall risk / isolation).

### δ phase — Advanced clinical documentation

- **Pathology / Cytology report** — biopsy / PAP smear / FNAB results.
  Linked to Procedure + Specimen resources.
- **CarePlan** (goal-oriented care coordination) — multi-encounter goal tracking.
- **Goal** — patient-specific care goals linked to CarePlan.
- **EpisodeOfCare** — chronic disease episode tracking across readmission chain.
- **AdverseEvent** — drug adverse event documentation.
- **DetectedIssue** — clinical decision support alerts.
- **死亡診断書** (Death certificate) — JP mandatory document for deceased encounters.
  Requires `cause_of_death` enricher.
- **Pre/Post-op evaluation** — anesthesia consult note pre-surgery.
- **OR nursing record** — circulating/scrub nurse intra-op documentation.

### ε phase — Infrastructure event granularity

- **ADT location transfer** — ward transfer records as Encounter.location[] events.
  Requires admission/transfer/discharge event CIF extension.
- **Vital frequency 拡張** — ICU vitals q1h / q30min / continuous monitoring stream.
  Requires monitor data integration.
- **Specimen 独立** — Specimen resource as independent resource (not embedded in DiagnosticReport).
  Required for cross-lab specimen tracking.
- **Per-dose MAR refactor** — current MAR is per-day; upgrade to per-dose with exact
  administration datetime, route, dose, nurse ID.

### Infrastructure — LLM provider integration (separate chain)

- **Bedrock / Ollama / Anthropic 実装** — infrastructure is prepared in `llm_service/`;
  template fallback is the default. LLM integration for Stage 1 document narrative (higher
  quality clinical notes) is a separate chain from document density chain. Integration testing
  requires API key / Ollama install; not part of α-min chain gate.

### α-min-1 per-task Minor findings (carry-over for adversarial fan-out)

(All Minor findings from Tasks 1-12 progress ledger, to be addressed in post-merge
adversarial fan-out review.)

- **Task 1 M-1**: stale `# EncounterRecord` comment in `clinosim/types/document.py:46`
  should be `# Encounter (clinosim.types.encounter)`.
- **Task 1 M-2**: misleading test name `test_narrative_context_default_constructible` —
  rename to `test_narrative_context_fully_specified_construction`.
- **Task 2 M-1**: ~~`normalize_probabilities` not used for `CATEGORY_WEIGHTS` in allergy enricher~~
  RESOLVED: G-1 fix (post-PR-128 adv fan-out) added `normalize_probabilities(weights, fallback="raise")` guard.
- **Task 2 M-2**: reaction entry per-field validator absent (HAI `_validate_hai_organisms`
  pattern would be tighter).
- **Task 3 M-1**: `field(default_factory=tuple)` → `= ()` simplification in frozen dataclass.
- **Task 3 M-2**: `display_ja` "退院サマリ" vs `loinc.yaml` "退院時サマリー" — registry-internal
  label; FHIR output uses `code_lookup` (AD-30 compliant). Verify canonical form.
- **Task 5 M-3**: baseline YAML `complicated_deterioration` has day_7 gap — add day_7 entry
  for YAML completeness even if not clinically needed at α-min.
- **Task 6 M-1**: `_build_social_history` false-positive `facts_used` marker when
  `occupation=""` — suppress for empty string.
- **Task 9 M-1**: `AllergyIntolerance.category` validation comment missing — add inline
  comment referencing FHIR R4 category binding.
- **Task 10 M-1**: `import base64` module-level hoist (currently inline in builder function).
- **Task 10 M-3**: `docStatus` was "preliminary" for all Stage 1 docs — E-1 fix (post-PR-128
  adv fan-out) changed to unconditional "final". `docStatus` coverage was added to test update
  in post-PR-128 composition test (assertion for `docStatus="final"` should be added to
  `test_fhir_documents.py` to pin the Stage-1="final" invariant).
- **Task 12 M-3**: dead code in determinism test.
- **Task 12 M-4**: `"python"` literal in `_sr_helpers.py` should be `sys.executable`.

## Tier 1 #3 α-min-1 post-merge adversarial fan-out findings (2026-07-01)

5-lens parallel adversarial review of PR #128 surfaced 3 Critical + 15 Important. High-impact
+ low-risk subset applied in fix commit (post-PR-128 adversarial review branch). Deferred items:

### Deferred Important findings

- **Lens 1 I-2**: `_build_dref_from_clinical_doc` silently returns `None` on empty `text`
  or missing `loinc_code`; consider adding a `warnings.warn()` or log so silent skips are
  visible in production runs (currently only surfaced by `DocumentReference.ndjson` count
  being lower than expected).

- **Lens 2 I-1/I-2/I-3 (27-YAML boilerplate refactor)**: 27 disease YAML files each repeat
  a `narrative.discharge_instructions` baseline block ("Diet: General diet as tolerated...").
  Refactor: hoist shared baseline to `modules/document/reference_data/physical_exam_findings.yaml`
  and `discharge_instructions.yaml`; keep only disease-specific overrides in each YAML.
  Separate finding: `uncomplicated_improvement` archetype name in disease YAMLs does not
  match `smooth_recovery` in some template generator branches — audit archetype name
  consistency (`complicated_deterioration` / `uncomplicated_improvement` / `smooth_recovery`
  across all 32 disease YAMLs + `template_generator.py` lookup paths).

- **Lens 3 I-3 JP Composition.section.title locale dict**: `Composition.section[].title`
  currently uses the English section key as-is (e.g. `"chief_complaint"`) for JP output.
  Add a JP locale dict mapping section keys to Japanese titles (e.g. `"主訴"`) + wire it
  in `_fhir_composition.py` section builder. Prerequisite: JP section.title spec in
  β-JP-1 locale dict.

- **Lens 4 I-1 LLMNarrativeGenerator singleton**: `LLMNarrativeGenerator` is instantiated
  once per `document_enricher` call (per patient in POST_ENCOUNTER loop). At Stage 2
  (β-JP-1) with real LLM calls, this incurs per-patient setup overhead. Refactor to module-
  level singleton or pass the generator as a parameter from the enricher registry. Stage 1
  (template-only) unaffected since constructor is lightweight.

- **Lens 4 I-3 allergen prevalence field sampling**: `allergens.yaml` carries a `prevalence`
  field per allergen entry (adult rate 0..1), validated at load time. Current enricher ignores
  it and samples entries uniformly (`rng.integers(0, len(entries))`). Either implement
  prevalence-weighted choice (more clinically realistic) OR remove the field from YAML and
  validator to avoid misleading it is used. Deferring to α-min-2 allergy density phase.

- **Lens 5 I-3 AD-30 allergen_display CIF field**: `Allergy.allergen_display` stores English
  text (e.g. `"Penicillin"`), violating AD-30 (CIF stores codes only; display resolved at
  output time via `clinosim.codes`). Pragmatic exception because `_fhir_allergy_intolerance.py`
  uses `allergen_display` as fallback when SNOMED lookup yields no result. Options: (a) remove
  the field and resolve display purely via `code_lookup("snomed-ct", allergen_code, lang)` at
  FHIR export time; (b) document as pragmatic exception in CLAUDE.md with a `# noqa: AD-30`
  comment. Strict fix preferred (option a) but requires verifying all emitted SNOMED codes are
  in `codes/data/snomed-ct.yaml`.

### Deferred Minor (stale doc cross-references)

- **M-1 DESIGN.md ADR summary stale stage**: DESIGN.md ADR summary row for AD-63 says
  "POST_RECORDS" but allergy is POST_POPULATION and document is POST_ENCOUNTER. Fix to
  "POST_POPULATION (allergy, order=10) + POST_ENCOUNTER (document, order=95)".
- **M-2 DQR Composition gap explanation stale**: DQR Known Limitations item 4 says
  `author: []` for empty attending; now `Practitioner/UNKNOWN` placeholder (A-1 fix). Update.
- **M-3 MODULES.md document row misclassification**: MODULES.md may classify the document
  module as POST_RECORDS; correct to POST_ENCOUNTER order=95.
- **M-4 fhir-data-generation-logic.md cross-refs stale**: check `docs/design-guides/` for
  references to `extensions["document"]` or `docStatus="preliminary"` and update.
- **M-5 DQR Known Limitations 4+5 stale post-Task-15**: post-Task-15 notes in DQR may
  reference legacy activator.py allergy path (now deleted). Verify and remove stale references.
- **M-6 C-1 archetype/severity not wired**: `document_enricher` now resolves `disease_protocol`
  from `_disease_id` IPC key but still uses default `severity="moderate"` and
  `clinical_course_archetype="uncomplicated_improvement"`. Wire `severity` and `archetype` by
  storing them in `record.extensions["_severity"]` / `record.extensions["_archetype"]` in
  `inpatient.py` alongside `_disease_id`, then read in `document_enricher` (same IPC pattern).
  This activates the `physical_exam_findings[archetype][day_N]` and course-archetype-specific
  assessment blocks in `template_generator.py`.

## AD-65 Bug A residual gap — disease YAML English narrative content (2026-07-02)

Discovered while implementing Task 11 (Bug A integration test + audit gate) of the AD-65
two-pass CIF architecture chain. Task 9 fixed the code-level locale-routing bug
(`_pick_localized` helper) and Task 10 populated every missing `_en` YAML peer — but **only**
for fields that actually carry a `<key>_en` / `<key>_ja` suffix pair (`ed_note_template.*`,
`outpatient_soap_template.*` in the 46 encounter YAMLs). Both tasks explicitly flagged (see
`.superpowers/sdd/task-9-report.md` §6 concern 2, `task-10-report.md` §7) that two disease-YAML
narrative sources used by ADMISSION_HP (inpatient H&P, LOINC 34117-2) have **no per-language
split at all** — not even a missing `_en` sibling, the data model itself is severity/day-keyed
with Japanese-only content:

- `disease_protocol.narrative.hpi_template.onset_pattern` (keyed by `mild`/`moderate`/`severe`)
- `disease_protocol.narrative.physical_exam_findings` + the shared baseline
  `clinosim/modules/document/reference_data/physical_exam_findings.yaml` (keyed by
  `clinical_course_archetype` × `day_N`, further nested by body system)

`_build_hpi` / `_build_physical_examination` in `template_generator.py` tag `facts_used` with
the module's documented `:ja_only_fallback` suffix when this path fires for a non-`ja` locale
(so the fallback is auditable, not silent) — but the actual section TEXT emitted for a US
cohort is still Japanese. Verified empirically: US p=100 cohort → 15 ADMISSION_HP documents,
630 Japanese characters, 100% located in `physical_examination` (none in `hpi` for this
seed/config, since `ctx.disease_protocol` was `None` for every generated admission_hp
encounter in that run — see the α-min-3-scope `document_enricher` archetype/severity wiring
gap in "M-6 C-1" above; once that's fixed, `hpi` will very likely start emitting Japanese too).

**Task 11 resolution (interim, shipped)**: `clinosim/modules/document/audit.py`'s
`KNOWN_JA_ONLY_FALLBACK_SECTIONS = {"hpi", "physical_examination"}` and the companion
`tests/integration/test_bug_a_us_hp_english_only.py` both exclude these two sections from
the zero-ja-chars assertion so the gate tracks the actual Bug-A locale-routing fix (any OTHER
section leaking Japanese still fails hard) rather than perpetually red on a known, separate,
tracked issue.

**Follow-up needed to fully close Bug A for ADMISSION_HP**: author English content for
`hpi_template.onset_pattern` (3 severity keys × 32 diseases) and `physical_exam_findings`
(N archetypes × N days × 5 body systems × 32 diseases + the shared baseline file) — this is a
data-model change (add a language axis to structures that currently have none), not a simple
`_en` sibling-key addition, so it is a distinctly larger undertaking than Task 10's 46-file
sweep. Recommend a dedicated chain (own SDD task set) rather than folding into AD-65 Bug A.
Once the data gap closes, remove `hpi` / `physical_examination` from
`KNOWN_JA_ONLY_FALLBACK_SECTIONS` and re-verify both the audit gate and the integration test
still pass with the exclusion removed (expect them to pass unconditionally at that point).

## AD-65 adv-1 deferred (2026-07-02)

Findings from PR #131 (`feature/tier1-narrative-stage2-architecture`) adv-1 5-lens
adversarial review that were triaged as out-of-scope for the fix chain. All are pre-existing
concerns or β-JP-1 (LLM narrative pass) scope, not landing in the AD-65 fix work.

- **L3 I-1 `Practitioner/UNKNOWN` fallback dangling reference**: `_bb_care_teams` emits
  `member.reference = "Practitioner/UNKNOWN"` when the attending id is empty. FHIR R4
  reference integrity says every reference must resolve to an emitted resource — no
  `Practitioner/UNKNOWN` resource is emitted anywhere. Pre-existing broader design issue
  (predates AD-65); options are (a) emit a synthetic UNKNOWN Practitioner, (b) skip the
  participant entirely, (c) use `identifier.value="UNKNOWN"` without a reference. Decision
  needs cross-team alignment.
- **L3 I-2 `Patient/` empty-id dangling reference**: similar pattern where an encounter with
  no patient id emits `Patient/`. Pre-existing; the boundary-raise approach (fail early
  when patient_id empty) is preferred over silent fallback.
- **L3 I-4 Bug A partial — HPI + physical_examination YAML restructure**: already tracked in
  the "AD-65 Bug A residual gap — disease YAML English narrative content" section above.
- **L4 IMPT-2 `_deterministic_timestamp` constant-per-pass → per-doc mix**: current impl
  returns the SAME timestamp for every document in a single narrative pass (base + rng_seed
  offset only). Realism would be per-doc seeded from `(doc.document_id, rng_seed)`. Session
  28 tracked as separate follow-up.
- **L4 IMPT-3 re-narrate orphan file cleanup on same version_id**: re-running narrate on the
  same version_id after a disease/encounter YAML edit that DROPPED a document leaves the
  stale narrative file on disk. CIFReader logs it as orphan but doesn't unlink. Add a
  pre-run cleanup pass or a `--overwrite` flag.
- **L4 IMPT-4 β-JP-1 `NarrativeOutput.metadata.get("generator", ...)` override hook +
  `doc_status` field**: LLMNarrativePass needs a way to signal `preliminary` vs `final`
  narrative status; wire `NarrativeOutput.metadata["doc_status"]` → CIF stub
  `doc_status` field → FHIR `DocumentReference.docStatus` / `Composition.status`. Defer to
  β-JP-1 planning.
- **L2 I-4 Encounter YAML `_en/_ja` peer requirement CI enforcement**: Task 10 (α-min-2)
  populated missing `_en` peers for all 46 encounter YAMLs; add a `_validate_*` gate at
  `load_encounter_condition` time so a future YAML edit that adds a `_ja`-only key raises
  at import.
- **L2 I-5 `current_version.txt` write helper (4-site DRY refactor)**: `open(..., "w") as f:
  f.write("template")` appears in CLI test-disease-generate, test-encounter-generate,
  generate, and narrate. Extract a helper in `cif_writer.py` /
  `clinosim/modules/document/narrative/passes.py`.
- **L2 M-4 `nursing_enricher` function rename to `nursing_assignment_enricher`**:
  CLAUDE.md AD-64 rule already spells out the naming convention (`nursing_assignment`
  for POST_ENCOUNTER order=94 vs `nursing_flowsheets` for POST_RECORDS order=20). Code
  hasn't been renamed yet; the enricher name in `enrichers.py:register_builtin_enrichers`
  is still `nursing`. Cosmetic, low priority.
- **L2 M-5 Integration tests using `ForcedScenario` instead of subprocess p=800**:
  `tests/integration/test_bug_c_triage_all_levels.py` and siblings launch the CLI via
  `subprocess.run` with p=800 which is slow (~30s each). Migrate to
  `ForcedScenario(disease_id=..., count=800)` + `run_forced` for a ~5x speedup.
- **L3 M-1 through M-8 β-JP-1 concerns**: (a) section title JP localization,
  (b) section.code LOINC dispatch, (c) docStatus dispatch, (d) DocumentReference.identifier
  emission, (e) US Core category tag, (f) XHTML `<br/>` escaping, (g) empty div status handling,
  (h) `Encounter.priority` JTAS/ESI mapping. All defer to β-JP-1.
- **L1 M-1 through M-4 cosmetic**: (a) CIFReader multi-encounter walk (currently walks
  encounters[0] only for narrative merge — a multi-encounter patient with narratives on
  encounters[1] would silently drop them; matters for the follow-up-visit scenario),
  (b) `--narrative-version` typo warn (already raise-fired via F-1, cosmetic UX enhancement
  possible), (c) test fixture format_type sanity, (d) manifest timestamp pin.
- **L5 Minor-1 through Minor-6 TODO.md missing entries for Task 3 known issues**: Task 3
  landed several known issues (e.g. sanity check on progress note LOS bounds, discharge
  summary conditional on discharge_datetime) that never made it into TODO.md as formal
  entries.
- **L1 M-1 `NURSING_LOINCS` inline in integration test file (Lens 2 M-1)**: at least one
  integration test hardcodes `{"78390-2", "34746-8", "34745-0"}` instead of importing
  `NURSING_LOINCS` from `clinosim.modules.document`. Should import; low-impact but drift
  risk once the YAML changes.

Full triage report: `/private/tmp/claude-*/adv1_ad65/triage.md` in the fix session
(reproducible from the 5-lens pass over PR #131 HEAD `c61914c716`).


## Common-logic unification review — deferred chains (2026-07-02, session 31)

Source: 4-lens module-wide audit (loader / code-mapping+i18n / generation+narrative IF /
docs) + `docs/design-notes/2026-07-02-grand-design-review-and-roadmap.md` (§3, canonical
prioritization). The byte-identical subset (R1-R7) landed on
`refactor/common-logic-unification`; everything below changes behavior/schema and needs
its own chain.

### N-chain: Narrative interface unification (β-JP-1 prerequisite) — DONE, 2 items remain

N-1 (`NarrativeGenerator` Protocol + constructor injection + former α-min-1 Task 7
machinery wired live via `LLMNarrativePass`), N-2 (provider unification via
`LLMService.complete_prompt`), N-3 (prompt ownership via `llm_service/prompts/{en,ja}/*.yaml`
+ `PromptRegistry`, public API exported from `llm_service/__init__.py`), and the adv-1
`_build_context` degenerate-context-fields item (now wired to real structural CIF fields —
`disease_protocol` / `clinical_course_archetype` / `severity` all read live data; see
`document/narrative/passes.py:_build_context`) were completed in session 31-32 (N-chain +
β-JP-1 chain 1a, commits `5e7077f0d9`/`c981c390e2`/`3da54aaeb6`/`38b4b32f31`/`45b4899c1e`).
Verified against code directly in session 35 — this entry had gone stale (marked ★★★ /
undone) after completion; **β-JP-1 has been unblocked since session 31**. Only two small
items remain, both previously filed as "later cleanup" / optional:

- **`narrative/cache.py get_default_cache()` singleton = test-only dead seam**: no production
  code path uses the module-level `_default_cache` (LLMNarrativePass owns a per-run
  `NarrativeCache` instance; LLMNarrativeGenerator defaults to a fresh instance). Remove the
  singleton + its test, or wire it deliberately.
- **N-4 (optional, incremental)**: data-drive `template_generator.py` (2075-line Python string
  assembly) into per-section YAML templates so new doc types need no Python edits.

### ★ Display-dict → codes YAML migration

**Re-verified 2026-07-05 (session 37)** — `_fhir_care_team.py` is already migrated (Task 11,
2026-07-01: category code resolved via `code_lookup("snomed-ct", ...)`, `codes/data/snomed-ct.yaml`
already has the entry; the Python constant is now only a defensive fallback). Remove from scope.
Remaining, re-scoped:
- ~~`_fhir_patient.py`~~ — **DONE (session 37)**: `codes/data/hl7-v3-maritalstatus.yaml` +
  `codes/data/bcp-47-language.yaml` added; both marital status and preferred-language display
  now resolve via `code_lookup`. Bonus: language display is now properly JP-localized (was
  English-only before, a latent gap of its own — no golden fixture exercised this field, so no
  regression risk).
- ~~`_fhir_microbiology.py`~~ — **DONE (session 37)**: new
  `codes/data/hl7-observation-interpretation.yaml` (S/I/R susceptibility subset only — the
  broader numeric-flag subset N/H/L/HH/LL/A/AA/HU/LU/POS/NEG in
  `_fhir_localization.py:_INTERPRETATION_DISPLAY_JA` is a separate, larger, not-yet-migrated code
  system and was NOT touched, since it's used differently — mixed code/English-word keys, no
  clean `code_lookup` fit yet). The dead duplicate R/S/I entries in that dict were removed after
  confirming (by tracing both its 2 callers) that neither ever produces an S/I/R code.
- ~~`_fhir_allergy_intolerance.py`~~ — **DONE (session 37)**: new
  `codes/data/hl7-allergyintolerance-clinical.yaml` + `hl7-allergyintolerance-verification.yaml`
  replace `_CLINICAL_STATUS_DISPLAY` / `_VERIFICATION_STATUS_DISPLAY`.
- ~~`_fhir_endpoint.py`~~ — **DONE (session 37)**: new `codes/data/hl7-endpoint-connection-type.yaml`
  + `hl7-endpoint-payload-type.yaml` replace the 2 inline literals.
- ~~`_fhir_reference_data.py`~~ — **DONE (session 37)**, the largest/last item in this backlog:
  new standalone `codes/data/condition-short-name.yaml` (39 entries, own `urn:clinosim:` code
  system rather than extending `icd-10-cm.yaml`'s schema — the short name is clinosim's own
  abbreviation convention, distinct from the official long name, so a separate lookup avoids
  confusing that widely-used file's existing consumers) replaces `_CONDITION_SHORT_NAME`.
  `_ENCOUNTER_TYPE_SNOMED_JA` migrated by adding the 4 SNOMED codes to `codes/data/snomed-ct.yaml`
  (en+ja) and simplifying `_ENCOUNTER_TYPE_SNOMED` (which held both code AND English display) down
  to `_ENCOUNTER_TYPE_SNOMED_CODE` (enum -> code only); both EN and JA display now resolve via
  `code_lookup("snomed-ct", code, lang)`, closing a second latent duplication (EN display had been
  hardcoded in Python while JA lived in a separate dict, both for the same 4 SNOMED concepts).

**★ Display-dict → codes YAML migration backlog CLOSED (session 37, 2026-07-05)** — all 6 files
from the 2026-07-02 review re-verified and migrated (2 were already done by prior sessions). 8 new
`codes/data/*.yaml` files added this session: `hl7-v3-maritalstatus`, `bcp-47-language`,
`hl7-observation-interpretation`, `hl7-allergyintolerance-clinical`,
`hl7-allergyintolerance-verification`, `hl7-endpoint-connection-type`, `hl7-endpoint-payload-type`,
`condition-short-name`; plus 4 new entries added to the existing `snomed-ct.yaml`.

### ~~★ Dual-access sweep~~ — CLOSED (session 37, 2026-07-05)

- Read side trivial single-field swaps (`csv_adapter.py`, `_fhir_device.py`, `_fhir_hai.py`,
  `_fhir_immunization.py`) → `_o()` (`get_attr_or_key`).
- `_fhir_conditions.py` — was mischaracterized in the original entry as the dataclass-vs-dict
  pattern (it's actually str-vs-dict); fixed the real latent bug found while re-scoping: a bare
  `ChronicCondition` dataclass reaching this function matched neither branch and was silently
  dropped via a trailing `else: continue`. Replaced with `get_attr_or_key()`, which also removed
  a redundant duplicate `c_stage` read.
- Write side: added `set_attr_or_key(obj, name, value)` (single-field replacement) and
  `get_or_create_container(obj, name, factory)` (nested dict/list field, composable for two levels
  e.g. `extensions` → `antibiotic`) to `_shared.py`. Swept all 8 files / 13 call sites:
  `code_status`/`care_level`/`immunization`/`family_history`/`nursing_enricher` (simple sets),
  `device`/`hai` (nested extensions + list append), `antibiotic` (5 sites: orders/MAR
  append+extend, extensions→antibiotic nested extend, plus 2 read-side sites in
  `_truncate_mar`/`_mark_order_stopped` that were also inconsistent ternary dict/dataclass reads).
- `_fhir_observations.py:431` / `observation/nursing_enricher.py:36,70` — confirmed NOT the same
  pattern (whole-object `dataclasses.asdict()` / `.__dict__` coercion, needed because the consumer
  function takes a full dict, not one field). Both already correct; no change made.

### Single items (ride along with related chains)

- `PrescriptionRecord.issue_date` precision gap — inpatient discharge prescription
  uses `admission_time` rather than true discharge datetime (deliberate simplification:
  `encounter.discharge_datetime` is not finalized at `_build_discharge_rx()` call site
  in `clinosim/simulator/inpatient.py`, and is `None` for AD-32 snapshot-truncated
  in-progress encounters). If closer precision needed later, move `_build_discharge_rx()`
  call to after discharge_datetime finalization, or duplicate the discharge formula at
  call site.
- Dead Bundle-timestamp footgun — `clinosim/modules/output/_fhir_facility.py:159` and
  `clinosim/modules/output/fhir_r4_adapter.py:456` both call `datetime.now()` to
  populate `Bundle["timestamp"]`, but this field is confirmed never read or serialized
  to output. Scope-clean from determinism chain (only sentinel-default fields +
  PhysiologicalState.timestamp + PrescriptionRecord.issue_date were in scope), but
  track to prevent future refactors accidentally propagating this unread wall-clock
  value into real output without noticing non-determinism.
- Move `DiagnosisCandidate` / `DifferentialDiagnosis` (`diagnosis/engine.py:51,60`) to
  `clinosim/types/` (types rule).
- `inpatient.py:1826` unknown-condition path: call `scenario_flags_from_protocol(None)` in the
  merge instead of comment-justified omission (J5-class risk).
- Unify locale-loader unsupported-country contract to "return {}" (immunization / code_status /
  family_history currently silently fall back to US; care_level is the compliant precedent).
- Root `spec.md` (2026-06-05): add historical-document header pointing to DESIGN.md +
  `clinosim/modules/output/SPEC.md`.
- DESIGN.md: note AD-1/2/12/14/15/27 numbering gaps as reserved/withdrawn; sort compact table.
- ~~Allergy/imaging display locale-freeze~~ — **re-verified 2026-07-05 (session 37), already
  correct, not a bug**: neither `allergy_enricher()` nor `_expand_views_to_series()` actually reads
  `display_en`/`display_ja` at all — both only store the SNOMED code, and display resolution
  happens downstream in `_fhir_allergy_intolerance.py` / `_fhir_service_request.py` via
  `code_lookup()` / `resolve_lang()`, already locale-correct. The YAML `display_en`/`display_ja`
  fields are validated as required (schema completeness) but simply unused by these two named
  functions — no code fix needed.
- JP microbiology culture codes now use JLAC10 (`6B010`, session 35, 2026-07-04) —
  `_fhir_microbiology.py` resolves the culture Observation/DiagnosticReport code via
  `code_mapping_microbiology.yaml` + `system_key_for("microbiology", ...)`, covering
  both community-acquired and HAI-derived cultures (both carry the same country-neutral
  `MicrobiologyResult.specimen` key). Verified against JSLM JLAC10 master v137: category
  6B (微生物学的検査/培養同定検査) has one generic culture-identification analyte code
  (no per-specimen variants at the analyte-code level — specimen type lives in the
  17-digit full code's material segment, which clinosim doesn't model), so all 4
  specimens map to the same `6B010`.
- ~~Antibiotic susceptibility JLAC10 mapping~~ — **FIXED (session 35, 2026-07-04, same-day
  follow-up)**: contrary to the original "needs its own research pass" deferral above, the
  JSLM master lookup showed JLAC10 category 6C (微生物学的検査/薬剤感受性検査) has the
  identical single-generic-code shape as category 6B did for culture — one code, `6C010`
  ("drug susceptibility test, common bacteria"), with no per-drug variants at the
  analyte-code level. `_bb_microbiology`'s susceptibility Observation code now resolves
  via `code_mapping_microbiology_susceptibility.yaml` (keyed by the `antibiotic_loinc`
  value already stored on `SusceptibilityResult` — no CIF schema change) +
  `system_key_for("microbiology", ...)` (reusing the same kind registered for culture
  codes). All 10 antibiotics (ampicillin/cefazolin/ceftriaxone/cefepime/ciprofloxacin/
  gentamicin/vancomycin/piperacillin_tazobactam/meropenem/trimethoprim_sulfamethoxazole)
  map to `6C010`. Same country-gated-with-coherent-fallback shape as the culture fix and
  the `_build_lab_observation` hardening (code system co-varies with whether the map
  actually resolved the key). Implemented directly with TDD on `master` (no subagent
  chain — pattern fully precedented by the same-day culture fix, no new design
  decisions). `pytest -m unit` 1069 passed.
- ~~CSV adapter JP microbiology code consistency~~ — **FIXED (session 35, 2026-07-04,
  same-day follow-up)**: `csv_adapter.py`'s `microbiology.csv` previously dumped the raw
  `test_loinc`/`antibiotic_loinc` CIF fields verbatim, so JP CSV output showed US LOINC
  values even after the FHIR builder started emitting JLAC10 — a live inconsistency
  between the two output formats for the same data. Fixed by (1) extracting
  `resolve_culture_code(specimen, test_loinc, country)` and
  `resolve_susceptibility_code(antibiotic_loinc, country)` out of `_bb_microbiology` in
  `_fhir_microbiology.py` into public functions (single source of truth per
  `docs/CONTRIBUTING-modules.md`'s "owner module public accessor" convention — no diff in
  `_bb_microbiology`'s behavior, verified by the full pre-existing microbiology test suite
  passing unchanged after the refactor); (2) `csv_adapter.py` now imports both and renames
  the columns from `test_loinc`/`antibiotic_loinc` (a column name that asserted a fixed
  code system) to `test_code`/`test_code_system` + `antibiotic_code`/
  `antibiotic_code_system` (a code/system pair, mirroring how FHIR always carries
  system+code together) — user explicitly chose the rename over keeping the misleading
  old names. No existing test referenced the old column names (checked before renaming).
  `pytest -m unit` 1072 passed.
- ~~`_build_lab_observation` unconditional code/system pairing latent defect~~ — **FIXED
  (2026-07-04, direct TDD fix on master)**: `clinosim/modules/output/_fhir_observations.py`
  now resolves `code_system_key` inside the same branch as `code_value` (`if lab_name in
  code_map: ... else: code_value = order.get("order_code", ""); code_system_key = "loinc"`),
  mirroring the fix Task 3 applied to `_bb_microbiology` in the JP microbiology JLAC10
  mapping chain (found during that task's review, this entry originally filed as a
  deferred follow-up). Regression tests in
  `tests/unit/output/test_fhir_observations_code_system.py` (JP mapped → jlac10, JP
  unmapped → loinc fallback stays coherent, US unaffected). No behavior change for real
  cohorts today (both `code_mapping_lab.yaml` files have full coverage, so the fallback
  branch was and remains dead for current data) — this hardens against a future
  incomplete-coverage regression. `pytest -m unit` (1062 passed) and `-m integration`
  (278 passed, 5 skipped, 1 xfailed) both green.

## clinical_course severity/archetype wiring fix — deferred scope (2026-07-05 → mostly RESOLVED 2026-07-06)

> **★ 2026-07-06 session 38 で本節の大半が解決**。この deferred 群(重症度二重システム / 孤児 YAML
> キー / `extra="forbid"` / course_archetypes 欠如 / I10 stage / person.age)は **FHIR completeness
> ゴール**の下に再構成され、9 チェーンで消化された。追跡台帳 =
> **`docs/design-notes/2026-07-06-fix-point-registry.md`**(FP-*)、考察 =
> `2026-07-06-fhir-completeness-and-data-model-unification.md`、規約 =
> `docs/design-guides/data-model-and-completeness-conventions.md`。
>
> **本節 sub-item の解決状況:**
>
> | 項目(以下の見出し) | 状態 | FP / commit |
> |---|---|---|
> | 重症度二重システム(severity.distribution vs severity_beta) | ✅ DONE | FP-SEV-MODEL / AD-67(疾患YAML canonical、severity.py、severity_beta 撤廃) |
> | `archetype_modifiers` dead | ✅ DONE | FP-YAML-2b / AD-68(select_archetype に配線) |
> | smaller orphaned keys(differential_diagnosis / rehabilitation / precipitants / prerequisite) | ✅ DONE | FP-YAML-2(削除) |
> | `extra="forbid"` rollout | ✅ DONE | FP-YAML-3 / AD-69 |
> | `incidence.risk_multipliers` unread(第3の disconnected data) | ⬜ OPEN | 未着手(registry follow-up 候補) |
> | `disease_risk_multipliers.fall_from_height: {F10}` dead | ⬜ OPEN | 上と同時に検討 |
> | 9 diseases no `course_archetypes` | 🟡 PARTIAL | FP-ARCH-1 で HF + subdural DONE、残 7 trauma 疾患(FP-ARCH-2/3) |
> | I10 STAGE_SEVERITY no-op | ✅ DONE | FP-I10(stage→BP baseline 消費) |
> | `person.age` multi-year 未対応 | ⬜ OPEN | FP-AGE(as-of 化 2 フェーズ、未着手) |
>
> **新規 follow-up(session 38 実装中に発見、registry 記載)**: (1) 疾患内在 modifier ~32 種
> (`severity.py:RESERVED_INTRINSIC_CONDITIONS` + archetype 側)は scenario-flag 機構待ちで skip、
> (2) `Condition.stage.type` の SNOMED 385356007 "Tumor stage finding" が全 6 staged 疾患で誤流用、
> (3) 死蔵モデル field 3 件(expected_vital_distributions / reference_ranges / drug_interactions)、
> (4) HF `initial_state_impact` の `sodium_status` 未認識 state var、(5) cohort-level 統計
> completeness audit 軸。詳細は registry 参照。
>
> 以下の原調査 file:line 詳細は履歴として保持(registry から参照)。

Full context: `docs/superpowers/specs/2026-07-05-clinical-course-severity-archetype-wiring-design.md`.
Comprehensive multi-agent code review + brainstorming session found a much
larger structural issue while fixing two concrete bugs (course_archetypes
wiring, severity_severe stub) — deliberately deferred per scope discipline.

### Two disconnected severity systems: disease YAML `severity.distribution`/`modifiers` vs locale `severity_beta`

`clinosim/modules/disease/protocol.py`'s `DiseaseProtocol` has no
`model_config = ConfigDict(extra="forbid")`, so the `severity:` block's
`distribution`/`modifiers` sub-keys (present in all 30 disease YAMLs, citing
real clinical literature — TIMI score, ACC/AHA, Tokyo Guidelines, JROAD, etc.)
are silently discarded at load time and never read by any Python code
(grep-verified: zero references to `protocol.severity`, `moderate_multiplier`,
`severe_multiplier`, `mild_multiplier` anywhere). The severity actually used
in simulation comes from an unrelated `severity_beta` 2-parameter Beta
distribution in `clinosim/locale/{us,jp}/demographics.yaml`, which is
comorbidity-blind. Options: (a) wire disease YAML's `severity.distribution` +
`modifiers` into the sampling path, replacing or supplementing
`severity_beta` (a real architecture change touching `population/engine.py`
and `simulator/inpatient.py`); (b) formally retire the disease-YAML
`severity:` block as non-machine-readable documentation (delete or clearly
annotate it, decide whether to keep the literature citations as comments);
(c) some hybrid (e.g. `severity.modifiers` becomes a small, well-scoped
comorbidity adjustment to the existing `severity_beta` draw, while
`distribution` stays descriptive-only). This is a genuine design decision,
not a mechanical fix — needs its own brainstorming session.

### `archetype_modifiers` YAML block is dead (28/30 disease YAMLs)

Meant to shift `course_archetypes` probabilities based on patient conditions
(e.g. `age_over_75`, `heart_failure`, `valvular_heart_disease`) — but
`select_archetype` (`clinosim/modules/clinical_course/engine.py:82-97`) has
its own separate, hardcoded severity/profile modifier logic instead of
reading this YAML block at all. Same missing-`extra="forbid"` root cause as
above. Options: wire it in (would need to decide how it composes with the
existing hardcoded modifiers — replace, or apply both?), or delete it from
the 30 YAMLs as abandoned/aspirational content.

### Smaller orphaned/duplicated disease-YAML top-level keys

Also silently dropped due to the missing `extra="forbid"` guard:
`differential_diagnosis` (5 files — `asthma_exacerbation`,
`deep_vein_thrombosis`, `hemorrhagic_stroke`, `influenza`,
`vertebral_compression_fracture` — duplicate the live nested
`diagnostic.differential`, dead top-level copy, active dual-maintenance
drift risk since nothing keeps the two in sync); `diagnostic_difficulty`
(top-level copy dead, only `diagnostic.diagnostic_difficulty` nested inside
the `diagnostic:` dict is read, at `inpatient.py:613`); `rehabilitation` (7
trauma/fracture files); `precipitants` (DKA); `prerequisite` (asthma); and a
fully vestigial `readmission: dict = {}` schema field with zero YAML usage
and zero Python readers. Each needs its own small decision (wire vs delete)
before `extra="forbid"` can be turned on safely.

### `model_config = ConfigDict(extra="forbid")` rollout blocked on the above

Cannot be added to `DiseaseProtocol` (`clinosim/modules/disease/protocol.py`)
until every orphaned key above is resolved (wired or deleted from all 30
YAMLs), or every existing disease YAML will fail to load. This is the actual
fix that would have caught all of the above at author time — worth
prioritizing once the per-key decisions are made.

### 9 diseases with no `course_archetypes` block

`heart_failure_exacerbation` plus 8 trauma/fracture diseases
(`crush_injury_hand`, `electrical_injury`, `fall_from_height`, `hip_fracture`,
`industrial_burn_severe`, `subdural_hematoma`, `traffic_accident_severe`,
`wrist_fracture_surgical`) have no `course_archetypes` block, so they
silently use the generic `_FALLBACK_PROBABILITIES`/`_FALLBACK_TRAJECTORIES`.
Plausibly acceptable for trauma (generic post-op recovery shape); a real gap
for `heart_failure_exacerbation`, which has a well-known diuresis-driven
recovery curve that isn't modeled. Needs per-disease YAML authoring, not a
code change.

### Disease YAML's own `incidence.risk_multipliers` list is entirely unread (third disconnected-data instance)

Discovered while investigating a locale-file dead-multiplier finding (F10
below): disease YAMLs' own `incidence.risk_multipliers` field (a list of
`{condition: "...", multiplier: ...}` dicts, e.g. `atrial_fibrillation_rvr.yaml`'s
`hypertension`/`heart_failure`/`alcohol_dependence`/etc., or
`fall_from_height.yaml` / `subdural_hematoma.yaml` /
`traffic_accident_severe.yaml`'s `F10` condition) is grep-confirmed to have
**zero** Python readers anywhere in the codebase. `population/engine.py`'s
actual disease-incidence risk multiplier mechanism
(`demo.get("disease_risk_multipliers", {})`, consumed at
`_disease_monthly_rate_from_locale`) reads an entirely separate, differently-shaped
top-level key from **locale** `demographics.yaml` (`{disease_id: {code: mult}}`,
keyed by `chronic_conditions` codes), which is hand-authored independently and
does NOT derive from the disease YAML's own list. This is the same
"documented-in-disease-YAML, never wired" bug class as the `severity.distribution`
finding above — same missing-`extra="forbid"` root cause, same scope
(architecture decision: should locale's `disease_risk_multipliers` be derived
from disease YAML's `incidence.risk_multipliers` instead of hand-duplicated?
or is disease YAML's list purely descriptive and should be deleted/annotated?).
Needs its own brainstorming session; do not fix piecemeal per-disease.

### `disease_risk_multipliers.fall_from_height: {F10: 2.0}` is permanently dead (both locales)

Symptom of the above: `F10` (ICD-10 "alcohol related disorders") is used as a
`chronic_conditions` code key in `clinosim/locale/{us,jp}/demographics.yaml`'s
`disease_risk_multipliers.fall_from_height`, but `F10` is never a key in
either country's `chronic_prevalence` block, so no person can ever have it in
`person.chronic_conditions` — the multiplier can never fire. Note a second,
narrower naming inconsistency even after that's fixed: disease YAMLs mix two
different key conventions for the same concept across different files —
`F10` (ICD-10-code-style, used in `fall_from_height`/`subdural_hematoma`/
`traffic_accident_severe`) vs `alcohol_dependence` (condition-name-style, used
in `acute_pancreatitis`/`aspiration_pneumonia`/`atrial_fibrillation_rvr`/
`bacterial_pneumonia`/`gi_bleeding`/`sepsis`/`liver_cirrhosis_decompensated`) —
neither convention currently resolves to a real sampled `chronic_conditions`
entry. Fold into the `incidence.risk_multipliers` wiring decision above rather
than patching F10 alone.

### Hypertension (I10) is the 6th graded-stage condition missing from `STAGE_SEVERITY` — currently a no-op

`clinosim/modules/patient/activator.py:37-44`'s `STAGE_SEVERITY` dict covers
N18/I50/J44/J45/I25 (the 5 conditions fixed this session/last) but not I10,
even though `_generate_stage` (`activator.py:70-71`) already samples a
graded I10 stage ("Stage 1"/"Stage 2") and a hardcoded vitals bump
(`activator.py:262-264`, `systolic_bp += 10, diastolic_bp += 5`) is identical
for both stages regardless. **Currently a true no-op fix**: `physiology/engine.py:initialize_state`
has no I10 branch consuming `severity_score` at all, so adding I10 to
`STAGE_SEVERITY` alone would produce a `severity_score` value nothing reads —
not worth doing until hypertension severity modeling (a real physiological
consumer) is added. Revisit together, not `STAGE_SEVERITY` alone.

### `person.age` never advances across a multi-year simulation

`generate_population` sets `age`/`date_of_birth` once
(`clinosim/modules/population/engine.py`); nothing increments `age` as the
simulation clock advances across `(year, month)` in
`simulator/engine.py:125-142`, even though `date_of_birth` is stored and could
derive current age. For the common single-year default run this has no
effect; for a genuinely multi-year run, age-based incidence lookups,
`hospitalization_threshold_modifier_by_age`, and the age-gated screening/flu-vax
logic in `generate_healthcare_calendar` all use a frozen age for the entire
run — cohort aging never happens. Fix is medium-complexity (derive age from
`dob` at each of several call sites rather than reading the static field);
deferred rather than folded into this session's quick-fix batch since it
touches multiple files for a scenario (multi-year runs) not in common use
today.

---

# Session Resume Prompt

次 session の cold-start 用 resume prompt(STEP 0-7 + プロジェクトコンセプト + logic
design 完全網羅)は別 file に切出し済:

→ **[`docs/session-resume/next.md`](docs/session-resume/next.md)**

Session wrap ごとに同 file を上書き更新(以前のは git history 参照)。
