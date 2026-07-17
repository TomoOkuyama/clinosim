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

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output._fhir_common import BundleContext, to_fhir_datetime

__all__ = [
    "CARE_TEAM_ID_PREFIX",
    "_bb_care_teams",
]

CARE_TEAM_ID_PREFIX = "careteam-"

# SNOMED CT CareTeam.category — 2026-07-17 v2 feedback: 735320007 was Unknown
# code in the fhirserver's SNOMED International Edition 2026-06-01 loadout
# (3,788 CareTeam rejections). Switched to 407484005 "Rehabilitation care team"
# which the v2 feedback explicitly proposed and is verified present in the
# same edition.
#
# History:
# - session 42: SNOMED 424535000 "Clinical team" was flagged inactive by HL7
#   fhirserver, so we switched to LOINC LA27976-8 "Episode of care team focused".
# - 2026-07-16 v1 feedback: LOINC LA27976-8 is unknown in LOINC 2.82 (1,913
#   CareTeam failures). Adopted SNOMED 735320007 (Multidisciplinary care team)
#   in place of the LOINC code.
# - 2026-07-17 v2 feedback: 735320007 was itself Unknown in SNOMED International
#   Edition 2026-06-01 (3,788 rejections). Switched to 407484005 following
#   the v2 feedback's explicit recommendation (§【最優先 2】).
# - Semantic caveat: "Rehabilitation care team" is technically rehab-specific;
#   emitting it uniformly on all encounter types is a validator-conformance
#   trade-off. A follow-up issue tracks encounter-type-specific dispatch
#   (rehab_inpatient keeps 407484005; other encounter types get a general
#   care-team code once one is verified present in the tx server load).
_CARE_TEAM_CATEGORY_SYSTEM = get_system_uri("snomed-ct")
_CARE_TEAM_CATEGORY_CODE = "407484005"  # Rehabilitation care team (record artifact)
_CARE_TEAM_CATEGORY_EN = "Rehabilitation care team"
_CARE_TEAM_CATEGORY_JA = "リハビリテーションケアチーム"


def _bb_care_teams(ctx: BundleContext) -> list[dict[str, Any]]:
    """Bundle builder: emit 1 CareTeam per encounter.

    Handles both dict (production CIF) and dataclass (test fixture) encounter
    objects via _o() dual-access helper (PR-90 lesson).
    """
    encounters = _o(ctx.record, "encounters", []) or []
    if not encounters:
        return []
    lang = resolve_lang(ctx.country)
    patient_id = _o(_o(ctx.record, "patient", {}) or {}, "patient_id", "") or ctx.patient_id
    # C1-15 (session 41 cycle 1): pharmacist ids from the hospital roster for
    # multi-disciplinary CareTeam participation. Selected deterministically per
    # encounter (id hash) so re-generation is byte-identical (AD-16).
    pharmacist_ids = sorted(
        sid for sid, staff in (ctx.roster_map or {}).items() if (staff.get("role", "") or "") == "pharmacist"
    )
    return [_build_care_team(enc, patient_id, lang, pharmacist_ids, ctx.country) for enc in encounters]


def _build_care_team(
    encounter: Any,
    patient_id: str,
    lang: str,
    pharmacist_ids: list[str] | None = None,
    country: str = "US",
) -> dict[str, Any]:
    """Build one FHIR R4 CareTeam resource from an Encounter (dataclass or dict)."""
    encounter_id = _o(encounter, "encounter_id", "") or ""
    attending_id = _o(encounter, "attending_physician_id", "") or ""
    primary_nurse_id = _o(encounter, "primary_nurse_id", "") or ""
    admission_dt = _o(encounter, "admission_datetime", None)
    discharge_dt = _o(encounter, "discharge_datetime", None)
    ward_id = _o(encounter, "ward_id", "") or ""

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

    # CY2-A (session 42 cycle 3): CareTeam.participant.role = SNOMED role
    # code. Verified SNOMED CT concepts:
    #   309343006 = "Physician"
    #   224535009 = "Registered nurse"
    #   46255001  = "Pharmacist"
    # Build participant list: attending always first; nurse only when non-empty.
    def _role_coding(code: str, en: str, ja: str) -> list[dict]:
        display = ja if lang == "ja" else en
        return [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": code,
                        "display": display,
                    }
                ],
                "text": display,
            }
        ]

    participants: list[dict[str, Any]] = [
        {
            "role": _role_coding("309343006", "Physician", "医師"),
            "member": {"reference": f"Practitioner/{attending_ref}"},
        },
    ]
    if primary_nurse_id:
        participants.append(
            {
                "role": _role_coding("224535009", "Registered nurse", "看護師"),
                "member": {"reference": f"Practitioner/{primary_nurse_id}"},
            }
        )
    # C1-15 (session 41 cycle 1): pharmacist participant for encounters that
    # actually had medication activity — inpatient/emergency where a clinical
    # pharmacist is standard-of-care in JP multi-disciplinary teams
    # (病棟薬剤師). Deterministic selection from roster by encounter-id hash so
    # regeneration is byte-identical (AD-16). Outpatient AMB visits typically
    # don't invoke a bedside pharmacist so we skip them.
    enc_type = _o(encounter, "encounter_type", "") or ""
    if pharmacist_ids and enc_type in ("inpatient", "emergency"):
        idx = sum(ord(c) for c in encounter_id) % len(pharmacist_ids)
        participants.append(
            {
                "role": _role_coding("46255001", "Pharmacist", "薬剤師"),
                "member": {"reference": f"Practitioner/{pharmacist_ids[idx]}"},
            }
        )

    care_team: dict[str, Any] = {
        "resourceType": "CareTeam",
        "id": f"{CARE_TEAM_ID_PREFIX}{encounter_id}",
        "status": status,
        "category": [
            {
                "coding": [
                    {
                        "system": _CARE_TEAM_CATEGORY_SYSTEM,
                        "code": _CARE_TEAM_CATEGORY_CODE,
                        "display": category_display,
                    }
                ],
                "text": category_display,
            }
        ],
        "name": f"Care team for encounter {encounter_id}",
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "participant": participants,
        # CY7-24 (Chain-7): CareTeam.managingOrganization — the hospital
        # coordinating this care team. 100% clinosim CareTeams are hospital-
        # coordinated (no cross-facility care coordination modeled).
        "managingOrganization": [{"reference": "Organization/hospital-main"}],
        # CY7-25 (Chain-7): CareTeam.reasonCode — link to the encounter
        # primary diagnosis. Emit the chief_complaint as text when available;
        # the encounter's Condition already carries the ICD code so we don't
        # duplicate the coding.
        "reasonCode": [
            {"text": _o(encounter, "chief_complaint", "") or ("入院診療" if lang == "ja" else "Inpatient care")}
        ],
    }

    # period — only when admission_datetime is present.
    if admission_dt is not None:
        period: dict[str, str] = {"start": _fmt_dt(admission_dt)}
        if discharge_dt is not None:
            period["end"] = _fmt_dt(discharge_dt)
        care_team["period"] = period

    # C5-29 (Chain 1 close-out): CareTeam.telecom — synthetic ward extension
    # phone number for team contact. Deterministic per (encounter_id, ward_id).
    # Structural placeholder (mirrors C3-03 lot_number pattern): no
    # authoritative phone directory; format follows locale telephone
    # conventions so the field is spec-compliant ContactPoint.
    _telecom = _ward_telecom(encounter_id, ward_id, country)
    if _telecom:
        care_team["telecom"] = _telecom

    return care_team


def _ward_telecom(encounter_id: str, ward_id: str, country: str) -> list[dict[str, str]]:
    """Deterministic synthetic ward phone as FHIR ContactPoint.

    Structural placeholder — same category as C3-03 immunization lot_number
    (synthetic-but-deterministic). Format:
      JP: 03-XXXX-YYYY (Tokyo area code, ward-derived extension)
      US: (555) XXX-YYYY (555 reserved-for-fiction area code)
    Uses (encounter_id, ward_id) hash so the same encounter regenerates the
    same phone across runs (AD-16 byte-determinism).
    """
    if not encounter_id:
        return []
    seed_str = f"{encounter_id}:{ward_id}"
    h = sum(ord(c) * (i + 1) for i, c in enumerate(seed_str))
    if is_jp(country):
        ext = f"{(h // 10_000) % 10_000:04d}"
        num = f"{h % 10_000:04d}"
        value = f"03-{ext}-{num}"
    else:
        area = f"{(h // 10_000) % 1000:03d}"
        num = f"{h % 10_000:04d}"
        value = f"(555) {area}-{num}"
    return [{"system": "phone", "value": value, "use": "work"}]


def _fmt_dt(dt: Any) -> str:
    """Format datetime-like value as ISO 8601 string (FP-UNIFY-2 helper delegation)."""
    return to_fhir_datetime(dt)
