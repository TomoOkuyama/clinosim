"""Chemo cycle scheduler cluster.

Extracted verbatim from ``clinosim/modules/population/engine.py`` as
step C3e of the full-review Phase C engine split (CRITICAL C3).
Behavior is byte-identical — ``engine.py`` re-exports these names so
every call site stays intact (``patient/activator`` and dedicated
tests import ``pick_active_chemo_regimen`` from the engine façade).

RNG consumption is composed of ``chemotherapy_regimen_seed(person_id,
cancer_code)`` sub-seeds; the caller's prng is NOT touched.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from clinosim.types.population import LifeEvent, PersonRecord


def pick_active_chemo_regimen(
    chemo_rng: np.random.Generator,
    regimens: dict,
    by_cancer: dict,
    cancer_code: str,
) -> tuple[str, dict] | None:
    """Consume one ``chemo_rng.random()`` and return the actively-assigned
    chemo regimen ``(name, regimen_dict)`` for ``cancer_code``, or ``None``
    when the patient falls into the surveillance-only residual mass.

    Kept as a stand-alone helper so both call sites — ``_chemo_cycle_events``
    (cycle event scheduling) and ``patient/activator._derive_home_medications``
    (chronic-med active-regimen mutex, Issue #1329) — share exactly one
    implementation of the Bernoulli envelope walk. Callers create their own
    ``np.random.default_rng(chemotherapy_regimen_seed(person_id, code))``
    and pass it in; this helper never creates or shares state.
    """
    assignments = by_cancer.get(cancer_code) or []
    if not assignments:
        return None
    u = float(chemo_rng.random())
    cumulative = 0.0
    for entry in assignments:
        cumulative += float(entry.get("probability", 0.0) or 0.0)
        if u < cumulative:
            name = str(entry.get("regimen") or "")
            regimen = regimens.get(name)
            if not name or regimen is None:
                return None
            return (name, regimen)
    return None


def _chemo_cycle_events(person: PersonRecord, year: int) -> list[LifeEvent]:
    """Emit chemo_visit LifeEvents for one person's active chemo regimen(s).

    RNG-neutrality contract: consumes ZERO calls on the caller's ``prng`` —
    every random draw uses ``chemotherapy_regimen_seed(person_id, cancer_code)``
    (a per-patient / per-cancer-code deterministic sub-RNG, sibling of
    the RT-Procedure emit pattern). YAML edits to ``chemo_regimens.yaml``
    therefore never cascade into unrelated patients' calendar streams.

    Design (slice-1): one regimen per cancer code; the assignment table
    is a simple Bernoulli draw against the code's ``probability``. If
    the draw succeeds, the patient carries that regimen for the whole
    year and cycles fire at the regimen's ``cycle_interval_days``
    starting from a random Day-1 offset in the first cycle window,
    capped by ``course_cycles`` (per-year cap = min(course_cycles,
    365 / cycle_interval_days)).
    """
    from clinosim.locale.loader import load_chemo_regimens
    from clinosim.seeding import chemotherapy_regimen_seed

    data = load_chemo_regimens()
    regimens = data.get("regimens") or {}
    by_cancer = data.get("by_cancer") or {}
    if not regimens or not by_cancer:
        return []

    out: list[LifeEvent] = []
    for cancer_code in person.chronic_conditions:
        assignments = by_cancer.get(cancer_code) or []
        if not assignments:
            continue
        chemo_rng = np.random.default_rng(chemotherapy_regimen_seed(person.person_id, cancer_code))
        picked = pick_active_chemo_regimen(chemo_rng, regimens, by_cancer, cancer_code)
        if picked is None:
            continue
        picked_name, regimen = picked
        interval = int(regimen.get("cycle_interval_days") or 0)
        if interval <= 0:
            continue
        course_cycles = int(regimen.get("course_cycles") or 0) or (365 // interval)
        max_cycles_this_year = min(course_cycles, max(1, 365 // interval))
        day_offset = int(chemo_rng.integers(1, interval + 1))
        cycle_start = date(year, 1, 1) + timedelta(days=day_offset - 1)
        for cycle_idx in range(max_cycles_this_year):
            visit_day = cycle_start + timedelta(days=interval * cycle_idx)
            if visit_day.year != year:
                break
            out.append(
                LifeEvent(
                    person_id=person.person_id,
                    event_type="chemo_visit",
                    timestamp=visit_day,
                    severity=0.0,
                    condition_type="chemo_infusion",
                    disease_id=cancer_code,
                    encounter_type="outpatient",
                    protocol_source=f"chemo_regimens:{picked_name}",
                )
            )
    return out
