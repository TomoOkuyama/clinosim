"""FHIR R4 rehabilitation-session builder — one Procedure per ``RehabSession``.

Each CIF ``RehabSession`` (a post-surgical PT session, Issue #3319) is emitted
as a ``Procedure``:

- ``code`` = the discipline's SNOMED CT session procedure (``Physical therapy
  procedure`` 91251008 for PT; the table lives in
  ``codes/data/clinosim-clinician-role.yaml`` ``rehab_session_snomed``).
- ``performedPeriod`` = ``session_date`` to ``session_date + duration_minutes``.
- ``performer`` = the roster therapist (``therapist_id``) with the therapist's
  SNOMED occupation as ``performer.function`` (Physiotherapist / Occupational
  therapist / Speech and language therapist); omitted when no therapist is
  recorded — no fabrication.
- ``status`` = ``not-done`` with a ``statusReason`` when the patient refused
  the session, otherwise ``completed``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from clinosim.countries import lang_for
from clinosim.locale.i18n import t
from clinosim.locale.loader import load_clinician_roles, rehab_discipline_role, rehab_session_snomed
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.output.fhir_r4.conditions.primary_ref import primary_condition_ref
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import dual_slot_concept
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.fhir_time import to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.ids import wrap_as_identifier
from clinosim.modules.output.fhir_r4.lib.profile_meta import profile_meta
from clinosim.modules.output.fhir_r4.procedures.procedures import (
    PROCEDURE_KEY_SYSTEM,
    _resolve_procedure_id,
)

# SNOMED CT "Therapeutic procedure" — the category of the other session-style
# Procedures (oxygen therapy, order-derived procedures).
_SNOMED_THERAPEUTIC_PROCEDURE = "277132007"


def _session_start(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def _bb_rehab_sessions(ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit one Procedure per rehabilitation session of the record."""
    sessions = ctx.record.get("rehab_sessions", []) or []
    if not sessions:
        return []
    lang = lang_for(ctx.country)
    roles = load_clinician_roles()
    out: list[dict[str, Any]] = []
    for sess in sessions:
        start = _session_start(_o(sess, "session_date", None))
        session_id = str(_o(sess, "session_id", "") or "")
        therapy_type = str(_o(sess, "therapy_type", "") or "")
        code = rehab_session_snomed(therapy_type)
        if start is None or not session_id or not code:
            continue
        end = start + timedelta(minutes=int(_o(sess, "duration_minutes", 0) or 0))
        enc_id = str(_o(sess, "encounter_id", "") or "")
        therapist_id = str(_o(sess, "therapist_id", "") or "")
        declined = _o(sess, "patient_participation", "") == "refused"

        structural_key = f"proc-rehab-{session_id}"
        procedure: dict[str, Any] = {
            "resourceType": "Procedure",
            "id": _resolve_procedure_id(structural_key),
            "identifier": [wrap_as_identifier(structural_key, PROCEDURE_KEY_SYSTEM)],
            **profile_meta("Procedure", ctx.country),
            "status": "not-done" if declined else "completed",
            "category": dual_slot_concept("snomed-ct", _SNOMED_THERAPEUTIC_PROCEDURE, lang),
            "code": dual_slot_concept("snomed-ct", code, lang),
            "subject": patient_ref(_o(sess, "patient_id", "") or ctx.patient_id),
            "performedPeriod": {"start": to_fhir_datetime(start), "end": to_fhir_datetime(end)},
        }
        if declined:
            procedure["statusReason"] = {"text": t("fhir_emit_text.rehab_session_declined", lang)}
        if enc_id:
            procedure["encounter"] = encounter_ref(enc_id)
            procedure["reasonReference"] = [
                {"reference": f"Condition/{primary_condition_ref(ctx.record, ctx.patient_id, enc_id)}"}
            ]
        if therapist_id:
            function_code = str((roles.get(rehab_discipline_role(therapy_type)) or {}).get("occupation_snomed") or "")
            performer: dict[str, Any] = {"actor": {"reference": f"Practitioner/{therapist_id}"}}
            if function_code:
                performer["function"] = dual_slot_concept("snomed-ct", function_code, lang)
            procedure["performer"] = [performer]
        out.append(procedure)
    return out
