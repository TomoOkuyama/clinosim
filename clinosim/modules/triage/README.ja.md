# `clinosim.modules.triage` — ED triage サンプリング (JTAS / ESI)

## 概要

Tier 1 #3 α-min-2 always-on AD-55 Module。全 ED (emergency) encounter に対し
triage level (JP は JTAS / US は ESI) + arrival mode (walk-in /
ambulance / other) + acuity score をサンプリングし、
`EncounterRecord.triage_data` に書き込む。非 emergency encounter は
no-op。

## Scope

- **In scope**: `triage_enricher` (POST_ENCOUNTER order=93、ED
  限定)、`pick_triage_level(severity, level_system, rng)` — YAML
  weight 表 (severity × system)、`pick_arrival_mode(severity, rng)`、
  `load_triage_protocols()` YAML loader with 6-layer
  `_validate_triage_protocols` (silent-no-op 防御)。
- **Out of scope**: encounter routing / class emission
  ([`clinosim.modules.encounter`](../encounter/README.md))、FHIR
  `Encounter.class` / `type` / `priority` emission
  ([`clinosim.modules.output`](../output/README.md))、ED narrative
  文書
  ([`clinosim.modules.document.narrative`](../document/narrative/README.md)
  — ED_TRIAGE_NOTE stub は
  [`document`](../document/README.md) module が後段
  POST_ENCOUNTER pass で emit する)。

## Public API

```python
from clinosim.modules.triage import TriageData
from clinosim.modules.triage.engine import (
    triage_enricher,             # POST_ENCOUNTER enricher entry
    pick_triage_level,           # (severity, level_system, rng) -> str
    pick_arrival_mode,           # (severity, rng) -> str
    load_triage_protocols,       # () -> dict (@lru_cache、6-layer validated)
)
```

## 決定論

- サブ seed オフセット `0x5452` (`"TR"`、Tier 1 #3 α-min-2 PR1) —
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["triage"]` に登録済み。
- Per-encounter RNG:
  `derive_sub_seed(master_seed, offset, encounter_id)` — 患者主
  RNG は乱さない (AD-16)。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`, `is_jp`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.types.triage` — `TriageData`。
- `clinosim.types.encounter` — `Encounter` (encounter_type gate)。
- `yaml`, `numpy`。

## 定数と設定

- [`reference_data/triage_protocols.yaml`](reference_data/triage_protocols.yaml)
  — (level_system × severity) 別 tier weight + arrival-mode 確率。
  import 時 `_validate_triage_protocols` が標準 6-layer 防御
  (空 top / 必須 key 欠落 / severity 別 weight / JTAS・ESI canonical
  level の双方向 coverage / 型 check) を実行。
- Level system: `jtas` (JP)、`esi` (US)。emission 時に country で
  dispatch。

## ディレクトリ構造

```
clinosim/modules/triage/
  __init__.py                        TriageData を再 export
  engine.py                          triage_enricher + pick_* helper + loader + 6-layer validator
  audit.py                           AD-60 audit plug-in (triage tier canonical constants + firing proof)
  reference_data/
    triage_protocols.yaml            (system × severity) 別 tier + arrival weight
```

**`enricher.py` は存在しない** — enricher entry は `engine.py` で
直接登録される。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`L303-316` 付近) で登録:

- `name="triage"`, `stage=POST_ENCOUNTER`, `order=93`,
  `enabled=lambda c: True`。
- `nursing_assignment` (order=94) と `document` (order=95) の前に
  実行。enricher body 内で ED-only 判定 (非 ED encounter は skip)。
- `audit.py` module は import 時に AD-60 audit framework に
  `register_audit_module` で登録される。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:311`](../../simulator/enrichers.py) | POST_ENCOUNTER order=93 登録。 |
| Audit registry | [`clinosim/modules/triage/audit.py`](audit.py) | AD-60 audit plug-in — canonical-constants cross-check + firing proof。 |
| Document module | [`clinosim/modules/document/audit.py`](../document/audit.py) | triage canonical tier 集合を cross-reference。 |
| FHIR encounter builder | [`clinosim/modules/output/fhir_r4/encounters/`](../output/fhir_r4/encounters/) | `EncounterRecord.triage_data` を read して `Encounter.priority` に反映。 |

## テスト

```bash
pytest tests/unit -k triage -q
clinosim audit run -d <cohort_dir> --module triage
```

個別ファイル:

- [`tests/unit/modules/triage/test_engine.py`](../../../tests/unit/modules/triage/test_engine.py)
  — enricher gate、サンプリング決定論、ED-only 挙動。
- [`tests/unit/modules/triage/test_triage_protocols_yaml.py`](../../../tests/unit/modules/triage/test_triage_protocols_yaml.py)
  — 6-layer validator coverage。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
