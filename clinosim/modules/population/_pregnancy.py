"""Pregnancy / perinatal lifecycle scheduler.

Extracted verbatim from ``clinosim/modules/population/engine.py`` as
step C3d of the full-review Phase C engine split (CRITICAL C3).
Behavior is byte-identical — ``engine.py`` re-exports these names so
every call site stays intact.

RNG consumption is composed of ``perinatal_delivery_seed(person_id, year)``
sub-seeds; the caller's prng is NOT touched (byte-neutrality contract).
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from clinosim.modules._shared import is_jp
from clinosim.types.population import LifeEvent, PersonRecord, TemporalStatePeriod

_PREGNANCY_ELIGIBLE_MIN_AGE = 15
_PREGNANCY_ELIGIBLE_MAX_AGE = 49


def _annual_conception_rate(lc: dict, country: str, age: int) -> float:
    """Look up the age-banded annual conception probability for ``country``.

    Bands in yaml are inclusive ranges like ``"25-29": 0.075``. Returns
    ``0.0`` for ages outside the eligible window or when config missing.
    """
    rates = (lc.get("annual_conception_rate") or {}).get("jp" if is_jp(country) else "us") or {}
    for band, value in rates.items():
        if "-" not in band:
            continue
        try:
            lo, hi = (int(x) for x in band.split("-"))
        except ValueError:
            continue
        if lo <= age <= hi:
            return float(value)
    return 0.0


_PERINATAL_STAGE_COUNTERS: dict[str, int] = {}


def _perinatal_stage_incr(stage: str) -> None:
    _PERINATAL_STAGE_COUNTERS[stage] = _PERINATAL_STAGE_COUNTERS.get(stage, 0) + 1


def _pregnancy_lifecycle_events(person: PersonRecord, year: int, country: str) -> list[LifeEvent]:
    """Full pregnancy lifecycle scheduler (META #957 Incr 1).

    Replaces the pre-Incr-1 ``_perinatal_delivery_events`` "Z34 chronic
    marker → one delivery/year" scheduler with a biology-shaped model:

      * Annual conception Bernoulli against the age-banded rate in
        ``perinatal.yaml::lifecycle.annual_conception_rate`` (locale-
        specific, MHLW/CDC-authoritative). On conception, opens a
        ``TemporalStatePeriod(state_type="pregnancy")`` with metadata
        ``{lmp, edd, planned_delivery_date}`` recording the LMP, EDD
        (LMP + gestation_days), and the jittered delivery date.
      * On the year containing the planned delivery date, emits one
        ``delivery`` IMP event + two ``postpartum_visit`` AMB follow-ups
        (7 d and 28 d post-delivery) and closes the period with
        ``outcome="delivered"``.
      * During any sim year the pregnancy is active, emits
        ``prenatal_visit`` AMB events at gestational weeks configured in
        ``lifecycle.prenatal_visit_gestational_weeks`` (default: 12/24/36).
      * Abortion path: on conception, ``resolve_pregnancy_outcome``
        rolls a per-(mother, year) sub-RNG; if it hits, we emit a single
        ``abortion`` event at ~10 gestational weeks and close the period
        with ``outcome="aborted"``. Same discharge diagnosis (O03.9 /
        O04.5) as the pre-Incr-1 flow.

    RNG-neutrality contract: consumes ZERO calls on the caller's
    ``prng``. Every draw uses ``perinatal_delivery_seed(person_id, year)``
    (sibling of ``chemotherapy_regimen_seed``). Non-obstetric patients'
    calendars are byte-identical whether this scheduler runs or not.

    Cross-year state: pregnancy periods carry across sim years via
    ``person.state_periods``. A conception in year N with EDD in year
    N+1 emits prenatal visits in year N (those before Dec 31) and the
    delivery + postpartum in year N+1. Same period record is consulted
    both years; the year-N call opens the period, the year-N+1 call
    closes it. The RNG cursor for year N+1 does NOT re-roll conception
    for that person because the ``get_active_state`` short-circuit skips
    the Bernoulli path.

    Age gate: mothers must be within [15, 49] per the Z34
    icd10_sex_restrictions.yaml sex-lock; ages outside this window
    return no events (and do not open new periods).
    """
    if person.sex != "F":
        return []
    if not (_PREGNANCY_ELIGIBLE_MIN_AGE <= person.age <= _PREGNANCY_ELIGIBLE_MAX_AGE):
        return []
    _perinatal_stage_incr("called_fertile_female")
    from clinosim.locale.loader import load_perinatal_config
    from clinosim.seeding import perinatal_delivery_seed
    from clinosim.simulator.perinatal import resolve_pregnancy_outcome

    cfg = load_perinatal_config()
    lc = cfg.get("lifecycle") or {}
    if not lc:
        _perinatal_stage_incr("config_missing")
        return []
    gestation_days = int(lc.get("gestation_days", 280))
    prenatal_ga_weeks = list(lc.get("prenatal_visit_gestational_weeks") or [12, 24, 36])
    postpartum_offsets = list(lc.get("postpartum_visit_offsets_days") or [7, 28])
    jit = lc.get("delivery_jitter_days") or [-7, 7]
    jit_lo, jit_hi = int(jit[0]), int(jit[1])

    rng = np.random.default_rng(perinatal_delivery_seed(person.person_id, year))

    active = person.get_active_state("pregnancy")
    if active is not None:
        _perinatal_stage_incr("carried_active_period")
    if active is None:
        rate = _annual_conception_rate(lc, country, person.age)
        if rate <= 0.0:
            _perinatal_stage_incr("rate_zero")
            return []
        _perinatal_stage_incr("conception_bernoulli_attempted")
        if float(rng.random()) >= rate:
            _perinatal_stage_incr("conception_declined")
            return []
        _perinatal_stage_incr("conception_rolled_pregnant")
        lmp_offset = int(rng.integers(0, 365))
        lmp = date(year, 1, 1) + timedelta(days=lmp_offset)
        edd = lmp + timedelta(days=gestation_days)

        outcome, discharge_dx = resolve_pregnancy_outcome(person.person_id, person.age, year)
        _perinatal_stage_incr(f"outcome_{outcome}")
        if outcome == "abortion":
            ab_offset_days = 70 + int(rng.integers(-14, 15))
            ab_date = lmp + timedelta(days=ab_offset_days)
            if ab_date.year != year:
                ab_date = date(year, 12, 31)
            period = TemporalStatePeriod(
                state_type="pregnancy",
                start_date=lmp,
                end_date=ab_date,
                outcome="aborted",
                metadata={
                    "lmp": lmp,
                    "edd": edd,
                    "abortion_date": ab_date,
                    "abortion_dx": discharge_dx,
                },
                period_seq=len(person.state_history("pregnancy")),
            )
            person.state_periods.append(period)
            return [
                LifeEvent(
                    person_id=person.person_id,
                    event_type="abortion",
                    timestamp=ab_date,
                    severity=0.0,
                    condition_type="pregnancy_termination",
                    disease_id=discharge_dx,
                    encounter_type="outpatient",
                    protocol_source="perinatal:abortion",
                )
            ]

        jitter = int(rng.integers(jit_lo, jit_hi + 1))
        planned_delivery_date = edd + timedelta(days=jitter)
        complications: list[str] = []
        for entry in cfg.get("complications", {}).get("bernoulli_draws") or []:
            prob = float(entry.get("probability", 0.0) or 0.0)
            if prob <= 0.0:
                continue
            if float(rng.random()) < prob:
                complications.append(str(entry.get("code") or ""))
        active = TemporalStatePeriod(
            state_type="pregnancy",
            start_date=lmp,
            end_date=None,
            outcome="",
            metadata={
                "lmp": lmp,
                "edd": edd,
                "planned_delivery_date": planned_delivery_date,
                "complications": [c for c in complications if c],
            },
            period_seq=len(person.state_history("pregnancy")),
        )
        person.state_periods.append(active)

    lmp = active.metadata["lmp"]
    planned_delivery_date = active.metadata.get("planned_delivery_date") or active.metadata["edd"]

    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    events: list[LifeEvent] = []

    for ga_wk in prenatal_ga_weeks:
        visit_date = lmp + timedelta(weeks=int(ga_wk))
        if not (year_start <= visit_date <= year_end):
            continue
        if visit_date >= planned_delivery_date:
            continue
        events.append(
            LifeEvent(
                person_id=person.person_id,
                event_type="chronic_visit",
                timestamp=visit_date,
                severity=0.0,
                condition_type="prenatal_visit",
                disease_id="Z34",
                encounter_type="outpatient",
                protocol_source="perinatal:prenatal",
            )
        )

    if year_start <= planned_delivery_date <= year_end:
        _perinatal_stage_incr("delivery_emitted_this_year")
        events.append(
            LifeEvent(
                person_id=person.person_id,
                event_type="delivery",
                timestamp=planned_delivery_date,
                severity=0.0,
                condition_type="perinatal_delivery",
                disease_id="Z34",
                encounter_type="inpatient",
                protocol_source="perinatal:delivery",
            )
        )
        for offset in postpartum_offsets:
            pp_dt = planned_delivery_date + timedelta(days=int(offset))
            if pp_dt.year != year:
                pp_dt = date(year, 12, 31)
            events.append(
                LifeEvent(
                    person_id=person.person_id,
                    event_type="chronic_visit",
                    timestamp=pp_dt,
                    severity=0.0,
                    condition_type="postpartum",
                    disease_id="Z39",
                    encounter_type="outpatient",
                    protocol_source="perinatal:postpartum",
                )
            )
        active.end_date = planned_delivery_date
        active.outcome = "delivered"
        active.metadata["delivered_on"] = planned_delivery_date
    else:
        _perinatal_stage_incr(
            "delivery_deferred_next_year" if planned_delivery_date > year_end else "delivery_before_sim_year"
        )

    return events
