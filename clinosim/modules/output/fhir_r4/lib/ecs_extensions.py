"""JP-CLINS eCS institutional-attribution extensions (Issue #743; split out of
``common.py`` in Issue #2530)."""

from __future__ import annotations

from typing import Any

from clinosim.locale.loaders.medical_display import department_display
from clinosim.modules._shared import is_jp

__all__ = [
    "attach_ecs_institutional_extensions",
    "build_ecs_department_extension",
    "build_ecs_institution_extension",
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
# Placeholder policy: hospital_config carries no institutional code or per-
# encounter department name today, so both extensions carry synthetic
# placeholders. Downstream Issues will thread real values from encounter
# context once hospital_config gains those fields.
_JP_ECS_INSTITUTION_NUMBER_EXT_URL = (
    "http://jpfhir.jp/fhir/clins/Extension/StructureDefinition/JP_eCS_InstitutionNumber"
)
_JP_ECS_DEPARTMENT_EXT_URL = "http://jpfhir.jp/fhir/eCS/Extension/StructureDefinition/JP_eCS_Department"
_JP_ECS_INSTITUTION_ID_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/insurance-medical-institution-no"
_JP_ECS_INSTITUTION_PLACEHOLDER = "1300000000"
_JP_ECS_DEPARTMENT_PLACEHOLDER = department_display("primary_care", "ja")


def build_ecs_institution_extension() -> dict[str, Any]:
    """Return the `JP_eCS_InstitutionNumber` extension for JP eCS resources.

    Value is the fixed 10-digit institutional-code placeholder — same as
    `hospital-main.identifier:medicalInstitutionCode`. Callers gate on JP.
    """
    return {
        "url": _JP_ECS_INSTITUTION_NUMBER_EXT_URL,
        "valueIdentifier": {
            "system": _JP_ECS_INSTITUTION_ID_SYSTEM,
            "value": _JP_ECS_INSTITUTION_PLACEHOLDER,
        },
    }


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
    if not is_jp(country):
        return
    exts = resource.setdefault("extension", [])
    if not isinstance(exts, list):
        return
    existing = {e.get("url") for e in exts if isinstance(e, dict)}
    if _JP_ECS_INSTITUTION_NUMBER_EXT_URL not in existing:
        exts.append(build_ecs_institution_extension())
    if include_department and _JP_ECS_DEPARTMENT_EXT_URL not in existing:
        exts.append(build_ecs_department_extension(department_text))
