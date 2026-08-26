"""Resolve the Condition.id representing an encounter's primary reason.

Single source of truth so every downstream emitter (Encounter.reasonReference,
Encounter.diagnosis[].condition, Procedure.reasonReference,
MedicationRequest.reasonReference, …) points at the SAME Condition.

## Rule

Given an encounter with a `clinical_diagnosis.discharge_diagnosis_code` (or
admission fallback), compare its 3-char ICD base against the patient's
`chronic_conditions[].code` bases:

- **Match** — encounter's primary is a documented chronic problem
  (HTN follow-up, DM control visit, HF exacerbation admission, …). Return
  the patient-scoped chronic Condition id (`cond-chronic-{patient}-{i:02d}`).
  The chronic Condition already models the ongoing disease; emitting a
  parallel `cond-{enc}-primary` would duplicate the row and can drift ICD
  granularity (I50 vs I50.9) across the two entries.
- **No match** — genuine acute problem (Z-code screening, new fracture,
  Ω infection). Return the encounter-scoped id (`cond-{enc}-primary`)
  that `_build_conditions` will emit as a fresh Condition.
- **No dx** — fall back to the encounter-scoped id; caller shape stays
  compatible with existing behaviour.

## FHIR alignment

Role of a Condition WITHIN an encounter (DD / CM / CC / AD) is expressed by
`Encounter.diagnosis[].use`, not by adding a second Condition.category coding.
So the chronic Condition keeps its `problem-list-item` category and takes on
the encounter-DD role purely through `Encounter.diagnosis[0].condition + use=DD`.
"""

from __future__ import annotations

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
)

# === Issue #854 Bucket B (PR-condition): opaque Condition.id ===
# Same pattern as PR #357 / #863 / #867 / #868 / #869 / #878 / #879 /
# #880 / #881 / #882. The Condition family has 2 structural-key shapes
# (both pre-#854 id bodies without the ``cond-`` prefix) — the resolver
# hashes whichever key the caller composes:
#   - encounter-primary: ``{encounter_id}-primary`` (or ``{patient_id}-primary``
#     when the encounter is missing an id — fallback used by outpatient /
#     partial-record paths).
#   - chronic: ``chronic-{patient_id}-{idx:02d}`` (patient-scoped so
#     duplicated per-encounter emits collapse via the write() dedup).
#
# PUBLIC constants so downstream readers (Encounter.diagnosis[] walkers,
# reasonReference readers across MR / Procedure / SR / DR, future audit
# tooling) can import them for identifier-based lookup without string-
# parsing the (now opaque) ``.id``.
CONDITION_ID_PREFIX = "cond-"
CONDITION_KEY_SYSTEM = structural_key_system("condition-key")


def _resolve_condition_id(structural_key: str) -> str:
    """Return the FHIR Condition.id for a Condition (Issue #854 Bucket B).

    Shape: ``cond-{sha256(structural_key)[:12]}`` = 17 chars, fixed. The
    ``cond-`` prefix retains the human-recognisable identity (URLs like
    ``/Condition/cond-<hex>`` read as a Condition at a glance) —
    consistent with the sibling resolvers introduced in
    PR #863 / #867 / #868 / #869 / #878 / #879 / #880 / #881 / #882.

    Structural keys (pre-#854 id body without ``cond-`` prefix):
    - encounter-primary: ``{encounter_id}-primary`` (or
      ``{patient_id}-primary`` when the encounter has no id).
    - chronic problem-list: ``chronic-{patient_id}-{idx:02d}``.

    Every cross-reference reader either funnels through
    :func:`primary_condition_ref` / :func:`primary_condition_ref_from_codes`
    (which apply this resolver internally) or, when it composes the
    structural key locally (chronic-list walker, composition builder),
    calls :func:`chronic_condition_id` / :func:`encounter_primary_condition_id`
    below — never string-parses the id.
    """
    return derive_opaque_id(CONDITION_ID_PREFIX, structural_key)


def encounter_primary_condition_key(patient_id: str, encounter_id: str) -> str:
    """Structural key for an encounter's primary-diagnosis Condition."""
    if encounter_id:
        return f"{encounter_id}-primary"
    return f"{patient_id}-primary"


def chronic_condition_key(patient_id: str, idx: int) -> str:
    """Structural key for the ``idx``-th chronic-condition list entry."""
    return f"chronic-{patient_id}-{idx:02d}"


def encounter_primary_condition_id(patient_id: str, encounter_id: str) -> str:
    """Return the opaque Condition.id for an encounter's primary diagnosis."""
    return _resolve_condition_id(encounter_primary_condition_key(patient_id, encounter_id))


def chronic_condition_id(patient_id: str, idx: int) -> str:
    """Return the opaque Condition.id for the ``idx``-th chronic condition."""
    return _resolve_condition_id(chronic_condition_key(patient_id, idx))


def _icd_base(code: str) -> str:
    """Return the 3-char ICD-10 base (before the dot)."""
    return code.split(".")[0] if code else ""


def _chronic_index_for_primary(record: dict, primary_base: str) -> int | None:
    """Return the 0-based index into `patient.chronic_conditions` whose code
    base matches `primary_base`. None if no match.

    Iterates in list order — first match wins. In practice a patient's
    chronic_conditions do not repeat the same base code, so at most one
    entry can match.
    """
    if not primary_base:
        return None
    chronics = (record.get("patient") or {}).get("chronic_conditions", []) or []
    for i, chronic in enumerate(chronics):
        if isinstance(chronic, str):
            c_code = chronic
        else:
            c_code = _o(chronic, "code", "") or ""
        if _icd_base(str(c_code)) == primary_base:
            return i
    return None


def primary_condition_ref(record: dict, patient_id: str, encounter_id: str) -> str:
    """Return the Condition.id that represents THIS encounter's primary reason.

    Chronic-primary encounters (dx base matches a chronic) resolve to the
    patient-scoped chronic Condition id. All other encounters resolve to
    the encounter-scoped `cond-{enc}-primary` id.

    The returned id is used verbatim in `Condition/<id>` references — the
    Condition itself is emitted (or not, when merging into a chronic)
    by `_build_conditions`.
    """
    dx = record.get("clinical_diagnosis", {}) or {}
    dx_code = dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code", "") or ""
    base = _icd_base(str(dx_code))
    idx = _chronic_index_for_primary(record, base)
    if idx is not None:
        return chronic_condition_id(patient_id, idx)
    return encounter_primary_condition_id(patient_id, encounter_id)


def primary_condition_ref_from_codes(
    primary_dx_code: str,
    chronic_condition_codes: list[str] | None,
    patient_id: str,
    encounter_id: str,
) -> str:
    """Variant of `primary_condition_ref` for callers that already have
    `primary_dx_code` + `chronic_condition_codes` extracted (encounter
    builder, encounter-scoped procedure/order builders).

    Same rule: match encounter dx base against chronic bases; on match
    return `cond-chronic-{patient}-{i:02d}` (i = index in the passed
    chronic list), else return `cond-{enc}-primary`.
    """
    base = _icd_base(str(primary_dx_code or ""))
    if base and chronic_condition_codes:
        for i, c_code in enumerate(chronic_condition_codes):
            if _icd_base(str(c_code or "")) == base:
                return chronic_condition_id(patient_id, i)
    return encounter_primary_condition_id(patient_id, encounter_id)


def is_chronic_primary(record: dict) -> bool:
    """Return True when this encounter's primary dx merges into a chronic
    Condition. Used by `_build_conditions` to decide whether to skip the
    encounter-primary Condition emission."""
    dx = record.get("clinical_diagnosis", {}) or {}
    dx_code = dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code", "") or ""
    base = _icd_base(str(dx_code))
    return _chronic_index_for_primary(record, base) is not None
