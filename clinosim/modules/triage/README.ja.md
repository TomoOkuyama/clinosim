# `clinosim.modules.triage` — ED triage サンプリング (JTAS / ESI)

## 概要

Tier 1 #3 α-min-2 always-on AD-55 Module。全 ED (emergency) encounter に対し
triage level (JP は JTAS / US は ESI) + arrival mode (walk-in /
ambulance / private_vehicle / police / helicopter) をサンプリングし、
`Encounter.triage_data` に書き込む (`acuity_score` は `None` のまま)。
level は ESI v4 に従い (Issue #2864)、JTAS の level も同じ規則に従う:

1. severity による抽選を ED condition の範囲に制限する —
   `narrative.ed_triage_template.common_triage_levels` の範囲を
   `triage_level_min` / `triage_level_max` で狭めたもの。
2. 抽選が 1 / 2 ならそのまま。3–5 なら resource level (decision
   point C) に置き換える: resource 種別 2 以上 → 3、1 → 4、0 → 5。
   種別は検査 (件数によらず 1)、画像 (ECG 含む)、非経口治療 (輸液、
   IV / IM / ネブライザー投与) と処置 (`resource_rule` の単純処置を
   除く) で、受診の order から数える。
3. `ed_triage_template.high_risk_orders` に挙げた治療 (アナフィラキシー
   への IM アドレナリン、ACS 疑いへの経験的アスピリン) があれば level を
   2 以下にする (decision point B)。
4. 結果を範囲内に clamp し、最後に来院時 vitals による上限
   (`triage_level_cap`、Issue #2082) を適用する (範囲を下回りうる)。

非 emergency encounter は no-op。

## Scope

- **In scope**: `triage_enricher` (POST_ENCOUNTER order=93、ED
  限定)、`pick_triage_level(severity, level_system, rng)` — YAML
  weight 表 (severity 別、JTAS と ESI で共通、condition の範囲に制限)、
  `pick_arrival_mode(severity, rng)`、`condition_triage_bounds(record)`、
  `resource_count(orders)` / `resource_level(orders)`、
  `has_high_risk_order(record, orders)`、`triage_level(record, enc, drawn)`、
  `triage_level_cap(vitals)`、
  `load_triage_protocols()` YAML loader (`TriageProtocols` Pydantic
  model で検証、silent-no-op 防御)。
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
    pick_triage_level,           # (severity, level_system, rng, bounds=(1, 5)) -> str
    pick_arrival_mode,           # (severity, rng) -> str
    condition_triage_bounds,     # (record) -> (最緊急, 最非緊急) level
    resource_count,              # (orders) -> ESI resource 種別数
    resource_level,              # (orders) -> 3 / 4 / 5
    has_high_risk_order,         # (record, orders) -> bool
    triage_level,                # (record, enc, drawn) -> 最終 level
    triage_level_cap,            # (vitals) -> 許容される最非緊急 level
    load_triage_protocols,       # () -> dict (@lru_cache、TriageProtocols 検証済)
)
```

## 決定論

- サブ seed オフセット `0x5452` (`"TR"`、Tier 1 #3 α-min-2 PR1) —
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["triage"]` に登録済み。
- Per-encounter RNG:
  `derive_sub_seed(master_seed, offset, encounter_id)` — 患者主
  RNG は乱さない (AD-16)。
- encounter あたり 2 draw (level → arrival mode)。範囲制限は level
  draw の写像先を変えるだけで draw 数は変えないため、arrival mode は
  影響を受けない (Issue #2864)。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`, `is_jp`,
  `normalize_probabilities`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.types.triage` — `TriageData`。
- `clinosim.modules.encounter.protocol` — `load_all_encounter_conditions`
  (condition 別 `triage_level_min` / `triage_level_max`、
  `narrative.ed_triage_template.common_triage_levels` /
  `high_risk_orders`)。
- `yaml`, `numpy`。

## 定数と設定

- [`reference_data/triage_protocols.yaml`](reference_data/triage_protocols.yaml)
  — `triage_systems` (JTAS / ESI の level ラベル)、`arrival_modes`、
  country 非依存の `severity_to_triage_distribution`、
  `arrival_mode_base_distribution`、`arrival_mode_severity_multipliers`、
  ESI v4 の `resource_rule` (`level_by_count`、`parenteral_routes`、
  `non_resource_procedures`)。
  `TriageProtocols` model (初回 `load_triage_protocols()` 呼出時に
  実行) の検査: top level 非空 / `triage_systems` が JTAS+ESI ちょうど /
  各 system の level が 1-5 / `arrival_modes` と
  `SUPPORTED_ARRIVAL_MODES` の一致 / severity key 一致かつ各分布の合計
  ~1.0 / base arrival-mode key 一致 / `resource_rule.level_by_count` が
  3–5 の 3 level。encounter protocol model は `common_triage_levels` が
  `"1"`–`"5"` であること、`high_risk_orders` の各要素が condition の
  治療名であり、到達できる level 1 か 2 があることを検査する。
- Level system: `JTAS` (JP)、`ESI` (US)。`ctx.config.country`
  (fallback `ctx.country`) で選択。
- vitals 上限の閾値 (`engine.py` 定数、ESI v4 danger zone):
  HR > 100、RR > 20、SpO2 < 92、疼痛 ≥ 7 → level ≤ 3; AVPU P、
  SpO2 < 90、SBP < 90 → level ≤ 2; AVPU U → level 1。

## ディレクトリ構造

```
clinosim/modules/triage/
  __init__.py                        TriageData を再 export
  engine.py                          triage_enricher + pick_* helper + loader + TriageProtocols model
  audit.py                           AD-60 audit plug-in (triage tier canonical constants + firing proof)
  reference_data/
    triage_protocols.yaml            (system × severity) 別 tier + arrival weight
```

**`enricher.py` は存在しない** — enricher entry は `engine.py` で
直接登録される。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`register_builtin_enrichers`) で登録:

- `name="triage"`, `stage=POST_ENCOUNTER`, `order=93`,
  `enabled=lambda c: True`。
- `nursing_assignment` (order=94) と `document` (order=95) の前に
  実行。enricher body 内で ED-only 判定 (非 ED encounter は skip)。
- `audit.py` module は import 時に AD-60 audit framework に
  `register_audit_module` で登録される。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Enricher registry | [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) (`register_builtin_enrichers`) | POST_ENCOUNTER order=93 登録。 |
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
  — `TriageProtocols` validator coverage。
- [`tests/unit/modules/triage/test_esi_bounds_2864.py`](../../../tests/unit/modules/triage/test_esi_bounds_2864.py)
  — 範囲制限付き抽選、resource 規則、high-risk order、vitals 上限。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
