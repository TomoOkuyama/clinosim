"""Vulture by-design whitelist.

Vulture (https://github.com/jendrikseipp/vulture) reports symbols that
appear unused by static analysis. Many of its findings are legitimate
patterns that must not be deleted: dataclass fields (read through instance
attribute access), Protocol / ABC method signatures dispatched by
duck-typing, symbols consumed only by tests (vulture only scans
``clinosim/``), YAML-driven schema fields populated at load time, and
re-exports through ``__init__.py``.

Each entry below is a reference to a symbol that vulture reports as unused
but the maintainers have decided to keep. Every entry carries a one-line
comment naming the category and the reason. When adding a new entry:

1. Confirm the finding is a genuine false positive (not dead code the
   scanner correctly caught).
2. Add the entry under the correct category section below.
3. If a new category emerges, add a section header explaining what it is.

Referenced from CI as
``vulture clinosim/ .vulture-whitelist.py --min-confidence 60``. Any
finding not covered by this file causes the ``vulture dead-code`` CI job
to fail.

Policy reference:
`docs/design-guides/documentation-and-code-quality-policy.md` §6
(dead-code hygiene).
"""

# The whitelist works by referencing each symbol so vulture treats it as
# "used". Bare identifier references are ambiguous (they can look like
# imports of missing modules), so this file assigns them to a dummy sink
# to make it clear they are intentional references, not real imports.


class _WhitelistSink:
    """Dummy object whose attribute lookups mark symbols as used.

    Vulture treats ``sink.SYMBOL`` as a read of ``SYMBOL``, which is
    exactly what we need to suppress its "unused" finding for that name.
    """

    def __getattr__(self, name: str) -> object:
        return None


_ = _WhitelistSink()


# =============================================================================
# Category A — dataclass / Pydantic fields
# =============================================================================
# Vulture flags every class-body assignment in a dataclass or Pydantic model
# as "unused variable" because it does not model attribute reads through the
# instance. The fields below are all read through their class instances by
# consumers elsewhere in the code, tests, or the FHIR output layer. Deleting
# any of them would change the public data shape.

# ----- clinosim/types/*.py (dataclass-based) -----

# types/clinical.py
_.presenting_symptoms  # types/clinical.py:92
_.admission_diagnosis_code  # types/clinical.py:104
_.admission_diagnosis_system  # types/clinical.py:105
_.working_diagnoses  # types/clinical.py:106
_.diagnosis_correct  # types/clinical.py:111
_.overcalled_diagnoses  # types/clinical.py:113
_.generator_metadata  # types/clinical.py:130
_.author_practitioner_id  # types/clinical.py:148
_.related_procedure_id  # types/clinical.py:149
_.content_type  # types/clinical.py:160
_.generator_config  # types/clinical.py:183
_.document_counts_by_type  # types/clinical.py:187
_.doc_types_enabled  # types/clinical.py:188
_.llm_cost_report  # types/clinical.py:190
_.partial  # types/clinical.py:199

# types/config.py
_.discharge_criteria  # types/config.py:32
_.target_los_multiplier  # types/config.py:33
_.diagnosis_code_system  # types/config.py:36
_.drug_code_system  # types/config.py:37
_.lab_code_system  # types/config.py:38
_.procedure_code_system  # types/config.py:39
_.bedrock_gateway  # types/config.py:56 (StrEnum member)
_.anthropic_direct  # types/config.py:57 (StrEnum member)
_.openai_compatible  # types/config.py:58 (StrEnum member)
_.local  # types/config.py:59 (StrEnum member)
_.timeout_seconds  # types/config.py:62
_.max_tokens_per_run  # types/config.py:67
_.fallback_on_budget_exceeded  # types/config.py:68
_.cache_enabled  # types/config.py:78
_.cache_max_entries  # types/config.py:79
_.cache_persist_to_disk  # types/config.py:80
_.model_config  # types/config.py:113 (Pydantic ConfigDict)
_.clinical_notes  # types/config.py:139
_.disease_modules  # types/config.py:192
_.cif_format  # types/config.py:201

# types/device.py
_.snomed_code  # types/device.py:20
_.placement_indication  # types/device.py:23

# types/diagnosis.py
_.confirmed  # types/diagnosis.py:24

# types/document.py
_.structured_form_yaml  # types/document.py:76
_.materialized_facts  # types/document.py:171
_.complications_expected  # types/document.py:224
_.scenario_hint  # types/document.py:235
_.llm_replaceable  # types/document.py:236

# types/encounter.py (largest single-file cluster — 47 fields)
_.episode_id  # types/encounter.py:58
_.admitting_physician_id  # types/encounter.py:63
_.discharging_physician_id  # types/encounter.py:64
_.chief_complaint_ja  # types/encounter.py:73 (JP locale field)
_.disease_event_id  # types/encounter.py:74
_.CONSULTATION  # types/encounter.py:114 (StrEnum member)
_.INFECTION_CONTROL  # types/encounter.py:117 (StrEnum member)
_.performed_by  # types/encounter.py:133
_.reference_range  # types/encounter.py:137
_.specimen_note  # types/encounter.py:140
_.refusal_reason  # types/encounter.py:156
_.prescription_id  # types/encounter.py:163
_.reason_condition  # types/encounter.py:192
_.imaging_modality  # types/encounter.py:200
_.imaging_body_site_code  # types/encounter.py:201
_.imaging_views  # types/encounter.py:202
_.imaging_spec_meta  # types/encounter.py:203
_.on_supplemental_oxygen  # types/encounter.py:233
_.oxygen_flow_rate_lpm  # types/encounter.py:234
_.oxygen_delivery_device  # types/encounter.py:235
_.measured_by  # types/encounter.py:237
_.data_source  # types/encounter.py:238
_.news2_score  # types/encounter.py:239
_.feeding  # types/encounter.py:249 (Barthel index component)
_.bathing  # types/encounter.py:250
_.grooming  # types/encounter.py:251
_.dressing  # types/encounter.py:252
_.bowel_control  # types/encounter.py:253
_.bladder_control  # types/encounter.py:254
_.toilet_use  # types/encounter.py:255
_.transfers  # types/encounter.py:256
_.stairs  # types/encounter.py:258
_.braden_total  # types/encounter.py:266 (Braden pressure-ulcer scale)
_.braden_sensory  # types/encounter.py:267
_.braden_moisture  # types/encounter.py:268
_.braden_activity  # types/encounter.py:269
_.braden_mobility  # types/encounter.py:270
_.braden_nutrition  # types/encounter.py:271
_.braden_friction  # types/encounter.py:272
_.morse_total  # types/encounter.py:273 (Morse fall scale)
_.fall_risk_level  # types/encounter.py:274
_.intake_other_ml  # types/encounter.py:284
_.output_drain_ml  # types/encounter.py:286
_.output_other_ml  # types/encounter.py:287
_.vaccine_cvx  # types/encounter.py:302
_.dose_number  # types/encounter.py:306
_.lot_number  # types/encounter.py:307

# types/family_history.py
_.condition_codes  # types/family_history.py:17

# types/hai.py
_.source_device_id  # types/hai.py:23
_.icd10_code  # types/hai.py:24
_.snomed_code  # types/hai.py:25
_.culture_specimen_id  # types/hai.py:28

# types/identity.py (JP マイナンバー / insurance card fields)
_.has_id_card  # types/identity.py:25 (JP マイナンバーカード保有)
_.id_card_linked_to_insurance  # types/identity.py:26 (JP マイナ保険証 登録)
_.member_id  # types/identity.py:36
_.group_symbol  # types/identity.py:37
_.card_acquired_on  # types/identity.py:50
_.insurance_linked_on  # types/identity.py:51
# (types/identity.py:53 `enrollment_on` moved to Category F below — no callers)

# types/imaging.py
_.series_uid  # types/imaging.py:23
_.series_number  # types/imaging.py:24
_.report_id  # types/imaging.py:41
_.findings_text_ja  # types/imaging.py:44 (JP locale field)
_.impression_text_ja  # types/imaging.py:46 (JP locale field)
_.study_instance_uid  # types/imaging.py:60
_.started_datetime  # types/imaging.py:66

# types/microbiology.py
_.specimen_snomed  # types/microbiology.py:35
_.quantitation  # types/microbiology.py:41

# types/output.py
_.clinosim_version  # types/output.py:35
_.generation_timestamp  # types/output.py:36
_.simulation_period_start  # types/output.py:40
_.simulation_period_end  # types/output.py:41
_.total_patients_generated  # types/output.py:43
_.llm_mode  # types/output.py:44
_.nursing_risk_assessments  # types/output.py:67
_.immunizations  # types/output.py:68
_.family_history  # types/output.py:69
_.code_status  # types/output.py:70
_.care_level  # types/output.py:71
_.death_day  # types/output.py:81

# types/patient.py
_.drug_metabolism_rate  # types/patient.py:17 (physiology field)
_.symptom_reporting_bias  # types/patient.py:22
_.dvt_susceptibility  # types/patient.py:24
_.line1  # types/patient.py:46 (address)
_.line2  # types/patient.py:47
_.phone_primary  # types/patient.py:57
_.email  # types/patient.py:58
_.emergency_contact_name  # types/patient.py:59
_.emergency_contact_phone  # types/patient.py:60
_.emergency_contact_relationship  # types/patient.py:61
_.name_script  # types/patient.py:71
_.controlled  # types/patient.py:81
_.rh_factor  # types/patient.py:132 (blood type Rh)
_.height_cm  # types/patient.py:133
_.weight_kg  # types/patient.py:134
_.employment_status  # types/patient.py:143
_.health_literacy  # types/patient.py:156

# types/population.py
_.discharge_diagnoses  # types/population.py:33
_.residual_inflammation  # types/population.py:35
_.was_readmission  # types/population.py:37
_.has_visited_hospital  # types/population.py:70
_.last_disease_id  # types/population.py:74
_.protocol_source  # types/population.py:110

# types/procedure.py
_.procedure_id  # types/procedure.py:23
_.procedure_code_jp  # types/procedure.py:28
_.procedure_code_us  # types/procedure.py:29
_.end_datetime  # types/procedure.py:35
_.duration_minutes  # types/procedure.py:36 (also :79 for another class)
_.primary_surgeon_id  # types/procedure.py:39
_.assistant_ids  # types/procedure.py:41
_.estimated_blood_loss_ml  # types/procedure.py:48
_.specimens_sent  # types/procedure.py:49
_.implants_used  # types/procedure.py:50
_.intraop_complications  # types/procedure.py:51
_.preop_diagnosis  # types/procedure.py:54
_.postop_diagnosis  # types/procedure.py:55
_.complication_codes  # types/procedure.py:66
_.session_id  # types/procedure.py:74
_.therapy_type  # types/procedure.py:77
_.patient_participation  # types/procedure.py:82
_.functional_progress  # types/procedure.py:84

# types/staff.py
_.qualification_year  # types/staff.py:21
_.phone  # types/staff.py:23
_.email  # types/staff.py:24
_.name_phonetic  # types/staff.py:30
# (types/staff.py:40 `get_by_id` moved to Category C — called from tests/unit/test_staff_types.py)

# types/triage.py
_.acuity_score  # types/triage.py:21
_.chief_complaint_summary  # types/triage.py:22

# ----- clinosim/modules/disease/protocol.py (Pydantic BaseModel) -----
# Pydantic fields — populated from YAML at load time, read through
# `disease_protocol.<field>` by consumers in `patient/`, `enricher/`,
# `narrative/`.
_.mild  # disease/protocol.py:400 (severity variant)
_.moderate  # disease/protocol.py:401
_.severe  # disease/protocol.py:402
_.general  # disease/protocol.py:409 (physical-exam category)
_.cardiovascular  # disease/protocol.py:410
_.respiratory  # disease/protocol.py:411
_.abdominal  # disease/protocol.py:412
_.neurological  # disease/protocol.py:413
_.emergency  # disease/protocol.py:429
_.diet_lifestyle  # disease/protocol.py:430
_.hpi_template  # disease/protocol.py:441
_.physical_exam_findings  # disease/protocol.py:442
_.discharge_instructions  # disease/protocol.py:443
_.only_if_severity  # disease/protocol.py:470
_.model_config  # disease/protocol.py:479 (Pydantic ConfigDict)
_.presenting_symptoms  # disease/protocol.py:485
_.expected_lab_distributions  # disease/protocol.py:496
_.expected_vital_distributions  # disease/protocol.py:497
_.drug_interactions  # disease/protocol.py:507
_.causes_myocardial_injury  # disease/protocol.py:521

# ----- clinosim/modules/encounter/protocol.py (Pydantic BaseModel) -----
# JP-locale narrative fields (subjective_ja / objective_ja / plan_ja /
# chief_complaint_ja / hpi_ja / physical_exam_ja / ed_workup_summary_ja /
# disposition_ja) — populated by the JP narrative pipeline and read by
# `modules/document/narrative/*` consumers.
_.subjective_ja  # encounter/protocol.py:25
_.objective_ja  # encounter/protocol.py:26
_.plan_ja  # encounter/protocol.py:28
_.general  # encounter/protocol.py:34 (physical-exam categories)
_.cardiovascular  # encounter/protocol.py:35
_.respiratory  # encounter/protocol.py:36
_.abdominal  # encounter/protocol.py:37
_.neurological  # encounter/protocol.py:38
_.musculoskeletal  # encounter/protocol.py:39
_.chief_complaint_ja  # encounter/protocol.py:45
_.hpi_ja  # encounter/protocol.py:46
_.physical_exam_ja  # encounter/protocol.py:47
_.ed_workup_summary_ja  # encounter/protocol.py:48
_.disposition_ja  # encounter/protocol.py:49
_.common_triage_levels  # encounter/protocol.py:55
_.outpatient_soap_template  # encounter/protocol.py:66
_.ed_note_template  # encounter/protocol.py:67
_.ed_triage_template  # encounter/protocol.py:68
_.model_config  # encounter/protocol.py:85 (Pydantic ConfigDict)
_.icd10_code  # encounter/protocol.py:88

# ----- clinosim/modules/facility/hospital_state.py (dataclass) -----
# Hospital-operational-state fields — read by scheduler / enricher /
# `add_to_queue` (indirect via `getattr(self, f"{resource}_queue")`) and
# by `tests/unit/test_order_queue_replay.py` via `hs.<field>` direct
# reads. Vulture cannot see the `getattr` indirection; the direct
# reads in tests satisfy some but not all of these — whitelist covers
# the remainder.
_.lab_queue  # facility/hospital_state.py:58 (indirect via getattr in add_to_queue)
_.ct_queue  # facility/hospital_state.py:59 (indirect via getattr in add_to_queue)
_.mri_queue  # facility/hospital_state.py:60
_.xray_queue  # facility/hospital_state.py:61
_.ultrasound_queue  # facility/hospital_state.py:62
_.or_queue  # facility/hospital_state.py:63
_.ed_crowding  # facility/hospital_state.py:40
_.nursing_staff  # facility/hospital_state.py:45 (also read as attribute at :67)
_.pharmacy_staff  # facility/hospital_state.py:46 (also read as attribute at :68, :76)
# Symmetric queue-management method — public API on HospitalState
# (documented in facility/README.md). Currently no live caller after
# `simulator/des_engine.py` was removed as orphan; kept for the
# add_to_queue / release_from_queue pairing so downstream code can
# still model resource release deterministically.
_.release_from_queue  # facility/hospital_state.py:221


# =============================================================================
# Category B — Protocol / ABC method signatures dispatched by duck-typing
# =============================================================================
# The abstract method on the base class and each concrete implementation
# are all reachable through the Protocol / ABC interface — vulture sees
# only the interface, not the dispatch. Deleting any single method would
# break the interface contract.

# LLM service provider interface: base class + 3 concrete implementations.
_.health_check  # llm_service/providers/base.py:42 (ABC method)
_.health_check  # llm_service/providers/bedrock.py:130 (concrete)
_.list_models  # llm_service/providers/bedrock.py:147 (concrete)
_.health_check  # llm_service/providers/mock.py:49 (concrete)
_.list_models  # llm_service/providers/mock.py:52 (concrete)
_.health_check  # llm_service/providers/ollama.py:76 (concrete)
_.list_models  # llm_service/providers/ollama.py:85 (concrete)

# LLM service: mock provider observability attributes for test assertions.
_.last_prompt  # llm_service/providers/mock.py:20 (set at :34)
_.last_system_prompt  # llm_service/providers/mock.py:21 (set at :35)

# LLM service prompt registry: probe method used by callers deciding
# whether to render a prompt at all.
_.has  # llm_service/prompt_registry.py:137

# FHIR labs coding-package: multi-class specimen-material coding surface.
# Each class holds its own `specimen_material_cs_uri` / `_display` because
# JP-CLINS profile requires per-context coding; called through the class
# selected at emit time. Vulture reports each as "unused method" because
# no single call-site touches all of them.
_.specimen_material_cs_uri  # fhir_r4/labs/coding_package.py:295
_.specimen_material_display  # fhir_r4/labs/coding_package.py:301
_.specimen_material_cs_uri  # fhir_r4/labs/coding_package.py:333
_.specimen_material_display  # fhir_r4/labs/coding_package.py:337
_.specimen_material_cs_uri  # fhir_r4/labs/coding_package.py:477
_.specimen_material_display  # fhir_r4/labs/coding_package.py:480


# =============================================================================
# Category C — Test-only public API
# =============================================================================
# Vulture only scans `clinosim/`; it does not see uses from `tests/`.
# Each entry below is used by one or more test files (verified by grep
# across `tests/`).

_.create_test_patient  # modules/patient/test_patient.py:17 (tests/unit/test_patient.py)
_.build_narrative_context  # modules/document/narrative/context.py:12 (tests/unit/modules/document/narrative/test_context.py)
_.run_benchmarks  # modules/validator/benchmarks.py:69 (tests/e2e/test_beta.py)
_.reset_for_test  # simulator/log.py:174 (test-only hook for log-buffer reset)
_._reset_for_test  # audit/registry.py:40 (test-only hook for registry reset)
_.get_by_id  # types/staff.py:40 (used in tests/unit/test_staff_types.py)


# =============================================================================
# Category D — Test-referenced constants
# =============================================================================
# Module-scope constants imported and asserted by unit tests. Not called
# from production code by name (production accesses via the string value),
# but the tests need the symbolic name for readability.

_.RADIOLOGY_DR_ID_PREFIX  # fhir_r4/labs/diagnostic_report.py:54 (tests/unit/output/test_fhir_radiology_dr.py imports)
_.ABX_NARROW_SUFFIX  # modules/antibiotic/engine.py:52 (tests/unit/test_antibiotic_id_length.py imports)
_.ICD_COUGH  # modules/diagnosis/nonspecific_codes.py:33 (tests/unit/simulator/test_r05_cough_not_wrong_diagnosis.py)
_.ARCHETYPE_EXPRESSION_VARS  # modules/clinical_course/engine.py:86 (tests/unit/modules/clinical_course/test_archetype_modifiers.py)

# session-88j: hedging helpers only called from tests today (template
# generator will consume them in a follow-up PR when the hedging
# language layer is wired end-to-end into the composer).
_.hedged_phrase  # modules/document/narrative/_hedging.py:34 (tests/unit/modules/document/narrative/test_hedging.py imports)
_.has_topic  # modules/document/narrative/_hedging.py:87 (same test file)

# session-88j Phase B: JA localizer helpers exported for future use —
# risk-level / Barthel-band tokens appear in narrative context payloads
# but no code path renders them yet. Tests pin the mapping so a future
# consumer inherits an already-validated behavior.
_._localize_risk_level_ja  # modules/document/narrative/replacement_strategy.py:234 (tests/unit/test_narrate_context_localization_ja.py imports)
_._localize_barthel_band_ja  # modules/document/narrative/replacement_strategy.py:239 (same test file)


# =============================================================================
# Category E — Attributes set by simulator, read by output / eval layer
# =============================================================================
# The simulator writes these fields onto Patient / Encounter / Order
# objects. Vulture flags them as "unused attribute" because the reads
# happen in a different module — typically the FHIR output builders,
# audit axes, or eval reporters — through attribute access on the
# serialised dataclass, or through `getattr(...)` in a generic serialiser.
# Deleting any of these fields would silently drop data from the output.

# Simulator writes chief_complaint_ja / disease_event_id / physician IDs
# onto encounters at simulation time; the FHIR builder in
# `modules/output/fhir_r4/encounters/` reads them.
_.chief_complaint_ja  # simulator/emergency.py:93
_.admitting_physician_id  # simulator/emergency.py:301
_.discharging_physician_id  # simulator/emergency.py:302
_.chief_complaint_ja  # simulator/inpatient.py:226
_.discharging_physician_id  # simulator/inpatient.py:496
_.admitting_physician_id  # simulator/inpatient.py:497
_.discharging_physician_id  # simulator/inpatient.py:538
_.chief_complaint_ja  # simulator/outpatient.py:94
_.admitting_physician_id  # simulator/outpatient.py:277
_.discharging_physician_id  # simulator/outpatient.py:278

# Simulator tracks first-visit status for enricher / diagnosis logic.
_.has_visited_hospital  # simulator/engine.py:404
_.has_visited_hospital  # simulator/helpers.py:108
_.last_disease_id  # simulator/helpers.py:114

# Diagnosis engine sets confirmation flag consumed downstream by FHIR builder.
_.confirmed  # modules/diagnosis/engine.py:144

# Imaging engine sets series UID for DICOM identifier chain.
_.series_uid  # modules/imaging/engine.py:560

# Observation enrichers write derived fields.
_.materialized_facts  # modules/document/narrative/passes.py:265
_.quantitation  # modules/observation/microbiology.py:196
_.news2_score  # modules/observation/nursing_enricher.py:43


# =============================================================================
# Category F — DELETE candidates, pending removal in a follow-up PR
# =============================================================================
# These are the symbols that appear to be genuinely unused after grep
# verification across `clinosim/` and `tests/` — no consumers, no test
# coverage, no re-exports through `__init__.py`. They are temporarily
# whitelisted here so this PR can establish the vulture guardrail without
# also shipping code deletions.
#
# **Follow-up PR removes both the symbols below AND their entries here.**
# See the "Delete candidates" section of the vulture-scan review report.

# Dead functions (no callers found in either clinosim/ or tests/):
_.load_terminology  # locale/loader.py:188 (only README mention; API-doc drift)
_.load_formatting  # locale/loader.py:206 (only README mention; API-doc drift)
_.get_default_cache  # modules/document/narrative/cache.py:133
_.generate_encounter_timeline  # modules/encounter/engine.py:177 (58 LOC; only README mention)
_.calculate_imaging_result_time  # modules/order/engine.py:555 (49 LOC; only README mention)
_.format_lab_trends  # modules/output/hospital_course_extractor.py:561 (21 LOC; only README mention)
_.run_consistency_checks  # modules/validator/consistency.py:55 (28 LOC; only README mention)
_._generate_name  # modules/staff/engine.py:324 (5 LOC; shadowed by _generate_name_pair)

# Dead methods on live classes:
_.from_config_file  # modules/llm_service/engine.py:256 (superseded by factory.build_from_config_file)
_._resolve_daily_trajectory  # modules/document/narrative/template_generator.py:2545
_.override  # types/config.py:245 (SimulatorConfig.override, no callers)
_.enrollment_on  # types/identity.py:53 (no callers)

# Dead classes:
_.DailyTrajectoryEntry  # modules/disease/protocol.py:446 (only referenced in a comment)
_.ResidentLike  # modules/identity/base.py:21 (Protocol never annotated on any function param)
_.DESEngine  # simulator/des_engine.py:87 (245 LOC unused DES engine)

# DESEngine's internal attributes / methods — deleted with the class.
_.event_id  # simulator/des_engine.py:31 (DESEngine.event_id)
_.event_id  # simulator/des_engine.py:60
_.pending_labs  # simulator/des_engine.py:82
_.pending_imaging  # simulator/des_engine.py:83
_.scenario_step  # simulator/des_engine.py:84
_.completed_records  # simulator/des_engine.py:105
_.seed_events  # simulator/des_engine.py:112

# Dead locals inside live functions (unused assignments not caught by ruff F841
# because they land on class body or module level rather than function local).
_.hours  # benchmarks/sepsis.py:43 (100 % confidence)
_.n_positive  # benchmarks/harness.py:32
_.cohort_filter  # audit/registry.py:20
_.per_event_check  # audit/registry.py:21
_.population_size  # simulator/memoize.py:118
_.clinosim_git_commit  # simulator/enumerate.py:439
_.total_patients  # simulator/enumerate.py:444
_.cache_hit  # llm_service/engine.py:206
_.fallback_reason  # llm_service/engine.py:207 (also :361, :379, :402)
_.chosen_option  # llm_service/engine.py:208
_.reasoning  # llm_service/engine.py:209
_.alt_arch  # modules/document/narrative/template_generator.py:2534
_.identifier  # fhir_r4/labs/coding_package.py:201
_.result_id  # fhir_r4/labs/coding_package.py:204
_.value_set_url  # fhir_r4/labs/coding_package.py:263

# Dead dataclass field:
_.metric  # modules/validator/benchmarks.py:19
_.deviation_pct  # modules/validator/benchmarks.py:24 (also :35 attribute)
_.check_name  # modules/validator/consistency.py:25 (part of delete with run_consistency_checks)

# mpmath.mp.prec — module-level side-effect assignment. mpmath reads .prec
# internally when log/exp/cos/etc are called; vulture does not know this
# and would delete our determinism precision configuration.
_.prec  # determinism.py:91 (mpmath state, cross-platform determinism)

# lab_timeseries helpers — consumed via lazy `from clinosim.modules...
# import` inside `_render_lab_trend_today` / `_render_lab_carry_forward`
# in `replacement_strategy.py`. Vulture only sees module-top imports.
_.latest_by_lab_name  # document/narrative/lab_timeseries.py:96
_.lab_trend  # document/narrative/lab_timeseries.py:188

# load_allergens — public API consumed by tests + README + internal call
# at engine.py:153; vulture (60% confidence) misses the internal call
# because #942 refactor also added load_allergen_config as a sibling.
# Kept as the documented public entrypoint for allergen-catalog loading.
_.load_allergens  # modules/allergy/engine.py:134

# Issue #957: Encounter.service_line consumed via _o(encounter, "service_line",
# "") in modules/document/engine.py::_effective_outpatient_loinc. Vulture only
# sees the dataclass field declaration + the direct assignment site in
# simulator/outpatient.py and misses the getattr-style consumer.
_.service_line  # types/encounter.py + simulator/outpatient.py (read via _o() in document/engine.py)
