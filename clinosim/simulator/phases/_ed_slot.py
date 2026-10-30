"""ED-visit slot phase runner.

Extracted verbatim from ``clinosim/simulator/engine.py`` as step C2f of
the full-review Phase C engine split (CRITICAL C2). Behavior is byte-
identical — ``engine.py`` re-exports the symbol via a lazy import so
every ``run_beta`` call site stays intact.

RNG consumption is composed of
``derive_phase_rng(master_seed, PHASE_ED_VISIT, slot_key)`` sub-seeds;
no shared global generator is read.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from clinosim.seeding import PHASE_ED_VISIT, derive_phase_rng
from clinosim.simulator._scheduling_thresholds import (
    ED_DAY_MAX_EXCLUSIVE,
    ED_DAY_MIN,
    ED_FAVORED_HOURS,
    ED_MINUTE_JITTER_MAX_EXCLUSIVE,
    ED_MINUTE_JITTER_MIN,
    ED_OCCUPATION_MISMATCH_FALLBACK,
    ED_RATE_PER_ADMITTED_DEFAULT,
)
from clinosim.simulator._setup import _activate_cached_person
from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.types.config import SimulatorConfig
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

if TYPE_CHECKING:
    from clinosim.simulator._setup import _TimeRangeBounds


def _run_ed_slot_phase(
    *,
    inpatient_records: list[CIFPatientRecord],
    patient_records: list[CIFPatientRecord],
    population: Any,
    demo: dict[str, Any],
    roster: Any,
    config: SimulatorConfig,
    bounds: _TimeRangeBounds,
    master_seed: int,
    patient_cache: dict[tuple[str, int | None], PatientProfile],
    hospital_ops: dict[str, Any] | None = None,
) -> int:
    """Emit the "ED visits (not admitted)" slot-based phase.

    Draws ``n_ed = int(len(inpatient_records) * ed_rate)`` slot RNGs
    (``master_seed ^ PHASE_ED_VISIT``, slot-keyed), samples per-slot
    (visit month / person / weighted condition / minute jitter) and
    appends the resulting ``CIFPatientRecord`` entries to
    ``patient_records``. The slot-RNG stream is cursor-independent;
    the snapshot filter and natural-death gate run after date
    sampling to keep the stream shape stable across cursors.

    Returns the final ``n_ed`` for the caller's progress log.
    """
    from clinosim.modules.encounter.protocol import load_all_encounter_conditions

    all_enc_conditions = load_all_encounter_conditions()
    ed_conditions = [
        (name, spec) for name, spec in all_enc_conditions.items() if spec.get("encounter_type") == "emergency"
    ]
    ed_demo = demo.get("ed_visit_not_admitted", {})
    total_months = (bounds.raw_end_y - bounds.start_y) * 12 + (bounds.raw_end_m - bounds.start_m) + 1
    n_ed = _ed_visit_count(
        ed_demo,
        n_inpatient=len(inpatient_records),
        n_persons=len(population.persons),
        total_months=total_months,
    )
    if not ed_conditions or n_ed <= 0:
        return 0

    from clinosim.simulator.hospital_ops import inpatient_departments

    _depts = inpatient_departments(hospital_ops)
    restrictions = [ed_severity_restriction(spec, _depts) for _name, spec in ed_conditions]
    occ_mult_table = demo.get("occupation_risk_multipliers", {})
    prefix_share = _chronic_prefix_share(
        population,
        sorted({px for _name, spec in ed_conditions for px in spec.get("requires_chronic_prefix") or []}),
    )
    for slot in range(n_ed):
        slot_key = f"{config.country}|ed-slot-{slot:06d}"
        slot_rng = derive_phase_rng(master_seed, PHASE_ED_VISIT, slot_key)

        month_offset = int(slot_rng.integers(0, total_months))
        visit_month = ((bounds.start_m - 1 + month_offset) % 12) + 1
        visit_year = bounds.start_y + (bounds.start_m - 1 + month_offset) // 12

        person_id = slot_rng.choice(list(population.persons.keys()))
        person = population.get_person(person_id)
        if not person or not person.in_population_during(
            date(visit_year, visit_month, 1),
            date(visit_year, visit_month, calendar.monthrange(visit_year, visit_month)[1]),
        ):
            continue
        patient = _activate_cached_person(
            person,
            as_of_year=visit_year,
            patient_cache=patient_cache,
            master_seed=master_seed,
            demo=demo,
        )

        ed_probs = [
            _ed_condition_weight(name, spec, person, visit_month, occ_mult_table, prefix_share) * share
            for (name, spec), (_allowed, share) in zip(ed_conditions, restrictions, strict=True)
        ]
        total_p = sum(ed_probs)
        if total_p <= 0:
            continue
        ed_probs = [p / total_p for p in ed_probs]
        cond_idx = int(slot_rng.choice(len(ed_conditions), p=ed_probs))
        _cond_name, cond = ed_conditions[cond_idx]
        ed_year = bounds.start_y + (bounds.start_m - 1 + month_offset) // 12
        ed_day = int(slot_rng.integers(ED_DAY_MIN, ED_DAY_MAX_EXCLUSIVE))
        ed_hour = int(slot_rng.choice(ED_FAVORED_HOURS))
        ed_time = datetime(
            ed_year,
            visit_month,
            ed_day,
            ed_hour,
            int(slot_rng.integers(ED_MINUTE_JITTER_MIN, ED_MINUTE_JITTER_MAX_EXCLUSIVE)),
        )
        if bounds.snapshot_dt and ed_time > bounds.snapshot_dt:
            continue
        if not person.in_population_at(ed_time.date()):
            continue

        ed_record = _simulate_ed_visit(
            patient,
            cond,
            ed_time,
            roster,
            slot_rng,
            country=config.country,
            config=config,
            allowed_severities=restrictions[cond_idx][0],
        )
        patient_records.append(ed_record)
    return n_ed


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
) -> float:
    """Selection weight of one ED condition for one resident.

    Conditions with ``requires_chronic_prefix`` (exacerbations of a chronic
    disease) are only drawn for residents who carry one of the prefixes; their
    weight is divided by the qualifying share of residents so the condition's
    overall share of ED visits matches its ``probability``.
    """
    person_age = int(getattr(person, "age", 0) or 0)
    if spec.get("min_age") is not None and person_age < int(spec["min_age"]):
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


def _ed_visit_count(ed_demo: dict[str, Any], *, n_inpatient: int, n_persons: int, total_months: int) -> int:
    """Number of ED-visit slots for the run.

    ``rate_per_1000_person_years`` (national ED visit rate, independent of the
    admission mix) takes precedence; otherwise the legacy
    ``rate_per_admitted`` multiple of inpatient records is used.
    """
    per_py = ed_demo.get("rate_per_1000_person_years")
    if per_py is not None:
        return int(n_persons * total_months / 12 * float(per_py) / 1000)
    return int(n_inpatient * ed_demo.get("rate_per_admitted", ED_RATE_PER_ADMITTED_DEFAULT))
