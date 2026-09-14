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

    # Issue #1404: neonatal admission narrative framing. When the record
    # is a birth admission the newborn enricher stamps
    # ``record.extensions["newborn"]`` with Apgar / bilirubin / CCHD /
    # metabolic-screen payloads, and drops Vitamin K + ophthalmic
    # prophylaxis MARs plus AABR / metabolic-screen Procedures onto the
    # top-level lists. Project the shape narrative renderers need
    # (Apgar 1/5 min tuple, bilirubin peak, CCHD reading, workup flags)
    # up front so ``_build_extra_context`` can render the neonatal
    # summary without re-walking the raw extension dict.
    newborn_workup = _build_newborn_workup(record, patient)

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
        # Issue #1404 — neonatal admission workup projection (Apgar,
        # bilirubin trend, CCHD SpO2, hearing/metabolic screen flags,
        # Vitamin K / ophthalmic prophylaxis MAR flags). Empty for
        # non-newborn records.
        newborn_workup=newborn_workup,
    )


def _build_newborn_workup(record: Any, patient: Any) -> dict[str, Any]:
    """Issue #1404: project ``record.extensions["newborn"]`` and top-level
    lists into a narrative-consumable shape. Returns an empty dict when
    the record is not a birth admission — the ``_build_extra_context``
    renderer keys on this to decide whether to emit the neonatal
    summary line.

    Neonatal gate: patient must be `occupation == "infant"` or
    `age == 0`. Non-newborn records return `{}`.

    Payload shape:
      {
        "is_neonate":      bool,
        "apgar_1min":      int | None,
        "apgar_5min":      int | None,
        "bilirubin_peak":  float | None,   # mg/dL peak from bilirubin list
        "cchd_ru_spo2":    int | None,     # right-upper SpO2
        "cchd_le_spo2":    int | None,     # lower-extremity SpO2
        "has_aabr":        bool,           # AABR hearing screen Procedure present
        "has_metabolic":   bool,           # tandem-MS metabolic screen Procedure present
        "has_vitamin_k":   bool,           # Vitamin K MAR present
        "has_ophthalmic":  bool,           # ophthalmic prophylaxis MAR present
      }
    """
    if patient is None:
        return {}
    _age = _o(patient, "age", None)
    _occ = str(_o(patient, "occupation", "") or "").strip().lower()
    is_neonate = (isinstance(_age, int) and _age == 0) or _occ == "infant"
    if not is_neonate:
        return {}

    extensions = _o(record, "extensions", None) or {}
    newborn_ext = extensions.get("newborn") if isinstance(extensions, dict) else None
    newborn_ext = newborn_ext or {}

    # Apgar tuple.
    apgar_by_min: dict[int, int] = {}
    for entry in newborn_ext.get("apgar") or []:
        minute = _o(entry, "minute", None)
        score = _o(entry, "score", None)
        if isinstance(minute, int) and isinstance(score, int):
            apgar_by_min[minute] = score

    # Bilirubin peak (highest value in mg/dL). Entries carry {timestamp, total_bilirubin_mg_dl}.
    bili_values: list[float] = []
    for entry in newborn_ext.get("bilirubin") or []:
        val = _o(entry, "total_bilirubin_mg_dl", None)
        if val is None:
            val = _o(entry, "value", None)
        if val is not None:
            try:
                bili_values.append(float(val))
            except (TypeError, ValueError):
                pass
    bilirubin_peak = max(bili_values) if bili_values else None

    # CCHD SpO2 — walk entries for the right-upper (`RU` / `right_upper`)
    # and lower-extremity (`LE` / `foot`) readings.
    cchd_ru: int | None = None
    cchd_le: int | None = None
    for entry in newborn_ext.get("cchd_pulse_ox") or []:
        site = str(_o(entry, "site", "") or "").lower()
        spo2 = _o(entry, "spo2_percent", None) or _o(entry, "value", None)
        if spo2 is None:
            continue
        try:
            spo2_int = int(spo2)
        except (TypeError, ValueError):
            continue
        if site in ("ru", "right_upper", "right upper", "pre_ductal", "pre-ductal"):
            cchd_ru = spo2_int
        elif site in ("le", "lower_extremity", "foot", "post_ductal", "post-ductal"):
            cchd_le = spo2_int

    # Presence flags for Procedures + MARs on the top-level lists.
    procedures = _o(record, "procedures", None) or []
    has_aabr = False
    has_metabolic = False
    for proc in procedures:
        name = str(_o(proc, "display_name", "") or _o(proc, "name", "") or "").lower()
        if "aabr" in name or "hearing screen" in name:
            has_aabr = True
        if "tandem" in name or "metabolic screen" in name or "代謝異常" in name:
            has_metabolic = True

    mars = _o(record, "medication_administrations", None) or []
    has_vitamin_k = False
    has_ophthalmic = False
    for mar in mars:
        display = str(_o(mar, "medication_display_name", "") or _o(mar, "display_name", "") or "").lower()
        if "vitamin k" in display or "phytonadione" in display or "フィトナジオン" in display:
            has_vitamin_k = True
        if "erythromycin" in display or "エリスロマイシン" in display:
            # Ophthalmic prophylaxis in US neonates is erythromycin
            # 0.5% ophthalmic ointment. Explicit OPH route also flags.
            route = str(_o(mar, "route", "") or "").lower()
            if route in ("oph", "ophthalmic", "eye") or "eye" in display:
                has_ophthalmic = True
        if "silver nitrate" in display or "povidone" in display:
            has_ophthalmic = True

    return {
        "is_neonate": True,
        "apgar_1min": apgar_by_min.get(1),
        "apgar_5min": apgar_by_min.get(5),
        "bilirubin_peak": bilirubin_peak,
        "cchd_ru_spo2": cchd_ru,
        "cchd_le_spo2": cchd_le,
        "has_aabr": has_aabr,
        "has_metabolic": has_metabolic,
        "has_vitamin_k": has_vitamin_k,
        "has_ophthalmic": has_ophthalmic,
    }


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
                # Issue #1403: event_type distinguishes silent-drop paths
                # (avoid / hold / substitute / deescalate) for narrative
                # Rule 2 cadence dispatch. Default "avoid" preserves the
                # legacy pair-conflict interpretation for older logs.
                "event_type": getattr(entry, "event_type", "avoid"),
                "stopped_on_day": getattr(entry, "stopped_on_day", None),
            }
        )
    return out
