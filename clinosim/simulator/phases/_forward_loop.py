"""The forward simulation loop — every phase advances month by month (Issue #2169).

Each simulated month runs these steps in order:

1. **Year boundary** (January, and the first month of the window):
   ``advance_population`` (aging passes, community mortality, longitudinal
   state), then the year's healthcare calendar is generated and queued.
2. **Monthly life events**: ``generate_monthly_events`` for everyone in the
   population; events that need the hospital are queued.
3. **ED visits**: the month's ED slots are drawn from the persons in the
   population and queued.
4. **Dispatch**: queued events dated in this month are dispatched in date
   order (admissions first on a given day). Dispatching produces new events
   that are queued too:
   - an index admission or readmission queues its post-discharge follow-up,
   - an index admission queues its readmission, when one fires,
   - a delivery registers a newborn, who enrolls at birth-stay discharge and
     gets a rest-of-year calendar.

Because a death is recorded the moment its stay is dispatched, and every
later event is gated on ``in_population_at`` its own date, nobody has an
encounter after death; and a person who joins mid-window (a newborn) takes
part in everything from enrollment on.

All draws use event-keyed sub-RNGs (``derive_phase_rng``), so the order of
dispatch does not shift any event's own randomness.
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import LifeEvent, generate_monthly_events
from clinosim.seeding import PHASE_LIFE_EVENT, derive_phase_rng
from clinosim.simulator import log as sim_log
from clinosim.simulator._dispatch import _dispatch_hospital_events, _DispatchState
from clinosim.types.encounter import EncounterType
from clinosim.types.output import CIFPatientRecord

# Dispatch order of event kinds that share a timestamp: admissions lead,
# so a death in hospital that day gates the rest.
_KIND_ORDER = {"life": 0, "readmission": 1, "calendar": 2, "post_discharge": 3, "ed": 4}


@dataclass
class QueuedEvent:
    when: datetime
    kind: str
    payload: Any


class EventQueue:
    """Date-ordered queue of pending events of every kind."""

    def __init__(self) -> None:
        # Entries are ordered by day, then kind (admissions lead their day),
        # then time, then insertion.
        self._heap: list[tuple[date, int, datetime, int, QueuedEvent]] = []
        self._seq = itertools.count()

    def push(self, when: datetime | date, kind: str, payload: Any) -> None:
        if not isinstance(when, datetime):
            when = datetime(when.year, when.month, when.day)
        heapq.heappush(
            self._heap, (when.date(), _KIND_ORDER[kind], when, next(self._seq), QueuedEvent(when, kind, payload))
        )

    def pop_through(self, last_day: date) -> Iterator[QueuedEvent]:
        """Yield events dated on or before ``last_day``, including ones pushed meanwhile."""
        while self._heap and self._heap[0][0] <= last_day:
            yield heapq.heappop(self._heap)[-1]


def monthly_ed_slot_count(n_persons: int, rate_per_1000_person_years: float, carry: float) -> tuple[int, float]:
    """ED slots for one month and the fractional remainder to carry forward."""
    expected = carry + n_persons * rate_per_1000_person_years / 1000 / 12
    n = math.floor(expected + 1e-9)  # absorb float error so whole totals are not lost
    return n, expected - n


@dataclass
class ForwardContext:
    """Run-wide state shared by every phase of the forward loop."""

    config: Any
    master_seed: int
    population: Any
    patient_records: list[CIFPatientRecord]
    patient_cache: dict
    prev_admission_cache: dict
    hospital_state: Any
    hospital_ops: dict[str, Any]
    beds_total: int
    inpatient_departments: Any
    protocols: dict[str, Any]
    healthcare: Any
    roster: Any
    demo: dict[str, Any]
    followup_data: dict[str, Any]
    country_key: str
    window: tuple[date, date]
    cutoff: date
    dispatch_state: _DispatchState = field(default_factory=_DispatchState)
    n_life_events: int = 0
    n_hospital_events: int = 0


def _month_last_day(year: int, month: int) -> date:
    import calendar

    return date(year, month, calendar.monthrange(year, month)[1])


def run_forward_loop(ctx: ForwardContext, months: list[tuple[int, int]]) -> None:
    """Advance the whole simulation through ``months`` (in order)."""
    from clinosim.simulator.phases._ed_slot import EDSlotSampler, dispatch_ed_slot
    from clinosim.simulator.phases._healthcare_calendar import (
        calendar_events_for_year,
        dispatch_calendar_event,
        newborn_calendar_events,
    )
    from clinosim.simulator.phases._post_discharge import dispatch_post_discharge, schedule_post_discharge
    from clinosim.simulator.phases._readmission import dispatch_readmission, schedule_readmission

    queue = EventQueue()
    ed_sampler = EDSlotSampler(ctx)
    known_persons = set(ctx.population.persons)

    def in_window(when: date) -> bool:
        return ctx.window[0] <= when <= ctx.cutoff

    def queue_inpatient_followups(record: CIFPatientRecord, *, index_stay: bool) -> None:
        if not record.encounters or record.encounters[0].encounter_type != EncounterType.INPATIENT:
            return
        followup = schedule_post_discharge(record, ctx)
        if followup is not None and in_window(followup.date()):
            queue.push(followup, "post_discharge", (record, followup))
        if index_stay:
            re_event = schedule_readmission(record, ctx)
            if re_event is not None and in_window(re_event.timestamp):
                queue.push(re_event.timestamp, "readmission", re_event)

    def enroll_new_persons(year: int) -> None:
        new_ids = [pid for pid in ctx.population.persons if pid not in known_persons]
        for pid in new_ids:
            known_persons.add(pid)
            for ev in newborn_calendar_events(ctx.population.persons[pid], year, ctx):
                if in_window(ev.timestamp):
                    queue.push(ev.timestamp, "calendar", ev)

    for i, (year, month) in enumerate(months):
        if month == 1 or i == 0:
            advance_population(ctx.population, year, ctx.config.country, window=ctx.window)
            for ev in calendar_events_for_year(ctx.population, year, ctx):
                if ev.timestamp and in_window(ev.timestamp):
                    queue.push(ev.timestamp, "calendar", ev)
            ed_sampler.refresh_population_shares()

        month_rng = derive_phase_rng(ctx.master_seed, PHASE_LIFE_EVENT, f"{year:04d}-{month:02d}")
        monthly = generate_monthly_events(
            ctx.population,
            year,
            month,
            month_rng,
            country=ctx.config.country,
            master_seed=ctx.master_seed,
            inpatient_departments=ctx.inpatient_departments,
        )
        monthly = [e for e in monthly if not e.timestamp or in_window(e.timestamp)]
        ctx.n_life_events += len(monthly)
        for ev in monthly:
            if ev.requires_hospital:
                queue.push(ev.timestamp, "life", ev)

        for slot in ed_sampler.slots_for_month(year, month):
            if in_window(slot.when.date()):
                queue.push(slot.when, "ed", slot)

        for item in queue.pop_through(_month_last_day(year, month)):
            n_before = len(ctx.patient_records)
            if item.kind == "life":
                ctx.n_hospital_events += 1
                _dispatch_one_life_event(item.payload, ctx)
                for record in ctx.patient_records[n_before:]:
                    queue_inpatient_followups(record, index_stay=not record.is_readmission)
            elif item.kind == "readmission":
                readmitted = dispatch_readmission(item.payload, ctx)
                if readmitted is not None:
                    queue_inpatient_followups(readmitted, index_stay=False)
            elif item.kind == "post_discharge":
                index_record, followup_time = item.payload
                dispatch_post_discharge(index_record, followup_time, ctx)
            elif item.kind == "calendar":
                dispatch_calendar_event(item.payload, ctx)
            elif item.kind == "ed":
                dispatch_ed_slot(item.payload, ed_sampler)
            enroll_new_persons(year)

    sim_log.info(
        "engine",
        "forward_loop_done",
        records=len(ctx.patient_records),
        life_events=ctx.n_life_events,
        hospital_events=ctx.n_hospital_events,
        ed_slots=ed_sampler.n_slots,
        peak_concurrent=ctx.dispatch_state.concurrent_patients,
    )


def _dispatch_one_life_event(event: LifeEvent, ctx: ForwardContext) -> None:
    _dispatch_hospital_events(
        events=[event],
        total=ctx.n_hospital_events,
        label="inpatient",
        state=ctx.dispatch_state,
        patient_records=ctx.patient_records,
        patient_cache=ctx.patient_cache,
        prev_admission_cache=ctx.prev_admission_cache,
        population=ctx.population,
        hospital_state=ctx.hospital_state,
        hospital_ops=ctx.hospital_ops,
        beds_total=ctx.beds_total,
        protocols=ctx.protocols,
        healthcare=ctx.healthcare,
        roster=ctx.roster,
        config=ctx.config,
        master_seed=ctx.master_seed,
        demo=ctx.demo,
    )
