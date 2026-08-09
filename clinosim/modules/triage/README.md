# `clinosim.modules.triage` — ED triage assignment

## Purpose

Always-on Module (AD-55, Tier 1 #3, POST_ENCOUNTER order 93) that
assigns an ED triage level, arrival mode, and acuity score to every ED
encounter and writes them to `EncounterRecord.triage_data`.

Country-appropriate levels: **JTAS** (Japan Triage and Acuity Scale)
for JP, **ESI** (Emergency Severity Index) for US.

## Scope

- **In scope**: JTAS 1-5 / ESI 1-5 assignment based on presenting
  complaint + physiology state, arrival-mode sampling (walk-in / EMS
  / private transport), acuity-score derivation for triage-response
  narrative.
- **Out of scope**: ED disposition decisions (in
  [`clinosim/simulator/emergency.py`](../../simulator/README.md)),
  triage-nurse identity (in
  [`clinosim/modules/staff/`](../staff/README.md)), FHIR
  `RiskAssessment` serialisation (in
  [`clinosim/modules/output/`](../output/README.md)).

## Public API

```python
from clinosim.modules.triage import (
    assign_triage,               # (encounter, protocol, patient, rng) -> TriageData
    enrich_triage,               # AD-56 post_records enricher entry
)
```

## Dependencies

- `clinosim.types.triage` — `TriageData`, `TriageLevel`.
- `clinosim.types.encounter` — `Encounter`, `EncounterType.EMERGENCY`.
- `clinosim.modules.encounter` — ED encounter protocol reference data
  (`common_triage_levels`).

## Constants and configuration

- Level distributions and arrival-mode probabilities live inline in
  `engine.py` and are flagged for extraction in
  [`docs/reviews/2026-08-09-constants-audit.md`](../../../docs/reviews/2026-08-09-constants-audit.md).
- Country dispatches on `SimulatorConfig.country`.

## Directory contents

```
clinosim/modules/triage/
  __init__.py           public API
  engine.py             triage assignment logic
  enricher.py           AD-56 post_records enricher (enrich_triage)
  audit.py              per-module audit spec
```

## Testing

```bash
pytest tests/unit -k triage -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
