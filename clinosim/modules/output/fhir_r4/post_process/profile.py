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
from functools import cache
from pathlib import Path

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
# JP Core / US Core / JP-CLINS profile URL registries moved under
# post-#1880 review (hardcoded-audit Finding 11) to:
#   - clinosim/codes/data/fhir-profiles-jp-core.yaml
#   - clinosim/codes/data/fhir-profiles-us-core.yaml
#   - clinosim/codes/data/fhir-profiles-jp-clins.yaml
# Each yaml carries `metadata.source` provenance (IG package + version)
# and is loaded once per process via the module-level `@cache`-ed
# helpers below.


@cache
def _jp_core_profiles() -> dict[str, list[str]]:
    import yaml

    path = Path(__file__).resolve().parents[4] / "codes" / "data" / "fhir-profiles-jp-core.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return {str(rt): [str(u) for u in urls] for rt, urls in (raw.get("profiles", {}) or {}).items()}


@cache
def _us_core_profiles() -> dict[str, list[str]]:
    import yaml

    path = Path(__file__).resolve().parents[4] / "codes" / "data" / "fhir-profiles-us-core.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return {str(rt): [str(u) for u in urls] for rt, urls in (raw.get("profiles", {}) or {}).items()}


@cache
def _us_core_condition_category_profiles() -> dict[str, str]:
    import yaml

    path = Path(__file__).resolve().parents[4] / "codes" / "data" / "fhir-profiles-us-core.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return {str(k): str(v) for k, v in (raw.get("condition_category_profiles", {}) or {}).items()}


@cache
def _jp_clins_profiles() -> dict[str, list[str]]:
    import yaml

    path = Path(__file__).resolve().parents[4] / "codes" / "data" / "fhir-profiles-jp-clins.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return {str(rt): [str(u) for u in urls] for rt, urls in (raw.get("profiles", {}) or {}).items()}


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


# US Core v9.0 profile URLs — Issue #1768 (Cluster E T8a).
# Mirrors `_JP_CORE_PROFILES`: single-profile resource types where no
# sub-type dispatch is needed. Condition and Observation are omitted
# because US Core publishes multiple variants per resource type keyed on
# category (problem-list vs encounter-diagnosis; lab vs vital-signs vs
# social-history); their category-dispatched profile selection is a
# separate work item (T8b).
#
# URLs quoted verbatim from the ``hl7.fhir.us.core@9.0.0`` IG package
# (``package/StructureDefinition-us-core-*.json`` ``.url`` fixedUri)
# per the repo convention of citing fixedUri rather than guessing
# (``feedback_verify_fhir_profile_uri_from_spec``).
# US Core profiles + category-dispatched Condition profiles moved to
# `clinosim/codes/data/fhir-profiles-us-core.yaml` (post-#1880 review,
# Finding 11). Dispatch inspects `category.coding[].code`; a Condition
# without a recognized code gets no profile claim (data-completeness
# precondition — see `feedback_profile_assertion_requires_data_completeness`).


def _apply_us_core_condition_profile(resource: dict) -> None:
    """Dispatch a Condition to its US Core variant by category coding.

    No-op when ``category.coding[].code`` matches neither variant — a
    profile claim without the corresponding category coding would
    violate the data-completeness precondition.
    """
    for cat in resource.get("category", []) or []:
        for coding in cat.get("coding", []) or []:
            code = coding.get("code")
            url = _us_core_condition_category_profiles().get(code or "")
            if url:
                meta = resource.setdefault("meta", {})
                profs = meta.setdefault("profile", [])
                if url not in profs:
                    profs.append(url)
                return


def _apply_us_core_profile(resource: dict) -> None:
    """Attach the US Core v9 profile URL for the resource's type when absent.

    Mirrors ``_apply_jp_core_profile``: idempotent, preserves existing
    ``meta.profile[]`` entries, silently no-ops for resource types that
    are not in the single-profile registry.

    Dispatches category-sensitive resource types to their variant-aware
    helpers:

    * Condition → ``_apply_us_core_condition_profile`` (T8b-1).
    * Observation / DiagnosticReport → still deferred (T8b-2 / later),
      the single-profile registry excludes them.

    Issue #1768: declaring the US Core profile URL lets the HL7 FHIR
    validator check the resource against US Core v9 constraints rather
    than base R4 only. The precondition is data-completeness
    (``feedback_profile_assertion_requires_data_completeness``) — each
    resource type registered here has already had its US Core
    must-support fields emitted by the per-resource builders (Patient
    race / ethnicity / birthsex via ``demographics/patient.py``,
    Coverage profile already declared inline in ``identity.yaml`` and
    the extensions block already stripped empty, etc.).
    """
    rt = resource.get("resourceType", "")
    if rt == "Condition":
        _apply_us_core_condition_profile(resource)
        return
    profiles = _us_core_profiles().get(rt)
    if not profiles:
        return
    meta = resource.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    for profile in profiles:
        if profile not in profs:
            profs.append(profile)


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
    profiles = _jp_core_profiles().get(rt)
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
# URLs verified against jpfhir.jp/fhir/clins/igv1/artifacts.html (v1.13.0,
# 2026-02-16) on 2026-07-12. Canonical URLs use /fhir/eCS/ path.
#
# JP-CLINS v1.13.0 publishes 5 profiles covering the "6 information items"
# domain: 傷病名 + 感染症 share JP_Condition_eCS; DiagnosticReport is not in
# JP-CLINS scope (lab results emitted only as Observation.LabResult).
# JP-CLINS eCS profile URLs moved to
# `clinosim/codes/data/fhir-profiles-jp-clins.yaml` (post-#1880 review,
# Finding 11). Issue #745 (Wave 3) extensions + the Encounter_eCS /
# FamilyMemberHistory_eCS deferral rationale are captured there.

# Static deterministic placeholder for `meta.lastUpdated` used to satisfy the
# JP-CLINS eCS must-support requirement on resources whose CIF source data
# carries no timestamp. Mirrors the pattern already used in
# `demographics/patient.py:370` and `encounters/facility.py:91`. Real-world
# lastUpdated is server-provided; clinosim's simulator has no such notion, so
# a fixed value keeps reproducibility byte-clean while satisfying min=1.
_JP_ECS_LAST_UPDATED_PLACEHOLDER = "2026-01-01T00:00:00+09:00"


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
    profiles = _jp_clins_profiles().get(rt)
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
    # Issue #745: `JP_Immunization_eCS` mandates `meta.lastUpdated` (min=1,
    # must-support); the emit path never populated it. Fill the same
    # deterministic placeholder pattern used by patient.py + facility.py
    # only when the eCS profile URL is actually being added — the two
    # moves are paired (declare eCS ↔ satisfy its must-support). The
    # other three new eCS profiles (DocumentReference / Device /
    # DeviceUseStatement) carry zero must-supports so no field emit is
    # needed.
    if rt == "Immunization" and not meta.get("lastUpdated"):
        meta["lastUpdated"] = _JP_ECS_LAST_UPDATED_PLACEHOLDER


def _medication_request_satisfies_ecs(resource: dict) -> bool:
    """Predicate: may this MedicationRequest assert JP_MedicationRequest_eCS? (Issue #445)

    `JP_MedicationRequest_eCS` (JP-CLINS 1.13.0) raises `dosageInstruction` to
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

    Also excludes the patient-lifetime blood-type ABO/RhD Observations
    emitted by ``labs/blood_type.py`` (``blood-abo-*`` / ``blood-rh-*``
    ids): they carry only LOINC codings for the group and the SNOMED CT
    result concept — no JP-CLINS CoreLabo / LocalCode co-emission — and
    so cannot satisfy the eCS applicability rule. The
    ``NON_ORDER_DRIVEN_LAB_OBS_ID_PREFIXES`` by-design registry in
    ``labs/service_request.py`` is the shared source of truth for
    non-order-driven lab Observation families; this predicate routes
    through it so a new family added to the registry is excluded from
    eCS stacking automatically (same "profile assertion must follow
    data completeness" invariant).

    Prior to Issue #2003 the blood-type Observations emitted the
    non-canonical v2-0074 ``LAB`` code on ``category.coding`` and so
    were silently (and accidentally) excluded by the ``== "laboratory"``
    category test below; this change restores that exclusion
    explicitly, now that the canonical ``laboratory`` code is in use.

    NOTE: this predicate ONLY governs eCS stacking. The parent
    ``JP_Observation_LabResult`` (JP Core) is still emitted on
    microbiology Observations by ``_fhir_microbiology.py`` line ~227 —
    that too is non-compliant (correct target is
    ``JP_Observation_Microbiology``, JP Core 1.2.0). Tracked in
    TODO.md § T67-M1. Excluding only from eCS stacking here keeps this
    fix minimally invasive; the full profile-declaration fix is a
    separate work item.
    """
    from clinosim.modules.output.fhir_r4.labs.service_request import (
        NON_ORDER_DRIVEN_LAB_OBS_ID_PREFIXES,
    )

    for cat in resource.get("category", []) or []:
        for coding in cat.get("coding", []) or []:
            if coding.get("code") == "laboratory":
                rid = resource.get("id", "")
                if any(rid.startswith(p) for p in NON_ORDER_DRIVEN_LAB_OBS_ID_PREFIXES):
                    return False
                return True
    return False
