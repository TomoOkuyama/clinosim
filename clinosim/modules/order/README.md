# `clinosim.modules.order` — order engine

## Purpose

Expands abstract order descriptions from a disease protocol YAML into
concrete `Order` instances, and computes the time at which each order's
result becomes available. Handles labs, imaging, medications, supportive
orders, and non-drug care-plan / therapy orders.

## Scope

- **In scope**: order placement from disease-protocol admission /
  daily-monitoring / drug blocks, result-timing computation for labs
  and imaging, panel-aware Order generation, medication-order
  enrichment (dose / route / frequency / duration), country-aware
  (JP / US) frequency and drug selection.
- **Out of scope**: result *values* (in
  [`clinosim/modules/observation/`](../observation/README.md)),
  medication *administration* record generation (in
  [`clinosim/simulator/medication_pipeline.py`](../../simulator/README.md)),
  FHIR serialisation (in [`clinosim/modules/output/`](../output/README.md)).

## Public API

```python
from clinosim.modules.order import (
    place_orders,                    # (protocol, encounter, rng, ...) -> list[Order]
    enrich_medication_order,         # (order, drug_spec, ...) -> Order
    calculate_lab_result_time,       # legacy: urgency + time + weekday model
    calculate_imaging_result_time,   # legacy: urgency + time + weekday model
    calculate_result_time_from_state, # hospital-state-aware model
    classify_lab_specs,              # panel-aware Order grouping (PR1)
)
```

## Dependencies

- `clinosim.types.encounter` — `Order`, `OrderType`, `OrderStatus`.
- `clinosim.types.clinical` — physiological state for state-aware timing.
- `clinosim.simulator.helpers` — RNG derivation.
- `clinosim.modules.observation` (indirect) — for result timing consumers.
- No dependency on `clinosim.modules.output` (one-way boundary).

## Constants and configuration

- Result-timing constants (urgency multipliers, night / weekend delays,
  hospital-state queue thresholds) are currently inline in `engine.py`
  and are flagged for extraction in
  [`docs/reviews/2026-08-09-constants-audit.md`](../../../docs/reviews/2026-08-09-constants-audit.md).
- Panel canonical mapping lives at
  `reference_data/lab_panel_groups.yaml`.
- Country-aware behaviour dispatches on the `country` field of
  `SimulatorConfig`; no separate config file.

## Directory contents

```
clinosim/modules/order/
  __init__.py               public API
  engine.py                 order placement + result timing (~460 LOC)
  panel_grouping.py         panel-aware Order generation
  reference_data/
    lab_panel_groups.yaml   panel → member tests canonical mapping
```

## Design principles

- **Protocol is the source of truth** — order content is expanded from
  the disease YAML `order_protocols.admission_orders` /
  `.daily_monitoring` / `drugs` blocks.
- **Fallback chain** — diseases with no `order_protocols` fall back to
  `expected_lab_distributions` and `drugs`.
- **Idempotent enrichment** — `enrich_medication_order` is safe to call
  repeatedly; already-populated fields are not overwritten.
- **Deterministic RNG (AD-16)** — every stochastic step receives a
  `numpy.random.Generator` sub-seeded from the caller.
- **Night / weekend awareness** — non-stat orders placed 22:00 – 06:00
  are deferred to the next morning; weekends slow lab / imaging.

## Testing

```bash
pytest tests/unit -k order -q
pytest tests/integration -k order -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
