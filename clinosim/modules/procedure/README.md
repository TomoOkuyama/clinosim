# `clinosim.modules.procedure` — surgical + bedside procedure and rehab generation

## Purpose

Owns per-encounter procedure emission for three families:

1. **Surgical procedures** (`simulate_surgery`) — driven by disease
   YAML `surgery` block or emergency-encounter `surgery` field:
   composes a `ProcedureRecord` with duration, intra-op
   complications, physiology impact (state deltas over the
   post-op window), and the resulting `outcome` string.
2. **Bedside procedures** (`generate_bedside_procedures`) —
   rule-matched routine inpatient procedures (central line, arterial
   line, thoracentesis, paracentesis, LP, foley placement, NG tube,
   dressing changes) with severity-scaled base probability +
   sampled post-admission time offset.
3. **Post-op rehabilitation** (`generate_rehab_sessions`) — daily
   PT schedule from post-op day 1 through discharge, with phase
   cutoffs, pain-model parameters, and modality allocation.

Every scalar the three engines consumed used to sit inline; the
three companion `_*_thresholds.py` files (Issue #637 sweep) lift
every one with a clinical citation.

## Scope

- **In scope**: `simulate_surgery` (returns `ProcedureRecord` with
  intra-op complications + state impact); `generate_bedside_procedures`
  (severity-scaled probability + time-offset sampling);
  `generate_rehab_sessions` (`RehabSession` list from day 1 to
  discharge); `_derive_outcome`, `_map_complications` (internal
  helpers surfaced for tests); `ProcedureMeta` (per-procedure
  metadata dataclass).
- **Out of scope**: procedure-code YAMLs
  ([`clinosim.codes`](../../codes/)), procedure encounter timeline
  ([`clinosim.modules.encounter`](../encounter/README.md)), FHIR
  `Procedure` emission
  ([`clinosim.modules.output.fhir_r4.procedures`](../output/fhir_r4/procedures/README.md)),
  imaging-order construction — that is
  [`clinosim.modules.imaging`](../imaging/README.md).

### Longitudinal service-line Procedures (v0.5 → v0.6.0)

Two additional Procedure surfaces sit alongside the surgical /
bedside / rehab trio above and reach FHIR via the same
`ProcedureRecord` shape:

- **Delivery Procedure** — attached to every mother-side perinatal
  delivery Encounter (see
  [`clinosim.modules.encounter`](../encounter/README.md)). Code:
  JP `K894` (経腟分娩 — MHLW 診療報酬点数表 K-code) or US CPT
  `59400` (routine obstetric care incl. vaginal delivery). Emitted
  by [`clinosim/simulator/perinatal.py`](../../simulator/perinatal.py)
  with the shape coming from
  [`clinosim/locale/shared/perinatal.yaml`](../../locale/shared/perinatal.yaml)
  `procedure` block; not routed through `simulate_surgery`.
- **Radiation-therapy Procedure** — attached to radiation
  encounters in the oncology service line; the Procedure carries
  the modality, dose, and site from the disease-YAML radiation
  block. Emitted via a dedicated builder (session 93 landing);
  not routed through `simulate_surgery` either.

Both retain the canonical `ProcedureRecord` fields so the FHIR
adapter ([`output/fhir_r4/procedures/`](../output/fhir_r4/procedures/README.md))
can emit them without a new resource-type builder.

## Public API

```python
from clinosim.modules.procedure import (
    ProcedureRecord,             # dataclass (from types.encounter, re-exported)
    RehabSession,                # dataclass
    simulate_surgery,            # (patient, encounter, protocol, rng, ...) -> ProcedureRecord
    generate_bedside_procedures, # (patient, encounter, protocol, rng, ...) -> list[ProcedureRecord]
    generate_rehab_sessions,     # (patient, encounter, ...) -> list[RehabSession]
)
```

Internal `ProcedureMeta` in `engine.py` carries per-procedure
metadata (code, display, duration distribution, common
complications, expected outcome map) — the tables it populates are
the data behind every `simulate_*` / `generate_*` call.

## Determinism

- No sub-seed offset in `ENRICHER_SEED_OFFSETS`. Every entry point
  is pure with respect to the `rng` argument the caller passes; the
  encounter simulators (`inpatient.py`, `emergency.py`) derive a
  per-encounter sub-RNG before calling.
- Complication sampling uses `rng.random()` gated by
  `_bedside_thresholds` / `_surgery_thresholds` probabilities;
  outcome derivation is a deterministic mapping from the sampled
  complication list.

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`, `is_jp`,
  `is_us`.
- `clinosim.modules.procedure._bedside_thresholds` — bedside
  procedure probabilities + time-offset ranges (Issue #637).
- `clinosim.modules.procedure._rehab_thresholds` — session
  duration, phase cutoffs, pain-model params, modality
  probabilities (Issue #637).
- `clinosim.modules.procedure._surgery_thresholds` — surgery
  timing, duration distributions, per-procedure state-impact
  deltas (Issue #637).
- `clinosim.modules.disease.acuity` — `EMERGENCY_PRIORITY_DISEASES`,
  `CRITICAL_MONITORING_DISEASES` (via cross-reference for
  emergency-only bedside procedures).
- `clinosim.types.encounter` — `ProcedureRecord`, plus the
  encounter / physiology-state types the engines mutate.
- `numpy` — `np.random.Generator`.

## Constants and configuration

- **Bedside thresholds** ([`_bedside_thresholds.py`](_bedside_thresholds.py),
  Issue #637): per-procedure base probability, severity multiplier
  for probability scaling, time-offset sampling range (minutes /
  hours after admission), gate constants.
- **Rehab thresholds** ([`_rehab_thresholds.py`](_rehab_thresholds.py),
  Issue #637): daily session duration distribution, phase cutoffs
  (acute / subacute / discharge-prep), pain-model beta parameters,
  modality allocation probabilities.
- **Surgery thresholds** ([`_surgery_thresholds.py`](_surgery_thresholds.py),
  Issue #637): OR-scheduling offset, duration mean / SD per
  procedure family, intra-op complication probabilities, post-op
  state-impact deltas.
- **No `reference_data/`** — the module reads disease YAMLs
  directly (via the protocol object passed in) and does not
  duplicate per-procedure catalogs.

## Directory contents

```
clinosim/modules/procedure/
  __init__.py                        re-exports 5 symbols
  engine.py                          simulate_surgery + generate_bedside_procedures + generate_rehab_sessions
  _bedside_thresholds.py             bedside proc probability + timing (Issue #637)
  _rehab_thresholds.py               rehab session shape + pain model (Issue #637)
  _surgery_thresholds.py             surgery timing / duration / state-impact (Issue #637)
  SPEC.md                            extended design reference (not runtime)
```

The module has **no `enricher.py`, no `audit.py`, no
`reference_data/`**.

## Enricher wiring

Not applicable — this module is imperatively invoked by the
encounter simulators, not registered with
`register_builtin_enrichers`. It has no seed offset in
`ENRICHER_SEED_OFFSETS`.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | Calls `simulate_surgery`, `generate_bedside_procedures`, `generate_rehab_sessions` per admission day. |
| Emergency encounter | [`clinosim/simulator/emergency.py`](../../simulator/emergency.py) | Calls `simulate_surgery` for ED-to-OR paths + `generate_bedside_procedures` for ED bedside acts. |
| FHIR Procedure builder | [`clinosim/modules/output/fhir_r4/procedures/`](../output/fhir_r4/procedures/) | Reads `ProcedureRecord` (+ oxygen-therapy performedPeriod) to emit FHIR `Procedure`. |

## Testing

```bash
pytest tests/unit -k "procedure or oxygen_therapy_procedure" -q
```

Individual files:

- [`tests/unit/test_procedure_types.py`](../../../tests/unit/test_procedure_types.py)
  — dataclass shape.
- [`tests/unit/test_procedure.py`](../../../tests/unit/test_procedure.py)
  — `simulate_surgery` + bedside + rehab behaviour.
- [`tests/unit/test_procedure_fhir_fields.py`](../../../tests/unit/test_procedure_fhir_fields.py)
  — FHIR field consistency guard.
- [`tests/integration/test_escalation_procedure_emission.py`](../../../tests/integration/test_escalation_procedure_emission.py)
  — escalation-driven procedure emission end-to-end.
- [`tests/unit/output/test_fhir_procedure_jp_text.py`](../../../tests/unit/output/test_fhir_procedure_jp_text.py)
  — JP display text guard.
- [`tests/unit/output/test_fhir_oxygen_therapy_procedure.py`](../../../tests/unit/output/test_fhir_oxygen_therapy_procedure.py)
  — oxygen-therapy `performedPeriod` derived from vitals flags
  (Issue #796).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
