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
    "extract_clinical_guidance",
    "extract_lab_trends",
    "extract_treatment_timeline",
    "extract_vitals_snapshot",
    "summarize_discharge_medications",
    "summarize_procedures",
    "summarize_admission_vitals",
    "summarize_terminal_vitals",
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
    events.extend(_lab_peak_events(record, admission_dt, language))

    # --- Treatment changes (new drugs started after day 0, drug switches) ---
    events.extend(_treatment_change_events(record, admission_dt, language))

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


def _ja_localize_drug(name: str, language: str) -> str:
    """Localize a drug name for JP; no-op otherwise."""
    if language != "ja" or not name:
        return name
    from clinosim.modules.output.fhir_r4_adapter import _localize_drug_name
    return _localize_drug_name(name, "JP")


def _ja_localize_procedure(name: str, language: str) -> str:
    """Localize a procedure name for JP."""
    if language != "ja" or not name:
        return name
    from clinosim.modules.output.fhir_r4_adapter import _PROCEDURE_NAME_JA, _localize_drug_name
    ja = _PROCEDURE_NAME_JA.get(name)
    return ja if ja else _localize_drug_name(name, "JP")


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
        name = _ja_localize_drug(name, language)
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
    by_label = "担当" if language == "ja" else "by"
    on_label = "施行日" if language == "ja" else "on"
    comp_label = "合併症" if language == "ja" else "complications"
    for p in procs:
        if not isinstance(p, dict):
            continue
        name = p.get("procedure_name") or p.get("procedure_type", "procedure")
        name = _ja_localize_procedure(name, language)
        start = _format_dt(p.get("start_datetime"))
        surgeon = p.get("primary_surgeon_id", "")
        complications = p.get("intraop_complications") or []
        comp_str = (
            f" ({comp_label}: {', '.join(complications)})" if complications else ""
        )
        if start:
            out.append(f"{name} {on_label} {start} {by_label} {surgeon}{comp_str}".strip())
        else:
            out.append(f"{name} {by_label} {surgeon}{comp_str}".strip())
    return out


def summarize_admission_vitals(record: dict[str, Any]) -> str:
    """Return the earliest set of vitals as a one-line summary."""
    return _summarize_vitals_at(record, index=0)


def summarize_terminal_vitals(record: dict[str, Any]) -> str:
    """Return the last recorded set of vitals (for death notes)."""
    return _summarize_vitals_at(record, index=-1)


def _summarize_vitals_at(record: dict[str, Any], index: int) -> str:
    """Return a one-line vital signs summary from vitals[index]."""
    vitals = record.get("vital_signs") or []
    if not vitals:
        return "(not recorded)"
    try:
        vs = vitals[index]
    except IndexError:
        return "(not recorded)"
    if not isinstance(vs, dict):
        return "(not recorded)"
    bp_sys = vs.get("systolic_bp") or vs.get("bp_systolic")
    bp_dia = vs.get("diastolic_bp") or vs.get("bp_diastolic")
    hr = vs.get("heart_rate")
    rr = vs.get("respiratory_rate")
    temp = vs.get("temperature") or vs.get("temperature_celsius")
    spo2 = vs.get("spo2") or vs.get("oxygen_saturation")
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
    if language == "ja":
        undiag = "診断未確定"
        admit_dx = code_lookup(admit_dx_system, admit_dx_code, language) if admit_dx_code else undiag
        chief = encounter.get("chief_complaint") or "記載なし"
        description = f"第0病日: {chief}にて入院。初期推定診断: {admit_dx}。"
    else:
        undiag = "undiagnosed"
        admit_dx = code_lookup(admit_dx_system, admit_dx_code, language) if admit_dx_code else undiag
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
        name = _ja_localize_procedure(name, language)
        comps = p.get("intraop_complications") or []
        ebl = p.get("estimated_blood_loss_ml")
        if language == "ja":
            comp_str = f"（合併症: {', '.join(comps)}）" if comps else ""
            ebl_str = f" 出血量 {ebl} mL." if ebl else ""
            desc = f"第{day}病日: {name}{comp_str}.{ebl_str}"
        else:
            comp_str = f" with {', '.join(comps)}" if comps else ""
            ebl_str = f" EBL {ebl} mL." if ebl else ""
            desc = f"Day {day}: {name}{comp_str}.{ebl_str}"
        events.append(
            HospitalCourseFact(
                hospital_day=day,
                event_type="surgery",
                description=desc,
            )
        )
    return events


def _procedure_events(
    record: dict[str, Any],
    admission_dt: datetime | None,
    language: str,
) -> list[HospitalCourseFact]:
    """Only surface invasive bedside procedures that warrant mention in hospital course.

    Note: this set is intentionally broader than _PROCEDURE_NOTE_TYPES in
    document_generator.py. arterial_line appears in the hospital course but
    does NOT generate a standalone Procedure Note, because arterial line
    insertion is typically documented in a nursing flow sheet rather than a
    formal procedure note.
    """
    invasive = {
        "central_line",
        "arterial_line",   # mentioned in hospital course but no standalone Procedure Note
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
        name = _ja_localize_procedure(name, language)
        desc = (f"第{day}病日: {name}（ベッドサイドで施行）"
                if language == "ja"
                else f"Day {day}: {name} performed at bedside.")
        events.append(
            HospitalCourseFact(
                hospital_day=day,
                event_type="procedure",
                description=desc,
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
    # JP translations for common complication labels
    _COMP_JA = {
        "pneumonia": "肺炎", "urinary_tract_infection": "尿路感染",
        "dvt": "深部静脈血栓症", "pulmonary_embolism": "肺塞栓",
        "wound_infection": "創部感染", "sepsis": "敗血症",
        "acute_kidney_injury": "急性腎障害", "delirium": "せん妄",
        "bleeding": "出血", "aspiration": "誤嚥",
        "arrhythmia": "不整脈", "icu_delirium": "ICUせん妄",
        "heart_failure": "心不全", "hypotension": "低血圧",
        "aspiration_pneumonia": "誤嚥性肺炎",
    }
    prefix = "合併症: " if language == "ja" else "Complication identified: "
    # Place complications at day 1 so they appear after admission but before peaks
    return [
        HospitalCourseFact(
            hospital_day=1,
            event_type="complication",
            description=prefix + (_COMP_JA.get(c, c) if language == "ja" else str(c)),
        )
        for c in complications
    ]


def _treatment_change_events(
    record: dict[str, Any],
    admission_dt: datetime | None,
    language: str = "en",
) -> list[HospitalCourseFact]:
    """Detect treatment changes: drugs started after day 0 (escalation/switch).

    Home medications and day-0 admission orders are excluded — only
    new medications appearing on day 1+ are surfaced as treatment changes.
    """
    mars = record.get("medication_administrations") or []
    if not mars:
        return []

    # Track first appearance day of each drug
    drug_first_day: dict[str, int] = {}
    for mar in mars:
        if not isinstance(mar, dict):
            continue
        name = mar.get("drug_name") or ""
        if not name:
            continue
        admin_dt = _parse_dt(
            mar.get("actual_datetime")
            or mar.get("administered_datetime")
            or mar.get("administration_datetime")
        )
        day = _day_offset(admission_dt, admin_dt) if admin_dt else 0
        if name not in drug_first_day or day < drug_first_day[name]:
            drug_first_day[name] = day

    # Only surface drugs that first appear after day 0 (treatment changes)
    events: list[HospitalCourseFact] = []
    # Exclude common supportive drugs that are always day 0
    supportive = {"acetaminophen", "ns", "lr", "normal saline", "lactated ringer"}
    for drug, first_day in drug_first_day.items():
        if first_day < 1:
            continue  # day 0 = admission orders, not a "change"
        if any(s in drug.lower() for s in supportive):
            continue
        drug_disp = _ja_localize_drug(drug, language)
        desc = (f"第{first_day}病日: {drug_disp} 投与開始（治療強化・切替）"
                if language == "ja"
                else f"Day {first_day}: Started {drug_disp} (treatment escalation/switch).")
        events.append(
            HospitalCourseFact(
                hospital_day=first_day,
                event_type="treatment_change",
                description=desc,
            )
        )
    return events[:5]  # cap to avoid noise


def _lab_peak_events(
    record: dict[str, Any],
    admission_dt: datetime | None,
    language: str = "en",
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
        unit = _unit_for(name, language)
        factor = _JA_CONVERSION.get(name, 1.0) if language == "ja" else 1.0
        disp_val = round(val * factor, 2) if factor != 1.0 else val
        desc = (f"第{day}病日: {name} が {disp_val:.1f} {unit} まで上昇"
                if language == "ja"
                else f"Day {day}: {name} peaked at {disp_val:.1f} {unit}.")
        events.append(
            HospitalCourseFact(
                hospital_day=day,
                event_type="test_peak",
                description=desc,
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
    dx_name = code_lookup(dx_system, dx_code, language) if dx_code else (
        "診断未確定" if language == "ja" else "uncertain"
    )
    disposition = encounter.get("discharge_disposition") or "home"
    _DISPO_JA = {
        "home": "自宅", "skilled_nursing_facility": "介護施設", "rehabilitation": "リハビリ施設",
        "expired": "死亡退院", "long_term_care": "長期療養施設", "hospice": "ホスピス",
        "against_medical_advice": "自己退院", "transferred": "転院",
    }
    dispo_disp = _DISPO_JA.get(disposition, disposition) if language == "ja" else disposition

    if record.get("deceased"):
        desc = (f"第{max(day, 0)}病日: 最大限の治療にも関わらず永眠。最終診断: {dx_name}。"
                if language == "ja"
                else f"Day {max(day, 0)}: Patient died despite maximal therapy. Final diagnosis: {dx_name}.")
        return HospitalCourseFact(
            hospital_day=max(day, 0),
            event_type="death",
            description=desc,
        )

    desc = (f"第{max(day, 0)}病日: {dispo_disp}退院。最終診断: {dx_name}。"
            if language == "ja"
            else f"Day {max(day, 0)}: Discharged to {dispo_disp}. Final diagnosis: {dx_name}.")
    return HospitalCourseFact(
        hospital_day=max(day, 0),
        event_type="discharge",
        description=desc,
    )


# ============================================================
# Clinical guidance — hidden context for LLM (NOT shown in output)
# ============================================================


def extract_clinical_guidance(
    record: dict[str, Any],
    language: str = "en",
) -> dict[str, Any]:
    """Extract hidden clinical context that the LLM can use for accuracy.

    This data helps the LLM write clinically coherent narratives but must
    NOT appear verbatim in the generated text. The prompt system instruction
    tells the LLM how to use it.

    Includes:
    - confirmed_diagnosis: ground truth (for realistic differential weighting)
    - diagnosis_correct: whether the clinical team got it right
    - patient_outcome: survived / died (for appropriate severity language)
    - disease_id: internal identifier (for archetype awareness)
    - severity: mild / moderate / severe
    - archetype: trajectory pattern (standard_recovery, treatment_resistant, etc.)
    """
    condition = record.get("condition_event") or {}
    cd = record.get("clinical_diagnosis") or {}
    gt_diseases = condition.get("ground_truth_diseases") or []
    encounter = (record.get("encounters") or [{}])[0]

    return {
        "confirmed_diagnosis": gt_diseases[0] if gt_diseases else "",
        "all_diagnoses": gt_diseases,
        "diagnosis_correct": cd.get("diagnosis_correct", True),
        "patient_outcome": "died" if record.get("deceased") else "survived",
        "disease_severity": condition.get("severity", ""),
        "disease_archetype": condition.get("archetype", ""),
        "los_days": _los_days_from_encounter(encounter),
        "had_surgery": any(
            p.get("category_code") == "387713003"
            for p in (record.get("procedures") or [])
            if isinstance(p, dict)
        ),
        "complications": record.get("complications_occurred") or [],
        "icu_transferred": record.get("icu_transferred", False),
    }


def _los_days_from_encounter(encounter: dict[str, Any]) -> int:
    a = _parse_dt(encounter.get("admission_datetime"))
    d = _parse_dt(encounter.get("discharge_datetime"))
    return max(0, (d - a).days) if a and d else 0


# ============================================================
# Lab trends — admission → peak → pre-discharge trajectory
# ============================================================


def extract_lab_trends(
    record: dict[str, Any],
    admission_dt: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Extract lab value trajectories for key markers.

    Returns a dict keyed by normalized lab name:
        {
          "CRP": {
            "admission": {"value": 5.2, "day": 0},
            "peak": {"value": 180.0, "day": 3},
            "latest": {"value": 12.5, "day": 12},
            "trend": "improving"  # improving | worsening | stable | insufficient_data
          },
          ...
        }
    """
    if admission_dt is None:
        enc = (record.get("encounters") or [{}])[0]
        admission_dt = _parse_dt(enc.get("admission_datetime"))

    orders = record.get("orders") or []
    # Collect all values per lab
    series: dict[str, list[tuple[int, float]]] = {}
    for o in orders:
        if not isinstance(o, dict) or o.get("order_type") != "lab":
            continue
        result = o.get("result") or {}
        if not result:
            continue
        lab_name = (result.get("lab_name") or o.get("display_name") or "").strip()
        key = _normalize_lab_name(lab_name)
        if key not in {"CRP", "WBC", "Cr", "Lactate", "Hgb", "Plt"}:
            continue
        try:
            value = float(result.get("value", 0))
        except (TypeError, ValueError):
            continue
        result_dt = _parse_dt(result.get("result_datetime"))
        day = _day_offset(admission_dt, result_dt) if result_dt else 0
        series.setdefault(key, []).append((day, value))

    trends: dict[str, dict[str, Any]] = {}
    for key, points in series.items():
        if not points:
            continue
        points.sort(key=lambda x: x[0])
        first_day, first_val = points[0]
        peak_day, peak_val = max(points, key=lambda x: x[1])
        last_day, last_val = points[-1]

        # Determine trend
        if len(points) < 2:
            trend = "insufficient_data"
        elif last_val < first_val * 0.7:
            trend = "improving"
        elif last_val > first_val * 1.3:
            trend = "worsening"
        else:
            trend = "stable"

        trends[key] = {
            "admission": {"value": round(first_val, 1), "day": first_day},
            "peak": {"value": round(peak_val, 1), "day": peak_day},
            "latest": {"value": round(last_val, 1), "day": last_day},
            "trend": trend,
            "n_measurements": len(points),
        }
    return trends


def format_lab_trends(
    trends: dict[str, dict[str, Any]], language: str = "en"
) -> list[str]:
    """Format lab trends as human-readable bullet strings for prompts."""
    out: list[str] = []
    for name, t in sorted(trends.items()):
        unit = _unit_for(name, language)
        factor = _JA_CONVERSION.get(name, 1.0) if language == "ja" else 1.0
        adm = t["admission"]
        peak = t["peak"]
        latest = t["latest"]
        trend_label = t["trend"]

        def _cv(v: float) -> float:
            return round(v * factor, 2) if factor != 1.0 else v

        out.append(
            f"{name}: admission {_cv(adm['value'])}{unit} (day {adm['day']}) "
            f"→ peak {_cv(peak['value'])}{unit} (day {peak['day']}) "
            f"→ latest {_cv(latest['value'])}{unit} (day {latest['day']}) "
            f"[{trend_label}]"
        )
    return out


# ============================================================
# Treatment timeline — medication starts/stops/changes
# ============================================================


def extract_treatment_timeline(
    record: dict[str, Any],
    language: str = "en",
    admission_dt: datetime | None = None,
) -> list[str]:
    """Extract medication administration events as a timeline.

    Returns bullet strings like:
        "Day 0: Started Ceftriaxone IV"   (EN)
        "第0病日: セフトリアキソン 静注 開始"  (JP)
    """
    if admission_dt is None:
        enc = (record.get("encounters") or [{}])[0]
        admission_dt = _parse_dt(enc.get("admission_datetime"))

    mars = record.get("medication_administrations") or []
    if not mars:
        return []

    # Track first/last appearance of each drug
    drug_timeline: dict[str, dict[str, Any]] = {}
    for mar in mars:
        if not isinstance(mar, dict):
            continue
        name = mar.get("drug_name") or mar.get("drug") or ""
        if not name:
            continue
        route = mar.get("route", "")
        admin_dt = _parse_dt(mar.get("actual_datetime") or mar.get("administered_datetime") or mar.get("administration_datetime"))
        day = _day_offset(admission_dt, admin_dt) if admin_dt else 0

        if name not in drug_timeline:
            drug_timeline[name] = {
                "first_day": day,
                "last_day": day,
                "route": route,
            }
        else:
            drug_timeline[name]["last_day"] = max(drug_timeline[name]["last_day"], day)
            if day < drug_timeline[name]["first_day"]:
                drug_timeline[name]["first_day"] = day

    # Build timeline bullets
    events: list[tuple[int, str]] = []
    for drug, info in drug_timeline.items():
        route = info["route"]
        drug_disp = _ja_localize_drug(drug, language)
        if language == "ja":
            events.append((info["first_day"], f"第{info['first_day']}病日: {drug_disp} {route} 投与開始".strip()))
            if info["last_day"] > info["first_day"] + 1:
                events.append(
                    (info["last_day"], f"第{info['last_day']}病日: {drug_disp} 最終投与")
                )
        else:
            events.append((info["first_day"], f"Day {info['first_day']}: Started {drug_disp} {route}".strip()))
            if info["last_day"] > info["first_day"] + 1:
                events.append(
                    (info["last_day"], f"Day {info['last_day']}: Last dose of {drug_disp}")
                )

    events.sort(key=lambda x: x[0])
    return [e[1] for e in events[:20]]  # cap at 20 entries


# ============================================================
# Vitals snapshot at a specific hospital day
# ============================================================


def extract_vitals_snapshot(
    record: dict[str, Any],
    target_day: int = 0,
    admission_dt: datetime | None = None,
) -> str:
    """Return a one-line vitals summary for a specific hospital day.

    Finds the vital sign record closest to the target day.
    Useful for pre-op vitals (target_day = surgery day) or
    pre-procedure vitals.
    """
    if admission_dt is None:
        enc = (record.get("encounters") or [{}])[0]
        admission_dt = _parse_dt(enc.get("admission_datetime"))

    vitals = record.get("vital_signs") or []
    if not vitals or admission_dt is None:
        return "(not recorded)"

    # Find the best vital record near target_day.
    # Prefer records that have a complete set of fields (HR + BP + SpO2 + Temp)
    # over records that are closer in time but have mostly None fields.
    candidates: list[tuple[float, int, dict[str, Any]]] = []
    for vs in vitals:
        if not isinstance(vs, dict):
            continue
        vs_dt = _parse_dt(
            vs.get("timestamp") or vs.get("measured_datetime") or vs.get("datetime")
        )
        if vs_dt is None:
            continue
        day = _day_offset(admission_dt, vs_dt)
        dist = abs(day - target_day)
        # Count non-None vital fields as a completeness score
        completeness = sum(1 for k in ("heart_rate", "systolic_bp", "spo2",
                                        "temperature_celsius", "temperature",
                                        "respiratory_rate")
                           if vs.get(k) is not None)
        # Sort key: within ±1 day, prefer completeness; beyond that, prefer proximity
        effective_dist = dist if dist > 1 else 0
        candidates.append((effective_dist, -completeness, vs))

    if not candidates:
        return "(not recorded)"
    candidates.sort(key=lambda x: (x[0], x[1]))
    return _format_vitals_dict(candidates[0][2])


def _format_vitals_dict(vs: dict[str, Any]) -> str:
    """Format a vital signs dict into a one-line summary."""
    bp_sys = vs.get("systolic_bp") or vs.get("bp_systolic")
    bp_dia = vs.get("diastolic_bp") or vs.get("bp_diastolic")
    hr = vs.get("heart_rate")
    rr = vs.get("respiratory_rate")
    temp = vs.get("temperature") or vs.get("temperature_celsius")
    spo2 = vs.get("spo2") or vs.get("oxygen_saturation")
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
    "hemoglobin": "Hgb",
    "hgb": "Hgb",
    "hb": "Hgb",
    "platelet count": "Plt",
    "platelet": "Plt",
    "plt": "Plt",
}


def _normalize_lab_name(name: str) -> str:
    return _LAB_NAME_MAP.get(name.strip().lower(), name)


_UNIT_MAP = {
    "CRP": "mg/L", "WBC": "cells/μL", "Cr": "mg/dL",
    "Lactate": "mmol/L", "Hgb": "g/dL", "Plt": "x10^3/μL",
}

# Japanese conventional units differ from SI for CRP: mg/dL instead of mg/L.
_UNIT_MAP_JA = {
    **_UNIT_MAP,
    "CRP": "mg/dL",
}

# Conversion factors from SI to Japanese conventional units (multiply).
_JA_CONVERSION: dict[str, float] = {
    "CRP": 0.1,  # mg/L → mg/dL (divide by 10)
}


def _unit_for(name: str, language: str = "en") -> str:
    if language == "ja":
        return _UNIT_MAP_JA.get(name, _UNIT_MAP.get(name, ""))
    return _UNIT_MAP.get(name, "")
