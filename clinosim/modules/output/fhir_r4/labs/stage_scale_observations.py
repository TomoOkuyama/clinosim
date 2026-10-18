"""FHIR R4 chronic-disease stage-scale Observation builder.

Emits one Observation per (patient, scale) carrying the latest known
clinical stage for scaled chronic conditions whose stage string is
already populated on ``chronic_conditions[].stage``:

- G20 (Parkinson's disease) → Hoehn & Yahr 1-5
- G35 (Multiple sclerosis) → banded EDSS (0-2 / 2.5-5 / 5.5-7 / 7.5-10)
- I69.1 / I69.3 (post-stroke sequela) → modified Rankin Scale 0-5
- F00 (Dementia) → Clinical Dementia Rating 0.5 / 1 / 2 / 3

One Observation per patient per scale — the "latest annual assessment"
semantic matching real-world outpatient-followup chart review. Pre-fix
no Observation of any of these scales was emitted; downstream readers
could see the ICD on the problem list but had no corresponding score
Observation to anchor severity (feat gap flagged in the v0.6.5 → HEAD
coverage audit).

## Emit shape

- ``category = survey`` (per HL7 v3-ObservationCategory) — these are
  clinician-administered rating scales, not laboratory results.
- ``code.coding[0].system = LOINC`` where a well-known LOINC exists:
  mRS = 72136-5, EDSS = 77691-7, CDR = 72172-0. Hoehn & Yahr has no
  authoritative LOINC in common clinical use at the time of writing;
  the H&Y Observation emits a display-only ``code.text`` so it round-
  trips cleanly without fabricating a code.
- ``value`` type varies by scale:
    - mRS → ``valueInteger`` (0-5)
    - CDR → ``valueDecimal`` (0.5 / 1 / 2 / 3)
    - EDSS / H&Y → ``valueString`` (banded label — the EDSS CIF stage
      is a range like "EDSS 5.5-7", not a point score, so a quantity
      value would misrepresent the data).
- ``subject`` → Patient reference. ``encounter`` is populated with the
  patient's snapshot-anchored last outpatient followup (or admission
  index encounter when no followup exists) so chart viewers can anchor
  the assessment to a visit.
- ``effectiveDateTime`` = that encounter's admission datetime.
- Deterministic ``id`` derived from ``{patient_id}-{scale_suffix}``.

## Determinism / RNG-shape isolation

No random draws. Stage comes verbatim from the already-populated
``chronic_conditions[].stage`` written at activator / aging-hook time;
this builder reads it, never advances it. Introducing the emit cannot
shift any downstream RNG cursor — adding a new resource type with no
master-RNG dependency is RNG-neutral by construction.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.modules._shared import get_attr_or_key
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import BundleContext, to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)

LOINC_MRS = "72136-5"
LOINC_EDSS = "77691-7"
LOINC_CDR = "72172-0"

_SCALE_SUFFIX = {
    "mrs": "mrs",
    "hy": "hy",
    "edss": "edss",
    "cdr": "cdr",
}

_DISPLAY_EN = {
    "mrs": "Modified Rankin Scale",
    "hy": "Hoehn and Yahr stage",
    "edss": "Expanded Disability Status Scale score",
    "cdr": "Clinical Dementia Rating Global score",
}

STAGE_SCALE_OBSERVATION_ID_PREFIX = "stage-"
STAGE_SCALE_OBSERVATION_KEY_SYSTEM = structural_key_system("stage-scale-observation-key")


def _resolve_scale_id(structural_key: str) -> str:
    return derive_opaque_id(STAGE_SCALE_OBSERVATION_ID_PREFIX, structural_key)


def _classify_stage(icd_code: str, stage: str) -> tuple[str, Any] | None:
    """Map ``(ICD code, stage string)`` to ``(scale_key, parsed_value)``.

    Returns ``None`` when the Condition is not one of the four tracked
    scales or the stage string is empty / unparseable. Stage strings
    are produced by ``patient.activator._generate_stage`` — any new
    stage label added there without a mapping here silently falls out
    of this emit, which is the conservative behavior (no fabrication).
    """
    if not stage:
        return None
    base = icd_code.split(".")[0]
    # mRS — I69.x stage string of the form "mRS <int>" (0-5).
    if base == "I69" and stage.startswith("mRS "):
        try:
            return "mrs", int(stage.split()[1])
        except (ValueError, IndexError):
            return None
    # Hoehn & Yahr — G20 stage of the form "H&Y <int>" (1-5).
    if base == "G20" and stage.startswith("H&Y "):
        return "hy", stage
    # Banded EDSS — G35 stage of the form "EDSS <lo>-<hi>".
    if base == "G35" and stage.startswith("EDSS "):
        return "edss", stage
    # Clinical Dementia Rating — F00 stage of the form "CDR <value>".
    if base == "F00" and stage.startswith("CDR "):
        try:
            return "cdr", float(stage.split()[1])
        except (ValueError, IndexError):
            return None
    return None


def _pick_anchor_encounter(encounters: list[dict], snapshot_date: str | None) -> dict | None:
    """Pick the encounter to anchor the Observation to.

    Preference order:
    1. The latest outpatient-followup encounter whose admission is at
       or before ``snapshot_date`` (chart-review semantics — the most
       recent clinic visit on which an annual scale might realistically
       be documented).
    2. The latest encounter of any type at or before ``snapshot_date``
       (fallback for patients with only inpatient / ED contact).
    3. The last encounter in the record (fallback for cohorts without
       a snapshot date pin).

    Returns ``None`` only when the record has no encounters at all —
    the caller then skips the emit (an orphan Observation with no
    anchor is less useful than silence).
    """
    if not encounters:
        return None
    cutoff = (snapshot_date or "9999-12-31")[:10]

    def admit_key(enc: dict) -> str:
        return str(get_attr_or_key(enc, "admission_datetime", "") or "")[:10]

    followups = [
        e
        for e in encounters
        if str(get_attr_or_key(e, "encounter_type", "") or "").lower()
        in ("outpatient", "followup", "outpatient-followup")
        and admit_key(e) <= cutoff
    ]
    if followups:
        return max(followups, key=admit_key)
    pre_cutoff = [e for e in encounters if admit_key(e) <= cutoff]
    if pre_cutoff:
        return max(pre_cutoff, key=admit_key)
    return encounters[-1]


def _build_one_observation(
    scale_key: str,
    value: Any,
    patient_id: str,
    encounter_id: str,
    effective_dt: str,
) -> dict[str, Any]:
    """Assemble one FHIR stage-scale Observation."""
    suffix = _SCALE_SUFFIX[scale_key]
    structural_key = f"{patient_id}-{suffix}"
    display = _DISPLAY_EN[scale_key]
    code_block: dict[str, Any] = {"text": display}
    if scale_key == "mrs":
        code_block["coding"] = [{"system": get_system_uri("loinc"), "code": LOINC_MRS, "display": display}]
    elif scale_key == "edss":
        code_block["coding"] = [{"system": get_system_uri("loinc"), "code": LOINC_EDSS, "display": display}]
    elif scale_key == "cdr":
        code_block["coding"] = [{"system": get_system_uri("loinc"), "code": LOINC_CDR, "display": display}]
    # H&Y: display-only — no authoritative LOINC emitted (see module docstring).

    obs: dict[str, Any] = {
        "resourceType": "Observation",
        "id": _resolve_scale_id(structural_key),
        "identifier": [wrap_as_identifier(structural_key, STAGE_SCALE_OBSERVATION_KEY_SYSTEM)],
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": get_system_uri("hl7-observation-category"),
                        "code": "survey",
                        "display": "Survey",
                    }
                ],
                "text": "Survey",
            }
        ],
        "code": code_block,
        "subject": patient_ref(patient_id),
    }
    if scale_key == "mrs":
        obs["valueInteger"] = int(value)
    elif scale_key == "cdr":
        obs["valueDecimal"] = float(value)
    else:
        obs["valueString"] = str(value)
    if effective_dt:
        obs["effectiveDateTime"] = effective_dt
    if encounter_id:
        obs["encounter"] = encounter_ref(encounter_id)
    return obs


def build_stage_scale_observations(
    patient_data: dict,
    encounters: list[dict],
    snapshot_date: str | None,
) -> list[dict[str, Any]]:
    """Return the list of stage-scale Observations for one patient.

    One Observation per tracked scale (mRS / H&Y / EDSS / CDR) when
    the patient carries a correspondingly-staged chronic condition.
    An empty list for patients with none of the four conditions.

    Dedup: if a patient somehow carries two Conditions mapping to the
    same scale (e.g. both I69.1 and I69.3, both with populated mRS),
    the first wins — a single mRS score at snapshot time matches
    chart-review reality better than two conflicting entries.
    """
    patient_id = str(patient_data.get("patient_id", "") or "")
    if not patient_id:
        return []
    chronics = patient_data.get("chronic_conditions") or []
    if not chronics:
        return []

    anchor_enc = _pick_anchor_encounter(encounters, snapshot_date)
    encounter_id = str(get_attr_or_key(anchor_enc, "encounter_id", "") or "") if anchor_enc else ""
    enc_admit = str(get_attr_or_key(anchor_enc, "admission_datetime", "") or "") if anchor_enc else ""
    effective_dt = to_fhir_datetime(enc_admit) if enc_admit else ""

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for cond in chronics:
        code = str(get_attr_or_key(cond, "code", "") or "")
        stage = str(get_attr_or_key(cond, "stage", "") or "")
        classified = _classify_stage(code, stage)
        if classified is None:
            continue
        scale_key, value = classified
        if scale_key in seen:
            continue
        seen.add(scale_key)
        out.append(_build_one_observation(scale_key, value, patient_id, encounter_id, effective_dt))
    return out


def _bb_stage_scale_observations(ctx: BundleContext) -> list[dict]:
    """Bundle builder: emit one Observation per (patient, scale) for
    the four tracked chronic-disease rating scales.

    Registered in ``_BUNDLE_BUILDERS`` after ``_bb_anthropometrics``.
    """
    patient_data = ctx.patient_data or {}
    encounters = ctx.record.get("encounters", []) or []
    return build_stage_scale_observations(patient_data, encounters, ctx.snapshot_date)
