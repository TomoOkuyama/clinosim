# `clinosim.modules.procedure` — surgical + bedside procedure and rehab generation

## Purpose

Owns per-encounter procedure emission for three families:

1. **Surgical procedures** (`simulate_surgery`) — called by
   `simulator/inpatient.py` when the disease protocol sets
   `requires_surgery`, reading the protocol's `procedure` block:
   returns `(ProcedureRecord, state_impacts)` with time to surgery,
   duration, EBL, anesthesia type, ASA class, intra-op complications
   mapped to SNOMED, and a SNOMED outcome code; `state_impacts` are
   physiology deltas the caller applies.
2. **Bedside procedures** (`generate_bedside_procedures`) —
   disease/condition-matched procedures from `_PROCEDURE_RULES`
   (e.g. urinary catheter, central / arterial line, LP,
   thoracentesis, paracentesis, NG tube, chest tube, cardioversion,
   transfusion, acute dialysis, ECG, IV line, splint / closed
   reduction, wound care, oxygen therapy) with severity-scaled base
   probability + sampled post-admission time offset. A separate
   `_ISSUE939_PROCEDURE_RULES` table (PCI, pacemaker, craniotomy,
   ileus tube, bowel resection; Issue #939) draws from its own
   per-(encounter, procedure) sub-RNG.
3. **Post-op rehabilitation** (`generate_rehab_sessions`) — daily
   PT schedule from post-op day 1 through discharge, with
   early / mid / late phase activities, a pain model, skip-day and
   refusal probabilities.
4. **Intubation** (`build_intubation_procedure`, Issue #2091) —
   deterministic intubation `ProcedureRecord` built by
   `simulator/daily_loop.py` when the state crosses the airway
   threshold.

Every scalar the engines consumed used to sit inline; the
three companion `_*_thresholds.py` files (Issue #637 sweep) lift
every one with a clinical citation.

## Scope

- **In scope**: `simulate_surgery` (returns `ProcedureRecord` +
  state impacts); `generate_bedside_procedures`
  (severity-scaled probability + time-offset sampling);
  `generate_rehab_sessions` (`RehabSession` list from day 1 to
  discharge); `build_intubation_procedure`; `_derive_outcome`,
  `_map_complications` (internal helpers surfaced for tests);
  `ProcedureMeta` (per-procedure SNOMED category + body site).
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
  JP code `M001-2` (3D-CRT) on ~40 % of follow-up visits whose
  `locale/shared/chronic_followup.yaml` entry sets
  `radiation_therapy_eligible: true` (Issue #957). Emitted inline by
  [`clinosim/simulator/outpatient.py`](../../simulator/outpatient.py)
  with an encounter-hashed RNG; not routed through `simulate_surgery`
  either.

Both retain the canonical `ProcedureRecord` fields so the FHIR
adapter ([`output/fhir_r4/procedures/`](../output/fhir_r4/procedures/README.md))
can emit them without a new resource-type builder.

## Public API

```python
from clinosim.modules.procedure import (
    ProcedureRecord,             # dataclass (from types.procedure, re-exported)
    RehabSession,                # dataclass (from types.procedure, re-exported)
    simulate_surgery,            # (patient, disease_id, encounter_id, admission_time, protocol, rng,
                                 #  country="JP", surgeon_id="", anesthesiologist_id="", operating_rooms=2)
                                 #  -> (ProcedureRecord, dict[str, float])
    generate_bedside_procedures, # (patient_id, encounter_id, disease_id, admission_time, severity, rng,
                                 #  country="US") -> list[ProcedureRecord]
    generate_rehab_sessions,     # (patient_id, encounter_id, surgery_date, total_days, rng,
                                 #  country="JP") -> list[RehabSession]
)
from clinosim.modules.procedure.engine import (
    build_intubation_procedure,  # (patient_id, encounter_id, start, country, procedure_id) -> ProcedureRecord
)
```

Internal `ProcedureMeta` in `engine.py` carries the per-procedure
SNOMED `category_code` + `body_site_code`, loaded (with the outcome
and complication SNOMED codes) from
[`clinosim/codes/data/procedure-snomed-metadata.yaml`](../../codes/data/procedure-snomed-metadata.yaml).
CPT / K-code / names / anesthesia per bedside procedure live in the
`_BEDSIDE_PROCEDURES` table in `engine.py`.

## Determinism

- No sub-seed offset in `ENRICHER_SEED_OFFSETS`. Every entry point
  is pure with respect to the `rng` argument the caller passes.
- Exception: the `_ISSUE939_PROCEDURE_RULES` loop in
  `generate_bedside_procedures` draws from
  `determinism.default_rng(seeding.issue939_procedure_seed(encounter_id,
  proc_type))`, so those procedures never shift the caller's stream.
- Complication sampling uses `rng.random()` gated by
  `_surgery_thresholds` probabilities; outcome derivation is a
  deterministic mapping from the sampled complication list (none →
  success, otherwise partial).

## Dependencies

- `clinosim.modules._shared` — `is_jp`.
- `clinosim.determinism` + `clinosim.seeding.issue939_procedure_seed`
  — isolated sub-RNG for the Issue #939 rules.
- `clinosim.modules.procedure._bedside_thresholds` — bedside
  procedure probabilities + time-offset ranges (Issue #637).
- `clinosim.modules.procedure._rehab_thresholds` — session
  duration, phase cutoffs, pain-model params, modality
  probabilities (Issue #637).
- `clinosim.modules.procedure._surgery_thresholds` — surgery
  timing, duration / EBL defaults, ASA, intra-op complication and
  state-impact constants (Issue #637).
- `clinosim.modules.disease.acuity` — `NEURO_LOC_MONITORING_DISEASES`
  (disease list for one `_PROCEDURE_RULES` entry).
- `clinosim.types.procedure` — `ProcedureRecord`, `RehabSession`.
- `numpy`, `yaml`.

## Constants and configuration

- **Bedside thresholds** ([`_bedside_thresholds.py`](_bedside_thresholds.py),
  Issue #637): severity multipliers for probability scaling,
  post-admission hour-offset (floor + exponential mean), and
  duration (floor / mean / SD). Per-procedure base probabilities sit
  in `_PROCEDURE_RULES` / `_ISSUE939_PROCEDURE_RULES` in `engine.py`.
- **Rehab thresholds** ([`_rehab_thresholds.py`](_rehab_thresholds.py),
  Issue #637): start POD, session hour, JP / US session duration,
  skip-day probability, phase cutoffs (early ≤ POD 3 / mid ≤ POD 14 /
  late), pain model (base, per-POD decay, SD, clamp), participation /
  refusal thresholds.
- **Surgery thresholds** ([`_surgery_thresholds.py`](_surgery_thresholds.py),
  Issue #637): JP / US time-to-surgery mean / SD / floor, default
  duration and EBL (overridden by the protocol `procedure` block),
  spinal-anesthesia probability, ASA class thresholds, intra-op
  complication probabilities, hip-fracture procedure split,
  post-op state-impact deltas.
- **No `reference_data/`** — the module reads the disease protocol
  passed in and the SNOMED metadata yaml under `clinosim/codes/data/`.

## Directory contents

```
clinosim/modules/procedure/
  __init__.py                        re-exports 5 symbols
  engine.py                          simulate_surgery + generate_bedside_procedures + generate_rehab_sessions + build_intubation_procedure
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
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | Once per admission: `simulate_surgery` + `generate_rehab_sessions` when `protocol.requires_surgery`, then `generate_bedside_procedures`. |
| Emergency encounter | [`clinosim/simulator/emergency.py`](../../simulator/emergency.py) | Calls `generate_bedside_procedures` for ED bedside acts. |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) | Calls `build_intubation_procedure` when the airway threshold is crossed. |
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
