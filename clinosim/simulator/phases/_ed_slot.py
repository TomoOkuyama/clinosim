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

from datetime import datetime
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
    ed_rate = ed_demo.get("rate_per_admitted", ED_RATE_PER_ADMITTED_DEFAULT)
    n_ed = int(len(inpatient_records) * ed_rate)
    if not ed_conditions or n_ed <= 0:
        return 0

    occ_mult_table = demo.get("occupation_risk_multipliers", {})
    for slot in range(n_ed):
        slot_key = f"{config.country}|ed-slot-{slot:06d}"
        slot_rng = derive_phase_rng(master_seed, PHASE_ED_VISIT, slot_key)

        total_months = (bounds.raw_end_y - bounds.start_y) * 12 + (bounds.raw_end_m - bounds.start_m) + 1
        month_offset = int(slot_rng.integers(0, total_months))
        visit_month = ((bounds.start_m - 1 + month_offset) % 12) + 1
        visit_year = bounds.start_y + (bounds.start_m - 1 + month_offset) // 12

        person_id = slot_rng.choice(list(population.persons.keys()))
        person = population.get_person(person_id)
        if not person or not person.is_alive:
            continue
        patient = _activate_cached_person(
            person,
            as_of_year=visit_year,
            patient_cache=patient_cache,
            master_seed=master_seed,
            demo=demo,
        )

        occupation = getattr(person, "occupation", "other")
        person_age = int(getattr(person, "age", 0) or 0)
        ed_probs = []
        for name, spec in ed_conditions:
            cond_min_age = spec.get("min_age")
            cond_max_age = spec.get("max_age")
            if cond_min_age is not None and person_age < int(cond_min_age):
                ed_probs.append(0.0)
                continue
            if cond_max_age is not None and person_age > int(cond_max_age):
                ed_probs.append(0.0)
                continue
            base_p = spec.get("probability", 0.05)
            seasonal = spec.get("seasonal", {})
            seasonal_mod = float(seasonal.get(visit_month, seasonal.get(str(visit_month), 1.0)))
            occ_mults = occ_mult_table.get(name, {})
            if occ_mults:
                occ_mod = occ_mults.get(occupation, ED_OCCUPATION_MISMATCH_FALLBACK)
            else:
                occ_mod = 1.0
            ed_probs.append(base_p * seasonal_mod * occ_mod)
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
        if not person.is_alive_at(ed_time.date()):
            continue

        ed_record = _simulate_ed_visit(
            patient,
            cond,
            ed_time,
            roster,
            slot_rng,
            country=config.country,
            config=config,
        )
        patient_records.append(ed_record)
    return n_ed
