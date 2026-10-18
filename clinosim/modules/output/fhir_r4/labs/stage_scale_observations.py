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

from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _ScaleSpec:
    """Single source of truth for one rating scale's FHIR emit shape.

    ``icd_base`` is matched against ``code.split('.')[0]``. ``prefix`` is
    the stage-string tag written by ``patient.activator._generate_stage``.
    ``loinc`` is ``None`` for scales with no authoritative LOINC in
    common clinical use (H&Y); the Observation then emits display-only.
    ``value_key`` is the FHIR value[x] slot name (``valueInteger`` /
    ``valueDecimal`` / ``valueString``); ``value_parser`` converts the
    raw stage string to that slot's value, returning ``None`` on parse
    failure (unparseable stages fall out of the emit — no fabrication).
    """

    icd_base: str
    prefix: str
    suffix: str
    loinc: str | None
    display: str
    value_key: str
    value_parser: Callable[[str], Any]


def _parse_mrs(stage: str) -> int | None:
    try:
        return int(stage.split()[1])
    except (ValueError, IndexError):
        return None


def _parse_cdr(stage: str) -> float | None:
    try:
        return float(stage.split()[1])
    except (ValueError, IndexError):
        return None


def _parse_identity(stage: str) -> str:
    """EDSS / H&Y are banded labels — emit the stage string verbatim."""
    return stage


# (icd_base, scale_key) → spec. One row per emitted scale.
_SCALE_SPECS: dict[str, _ScaleSpec] = {
    "mrs": _ScaleSpec(
        icd_base="I69",
        prefix="mRS ",
        suffix="mrs",
        loinc="72136-5",
        display="Modified Rankin Scale",
        value_key="valueInteger",
        value_parser=_parse_mrs,
    ),
    "hy": _ScaleSpec(
        icd_base="G20",
        prefix="H&Y ",
        suffix="hy",
        loinc=None,  # No authoritative LOINC — display-only (see module docstring).
        display="Hoehn and Yahr stage",
        value_key="valueString",
        value_parser=_parse_identity,
    ),
    "edss": _ScaleSpec(
        icd_base="G35",
        prefix="EDSS ",
        suffix="edss",
        loinc="77691-7",
        display="Expanded Disability Status Scale score",
        value_key="valueString",
        value_parser=_parse_identity,
    ),
    "cdr": _ScaleSpec(
        icd_base="F00",
        prefix="CDR ",
        suffix="cdr",
        loinc="72172-0",
        display="Clinical Dementia Rating Global score",
        value_key="valueDecimal",
        value_parser=_parse_cdr,
    ),
}

# Reverse index: (icd_base, stage_prefix) → spec. The prefix guard lets a
# future stage system reusing the same ICD base route to a different
# spec; the parser is still what rejects unparseable stage strings.
_SPEC_BY_ICD: dict[str, _ScaleSpec] = {s.icd_base: s for s in _SCALE_SPECS.values()}


# Public LOINC aliases (consumed by tests + external callers).
LOINC_MRS = _SCALE_SPECS["mrs"].loinc
LOINC_EDSS = _SCALE_SPECS["edss"].loinc
LOINC_CDR = _SCALE_SPECS["cdr"].loinc

STAGE_SCALE_OBSERVATION_ID_PREFIX = "stage-"
STAGE_SCALE_OBSERVATION_KEY_SYSTEM = structural_key_system("stage-scale-observation-key")

# Chart-review anchor: production CIF uses ``encounter_type ∈
# {"outpatient", "inpatient", "emergency"}``. Outpatient is the only
# realistic venue for an annual rating-scale assessment; the fallback
# chain in ``_pick_anchor_encounter`` handles patients without one.
_FOLLOWUP_ENCOUNTER_TYPES: frozenset[str] = frozenset({"outpatient"})


def _resolve_scale_id(structural_key: str) -> str:
    return derive_opaque_id(STAGE_SCALE_OBSERVATION_ID_PREFIX, structural_key)


def _classify_stage(icd_code: str, stage: str) -> tuple[_ScaleSpec, Any] | None:
    """Map ``(ICD code, stage string)`` to ``(spec, parsed_value)``.

    Returns ``None`` when the ICD base is not one of the four tracked
    scales, the stage is empty, the prefix doesn't match the spec (a
    future stage system on the same ICD without this mapping), or the
    parser rejects the value. Any of these drops the Condition from the
    emit — the conservative behavior (no fabrication).
    """
    if not stage:
        return None
    spec = _SPEC_BY_ICD.get(icd_code.split(".")[0])
    if spec is None or not stage.startswith(spec.prefix):
        return None
    parsed = spec.value_parser(stage)
    if parsed is None:
        return None
    return spec, parsed


def _pick_anchor_encounter(encounters: list[dict], snapshot_date: str | None) -> dict | None:
    """Pick the encounter to anchor the Observation to.

    Preference order:
    1. The latest outpatient encounter at or before ``snapshot_date``
       (chart-review semantics — the most recent clinic visit on which
       an annual rating scale might realistically be documented).
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

    def enc_type(enc: dict) -> str:
        return str(get_attr_or_key(enc, "encounter_type", "") or "").lower()

    best_followup: dict | None = None
    best_followup_key = ""
    best_any: dict | None = None
    best_any_key = ""
    for enc in encounters:
        key = admit_key(enc)
        if key > cutoff:
            continue
        if key > best_any_key:
            best_any_key = key
            best_any = enc
        if enc_type(enc) in _FOLLOWUP_ENCOUNTER_TYPES and key > best_followup_key:
            best_followup_key = key
            best_followup = enc
    if best_followup is not None:
        return best_followup
    if best_any is not None:
        return best_any
    return encounters[-1]


def _build_one_observation(
    spec: _ScaleSpec,
    value: Any,
    patient_id: str,
    encounter_id: str,
    effective_dt: str,
) -> dict[str, Any]:
    """Assemble one FHIR stage-scale Observation."""
    structural_key = f"{patient_id}-{spec.suffix}"
    code_block: dict[str, Any] = {"text": spec.display}
    if spec.loinc is not None:
        code_block["coding"] = [{"system": get_system_uri("loinc"), "code": spec.loinc, "display": spec.display}]

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
        spec.value_key: value,
    }
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
        classified = _classify_stage(
            str(get_attr_or_key(cond, "code", "") or ""),
            str(get_attr_or_key(cond, "stage", "") or ""),
        )
        if classified is None:
            continue
        spec, value = classified
        if spec.suffix in seen:
            continue
        seen.add(spec.suffix)
        out.append(_build_one_observation(spec, value, patient_id, encounter_id, effective_dt))
    return out


def _bb_stage_scale_observations(ctx: BundleContext) -> list[dict]:
    """Bundle builder: emit one Observation per (patient, scale) for
    the four tracked chronic-disease rating scales.

    Registered in ``_BUNDLE_BUILDERS`` after ``_bb_anthropometrics``.
    """
    patient_data = ctx.patient_data or {}
    encounters = ctx.record.get("encounters", []) or []
    return build_stage_scale_observations(patient_data, encounters, ctx.snapshot_date)
