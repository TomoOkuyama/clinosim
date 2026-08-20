# `clinosim.modules.encounter` — encounter condition protocols + daily-cycle timeline

## Purpose

Owns two related concerns for inpatient / ED / outpatient encounters:

1. The **encounter-condition protocol registry** — 46 YAMLs under
   [`reference_data/`](reference_data/) covering short outpatient and
   ED conditions (asthma attack, migraine, minor laceration,
   screening visits, allergic reaction, syncope, viral gastroenteritis,
   annual health screening, dialysis session, rehab outpatient, …).
   This is the sibling registry to
   [`clinosim.modules.disease`](../disease/README.md), which owns the
   heavier admission / trauma protocols.
2. The **inpatient daily-cycle timeline** — deterministic
   admission → daily cycle → discharge event ordering for a
   single inpatient encounter, plus the deterministic hash-based
   encounter-id suffix that keeps encounter ids stable across
   cursor / snapshot boundaries.

## Scope

- **In scope**: `EncounterConditionProtocol` Pydantic schema + child
  models (`OutpatientSoapTemplate`, `EdNoteTemplate`, `EdPhysicalExam`,
  `EdTriageTemplate`, `EncounterNarrativeSpec`); per-protocol
  loader + full-registry loader (both `@lru_cache`);
  `create_inpatient_encounter` with the F1 cross-cursor stable id
  formula; `generate_daily_cycle` (per-day event skeleton at the
  Japan medium-hospital cadence — morning vitals 06:00, morning labs
  06:30, rounds 09:00, afternoon vitals 14:00, evening vitals
  18:00, evening meds 18:30, night check 22:00); and
  `generate_encounter_timeline` (admission + daily × N + discharge,
  chronologically sorted).
- **Out of scope**: inpatient / trauma / occupational-injury
  protocols ([`clinosim.modules.disease`](../disease/README.md));
  narrative rendering
  ([`clinosim.modules.document.narrative`](../document/narrative/README.md));
  encounter simulation / stateful daily loop
  ([`clinosim.simulator`](../../simulator/)); FHIR `Encounter`
  emission ([`clinosim.modules.output`](../output/README.md)).

## Public API

`__init__.py` is empty; consumers import directly from the two
submodules:

```python
from clinosim.modules.encounter.engine import (
    DailyCycleEvent,                 # dataclass (timestamp, event_type, data)
    create_inpatient_encounter,      # (patient_id, admission_datetime, chief_complaint="…", department_id="internal_medicine", visit_number=1) -> Encounter
    generate_daily_cycle,            # (encounter, day_number) -> list[DailyCycleEvent]
    generate_encounter_timeline,     # (encounter, total_days) -> list[DailyCycleEvent]
)

from clinosim.modules.encounter.protocol import (
    EncounterConditionProtocol,      # Pydantic BaseModel
    EncounterNarrativeSpec,          # narrative wrapper (α-min-2 Task 6)
    OutpatientSoapTemplate,          # SOAP note fields
    EdNoteTemplate,                  # ED physician note fields
    EdPhysicalExam,                  # ED physical exam sub-model
    EdTriageTemplate,                # ED triage sub-model
    load_encounter_condition,        # (condition_id) -> dict  (@lru_cache=64)
    load_all_encounter_conditions,   # () -> dict[condition_id, dict]  (@lru_cache=1)
)
```

## Determinism

- **Encounter IDs are hash-derived, not counter-derived** (F1 fix).
  `_encounter_id_suffix(patient_id, admission_datetime, chief_complaint,
  department_id, visit_number)` folds all five inputs into a SHA-256
  digest, takes the first 6 bytes, and mods by
  `_ENCOUNTER_SUFFIX_MODULUS = 10**12` (12 decimal digits). This is
  cursor-independent: two runs differing only in `snapshot_date`
  produce the same id for the same encounter, regardless of how many
  unrelated encounters were processed upstream. The 12-digit width
  was chosen after the earlier 6-digit width was empirically
  observed to collide within a single patient at p=500.
- Daily-cycle + timeline generation is pure: no `rng` argument, and
  the cadence hours (06:00 / 06:30 / 09:00 / 14:00 / 18:00 / 18:30 /
  22:00) are fixed.
- Protocol loaders are pure — Pydantic `extra="forbid"` catches
  drift at load time.

## Dependencies

- `pydantic` — schema + `extra="forbid"`.
- `yaml` — YAML parser.
- `clinosim.types.encounter` — `Encounter`, `EncounterStatus`,
  `EncounterType`.
- `hashlib.sha256` — encounter-id derivation.
- No dependency on any other `clinosim.modules.*`.

## Constants and configuration

- **Encounter-condition YAML registry**: [`reference_data/`](reference_data/)
  — 46 files (one per condition id; filename = condition_id +
  `.yaml`). Covers outpatient chronic follow-up, ED short-stay,
  screening (mammography / colonoscopy / diabetic retinopathy /
  annual health screening), rehab, dialysis, cardiac rehab,
  smoking-cessation, and mental-health follow-up condition classes.
  Each entry carries chief-complaint, physical-exam templates,
  narrative sections (SOAP / ED-note / triage), and clinical
  metadata.
- **Encounter-id shape** (`engine.py`):
  - `_ENCOUNTER_SUFFIX_MODULUS = 10**12` — 12-digit suffix modulus.
  - Encounter id format: `ENC-{patient_id}-{suffix:012d}`.
  - Episode id format: `EP-{patient_id}-{suffix:012d}`.
  - Disease-event id format: `DE-{patient_id}-001`.
- **Daily cycle cadence** (`generate_daily_cycle`, hard-coded):
  06:00 morning vitals · 06:30 morning labs · 09:00 rounds ·
  14:00 afternoon vitals · 18:00 evening vitals ·
  18:30 evening meds · 22:00 night check. Applies to
  "Japan, medium hospital"; other cadences would be a per-country
  extension.

## Directory contents

```
clinosim/modules/encounter/
  __init__.py                     empty
  engine.py                       inpatient encounter creation + daily-cycle timeline
  protocol.py                     EncounterConditionProtocol + child models + loaders
  reference_data/
    <condition_id>.yaml           46 files (one per outpatient / ED / screening condition)
  SPEC.md                         extended design reference (not runtime)
```

The module has **no `enricher.py`, no `audit.py`**.

## Enricher wiring

Not applicable — this module is a data + primitives layer, not an
enricher. It is not registered with `register_builtin_enrichers` and
has no seed offset in `ENRICHER_SEED_OFFSETS`. The simulator imports
what it needs directly.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Simulator boot + all encounter simulators | [`clinosim/simulator/{engine,inpatient,outpatient,emergency,unknown_condition,enumerate,cli_test_encounter,cli}.py`](../../simulator/) | Import `create_inpatient_encounter` + the condition-protocol loaders. |
| Narrative | [`clinosim/modules/document/narrative/passes.py`](../document/narrative/passes.py) | Reads `EncounterConditionProtocol.narrative` for the outpatient / ED template flow. |
| Encounter-type FHIR mapping | [`clinosim/modules/output/fhir_r4/encounters/`](../output/fhir_r4/encounters/) | Consumes the encounter class + type strings the protocol carries. |

## Testing

```bash
pytest tests/unit -k encounter -q
```

Individual files:

- [`tests/unit/test_encounter_protocol_validation.py`](../../../tests/unit/test_encounter_protocol_validation.py)
  — Pydantic schema + `extra="forbid"` guard across all 46 YAMLs.
- [`tests/unit/test_encounter_archetype_severity.py`](../../../tests/unit/test_encounter_archetype_severity.py)
  — archetype × severity coverage.
- [`tests/unit/test_encounter_features.py`](../../../tests/unit/test_encounter_features.py)
  — expected feature keys per condition.
- [`tests/unit/test_cli_test_encounter_format.py`](../../../tests/unit/test_cli_test_encounter_format.py)
  — CLI encounter-id format guard (F1 stability).
- [`tests/unit/output/test_fhir_encounter_*`](../../../tests/unit/output/)
  — FHIR-side integration guards (encounter reason code JP, ED
  delegation, type codes YAML).
- [`tests/unit/modules/encounter/`](../../../tests/unit/modules/encounter/)
  — module-scoped unit tests.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
