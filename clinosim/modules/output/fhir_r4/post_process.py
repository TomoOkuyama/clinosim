"""Post-emit resource-shape helpers for `fhir_r4_adapter.py` (session 82 PR N).

Extracted from `clinosim/modules/output/fhir_r4_adapter.py` — this module owns
the 35 module-level constants + 18 helper functions that fire AFTER each
`_bb_*` builder emits a resource but BEFORE the adapter serializes it to
NDJSON. Contents (grouped):

- Datetime normalization: `_normalize_dt`, `_normalize_dt_fields`
  (+ `_DATETIME_FIELDS`, `_PERIOD_FIELDS`, `_INSTANT_FIELDS`)
- Post-populate ECS / status coding / condition:
  `_populate_observation_identifier_and_last_updated`,
  `_populate_jp_medication_dosage_ecs_fields`,
  `_populate_status_coding_display`, `_populate_condition_ai_mr_ecs_fields`
  (+ many JP / MHLW / MEDIS constants)
- Strip helpers:
  `_strip_forbidden_observation_reference_range_extensions`,
  `_strip_japanese_display_on_english_only_systems`
- Companion Specimen synthesis: `_lab_observation_needs_specimen`,
  `_pick_specimen_type_for_lab`, `_build_companion_specimen`
  (+ `_SPECIMEN_TYPE_BLOOD`, `_SPECIMEN_TYPE_URINE`, `_COMPANION_SPECIMEN_ID_PREFIX`)
- Sibling-coding lookup: `_copy_display_from_sibling_coding`
  (+ `_FHIR_URI_TO_CODE_SYSTEM_KEY`)
- JP classification / profile stacking: `_contains_japanese_char`,
  `_apply_jp_core_profile`, `_apply_jp_clins_profile`,
  `_normalize_jp_observation_category`, `_medication_request_satisfies_ecs`,
  `_is_lab_observation` (+ `_JP_CORE_PROFILES`, `_JP_CLINS_PROFILES`,
  `_JP_OBSERVATION_CATEGORY_SYSTEM`, `_HL7_OBSERVATION_CATEGORY_SYSTEM`,
  `_ECS_IDENTIFIER_SYSTEMS`, `_ENGLISH_ONLY_CODING_SYSTEM_PREFIXES`,
  `_HL7_V3_SUBSTITUTION_SYSTEM`)

**No import from `fhir_r4_adapter.py`** — this module is self-contained on
purpose, so `adapter.py` can back-compat re-export these names at the bottom
of its file (test callers do `from ...fhir_r4_adapter import _apply_jp_core_profile`
today).
"""

from __future__ import annotations

import re
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import is_jp  # noqa: I001
from clinosim.modules.output.fhir_r4.builders.allergy_intolerance import (  # noqa: F401
    _bb_allergy_intolerances,
)
from clinosim.modules.output.fhir_r4.builders.care_level import _bb_care_level  # noqa: F401
from clinosim.modules.output.fhir_r4.builders.care_team import (  # noqa: F401
    _bb_care_teams,
)
from clinosim.modules.output.fhir_r4.builders.clinical_impression import (  # noqa: F401
    _bb_clinical_impressions,
)
from clinosim.modules.output.fhir_r4.builders.code_status import _bb_code_status  # noqa: F401
from clinosim.modules.output.fhir_r4.builders.composition import (  # noqa: F401
    _bb_compositions,
)
from clinosim.modules.output.fhir_r4.builders.conditions import _build_conditions  # noqa: F401
from clinosim.modules.output.fhir_r4.builders.device import (  # noqa: F401
    _bb_device,
    _bb_device_use,
)
from clinosim.modules.output.fhir_r4.builders.diagnostic_report import (  # noqa: F401
    _bb_diagnostic_reports,
    build_lab_panel_reports,  # kept for backward compat (tests + external callers)
)
from clinosim.modules.output.fhir_r4.builders.document_reference_checkup import (  # noqa: F401
    _bb_document_references_checkup,
)
from clinosim.modules.output.fhir_r4.builders.documents import (  # noqa: F401
    _bb_document_references,
)
from clinosim.modules.output.fhir_r4.builders.encounter import (  # noqa: F401
    _build_encounter,
    _compute_encounter_length,
)
from clinosim.modules.output.fhir_r4.builders.endpoint import (  # noqa: F401
    _bb_endpoints,
)
from clinosim.modules.output.fhir_r4.builders.facility import _build_facility_bundle  # noqa: F401
from clinosim.modules.output.fhir_r4.builders.family_history import _bb_family_history  # noqa: F401
from clinosim.modules.output.fhir_r4.builders.hai import _bb_hai_conditions  # noqa: F401
from clinosim.modules.output.fhir_r4.builders.imaging_study import (  # noqa: F401
    _bb_imaging_studies,
)
from clinosim.modules.output.fhir_r4.builders.immunization import _bb_immunizations  # noqa: F401
from clinosim.modules.output.fhir_r4.inline_bb import (
    build_order_in_rp_map,  # noqa: F401 — back-compat re-export for test imports
)
from clinosim.modules.output.fhir_r4.localization import (  # noqa: F401
    _CATEGORY_DISPLAY_JA,
    _CLASS_DISPLAY_JA,
    _FREQ_JA,
    _INTERPRETATION_DISPLAY_JA,
    _LOCATION_NAME_JA,
    _LOCATION_TYPE_DISPLAY_JA,
    _OCCUPATION_DISPLAY_EN,
    _OCCUPATION_DISPLAY_JA,
    _ORG_TYPE_DISPLAY_JA,
    _RELATIONSHIP_DISPLAY_JA,
    _ROLE_PREFIX_MAP_JA,
    _ROUTE_JA,
    _SEVERITY_DISPLAY_JA,
    _dept_display,
    _load_department_display,
    _load_drug_names_ja,
    _load_med_terms_ja,
    _localize_display,
    _localize_dosage_terms,
    _localize_drug_name,
    _localize_interp,
    _procedure_display,
)
from clinosim.modules.output.fhir_r4.builders.medications import (  # noqa: F401
    _build_discharge_medication_request,
    _build_medication_admin,
    _build_medication_request,
)
from clinosim.modules.output.fhir_r4.builders.microbiology import _bb_microbiology  # noqa: F401
from clinosim.modules.output.fhir_r4.builders.nursing import _bb_nursing_observations  # noqa: F401
from clinosim.modules.output.fhir_r4.builders.observations import (  # noqa: F401
    _bb_labs,
    _build_lab_observation,
    _build_vital_observations,
)
from clinosim.modules.output.fhir_r4.builders.patient import (  # noqa: F401
    _ORG_TYPE_SYSTEM,
    _SUBSCRIBER_REL_SYSTEM,
    _build_coverage_resources,
    _build_occupation_observation,
    _build_patient,
    _identity_cfg,
    _payer_name_map,
)
from clinosim.modules.output.fhir_r4.builders.practitioner import (  # noqa: F401
    _build_practitioner,
    _build_practitioner_role,
)
from clinosim.modules.output.fhir_r4.builders.procedures import _build_procedure  # noqa: F401
from clinosim.modules.output.fhir_r4.reference_data import (  # noqa: F401
    _ALLERGEN_RXNORM,
    _ENCOUNTER_TYPE_SNOMED_CODE,
    _PREFECTURE_CODE,
    _ROLE_PREFIX_MAP,
    _ROUTE_SNOMED,
    _SEVERITY_SNOMED,
    _SPECIALTY_SNOMED,
)
from clinosim.modules.output.fhir_r4.builders.service_request import (  # noqa: F401
    _bb_service_requests,
)
from clinosim.modules.output.fhir_r4.builders.smoking_alcohol import (  # noqa: F401
    _bb_alcohol_use,
    _bb_smoking_status,
)

# FA-1 (Phases 1-13) split this adapter's leaf data, shared fragment helpers, and
# per-theme resource builders into sibling _fhir_* modules. The blocks below are
# re-imported here so existing `from ...fhir_r4_adapter import X` call sites keep
# working (facade). They are marked # noqa: F401 because many symbols are now used
# only by the extracted modules (which import them directly) and are re-exported
# purely as a compatibility facade; the # noqa keeps the facade stable as further
# builders move out, without per-symbol import churn each phase.
from clinosim.modules.output.fhir_r4.common import (  # noqa: F401
    BundleContext,
    _build_address,
    _build_diagnosis_codeable_concept,
    _build_dosage_instruction,
    _build_reference_range,
    _build_telecom,
    _entry,
    _infer_severity,
    _loinc_coding,
    _make_participant,
    _map_diagnosis_code,
    _map_encounter_status,
    _map_mar_status,
    _micro_coding,
    _parse_dose_for_mar,
    _severity_coding,
    _sha1_b64,
    _strip_protocol_prefix,
    _survey_category,
    derive_meta_last_updated,
)

# FHIR R4 `Resource.id` type: `[A-Za-z0-9\-\.]{1,64}`. iris4h-ai P0 finding
# (2026-07-17): 812,606 ids across the export violated this spec — `_` in id
# and >64 char ids were rejected by IRIS FHIR endpoint with HTTP 400. HAPI
# validator is more lenient but the FHIR spec is strict. The regex here is the
# single source of truth for the pattern — every writer path routes ids
# through it, and any non-conforming id logs a warning (fail-soft: the write
# still succeeds so a bug in a single builder does not break the whole export,
# but the log lets the audit CI catch regressions).
_FHIR_ID_PATTERN = re.compile(r"^[A-Za-z0-9\-\.]{1,64}$")


# session 48 deferred cleanup (g): shape unification.
# JP Core registry uses `dict[str, list[str]]` (was `dict[str, str]`) so its
# shape matches `_JP_CLINS_PROFILES` below. Future JP Core release with
# multiple sibling profiles per resource type (e.g. JP_Observation_Common
# + JP_Observation_Vital) can be listed here without an accessor change.
_JP_CORE_PROFILES: dict[str, list[str]] = {
    # Resources with a canonical JP Core profile URL (JPFHIR core 1.1+).
    # Verified via https://jpfhir.jp/fhir/core/
    "Patient": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient"],
    "Encounter": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Encounter"],
    "Condition": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Condition"],
    "Coverage": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Coverage"],
    "Observation": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"],
    "MedicationRequest": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationRequest"],
    "MedicationAdministration": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationAdministration"],
    "AllergyIntolerance": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_AllergyIntolerance"],
    "Immunization": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Immunization"],
    "Practitioner": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Practitioner"],
    "PractitionerRole": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_PractitionerRole"],
    "Organization": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Organization"],
    "DiagnosticReport": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_DiagnosticReport_Common"],
    # RM-6c (session 42): Procedure profile so RECORD-based and ORDER-based
    # Procedure emissions both carry JP Core conformance.
    "Procedure": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Procedure"],
    # session 53 (#145): additional JP Core StructureDefinition URLs — spec
    # `.url` fixedUri copied verbatim from
    # iris4h-ai/jp_core/package/StructureDefinition-jp-*.json.
    # JP Core 1.2.0 does NOT publish profiles for CareTeam / Composition /
    # ClinicalImpression / Endpoint, so those four resource types remain on
    # base FHIR R4 (Composition still carries per-doc-type JP-CLINS profiles
    # emitted at the composition builder level; see _JP_CLINS_PROFILES
    # attach logic in _apply_jp_clins_profile).
    "ServiceRequest": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_ServiceRequest_Common"],
    "DocumentReference": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_DocumentReference"],
    "FamilyMemberHistory": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_FamilyMemberHistory"],
    # ImagingStudy has two JP Core profiles (_Radiology + _Endoscopy).
    # clinosim only emits radiology studies (CT/CXR/MRI via `imaging` module,
    # AD-62 — endoscopy is out of scope), so only the radiology profile is
    # attached.
    "ImagingStudy": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_ImagingStudy_Radiology"],
}


# session 48 feedback FB-F1: 全 emit resource で dateTime / instant field を
# TZ 付与に正規化する post-emit normalization pass。builders 個別修正の代替。
# 対象 field は FHIR R4 で dateTime / instant 型を持つ known-name 一覧。
_DATETIME_FIELDS = frozenset(
    (
        # top-level dateTime
        "authoredOn",
        "effectiveDateTime",
        "performedDateTime",
        "date",
        "started",
        "receivedTime",
        "recordedDate",
        "onsetDateTime",
        "occurrenceDateTime",
        "abatementDateTime",
        "assertedDate",
        "authored",
        "assertedDateTime",
        "collectedDateTime",  # Specimen.collection.collectedDateTime (nested)
        "time",  # attester.time / Provenance.recorded など
        # instant type
        "issued",
        "recorded",
        "createdOn",
        "sent",
        "lastUpdated",
    )
)
_PERIOD_FIELDS = frozenset(("start", "end"))
# Period-typed dict keys the walker treats as `{"start": ..., "end": ...}` sub-objects.
# Issue #570 audit: `performedPeriod` / `effectivePeriod` / `occurrencePeriod` were
# recursed but their `start`/`end` were not in `_DATETIME_FIELDS`, so JST leaked
# through them on US cohorts. Enumerated here as a single source of truth.
_PERIOD_KEYS = frozenset(
    (
        "period",
        "validityPeriod",
        "servicedPeriod",
        "performedPeriod",
        "effectivePeriod",
        "occurrencePeriod",
        "authoredOnPeriod",
    )
)
# instant 型 field(秒精度+TZ 必須)
_INSTANT_FIELDS = frozenset(("issued", "lastUpdated"))

# Observation.identifier system — internal namespace for clinosim-generated
# Observations. Feedback (2026-07-16) noted that JP_Observation_LabResult_eCS
# declares `identifier` with `min=1`; every Observation now carries this
# identifier populated from `Observation.id`.
_CLINOSIM_OBSERVATION_ID_SYSTEM = "urn:clinosim:observation-id"

# JP-CLINS 1.12.0 JP_Observation_LabResult_eCS profile requires an
# `identifier:resourceIdentifier` slice whose `.system` matches the profile's
# patternUri (spec directly from
# `StructureDefinition-JP-Observation-LabResult-eCS.json`, differential
# element `Observation.identifier:resourceIdentifier.system`). Emitting the
# internal `urn:clinosim:observation-id` alone triggered 30,315 slice-
# minimum-violation errors in the 2026-07-17 v2 fullset validation (v2
# feedback §【最優先 1】, -7.3pp headroom). For JP output we prepend this
# canonical spec URI; the internal urn is preserved as a secondary
# identifier so downstream consumers can still round-trip clinosim
# resources.
_JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier"

# HL7 v3 substanceAdminSubstitution CodeSystem (used by JP MR eCS walker to
# convert `substitution.allowedBoolean` -> `substitution.allowedCodeableConcept`
# per session 57 Chain 5). Defined at module top-level so the
# test_adapter_does_not_hardcode_code_system_uris invariant continues to hold
# (the URI never appears as a `"system": "..."` literal inside a builder).
_HL7_V3_SUBSTITUTION_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-substanceAdminSubstitution"

# JP-CLINS MedicationRequest.dosageInstruction (Dosage = JP_MedicationDosage_eCS)
# canonical constants (spec fixedUri from
# StructureDefinition-jp-medicationdosage-eCS.json in JP-CLINS 1.12.0).
# The R5020 constraint ("valid Usage-MedicationUsage-codesystem") requires
# exactly one of: MHLW ePrescription code OR the dummy uncoded code.
# clinosim has no MHLW usage-code mapping, so the dummy is the correct choice
# and matches JP-CLINS's own example fixture
# (MedicationRequest-Example-JP-MedReq-PO-TID-2days-dummyUsageCode.json).
_JP_CLINS_MEDICATION_USAGE_UNCODED_CS = "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_MedicationUsage_Uncoded_CS"
_JP_CLINS_MEDICATION_USAGE_UNCODED_CODE = "0X0XXXXXXXXX0000"
_JP_CLINS_MEDICATION_USAGE_UNCODED_DISPLAY = "ダミー用法コード"
# JP_MedicationDosage_eCS declares Dosage.extension:periodOfUse as min=1
# (spec differential slice). The extension's valuePeriod.start marks the day
# the dose becomes effective.
_JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL = (
    "http://jpfhir.jp/fhir/core/Extension/StructureDefinition/JP_MedicationDosage_PeriodOfUse"
)
# The MHLW ePrescription CS is the "coded" alternative to the dummy code. When
# a builder has emitted this system already, the walker leaves it alone.
_JP_MHLW_MEDICATION_USAGE_EPRESCRIPTION_CS = "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/MedicationUsage_ePrescription"

# JP_MedicationDosage_eCS `Dosage.doseAndRate.type` min=1 (session 58 Chain #2).
# Spec-authoritative example fixture
# (`MedicationRequest-Example-JP-MedReq-PO-TID-2days-dummyUsageCode.json` in
# `clinical-information-sharing#1.12.0/package/example/`) uses the MHLW
# MedicationIngredientStrengthType CodeSystem `code=1 / display=製剤量`
# (pharmaceutical dose = the amount of formulation ordered, as opposed to
# active-ingredient strength). clinosim does not otherwise emit this
# CodeSystem, so we define the URI here so `_populate_jp_medication_dosage_ecs_fields`
# can inject the coding without duplicating the literal.
_JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS = (
    "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/MedicationIngredientStrengthStrengthType"
)
_JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_CODE = "1"
_JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_DISPLAY = "製剤量"

# UCUM CodeSystem URI + daily unit — used to rewrite
# `Dosage.timing.repeat.periodUnit='d'` (bare `code` with unresolvable-by-tx
# UnitsOfTime binding) into a `Dosage.timing.repeat.boundsDuration` Duration
# whose `system` field lets the validator resolve `d` inline. Session 58
# Chain #2.
_UCUM_SYSTEM_URI = "http://unitsofmeasure.org"
_UCUM_DAY_CODE = "d"
_UCUM_DAY_UNIT_JA = "日"
# eCS-required identifier namespaces (feedback fix PR-G, 2026-07-17). Every
# resource for which JP-CLINS eCS requires `identifier` with `min=1` gets a
# canonical clinosim namespace so consumers can round-trip resources without
# fabricating IDs. MedicationRequest is intentionally NOT in this map — its
# builder already emits identifier[] with rpNumber + orderInRp (JP Core
# NamingSystem slice discriminators, session 51 rule).
_ECS_IDENTIFIER_SYSTEMS: dict[str, str] = {
    "Condition": "urn:clinosim:condition-id",
    "AllergyIntolerance": "urn:clinosim:allergyintolerance-id",
}

# JP-CLINS `JP_Condition_eCS` requires the `code.coding:medisRecordNo` slice
# (min=1) whose `system` fixedUri is the MEDIS 標準病名マスター 病名管理番号
# CodeSystem (spec: `StructureDefinition-JP-Condition-eCS.json`). clinosim does
# not ship an ICD-10 → keyNumber mapping, so we emit the MEDIS "uncoded
# disease" placeholder (`99999999` / `未コード化傷病名`) — an authoritative
# entry used in real JP hospital systems when reception input does not map
# cleanly to the 標準病名マスター. The code is verified present in the JP-
# terminology fragment CodeSystem loaded by fhir-jp-validator
# (`jpfhir-terminology 2.2606.0` / `medis-codesystem-diseasekanricodes`).
_MEDIS_DISEASE_KEYNUMBER_SYSTEM = "http://medis.or.jp/CodeSystem/master-disease-keyNumber"
_MEDIS_UNCODED_DISEASE_CODE = "99999999"
_MEDIS_UNCODED_DISEASE_DISPLAY = "未コード化傷病名"

# HL7 condition-clinical / condition-ver-status display map. The tiny code
# vocabulary is not in clinosim/codes/data/ (they are HL7 spec CS, not
# clinical codes) so we keep the English display map inline.
_CONDITION_CLINICAL_DISPLAY: dict[str, str] = {
    "active": "Active",
    "recurrence": "Recurrence",
    "relapse": "Relapse",
    "inactive": "Inactive",
    "remission": "Remission",
    "resolved": "Resolved",
}
_CONDITION_VER_STATUS_DISPLAY: dict[str, str] = {
    "unconfirmed": "Unconfirmed",
    "provisional": "Provisional",
    "differential": "Differential",
    "confirmed": "Confirmed",
    "refuted": "Refuted",
    "entered-in-error": "Entered in Error",
}
_ALLERGY_CLINICAL_DISPLAY: dict[str, str] = {
    "active": "Active",
    "inactive": "Inactive",
    "resolved": "Resolved",
}
_ALLERGY_VER_STATUS_DISPLAY: dict[str, str] = {
    "unconfirmed": "Unconfirmed",
    "presumed": "Presumed",
    "confirmed": "Confirmed",
    "refuted": "Refuted",
    "entered-in-error": "Entered in Error",
}

# Reverse map: FHIR system URI → clinosim system key (for `code_lookup`).
# Used by `_copy_display_from_sibling_coding` fallback when no sibling coding
# with a display is available (e.g. AllergyIntolerance.code carries a single
# SNOMED coding).
_FHIR_URI_TO_CODE_SYSTEM_KEY: dict[str, str] = {
    "http://snomed.info/sct": "snomed-ct",
    "http://loinc.org": "loinc",
    "http://hl7.org/fhir/sid/icd-10": "icd-10",
    "http://hl7.org/fhir/sid/icd-10-cm": "icd-10-cm",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "rxnorm",
    # Issue #350 (session 63): JP-locale ICD-10 canonical URI. Reverse-map
    # to the same code data as `icd-10` (via `_SYSTEM_DATA_ALIASES` in
    # `clinosim/codes/loader.py`) so `_copy_display_from_sibling_coding`
    # can look up displays for JP-emitted ICD-10 codings.
    "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full": "icd-10-mhlw",
}


def _normalize_dt(v, country: str = "", want_instant: bool = False):
    """string dateTime → country-specific TZ suffix 付与 / rewrite。

    Issue #570 locale gate: builders unconditionally emit ``+09:00`` (JST) via
    ``to_fhir_datetime`` / ``to_fhir_instant``. This walker then rewrites the
    suffix per country: JP keeps ``+09:00``; other cohorts (US default) get
    ``Z`` (UTC neutral). Other pre-existing TZ suffixes (e.g. ``-05:00``) are
    preserved as-is.
    """
    from clinosim.modules.output.fhir_r4.common import tz_suffix_for_country

    tz = tz_suffix_for_country(country)
    if not isinstance(v, str) or not v:
        return v
    # date-only YYYY-MM-DD は通す(FHIR date 型として valid)
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        if want_instant:
            # instant 要求 → 秒 + TZ 補完
            return f"{v}T00:00:00{tz}"
        return v
    if "T" not in v:
        return v  # 空 or 非 datetime 形式は不変
    # 既に JST suffix — country が JP なら維持、それ以外は country の TZ に rewrite。
    if v.endswith("+09:00"):
        return v if tz == "+09:00" else v[:-6] + tz
    # 他 TZ (Z, -05:00 等) は既に explicit なので変更しない (builder or upstream 意図)。
    if v.endswith("Z") or (len(v) >= 6 and v[-6] in "+-" and v[-3] == ":"):
        return v
    # TZ 無し → country の TZ を付与。秒欠落補完 (instant 用)。
    if want_instant and v.count(":") == 1:
        v = v + ":00"
    return v + tz


# JP Core Observation.category の canonical CodeSystem URI(spec fixedUri
# 直接引用、iris4h-ai/jp_core/package/StructureDefinition-jp-observation-
# common.json の `category:first.coding.system.fixedUri`)。
_JP_OBSERVATION_CATEGORY_SYSTEM = "http://jpfhir.jp/fhir/core/CodeSystem/JP_SimpleObservationCategory_CS"

# HL7 標準 URL + 過去 clinosim 版が誤って使った fabricated URL の両方を
# normalize 対象とする(古い regen data + defensive migration)。
_HL7_OBSERVATION_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"
_HL7_OBSERVATION_CATEGORY_SYSTEMS = frozenset(
    [
        _HL7_OBSERVATION_CATEGORY_SYSTEM,
        "http://jpfhir.jp/fhir/observation-category",  # legacy fabricated
    ]
)


def _populate_observation_identifier_and_last_updated(resource: dict, country: str = "") -> None:
    """Populate `Observation.identifier` and `Observation.meta.lastUpdated`.

    JP_Observation_LabResult_eCS (JP-CLINS 1.12.0) requires both fields:
    - `identifier[]` (`min=1`) with an `identifier:resourceIdentifier` slice
      whose `.system` matches the spec `patternUri`. For JP output the
      spec-canonical URI is emitted as the leading identifier so the slice
      is satisfied; the internal `urn:clinosim:observation-id` is appended
      as a secondary identifier so downstream consumers keep the round-trip
      key.
    - `meta.lastUpdated` (`min=1`) — falls back to `effectiveDateTime` (or
      `issued` / `effectivePeriod.end`) when the builder did not set one. The
      value is a good approximation for synthesized data since clinosim has
      no separate "record last modified" concept.

    Base FHIR admits both as optional, so the walker fires universally.
    Idempotent — leaves builder-populated values untouched.

    Feedback fix (2026-07-16, PR-D) covered identifier + meta.lastUpdated
    universally. Session 57 chain A (v2 feedback §【最優先 1】) adds the
    JP-locale spec URI so the resourceIdentifier slice actually matches.
    """
    if resource.get("resourceType") != "Observation":
        return
    # identifier — Issue #336 (session 62): 従来 `if not resource.get("identifier")`
    # で全体 skip だったが、microbiology `mb-org-*` / `mb-sus-*` は builder 側で
    # HAI_EVENT_ID_SYSTEM identifier を先に populate 済 → walker skip →
    # JP_Observation_LabResult_eCS の `resourceIdentifier` slice min=1 fail
    # (v9 obs 1 件 error)。sibling MedicationRequest walker (line 1908-1924)
    # と同じ idempotent-prepend pattern に統一 = 既存 identifier list を保持
    # しつつ、canonical URI が未収録なら prepend、internal namespace も append。
    rid = resource.get("id", "")
    if rid:
        existing = resource.setdefault("identifier", [])
        existing_systems = {i.get("system") for i in existing if isinstance(i, dict)}
        # JP output: canonical resourceInstance-identifier slice を必ず先頭に
        # (spec `Observation.identifier:resourceIdentifier.system` patternUri)。
        if is_jp(country) and _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM not in existing_systems:
            existing.insert(0, {"system": _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM, "value": rid})
        # 全 country: 内部 round-trip 用 identifier(既存 downstream consumer 用)。
        if _CLINOSIM_OBSERVATION_ID_SYSTEM not in existing_systems:
            existing.append({"system": _CLINOSIM_OBSERVATION_ID_SYSTEM, "value": rid})
    # meta.lastUpdated — reuse an existing datetime field. _normalize_dt_fields
    # then converts it to the FHIR `instant` shape (seconds + TZ).
    meta = resource.setdefault("meta", {})
    if not meta.get("lastUpdated"):
        ts = derive_meta_last_updated(resource, ("effectiveDateTime", "issued", "effectivePeriod.end"))
        if ts:
            meta["lastUpdated"] = ts


def _strip_forbidden_observation_reference_range_extensions(resource: dict) -> None:
    """Remove `extension` / `modifierExtension` from every
    `Observation.referenceRange[*]` (and `.low` / `.high`, plus
    `Observation.component[*].referenceRange[*]` mirrored paths).

    Rationale:

    - `JP_Observation_LabResult_eCS` (JP-CLINS 1.12.0) locks
      `Observation.referenceRange.extension` (and `modifierExtension`,
      `low.extension`, `high.extension`) to `max=0`; the same lock
      applies to `component[*].referenceRange.*`. Any extension emitted
      on these paths violates the profile, regardless of URL.
    - clinosim previously emitted a `referenceRangeSource` extension
      whose URL was not registered anywhere in the JP-CLINS 1.12.0 /
      jp-core 1.2.0 / jpfhir-terminology 2.2606.0 packages
      (fhir-jp-validator 2026-07-17 §【最優先 2】surfaced 31,006
      errors from this). The emit site in `_fhir_common._build_reference_range`
      no longer writes it, but this walker is the second layer of the
      silent-no-op defense: any cached CIF re-exported after the fix,
      or a hypothetical future builder that reintroduces a sub-extension,
      would still be scrubbed.

    Universal (US Observation also benefits — the extension was already
    JP-gated, but stripping is a no-op on non-existent fields).
    Idempotent.
    """
    if resource.get("resourceType") != "Observation":
        return

    def _scrub(rrs: Any) -> None:
        if not isinstance(rrs, list):
            return
        for rr in rrs:
            if not isinstance(rr, dict):
                continue
            rr.pop("extension", None)
            rr.pop("modifierExtension", None)
            for side in ("low", "high"):
                sub = rr.get(side)
                if isinstance(sub, dict):
                    sub.pop("extension", None)
                    sub.pop("modifierExtension", None)

    _scrub(resource.get("referenceRange"))
    for comp in resource.get("component") or []:
        if isinstance(comp, dict):
            _scrub(comp.get("referenceRange"))


def _lab_observation_needs_specimen(resource: dict) -> bool:
    """True for lab Observations that need a companion Specimen resource.

    JP-CLINS `JP_Observation_LabResult_eCS` declares `Observation.specimen`
    with `min=1`. clinosim lab Observations use ids prefixed `lab-<encounter>-`;
    microbiology / vital / social-history / imaging / survey Observations use
    different prefixes and either have their own Specimen (microbiology) or
    require none. Detect by id prefix + absence of a builder-set `specimen`.
    """
    if resource.get("resourceType") != "Observation":
        return False
    if resource.get("specimen"):
        return False
    rid = resource.get("id", "")
    return isinstance(rid, str) and rid.startswith("lab-")


# Companion-Specimen id prefix. Same shape as the lab-obs id it derives from,
# preserving the `lab-<encounter>-NNNN` traceable structure.
_COMPANION_SPECIMEN_ID_PREFIX = "spec-"

# Default specimen: blood (SNOMED 119297000) — matches the majority of clinosim's
# lab output (CBC / chem panel / LFT / cardiac markers / coagulation / ...).
_SPECIMEN_TYPE_BLOOD = {"code": "119297000", "display_en": "Blood specimen", "display_ja": "血液検体"}
# Urine specimen (SNOMED 122575003) — for Urinalysis / urine dipstick tests.
_SPECIMEN_TYPE_URINE = {"code": "122575003", "display_en": "Urine specimen", "display_ja": "尿検体"}


def _pick_specimen_type_for_lab(observation: dict) -> dict:
    """Pick the Specimen.type coding for a lab Observation. Blood is the
    default; Urinalysis-style tests get urine specimen.

    The rule is intentionally conservative — only names that clearly indicate
    a non-blood specimen switch away from blood. Anything else stays blood so
    clinosim doesn't silently fabricate specimen types on general chem panels.
    """
    code_field = observation.get("code") or {}
    text = str(code_field.get("text", "") or "").lower()
    for coding in code_field.get("coding", []) or []:
        display = str(coding.get("display", "") or "").lower()
        if "urin" in display or "urine" in display:
            return _SPECIMEN_TYPE_URINE
    if "urin" in text or "urine" in text:
        return _SPECIMEN_TYPE_URINE
    return _SPECIMEN_TYPE_BLOOD


def _build_companion_specimen(observation: dict, country: str) -> dict:
    """Build a minimal Specimen resource paired with a lab Observation.

    Populated fields:
    - `id`  — `spec-<observation.id>` (canonical namespace, id-stable)
    - `subject` — copied from the Observation.subject
    - `type` — SNOMED specimen coding (blood by default; urine for Urinalysis)
    - `collection.collectedDateTime` — the Observation's effectiveDateTime
    - `identifier` — `urn:clinosim:specimen-id` for round-trip stability
    """
    obs_id = observation.get("id", "")
    spec_id = f"{_COMPANION_SPECIMEN_ID_PREFIX}{obs_id}"
    subject = observation.get("subject", {}) or {}
    type_entry = _pick_specimen_type_for_lab(observation)
    display = type_entry["display_ja"] if is_jp(country) else type_entry["display_en"]
    specimen: dict[str, Any] = {
        "resourceType": "Specimen",
        "id": spec_id,
        "identifier": [{"system": "urn:clinosim:specimen-id", "value": spec_id}],
        "subject": subject,
        "type": {
            "coding": [{"system": get_system_uri("snomed-ct"), "code": type_entry["code"], "display": display}],
            "text": display,
        },
        "status": "available",
    }
    edt = observation.get("effectiveDateTime")
    if edt:
        specimen["collection"] = {"collectedDateTime": edt}
    return specimen


def _populate_jp_medication_dosage_ecs_fields(resource: dict) -> None:
    """Populate `JP_MedicationDosage_eCS`-required fields on each
    `MedicationRequest.dosageInstruction[]`.

    JP-CLINS 1.12.0 pulls the Dosage type through a JP-specific profile that
    layers three requirements the clinosim builder does not currently emit:

    1. **`Dosage.extension:periodOfUse` (min=1)** — a `Period` whose `start`
       marks the day the dose becomes effective. Derived from `authoredOn`
       (fallback: `recorded`).
    2. **`Dosage.timing.code.coding` (min=1) satisfying R5020** — exactly one
       of the MHLW ePrescription coded system OR the JP-CLINS dummy uncoded
       code `0X0XXXXXXXXX0000`. clinosim has no MHLW coded mapping, so we
       emit the JP-CLINS dummy — this is the exact choice made by the
       official JP-CLINS example fixture
       (`MedicationRequest-Example-JP-MedReq-PO-TID-2days-dummyUsageCode.json`).
    3. **`Dosage.timing.code.text` (min=1)** — human-readable frequency
       description; falls back to `Dosage.text` when unset.

    JP only (the walker is registered inside the `is_jp(country)` branch).
    Idempotent — leaves any builder-populated extension / timing.code alone.

    Feedback fix (2026-07-16, PR-I). Covers `dosageInstruction[N].extension` +
    `Constraint failed: validUsage-MedicationUsage-codesystem` from §"【最優先 2】".
    """
    if resource.get("resourceType") != "MedicationRequest":
        return
    dosages = resource.get("dosageInstruction")
    if not isinstance(dosages, list):
        return

    # Derive the period start from authoredOn / recorded (date portion only —
    # Period.start is a dateTime, but the JP-CLINS example uses date-only).
    authored = resource.get("authoredOn") or resource.get("recorded") or ""
    start_date = ""
    if isinstance(authored, str) and authored:
        # authoredOn is dateTime with TZ; strip the T portion for a stable date.
        start_date = authored.split("T", 1)[0]

    for dosage in dosages:
        if not isinstance(dosage, dict):
            continue

        # (1) PeriodOfUse extension (min=1 slice).
        exts = dosage.setdefault("extension", [])
        if isinstance(exts, list):
            already_periodofuse = any(
                isinstance(e, dict) and e.get("url") == _JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL for e in exts
            )
            if not already_periodofuse and start_date:
                exts.append(
                    {
                        "url": _JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL,
                        "valuePeriod": {"start": start_date},
                    }
                )

        # (2)+(3) timing.code (R5020 + text min=1).
        timing = dosage.setdefault("timing", {})
        if not isinstance(timing, dict):
            continue
        code_field = timing.setdefault("code", {})
        if not isinstance(code_field, dict):
            continue
        codings = code_field.setdefault("coding", [])
        if isinstance(codings, list):
            already_valid = any(
                isinstance(c, dict)
                and c.get("system")
                in (_JP_CLINS_MEDICATION_USAGE_UNCODED_CS, _JP_MHLW_MEDICATION_USAGE_EPRESCRIPTION_CS)
                for c in codings
            )
            if not already_valid:
                codings.append(
                    {
                        "system": _JP_CLINS_MEDICATION_USAGE_UNCODED_CS,
                        "code": _JP_CLINS_MEDICATION_USAGE_UNCODED_CODE,
                        "display": _JP_CLINS_MEDICATION_USAGE_UNCODED_DISPLAY,
                    }
                )
        # DO NOT fill timing.code.text with dosage text. Timing.code is a
        # CodeableConcept with binding to TimingAbbreviation (BID/TID/QID/Q4H/QD).
        # Dosage text belongs in Dosage.text only (line 745). Filling both
        # creates duplication and makes timing.code.text unsuitable for its
        # intended purpose (machine-readable frequency abbreviations). Issue #477.

        # (4) `Dosage.doseAndRate.type` min=1 (session 58 Chain #2).
        # Every doseAndRate entry gets the MHLW MedicationIngredientStrength
        # `1 / 製剤量` coding when `type` is absent. Matches the JP-CLINS
        # example fixture — see the `_JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS`
        # constant docstring for the exact provenance.
        dose_and_rate = dosage.get("doseAndRate")
        if isinstance(dose_and_rate, list):
            for dr in dose_and_rate:
                if not isinstance(dr, dict) or dr.get("type"):
                    continue
                dr["type"] = {
                    "coding": [
                        {
                            "system": _JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS,
                            "code": _JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_CODE,
                            "display": _JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_DISPLAY,
                        }
                    ]
                }

        # (5) Add a `timing.repeat.boundsDuration` slice + strip
        # `periodUnit='d'`/`period` on JP output.
        #
        # 履歴:
        # - session 58 Chain #2:元の狙いは boundsDuration only 化
        #   (UnitsOfTime binding 回避)
        # - session 59 #281:JP-CLINS example fixture が両方 emit する
        #   ことを根拠に `periodUnit` の pop を撤回
        # - v6 (session 60):HAPI validator が `periodUnit=code`(FHIR R4
        #   `code` type は system 情報を持たない)の binding 検証で
        #   system URI を決定できず 3,532 件 UnitsOfTime error 発火
        #   (v5 では 0 件だった regression、tim-2 と分岐した振舞い)
        # - #307 session 60(判断リカバリ pragmatic middle path):
        #   spec は example と別。JP-CLINS example が両方 emit しても
        #   spec が両方 required とは限らず、boundsDuration + frequency
        #   で per-day cadence 情報は spec-valid に保持可能。session 58
        #   chain #2 元の狙いに復帰し、`periodUnit` + `period` を pop
        #   する(tim-2 non-fire + UnitsOfTime binding 対象外)。
        #
        # US 側は影響なし(この walker は JP-only、_fhir_common.py の
        # `period + periodUnit` はそのまま emit される。US は FHIR R4
        # 標準 validator が `code` binding を通す仕様)。
        repeat = timing.get("repeat")
        if isinstance(repeat, dict) and repeat.get("periodUnit") == "d":
            bounds = repeat.get("boundsDuration")
            if not isinstance(bounds, dict):
                # Value 1 mirrors the periodUnit anchoring semantics (per-day
                # cadence). Downstream consumers relying on the total-therapy-
                # duration reading of `boundsDuration` should look at
                # dispenseRequest.expectedSupplyDuration instead.
                period = repeat.get("period", 1)
                repeat["boundsDuration"] = {
                    "value": period if isinstance(period, (int, float)) else 1,
                    "unit": _UCUM_DAY_UNIT_JA,
                    "system": _UCUM_SYSTEM_URI,
                    "code": _UCUM_DAY_CODE,
                }
            # #307 session 60:pop `periodUnit` + `period` after boundsDuration
            # is populated. tim-2 (period.exists() implies periodUnit.exists())
            # は pair で無くなれば non-fire。frequency + boundsDuration で
            # per-day cadence は保持。
            repeat.pop("periodUnit", None)
            repeat.pop("period", None)


def _copy_display_from_sibling_coding(codings: list, lang: str = "en") -> None:
    """When one coding entry has a display for a code and another sibling entry
    with the same code lacks it, propagate the display. Used on
    `Condition.code.coding[]` and `AllergyIntolerance.code.coding[]` where the
    primary JP coding (WHO ICD-10 / SNOMED, English-only CodeSystem) had its
    display stripped by the P2 A walker but the interop coding (ICD-10-CM /
    same code, English display) already has it.

    When no sibling display is available (e.g. AllergyIntolerance emits a
    single SNOMED coding), fall back to `code_lookup` in ``lang`` for known
    FHIR system URIs. JP output routes ``lang="ja"`` here so the primary
    coding carries a JP-native display where clinosim/codes/data has one,
    and only falls back to English when no ja entry exists.

    Feedback fix (2026-07-16, PR-G). Preserves the FHIR R4 rule that every
    coding on an English-only CodeSystem must carry a resolvable display.
    """
    if not isinstance(codings, list):
        return
    code_display: dict[str, str] = {}
    for c in codings:
        if isinstance(c, dict):
            code_ = c.get("code")
            display = c.get("display")
            if isinstance(code_, str) and code_ and isinstance(display, str) and display and code_ not in code_display:
                code_display[code_] = display
    for c in codings:
        if isinstance(c, dict) and not c.get("display"):
            code_ = c.get("code")
            if not isinstance(code_, str) or not code_:
                continue
            # Priority for the display value on a coding that lacks one:
            # (1) authoritative `code_lookup` in the requested language (ja)
            # (2) sibling coding's display (interop entry with english)
            # (3) `code_lookup` in english as a last-resort fallback.
            # (1) beats (2) on JP output so a dual-coded Condition emits the
            # authoritative JP display rather than the english interop label.
            display = None
            system_uri = c.get("system", "")
            system_key = _FHIR_URI_TO_CODE_SYSTEM_KEY.get(system_uri) if isinstance(system_uri, str) else None
            # Session 57 chain G (v2 feedback §【中優先 7】): the sibling-copy
            # step previously re-injected a Japanese display via
            # `code_lookup(..., "ja")` for JP output. On English-only
            # CodeSystems (LOINC / SNOMED / HL7 terminology / DICOM / UCUM
            # / `http://hl7.org/fhir/sid/*` including ICD-10) that undid
            # `_strip_japanese_display_on_english_only_systems`, so the
            # HAPI Validator's "Wrong Display Name" check surfaced ~2.5k
            # ICD-10 errors in v2 fullset. Skip the ja lookup path when
            # the coding's system is on the English-only allowlist so the
            # sibling-copy step falls through to the interop display
            # (2) or the canonical English lookup (3).
            is_english_only_system = isinstance(system_uri, str) and system_uri.startswith(
                _ENGLISH_ONLY_CODING_SYSTEM_PREFIXES
            )
            if system_key and lang != "en" and not is_english_only_system:
                looked_up = code_lookup(system_key, code_, lang)
                if looked_up and looked_up != code_:
                    display = looked_up
            if not display:
                display = code_display.get(code_)
            if not display and system_key:
                looked_up = code_lookup(system_key, code_, "en")
                if looked_up and looked_up != code_:
                    display = looked_up
            if display:
                c["display"] = display


def _populate_status_coding_display(coding_dict: Any, display_map: dict[str, str]) -> None:
    """Populate `.coding[].display` from a static map when missing.

    Used on `clinicalStatus` / `verificationStatus` where the HL7 CodeSystem
    values are a fixed small vocabulary (active / confirmed / ...) that is
    not carried in clinosim/codes/data/.
    """
    if not isinstance(coding_dict, dict):
        return
    codings = coding_dict.get("coding")
    if not isinstance(codings, list):
        return
    for c in codings:
        if not isinstance(c, dict) or c.get("display"):
            continue
        code_ = c.get("code")
        if isinstance(code_, str) and code_ in display_map:
            c["display"] = display_map[code_]


def _populate_condition_ai_mr_ecs_fields(resource: dict, country: str = "US") -> None:
    """Populate JP-CLINS eCS-required fields on Condition / AllergyIntolerance
    / MedicationRequest.

    Feedback fix (2026-07-16, PR-G). The 2026-07-16 fhir-jp-validator report
    §"【最優先 2】" lists a common pattern across the three resources:

    - `identifier` (min=1) — canonical clinosim namespace when not builder-set.
    - `meta.lastUpdated` (min=1) — falls back to the most authoritative
      datetime available on the resource; never fabricated when no source.
    - `clinicalStatus.coding.display` — HL7 CodeSystem values (active /
      inactive / resolved / confirmed / …) resolved via a static English
      display map.
    - `verificationStatus.coding.display` — same idea, different HL7 CS.
    - `code.coding[].display` on the primary coding — copied from a sibling
      coding that shares the same code and has a display (P2 A walker
      strips Japanese display from English-only CodeSystems; when the
      builder emits a paired interop coding with English display, we
      propagate it to the primary coding).

    The walker fires universally (US output picks up the same fields
    harmlessly) and stays idempotent.
    """
    rt = resource.get("resourceType")
    if rt not in ("Condition", "AllergyIntolerance", "MedicationRequest"):
        return

    # (1) identifier — canonical namespace, only when not builder-populated.
    # Session 57 v3 (Chain-9): for JP output, prepend the JP-CLINS
    # `resourceIdentifier` slice (spec `patternUri`
    # `http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier`) so the
    # `Condition.identifier:resourceIdentifier` slice discriminator matches.
    # Same URI + same 2-element pattern as Chain A on Observation. Keeps the
    # internal `urn:clinosim:*` namespace as a secondary identifier so downstream
    # consumers can still round-trip by resource id.
    if rt in _ECS_IDENTIFIER_SYSTEMS and not resource.get("identifier"):
        rid = resource.get("id", "")
        if rid:
            if is_jp(country):
                resource["identifier"] = [
                    {"system": _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM, "value": rid},
                    {"system": _ECS_IDENTIFIER_SYSTEMS[rt], "value": rid},
                ]
            else:
                resource["identifier"] = [{"system": _ECS_IDENTIFIER_SYSTEMS[rt], "value": rid}]

    # (2) meta.lastUpdated fallback chain.
    meta = resource.setdefault("meta", {})
    if not meta.get("lastUpdated"):
        prefer: tuple[str, ...] = (
            ("authoredOn", "recorded")
            if rt == "MedicationRequest"
            else ("recordedDate", "assertedDate", "onsetDateTime")
        )
        ts = derive_meta_last_updated(resource, prefer)
        if ts:
            meta["lastUpdated"] = ts

    # (3) clinicalStatus / verificationStatus displays.
    if rt == "Condition":
        _populate_status_coding_display(resource.get("clinicalStatus"), _CONDITION_CLINICAL_DISPLAY)
        _populate_status_coding_display(resource.get("verificationStatus"), _CONDITION_VER_STATUS_DISPLAY)
    elif rt == "AllergyIntolerance":
        _populate_status_coding_display(resource.get("clinicalStatus"), _ALLERGY_CLINICAL_DISPLAY)
        _populate_status_coding_display(resource.get("verificationStatus"), _ALLERGY_VER_STATUS_DISPLAY)

    # (4) code.coding[].display sibling-copy (Condition / AllergyIntolerance).
    # JP output prefers JP display via `code_lookup(..., "ja")`; US uses "en".
    lang = "ja" if is_jp(country) else "en"
    if rt in ("Condition", "AllergyIntolerance"):
        code_field = resource.get("code")
        if isinstance(code_field, dict):
            _copy_display_from_sibling_coding(code_field.get("coding") or [], lang)
        if rt == "AllergyIntolerance":
            for reaction in resource.get("reaction", []) or []:
                if isinstance(reaction, dict):
                    for manifestation in reaction.get("manifestation", []) or []:
                        if isinstance(manifestation, dict):
                            _copy_display_from_sibling_coding(manifestation.get("coding") or [], lang)

    # (4b) JP-CLINS `JP_Condition_eCS` `code.coding:medisRecordNo` slice min=1.
    # Session 58 Chain #1 (v4 feedback, 6,242 errors, -1.5pp). Every JP
    # Condition must carry a MEDIS 病名管理番号 coding; without an ICD-10 →
    # keyNumber crosswalk shipped in clinosim, we use the MEDIS "uncoded
    # disease" placeholder — a real, spec-registered entry (`99999999` /
    # `未コード化傷病名`) used in JP hospital systems when reception input
    # does not map cleanly. Idempotent: skips when a MEDIS coding is already
    # present so future per-ICD-10 curation can be layered without conflict.
    if rt == "Condition" and is_jp(country):
        code_field = resource.get("code")
        if isinstance(code_field, dict):
            codings = code_field.setdefault("coding", [])
            if not any(isinstance(c, dict) and c.get("system") == _MEDIS_DISEASE_KEYNUMBER_SYSTEM for c in codings):
                codings.append(
                    {
                        "system": _MEDIS_DISEASE_KEYNUMBER_SYSTEM,
                        "code": _MEDIS_UNCODED_DISEASE_CODE,
                        "display": _MEDIS_UNCODED_DISEASE_DISPLAY,
                    }
                )

    # (5) Session 57 Chain 5 (v2 feedback §【最優先 5】):
    # JP_MedicationRequest_eCS pins `status` = patternCode "completed" and
    # `intent` = patternCode "order", and requires `substitution.allowed[x]`
    # to be a CodeableConcept (allowedBoolean is rejected). Spec:
    # `tx-server-build/.../clinical-information-sharing#1.12.0/package/
    # StructureDefinition-JP-MedicationRequest-eCS.json`. Enforced only on
    # JP output; US path keeps the original semantics.
    if rt == "MedicationRequest" and is_jp(country):
        resource["status"] = "completed"
        resource["intent"] = "order"
        sub = resource.get("substitution")
        if isinstance(sub, dict) and "allowedBoolean" in sub:
            allowed_bool = bool(sub.pop("allowedBoolean"))
            _sub_code = "E" if allowed_bool else "N"
            _sub_display = "equivalent" if allowed_bool else "none"
            sub["allowedCodeableConcept"] = {
                "coding": [
                    {
                        "system": _HL7_V3_SUBSTITUTION_SYSTEM,
                        "code": _sub_code,
                        "display": _sub_display,
                    }
                ]
            }
        # Session 57 v3 (Chain-10): JP_MedicationRequest_eCS requires
        # `identifier` min=3 with the `identifier:requestIdentifier` slice
        # (min=1 max=1) present in addition to the builder-emitted
        # `rpNumber` + `orderInRp` slices. The requestIdentifier value is
        # the per-medication order id; system is reused from the same
        # `resourceInstance-identifier` namespace applied to Observation
        # (Chain A) and Condition/AI (Chain-9). Idempotent — the walker
        # skips when the URI is already present in identifier[].
        ids = resource.get("identifier", []) or []
        rid = resource.get("id", "")
        if rid and not any(
            isinstance(i, dict) and i.get("system") == _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM for i in ids
        ):
            resource["identifier"] = [
                {"system": _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM, "value": rid},
                *ids,
            ]


def _normalize_jp_observation_category(resource: dict) -> None:
    """Normalize `Observation.category` for JP output(single seam).

    JP only(caller が country=JP のみで呼ぶ前提)。fhir-jp-validator
    feedback 2026-07-17 §"【最優先 3】"(286k errors)の適合設計:
    **1 category element = 1 coding**、HL7 と JP CS は必ず**別々の
    category element**として emit する。

    Spec 根拠(StructureDefinition snapshot 実測):

    - **JP_Observation_LabResult_eCS**(JP-CLINS 1.12.0)
      `Observation.category` は `1..1`、slice `laboratory` の
      `coding` は `1..1` かつ `coding.system fixedUri` =
      `JP_SimpleObservationCategory_CS`。HL7 coding 併記は
      `category:laboratory.coding max=1` を破り、かつ HL7 URL は
      fixedUri と不一致で slice discriminator を破る。→ **lab は JP CS
      単独 1 element**。
    - **JP_Observation_VitalSigns**(jp-core 1.2.0)
      `Observation.category` は `1..*`、slicing rules=`open`。
      slice `first` は `coding.system fixedUri = JP_Simple...` +
      `coding.code fixedCode = vital-signs`。`rules=open` により
      slice に match しない追加 element は許容される。base HL7
      `vitalsigns` profile(HAPI が LOINC 85354-9 等から自動適用)は
      `category:VSCat` slice に HL7 URL#vital-signs coding を要求。
      両方を満たすため → **VS は HL7 element + JP CS element の
      2 element** に分離。公式 example
      `Observation-jp-observation-vitalsigns-example-1.json` も
      同形。
    - **他 code**(social-history / imaging / procedure / survey / exam)
      HL7 base の各 slice discriminator も `coding.system+code` を
      使うため、混在すると同種の fixedUri 違反を招く。→ **JP CS
      単独 1 element**(vital-signs 以外は「1 element = 1 coding」を
      機械的に適用、conservatively minimal shape)。

    共通処理:

    - HL7 標準 URL および過去 clinosim 版の fabricated URL
      (`http://jpfhir.jp/fhir/observation-category`)は canonical
      `JP_SimpleObservationCategory_CS` に置換。
    - `display` は省略。JP CS も HL7 CodeSystem も英語 display のみ
      定義しているため日本語 display は HAPI に「Wrong Display Name」
      で reject される(feedback V5 発見 A')。日本語ラベルは
      `text` field 側で保持(translation として自由)。
    - observation-category 以外の system coding は preserve(独自
      CodeSystem を持ち込むテスト向けの defensive branch)。
      preserve 先は JP element(最初の JP category element の coding
      配列に前置)。
    """
    if resource.get("resourceType") != "Observation":
        return
    cats = resource.get("category")
    if not isinstance(cats, list) or not cats:
        return
    # Sweep every category element: collect obs-cat codes (in appearance
    # order, dedup), preserved foreign codings, and the first non-empty
    # `text` hint. Then rebuild `resource["category"]` from scratch — the
    # per-element output shape depends on the code (VS vs everything else)
    # so we cannot rewrite in place safely.
    category_codes: list[str] = []
    seen_codes: set[str] = set()
    preserved: list[dict] = []
    text_hint: str = ""
    for cat in cats:
        if not isinstance(cat, dict):
            continue
        if not text_hint:
            t = cat.get("text")
            if isinstance(t, str) and t:
                text_hint = t
        codings = cat.get("coding")
        if not isinstance(codings, list):
            continue
        for cod in codings:
            if not isinstance(cod, dict):
                continue
            sys_ = cod.get("system")
            code_ = cod.get("code")
            if sys_ in _HL7_OBSERVATION_CATEGORY_SYSTEMS or sys_ == _JP_OBSERVATION_CATEGORY_SYSTEM:
                if isinstance(code_, str) and code_ and code_ not in seen_codes:
                    category_codes.append(code_)
                    seen_codes.add(code_)
            else:
                preserved.append(cod)
    if not category_codes:
        return
    rebuilt: list[dict] = []
    for code_ in category_codes:
        if code_ == "vital-signs":
            # HL7 element first: matched by the auto-applied base
            # `vitalsigns` profile's `category:VSCat` slice; the JP Core
            # `category:first` slice ignores it via `rules=open`.
            rebuilt.append({"coding": [{"system": _HL7_OBSERVATION_CATEGORY_SYSTEM, "code": code_}]})
        # Always emit a JP element (satisfies JP Core / eCS slices for
        # every obs-cat code, including VS's `category:first`).
        rebuilt.append({"coding": [{"system": _JP_OBSERVATION_CATEGORY_SYSTEM, "code": code_}]})
    # Attach preserved foreign codings and the text hint to the first JP
    # element. Foreign category codings are rare in production; landing
    # them on the JP element mirrors the pre-refactor placement.
    for cat_elem in rebuilt:
        codings = cat_elem["coding"]
        if codings and codings[0].get("system") == _JP_OBSERVATION_CATEGORY_SYSTEM:
            if preserved:
                cat_elem["coding"] = list(preserved) + codings
            if text_hint:
                cat_elem["text"] = text_hint
            break
    resource["category"] = rebuilt


# iris4h-ai feedback V4/V5 P2 A: display 省略対象の「英語 display のみ」
# CodeSystem prefix 一覧。ここに含まれる system の Coding.display に日本語
# 文字が入っていた場合、post-emit walker が display を削除する。
# 出典:各 CodeSystem 公式定義(LOINC.org / SNOMED International /
# HL7 terminology / DICOM / UCUM / HL7 FHIR sid)は英語 display のみ定義
# しており、日本語文字を含む display は HAPI Validator に「Wrong Display
# Name」として rejected される。
#
# JP-specific CodeSystem(JP Core / JP-CLINS / MEDIS HOT / YJ code /
# clinosim custom)は本 prefix に含まれず、日本語 display が preserve される。
_ENGLISH_ONLY_CODING_SYSTEM_PREFIXES: tuple[str, ...] = (
    "http://loinc.org",
    "http://snomed.info/sct",
    "http://terminology.hl7.org/",
    "http://hl7.org/fhir/",
    "http://dicom.nema.org/",
    "http://unitsofmeasure.org",
)


def _contains_japanese_char(text: str) -> bool:
    """Return True if `text` contains at least one CJK Unified Ideograph /
    Hiragana / Katakana / halfwidth-fullwidth character.

    ASCII-only strings return False, so display fields that already carry a
    valid English label are left untouched by the P2 A walker.
    """
    for ch in text:
        cp = ord(ch)
        if (
            0x3040 <= cp <= 0x309F  # Hiragana
            or 0x30A0 <= cp <= 0x30FF  # Katakana
            or 0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs
            or 0xFF00 <= cp <= 0xFFEF  # Halfwidth and Fullwidth Forms
        ):
            return True
    return False


def _strip_japanese_display_on_english_only_systems(node: Any) -> None:
    """Recursively drop `display` from Coding entries on English-only
    CodeSystems when the display contains Japanese characters.

    Called only on JP output. Duck-types Coding via `system` + `code` +
    `display` all being non-empty strings; matches both
    `CodeableConcept.coding[]` entries and Coding-typed fields
    (e.g. `ImagingStudy.series[].modality`). The enclosing
    CodeableConcept's `text` field is not touched, so the Japanese
    human-readable label survives there.

    Non-standard CodeSystem URIs (JP Core CS / JP-CLINS CS / MEDIS HOT /
    YJ code / clinosim custom) are outside the prefix allowlist and are
    preserved as-is.

    Idempotent — re-running on already-normalized data has no effect
    (the walker only touches entries whose `display` still contains
    Japanese characters).
    """
    if isinstance(node, dict):
        sys_ = node.get("system")
        code_ = node.get("code")
        disp = node.get("display")
        if (
            isinstance(sys_, str)
            and isinstance(code_, str)
            and isinstance(disp, str)
            and disp
            and sys_.startswith(_ENGLISH_ONLY_CODING_SYSTEM_PREFIXES)
            and _contains_japanese_char(disp)
        ):
            del node["display"]
        for value in node.values():
            if isinstance(value, (dict, list)):
                _strip_japanese_display_on_english_only_systems(value)
    elif isinstance(node, list):
        for item in node:
            _strip_japanese_display_on_english_only_systems(item)


def _normalize_dt_fields(resource, country: str = "") -> None:
    """resource dict を再帰 walk、_DATETIME_FIELDS / _INSTANT_FIELDS / Period を正規化。

    Issue #570: threads ``country`` through so US cohorts append UTC (``Z``)
    instead of JST (``+09:00``). Callers with country in scope must pass it;
    the default `""` falls back to UTC (safest neutral).
    """
    if isinstance(resource, dict):
        for k, v in list(resource.items()):
            if k in _INSTANT_FIELDS and isinstance(v, str):
                resource[k] = _normalize_dt(v, country, want_instant=True)
            elif k in _DATETIME_FIELDS and isinstance(v, str):
                resource[k] = _normalize_dt(v, country)
            elif k in _PERIOD_KEYS and isinstance(v, dict):
                for pk in _PERIOD_FIELDS:
                    if pk in v:
                        v[pk] = _normalize_dt(v[pk], country)
                _normalize_dt_fields(v, country)
            elif isinstance(v, (dict, list)):
                _normalize_dt_fields(v, country)
    elif isinstance(resource, list):
        for item in resource:
            _normalize_dt_fields(item, country)


def _apply_jp_core_profile(resource: dict) -> None:
    """Attach the JP Core profile URLs for the resource's type when absent.

    C3-11..18 (session 42 cycle 3): idempotent — leaves existing meta.profile
    untouched when a builder has already set one. Appends any JP Core
    StructureDefinition URL that is not yet in `meta.profile[]`.
    Session 48 cleanup: dict shape unified with `_JP_CLINS_PROFILES` (list-of-URLs).

    session 59 #218:radiology DR builder が `_Radiology` profile を pre-set
    している場合、ここで `_Common` を追加すると 2 profile 併存で validator
    がどちらの制約で検査するか曖昧化。同 resourceType で複数 JP Core profile
    variants(_Common / _Radiology / _LabResult 等)が存在する場合、既に
    variant profile が set 済なら generic Common の追加をスキップ。
    """
    rt = resource.get("resourceType", "")
    profiles = _JP_CORE_PROFILES.get(rt)
    if not profiles:
        return
    meta = resource.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    # session 59 #218:DR に variant profile(_Radiology / _LabResult)が
    # pre-set 済なら Common を追加しない。
    if rt == "DiagnosticReport":
        _variant_prefix = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_DiagnosticReport_"
        if any(isinstance(p, str) and p.startswith(_variant_prefix) and not p.endswith("_Common") for p in profs):
            return
    for profile in profiles:
        if profile not in profs:
            profs.append(profile)


# JP-CLINS eCS profiles (電子カルテ情報共有サービス).
# Applied additively on top of JP Core profiles for country=JP.
# URLs verified against jpfhir.jp/fhir/clins/igv1/artifacts.html (v1.12.0,
# 2026-02-16) on 2026-07-12. Canonical URLs use /fhir/eCS/ path.
#
# JP-CLINS v1.12.0 publishes 5 profiles covering the "6 information items"
# domain: 傷病名 + 感染症 share JP_Condition_eCS; DiagnosticReport is not in
# JP-CLINS scope (lab results emitted only as Observation.LabResult).
_JP_CLINS_PROFILES: dict[str, list[str]] = {
    "Condition": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Condition_eCS",
    ],
    "AllergyIntolerance": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_AllergyIntolerance_eCS",
    ],
    "Observation": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS",
    ],
    "MedicationRequest": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_MedicationRequest_eCS",
    ],
    "Procedure": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Procedure_eCS",
    ],
}


def _apply_jp_clins_profile(resource: dict) -> None:
    """Attach JP-CLINS eCS profile URLs additively (idempotent).

    Called after `_apply_jp_core_profile`. Preserves existing meta.profile[]
    entries and skips URLs already present. Filters: for Observation, only
    laboratory category resources receive the JP-CLINS profile (vital signs
    stay on the JP Core profile only); for MedicationRequest, only resources that
    can actually satisfy the eCS constraints (see
    `_medication_request_satisfies_ecs`).
    """
    rt = resource.get("resourceType", "")
    profiles = _JP_CLINS_PROFILES.get(rt)
    if not profiles:
        return
    if rt == "Observation" and not _is_lab_observation(resource):
        return
    if rt == "MedicationRequest" and not _medication_request_satisfies_ecs(resource):
        return
    meta = resource.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    for url in profiles:
        if url not in profs:
            profs.append(url)


def _medication_request_satisfies_ecs(resource: dict) -> bool:
    """Predicate: may this MedicationRequest assert JP_MedicationRequest_eCS? (Issue #445)

    `JP_MedicationRequest_eCS` (JP-CLINS 1.12.0) raises `dosageInstruction` to
    **min=1**; the parent `JP_MedicationRequest` (JP Core 1.2.0) leaves it at
    **min=0**. Discharge and outpatient-renewal prescriptions transcribed from
    `patient.current_medications` carry neither dose nor route — both are lost upstream
    where the field is a plain `list[str]` (Issue #452) — so there is nothing truthful to
    put in `dosageInstruction`. Withholding the eCS URL leaves those resources conformant
    to the profile they *do* satisfy instead of claiming one they do not. This is the
    session-66 rule ("a `meta.profile` claim must follow data-completeness
    verification") applied per instance, and the same shape as the `_is_lab_observation`
    filter: a resourceType-wide claim narrowed by a predicate.

    Every MedicationRequest built from an inpatient Order carries a structured route, so
    this predicate is true for all of them and their output is unchanged.

    FUTURE CONSTRAINT — read before assembling a JP-CLINS Bundle: `JP_Bundle_CLINS`
    slices `Bundle.entry` with `discriminator: profile@resource` and `rules: closed`
    over 5 slices, so a MedicationRequest *without* the eCS URL matches no slice and
    becomes a closed-slicing violation rather than a `dosageInstruction` violation.
    clinosim emits no Bundle today (Bulk Data NDJSON, AD-31) and no Composition
    references a MedicationRequest, so that is currently unreachable. Whoever builds a
    CLINS bundle must first either fix Issue #452 (give these rows a real dose/route and
    delete this predicate) or exclude dosage-less prescriptions from the bundle.
    """
    return bool(resource.get("dosageInstruction"))


def _is_lab_observation(resource: dict) -> bool:
    """Predicate: does the resource qualify for JP_Observation_LabResult_eCS?

    Excludes microbiology (culture identification / antimicrobial
    susceptibility) even though FHIR category is ``laboratory`` — JP-CLINS
    eCS covers chemistry / hematology / serology only; microbiology and
    pathology are explicitly out of scope in the profile's prose
    (spec: "細菌検査(塗抹・培養・感受性)および病理はスコープ外").
    Microbiology Observations are emitted by ``_fhir_microbiology.py``
    with ``id`` prefixes ``mb-org-*`` / ``mb-sus-*``. Silent-fallback via
    id-prefix is intentional: category is a display concern (all lab-like
    results carry ``laboratory``), while profile stacking is a spec-scope
    concern that requires the finer distinction.

    NOTE: this predicate ONLY governs eCS stacking. The parent
    ``JP_Observation_LabResult`` (JP Core) is still emitted on
    microbiology Observations by ``_fhir_microbiology.py`` line ~227 —
    that too is non-compliant (correct target is
    ``JP_Observation_Microbiology``, JP Core 1.2.0). Tracked in
    TODO.md § T67-M1. Excluding only from eCS stacking here keeps this
    fix minimally invasive; the full profile-declaration fix is a
    separate work item.
    """
    for cat in resource.get("category", []) or []:
        for coding in cat.get("coding", []) or []:
            if coding.get("code") == "laboratory":
                rid = resource.get("id", "")
                if rid.startswith("mb-org-") or rid.startswith("mb-sus-"):
                    return False
                return True
    return False
