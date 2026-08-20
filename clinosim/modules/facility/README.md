# `clinosim.modules.facility` — hospital operational-state model

## Purpose

Models the time-varying operational state of a single hospital —
resource-queue utilisation (lab, CT, MRI, X-ray, ultrasound, OR),
bed occupancy, ED crowding, and shift-based staff levels — and
computes queueing-theory delays that downstream lab / imaging / OR
orders use to schedule realistic result times. Also owns the loader
for the default hospital-operations YAML.

## Scope

- **In scope**: `HospitalState` dataclass (per-resource queue floats
  in `[0, 1]`, per-role staff floats), `update_for_time(dt,
  hospital_ops)` (shift dispatch by hour + weekday, weekend modifier,
  named daily-pattern deltas from YAML), `calculate_delay(resource,
  urgency, hospital_ops)` (M/M/1-style base × congestion_factor ×
  staff_factor + reporting time, with hard caps at
  `DELAY_MAX_DELAY_ROUTINE_MIN` / `DELAY_MAX_DELAY_STAT_MIN`),
  `add_to_queue` / `release_from_queue` (per-order utilisation
  bookkeeping), `load_hospital_operations()` YAML loader for the
  default config.
- **Out of scope**: staff *identities* / rostering
  ([`clinosim.modules.staff`](../staff/README.md)), cross-hospital /
  regional organisation
  ([`clinosim.modules.healthcare_system`](../healthcare_system/README.md)),
  device inventory
  ([`clinosim.modules.device`](../device/README.md)), FHIR
  `Organization` / `Location` serialisation
  ([`clinosim.modules.output`](../output/README.md)), department /
  ward definitions (data-only YAML under
  [`clinosim/config/hospital_operations.yaml`](../../config/hospital_operations.yaml)).

## Public API

`__init__.py` is empty; consumers import the two symbols directly
from `hospital_state`:

```python
from clinosim.modules.facility.hospital_state import (
    HospitalState,               # dataclass — queue / occupancy / staff / helpers
    load_hospital_operations,    # () -> dict (cached load of clinosim/config/hospital_operations.yaml)
)
```

`HospitalState` methods:

| Method | Contract |
|---|---|
| `update_for_time(dt, hospital_ops)` | Sets shift-based staffing (`day` / `evening` / `night`), applies weekend modifier when `weekday >= WEEKEND_WEEKDAY_MIN`, then applies each `daily_patterns.*` YAML entry whose `hours` window and `weekday` filter match. |
| `calculate_delay(resource, urgency, hospital_ops)` | Returns delay in minutes for the given resource + urgency using `base × (1 / (1 - utilization)) × (1 / staff) + reporting_time × (1 / staff)`, with congestion + staff factors clamped by `DELAY_CONGESTION_CAP` + `DELAY_STAFF_CAP`, and the whole answer capped by `DELAY_MAX_DELAY_{STAT,ROUTINE}_MIN`. |
| `add_to_queue(resource, hospital_ops)` | Bumps `<resource>_queue` by `1/capacity` for that resource. |
| `release_from_queue(resource, hospital_ops)` | Drops `<resource>_queue` by `1/capacity`. |

## Determinism

Not applicable — `HospitalState` is a deterministic
resource-contention model. It uses no `np.random.Generator`,
`derive_sub_seed`, or `ENRICHER_SEED_OFFSETS` entry. `calculate_delay`
is a pure function of `(state, resource, urgency, hospital_ops)`;
`add_to_queue` / `release_from_queue` mutate `HospitalState`
deterministically. Byte-identity at a pinned seed is guaranteed as
long as call ordering is preserved (see `_hospital_state_thresholds.py`
docstring for the byte-diff contract).

## Dependencies

- `clinosim.modules.facility._hospital_state_thresholds` — every
  clamp, cap, fallback, and shift-boundary constant.
- `yaml` — YAML parser for the default hospital-operations file.
- **`_UNSET_DATETIME = datetime(1970, 1, 1)`** — sentinel default for
  `HospitalState.timestamp` (see `clinosim/types/clinical.py` for the
  determinism-chain rationale, 2026-07-04).
- No dependency on any other `clinosim.modules.*`.

## Constants and configuration

- Threshold table: [`_hospital_state_thresholds.py`](_hospital_state_thresholds.py)
  — every scalar the state model uses, lifted from inline literals
  per policy §5. Two clusters:
  - **Shift and schedule**: `SHIFT_DAY_START_HOUR`,
    `SHIFT_DAY_END_HOUR_EXCLUSIVE`, `SHIFT_EVENING_START_HOUR`,
    `WEEKEND_WEEKDAY_MIN`, `FALLBACK_WEEKEND_MODIFIER`, plus
    per-role staff fallbacks (`FALLBACK_{LAB,RADIOLOGY,NURSING,PHARMACY,OR}_STAFF`).
  - **Queueing / delay**: `DELAY_MAX_DELAY_ROUTINE_MIN`,
    `DELAY_MAX_DELAY_STAT_MIN`, `DELAY_CONGESTION_CAP`,
    `DELAY_CONGESTION_UTILIZATION_FLOOR`,
    `DELAY_QUEUE_UTILIZATION_CEILING`,
    `DELAY_QUEUE_UTILIZATION_FLOOR`, `DELAY_STAFF_CAP`,
    `DELAY_STAFF_FLOOR`, plus YAML fallbacks
    (`FALLBACK_BASE_{STAT,ROUTINE}_MIN`,
    `FALLBACK_REPORTING_{STAT,ROUTINE}_MIN`,
    `FALLBACK_QUEUE_UTILIZATION`, `FALLBACK_RESOURCE_CAPACITY`).
- Runtime YAML: [`clinosim/config/hospital_operations.yaml`](../../config/hospital_operations.yaml)
  (or the size variants `hospital_small.yaml` /
  `hospital_large.yaml` loaded via the CLI
  `--hospital-config PATH` argument). Sections consumed:
  - `staffing.{day, evening, night}.*` — per-shift staff levels;
    `weekend_modifier` for Sat / Sun scaling.
  - `daily_patterns.<name>` — `hours: [start, end]` (wrap-safe),
    optional `weekday`, and any of `lab_queue_delta`, `ct_queue_delta`,
    `mri_queue_delta`, `xray_queue_delta`, `bed_occupancy_delta`,
    `ed_crowding_delta`.
  - `base_processing_time.<resource>[_stat|_routine]` — base minutes
    per order (falls back to `FALLBACK_BASE_{STAT,ROUTINE}_MIN`).
  - `reporting_time.{stat, routine}` — imaging reporting minutes.
  - `resource_capacity.{lab_analyzers, ct_scanners, mri_scanners,
    xray_rooms, ultrasound_rooms, operating_rooms}` — capacity
    integers used by `add_to_queue` / `release_from_queue`.
- `load_hospital_operations()` is `@lru_cache(maxsize=1)`; the
  returned dict is treated as read-only. The CLI's custom
  `--hospital-config PATH` path loads a fresh dict directly and is
  intentionally unaffected by this cache.

## Directory contents

```
clinosim/modules/facility/
  __init__.py                     empty
  hospital_state.py               HospitalState + load_hospital_operations
  _hospital_state_thresholds.py   named threshold constants (shift + queueing)
  SPEC.md                         extended design reference (per-department layout — not runtime)
```

The module has **no `engine.py`, no `enricher.py`, no `audit.py`, no
`reference_data/`**.

## Enricher wiring

Not applicable — this module is a data model + loader, not an
enricher. It is not registered with `register_builtin_enrichers` and
has no seed offset in `ENRICHER_SEED_OFFSETS`. The simulator boot
path constructs a `HospitalState` once and passes it (and the
`hospital_ops` dict) to every clinical event that needs a delay
computed.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Simulator boot | [`clinosim/simulator/engine.py`](../../simulator/engine.py) (`~L191`) | Loads `hospital_ops` (either from `--hospital-config PATH` or from `load_hospital_operations()`) and constructs a per-run `HospitalState`. |
| Discrete-event scheduler | [`clinosim/simulator/des_engine.py`](../../simulator/des_engine.py) (`~L21`) | Uses `HospitalState.calculate_delay` to timestamp lab / imaging / OR results. |
| Order queue-replay test | [`tests/unit/test_order_queue_replay.py`](../../../tests/unit/test_order_queue_replay.py) | Loads `HospitalState` + `load_hospital_operations()` to replay queue add / release semantics. |
| Wall-clock sentinel test | [`tests/unit/test_wallclock_sentinel_defaults.py`](../../../tests/unit/test_wallclock_sentinel_defaults.py) | Asserts the `_UNSET_DATETIME` sentinel default. |

## Testing

```bash
pytest tests/unit -k "facility or hospital_state or order_queue_replay" -q
```

Individual files:

- [`tests/unit/test_facility_ecs_organization.py`](../../../tests/unit/test_facility_ecs_organization.py)
  — JP-CLINS unified `hospital-main` Organization (JP_Organization +
  JP_Organization_eCS profiles on one resource, Issue #746). Anchors
  the FHIR Organization emission that reads the facility identity.
- [`tests/unit/test_order_queue_replay.py`](../../../tests/unit/test_order_queue_replay.py)
  — queue add / release invariants.
- [`tests/unit/test_wallclock_sentinel_defaults.py`](../../../tests/unit/test_wallclock_sentinel_defaults.py)
  — sentinel-default behaviour for `HospitalState.timestamp`.

Coverage gap: `calculate_delay` and `update_for_time` have no direct
unit test today; they are exercised transitively via the DES engine
tests. A focused test for the delay formula (base × congestion ×
staff + reporting; caps; per-resource capacity dispatch) would be a
low-cost follow-up.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
