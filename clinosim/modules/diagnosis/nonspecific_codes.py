"""Named constants for non-specific / fallback ICD-10 codes used across the simulator.

Previously scattered as bare string literals in `inpatient.py` / `outpatient.py` /
`emergency.py` / `diagnosis/engine.py`. Two problems that caused:

* `inpatient.py:418` used ``"R05"`` (a real code for Cough) as a
  ``diagnosis_correct`` sentinel — legitimate cough presentations were silently
  marked incorrect. The engine's actual unresolved-diagnosis sentinel is
  ``"R69"``, so the two disagreed and neither location was named.
* Bare literals meant a rename or clinical review had to grep across modules.

Names below quote the ICD-10 title verbatim so a rename triggers an
ImportError rather than silent drift.

Issue #551 lands the first two constants (``UNRESOLVED_DIAGNOSIS_ICD`` and
``ICD_COUGH`` — the code that used to double as the wrong-dx sentinel). The
remaining fallback codes (``R50.9`` / ``R53.1`` / ``R68.8`` / ``Z09``) are
tracked in the follow-up issue that will extract them in one sweep.
"""

from __future__ import annotations

# The engine's "differential did not converge" fallback. Returned by
# `clinosim.modules.diagnosis.engine._pick_discharge_dx` when no working
# diagnosis and no candidate can be resolved. When a downstream builder sees
# this value as the discharge code, the diagnosis was NOT correctly identified.
UNRESOLVED_DIAGNOSIS_ICD = "R69"

# ICD-10 R05 = "Cough" — a real clinical code. Historically also (mis)used
# in `inpatient.py` as a wrong-dx sentinel; that usage is removed as of
# Issue #551. Exported here so any future dedup / display work can reference
# the same string without re-introducing a literal.
ICD_COUGH = "R05"


# ============================================================
# Issue #916: ICD-10 Z-chapter visit-reason codes.
# ============================================================
#
# The ICD-10 Z-chapter ("Factors influencing health status and contact with
# health services") is not a chapter of clinical diagnoses. Its members
# describe **reasons for encountering the health system** — routine checkups,
# immunization visits, aftercare follow-up, screening exams. Emitting them
# as ``Condition`` resources contradicts both the ICD-10 semantics of the
# chapter and the FHIR spec's own guidance that ``Condition`` represents
# a clinical condition / problem / diagnosis / health matter.
#
# Audit signature (v0.5.0 ``de261adf``): **43.3 % (14,384 / 33,188) of the
# generated Condition resources are Z-chapter codes**, every one of them
# emitted as ``clinicalStatus=resolved`` with ``abatementDateTime`` on the
# same day as ``onsetDateTime`` — the "same-day pseudo-diagnosis" tell.
#
# These codes live in FHIR as:
# - ``Z09`` follow-up            → ``Encounter.reasonCode``
# - ``Z00.0`` general medical    → ``Encounter.reasonCode``
# - ``Z23`` immunization         → ``Immunization`` resource (self-describing)
# - ``Z12.x`` / ``Z13.x`` screen → ``Encounter.reasonCode`` /
#                                  ``ServiceRequest.reasonCode``
#
# Personal-history / family-history / device-presence Z-codes (``Z80``-
# ``Z99``) are **clinical facts** and remain valid Conditions — they are
# not on the visit-reason list.
_VISIT_REASON_ZCODE_BASES: frozenset[str] = frozenset(
    {
        "Z00",  # General examination
        "Z01",  # Special examination
        "Z02",  # Administrative examination
        "Z09",  # Follow-up after treatment
        "Z11",  # Special screening — infectious
        "Z12",  # Special screening — neoplasms
        "Z13",  # Special screening — other
        "Z23",  # Immunization
        "Z25",  # Immunization (viral, single)
        "Z26",  # Immunization (other infectious)
        "Z27",  # Immunization (combinations)
        "Z28",  # Immunization not carried out
        "Z29",  # Prophylactic measures
        "Z71",  # Counseling
        "Z76",  # Other reason for encounter
    }
)


def is_visit_reason_zcode(code: str) -> bool:
    """Return True when ``code`` is a Z-chapter visit-reason code (Issue #916).

    Matches the ICD-10 base (before ``.``) against
    ``_VISIT_REASON_ZCODE_BASES``. Z-codes representing personal / family
    history or presence-of-device (``Z80``-``Z99``) are **not** visit-reason
    codes — they describe clinical facts and remain valid Conditions.

    Empty / non-Z codes return False.
    """
    if not code:
        return False
    base = code.split(".", 1)[0]
    return base in _VISIT_REASON_ZCODE_BASES


def encounter_primary_dx_code(record: dict | None, encounter_id: str) -> str:
    """Resolve the primary dx code for an encounter, encounter-scoped first.

    Issue #1215 introduced ``Encounter.admission_diagnosis_code`` /
    ``admission_diagnosis_system`` so a companion encounter appended by an
    enricher (e.g. ``ENC-VAX-*`` vaccination visit — Issue #1197 Pass 5
    fix) can carry its own visit-reason code (Z23) instead of inheriting
    the record's primary IMP admission dx. FHIR emit-path gates that
    switch on the encounter's dx (e.g. ``is_visit_reason_zcode`` for the
    Procedure.reasonReference gate — Issue #1222) must prefer that per-
    encounter code when it's populated; otherwise the gate looks at the
    wrong dx and fails to fire.

    Resolution order:
      1. ``encounter.admission_diagnosis_code`` (per-encounter override,
         Issue #1215)
      2. ``record.clinical_diagnosis.discharge_diagnosis_code``
      3. ``record.clinical_diagnosis.admission_diagnosis_code``
      4. ``""`` (unknown)

    Empty ``record`` or ``encounter_id`` short-circuits to ``""``.
    """
    if not record or not encounter_id:
        return ""
    for enc in record.get("encounters") or []:
        if not isinstance(enc, dict):
            continue
        if enc.get("encounter_id") == encounter_id:
            enc_code = enc.get("admission_diagnosis_code") or ""
            if enc_code:
                return str(enc_code)
            break
    dx = record.get("clinical_diagnosis") or {}
    return str(dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code", "") or "")
