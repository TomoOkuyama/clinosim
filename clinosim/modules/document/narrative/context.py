"""NarrativeContext factory (CIF → ctx)."""

from __future__ import annotations

from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import resolve_lang
from clinosim.types.document import DocumentType, NarrativeContext


def build_narrative_context(
    record: Any,
    encounter: Any,
    document_type: DocumentType,
    day_index: int,
    country: str,
    disease_protocol: Any | None = None,
    encounter_protocol: Any | None = None,
    clinical_course_archetype: str = "uncomplicated_improvement",
    severity: str = "moderate",
    los_days: int = 1,
    roster_map: dict[str, dict] | None = None,
) -> NarrativeContext:
    """CIF record + encounter → NarrativeContext.

    Downstream generators (template / LLM) read this ctx and nothing else.
    ``day_index`` conveys the stage within a daily generation cycle
    (progress note runs 0..LOS, H&P = 0, discharge = LOS-1).
    """
    lang = resolve_lang(country)
    locale = country.lower()
    patient = _o(record, "patient", None)
    allergies: list[Any] = _o(patient, "allergies", []) if patient is not None else []

    # Issue #1066 (drug_safety): filter PatientProfile.safety_skip_log to this encounter.
    safety_skips = _build_safety_skips(patient, encounter)

    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=_o(encounter, "encounter_type", None),
        disease_protocol=disease_protocol,
        encounter_protocol=encounter_protocol,
        clinical_course_archetype=clinical_course_archetype,
        severity=severity,
        day_index=day_index,
        los_days=los_days,
        vitals=_o(record, "vital_signs", []) or [],
        lab_results=_o(record, "lab_results", []) or [],
        medications=_o(record, "medication_administrations", []) or [],
        diagnoses=_o(record, "diagnoses", []) or [],
        procedures=_o(record, "procedures", []) or [],
        rehab_sessions=_o(record, "rehab_sessions", []) or [],
        allergies=allergies or [],
        document_type=document_type,
        target_lang=lang,
        locale=locale,
        complications_occurred=list(_o(record, "complications_occurred", []) or []),
        # Issue #848: intra-admission new-disease diagnoses from
        # ``engine._merge_disease_into_active_encounter``. Extracted from
        # ``record.clinical_diagnosis.working_diagnoses`` (populated only
        # for encounters that had an in-hospital complication event).
        working_diagnoses=list(_o(_o(record, "clinical_diagnosis", None), "working_diagnoses", []) or []),
        adl_assessments=list(_o(record, "adl_assessments", []) or []),
        nursing_risk_assessments=list(_o(record, "nursing_risk_assessments", []) or []),
        intake_output_records=list(_o(record, "intake_output_records", []) or []),
        # Issue #819 follow-up: staff-name resolution at template time.
        # `roster_map` is `{staff_id: staff_dict}` from hospital.json.
        # Empty when the caller has no roster (unit tests, offline
        # narrative regen without a hospital.json) — template renderers
        # fall back to raw ids in that case.
        roster_map=roster_map or {},
        # Issue #981 — surface encounter orders for ED workup rendering.
        # `record.orders` (per-encounter file) already scopes to one
        # encounter, so no additional filtering is needed here.
        orders=_o(record, "orders", []) or [],
        # Issue #982 — surface family_history for narrative rendering.
        family_history=_o(record, "family_history", []) or [],
        # Issue #1066 — encounter-filtered drug_safety avoidance log for narrative surface.
        safety_skips=safety_skips,
    )


def _build_safety_skips(patient: Any, encounter: Any) -> list[dict[str, Any]]:
    """Filter ``patient.safety_skip_log`` to entries whose encounter_id matches
    ``encounter.id`` and reshape into narrative-consumable dicts.
    Returns [] when patient is None, no log exists, or no entries match.
    """
    if patient is None:
        return []
    raw_log = _o(patient, "safety_skip_log", []) or []
    if not raw_log:
        return []
    encounter_id = _o(encounter, "id", None) if encounter is not None else None
    if encounter_id is None:
        return []
    out: list[dict[str, Any]] = []
    for entry in raw_log:
        if getattr(entry, "encounter_id", None) != encounter_id:
            continue
        verdict = getattr(entry, "verdict", None)
        out.append(
            {
                "considered": entry.candidate_drug,
                "considered_ja": entry.candidate_drug_ja,
                "avoided_due_to": entry.active_conflict,
                "avoided_due_to_ja": entry.active_conflict_ja,
                "rationale_en": getattr(verdict, "rationale_en", None),
                "rationale_ja": getattr(verdict, "rationale_ja", None),
                "substituted_with": entry.substituted_with,
                "substituted_with_ja": entry.substituted_with_ja,
                "context": entry.context_hint,
                "severity": getattr(verdict, "severity", None),
            }
        )
    return out
