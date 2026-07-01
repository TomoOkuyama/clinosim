"""FHIR R4 CareTeam resource builder (Tier 1 #3 α-min-2 Task 11).

Emits 1 CareTeam per encounter with participant[]=[attending_physician,
primary_nurse]. 2-name scope for α-min-2; multi-disciplinary CareTeam
(pharmacist / nutritionist / rehab / MSW) deferred to β-JP-1.

Fields sourced from Encounter (α-min-2 additions):
- attending_physician_id (existing, set by simulators)
- primary_nurse_id (set by nursing_enricher POST_ENCOUNTER order=94, "")

No-drop invariant (CIF → FHIR):
  encounter_id              -> CareTeam.id (CARE_TEAM_ID_PREFIX + enc_id)
  attending_physician_id    -> CareTeam.participant[0].member (Practitioner ref)
                               "UNKNOWN" placeholder when empty (surfaces via
                               reference integrity audit; mirrors Composition
                               α-min-1 adv-1 fix pattern)
  primary_nurse_id          -> CareTeam.participant[1].member (only when non-empty)
  admission_datetime        -> CareTeam.period.start
  discharge_datetime        -> CareTeam.period.end (omitted when None)
  patient_id                -> CareTeam.subject (Patient ref)
  encounter_id              -> CareTeam.encounter (Encounter ref)

CareTeam.status:
  "active"   — discharge_datetime is None (encounter in-progress)
  "inactive" — discharge_datetime present (encounter completed)

Canonical constant ownership:
- CARE_TEAM_ID_PREFIX: this module (writer-owner, per spec §5.1 pattern)
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.output._fhir_common import BundleContext

__all__ = [
    "CARE_TEAM_ID_PREFIX",
    "_bb_care_teams",
]

CARE_TEAM_ID_PREFIX = "careteam-"

# SNOMED CT "Clinical team" — verified via SNOMED International browser, 2026-07-01.
# Registered in clinosim/codes/data/snomed-ct.yaml (Task 11 addition).
_CARE_TEAM_CATEGORY_SYSTEM = "http://snomed.info/sct"
_CARE_TEAM_CATEGORY_CODE = "424535000"
_CARE_TEAM_CATEGORY_EN = "Clinical team"
_CARE_TEAM_CATEGORY_JA = "臨床チーム"


def _bb_care_teams(ctx: BundleContext) -> list[dict[str, Any]]:
    """Bundle builder: emit 1 CareTeam per encounter.

    Handles both dict (production CIF) and dataclass (test fixture) encounter
    objects via _o() dual-access helper (PR-90 lesson).
    """
    encounters = _o(ctx.record, "encounters", []) or []
    if not encounters:
        return []
    lang = "ja" if ctx.country.lower() == "jp" else "en"
    patient_id = _o(_o(ctx.record, "patient", {}) or {}, "patient_id", "") or ctx.patient_id
    return [_build_care_team(enc, patient_id, lang) for enc in encounters]


def _build_care_team(encounter: Any, patient_id: str, lang: str) -> dict[str, Any]:
    """Build one FHIR R4 CareTeam resource from an Encounter (dataclass or dict)."""
    encounter_id = _o(encounter, "encounter_id", "") or ""
    attending_id = _o(encounter, "attending_physician_id", "") or ""
    primary_nurse_id = _o(encounter, "primary_nurse_id", "") or ""
    admission_dt = _o(encounter, "admission_datetime", None)
    discharge_dt = _o(encounter, "discharge_datetime", None)

    # CareTeam.status: active = in-progress, inactive = completed.
    status = "active" if discharge_dt is None else "inactive"

    # Category display — locale-aware via codes lookup; fallback to constant.
    # code_lookup returns the code itself when not found; guard against that.
    _raw_display = code_lookup("snomed-ct", _CARE_TEAM_CATEGORY_CODE, lang)
    if _raw_display and _raw_display != _CARE_TEAM_CATEGORY_CODE:
        category_display = _raw_display
    else:
        category_display = _CARE_TEAM_CATEGORY_JA if lang == "ja" else _CARE_TEAM_CATEGORY_EN

    # attending_physician_id — UNKNOWN placeholder when missing (mirrors α-min-1 Composition
    # adv-1 fix). Surfaces for reference integrity audit; does not silently drop the resource.
    attending_ref = attending_id if attending_id else "UNKNOWN"

    # Build participant list: attending always first; nurse only when non-empty.
    participants: list[dict[str, Any]] = [
        {"member": {"reference": f"Practitioner/{attending_ref}"}},
    ]
    if primary_nurse_id:
        participants.append(
            {"member": {"reference": f"Practitioner/{primary_nurse_id}"}},
        )

    care_team: dict[str, Any] = {
        "resourceType": "CareTeam",
        "id": f"{CARE_TEAM_ID_PREFIX}{encounter_id}",
        "status": status,
        "category": [{
            "coding": [{
                "system": _CARE_TEAM_CATEGORY_SYSTEM,
                "code": _CARE_TEAM_CATEGORY_CODE,
                "display": category_display,
            }],
            "text": category_display,
        }],
        "name": f"Care team for encounter {encounter_id}",
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "participant": participants,
    }

    # period — only when admission_datetime is present.
    if admission_dt is not None:
        period: dict[str, str] = {"start": _fmt_dt(admission_dt)}
        if discharge_dt is not None:
            period["end"] = _fmt_dt(discharge_dt)
        care_team["period"] = period

    return care_team


def _fmt_dt(dt: Any) -> str:
    """Format datetime-like value as ISO 8601 string."""
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)
