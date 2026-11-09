"""ED visits (not admitted) — drawn each month, dispatched on their date.

RNG consumption is composed of month-keyed
``derive_phase_rng(master_seed, PHASE_ED_VISIT, slot_key)`` sub-seeds;
no shared global generator is read. The slot's patient is chosen by
rendezvous hashing over the month's residents, not by an RNG draw.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from clinosim import determinism
from clinosim.countries import country_code
from clinosim.modules._shared import random_day_of_month
from clinosim.modules.encounter.protocol import protocol_min_age
from clinosim.seeding import PHASE_ED_VISIT, derive_phase_rng, id_hashes, rendezvous_pick
from clinosim.simulator._scheduling_thresholds import (
    ED_FAVORED_HOURS,
    ED_MINUTE_JITTER_MAX_EXCLUSIVE,
    ED_MINUTE_JITTER_MIN,
    ED_OCCUPATION_MISMATCH_FALLBACK,
)
from clinosim.simulator._setup import _activate_cached_person
from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.simulator.phases._forward_loop import monthly_ed_slot_count

if TYPE_CHECKING:
    from clinosim.simulator.phases._forward_loop import ForwardContext


@dataclass
class EDSlot:
    """One drawn ED visit, dispatched on ``when``."""

    when: datetime
    person_id: str
    condition_index: int
    rng: Any


class EDSlotSampler:
    """Draws each month's ED visits from the persons in the population (Issue #2169).

    The month's slot count is the locale's ``rate_per_1000_person_years``
    applied to the persons in the population that month (fractions carry
    to the next month), so the volume follows the population as it grows
    and shrinks. Each slot has its own month-keyed sub-RNG.
    """

    def __init__(self, ctx: ForwardContext) -> None:
        from clinosim.modules.encounter.protocol import load_all_encounter_conditions
        from clinosim.simulator.hospital_ops import inpatient_departments

        self.ctx = ctx
        all_conditions = load_all_encounter_conditions()
        self.conditions = [(n, spec) for n, spec in all_conditions.items() if spec.get("encounter_type") == "emergency"]
        depts = inpatient_departments(ctx.hospital_ops)
        self.restrictions = [ed_severity_restriction(spec, depts) for _n, spec in self.conditions]
        self.occ_mult_table = ctx.demo.get("occupation_risk_multipliers", {})
        self.rate = float((ctx.demo.get("ed_visit_not_admitted") or {}).get("rate_per_1000_person_years") or 0.0)
        self.prefixes = sorted({px for _n, spec in self.conditions for px in spec.get("requires_chronic_prefix") or []})
        self.prefix_share: dict[str, float] = {}
        self.carry = 0.0
        self.n_slots = 0
        # Issue #3063: conditions drawn per birth (febrile neonate), not from the visit mix.
        self.per_birth = [i for i, (_n, spec) in enumerate(self.conditions) if spec.get("incidence_per_1000_births")]

    def refresh_population_shares(self) -> None:
        """Recompute the chronic-prefix shares (once per year)."""
        self.prefix_share = _chronic_prefix_share(self.ctx.population, self.prefixes)

    def slots_for_month(self, year: int, month: int) -> list[EDSlot]:
        if not self.conditions or self.rate <= 0:
            return []
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        residents = [p for p in self.ctx.population.persons.values() if p.in_population_during(first, last)]
        n, self.carry = monthly_ed_slot_count(len(residents), self.rate, self.carry)
        resident_ids = [p.person_id for p in residents]
        hashes = id_hashes(resident_ids) if n else None
        slots: list[EDSlot] = []
        for i in range(n):
            key = f"{self.ctx.config.country}|ed-{year:04d}-{month:02d}-{i:05d}"
            rng = derive_phase_rng(self.ctx.master_seed, PHASE_ED_VISIT, key)
            # Stable pick (Issue #2357): a death or move elsewhere changes only
            # the slots that would have picked that person.
            person = residents[rendezvous_pick(f"{self.ctx.master_seed}|{key}", resident_ids, hashes)]
            weights = [
                _ed_condition_weight(name, spec, person, month, self.occ_mult_table, self.prefix_share, visit_year=year)
                * share
                for (name, spec), (_allowed, share) in zip(self.conditions, self.restrictions, strict=True)
            ]
            total = sum(weights)
            if total <= 0:
                continue
            cond_idx = int(rng.choice(len(self.conditions), p=[w / total for w in weights]))
            day = random_day_of_month(rng, year, month)
            when = datetime(
                year,
                month,
                day,
                int(rng.choice(ED_FAVORED_HOURS)),
                int(rng.integers(ED_MINUTE_JITTER_MIN, ED_MINUTE_JITTER_MAX_EXCLUSIVE)),
            )
            slots.append(EDSlot(when, person.person_id, cond_idx, rng))
        for idx in self.per_birth:
            name, spec = self.conditions[idx]
            if self.restrictions[idx][1] <= 0:
                continue  # every severity is admitted to this hospital's inpatient unit
            for person_id, when in neonatal_ed_onsets(
                spec, residents, self.ctx.config.country, self.ctx.master_seed, year, month
            ):
                key = f"{self.ctx.config.country}|ed-per-birth-{name}-{person_id}"
                slots.append(EDSlot(when, person_id, idx, derive_phase_rng(self.ctx.master_seed, PHASE_ED_VISIT, key)))
        self.n_slots += len(slots)
        return slots

    def condition(self, slot: EDSlot) -> tuple[dict[str, Any], tuple[str, ...] | None]:
        return self.conditions[slot.condition_index][1], self.restrictions[slot.condition_index][0]


def dispatch_ed_slot(slot: EDSlot, sampler: EDSlotSampler) -> None:
    """Simulate one ED visit on its date (skipped if the person left the population)."""
    ctx = sampler.ctx
    person = ctx.population.get_person(slot.person_id)
    if not person or not person.in_population_at(slot.when.date()):
        return
    patient = _activate_cached_person(
        person,
        as_of_year=slot.when.year,
        patient_cache=ctx.patient_cache,
        master_seed=ctx.master_seed,
        demo=ctx.demo,
    )
    cond, allowed = sampler.condition(slot)
    if neonate_excluded(cond, person, slot.when, sampler.conditions):
        return
    ctx.patient_records.append(
        _simulate_ed_visit(
            patient,
            cond,
            slot.when,
            ctx.roster,
            slot.rng,
            country=ctx.config.country,
            config=ctx.config,
            allowed_severities=allowed,
        )
    )


def _neonatal_period_days(conditions: list[tuple[str, dict[str, Any]]]) -> int | None:
    """The longest neonatal period (``max_age_days``) of the per-birth ED conditions."""
    days = [int(spec["max_age_days"]) for _n, spec in conditions if spec.get("incidence_per_1000_births")]
    return max(days) if days else None


def neonate_excluded(
    spec: dict[str, Any], person: Any, when: datetime, conditions: list[tuple[str, dict[str, Any]]]
) -> bool:
    """True when ``spec`` is an ordinary ED condition and ``person`` is a
    neonate at ``when`` (Issue #3063): a febrile neonate gets the neonatal
    evaluation, and the ED protocols written for older patients are not
    applied to an infant in the neonatal period."""
    if spec.get("incidence_per_1000_births"):
        return False
    period = _neonatal_period_days(conditions)
    dob = getattr(person, "date_of_birth", None)
    return period is not None and dob is not None and (when.date() - dob).days <= period


def neonatal_ed_onsets(
    spec: dict[str, Any], persons: list[Any], country: str, master_seed: int, year: int, month: int
) -> list[tuple[str, datetime]]:
    """ED visits of a per-birth condition falling in ``year``-``month``
    (Issue #3063): each infant presents at most once, with probability
    ``incidence_per_1000_births`` / 1000 for the country (none without a
    rate), on a day of life in ``min_age_days``-``max_age_days``. Drawn by
    hashing the person id, so no shared random stream is read."""
    rate = float((spec.get("incidence_per_1000_births") or {}).get(country_code(country), 0.0)) / 1000.0
    if rate <= 0:
        return []
    lo, hi = int(spec["min_age_days"]), int(spec["max_age_days"])
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    onsets: list[tuple[str, datetime]] = []
    for person in persons:
        dob = getattr(person, "date_of_birth", None)
        if dob is None or not first - timedelta(days=hi) <= dob <= last - timedelta(days=lo):
            continue
        salt = f"{master_seed}|{spec['condition_id']}|{person.person_id}"
        if not determinism.sha_bernoulli(salt, rate):
            continue
        day = dob + timedelta(days=lo + determinism.sha_index(f"{salt}|day", hi - lo + 1))
        if not first <= day <= last:
            continue
        hour = int(ED_FAVORED_HOURS[determinism.sha_index(f"{salt}|hour", len(ED_FAVORED_HOURS))])
        minute = ED_MINUTE_JITTER_MIN + determinism.sha_index(
            f"{salt}|minute", ED_MINUTE_JITTER_MAX_EXCLUSIVE - ED_MINUTE_JITTER_MIN
        )
        onsets.append((str(person.person_id), datetime(day.year, day.month, day.day, hour, minute)))
    return onsets


def ed_severity_restriction(
    spec: dict[str, Any], inpatient_depts: frozenset[str]
) -> tuple[tuple[str, ...] | None, float]:
    """Severities an ED condition keeps as ED-only visits at this hospital
    (Issue #2132), and the share of its weight they carry.

    ``admitted_with_inpatient_unit: {department, severities}`` names the
    severities that a hospital with an inpatient unit of ``department``
    admits instead (they arrive as that unit's admissions, e.g. depression
    admissions to psychiatry); the ED condition then keeps the remaining
    severities only. ``(None, 1.0)`` when nothing is restricted.
    """
    rule = spec.get("admitted_with_inpatient_unit") or {}
    if not rule or rule.get("department") not in inpatient_depts:
        return None, 1.0
    admitted = set(rule.get("severities") or [])
    dist = spec.get("severity_distribution") or {}
    kept = tuple(s for s in dist if s not in admitted and float(dist[s]) > 0)
    return kept, sum(float(dist[s]) for s in kept)


def _has_chronic_prefix(person: Any, prefix: str) -> bool:
    return any(str(getattr(c, "code", c)).startswith(prefix) for c in getattr(person, "chronic_conditions", []) or [])


def _chronic_prefix_share(population: Any, prefixes: list[str]) -> dict[str, float]:
    """Share of living residents carrying each chronic-code prefix (no RNG)."""
    alive = [p for p in population.persons.values() if getattr(p, "is_alive", True)]
    if not alive:
        return {px: 0.0 for px in prefixes}
    return {px: sum(_has_chronic_prefix(p, px) for p in alive) / len(alive) for px in prefixes}


def _ed_condition_weight(
    name: str,
    spec: dict[str, Any],
    person: Any,
    visit_month: int,
    occ_mult_table: dict[str, Any],
    prefix_share: dict[str, float],
    visit_year: int | None = None,
) -> float:
    """Selection weight of one ED condition for one resident.

    The ``min_age`` / ``max_age`` gate uses the age reached in ``visit_year``
    (Issue #2174); ``person.age`` is the static age at generation and does
    not advance over the window (a newborn stays 0).

    Conditions with ``requires_chronic_prefix`` (exacerbations of a chronic
    disease) are only drawn for residents who carry one of the prefixes; their
    weight is divided by the qualifying share of residents so the condition's
    overall share of ED visits matches its ``probability``.
    """
    person_age = int(getattr(person, "age", 0) or 0)
    dob = getattr(person, "date_of_birth", None)
    if visit_year is not None and dob is not None:
        person_age = visit_year - dob.year
    min_age = protocol_min_age(spec)
    if min_age is not None and person_age < min_age:
        return 0.0
    if spec.get("max_age") is not None and person_age > int(spec["max_age"]):
        return 0.0
    weight = float(spec.get("probability", 0.05))
    required = spec.get("requires_chronic_prefix") or []
    if required:
        matched = [px for px in required if _has_chronic_prefix(person, px)]
        if not matched:
            return 0.0
        share = sum(prefix_share.get(px, 0.0) for px in required)
        if share <= 0.0:
            return 0.0
        weight /= share
    seasonal = spec.get("seasonal", {})
    weight *= float(seasonal.get(visit_month, seasonal.get(str(visit_month), 1.0)))
    occ_mults = occ_mult_table.get(name, {})
    if occ_mults:
        weight *= occ_mults.get(getattr(person, "occupation", "other"), ED_OCCUPATION_MISMATCH_FALLBACK)
    return weight
