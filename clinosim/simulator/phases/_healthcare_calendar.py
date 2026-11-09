"""Healthcare calendar — generated per year, dispatched on each event's date.

The forward loop (Issue #2169) generates each year's calendar at the year
boundary and queues the events; deliveries dispatched from it register
newborns, who then get their own rest-of-year calendar.

The RNG consumption inside this phase is entirely composed of
``derive_phase_rng(master_seed, PHASE_OUTPATIENT_CAL, …)`` sub-seeds;
no shared global generator is read.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from clinosim.locale.i18n import t
from clinosim.modules.immunization.visits import FLU_VISIT_CONDITION
from clinosim.modules.population.engine import LifeEvent, generate_healthcare_calendar
from clinosim.seeding import PHASE_OUTPATIENT_CAL, derive_phase_rng
from clinosim.simulator._scheduling_thresholds import (
    OUTPATIENT_CALENDAR_VISIT_HOUR,
    OUTPATIENT_LABS_ANNUAL_PROBABILITY,
    OUTPATIENT_LABS_QUARTERLY_PROBABILITY,
    OUTPATIENT_MINUTE_JITTER_MAX_EXCLUSIVE,
    OUTPATIENT_MINUTE_JITTER_MIN,
    OUTPATIENT_SAME_DAY_GAP_MIN,
)
from clinosim.simulator._setup import (
    _HEALTH_SCREENING_VISIT_REASON,
    _HEALTH_SCREENING_VISIT_REASON_FALLBACK,
    _activate_cached_person,
    _pediatric_visit_reason,
)
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.simulator.outpatient_dept import resolve_outpatient_department
from clinosim.simulator.screening_visit import screening_visit_spec

if TYPE_CHECKING:
    from clinosim.simulator._dispatch import InpatientStayIndex
    from clinosim.simulator.phases._forward_loop import ForwardContext


def specialty_departments_to_visit(primary_dept: str, specialties: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The specialty follow-ups that are separate visits (Issue #2645): one per
    department other than the primary visit's, in order."""
    seen = {primary_dept}
    out: list[tuple[str, str]] = []
    for name, dept in specialties:
        if dept in seen:
            continue
        seen.add(dept)
        out.append((name, dept))
    return out


def next_visit_start(previous_end: datetime) -> datetime:
    """Start of the patient's next same-day visit after one ending at ``previous_end``."""
    return previous_end + timedelta(minutes=OUTPATIENT_SAME_DAY_GAP_MIN)


def place_outpatient_visit(day_ends: dict, patient_id: str, start: datetime) -> datetime:
    """Start of a visit planned at ``start``: after the patient's previous
    visit that day when they would overlap (Issue #2690). No RNG."""
    end = day_ends.get((patient_id, start.date()))
    return max(start, next_visit_start(end)) if end else start


# Calendar events that are clinic visits; an admission (delivery, abortion)
# during a stay is merged into it by the inpatient dispatch instead.
_CLINIC_VISIT_EVENTS = frozenset({"chronic_visit", "pediatric_visit", "chemo_visit", "health_screening"})


def visit_time_outside_stays(
    stays: InpatientStayIndex, patient_records: list, patient_id: str, visit_time: datetime
) -> datetime | None:
    """``visit_time`` when the patient is not admitted then; otherwise the
    same clock time on the day after discharge (Issue #2996), past any
    further stay; ``None`` while the patient is still admitted at the
    snapshot. No RNG."""
    while (stay := stays.active_at(patient_records, patient_id, visit_time)) is not None:
        discharge = stay.encounters[0].discharge_datetime
        if discharge is None:
            return None
        visit_time = datetime.combine(discharge.date() + timedelta(days=1), visit_time.time())
    return visit_time


def note_outpatient_visit(day_ends: dict, patient_id: str, record: Any) -> None:
    """Remember when the visit in ``record`` ends (Issue #2690)."""
    encs = getattr(record, "encounters", None) or []
    end = getattr(encs[0], "discharge_datetime", None) if encs else None
    if not isinstance(end, datetime):
        return
    key = (patient_id, end.date())
    if key not in day_ends or end > day_ends[key]:
        day_ends[key] = end


def calendar_events_for_year(population: Any, year: int, ctx: ForwardContext) -> list[LifeEvent]:
    """The year's calendar (chronic follow-up, pediatric, screening, delivery,
    chemo, ...) for everyone in the population at some point of the year.

    Generated at the year boundary by the forward loop (Issue #2169), with the
    same year-keyed sub-RNG as before so streams stay cursor-independent.
    """
    calendar_key = f"{ctx.config.country}|{year:04d}|calendar"
    calendar_rng = derive_phase_rng(ctx.master_seed, PHASE_OUTPATIENT_CAL, calendar_key)
    return generate_healthcare_calendar(population, year, ctx.config.country, calendar_rng)


def newborn_calendar_events(person: Any, year: int, ctx: ForwardContext) -> list[LifeEvent]:
    """Rest-of-year calendar for a person who joined after the year boundary.

    A newborn registered mid-year missed ``calendar_events_for_year``; this
    generates their own year calendar (person-keyed sub-RNG) and keeps the
    events on or after enrollment.
    """
    from clinosim.modules.population.engine import PopulationRegistry

    solo = PopulationRegistry(persons={person.person_id: person})
    key = f"{ctx.config.country}|{year:04d}|calendar|{person.person_id}"
    rng = derive_phase_rng(ctx.master_seed, PHASE_OUTPATIENT_CAL, key)
    events = generate_healthcare_calendar(solo, year, ctx.config.country, rng)
    return [e for e in events if e.timestamp and person.in_population_at(e.timestamp)]


def dispatch_calendar_event(event: LifeEvent, ctx: ForwardContext, visit_day: date | None = None) -> datetime | None:
    """Simulate one calendar event on its date (``visit_day`` when it was
    postponed), appending its record(s).

    Issue #2996: a clinic visit dated while the patient is admitted is not
    held; the return value is the time after discharge to dispatch it at
    instead (``None`` otherwise). A visit the stay pushes into the next
    calendar year is dropped: that year's calendar has its own visits."""
    from clinosim.simulator.engine import _handle_overlap_via_merge

    day = visit_day or event.timestamp
    person = ctx.population.get_person(event.person_id)
    if not person or not person.in_population_at(day):
        return None

    ev_key = f"{event.person_id}|{event.timestamp.isoformat()}|{event.event_type}|{event.disease_id}"
    ev_rng = derive_phase_rng(ctx.master_seed, PHASE_OUTPATIENT_CAL, ev_key)

    visit_time = datetime(
        day.year,
        day.month,
        day.day,
        OUTPATIENT_CALENDAR_VISIT_HOUR,
        int(ev_rng.integers(OUTPATIENT_MINUTE_JITTER_MIN, OUTPATIENT_MINUTE_JITTER_MAX_EXCLUSIVE)),
    )
    if event.event_type in _CLINIC_VISIT_EVENTS:
        free_time = visit_time_outside_stays(ctx.inpatient_stays, ctx.patient_records, event.person_id, visit_time)
        if free_time != visit_time:
            if free_time is None or free_time.year != event.timestamp.year:
                return None
            return free_time

    patient = _activate_cached_person(
        person,
        as_of_year=event.timestamp.year,
        patient_cache=ctx.patient_cache,
        master_seed=ctx.master_seed,
        demo=ctx.demo,
    )
    # Issue #2690: a patient is in one clinic at a time — a visit that would
    # overlap an earlier same-day visit starts after it (the minute draw above
    # is unchanged, so no stream moves).
    visit_time = place_outpatient_visit(ctx.outpatient_day_ends, event.person_id, visit_time)

    if event.event_type == "chronic_visit":
        spec = ctx.followup_data.get(event.disease_id, {})
        visit_labs = list(spec.get("labs", []))
        for lab in spec.get("labs_quarterly", []):
            if ev_rng.random() < OUTPATIENT_LABS_QUARTERLY_PROBABILITY and lab not in visit_labs:
                visit_labs.append(lab)
        for lab in spec.get("labs_annual", []):
            if ev_rng.random() < OUTPATIENT_LABS_ANNUAL_PROBABILITY and lab not in visit_labs:
                visit_labs.append(lab)
        from clinosim.modules.monitoring import monitoring_labs_for_patient

        _visit_key = f"{patient.patient_id}:{visit_time.isoformat()}"
        for lab in monitoring_labs_for_patient(patient.current_medications, _visit_key):
            if lab not in visit_labs:
                visit_labs.append(lab)
        merged_spec = dict(spec)
        merged_spec["labs"] = visit_labs
        chronic_dept = resolve_outpatient_department("chronic_followup", event.disease_id, None, ctx.hospital_ops)
        opd_record = _simulate_outpatient_visit(
            patient,
            "chronic_followup",
            visit_time,
            ctx.roster,
            ev_rng,
            chronic_code=event.disease_id,
            followup_spec=merged_spec,
            country=ctx.config.country,
            config=ctx.config,
            department_id=chronic_dept,
        )
    elif event.event_type == "pediatric_visit":
        pedi_dept = resolve_outpatient_department("pediatric_visit", event.disease_id, None, ctx.hospital_ops)
        opd_record = _simulate_outpatient_visit(
            patient,
            "pediatric_visit",
            visit_time,
            ctx.roster,
            ev_rng,
            chronic_code=event.disease_id or "pediatric_visit",
            followup_spec={
                "labs": [],
                "visit_reason": _pediatric_visit_reason(event.disease_id),
            },
            country=ctx.config.country,
            config=ctx.config,
            department_id=pedi_dept,
        )
    elif event.event_type == "abortion":
        from clinosim.simulator.perinatal import simulate_abortion_encounter

        abortion_records = simulate_abortion_encounter(
            patient=patient,
            visit_date=visit_time,
            discharge_dx=event.disease_id,
            roster=ctx.roster,
            rng=ev_rng,
            country=ctx.config.country,
            config=ctx.config,
            hospital_ops=ctx.hospital_ops,
        )
        for _r in abortion_records:
            _post_hoc_overlap = _handle_overlap_via_merge(ctx.patient_records, _r, event.disease_id)
            if _post_hoc_overlap is None:
                ctx.patient_records.append(_r)
                note_outpatient_visit(ctx.outpatient_day_ends, event.person_id, _r)
        return None
    elif event.event_type == "delivery":
        from clinosim.simulator.perinatal import simulate_delivery_encounter

        delivery_records = simulate_delivery_encounter(
            patient=patient,
            visit_date=visit_time,
            roster=ctx.roster,
            rng=ev_rng,
            country=ctx.config.country,
            config=ctx.config,
            hospital_ops=ctx.hospital_ops,
            population_registry=ctx.population,
        )
        if delivery_records:
            mother_rec = delivery_records[0]
            companions = list(delivery_records[1:])
            _post_hoc_overlap = _handle_overlap_via_merge(
                ctx.patient_records, mother_rec, event.disease_id, companions=companions
            )
            if _post_hoc_overlap is None:
                ctx.patient_records.append(mother_rec)
            for _r in companions:
                ctx.patient_records.append(_r)
        return None
    elif event.event_type == "chemo_visit":
        regimen_name = event.protocol_source.split(":", 1)[1] if ":" in event.protocol_source else ""
        from clinosim.locale.loader import load_chemo_regimens

        chemo_data = load_chemo_regimens()
        regimen = (chemo_data.get("regimens") or {}).get(regimen_name) or {}
        chemo_spec: dict = {
            "labs": [],
            "visit_reason": (chemo_data.get("encounter") or {}).get("visit_reason") or "Chemotherapy infusion",
            "chemo_regimen_name": regimen_name,
            "chemo_regimen": regimen,
            "chemo_procedure": chemo_data.get("procedure") or {},
        }
        chemo_dept = resolve_outpatient_department("chemo_visit", event.disease_id, None, ctx.hospital_ops)
        opd_record = _simulate_outpatient_visit(
            patient,
            "chemo_visit",
            visit_time,
            ctx.roster,
            ev_rng,
            chronic_code=event.disease_id,
            followup_spec=chemo_spec,
            country=ctx.config.country,
            config=ctx.config,
            department_id=chemo_dept,
        )
    elif event.event_type == "health_screening":
        screening_id = event.disease_id or "annual_health_screening"
        screening_reason = _HEALTH_SCREENING_VISIT_REASON.get(event.disease_id, _HEALTH_SCREENING_VISIT_REASON_FALLBACK)
        screening_dept = resolve_outpatient_department("health_screening", screening_id, None, ctx.hospital_ops)
        # Issue #2870: the visit runs its own protocol (labs, imaging,
        # procedure, sedation), drawn on a stream of its own so the visit's
        # other draws (staff, vitals) keep theirs.
        workup_rng = derive_phase_rng(ctx.master_seed, PHASE_OUTPATIENT_CAL, f"{ev_key}|workup")
        screening_spec = screening_visit_spec(screening_id, patient, ctx.config.country, workup_rng)
        screening_spec["visit_reason"] = screening_reason
        opd_record = _simulate_outpatient_visit(
            patient,
            "health_screening",
            visit_time,
            ctx.roster,
            ev_rng,
            chronic_code=screening_id,
            followup_spec=screening_spec,
            country=ctx.config.country,
            config=ctx.config,
            department_id=screening_dept,
        )
    else:
        return None

    ctx.patient_records.append(opd_record)
    note_outpatient_visit(ctx.outpatient_day_ends, event.person_id, opd_record)

    # Issue #2868: a flu vaccination visit is not a chronic follow-up, so it
    # starts no specialty follow-up (those carried its Z23 reason).
    if event.event_type == "chronic_visit" and event.disease_id != FLU_VISIT_CONDITION:
        from clinosim.locale.loader import department_display, load_specialty_routing
        from clinosim.simulator.hospital_ops import resolve_department
        from clinosim.simulator.outpatient import _specialty_fanout_tick

        # Issue #2270: the visit reason lives on the specialty route
        # (specialty_routing.yaml); an unrouted specialty gets the generic
        # department follow-up wording.
        _specialty_visit_reason = {
            str(r.get("specialty")): r["visit_reason"] for r in load_specialty_routing() if r.get("visit_reason")
        }
        # Issue #2645: a specialty follow-up whose department is the one the
        # patient is already seen in that day is the same visit; one in another
        # department starts after the previous visit ends.
        specialties = [
            (name, resolve_department(name, ctx.hospital_ops))
            for name, _cadence, _period_key in _specialty_fanout_tick(patient, visit_time)
        ]
        slot_end = opd_record.encounters[0].discharge_datetime if opd_record.encounters else None
        for specialty_name, specialty_dept in specialty_departments_to_visit(chronic_dept, specialties):
            specialty_time = next_visit_start(slot_end) if slot_end else visit_time
            specialty_record = _simulate_outpatient_visit(
                patient,
                "chronic_followup",
                specialty_time,
                ctx.roster,
                ev_rng,
                chronic_code=event.disease_id,
                followup_spec={
                    "labs": [],
                    "visit_reason": _specialty_visit_reason.get(
                        specialty_name,
                        {
                            "en": t(
                                "module_text.specialty_followup", "en", dept=department_display(specialty_name, "en")
                            ),
                            "ja": t(
                                "module_text.specialty_followup", "ja", dept=department_display(specialty_name, "ja")
                            ),
                        },
                    ),
                },
                country=ctx.config.country,
                config=ctx.config,
                department_id=specialty_dept,
            )
            ctx.patient_records.append(specialty_record)
            note_outpatient_visit(ctx.outpatient_day_ends, event.person_id, specialty_record)
            if specialty_record.encounters:
                slot_end = specialty_record.encounters[0].discharge_datetime
    return None
