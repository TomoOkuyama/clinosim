"""Terminal course before an in-hospital death (Issue #2985).

The daily loop decides a death at the end of a hospital day from the
disease's mortality benchmark; the day's state and vitals were produced
before that decision and could be those of a recovering patient. When a
death is drawn, :func:`apply_terminal_course` gives the final hours their
course: the last state-history entry becomes the terminal state
(circulatory, respiratory and neurological failure) and the vitals charted
in the last ``TERMINAL_WINDOW_HOURS`` are re-derived from a state moving
from the day's state to it, ending in a full set charted shortly before
death when the last round was hours earlier.

The measurement noise comes from a per-stay sub-stream
(``seeding.terminal_course_seed``): the stay's own RNG is not read, so the
draws of every other patient and of this stay are unchanged.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta

from clinosim import determinism
from clinosim.modules.observation.pediatric_ranges import age_in_completed_months
from clinosim.modules.physiology.engine import derive_observed_vitals
from clinosim.seeding import terminal_course_seed
from clinosim.simulator._daily_loop_thresholds import (
    TERMINAL_CONSCIOUSNESS_MIN,
    TERMINAL_OBSERVATION_GAP_HOURS,
    TERMINAL_OBSERVATION_MINUTES_BEFORE_DEATH,
    TERMINAL_OXYGENATION_MIN,
    TERMINAL_PERFUSION_MAX,
    TERMINAL_VOLUME_MAX,
    TERMINAL_WINDOW_HOURS,
)
from clinosim.simulator.oxygen_course import OxygenCourse, oxygen_course_rules
from clinosim.simulator.vitals_pipeline import _loc_for, _o2_for, o2_target, spo2_on_oxygen
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType, VitalSignRecord
from clinosim.types.patient import PatientProfile

# A recovering note does not belong to the final hours.
_RECOVERY_NOTE = "improving, appetite good"


def terminal_state(state: PhysiologicalState) -> PhysiologicalState:
    """``state`` at death: no axis is better than the terminal bounds (an
    already worse axis is kept)."""
    out = deepcopy(state)
    out.perfusion_status = min(out.perfusion_status, TERMINAL_PERFUSION_MAX)
    out.volume_status = min(out.volume_status, TERMINAL_VOLUME_MAX)
    out.oxygenation_impairment = max(out.oxygenation_impairment, TERMINAL_OXYGENATION_MIN)
    out.consciousness_impairment = max(out.consciousness_impairment, TERMINAL_CONSCIOUSNESS_MIN)
    return out


def _blend(start: PhysiologicalState, end: PhysiologicalState, f: float) -> PhysiologicalState:
    out = deepcopy(start)
    for axis in ("perfusion_status", "volume_status", "oxygenation_impairment", "consciousness_impairment"):
        a, b = getattr(start, axis), getattr(end, axis)
        setattr(out, axis, a + (b - a) * f)
    return out


def apply_terminal_course(
    vitals: list[VitalSignRecord],
    state_history: list[PhysiologicalState],
    patient: PatientProfile,
    *,
    disease_id: str,
    encounter_id: str,
    death_time: datetime,
    stay_oxygen: OxygenCourse | None = None,
) -> None:
    """Rewrite, in place, the final hours before ``death_time``: the last
    ``state_history`` entry becomes :func:`terminal_state` of it and the
    vitals charted in the window follow the state's course to it.
    ``stay_oxygen`` is the stay's oxygen course: a patient on the ventilator
    stays on it through the final readings (Issue #3535)."""
    if not state_history:
        return
    day_state = state_history[-1]
    final = terminal_state(day_state)
    state_history[-1] = final
    rng = determinism.default_rng(terminal_course_seed(patient.patient_id, encounter_id))
    window = timedelta(hours=TERMINAL_WINDOW_HOURS)
    start = death_time - window

    def observe(record: VitalSignRecord) -> VitalSignRecord:
        f = min(1.0, max(0.0, (record.timestamp - start) / window))
        state = _blend(day_state, final, f)
        age_months = age_in_completed_months(patient.date_of_birth, record.timestamp)
        raw = derive_observed_vitals(state, patient.baseline_vitals, record.timestamp, rng, age_months=age_months)
        on_o2, flow, device = record.on_supplemental_oxygen, record.oxygen_flow_rate_lpm, record.oxygen_delivery_device
        spo2 = record.spo2
        if spo2 is not None:
            # The draw is consumed here; the oxygen state it feeds is resolved
            # in time order after the loop (Issue #3469).
            draws.append((len(rewritten), record.timestamp, raw["spo2"], _o2_for(raw["spo2"], disease_id, rng)))
            states[len(rewritten)] = state
            spo2 = round(raw["spo2"], 1)
            on_o2, flow, device = False, None, ""
        note = ". ".join(p for p in record.nursing_note.rstrip(".").split(". ") if p and p != _RECOVERY_NOTE)
        return replace(
            record,
            temperature_celsius=None if record.temperature_celsius is None else round(raw["temperature"], 1),
            heart_rate=None if record.heart_rate is None else int(round(raw["heart_rate"])),
            systolic_bp=None if record.systolic_bp is None else int(round(raw["systolic_bp"])),
            diastolic_bp=None if record.diastolic_bp is None else int(round(raw["diastolic_bp"])),
            respiratory_rate=None if record.respiratory_rate is None else int(round(raw["respiratory_rate"])),
            spo2=spo2,
            on_supplemental_oxygen=on_o2,
            oxygen_flow_rate_lpm=round(flow, 1) if flow else None,
            oxygen_delivery_device=device,
            consciousness_level=_loc_for(state, disease_id, 0, rng) if record.consciousness_level else "",
            nursing_note=note + "." if note else "",
        )

    draws: list = []
    states: dict[int, PhysiologicalState] = {}
    rewritten: list[int] = []
    for i, record in enumerate(vitals):
        if start <= record.timestamp < death_time:
            vitals[i] = observe(record)
            rewritten.append(i)
    full_sets = [v for v in vitals if v.timestamp < death_time and None not in (v.heart_rate, v.systolic_bp, v.spo2)]
    last_full = max(full_sets, key=lambda v: v.timestamp) if full_sets else None
    if last_full is None or death_time - last_full.timestamp > timedelta(hours=TERMINAL_OBSERVATION_GAP_HOURS):
        at = death_time - timedelta(minutes=TERMINAL_OBSERVATION_MINUTES_BEFORE_DEATH)
        nurse = vitals[-1].measured_by if vitals else ""
        template = VitalSignRecord(
            timestamp=at,
            temperature_celsius=0.0,
            heart_rate=0,
            systolic_bp=0,
            diastolic_bp=0,
            respiratory_rate=0,
            spo2=0.0,
            consciousness_level="A",
            measured_by=nurse,
            data_source="manual",
        )
        # Issue #3535: the final reading is part of the oxygen course below
        # (appended last, it kept the room-air default and dropped the device).
        vitals.append(observe(template))
        rewritten.append(len(vitals) - 1)

    # Oxygen continues from the last reading before the window and follows the
    # state's course through it, as it does over the stay.
    course = OxygenCourse()
    if stay_oxygen is not None:
        course.ventilated_since, course.ventilated_until = stay_oxygen.ventilated_since, stay_oxygen.ventilated_until
    vent_device = oxygen_course_rules().ventilation.device
    before = [v for v in vitals if v.timestamp < start and v.spo2 is not None]
    if before:
        last = max(before, key=lambda v: v.timestamp)
        if last.on_supplemental_oxygen and last.oxygen_delivery_device != vent_device:
            course.on, course.flow, course.device = True, last.oxygen_flow_rate_lpm, last.oxygen_delivery_device
    target = o2_target(disease_id)
    for key, when, raw_spo2, draw in sorted(draws, key=lambda d: d[1]):
        i = rewritten[key]
        row_state = states[key]

        def on_oxygen(r: float, f: float, st: PhysiologicalState = row_state) -> float:
            return spo2_on_oxygen(r, f, st, disease_id)

        on, flow, device, spo2 = course.resolve(when, raw_spo2, target, draw, on_oxygen)
        vitals[i] = replace(
            vitals[i],
            spo2=round(spo2, 1),
            on_supplemental_oxygen=on,
            oxygen_flow_rate_lpm=round(flow, 1) if flow else None,
            oxygen_delivery_device=device,
        )
    vitals.sort(key=lambda v: v.timestamp)


def drop_results_after_death(orders: list[Order], lab_results: list[OrderResult], death_time: datetime) -> None:
    """Issue #3280: no specimen is collected and nothing is resulted after
    the patient died. The death time is the calendar midnight after the last
    hospital day, while a hospital day runs 24 hours from the admission time,
    so an evening admission has the last day's scheduled labs ordered after
    it. A lab order placed after ``death_time`` is removed; a result timed
    after it (a specimen held over the night) is removed from ``lab_results``
    and from its order, which is then cancelled — as the vitals and
    administrations end at the death time. Draws nothing; runs after the
    day's results, so no other stay's stream is touched."""
    orders[:] = [o for o in orders if not (o.order_type == OrderType.LAB and o.ordered_datetime > death_time)]
    late = {id(o.result) for o in orders if o.result is not None and o.result.result_datetime > death_time}
    lab_results[:] = [r for r in lab_results if r.result_datetime <= death_time]
    for order in orders:
        if order.result is not None and id(order.result) in late:
            order.result = None
            order.status = OrderStatus.CANCELLED
