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
        return f"cond-chronic-{patient_id}-{idx:02d}"
    if encounter_id:
        return f"cond-{encounter_id}-primary"
    return f"cond-{patient_id}-primary"


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
                return f"cond-chronic-{patient_id}-{i:02d}"
    if encounter_id:
        return f"cond-{encounter_id}-primary"
    return f"cond-{patient_id}-primary"


def is_chronic_primary(record: dict) -> bool:
    """Return True when this encounter's primary dx merges into a chronic
    Condition. Used by `_build_conditions` to decide whether to skip the
    encounter-primary Condition emission."""
    dx = record.get("clinical_diagnosis", {}) or {}
    dx_code = dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code", "") or ""
    base = _icd_base(str(dx_code))
    return _chronic_index_for_primary(record, base) is not None
