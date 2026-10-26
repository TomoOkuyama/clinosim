"""Locale data loader — single access point for all country/language-specific data.

Holds only culture/country-dependent data. Terminology/display files were migrated
to clinosim/codes/ (international code systems); they no longer live under locale/.

Directory structure (country-based):
  locale/
    jp/
      names.yaml, addresses.yaml, demographics.yaml, formatting.yaml,
      identity.yaml, immunization_schedule.yaml, code_mapping_*.yaml
    us/
      (same shape as jp/)
    shared/
      naming_rules.yaml, chronic_medications.yaml, chronic_followup.yaml,
      narrative_*.yaml, chief_complaint_translations.yaml

Note: `drug_names_ja.yaml` was deleted under META #1849 Phase 5 Step 4
(2026-10-24). The drug-name EN→JA display mapping now lives in the
authority catalogs under `clinosim/codes/data/` (drugs.yaml +
clinosim-{imaging-exam-name,procedure-phrase,allergen-substance,
admin-form-display}.yaml); the free-text EN → JA display helper
`load_narrative_display_dict()` (renamed from `load_drug_names_ja` in
Phase 5 Step 3) UNIONs those catalogs into the dict shape callers
have always used.
"""

from __future__ import annotations

# Shared yaml-reading primitives — factored out so submodules under
# `clinosim/locale/loaders/` can import them without a cycle back
# through this module (hardcoded-review Phase B1).
from clinosim.locale._io import (
    _country_dir,
)

# Narrative-renderer loader cluster — moved into
# `clinosim/locale/loaders/narrative.py` (hardcoded-review Phase B1).
# Re-exported at module scope so every historical
# `from clinosim.locale.loader import load_narrative_X` keeps working.
from clinosim.locale.loaders.clinical import (
    _iter_route_values,
    _validate_chronic_medications_route_vocabulary,
    load_actuarial_life_table,
    load_chemo_regimens,
    load_chronic_followup,
    load_chronic_medications,
    load_comorbidity_progression_multipliers,
    load_condition_mortality_smr,
    load_health_screening_visit_reason,
    load_iv_infusion_defaults,
    load_perinatal_config,
    load_pregnancy_substitutions,
    load_reference_ranges,
    load_single_gene_diseases,
    load_specialty_routing,
)
from clinosim.locale.loaders.demographics import (
    _load_demographics_cached,
    _validate_addresses,
    _validate_demographics,
    _validate_names,
    load_addresses,
    load_code_mapping,
    load_demographics,
    load_formatting,
    load_names,
    load_naming_rules,
    load_terminology,
)
from clinosim.locale.loaders.fhir_identity import (
    _validate_ambulatory_visit_length,
    load_ambulatory_visit_length,
    load_encounter_disposition_defaults,
    load_external_organizations,
    load_identity_config,
    load_practitioner_qualifications,
)
from clinosim.locale.loaders.medical_display import (
    load_allergen_rxnorm_map,
    load_department_display,
    load_diet_type_display,
    load_frequency_tokens,
    load_med_terms,
    load_med_terms_ja,
    load_occupation_display,
    load_prefecture_jis_x_0401_map,
)
from clinosim.locale.loaders.narrative import (
    _load_country_language_map,
    load_chief_complaint_translations,
    load_inpatient_subjective_pool,
    load_llm_prompt_labels,
    load_narrative_archetypes,
    load_narrative_complications,
    load_narrative_display_dict,
    load_narrative_imaging,
    load_narrative_lab_flags,
    load_narrative_lab_names,
    load_narrative_labels,
    load_narrative_op_approach,
    load_narrative_op_implants,
    load_narrative_stage_tokens,
    resolve_localized_display,
)

__all__ = [
    "_country_dir",
    "_iter_route_values",
    "_load_country_language_map",
    "_load_demographics_cached",
    "_validate_addresses",
    "_validate_ambulatory_visit_length",
    "_validate_chronic_medications_route_vocabulary",
    "_validate_demographics",
    "_validate_names",
    "load_actuarial_life_table",
    "load_addresses",
    "load_allergen_rxnorm_map",
    "load_ambulatory_visit_length",
    "load_chemo_regimens",
    "load_chief_complaint_translations",
    "load_chronic_followup",
    "load_chronic_medications",
    "load_code_mapping",
    "load_comorbidity_progression_multipliers",
    "load_condition_mortality_smr",
    "load_demographics",
    "load_department_display",
    "load_diet_type_display",
    "load_encounter_disposition_defaults",
    "load_external_organizations",
    "load_formatting",
    "load_frequency_tokens",
    "load_health_screening_visit_reason",
    "load_identity_config",
    "load_inpatient_subjective_pool",
    "load_iv_infusion_defaults",
    "load_llm_prompt_labels",
    "load_med_terms",
    "load_med_terms_ja",
    "load_names",
    "load_naming_rules",
    "load_narrative_archetypes",
    "load_narrative_complications",
    "load_narrative_display_dict",
    "load_narrative_imaging",
    "load_narrative_lab_flags",
    "load_narrative_lab_names",
    "load_narrative_labels",
    "load_narrative_op_approach",
    "load_narrative_op_implants",
    "load_narrative_stage_tokens",
    "load_occupation_display",
    "load_perinatal_config",
    "load_practitioner_qualifications",
    "load_prefecture_jis_x_0401_map",
    "load_pregnancy_substitutions",
    "load_reference_ranges",
    "load_single_gene_diseases",
    "load_specialty_routing",
    "load_terminology",
    "resolve_localized_display",
]


# _load_yaml moved to clinosim/locale/_io.py (hardcoded-review Phase B1)
# and imported at the top of this module.
