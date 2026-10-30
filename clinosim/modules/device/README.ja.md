# `clinosim.modules.device` — ICU デバイス配置

## 概要

POST_ENCOUNTER always-on の AD-55 Module。ICU 転棟した患者の入院
encounter に対して ICU デバイス (中心静脈カテーテル、
膀胱留置カテーテル、機械換気) を配置し、結果を
`CIFPatientRecord.extensions["device"]` に書き込む。下流の
[`clinosim.modules.hai`](../hai/README.ja.md) が line-days を消費する
(Phase 2 HAI cascade — CDC NHSN の per-line-day risk baseline)。

## Scope

- **In scope**: `place_devices_for_encounter` の per-encounter 評価
  (入院中の最悪 physiology state + 意識障害 (GCS < 13) + 挿管 procedure
  + YAML 条件 → device 集合。留置日 / 抜去日 = encounter の入院日 /
  退院日)、`load_devices_config` YAML loader、POST_ENCOUNTER
  `enrich_device` enricher。
- **Out of scope**: デバイス line-days からの HAI event サンプリング
  ([`clinosim.modules.hai`](../hai/README.ja.md))、デバイス関連抗菌薬
  ([`clinosim.modules.antibiotic`](../antibiotic/README.ja.md))、
  FHIR `Device` / `DeviceUseStatement` emission
  ([`clinosim.modules.output`](../output/README.ja.md))。

## Public API

```python
from clinosim.modules.device import (
    load_devices_config,             # () -> dict (@lru_cache)
    place_devices_for_encounter,     # (record, encounter, rng, devices_config) -> list[DeviceRecord]
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
- enricher は患者単位 RNG
  (`derive_sub_seed(master_seed, offset, patient_id)`) を作り
  `place_devices_for_encounter` に渡すが、現状の配置処理はそこから
  draw しない — device 集合は record の決定論的関数。患者主 RNG は
  乱さない (AD-16)。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`,
  `get_or_create_container`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.types.device` — `DeviceRecord`。
- `clinosim.types.encounter` — `Encounter`, `EncounterType`。
- `clinosim.types.output` — `CIFPatientRecord`。
- `clinosim.types.clinical` — `PhysiologicalState` (peak state
  評価入力)。
- `numpy`, `yaml`。

## 定数と設定

- [`reference_data/devices.yaml`](reference_data/devices.yaml) —
  デバイスカタログ (`cvc`, `indwelling_catheter`,
  `mechanical_ventilator`)。各 entry は `snomed_code`、
  `snomed_display_en` / `_ja`、`any: [token, ...]` 節の list である
  `placement_criteria` を持つ (いずれかの節のいずれかの token が
  成立すれば配置)。現状の条件: CVC ← `severity_moderate_plus`、
  膀胱留置カテーテル ← `severity_moderate_plus` または
  `altered_consciousness`、人工呼吸器 ← `intubated`。配置確率や
  line-days 分布は持たない。
- indication token (`_evaluate_indications`):
  `severity_moderate_plus` (gate 通過時は常に真)、
  `altered_consciousness` (encounter の vital に GCS < 13 がある)、
  `hypoxia` (最悪 perfusion < 0.4 または oxygenation impairment ≥ 0.6)、
  `intubated` (encounter に `intubation` procedure がある)、
  `high_respiratory_demand` (respiratory fraction > 0.7)。`hypoxia` と
  `high_respiratory_demand` は算出されるが現状どの yaml 条件も使わない。
- Gate: `record.icu_transferred` が真かつ encounter type が
  `EncounterType.INPATIENT` の場合のみ発火。

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
(`L310-320` 付近) で登録:

- `name="device"`, `stage=POST_ENCOUNTER`, `order=70`,
  `enabled=lambda c: True`。
- `hai` (order=80) の前に実行し、HAI enricher が line-days を読む
  時点で `extensions["device"]` が既に存在するようにする。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Enricher registry | [`clinosim/simulator/enrichers.py:316`](../../simulator/enrichers.py) | POST_ENCOUNTER order=70 登録。 |
| HAI enricher | [`clinosim/modules/hai/enricher.py`](../hai/enricher.py) | `extensions["device"]` の line-days を CDC NHSN per-line-day HAI onset サンプリングに使用 (Phase 2)。 |
| FHIR `Device` builder | [`clinosim/modules/output/fhir_r4/procedures/device.py`](../output/fhir_r4/procedures/device.py) | `extensions["device"]` の entry ごとに `Device` + `DeviceUseStatement` を 1 件ずつ emit (id は `DeviceRecord.device_id` から導出した opaque id)。 |

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
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
