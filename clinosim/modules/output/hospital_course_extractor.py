"""Extract deterministic clinical facts from a structural CIF patient record.

These facts are passed as ``hospital_course_bullets`` to LLM prompt templates
so that the LLM only needs to prose them up — it does not invent events.

This preserves clinical fidelity: everything in the discharge summary's
hospital course section is traceable to a simulation event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from clinosim.codes import lookup as code_lookup

__all__ = [
    "HospitalCourseFact",
    "extract_hospital_course",
    "summarize_discharge_medications",
    "summarize_procedures",
    "summarize_admission_vitals",
]


@dataclass(frozen=True)
class HospitalCourseFact:
    """A single clinical event in the hospital course."""

    hospital_day: int
    event_type: str    # admission | surgery | procedure | complication |
                        # treatment_change | test_peak | transfer | discharge | death
    description: str


# ============================================================
# Public entry point
# ============================================================


def extract_hospital_course(
    record: dict[str, Any],
    language: str = "en",
) -> list[HospitalCourseFact]:
    """Extract a time-sorted list of events from a CIF patient record dict.

    Args:
        record: dict-form CIFPatientRecord (as written by cif_writer).
        language: "en" or "ja" — affects display text for codes only.

    Returns:
        List of HospitalCourseFact sorted by hospital_day ascending.
    """
    events: list[HospitalCourseFact] = []
    encounter = (record.get("encounters") or [{}])[0]
    admission_dt = _parse_dt(encounter.get("admission_datetime"))
    discharge_dt = _parse_dt(encounter.get("discharge_datetime"))

    # --- Admission ---
    events.append(_admission_event(record, encounter, admission_dt, language))

    # --- Surgeries ---
    events.extend(_surgery_events(record, admission_dt, language))

    # --- Invasive bedside procedures ---
    events.extend(_procedure_events(record, admission_dt, language))

    # --- Complications ---
    events.extend(_complication_events(record, language))

    # --- Lab / physiological peaks (CRP, WBC, Cr) ---
    events.extend(_lab_peak_events(record, admission_dt))

    # --- Discharge / death ---
    events.append(
        _discharge_event(record, encounter, admission_dt, discharge_dt, language)
    )

    # Deduplicate and sort
    events.sort(key=lambda e: (e.hospital_day, _event_order(e.event_type)))
    return events


# ============================================================
# Public helpers — used directly by document generators
# ============================================================


def summarize_discharge_medications(
    record: dict[str, Any], language: str = "en"
) -> list[str]:
    """Return a list of "<drug> <dose> <route> <frequency>" strings."""
    rx = record.get("discharge_prescription") or {}
    items = rx.get("items") or []
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("drug_name") or item.get("drug") or ""
        dose = item.get("dose", "")
        route = item.get("route", "")
        freq = item.get("frequency", "")
        duration = item.get("duration", "")
        parts = [p for p in (name, dose, route, freq, duration) if p]
        if parts:
            out.append(" ".join(str(p) for p in parts))
    return out


def summarize_procedures(
    record: dict[str, Any], language: str = "en"
) -> list[str]:
    """Return human-readable strings for all procedures in the encounter."""
    procs = record.get("procedures") or []
    out: list[str] = []
    for p in procs:
        if not isinstance(p, dict):
            continue
        name = p.get("procedure_name") or p.get("procedure_type", "procedure")
        start = _format_dt(p.get("start_datetime"))
        surgeon = p.get("primary_surgeon_id", "")
        complications = p.get("intraop_complications") or []
        comp_str = (
            f" (complications: {', '.join(complications)})" if complications else ""
        )
        if start:
            out.append(f"{name} on {start} by {surgeon}{comp_str}".strip())
        else:
            out.append(f"{name} by {surgeon}{comp_str}".strip())
    return out


def summarize_admission_vitals(record: dict[str, Any]) -> str:
    """Return the earliest set of vitals as a one-line summary."""
    vitals = record.get("vital_signs") or []
    if not vitals:
        return "(not recorded)"
    first = vitals[0]
    if not isinstance(first, dict):
        return "(not recorded)"
    bp_sys = first.get("systolic_bp") or first.get("bp_systolic")
    bp_dia = first.get("diastolic_bp") or first.get("bp_diastolic")
    hr = first.get("heart_rate")
    rr = first.get("respiratory_rate")
    temp = first.get("temperature")
    spo2 = first.get("spo2") or first.get("oxygen_saturation")
    parts = []
    if temp is not None:
        parts.append(f"T {temp}°C")
    if hr is not None:
        parts.append(f"HR {hr}")
    if rr is not None:
        parts.append(f"RR {rr}")
    if bp_sys is not None and bp_dia is not None:
        parts.append(f"BP {bp_sys}/{bp_dia}")
    if spo2 is not None:
        parts.append(f"SpO2 {spo2}%")
    return ", ".join(parts) if parts else "(not recorded)"


# ============================================================
# Private event builders
# ============================================================


def _admission_event(
    record: dict[str, Any],
    encounter: dict[str, Any],
    admission_dt: datetime | None,
    language: str,
) -> HospitalCourseFact:
    cd = record.get("clinical_diagnosis") or {}
    admit_dx_code = cd.get("admission_diagnosis_code") or ""
    admit_dx_system = cd.get("admission_diagnosis_system") or "icd-10-cm"
    admit_dx = code_lookup(admit_dx_system, admit_dx_code, language) if admit_dx_code else "undiagnosed"
    chief = encounter.get("chief_complaint") or "not recorded"
    description = (
        f"Day 0: Admitted with {chief}. "
        f"Initial working diagnosis: {admit_dx}."
    )
    return HospitalCourseFact(
        hospital_day=0, event_type="admission", description=description
    )


def _surgery_events(
    record: dict[str, Any],
    admission_dt: datetime | None,
    language: str,
) -> list[HospitalCourseFact]:
    events: list[HospitalCourseFact] = []
    for p in record.get("procedures") or []:
        if not isinstance(p, dict):
            continue
        if p.get("category_code") != "387713003":  # only surgical
            continue
        day = _day_offset(admission_dt, p.get("start_datetime"))
        name = p.get("procedure_name") or p.get("procedure_type", "surgery")
        comps = p.get("intraop_complications") or []
        comp_str = f" with {', '.join(comps)}" if comps else ""
        ebl = p.get("estimated_blood_loss_ml")
        ebl_str = f" EBL {ebl} mL." if ebl else ""
        events.append(
            HospitalCourseFact(
                hospital_day=day,
                event_type="surgery",
                description=f"Day {day}: {name}{comp_str}.{ebl_str}",
            )
        )
    return events


def _procedure_events(
    record: dict[str, Any],
    admission_dt: datetime | None,
    language: str,
) -> list[HospitalCourseFact]:
    """Only surface invasive bedside procedures that warrant a note."""
    invasive = {
        "central_line",
        "arterial_line",
        "lumbar_puncture",
        "thoracentesis",
        "paracentesis",
        "chest_tube",
        "intubation",
        "bronchoscopy",
        "cardioversion",
    }
    events: list[HospitalCourseFact] = []
    for p in record.get("procedures") or []:
        if not isinstance(p, dict):
            continue
        if p.get("category_code") == "387713003":
            continue  # surgical already handled
        ptype = p.get("procedure_type", "")
        if ptype not in invasive:
            continue
        day = _day_offset(admission_dt, p.get("start_datetime"))
        name = p.get("procedure_name") or ptype
        events.append(
            HospitalCourseFact(
                hospital_day=day,
                event_type="procedure",
                description=f"Day {day}: {name} performed at bedside.",
            )
        )
    return events


def _complication_events(
    record: dict[str, Any], language: str
) -> list[HospitalCourseFact]:
    """Complications occurred during the admission.

    ``complications_occurred`` is a list of simple labels like ``"pneumonia"``.
    We assign them to the mid-stay day for ordering; exact day is unknown.
    """
    complications = record.get("complications_occurred") or []
    if not complications:
        return []
    # Place complications at day 1 so they appear after admission but before peaks
    return [
        HospitalCourseFact(
            hospital_day=1,
            event_type="complication",
            description=f"Complication identified: {c}",
        )
        for c in complications
    ]


def _lab_peak_events(
    record: dict[str, Any],
    admission_dt: datetime | None,
) -> list[HospitalCourseFact]:
    """Surface peaks of CRP / WBC / Creatinine / Lactate as notable events."""
    orders = record.get("orders") or []
    peaks: dict[str, tuple[datetime | None, float]] = {}

    for o in orders:
        if not isinstance(o, dict):
            continue
        if o.get("order_type") != "lab":
            continue
        result = o.get("result") or {}
        if not result:
            continue
        lab_name = (result.get("lab_name") or o.get("display_name") or "").strip()
        if not lab_name:
            continue
        key = _normalize_lab_name(lab_name)
        if key not in {"CRP", "WBC", "Cr", "Lactate"}:
            continue
        try:
            value = float(result.get("value", 0))
        except (TypeError, ValueError):
            continue
        result_dt = _parse_dt(result.get("result_datetime"))
        if key not in peaks or value > peaks[key][1]:
            peaks[key] = (result_dt, value)

    events: list[HospitalCourseFact] = []
    for name, (dt, val) in peaks.items():
        day = _day_offset(admission_dt, dt) if dt else 1
        unit = _unit_for(name)
        events.append(
            HospitalCourseFact(
                hospital_day=day,
                event_type="test_peak",
                description=f"Day {day}: {name} peaked at {val:.1f} {unit}.",
            )
        )
    return events


def _discharge_event(
    record: dict[str, Any],
    encounter: dict[str, Any],
    admission_dt: datetime | None,
    discharge_dt: datetime | None,
    language: str,
) -> HospitalCourseFact:
    day = _day_offset(admission_dt, discharge_dt) if discharge_dt else -1
    cd = record.get("clinical_diagnosis") or {}
    dx_code = cd.get("discharge_diagnosis_code") or ""
    dx_system = cd.get("discharge_diagnosis_system") or "icd-10-cm"
    dx_name = code_lookup(dx_system, dx_code, language) if dx_code else "uncertain"
    disposition = encounter.get("discharge_disposition") or "home"

    if record.get("deceased"):
        return HospitalCourseFact(
            hospital_day=max(day, 0),
            event_type="death",
            description=(
                f"Day {max(day, 0)}: Patient died despite maximal therapy. "
                f"Final diagnosis: {dx_name}."
            ),
        )

    return HospitalCourseFact(
        hospital_day=max(day, 0),
        event_type="discharge",
        description=(
            f"Day {max(day, 0)}: Discharged to {disposition}. "
            f"Final diagnosis: {dx_name}."
        ),
    )


# ============================================================
# Utility functions
# ============================================================


_EVENT_ORDER = {
    "admission": 0,
    "surgery": 1,
    "procedure": 2,
    "complication": 3,
    "test_peak": 4,
    "treatment_change": 5,
    "transfer": 6,
    "discharge": 9,
    "death": 9,
}


def _event_order(event_type: str) -> int:
    return _EVENT_ORDER.get(event_type, 5)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _format_dt(value: Any) -> str:
    dt = _parse_dt(value)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def _day_offset(base: datetime | None, target: Any) -> int:
    """Return the hospital day (integer), 0 for same calendar day."""
    target_dt = _parse_dt(target)
    if base is None or target_dt is None:
        return 0
    delta = target_dt - base
    return max(0, delta.days)


_LAB_NAME_MAP = {
    "crp": "CRP",
    "c-reactive protein": "CRP",
    "wbc": "WBC",
    "white blood cell count": "WBC",
    "creatinine": "Cr",
    "cr": "Cr",
    "lactate": "Lactate",
}


def _normalize_lab_name(name: str) -> str:
    return _LAB_NAME_MAP.get(name.strip().lower(), name)


_UNIT_MAP = {"CRP": "mg/L", "WBC": "cells/μL", "Cr": "mg/dL", "Lactate": "mmol/L"}


def _unit_for(name: str) -> str:
    return _UNIT_MAP.get(name, "")
