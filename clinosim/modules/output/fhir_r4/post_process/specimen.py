"""Companion Specimen synthesis for lab Observations.

Extracted from ``_fhir_post_process.py`` (Issue #555 PR3, folds Issue #556).
JP-CLINS ``JP_Observation_LabResult_eCS`` declares ``Observation.specimen``
with ``min=1``; this module detects lab Observations that lack a builder-set
specimen and synthesizes a blood-default (or urine-for-Urinalysis) companion
Specimen resource keyed to the parent Observation's id.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes.loader import lookup as code_lookup
from clinosim.modules._shared import resolve_lang
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)

# Companion-Specimen id prefix. Post-#854 the id body is a sha256-derived
# opaque hex (see ``_resolve_specimen_id`` below) rather than the pre-#854
# ``lab-<encounter>-NNNN`` compound — traceability is preserved via
# ``identifier[]`` under :data:`SPECIMEN_KEY_SYSTEM`.
_COMPANION_SPECIMEN_ID_PREFIX = "spec-"

# === Issue #854 Bucket B (PR-specimen): opaque Specimen.id ===
# Same pattern as PR #357 / #863 / #867 / #868 / #869 / #878 / #879 / #880
# / #881. Both Specimen producers — microbiology cultures
# (``labs/microbiology.py::_bb_microbiology``) and companion-Specimen
# post-process (this file) — funnel through this shared resolver so the
# opaque-id / structural-key round-trip is consistent regardless of the
# source path.
#
# PUBLIC constants so downstream readers (identifier[] lookup, future
# audit tooling) can import them for identifier-based recovery without
# string-parsing the (now opaque) ``.id``.
SPECIMEN_ID_PREFIX = _COMPANION_SPECIMEN_ID_PREFIX
SPECIMEN_KEY_SYSTEM = structural_key_system("specimen-key")


def _resolve_specimen_id(structural_key: str) -> str:
    """Return the FHIR Specimen.id for a structural key (Issue #854 Bucket B).

    Shape: ``spec-{sha256(structural_key)[:12]}`` = 17 chars, fixed.

    Structural keys (pre-#854 id body without ``spec-`` prefix):
    - microbiology: ``{enc or patient_id}-{i}`` (i is the 0-based culture
      index in the ``microbiology`` list).
    - companion post-process: the parent lab Observation.id — post-#878
      that is itself an opaque ``lab-<12hex>``; the specimen is derived
      from it so a viewer can trivially pair specimen ↔ observation by
      matching the corresponding round-trip identifiers.

    Every cross-reference site (``Observation.specimen``,
    ``DiagnosticReport.specimen[]``) receives ``spec_id`` via variable
    propagation from the emit site — no string reconstruction happens
    anywhere else, so byte-consistency is preserved by construction.
    """
    return derive_opaque_id(SPECIMEN_ID_PREFIX, structural_key)


# Specimen SNOMED code constants. Displays resolve via code_lookup against
# `clinosim/codes/data/snomed-ct.yaml`:
#   119297000 → Blood specimen / 血液検体 — default for lab output
#     (CBC / chem panel / LFT / cardiac markers / coagulation / ...).
#   122575003 → Urine specimen / 尿検体 — Urinalysis / urine dipstick tests.
_SPECIMEN_SNOMED_BLOOD = "119297000"
_SPECIMEN_SNOMED_URINE = "122575003"


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


def _pick_specimen_type_for_lab(observation: dict) -> str:
    """Pick the Specimen.type SNOMED code for a lab Observation. Blood is
    the default; Urinalysis-style tests get urine specimen.

    The rule is intentionally conservative — only names that clearly indicate
    a non-blood specimen switch away from blood. Anything else stays blood so
    clinosim doesn't silently fabricate specimen types on general chem panels.
    """
    code_field = observation.get("code") or {}
    text = str(code_field.get("text", "") or "").lower()
    for coding in code_field.get("coding", []) or []:
        display = str(coding.get("display", "") or "").lower()
        if "urin" in display or "urine" in display:
            return _SPECIMEN_SNOMED_URINE
    if "urin" in text or "urine" in text:
        return _SPECIMEN_SNOMED_URINE
    return _SPECIMEN_SNOMED_BLOOD


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
    # Issue #854 Bucket B (PR-specimen): opaque Specimen.id.
    # Structural key = the parent lab Observation.id (post-#878 that is
    # itself already the opaque ``lab-<12hex>``). The pre-#854 internal
    # identifier system (``urn:clinosim:specimen-id``) is preserved
    # verbatim so any consumer already keyed on that system keeps
    # working; a new ``SPECIMEN_KEY_SYSTEM`` identifier carries the
    # structural key for downstream opaque-id-aware consumers.
    _spec_structural_key = obs_id
    spec_id = _resolve_specimen_id(_spec_structural_key)
    subject = observation.get("subject", {}) or {}
    specimen_snomed = _pick_specimen_type_for_lab(observation)
    display = code_lookup("snomed-ct", specimen_snomed, resolve_lang(country))
    specimen: dict[str, Any] = {
        "resourceType": "Specimen",
        "id": spec_id,
        "identifier": [
            {"system": "urn:clinosim:specimen-id", "value": spec_id},
            wrap_as_identifier(_spec_structural_key, SPECIMEN_KEY_SYSTEM),
        ],
        "subject": subject,
        "type": {
            "coding": [{"system": get_system_uri("snomed-ct"), "code": specimen_snomed, "display": display}],
            "text": display,
        },
        "status": "available",
    }
    edt = observation.get("effectiveDateTime")
    if edt:
        specimen["collection"] = {"collectedDateTime": edt}
    return specimen
