"""Simulator setup / pre-flight cluster.

Extracted verbatim from ``clinosim/simulator/engine.py`` as step C2a of
the full-review Phase C engine split (CRITICAL C2). Behavior is byte-
identical — ``engine.py`` re-exports these names via lazy delegators so
every call site stays intact.

This module carries no RNG consumption of its own; ``activate_cached_person``
derives a per-person sub-RNG via ``derive_phase_rng``, which is pure
seed-material math (no shared global generator).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.seeding import PHASE_INPATIENT_SIM, derive_phase_rng
from clinosim.types.config import SimulatorConfig
from clinosim.types.encounter import EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile


def _load_health_screening_visit_reason() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    from clinosim.locale.loader import load_health_screening_visit_reason

    raw = load_health_screening_visit_reason()
    screenings_raw = raw.get("screenings", {}) or {}
    screenings: dict[str, dict[str, str]] = {}
    for key, row in screenings_raw.items():
        if isinstance(row, dict):
            screenings[str(key)] = {lang: str(txt) for lang, txt in row.items()}
    fallback_raw = raw.get("fallback", {}) or {}
    fallback: dict[str, str] = {str(k): str(v) for k, v in fallback_raw.items()}
    return screenings, fallback


_HEALTH_SCREENING_VISIT_REASON, _HEALTH_SCREENING_VISIT_REASON_FALLBACK = _load_health_screening_visit_reason()


def _pediatric_visit_reason(disease_id: str) -> str | dict[str, str]:
    """Look up the visit_reason for a `pediatric_visit` LifeEvent from the schedule YAML.

    The schedule is keyed by encounter-key (e.g., ``well_child_infant``,
    ``pediatric_uri_young``); multiple encounter-keys may share the same
    ``disease_id`` (for example, ``pediatric_uri_young`` / ``pediatric_uri_school``
    / ``pediatric_uri_adolescent`` are three age-band-specific
    frequencies for the same clinical concept ``pediatric_uri``). Look
    up by direct key match first, then by ``disease_id`` scan across all
    entries so both shapes resolve. Falls back to a generic label if the
    id is in neither position (e.g., LifeEvent authored by an out-of-tree
    tool). Issue #760 pass 2 introduced this helper; pass 4 extended the
    lookup to handle multi-band entries.

    Returns the raw yaml value — either a plain string or a bilingual
    ``{en, ja}`` dict — and lets the outpatient emit-site call
    ``clinosim.locale.text.resolve_text`` with the correct locale (Session
    90 narrative-review fix: pediatric_schedule.yaml was single-string
    English, causing JP cohorts to leak English into chief_complaint and
    into the template narrative fallback SOAP).
    """
    from clinosim.modules.pediatric.calendar import load_pediatric_schedule

    schedule = load_pediatric_schedule()
    entry = schedule.get(disease_id)
    if entry and entry.get("visit_reason"):
        return entry["visit_reason"]
    for candidate_entry in schedule.values():
        if candidate_entry.get("disease_id") == disease_id and candidate_entry.get("visit_reason"):
            return candidate_entry["visit_reason"]
    return {"en": f"Pediatric visit: {disease_id}", "ja": "小児外来受診"}


def _parse_time_range_bound(bound: str) -> datetime:
    """Parse a `config.time_range` bound string into a datetime.

    Accepts both ``YYYY-MM-DD`` (CLI-populated) and ``YYYY-MM`` (test
    fixtures / month-precision callers). A month-only string resolves to
    day 1 (00:00) of that month — the natural lower bound for the month.
    """
    try:
        return datetime.strptime(bound, "%Y-%m-%d")
    except ValueError:
        return datetime.strptime(bound, "%Y-%m")


class _TimeRangeBounds(NamedTuple):
    """Resolved month-loop bounds for ``run_beta``.

    - ``start_y`` / ``start_m``: inclusive lower bound of the sim window.
    - ``end_y`` / ``end_m``: upper bound of the month loop, capped by
      ``snapshot_date`` when it precedes the config's end — this is what
      the primary per-month event-generation loop reads.
    - ``raw_end_y`` / ``raw_end_m``: uncapped upper bound preserved from
      ``config.time_range[1]``. The P4' ED slot phase sizes a draw range
      off these so the sampled month is cursor-independent even though
      the month-loop bound itself is cursor-capped (F1 cross-cursor
      determinism). See the per-ED-slot computation for the invariant.
    - ``snapshot_dt``: parsed ``config.snapshot_date`` (``None`` means
      no snapshot cap).
    - ``start_dt_lb``: day-precision lower bound used by the per-month
      filter (Issue #1039 — month-precision generation can emit events
      earlier than ``--start``).
    """

    start_y: int
    start_m: int
    end_y: int
    end_m: int
    raw_end_y: int
    raw_end_m: int
    snapshot_dt: datetime | None
    start_dt_lb: datetime


def _activate_cached_person(
    person: PersonRecord,
    *,
    as_of_year: int | None,
    patient_cache: dict[tuple[str, int | None], PatientProfile],
    master_seed: int,
    demo: dict[str, Any],
) -> PatientProfile:
    """Return the cached ``PatientProfile`` for a person, activating on miss.

    A person who appears across multiple phases (admission, readmission,
    post-discharge, calendar, ED) must share a single ``PatientProfile``
    so their chronic-condition onset/stage, physiological profile, and
    baseline vitals are consistent across every encounter. The cache
    is keyed by ``(person_id, as_of_year)`` per Issue #1581 so a year-1
    encounter sees that year's stage snapshot rather than end-of-sim.
    ``as_of_year=None`` preserves the pre-#1581 single-cached-profile
    behaviour. Patient activation is fully determined by
    ``(patient_id, as_of_year)`` — the per-person sub-RNG is snapshot-
    independent, and ``activate_patient`` honours ``as_of_year`` via
    ``person.disease_stage_history``.
    """
    key = (person.person_id, as_of_year)
    if key not in patient_cache:
        act_rng = derive_phase_rng(master_seed, PHASE_INPATIENT_SIM, f"activate|{person.person_id}")
        patient_cache[key] = activate_patient(person, act_rng, demo, as_of_year=as_of_year)
    return patient_cache[key]


def _derive_time_range_bounds(config: SimulatorConfig) -> _TimeRangeBounds:
    """Parse ``config.time_range`` + ``config.snapshot_date`` into the
    month-loop bounds used by ``run_beta``.
    """
    start_y, start_m = int(config.time_range[0][:4]), int(config.time_range[0][5:7])
    end_y, end_m = int(config.time_range[1][:4]), int(config.time_range[1][5:7])
    raw_end_y, raw_end_m = end_y, end_m

    snapshot_dt: datetime | None = None
    if config.snapshot_date:
        snapshot_dt = datetime.strptime(config.snapshot_date, "%Y-%m-%d")
        snap_y, snap_m = snapshot_dt.year, snapshot_dt.month
        if (snap_y, snap_m) < (end_y, end_m):
            end_y, end_m = snap_y, snap_m

    start_dt_lb = _parse_time_range_bound(config.time_range[0])
    return _TimeRangeBounds(
        start_y=start_y,
        start_m=start_m,
        end_y=end_y,
        end_m=end_m,
        raw_end_y=raw_end_y,
        raw_end_m=raw_end_m,
        snapshot_dt=snapshot_dt,
        start_dt_lb=start_dt_lb,
    )


def _load_hospital_ops(hospital_config_path: str | None) -> dict[str, Any]:
    """Load hospital-operations YAML into the engine.

    ``hospital_config_path`` is the explicit path (CLI / API caller); when
    ``None`` the default ``config/hospital_operations.yaml`` is loaded via
    the facility loader.
    """
    from clinosim.simulator.hospital_ops import validate_hospital_ops

    if hospital_config_path:
        import yaml

        with open(Path(hospital_config_path), encoding="utf-8") as f:
            ops = yaml.safe_load(f) or {}
        validate_hospital_ops(ops, str(hospital_config_path))
        return ops
    from clinosim.modules.facility.hospital_state import load_hospital_operations

    ops = load_hospital_operations()
    validate_hospital_ops(ops, "config/hospital_operations.yaml")
    return ops


def _resolve_pop_size(hospital_ops: dict[str, Any], config: SimulatorConfig) -> int:
    """Resolve the catchment population size for a run.

    If the user did not pass ``-p`` (``config.catchment_population is None``)
    the hospital's ``recommended_population`` (country-specific or scalar)
    wins; a user-supplied value overrides and prints a soft warning on
    disagreement (Bug D). Fallback is 40 000 when the YAML lacks the key.
    """
    recommended_raw = hospital_ops.get("recommended_population")
    if not recommended_raw:
        return config.catchment_population or 40000
    if isinstance(recommended_raw, dict):
        recommended = int(recommended_raw.get(config.country) or recommended_raw.get("default", 40000))
    else:
        recommended = int(recommended_raw)
    if config.catchment_population is None:
        return recommended
    if config.catchment_population != recommended:
        print(
            f"⚠️  User-specified -p {config.catchment_population} used as-is "
            f"(hospital recommended: {recommended} for {config.country})",
            file=sys.stderr,
        )
    return config.catchment_population


def _load_prev_admission_cache(
    cache_dir: Path | str | None,
    config: SimulatorConfig,
) -> dict[tuple[str, str, str], CIFPatientRecord]:
    """Load the F4 previous-snapshot admission-loop cache.

    Returns an index of ``(person_id, admission_date_iso, disease_id) ->
    CIFPatientRecord`` for cached INPATIENT, non-readmission records whose
    patients discharged entirely before the cache's snapshot cursor.

    An invalid cache (missing / stale manifest / seed-config-country drift)
    is reported to stderr and treated as a cold start — the caller gets
    an empty dict. ``cache_dir=None`` returns ``{}`` without any I/O.

    See the per-event cache-hit sites inside ``run_beta`` for the two
    confirmed classes of shared-mutable-state divergence a hit can cause
    for OTHER admissions in the same run (implied-chronic accretion on
    the shared activated ``PatientProfile``; ``HospitalState`` queue
    congestion). F1's per-event sub-seed determinism guarantees the
    cached record's OWN bytes are identical to a fresh simulation.
    """
    prev_admission_cache: dict[tuple[str, str, str], CIFPatientRecord] = {}
    if cache_dir is None:
        return prev_admission_cache

    from clinosim.simulator.memoize import (
        _all_pids_from_cif,
        eligible_patient_ids,
        is_cache_valid,
        load_patient_records_from_cif,
        read_cache_manifest,
    )

    cache_dir_p = Path(cache_dir)
    valid, reason = is_cache_valid(cache_dir_p, config)
    if not valid:
        print(f"  ⚠️  cache invalidated ({reason}); recomputing from scratch", flush=True)
        return prev_admission_cache

    manifest = read_cache_manifest(cache_dir_p)
    assert manifest is not None
    prev_cursor_date = datetime.strptime(manifest.snapshot_date, "%Y-%m-%d").date()
    prev_cif_dir = cache_dir_p / "cif"
    all_prev_pids = _all_pids_from_cif(prev_cif_dir)
    prev_all = load_patient_records_from_cif(prev_cif_dir, all_prev_pids)
    flat_prev_records = [r for records in prev_all.values() for r in records]
    eligible = eligible_patient_ids(flat_prev_records, prev_cursor_date)
    for pid, records in prev_all.items():
        if pid not in eligible:
            continue
        for r in records:
            if not r.encounters:
                continue
            if r.encounters[0].encounter_type != EncounterType.INPATIENT:
                continue
            if r.is_readmission:
                continue
            enc = r.encounters[0]
            ce_disease_id = (
                r.condition_event.ground_truth_diseases[0]
                if r.condition_event.ground_truth_diseases
                else r.condition_event.symptom_pattern
            )
            if not ce_disease_id:
                continue
            admission_date_iso = enc.admission_datetime.date().isoformat()
            prev_admission_cache[(pid, admission_date_iso, ce_disease_id)] = r
    print(
        f"  Cache: {len(eligible)} eligible patients, {len(prev_admission_cache)} admission-loop records reusable",
        flush=True,
    )
    return prev_admission_cache
