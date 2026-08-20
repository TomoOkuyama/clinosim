# `clinosim.modules.device` — ICU デバイス配置

## 概要

POST_ENCOUNTER always-on の AD-55 Module。適格な入院 / ICU /
rehab-inpatient encounter に対して ICU デバイス (中心静脈カテーテル、
膀胱留置カテーテル、機械換気) を配置し、結果を
`CIFPatientRecord.extensions["device"]` に書き込む。下流の
[`clinosim.modules.hai`](../hai/README.md) が line-days を消費する
(Phase 2 HAI cascade — CDC NHSN の per-line-day risk baseline)。

## Scope

- **In scope**: `place_devices_for_encounter` の per-encounter 評価
  (peak physiology state + altered-consciousness flag + YAML 条件
  → device 集合)、`load_devices_config` YAML loader、POST_ENCOUNTER
  `enrich_device` enricher。
- **Out of scope**: デバイス line-days からの HAI event サンプリング
  ([`clinosim.modules.hai`](../hai/README.md))、デバイス関連抗菌薬
  ([`clinosim.modules.antibiotic`](../antibiotic/README.md))、
  FHIR `Device` / `DeviceUseStatement` emission
  ([`clinosim.modules.output`](../output/README.md))。

## Public API

```python
from clinosim.modules.device import (
    load_devices_config,             # () -> dict (@lru_cache)
    place_devices_for_encounter,     # (record, encounter, rng) -> list[Device]
)
from clinosim.modules.device.enricher import enrich_device
```

内部 helper (`engine.py`): `_evaluate_indications`,
`_indications_met`, `_altered_consciousness_for_encounter`,
`_peak_state_for_encounter`。

## 決定論

- サブ seed オフセット `0x4445` (`"DE"`, PR-A) —
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["device"]` に登録済み。
- Per-encounter RNG:
  `derive_sub_seed(master_seed, offset, encounter_id)` — 同 encounter
  は常に同 device 集合をサンプリング。患者主 RNG は乱さない (AD-16)。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`,
  `normalize_probabilities`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.types.encounter` — `Device`, `Encounter`,
  `CIFPatientRecord`。
- `clinosim.types.clinical` — `PhysiologicalState` (peak state
  評価入力)。
- `numpy`, `yaml`。

## 定数と設定

- [`reference_data/devices.yaml`](reference_data/devices.yaml) —
  デバイスカタログ。各 entry が indication criteria (physiology
  state 閾値、altered-consciousness gate、admission source filter)、
  配置確率、期待 line-days 分布を持つ。
- Encounter-type gate: `INPATIENT_ENCOUNTER_TYPES =
  {"inpatient", "icu", "rehab_inpatient"}` (nursing 参照集合と同じ)
  でのみ発火。

## ディレクトリ構造

```
clinosim/modules/device/
  __init__.py                        load_devices_config + place_devices_for_encounter 再 export
  engine.py                          indication 評価 + デバイス配置
  enricher.py                        POST_ENCOUNTER enricher
  reference_data/
    devices.yaml                     デバイスカタログ + indication 条件
```

**`audit.py` は存在しない** — 検証は下記 test で担保。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`L237-246` 付近) で登録:

- `name="device"`, `stage=POST_ENCOUNTER`, `order=70`,
  `enabled=lambda c: True`。
- `hai` (order=80) の前に実行し、HAI enricher が line-days を読む
  時点で `extensions["device"]` が既に存在するようにする。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:241`](../../simulator/enrichers.py) | POST_ENCOUNTER order=70 登録。 |
| HAI enricher | [`clinosim/modules/hai/engine.py`](../hai/engine.py) | `extensions["device"]` の line-days を CDC NHSN per-line-day HAI onset サンプリングに使用 (Phase 2)。 |
| FHIR `Device` builder | [`clinosim/modules/output/fhir_r4/`](../output/fhir_r4/) | `extensions["device"]` から `Device` + `DeviceUseStatement` を emit。 |

## テスト

```bash
pytest tests/unit -k "device_engine or device_enricher" -q
```

個別ファイル:

- [`tests/unit/test_device_engine.py`](../../../tests/unit/test_device_engine.py)
  — indication 評価。
- [`tests/unit/test_device_enricher.py`](../../../tests/unit/test_device_enricher.py)
  — enricher 決定論 + encounter-type gating。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
