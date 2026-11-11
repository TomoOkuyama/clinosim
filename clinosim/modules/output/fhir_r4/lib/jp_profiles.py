"""JP Core / JP-CLINS profile and identifier-system URIs used in more than one
place by the FHIR R4 builders (Issue #2842).

``docs/design-guides/implementation-rules.md`` §4: a profile or identifier
URI used in more than one place is one module-level constant. Each value is
the spec ``fixedUri`` / canonical URL, unchanged from the literals it
replaces, and is pinned by ``tests/unit/output/test_jp_uri_constants_2842.py``
(which also asserts the literal appears nowhere else under ``clinosim/``).
"""

from __future__ import annotations

__all__ = [
    "JP_COMPOSITION_EDISCHARGE_SUMMARY_PROFILE",
    "JP_INSURANCE_MEDICAL_INSTITUTION_NO_SYSTEM",
    "JP_LOCATION_PROFILE",
    "JP_MEDICATION_ADMINISTRATION_INDEX_SYSTEM",
    "JP_MEDICATION_RP_GROUP_NUMBER_SYSTEM",
    "JP_OBSERVATION_COMMON_PROFILE",
    "JP_ORGANIZATION_ECS_PROFILE",
    "JP_ORGANIZATION_PROFILE",
    "JP_PROCEDURE_PROFILE",
    "JP_RESOURCE_INSTANCE_IDENTIFIER_SYSTEM",
]

# --- Identifier systems ---------------------------------------------------- #

# 保険医療機関番号 (Organization.identifier:medicalInstitutionCode slice).
JP_INSURANCE_MEDICAL_INSTITUTION_NO_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/insurance-medical-institution-no"
# リソース一意識別子 (identifier:resourceIdentifier slice; Observation,
# Condition, AllergyIntolerance, MedicationRequest, Composition).
JP_RESOURCE_INSTANCE_IDENTIFIER_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier"
# 処方箋内部の剤グループとしての Rp 番号 (MedicationRequest.identifier:rpNumber).
JP_MEDICATION_RP_GROUP_NUMBER_SYSTEM = "http://jpfhir.jp/fhir/core/mhlw/IdSystem/Medication-RPGroupNumber"
# 同一 Rp 内の薬剤連番 (MedicationRequest.identifier:orderInRp).
JP_MEDICATION_ADMINISTRATION_INDEX_SYSTEM = "http://jpfhir.jp/fhir/core/mhlw/IdSystem/MedicationAdministrationIndex"

# --- Profiles (meta.profile) ----------------------------------------------- #

JP_OBSERVATION_COMMON_PROFILE = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"
# JP_Observation_LabResult: `variants: Observation/LabResult` in
# codes/data/fhir-profiles-jp-core.yaml (Issue #3201).
JP_LOCATION_PROFILE = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Location"
JP_ORGANIZATION_PROFILE = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Organization"
JP_ORGANIZATION_ECS_PROFILE = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Organization_eCS"
JP_PROCEDURE_PROFILE = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Procedure"
JP_COMPOSITION_EDISCHARGE_SUMMARY_PROFILE = (
    "http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/JP_Composition_eDischargeSummary"
)
