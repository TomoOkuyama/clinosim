"""JP Core / JP-CLINS profile stacking + resource-type discriminators.

Extracted from ``_fhir_post_process.py`` (Issue #555 PR3, folds Issue #556).

Applied AFTER every ``_bb_*`` builder emits a resource. ``_apply_jp_core_profile``
attaches the JP Core StructureDefinition URL(s) matching the resourceType;
``_apply_jp_clins_profile`` layers the JP-CLINS eCS URL on top, gated by
predicates (``_is_lab_observation``, ``_medication_request_satisfies_ecs``) that
enforce the rule "a ``meta.profile`` claim must follow
data-completeness verification".
"""

from __future__ import annotations

import re

# FHIR R4 `Resource.id` type: `[A-Za-z0-9\-\.]{1,64}`. iris4h-ai P0 finding
# (2026-07-17): 812,606 ids across the export violated this spec — `_` in id
# and >64 char ids were rejected by IRIS FHIR endpoint with HTTP 400. HAPI
# validator is more lenient but the FHIR spec is strict. The regex here is the
# single source of truth for the pattern — every writer path routes ids
# through it, and any non-conforming id logs a warning (fail-soft: the write
# still succeeds so a bug in a single builder does not break the whole export,
# but the log lets the audit CI catch regressions).
_FHIR_ID_PATTERN = re.compile(r"^[A-Za-z0-9\-\.]{1,64}$")


# deferred cleanup (g): shape unification.
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
    # RM-6c: Procedure profile so RECORD-based and ORDER-based
    # Procedure emissions both carry JP Core conformance.
    "Procedure": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Procedure"],
    # (#145): additional JP Core StructureDefinition URLs — spec
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


def _apply_jp_core_profile(resource: dict) -> None:
    """Attach the JP Core profile URLs for the resource's type when absent.

    C3-11..18: idempotent — leaves existing meta.profile
    untouched when a builder has already set one. Appends any JP Core
    StructureDefinition URL that is not yet in `meta.profile[]`.
    cleanup: dict shape unified with `_JP_CLINS_PROFILES` (list-of-URLs).

    #218:radiology DR builder が `_Radiology` profile を pre-set
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
    # #218:DR に variant profile(_Radiology / _LabResult)が
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

    Issue #743: any resource that receives the eCS profile URL also gets the
    JP-CLINS institutional-attribution extensions (`JP_eCS_InstitutionNumber`
    + `JP_eCS_Department`), which are must-support on Condition,
    AllergyIntolerance, MedicationRequest per the eCS SDs. Attaching the
    extensions in the same hook that adds the profile URL keeps the
    "profile assertion must follow data completeness" invariant true by
    construction — the two moves are strictly paired.

    The Department extension context excludes Patient (Patient emits its own
    profile URL inline and calls the InstitutionNumber attach separately in
    `demographics/patient.py`). Observation is in extension scope but is
    covered in a follow-up (this hook currently attaches extensions only
    for Condition / AllergyIntolerance / MedicationRequest).
    """
    from clinosim.modules.output.fhir_r4.lib.common import attach_ecs_institutional_extensions

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
    # Issue #743: extensions for the 3 profiles where the eCS SDs mandate
    # them as must-support. Skip Observation (follow-up) and Procedure
    # (extension SD context does not list Procedure).
    if rt in ("Condition", "AllergyIntolerance", "MedicationRequest"):
        attach_ecs_institutional_extensions(resource, "JP", include_department=True)


def _medication_request_satisfies_ecs(resource: dict) -> bool:
    """Predicate: may this MedicationRequest assert JP_MedicationRequest_eCS? (Issue #445)

    `JP_MedicationRequest_eCS` (JP-CLINS 1.12.0) raises `dosageInstruction` to
    **min=1**; the parent `JP_MedicationRequest` (JP Core 1.2.0) leaves it at
    **min=0**. Discharge and outpatient-renewal prescriptions transcribed from
    `patient.current_medications` carry neither dose nor route — both are lost upstream
    where the field is a plain `list[str]` (Issue #452) — so there is nothing truthful to
    put in `dosageInstruction`. Withholding the eCS URL leaves those resources conformant
    to the profile they *do* satisfy instead of claiming one they do not. This is the
    rule ("a `meta.profile` claim must follow data-completeness
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
