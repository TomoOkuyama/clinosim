"""Post-emit resource-shape pipeline — split from ``_fhir_post_process.py``
(Issue #555 PR3, folds Issue #556).

Five concern-scoped modules:
  - ``datetime_normalize`` — datetime / period / instant field normalization.
  - ``populate`` — post-populate ECS / status coding / condition fields.
  - ``strip`` — strip forbidden coding fragments; drop JP text on English-only systems.
  - ``specimen`` — companion Specimen synthesis for lab Observations.
  - ``profile`` — JP Core / JP-CLINS profile stacking + resource-type discriminators.

This ``__init__`` re-exports every name that the pre-split ``_fhir_post_process``
module exposed to its 18 callers. New code should import from the specific
concern module (``from clinosim.modules.output.fhir_r4.post_process.profile
import _apply_jp_clins_profile``) rather than through this facade — the
facade exists for atomic-migration source compatibility only.
"""

from __future__ import annotations

__all__ = [
    # datetime_normalize
    "_DATETIME_FIELDS",
    "_INSTANT_FIELDS",
    "_PERIOD_FIELDS",
    "_PERIOD_KEYS",
    "_normalize_dt",
    "_normalize_dt_fields",
    # populate
    "_ALLERGY_CLINICAL_DISPLAY",
    "_ALLERGY_VER_STATUS_DISPLAY",
    "_CLINOSIM_OBSERVATION_ID_SYSTEM",
    "_CONDITION_CLINICAL_DISPLAY",
    "_CONDITION_VER_STATUS_DISPLAY",
    "_ECS_IDENTIFIER_SYSTEMS",
    "_FHIR_URI_TO_CODE_SYSTEM_KEY",
    "_HL7_V3_SUBSTITUTION_SYSTEM",
    "_JP_CLINS_MEDICATION_USAGE_UNCODED_CODE",
    "_JP_CLINS_MEDICATION_USAGE_UNCODED_CS",
    "_JP_CLINS_MEDICATION_USAGE_UNCODED_DISPLAY",
    "_JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL",
    "_JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS",
    "_JP_MHLW_MEDICATION_USAGE_EPRESCRIPTION_CS",
    "_JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_CODE",
    "_JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_DISPLAY",
    "_JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM",
    "_MEDIS_DISEASE_KEYNUMBER_SYSTEM",
    "_MEDIS_UNCODED_DISEASE_CODE",
    "_MEDIS_UNCODED_DISEASE_DISPLAY",
    "_UCUM_DAY_CODE",
    "_UCUM_DAY_UNIT_JA",
    "_UCUM_SYSTEM_URI",
    "_copy_display_from_sibling_coding",
    "_normalize_jp_observation_category",
    "_populate_condition_ai_mr_ecs_fields",
    "_populate_jp_medication_dosage_ecs_fields",
    "_populate_observation_identifier_and_last_updated",
    "_populate_status_coding_display",
    # profile
    "_FHIR_ID_PATTERN",
    "_HL7_OBSERVATION_CATEGORY_SYSTEM",
    "_HL7_OBSERVATION_CATEGORY_SYSTEMS",
    "_JP_CLINS_PROFILES",
    "_JP_CORE_PROFILES",
    "_JP_OBSERVATION_CATEGORY_SYSTEM",
    "_apply_jp_clins_profile",
    "_apply_jp_core_profile",
    "_is_lab_observation",
    "_medication_request_satisfies_ecs",
    # specimen
    "_COMPANION_SPECIMEN_ID_PREFIX",
    "_SPECIMEN_TYPE_BLOOD",
    "_SPECIMEN_TYPE_URINE",
    "_build_companion_specimen",
    "_lab_observation_needs_specimen",
    "_pick_specimen_type_for_lab",
    # strip
    "_ENGLISH_ONLY_CODING_SYSTEM_PREFIXES",
    "_contains_japanese_char",
    "_strip_forbidden_observation_reference_range_extensions",
    "_strip_japanese_display_on_english_only_systems",
]

from clinosim.modules.output.fhir_r4.post_process.datetime_normalize import (  # noqa: E402, F401
    _DATETIME_FIELDS,
    _INSTANT_FIELDS,
    _PERIOD_FIELDS,
    _PERIOD_KEYS,
    _normalize_dt,
    _normalize_dt_fields,
)
from clinosim.modules.output.fhir_r4.post_process.populate import (  # noqa: E402, F401
    _ALLERGY_CLINICAL_DISPLAY,
    _ALLERGY_VER_STATUS_DISPLAY,
    _CLINOSIM_OBSERVATION_ID_SYSTEM,
    _CONDITION_CLINICAL_DISPLAY,
    _CONDITION_VER_STATUS_DISPLAY,
    _ECS_IDENTIFIER_SYSTEMS,
    _FHIR_URI_TO_CODE_SYSTEM_KEY,
    _HL7_V3_SUBSTITUTION_SYSTEM,
    _JP_CLINS_MEDICATION_USAGE_UNCODED_CODE,
    _JP_CLINS_MEDICATION_USAGE_UNCODED_CS,
    _JP_CLINS_MEDICATION_USAGE_UNCODED_DISPLAY,
    _JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL,
    _JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS,
    _JP_MHLW_MEDICATION_USAGE_EPRESCRIPTION_CS,
    _JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_CODE,
    _JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_DISPLAY,
    _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM,
    _MEDIS_DISEASE_KEYNUMBER_SYSTEM,
    _MEDIS_UNCODED_DISEASE_CODE,
    _MEDIS_UNCODED_DISEASE_DISPLAY,
    _UCUM_DAY_CODE,
    _UCUM_DAY_UNIT_JA,
    _UCUM_SYSTEM_URI,
    _copy_display_from_sibling_coding,
    _normalize_jp_observation_category,
    _populate_condition_ai_mr_ecs_fields,
    _populate_jp_medication_dosage_ecs_fields,
    _populate_observation_identifier_and_last_updated,
    _populate_status_coding_display,
)
from clinosim.modules.output.fhir_r4.post_process.profile import (  # noqa: E402, F401
    _FHIR_ID_PATTERN,
    _HL7_OBSERVATION_CATEGORY_SYSTEM,
    _HL7_OBSERVATION_CATEGORY_SYSTEMS,
    _JP_CLINS_PROFILES,
    _JP_CORE_PROFILES,
    _JP_OBSERVATION_CATEGORY_SYSTEM,
    _apply_jp_clins_profile,
    _apply_jp_core_profile,
    _is_lab_observation,
    _medication_request_satisfies_ecs,
)
from clinosim.modules.output.fhir_r4.post_process.specimen import (  # noqa: E402, F401
    _COMPANION_SPECIMEN_ID_PREFIX,
    _SPECIMEN_TYPE_BLOOD,
    _SPECIMEN_TYPE_URINE,
    _build_companion_specimen,
    _lab_observation_needs_specimen,
    _pick_specimen_type_for_lab,
)
from clinosim.modules.output.fhir_r4.post_process.strip import (  # noqa: E402, F401
    _ENGLISH_ONLY_CODING_SYSTEM_PREFIXES,
    _contains_japanese_char,
    _strip_forbidden_observation_reference_range_extensions,
    _strip_japanese_display_on_english_only_systems,
)
