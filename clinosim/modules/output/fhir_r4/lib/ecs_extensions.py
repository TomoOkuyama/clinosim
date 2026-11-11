"""JP-CLINS eCS institutional-attribution extensions (Issue #743; split out of
``common.py`` in Issue #2530)."""

from __future__ import annotations

from typing import Any

from clinosim.country_profile import country_profile
from clinosim.locale.loaders.fhir_identity import load_facility_identity
from clinosim.locale.loaders.medical_display import department_display
from clinosim.modules.output.fhir_r4.lib.jp_profiles import JP_INSURANCE_MEDICAL_INSTITUTION_NO_SYSTEM

__all__ = [
    "attach_ecs_institutional_extensions",
    "build_ecs_department_extension",
    "build_ecs_institution_extension",
    "hospital_institution_code",
]


# --------------------------------------------------------------------------- #
# JP-CLINS eCS institutional-attribution extensions (Issue #743).
#
# `JP_eCS_InstitutionNumber` and `JP_eCS_Department` are must-support on the
# JP-CLINS eCS profiles for Condition, AllergyIntolerance, MedicationRequest,
# and Patient (InstitutionNumber only — the Department extension's context
# excludes Patient). Their absence on eCS-profile-declaring resources
# violates the memory rule
# `[★★★★ Profile assertion は data-completeness verify 後]`.
#
# Extension URLs / systems come from the authoritative SDs:
#   - StructureDefinition-jp-ecs-institution-number.json
#   - StructureDefinition-jp-ecs-department.json
# InstitutionNumber.value[x] type = Identifier; the Identifier.system for the
# 10-digit medical-institution code is the same URI used by the facility
# builder's `hospital-main.identifier:medicalInstitutionCode` (Issue #746).
#
# The institution number is the hospital's 10-digit 医療機関コード from
# ``locale/jp/facility_identity.yaml`` (Issue #3129); the department falls
# back to a placeholder when the caller has no encounter department.
_JP_ECS_INSTITUTION_NUMBER_EXT_URL = (
    "http://jpfhir.jp/fhir/clins/Extension/StructureDefinition/JP_eCS_InstitutionNumber"
)
_JP_ECS_DEPARTMENT_EXT_URL = "http://jpfhir.jp/fhir/eCS/Extension/StructureDefinition/JP_eCS_Department"
_JP_ECS_INSTITUTION_ID_SYSTEM = JP_INSURANCE_MEDICAL_INSTITUTION_NO_SYSTEM
_JP_ECS_DEPARTMENT_PLACEHOLDER = department_display("primary_care", "ja")


def build_ecs_institution_extension() -> dict[str, Any]:
    """Return the `JP_eCS_InstitutionNumber` extension for JP eCS resources.

    Value is the hospital's 10-digit 医療機関コード (Issue #3129) — same as
    `hospital-main.identifier:medicalInstitutionCode`. Callers gate on JP.
    """
    return {
        "url": _JP_ECS_INSTITUTION_NUMBER_EXT_URL,
        "valueIdentifier": {
            "system": _JP_ECS_INSTITUTION_ID_SYSTEM,
            "value": hospital_institution_code("JP"),
        },
    }


def hospital_institution_code(country: str) -> str:
    """The hospital's 10-digit 医療機関コード (``facility_identity.yaml``,
    Issue #3129); empty for a country without one."""
    return str(load_facility_identity(country).get("institution_code") or "")


def build_ecs_department_extension(department_text: str = "") -> dict[str, Any]:
    """Return the `JP_eCS_Department` extension for JP eCS resources.

    `department_text` is the department display name; falls back to the
    「総合診療科」placeholder when the caller cannot determine one from
    encounter context. Callers gate on JP.
    """
    text = department_text or _JP_ECS_DEPARTMENT_PLACEHOLDER
    return {
        "url": _JP_ECS_DEPARTMENT_EXT_URL,
        "valueCodeableConcept": {"text": text},
    }


def attach_ecs_institutional_extensions(
    resource: dict[str, Any],
    country: str,
    department_text: str = "",
    include_department: bool = True,
) -> None:
    """Append the two JP-CLINS eCS institutional-attribution extensions to
    ``resource["extension"]`` on JP output. No-op on US output. Idempotent:
    skips either extension whose URL is already present so re-application
    (e.g. from a post-hook after the builder) does not duplicate.

    Set ``include_department=False`` for Patient (the Department extension's
    context excludes Patient per its SD).
    """
    if not country_profile(country).uses("jp_clins"):
        return
    exts = resource.setdefault("extension", [])
    if not isinstance(exts, list):
        return
    existing = {e.get("url") for e in exts if isinstance(e, dict)}
    if _JP_ECS_INSTITUTION_NUMBER_EXT_URL not in existing:
        exts.append(build_ecs_institution_extension())
    if include_department and _JP_ECS_DEPARTMENT_EXT_URL not in existing:
        exts.append(build_ecs_department_extension(department_text))
