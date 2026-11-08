# `clinosim.modules.triage` — ED triage sampling (JTAS / ESI)

## Purpose

Tier 1 #3 α-min-2 always-on AD-55 Module. On every ED (emergency)
encounter, samples a triage level (JTAS in JP / ESI in US) and an
arrival mode (walk-in / ambulance / private_vehicle / police /
helicopter), then writes the result to `Encounter.triage_data`
(`acuity_score` is left `None`). The level follows ESI v4 (Issue
#2864), and JTAS levels follow the same rule:

1. The severity draw is restricted to the ED condition's bounds —
   the range of `narrative.ed_triage_template.common_triage_levels`,
   narrowed by `triage_level_min` / `triage_level_max`.
2. A drawn 1 or 2 stands. A drawn 3–5 becomes the resource level
   (decision point C): ≥ 2 resource types → 3, 1 → 4, 0 → 5. The
   types are labs (any number), imaging (incl. ECG), parenteral
   treatment (IV fluids, IV / IM / nebulized medications) and
   procedures (except the simple ones in `resource_rule`), counted
   from the visit's orders.
3. A treatment listed in `ed_triage_template.high_risk_orders` (IM
   epinephrine for anaphylaxis, empiric aspirin for possible ACS)
   makes the level 2 at most (decision point B).
4. The result is clamped into the bounds; then the arrival-vitals cap
   (`triage_level_cap`, Issue #2082) applies and may go below them.

Non-emergency encounters are a no-op.

## Scope

- **In scope**: `triage_enricher` (POST_ENCOUNTER order=93,
  ED-only); `pick_triage_level(severity, level_system, rng)` —
  YAML weight table by severity (shared by JTAS and ESI), restricted
  to the condition bounds;
  `pick_arrival_mode(severity, rng)`; `condition_triage_bounds(record)`;
  `resource_count(orders)` / `resource_level(orders)`;
  `has_high_risk_order(record, orders)`; `triage_level(record, enc, drawn)`;
  `triage_level_cap(vitals)`;
  `load_triage_protocols()` YAML loader validated by the
  `TriageProtocols` Pydantic model (silent-no-op defense).
- **Out of scope**: encounter routing / class emission (in
  [`clinosim.modules.encounter`](../encounter/README.md)), FHIR
  `Encounter.class` / `type` / `priority` emission (in
  [`clinosim.modules.output`](../output/README.md)), ED narrative
  document ([`clinosim.modules.document.narrative`](../document/narrative/README.md)
  — the ED_TRIAGE_NOTE stub is emitted by the
  [`document`](../document/README.md) module in a later
  POST_ENCOUNTER pass).

## Public API

```python
from clinosim.modules.triage import TriageData
from clinosim.modules.triage.engine import (
    triage_enricher,             # POST_ENCOUNTER enricher entry
    pick_triage_level,           # (severity, level_system, rng, bounds=(1, 5)) -> str
    pick_arrival_mode,           # (severity, rng) -> str
    condition_triage_bounds,     # (record) -> (most, least) urgent level
    resource_count,              # (orders) -> distinct ESI resource types
    resource_level,              # (orders) -> 3 / 4 / 5
    has_high_risk_order,         # (record, orders) -> bool
    triage_level,                # (record, enc, drawn) -> final level
    triage_level_cap,            # (vitals) -> least-urgent level allowed
    load_triage_protocols,       # () -> dict (@lru_cache, TriageProtocols-validated)
)
```

## Determinism

- Sub-seed offset `0x5452` (`"TR"`, Tier 1 #3 α-min-2 PR1) —
  registered in [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["triage"]`.
- Per-encounter RNG:
  `derive_sub_seed(master_seed, offset, encounter_id)` — main
  patient RNG untouched (AD-16).
- Two draws per encounter (level, then arrival mode). The bounds
  change which level the level draw maps to, not the number of draws,
  so the arrival mode is unchanged by them (Issue #2864).

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`, `is_jp`,
  `normalize_probabilities`.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.types.triage` — `TriageData`.
- `clinosim.modules.encounter.protocol` — `load_all_encounter_conditions`
  (per-condition `triage_level_min` / `triage_level_max`,
  `narrative.ed_triage_template.common_triage_levels` /
  `high_risk_orders`).
- `yaml`, `numpy`.

## Constants and configuration

- [`reference_data/triage_protocols.yaml`](reference_data/triage_protocols.yaml)
  — `triage_systems` (JTAS / ESI level labels), `arrival_modes`,
  country-independent `severity_to_triage_distribution`,
  `arrival_mode_base_distribution`,
  `arrival_mode_severity_multipliers` and the ESI v4 `resource_rule`
  (`level_by_count`, `parenteral_routes`, `non_resource_procedures`). The `TriageProtocols` model
  (run by the first `load_triage_protocols()` call) checks: non-empty
  top level / `triage_systems` is exactly JTAS+ESI / each system has
  levels 1-5 / `arrival_modes` matches `SUPPORTED_ARRIVAL_MODES` /
  severity keys match and each distribution sums to ~1.0 /
  base arrival-mode keys match / `resource_rule.level_by_count` is
  three levels in 3–5. The encounter protocol model checks that
  `common_triage_levels` are `"1"`–`"5"` and that every
  `high_risk_orders` entry names a treatment of the condition and has
  a level of 1 or 2 to reach.
- Level systems: `JTAS` (JP), `ESI` (US), chosen from
  `ctx.config.country` (fallback `ctx.country`).
- Vitals cap thresholds (`engine.py` constants, ESI v4 danger zone):
  HR > 100, RR > 20, SpO2 < 92, pain ≥ 7 → level ≤ 3; AVPU P,
  SpO2 < 90 or SBP < 90 → level ≤ 2; AVPU U → level 1.

## Directory contents

```
clinosim/modules/triage/
  __init__.py                        re-exports TriageData
  engine.py                          triage_enricher + pick_* helpers + loader + TriageProtocols model
  audit.py                           AD-60 audit plug-in (triage-tier canonical constants + firing proof)
  reference_data/
    triage_protocols.yaml            per (system × severity) tier + arrival weights
```

The module has **no `enricher.py`** — the enricher entry point lives
in `engine.py` and is registered directly.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`register_builtin_enrichers`):

- `name="triage"`, `stage=POST_ENCOUNTER`, `order=93`,
  `enabled=lambda c: True`.
- Runs before `nursing_assignment` (order=94) and `document`
  (order=95). ED-only inside the enricher body (non-ED encounters
  are skipped).
- The `audit.py` module registers with the AD-60 audit framework at
  import time (`register_audit_module`).

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) (`register_builtin_enrichers`) | POST_ENCOUNTER order=93 registration. |
| Audit registry | [`clinosim/modules/triage/audit.py`](audit.py) | AD-60 audit plug-in — canonical-constants cross-check + firing proof. |
| Document module audit | [`clinosim/modules/document/audit.py`](../document/audit.py) | Delegates its triage-level proof to `_build_triage_severity_proof`. |
| ED narrative renderers | [`clinosim/modules/document/narrative/renderers/`](../document/narrative/renderers/) | `ed_triage_note.py`, `_ed_helpers.py`, `section_builders/ed_note.py` read `encounter.triage_data`. |

## Testing

```bash
pytest tests/unit -k triage -q
clinosim audit run -d <cohort_dir> --module triage
```

Individual files:

- [`tests/unit/modules/triage/test_engine.py`](../../../tests/unit/modules/triage/test_engine.py)
  — enricher gate, sampling determinism, ED-only behaviour.
- [`tests/unit/modules/triage/test_triage_protocols_yaml.py`](../../../tests/unit/modules/triage/test_triage_protocols_yaml.py)
  — `TriageProtocols` validator coverage.
- [`tests/unit/modules/triage/test_esi_bounds_2864.py`](../../../tests/unit/modules/triage/test_esi_bounds_2864.py)
  — bounded draw, resource rule, high-risk orders, vitals cap.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
