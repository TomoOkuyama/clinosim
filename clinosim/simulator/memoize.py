"""F4 snapshot memoisation — reuse the previous snapshot's output as a cache.

The core primitive that makes daily cron feasible for large populations.
A patient whose every encounter was already discharged as of the previous
snapshot produces bit-identical output on the next cursor advance
(consequence of snapshot semantics + F1 cross-cursor determinism). By
skipping the simulator for those patients and loading them from the
previous CIF instead, a p=500k advance shrinks from hours to minutes.

No state module or ``cursor.json`` is needed. The cache directory is the
previous snapshot's output directory itself; only a single
``_cache_manifest.json`` file coexists alongside it.

**One known limitation** remains after Issue #761's cache-hit queue
replay landed. It requires touching ``clinosim/simulator/inpatient.py``,
which is outside the cache-hit path insertion range
(``clinosim/simulator/engine.py`` admission loop only), and is recorded
here as follow-up backlog rather than fixed inline because the required
fix falls outside this module's scope.

(A second limitation, cross-patient ``result_datetime`` drift from
uncounted ``hospital_state`` queue increments on cache-hit admissions,
was fixed in Issue #761 by replaying each cached admission's lab /
imaging orders through ``replay_order_to_state`` on the memo side —
see ``clinosim/simulator/engine.py::_replay_cached_admission_queue``.
That limitation is no longer active; historical detail is preserved at
the bottom of this docstring for context and for the corresponding note
in ``test_memoize_hit_bit_identical``.)

1. **``_IMPLIED_CHRONIC_BY_DISEASE`` accretion**
   (``inpatient.py:493``). When ``_simulate_patient`` sees an admission
   whose disease_id maps to the implied-chronic table, it appends
   directly (in-place, no RNG, purely deterministic on disease_id + sex)
   to the ``chronic_conditions`` list of the *shared* ``PatientProfile``
   object held in ``engine.py``'s ``patient_cache[pid]``. A cache hit
   skips the ``_simulate_patient`` call entirely, so this mutation is
   never applied to the shared object during the memo run. Any later
   record for the same patient (processed after the cache-hit admission)
   sees the shared object with one fewer chronic condition, which then
   propagates through ``initialize_state`` into the physiological state
   of downstream admissions. The test
   ``tests/unit/test_engine_memoize.py::test_memoize_hit_bit_identical``
   excludes any patient in this class from the comparison entirely (same
   pattern as ``test_engine_cross_cursor.py`` note 3).

   **A' Phase 1 note (Issue #440)**. After
   ``_deactivate_to_layer1`` began live-syncing
   ``patient_cache[pid].current_medications``, a cold-vs-memo divergence
   analogous to limitation 1 appeared on the ``current_medications``
   field. **The new divergence path is confirmed empirically.** However,
   the exact-name dedup added alongside the change (``_build_discharge_rx``
   in ``inpatient.py``) prevents same-name drug accumulation across
   admissions, so the observed drift after Phase 1 + dedup
   (p=600 / seed=123 / 2 mo advance, stress variant of
   ``tests/unit/test_engine_memoize.py::test_memoize_hit_bit_identical``)
   is::

     master   chronic_conditions drift = 5 (POP-000281 / 483 / 489 / 502 / 537)
              current_medications drift = 0
              combined drift               = 5
     branch   chronic_conditions drift = 5 (same 5 pids)
              current_medications drift = 1 (POP-000483)
              combined drift               = 5 (POP-000483 is already
                                                caught on the chronic side,
                                                so the existing fingerprint
                                                exclusion covers it)

   The excluded-pid set is **identical between master and branch**, so
   the fingerprint detection is not extended pre-emptively to include
   ``current_medications``. Extending it would not add protection for
   any patient not already protected, and it would silence a future
   canonical-cmp failure that would fail loudly if a patient ever drifts
   on ``current_medications`` without drifting on ``chronic_conditions``.
   That fail-loud channel is worth keeping.

   **A' Phase 2 outstanding work (Issue #440)**. On the memo run,
   cache-hit admissions load from the previous CIF but
   ``patient_cache[pid]`` is rebuilt in ``_activate_cached``, which does
   not restore the "medications newly started in the previous admission"
   that ``person.current_medications`` held at cursor A. Consequently
   a subsequent encounter for the same patient in the same memo run
   simulates as "patient without the drugs prescribed at discharge",
   which is clinically wrong (the cold run correctly carries them
   through via A'). The fix requires performing the equivalent of the
   previous CIF's ``_deactivate_to_layer1`` Layer 2 restore on the memo
   side; that has been captured on Issue #440 as Phase 2.

Historic — fixed by Issue #761
------------------------------

**``HospitalState`` resource-queue congestion**
(``clinosim/modules/order/engine.py``:``calculate_result_time_from_state``
→ ``hospital_state.add_to_queue``). The result turnaround for a lab or
imaging order depends on the *cumulative, shared* congestion state
``hospital_state.lab_queue`` / ``ct_queue`` etc. A cache-hit admission
never produced the queue increments its lab / imaging orders would have
produced, so the ``result_datetime`` of unrelated admissions later in
the same run (not even necessarily the same patient) drifted from the
cold run. Stress test at p=300-1000 across multiple seeds reproduced
the drift on the order of tens of minutes (dates and clinical content
unaffected). #762's chronic-prevalence recalibration shifted the
default ``test_memoize_hit_bit_identical`` config (p=100 / seed=42 /
1 mo advance) into the "consistently triggers" zone and forced the
interim ``_strip_result_datetime`` workaround in ``_canonical_cmp``.
Issue #761's fix reverted the workaround: the cache-hit branches in
``clinosim/simulator/engine.py`` now call
``_replay_cached_admission_queue``, which iterates the loaded record's
``orders`` and applies ``update_for_time`` + ``add_to_queue`` for each
lab / imaging order via ``clinosim/modules/order/engine.py::``
``replay_order_to_state``. Zero RNG draws are added on the memo path,
and cold and memo runs now produce bit-identical ``result_datetime``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clinosim.types.config import SimulatorConfig
    from clinosim.types.output import CIFPatientRecord

_MANIFEST_FILENAME = "_cache_manifest.json"
_MANIFEST_SCHEMA_VERSION = 1


@dataclass
class CacheManifest:
    """Metadata for a previous snapshot's cache. Persists as ``_cache_manifest.json``."""

    schema_version: int
    master_seed: int
    config_hash: str
    snapshot_date: str
    country: str
    population_size: int


def compute_config_hash(config: SimulatorConfig) -> str:
    """Canonical SHA-256 hash of a ``SimulatorConfig``, excluding cursor-dependent fields.

    Configs that differ only in cursor (observation cutoff) are cache-
    eligible, so their hashes must match. If seed / country / population
    / hospital / ``time_range[0]`` (start) changes, the hash changes and
    the cache is invalidated.

    Excluded fields:
      - ``snapshot_date`` (the explicit cursor).
      - ``time_range[1]`` (cursor mirror on the CLI ``--end``; the CLI
        sets both ``snapshot_date`` and ``time_range[1]`` from ``--end``,
        so both must be excluded to keep the cache valid as the cursor
        advances).

    NOTE: ``SimulatorConfig`` is a Pydantic ``BaseModel`` (not a stdlib
    dataclass), so ``model_dump()`` is used rather than
    ``dataclasses.asdict()`` for the canonical snapshot. ``default=str``
    in ``json.dumps`` covers any residual non-JSON-native values (tuples
    already serialise as lists, but this keeps the hash robust against
    future field types).
    """
    d = config.model_dump()
    d.pop("snapshot_date", None)
    # The cursor also lives in ``time_range[1]`` via the CLI ``--end`` flag.
    # Accept either tuple or list.
    tr = d.get("time_range")
    if isinstance(tr, (list, tuple)) and len(tr) >= 2:
        # Keep only the start: the cache stays valid as long as start is stable.
        d["time_range"] = [tr[0]]
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def write_cache_manifest(output_dir: Path, config: SimulatorConfig) -> None:
    """Write ``_cache_manifest.json`` to the output directory."""
    manifest = CacheManifest(
        schema_version=_MANIFEST_SCHEMA_VERSION,
        master_seed=config.random_seed,
        config_hash=compute_config_hash(config),
        snapshot_date=config.snapshot_date or "",
        country=config.country,
        population_size=config.catchment_population or 0,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / _MANIFEST_FILENAME).open("w", encoding="utf-8") as f:
        json.dump(asdict(manifest), f, ensure_ascii=False, indent=2)


def read_cache_manifest(cache_dir: Path) -> CacheManifest | None:
    """Read the cache manifest from a directory. Returns ``None`` if absent."""
    path = cache_dir / _MANIFEST_FILENAME
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        d = json.load(f)
    return CacheManifest(**d)


def is_cache_valid(cache_dir: Path, config: SimulatorConfig) -> tuple[bool, str]:
    """Decide whether ``cache_dir`` is compatible with ``config``.

    Returns ``(valid, reason)``. The cache is valid when everything
    except ``snapshot_date`` (seed / country / population / hospital /
    ...) matches the cache manifest. Any mismatch fails loudly: the
    caller is told to ignore the cache and rerun end-to-end.
    """
    manifest = read_cache_manifest(cache_dir)
    if manifest is None:
        return False, f"no cache manifest at {cache_dir / _MANIFEST_FILENAME}"
    if manifest.schema_version != _MANIFEST_SCHEMA_VERSION:
        return False, (f"cache schema version {manifest.schema_version} != expected {_MANIFEST_SCHEMA_VERSION}")
    if manifest.master_seed != config.random_seed:
        return False, (f"seed mismatch: cache={manifest.master_seed} config={config.random_seed}")
    if manifest.config_hash != compute_config_hash(config):
        return False, "config_hash mismatch (config changed since cache was written)"
    if manifest.country != config.country:
        return False, f"country mismatch: cache={manifest.country} config={config.country}"
    return True, "ok"


def eligible_patient_ids(
    patient_records: list[CIFPatientRecord],
    prev_cursor_date: date,
) -> set[str]:
    """Patient IDs whose every encounter completed on or before ``prev_cursor_date``.

    Strict rule: if any encounter is still in progress
    (``discharge_datetime is None``) or has ``discharge_datetime >
    prev_cursor``, the patient is ineligible. Any patient who could
    cross the cursor must be re-simulated fully.

    A single ``patient_id`` typically maps to many separate
    ``CIFPatientRecord`` entries in ``patient_records`` (one admission
    plus several annual chronic-disease follow-up visits, ED visits,
    etc. — an empirical p=300 run showed ~90 % of patients have two or
    more records). The original implementation added ``pid`` to the
    result set independently per record
    (``if all_completed: result.add(pid)``), so a patient with one
    complete record and one in-progress record would still end up in
    the eligible set (whichever record happened to be iterated last did
    not matter — ``add`` is monotonic and nothing ever removed a pid
    once added). That would let the F4 cache substitute a patient who
    still has an open encounter. Aggregating per pid first (any
    incomplete encounter anywhere disqualifies the whole patient) fixes
    it; behaviour for the existing single-record-per-patient unit tests
    is unchanged.
    """
    seen: set[str] = set()
    ineligible: set[str] = set()
    for r in patient_records:
        pid = r.patient.patient_id
        seen.add(pid)
        if pid in ineligible:
            continue
        for enc in r.encounters:
            dc = enc.discharge_datetime
            if dc is None or dc.date() > prev_cursor_date:
                ineligible.add(pid)
                break
    return seen - ineligible


def _all_pids_from_cif(cif_dir: Path) -> set[str]:
    """Fast pre-scan of every ``patient_id`` present in the previous CIF (no dataclass conversion).

    Reuses ``clinosim.modules.output.cif_reader.CIFReader.iter_patients()``
    as the single source of truth so the structural-CIF walk logic is
    not duplicated. Narrative merge is not needed for cache use, but
    ``CIFReader`` continues (with a warning only) when the narrative
    directory is absent, so it is harmless here.
    """
    from clinosim.modules.output.cif_reader import CIFReader

    reader = CIFReader(str(cif_dir))
    pids: set[str] = set()
    for raw in reader.iter_patients():
        pid = (raw.get("patient") or {}).get("patient_id", "")
        if pid:
            pids.add(pid)
    return pids


def load_patient_records_from_cif(
    cif_dir: Path,
    eligible_pids: set[str],
) -> dict[str, list[CIFPatientRecord]]:
    """Load every record for the given patient IDs from the previous CIF, grouped by ``pid``.

    A single patient may have multiple independent ``CIFPatientRecord``
    entries — admission, readmission, chronic follow-up (calendar),
    ED visit, and so on (p=300 empirical: ~90 % of patients have two
    or more records). Return a ``dict[str, list[CIFPatientRecord]]``
    grouped by ``pid`` (rather than the naive ``dict[str,
    CIFPatientRecord]`` that assumes one record per patient), so that
    ``eligible_patient_ids`` can inspect every record for a given
    patient when deciding completeness.

    Deserialisation uses ``pydantic.TypeAdapter(CIFPatientRecord)``.
    ``CIFPatientRecord`` is a stdlib dataclass, but Pydantic v2 can
    validate dataclasses (including nested dataclasses, ``Enum``,
    ``date``, and ``datetime`` — a p=200 real-data verification
    confirmed correct round-trip from JSON back to the original types).
    The single exception is ``extensions: dict[str, Any]``: because the
    field has no declared type, values written by a module as a
    dataclass (e.g. ``ImagingStudyRecord``) come back as raw dicts.
    That is the same state assumed by the existing AD-55 / AD-56
    dual-access convention
    (``clinosim/modules/_shared.py:get_attr_or_key`` / ``_o()``); the
    FHIR adapter and other CIF-from-disk readers already treat
    ``extensions`` as dicts.
    """
    if not eligible_pids:
        return {}

    from pydantic import TypeAdapter

    from clinosim.modules.output.cif_reader import CIFReader
    from clinosim.types.output import CIFPatientRecord

    ta: TypeAdapter[CIFPatientRecord] = TypeAdapter(CIFPatientRecord)
    reader = CIFReader(str(cif_dir))
    result: dict[str, list[CIFPatientRecord]] = {}
    for raw in reader.iter_patients():
        pid = (raw.get("patient") or {}).get("patient_id", "")
        if pid not in eligible_pids:
            continue
        record = ta.validate_python(raw)
        result.setdefault(pid, []).append(record)
    return result
