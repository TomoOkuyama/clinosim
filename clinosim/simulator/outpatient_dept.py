"""Outpatient follow-up department resolver.

Decides which hospital department an outpatient follow-up encounter
belongs to (department_id + rounds-attending assignment).

Layering
--------
Two decisions compose:

1. **specialty**: derived here from ``visit_type`` + a disease or
   screening code — the clinical specialty that would normally see this
   kind of visit (e.g. cardiology for chronic IHD, gastroenterology for
   colonoscopy screening, pediatrics for well-child).
2. **available department**: the specialty is then handed to
   :func:`clinosim.simulator.hospital_ops.resolve_department`, which
   consults ``hospital_operations.yaml`` — ``available_departments``
   (physical presence) and ``department_rollup`` (granular → available
   mapping) — to pick the actual department the encounter attaches to.

Post-discharge follow-ups short-circuit both stages: they inherit the
prior inpatient department directly (already a resolved available
department).

Placement
---------
The disease/screening → specialty mapping lives here rather than in
``hospital_ops.py`` because it is outpatient-visit-shaped domain logic
(chronic + screening + pediatric). ``hospital_ops.py`` stays scope-
limited to the pure infrastructure layer (specialty → available).
"""

from __future__ import annotations

from clinosim.simulator.hospital_ops import resolve_department

# Chronic-disease → clinical specialty (Japanese primary-care realism).
# Everything not listed defaults to internal_medicine — matches how
# 内科 handles the bulk of chronic follow-up (I10 HTN, E11 DM, E78
# dyslipidemia, E03 hypothyroid, N18 CKD via nephrology-rollup, J44
# COPD via pulmonology-rollup, F00 dementia, G20 PD, etc.).
_CHRONIC_DISEASE_SPECIALTY: dict[str, str] = {
    # Cardiology chronic
    "I25": "cardiology",  # chronic IHD
    "I50": "cardiology",  # heart failure
    "I48": "cardiology",  # atrial fibrillation
    "I20": "cardiology",  # angina pectoris
    "I21": "cardiology",  # MI (post-MI followup)
    "I26": "cardiology",  # PE (post-embolic followup)
    # Gastroenterology chronic
    "K21": "gastroenterology",  # GERD
    "K25": "gastroenterology",  # peptic ulcer
    "K57": "gastroenterology",  # diverticular disease
    "K74": "gastroenterology",  # cirrhosis
    "K80": "gastroenterology",  # cholelithiasis
    "K92": "gastroenterology",  # GI bleed followup
    "K56": "gastroenterology",  # ileus followup
    # Orthopedics chronic
    "M17": "orthopedics",  # knee OA
    "M54": "orthopedics",  # lumbago
    "M81": "orthopedics",  # osteoporosis
    # Preventive Z codes → primary care (health check / immunization /
    # screening — appear as chronic_followup at CIF level because the
    # calendar dispatcher tags them via chronic_code, but they are OPD
    # primary-care visits clinically).
    "Z00": "primary_care",
    "Z01": "primary_care",
    "Z09": "primary_care",
    "Z12": "primary_care",
    "Z13": "primary_care",
    "Z23": "primary_care",
}

# Screening event_type → clinical specialty.
_SCREENING_SPECIALTY: dict[str, str] = {
    "annual_health_screening": "primary_care",
    "colonoscopy_screening": "gastroenterology",
    "mammography_screening": "obgyn",
}


def _specialty_for_visit(visit_type: str, code: str) -> str:
    """Return the clinical specialty that would normally handle this visit."""
    if visit_type == "pediatric_visit":
        return "pediatrics"
    if visit_type == "health_screening":
        return _SCREENING_SPECIALTY.get(code, "primary_care")
    if visit_type in ("chronic_followup", "chronic"):
        if not code:
            return "internal_medicine"
        direct = _CHRONIC_DISEASE_SPECIALTY.get(code)
        if direct:
            return direct
        key = code.split(".")[0]
        return _CHRONIC_DISEASE_SPECIALTY.get(key, "internal_medicine")
    return "internal_medicine"


def resolve_outpatient_department(
    visit_type: str,
    code: str,
    prior_department_id: str | None,
    hospital_ops: dict | None,
) -> str:
    """Resolve the department_id an outpatient follow-up encounter attaches to.

    Parameters
    ----------
    visit_type
        ``"post_discharge"`` | ``"chronic_followup"`` | ``"pediatric_visit"``
        | ``"health_screening"``. Anything else falls through to internal
        medicine after rollup.
    code
        Disease id (chronic / post-discharge) or screening-type key
        (health_screening). Ignored for post-discharge.
    prior_department_id
        The inpatient department for a post-discharge follow-up.
        Required for ``visit_type == "post_discharge"`` to preserve the
        continuity-of-care invariant (trauma/surgery patients follow up
        in the surgical service, not general internal medicine).
    hospital_ops
        Parsed ``hospital_operations.yaml`` — provides
        ``available_departments`` and ``department_rollup``.
    """
    if visit_type == "post_discharge" and prior_department_id:
        return resolve_department(prior_department_id, hospital_ops)

    specialty = _specialty_for_visit(visit_type, code)
    return resolve_department(specialty, hospital_ops)
