# triage module

## 役割

Tier 1 #3 α-min-2 always-on Module(AD-55、POST_ENCOUNTER order=93)。
ED encounter で JTAS(JP)/ ESI(US)level + arrival_mode + acuity_score を
sampling、`EncounterRecord.triage_data` に populate。

## Dependencies

- `clinosim/types/triage.py` — `TriageData` dataclass
- `clinosim/simulator/seeding.py` — `ENRICHER_SEED_OFFSETS["triage"] = 0x5452`
- `clinosim/modules/_shared.py` — `normalize_probabilities`

## Reference data

- `reference_data/triage_protocols.yaml` — JTAS + ESI 5-level 定義、arrival_modes、severity_to_triage_distribution、arrival_mode_severity_multipliers

## Consumers

- `clinosim/modules/document/` — ED_TRIAGE_NOTE narrative で triage_data 参照
- `clinosim/modules/output/_fhir_documents.py` — ED_TRIAGE_NOTE の content に serialize

## 関連

- Spec: `docs/superpowers/specs/2026-07-01-tier1-3-document-density-alpha-min-2-design.md`
- Master plan: `docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`
