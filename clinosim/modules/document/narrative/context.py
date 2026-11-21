"""NarrativeContext factory (CIF → ctx)."""

from __future__ import annotations

from typing import Any

from clinosim.countries import lang_for
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.drug_safety import rule_kind
from clinosim.modules.observation.engine import reported_lab_results
from clinosim.simulator.complications import complication_names, normalized_complications
from clinosim.timeutil import parse_iso_datetime
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
    lang = lang_for(country)
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
        # Issue #3011: values in the country's reporting unit (JP CRP mg/dL),
        # as the FHIR Observation reports them.
        lab_results=reported_lab_results(_o(record, "lab_results", []) or [], locale),
        medications=_o(record, "medication_administrations", []) or [],
        diagnoses=_o(record, "diagnoses", []) or [],
        procedures=_o(record, "procedures", []) or [],
        rehab_sessions=_o(record, "rehab_sessions", []) or [],
        allergies=allergies or [],
        document_type=document_type,
        target_lang=lang,
        locale=locale,
        # Phase 1a: the CIF field carries structured dict entries (name +
        # onset_day + onset_datetime + source). ``complications_occurred``
        # stays a bare-string list to keep the template_generator consumers
        # untouched; ``complications_events`` is the dict-carrying twin
        # that the LLM prompt path reads for temporal filtering (Phase 1b).
        complications_occurred=complication_names(_o(record, "complications_occurred", []) or []),
        complications_events=normalized_complications(_o(record, "complications_occurred", []) or []),
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
        prior_safety_holds=build_prior_safety_holds(patient, encounter),
        # Issue #2995: home medications at admission (admission H&P).
        home_medications_at_admission=_o(record, "home_medications_at_admission", None),
        # Issue #1404 — neonatal admission workup projection (Apgar,
        # bilirubin trend, CCHD SpO2, hearing/metabolic screen flags,
        # Vitamin K / ophthalmic prophylaxis MAR flags). Empty for
        # non-newborn records.
        newborn_workup=newborn_workup,
        # Issue #3256: code status and ICU transfer (death summary).
        code_status=str(_o(record, "code_status", "") or ""),
        icu_transferred=bool(_o(record, "icu_transferred", False)),
        icu_transferred_day=icu_transfer_day(_o(record, "icu_transferred_day", None)),
        **visit_reason_fields(record, encounter),
        # Issue #3268: the encounter's culture results.
        microbiology=encounter_microbiology(record, encounter),
        devices=build_devices(record, encounter),
        # Issue #3246: readmission (H&P HPI and discharge summary).
        is_readmission=bool(_o(record, "is_readmission", False)),
        readmission_number=int(_o(record, "readmission_number", 0) or 0),
    )


def visit_reason_fields(record: Any, encounter: Any) -> dict[str, Any]:
    """The visit-reason facts of ``encounter`` (Issues #3249, #3252): the
    simulator's ``visit_type`` / ``visit_condition_id`` when the encounter is
    the record's own (an encounter appended to the record, such as the
    immunization enricher's vaccination visit, is not the visit the condition
    event describes), the immunizations given at the encounter and its imaging
    studies."""
    enc_id = str(_o(encounter, "encounter_id", "") or "")
    encounters = _o(record, "encounters", []) or []
    own = bool(encounters) and str(_o(encounters[0], "encounter_id", "") or "") == enc_id
    event = _o(record, "condition_event", None)
    extensions = _o(record, "extensions", {}) or {}
    return {
        "visit_type": str(_o(event, "visit_type", "") or "") if own else "",
        "visit_condition_id": str(_o(event, "visit_condition_id", "") or "") if own else "",
        "immunizations": [
            i for i in (_o(record, "immunizations", []) or []) if enc_id and _o(i, "encounter_id", "") == enc_id
        ],
        "imaging_studies": [
            s
            for s in (extensions.get("imaging", []) if isinstance(extensions, dict) else []) or []
            if enc_id and _o(s, "encounter_id", "") == enc_id
        ],
    }


def encounter_microbiology(record: Any, encounter: Any) -> list[Any]:
    """The culture results of ``encounter`` (Issue #3268)."""
    enc_id = str(_o(encounter, "encounter_id", "") or "")
    return [m for m in (_o(record, "microbiology", []) or []) if enc_id and _o(m, "encounter_id", "") == enc_id]


def build_devices(record: Any, encounter: Any) -> list[dict[str, Any]]:
    """The urinary and central venous catheters of ``encounter`` (Issue #3480).

    Per kind of ``nursing_shift_items.yaml`` ``device_kinds``: the insertion is
    the stay's insertion procedure (start time), else the placing order (its
    time), else the ICU device record's placement date; the removal is the
    device record's removal date, the only place a removal is recorded (a
    device with none is in place until discharge). Returns ``{"kind",
    "start", "end_date", "source"}`` per device, in the YAML order."""
    import re

    from clinosim.modules.document.narrative._nursing_shift_items import nursing_shift_items_config

    enc_id = str(_o(encounter, "encounter_id", "") or "")
    extensions = _o(record, "extensions", {}) or {}
    records = [
        d
        for d in (extensions.get("device", []) if isinstance(extensions, dict) else []) or []
        if not enc_id or str(_o(d, "encounter_id", "") or enc_id) == enc_id
    ]
    procedures = [
        p
        for p in _o(record, "procedures", []) or []
        if not enc_id or str(_o(p, "encounter_id", "") or enc_id) == enc_id
    ]
    orders = [
        o
        for o in _o(record, "orders", []) or []
        if str(_o(o, "status", "") or "") != "cancelled"
        and (not enc_id or str(_o(o, "encounter_id", "") or enc_id) == enc_id)
    ]
    out: list[dict[str, Any]] = []
    for dk in nursing_shift_items_config().device_kinds:
        dev = [d for d in records if _o(d, "device_type", "") in dk.device_types]
        starts: list[tuple[Any, str]] = [
            (_o(p, "start_datetime", None), "procedure")
            for p in procedures
            if _o(p, "procedure_type", "") in dk.procedure_types
        ]
        starts += [
            (_o(o, "ordered_datetime", None), "order")
            for o in orders
            if any(
                re.search(pat, str(_o(o, field, "") or ""), re.IGNORECASE)
                for pat in dk.order_patterns
                for field in ("display_name", "order_code")
            )
        ]
        starts += [(_o(d, "placement_date", None), "device") for d in dev]
        timed = [(w, src) for v, src in starts if (w := parse_iso_datetime(v, lenient=True)) is not None]
        if not timed:
            continue
        # The earliest procedure / order time; the coarse placement date only
        # when neither exists.
        precise = [x for x in timed if x[1] != "device"]
        when, source = min(precise or timed, key=lambda x: x[0])
        removals = [r for d in dev if (r := _o(d, "removal_date", None))]
        out.append(
            {
                "kind": dk.kind,
                "start": when.isoformat(),
                "end_date": str(max(removals))[:10] if removals else None,
                "source": source,
            }
        )
    return out


def icu_transfer_day(value: Any) -> int:
    """``record.icu_transferred_day`` as an int, -1 when the record has none."""
    return int(value) if isinstance(value, int) else -1


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
        "bilirubin_series": list[dict],    # {timestamp, day, value_mg_dl} per measurement
        "cchd_ru_spo2":    int | None,     # right-upper SpO2
        "cchd_le_spo2":    int | None,     # lower-extremity SpO2
        "has_aabr":        bool,           # AABR hearing screen Procedure present
        "aabr_outcome_key": str | None,    # "pass" / "refer" from outcome_code (#3404)
        "has_metabolic":   bool,           # tandem-MS metabolic screen Procedure present
        "metabolic_result_datetime": datetime | str | None,  # when the screen is reported (Issue #3358)
        "metabolic_outcome_key": "pass" | "refer" | None,
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

    # Bilirubin peak (highest value in mg/dL). Real emit shape from
    # newborn.engine.build_bilirubin_observations uses `value_mg_dl`;
    # older/legacy fixture shapes may use `total_bilirubin_mg_dl` or
    # `value`. Read all three (real shape first) — S114 verify (Issue
    # #1412) found only `value_mg_dl` populated on p=10000 production.
    bili_values: list[float] = []
    bili_series: list[dict[str, Any]] = []
    for entry in newborn_ext.get("bilirubin") or []:
        val = _o(entry, "value_mg_dl", None) or _o(entry, "total_bilirubin_mg_dl", None) or _o(entry, "value", None)
        if val is not None:
            try:
                bili_values.append(float(val))
            except (TypeError, ValueError):
                continue
            # Issue #3260: the dated series, so an exam reports only the
            # bilirubin measured by its own time.
            bili_series.append(
                {"timestamp": _o(entry, "timestamp", None), "day": _o(entry, "day", None), "value_mg_dl": float(val)}
            )
    bilirubin_peak = max(bili_values) if bili_values else None

    # CCHD SpO2 — walk entries for the right-upper (pre-ductal) and
    # lower-extremity (post-ductal) readings. Real emit shape from
    # newborn.engine.build_cchd_pulse_ox uses `site: "right_hand"` /
    # `"foot"` and `value_pct`. Legacy fixture shapes may use `ru` /
    # `right_upper` / `pre_ductal` / `spo2_percent` / `value` — support
    # all so hand-authored tests and production data both project.
    cchd_ru: int | None = None
    cchd_le: int | None = None
    for entry in newborn_ext.get("cchd_pulse_ox") or []:
        site = str(_o(entry, "site", "") or "").lower()
        spo2 = _o(entry, "value_pct", None) or _o(entry, "spo2_percent", None) or _o(entry, "value", None)
        if spo2 is None:
            continue
        try:
            spo2_int = int(spo2)
        except (TypeError, ValueError):
            continue
        # Pre-ductal (right upper) readings: production shape uses
        # `right_hand`; earlier fixtures use `ru` / `right_upper` /
        # `pre_ductal`. All recognized here.
        if site in ("ru", "right_upper", "right upper", "right_hand", "pre_ductal", "pre-ductal"):
            cchd_ru = spo2_int
        # Post-ductal (lower extremity) readings.
        elif site in ("le", "lower_extremity", "foot", "post_ductal", "post-ductal"):
            cchd_le = spo2_int

    # Presence flags for Procedures + MARs on the top-level lists.
    # Real ProcedureRecord shape uses `procedure_type` (canonical enum
    # string like "hearing_screen_aabr" / "metabolic_screen_tandem_ms")
    # rather than `display_name` — the display is resolved at emit time.
    # Check `procedure_type` first (production), fall back to
    # display / name / id for hand-authored fixtures.
    procedures = _o(record, "procedures", None) or []
    has_aabr = False
    aabr_outcome_key: str | None = None
    has_metabolic = False
    # Issue #3241: when each item was done, so a note carries only what
    # existed at its authored time (:func:`newborn_workup_known_at`).
    event_times: dict[str, str] = {}

    def _note_time(event: str, value: Any) -> None:
        text = str(value or "")
        if text and (event not in event_times or text < event_times[event]):
            event_times[event] = text

    for proc in procedures:
        ptype = str(_o(proc, "procedure_type", "") or "").lower()
        pid = str(_o(proc, "procedure_id", "") or "").upper()
        display = str(_o(proc, "display_name", "") or _o(proc, "name", "") or "").lower()
        haystack = f"{ptype} {display}"
        if (
            "aabr" in haystack
            or "hearing_screen" in haystack
            or "hearing screen" in haystack
            or "HEARING-SCREEN" in pid
        ):
            has_aabr = True
            # Issue #3404: the screen is stated once it has finished (its
            # end time), with the result the CIF recorded.
            _note_time("aabr", _o(proc, "end_datetime", None) or _o(proc, "start_datetime", None))
            aabr_outcome_key = _aabr_outcome_key(_o(proc, "outcome_code", None))
        if (
            "tandem" in haystack
            or "metabolic_screen" in haystack
            or "metabolic screen" in haystack
            or "代謝異常" in haystack
            or "METABOLIC-SCREEN" in pid
        ):
            has_metabolic = True
            _note_time("metabolic", _o(proc, "start_datetime", None))

    # Real MedicationAdministrationRecord shape uses `drug_name`
    # (not `medication_display_name` / `display_name`).
    mars = _o(record, "medication_administrations", None) or []
    has_vitamin_k = False
    has_ophthalmic = False
    for mar in mars:
        display = str(
            _o(mar, "drug_name", "") or _o(mar, "medication_display_name", "") or _o(mar, "display_name", "") or ""
        ).lower()
        mar_time = _o(mar, "actual_datetime", None) or _o(mar, "scheduled_datetime", None)
        if "vitamin k" in display or "phytonadione" in display or "フィトナジオン" in display:
            has_vitamin_k = True
            _note_time("vitamin_k", mar_time)
        if "erythromycin" in display or "エリスロマイシン" in display:
            # Ophthalmic prophylaxis in US neonates is erythromycin
            # 0.5% ophthalmic ointment. Explicit OPH route also flags.
            route = str(_o(mar, "route", "") or "").lower()
            if route in ("oph", "ophthalmic", "eye") or "eye" in display or "ophthalmic" in display:
                has_ophthalmic = True
                _note_time("ophthalmic", mar_time)
        if "silver nitrate" in display or "povidone" in display:
            has_ophthalmic = True
            _note_time("ophthalmic", mar_time)

    metabolic_ext = newborn_ext.get("metabolic_screen") or {}
    return {
        "is_neonate": True,
        "metabolic_result_datetime": _o(metabolic_ext, "result_datetime", None),
        "metabolic_outcome_key": _o(metabolic_ext, "outcome_key", None),
        "apgar_1min": apgar_by_min.get(1),
        "apgar_5min": apgar_by_min.get(5),
        "bilirubin_peak": bilirubin_peak,
        "bilirubin_series": bili_series,
        "cchd_ru_spo2": cchd_ru,
        "cchd_le_spo2": cchd_le,
        "has_aabr": has_aabr,
        "aabr_outcome_key": aabr_outcome_key,
        "has_metabolic": has_metabolic,
        "has_vitamin_k": has_vitamin_k,
        "has_ophthalmic": has_ophthalmic,
        "event_times": event_times,
        # Issue #3245: the birth data of the newborn's record (the mother's
        # delivery) and the newborn profile's own birth weight and length.
        "birth": dict(newborn_ext.get("birth") or {}),
        "birth_weight_kg": _o(patient, "weight_kg", None),
        "birth_length_cm": _o(patient, "height_cm", None),
        "cchd_at": _cchd_time(newborn_ext),
    }


def _cchd_time(newborn_ext: dict[str, Any]) -> str:
    """The earliest time of the newborn's CCHD pulse-oximetry readings."""
    times = [str(_o(e, "timestamp", "") or "") for e in newborn_ext.get("cchd_pulse_ox") or []]
    return min((x for x in times if x), default="")


def newborn_metabolic_status(workup: dict[str, Any], as_of: Any) -> str:
    """The newborn metabolic screen as known at ``as_of`` (Issue #3358), the one
    rule every document reads: ``"not_collected"`` (never done, or collected
    after ``as_of``: say nothing), ``"pending"`` (collected, the dried blood
    spot not yet reported: submitted, result pending) or ``"resulted"`` (``as_of``
    at or after the reported time). ``as_of`` None (no document time) or a
    record without a result time never states a result."""
    from clinosim.timeutil import parse_iso_datetime

    if not workup.get("has_metabolic"):
        return "not_collected"
    if as_of is None:
        return "pending"
    collected = parse_iso_datetime((workup.get("event_times") or {}).get("metabolic"), lenient=True)
    if collected is not None and collected > as_of:
        return "not_collected"
    result = parse_iso_datetime(workup.get("metabolic_result_datetime"), lenient=True)
    return "resulted" if result is not None and result <= as_of else "pending"


def _aabr_outcome_key(outcome_code: Any) -> str | None:
    """``"pass"`` / ``"refer"`` for the SNOMED outcome code of the hearing
    screen Procedure (codes from ``newborn_screening.yaml``
    ``hearing_screen``); None when the CIF carries no known code."""
    from clinosim.modules.newborn.engine import load_newborn_config

    code = str(outcome_code or "")
    cfg = load_newborn_config().get("hearing_screen") or {}
    for key in ("pass", "refer"):
        if code and code == str(cfg.get(f"outcome_{key}") or ""):
            return key
    return None


def newborn_workup_known_at(workup: dict[str, Any], as_of: Any) -> dict[str, Any]:
    """``workup`` limited to what existed at ``as_of`` (Issue #3241): a
    screening or measurement dated after the document is left out. The Apgar
    scores are birth data and stay. ``as_of`` None, or an item with no time:
    kept."""
    if not workup or as_of is None:
        return workup
    from clinosim.timeutil import parse_iso_datetime

    def after(text: Any) -> bool:
        at = parse_iso_datetime(text, lenient=True)
        return at is not None and at > as_of

    times = workup.get("event_times") or {}
    out = dict(workup)
    # Issue #3358: the metabolic screen is known from its collection and
    # resulted only from its reported time (one status for every caller).
    out["metabolic_status"] = newborn_metabolic_status(workup, as_of)
    out["has_metabolic"] = out["metabolic_status"] != "not_collected"
    for key, event in (
        ("has_aabr", "aabr"),
        ("has_vitamin_k", "vitamin_k"),
        ("has_ophthalmic", "ophthalmic"),
    ):
        if out.get(key) and after(times.get(event)):
            out[key] = False
    if after(workup.get("cchd_at")):
        out["cchd_ru_spo2"] = out["cchd_le_spo2"] = None
    series = [e for e in workup.get("bilirubin_series") or [] if not after(e.get("timestamp"))]
    out["bilirubin_series"] = series
    out["bilirubin_peak"] = max((e["value_mg_dl"] for e in series), default=None)
    return out


def build_prior_safety_holds(patient: Any, encounter: Any) -> list[dict[str, Any]]:
    """The safety holds of ``patient.safety_skip_log`` logged for encounters
    other than ``encounter`` (Issue #3250): a drug held during an earlier
    admission, for the plan of the visit that follows it. Each entry is
    ``{drug, drug_ja, reason, reason_ja, held_on}`` (``held_on``: ISO date)."""
    if patient is None or encounter is None:
        return []
    encounter_id = _o(encounter, "id", None) or _o(encounter, "encounter_id", None)
    out: list[dict[str, Any]] = []
    for entry in _o(patient, "safety_skip_log", []) or []:
        if _o(entry, "event_type", "avoid") != "hold" or _o(entry, "encounter_id", None) == encounter_id:
            continue
        out.append(
            {
                "drug": _o(entry, "candidate_drug", None) or "",
                "drug_ja": _o(entry, "candidate_drug_ja", None) or "",
                "reason": _o(entry, "active_conflict", None) or "",
                "reason_ja": _o(entry, "active_conflict_ja", None) or "",
                "held_on": str(_o(entry, "timestamp", "") or "")[:10],
            }
        )
    return out


def _build_safety_skips(patient: Any, encounter: Any) -> list[dict[str, Any]]:
    """Filter ``patient.safety_skip_log`` to entries whose encounter_id matches
    the active encounter and reshape into narrative-consumable dicts.
    Returns [] when patient is None, no log exists, or no entries match.

    Accepts both attribute-shaped inputs (``SafetySkipEntry`` dataclass +
    ``PatientProfile`` from in-process simulation) and dict-shaped inputs
    (JSON-hydrated CIF read from disk by ``passes.NarrativePass``). The
    encounter is looked up via ``id`` first (attr shape from the runtime
    ``Encounter``) then ``encounter_id`` (dict shape from CIF JSON).
    """
    if patient is None:
        return []
    raw_log = _o(patient, "safety_skip_log", []) or []
    if not raw_log:
        return []
    if encounter is None:
        return []
    encounter_id = _o(encounter, "id", None) or _o(encounter, "encounter_id", None)
    if encounter_id is None:
        return []
    out: list[dict[str, Any]] = []
    for entry in raw_log:
        if _o(entry, "encounter_id", None) != encounter_id:
            continue
        verdict = _o(entry, "verdict", None)
        out.append(
            {
                "considered": _o(entry, "candidate_drug", None),
                "considered_ja": _o(entry, "candidate_drug_ja", None),
                "avoided_due_to": _o(entry, "active_conflict", None),
                "avoided_due_to_ja": _o(entry, "active_conflict_ja", None),
                "rationale_en": _o(verdict, "rationale_en", None),
                "rationale_ja": _o(verdict, "rationale_ja", None),
                "substituted_with": _o(entry, "substituted_with", None),
                "substituted_with_ja": _o(entry, "substituted_with_ja", None),
                "context": _o(entry, "context_hint", None),
                "severity": _o(verdict, "severity", None),
                # Issue #1403: event_type distinguishes silent-drop paths
                # (avoid / hold / substitute / deescalate) for narrative
                # Rule 2 cadence dispatch. Default "avoid" preserves the
                # legacy pair-conflict interpretation for older logs.
                "event_type": _o(entry, "event_type", "avoid"),
                "stopped_on_day": _o(entry, "stopped_on_day", None),
                # Issue #2930: allergy / disease / interaction, read from the
                # verdict's rule id, so an allergy skip is worded as an allergy.
                "conflict_kind": rule_kind(_o(verdict, "rule_id", None)),
                # Issue #3411: the rule that logged the event (a discharge
                # prescription hold is not an in-stay hold) and the stored
                # reason text (a hold of the table's change kind is worded as
                # a change).
                "rule_id": _o(verdict, "rule_id", None),
                "hold_reason_key": _o(verdict, "matched_active_drug", None),
            }
        )
    return out
