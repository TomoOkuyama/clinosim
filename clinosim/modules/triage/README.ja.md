# `clinosim.modules.triage` — ED triage サンプリング (JTAS / ESI)

## 概要

Tier 1 #3 α-min-2 always-on AD-55 Module。全 ED (emergency) encounter に対し
triage level (JP は JTAS / US は ESI) + arrival mode (walk-in /
ambulance / private_vehicle / police / helicopter) をサンプリングし、
`Encounter.triage_data` に書き込む (`acuity_score` は `None` のまま)。
サンプルした level は ED condition の `triage_level_min` /
`triage_level_max` で clamp し、来院時 vitals による上限
(`triage_level_cap`、Issue #2082) を適用する。非 emergency encounter は
no-op。

## Scope

- **In scope**: `triage_enricher` (POST_ENCOUNTER order=93、ED
  限定)、`pick_triage_level(severity, level_system, rng)` — YAML
  weight 表 (severity 別、JTAS と ESI で共通)、
  `pick_arrival_mode(severity, rng)`、`condition_triage_bounds(record)`、
  `triage_level_cap(vitals)`、
  `load_triage_protocols()` YAML loader with 6-layer
  `_validate_triage_protocols` (silent-no-op 防御)。
- **Out of scope**: encounter routing / class emission
  ([`clinosim.modules.encounter`](../encounter/README.ja.md))、FHIR
  `Encounter.class` / `type` / `priority` emission
  ([`clinosim.modules.output`](../output/README.ja.md))、ED narrative
  文書
  ([`clinosim.modules.document.narrative`](../document/narrative/README.ja.md)
  — ED_TRIAGE_NOTE stub は
  [`document`](../document/README.ja.md) module が後段
  POST_ENCOUNTER pass で emit する)。

## Public API

```python
from clinosim.modules.triage import TriageData
from clinosim.modules.triage.engine import (
    triage_enricher,             # POST_ENCOUNTER enricher entry
    pick_triage_level,           # (severity, level_system, rng) -> str
    pick_arrival_mode,           # (severity, rng) -> str
    condition_triage_bounds,     # (record) -> (最緊急, 最非緊急) level
    triage_level_cap,            # (vitals) -> 許容される最非緊急 level
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

- `clinosim.modules._shared` — `get_attr_or_key`, `is_jp`,
  `normalize_probabilities`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.types.triage` — `TriageData`。
- `clinosim.modules.encounter.protocol` — `load_all_encounter_conditions`
  (condition 別 `triage_level_min` / `triage_level_max`)。
- `yaml`, `numpy`。

## 定数と設定

- [`reference_data/triage_protocols.yaml`](reference_data/triage_protocols.yaml)
  — `triage_systems` (JTAS / ESI の level ラベル)、`arrival_modes`、
  country 非依存の `severity_to_triage_distribution`、
  `arrival_mode_base_distribution`、`arrival_mode_severity_multipliers`。
  `_validate_triage_protocols` (初回 `load_triage_protocols()` 呼出時に
  実行) の検査: top level 非空 / `triage_systems` が JTAS+ESI ちょうど /
  各 system の level が 1-5 / `arrival_modes` と
  `SUPPORTED_ARRIVAL_MODES` の一致 / severity key 一致かつ各分布の合計
  ~1.0 / base arrival-mode key 一致。
- Level system: `JTAS` (JP)、`ESI` (US)。`ctx.config.country`
  (fallback `ctx.country`) で選択。
- vitals 上限の閾値 (`engine.py` 定数、ESI v4 danger zone):
  HR > 100、RR > 20、SpO2 < 92、疼痛 ≥ 7 → level ≤ 3; AVPU P、
  SpO2 < 90、SBP < 90 → level ≤ 2; AVPU U → level 1。

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
(`L393-408` 付近) で登録:

- `name="triage"`, `stage=POST_ENCOUNTER`, `order=93`,
  `enabled=lambda c: True`。
- `nursing_assignment` (order=94) と `document` (order=95) の前に
  実行。enricher body 内で ED-only 判定 (非 ED encounter は skip)。
- `audit.py` module は import 時に AD-60 audit framework に
  `register_audit_module` で登録される。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Enricher registry | [`clinosim/simulator/enrichers.py:400`](../../simulator/enrichers.py) | POST_ENCOUNTER order=93 登録。 |
| Audit registry | [`clinosim/modules/triage/audit.py`](audit.py) | AD-60 audit plug-in — canonical-constants cross-check + firing proof。 |
| Document module audit | [`clinosim/modules/document/audit.py`](../document/audit.py) | triage level proof を `_build_triage_severity_proof` に委譲。 |
| ED narrative renderer | [`clinosim/modules/document/narrative/renderers/`](../document/narrative/renderers/) | `ed_triage_note.py`、`_ed_helpers.py`、`section_builders/ed_note.py` が `encounter.triage_data` を read。 |

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
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
