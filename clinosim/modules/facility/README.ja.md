# `clinosim.modules.facility` — 病院運用状態モデル

## 概要

単一病院の時間変化する運用状態 — resource queue 利用率 (lab / CT /
MRI / X-ray / ultrasound / OR)、病床稼働率、ED crowding、shift-based
staff level — をモデル化し、下流の lab / imaging / OR 発注が現実的な
result 時刻を組めるよう queueing theory による遅延を計算する。
default hospital-operations YAML の loader も本モジュールが持つ。

## Scope

- **In scope**: `HospitalState` dataclass (resource ごとの queue float
  `[0, 1]`、職種別 staff float)、`update_for_time(dt, hospital_ops)`
  (時刻 + 曜日で shift dispatch、weekend modifier、YAML 定義の
  named `daily_patterns` delta 適用)、`calculate_delay(resource,
  urgency, hospital_ops)` (M/M/1 風 base × congestion_factor ×
  staff_factor + reporting time、hard cap は
  `DELAY_MAX_DELAY_ROUTINE_MIN` / `DELAY_MAX_DELAY_STAT_MIN`)、
  `add_to_queue` / `release_from_queue` (発注ごとの利用率簿記)、
  default config を load する `load_hospital_operations()`。
- **Out of scope**: スタッフ *identity* / roster
  ([`clinosim.modules.staff`](../staff/README.md))、cross-hospital /
  地域 organisation
  ([`clinosim.modules.healthcare_system`](../healthcare_system/README.md))、
  機器在庫 ([`clinosim.modules.device`](../device/README.md))、
  FHIR `Organization` / `Location` 出力
  ([`clinosim.modules.output`](../output/README.md))、部門 / 病棟
  定義 (data-only YAML
  [`clinosim/config/hospital_operations.yaml`](../../config/hospital_operations.yaml))。

## Public API

`__init__.py` は空。呼び出し側は `hospital_state` から直接 import:

```python
from clinosim.modules.facility.hospital_state import (
    HospitalState,               # dataclass — queue / occupancy / staff / helper
    load_hospital_operations,    # () -> dict (clinosim/config/hospital_operations.yaml の cache 済 load)
)
```

`HospitalState` の method:

| Method | 契約 |
|---|---|
| `update_for_time(dt, hospital_ops)` | shift-based staffing (`day` / `evening` / `night`) を設定、`weekday >= WEEKEND_WEEKDAY_MIN` なら weekend modifier 適用、次に `daily_patterns.*` の各 YAML entry を `hours` window + `weekday` フィルタが一致するとき適用。 |
| `calculate_delay(resource, urgency, hospital_ops)` | resource + urgency に対する遅延 (分) を `base × (1 / (1 - utilization)) × (1 / staff) + reporting_time × (1 / staff)` で返す。congestion + staff factor は `DELAY_CONGESTION_CAP` + `DELAY_STAFF_CAP` で clamp、最終値は `DELAY_MAX_DELAY_{STAT,ROUTINE}_MIN` で cap。 |
| `add_to_queue(resource, hospital_ops)` | `<resource>_queue` を `1/capacity` だけ増加。 |
| `release_from_queue(resource, hospital_ops)` | `<resource>_queue` を `1/capacity` だけ減少。 |

## 決定論

該当なし — `HospitalState` は decision 論的 resource-contention
モデル。`np.random.Generator` / `derive_sub_seed` / `ENRICHER_SEED_OFFSETS`
エントリのいずれも使わない。`calculate_delay` は
`(state, resource, urgency, hospital_ops)` の純粋関数、
`add_to_queue` / `release_from_queue` は `HospitalState` を決定論的
に mutate する。call 順序が保たれる限り pinned seed での byte-identity
は保証される (byte-diff 契約は `_hospital_state_thresholds.py` の
docstring 参照)。

## 依存

- `clinosim.modules.facility._hospital_state_thresholds` — 全 clamp /
  cap / fallback / shift 境界の定数。
- `yaml` — default hospital-operations file の YAML パーサ。
- **`_UNSET_DATETIME = datetime(1970, 1, 1)`** — `HospitalState.timestamp`
  の sentinel default (決定論 chain の rationale は
  `clinosim/types/clinical.py` 2026-07-04 を参照)。
- 他の `clinosim.modules.*` には依存しない。

## 定数と設定

- Threshold 表: [`_hospital_state_thresholds.py`](_hospital_state_thresholds.py)
  — state model が使う全 scalar を policy §5 に従って inline 定数から
  lift。2 cluster:
  - **Shift and schedule**: `SHIFT_DAY_START_HOUR`,
    `SHIFT_DAY_END_HOUR_EXCLUSIVE`, `SHIFT_EVENING_START_HOUR`,
    `WEEKEND_WEEKDAY_MIN`, `FALLBACK_WEEKEND_MODIFIER`、および
    職種別 staff fallback (`FALLBACK_{LAB,RADIOLOGY,NURSING,PHARMACY,OR}_STAFF`)。
  - **Queueing / delay**: `DELAY_MAX_DELAY_ROUTINE_MIN`,
    `DELAY_MAX_DELAY_STAT_MIN`, `DELAY_CONGESTION_CAP`,
    `DELAY_CONGESTION_UTILIZATION_FLOOR`,
    `DELAY_QUEUE_UTILIZATION_CEILING`,
    `DELAY_QUEUE_UTILIZATION_FLOOR`, `DELAY_STAFF_CAP`,
    `DELAY_STAFF_FLOOR`、および YAML fallback
    (`FALLBACK_BASE_{STAT,ROUTINE}_MIN`,
    `FALLBACK_REPORTING_{STAT,ROUTINE}_MIN`,
    `FALLBACK_QUEUE_UTILIZATION`, `FALLBACK_RESOURCE_CAPACITY`)。
- Runtime YAML: [`clinosim/config/hospital_operations.yaml`](../../config/hospital_operations.yaml)
  (または CLI `--hospital-config PATH` 経由の size variant
  `hospital_small.yaml` / `hospital_large.yaml`)。参照 section:
  - `staffing.{day, evening, night}.*` — shift 別 staff level。
    `weekend_modifier` で土日スケーリング。
  - `daily_patterns.<name>` — `hours: [start, end]` (wrap-safe)、
    任意 `weekday`、`lab_queue_delta` / `ct_queue_delta` /
    `mri_queue_delta` / `xray_queue_delta` / `bed_occupancy_delta` /
    `ed_crowding_delta` のいずれか。
  - `base_processing_time.<resource>[_stat|_routine]` — 発注ごとの
    base 分 (欠落時 `FALLBACK_BASE_{STAT,ROUTINE}_MIN`)。
  - `reporting_time.{stat, routine}` — imaging reporting 分。
  - `resource_capacity.{lab_analyzers, ct_scanners, mri_scanners,
    xray_rooms, ultrasound_rooms, operating_rooms}` —
    `add_to_queue` / `release_from_queue` が使う capacity 整数。
- `load_hospital_operations()` は `@lru_cache(maxsize=1)`。返却
  dict は read-only 扱い。CLI の `--hospital-config PATH` 経路は
  意図的に本 cache の影響を受けず、fresh dict を直接 load する。

## ディレクトリ構造

```
clinosim/modules/facility/
  __init__.py                     空
  hospital_state.py               HospitalState + load_hospital_operations
  _hospital_state_thresholds.py   named threshold 定数 (shift + queueing)
  SPEC.md                         拡張設計参考 (部門レイアウト — runtime data ではない)
```

**`engine.py` / `enricher.py` / `audit.py` / `reference_data/` は
存在しない**。

## Enricher 配線

該当なし — 本モジュールは data model + loader であり enricher で
はない。`register_builtin_enrichers` に登録なく、`ENRICHER_SEED_OFFSETS`
にも seed 未登録。simulator boot 経路が `HospitalState` を run あたり
1 回構築し、遅延計算が必要な全臨床イベントに (state + `hospital_ops`
dict を) 渡す。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Simulator boot | [`clinosim/simulator/engine.py`](../../simulator/engine.py) (`L191` 付近) | `hospital_ops` を load (`--hospital-config PATH` または `load_hospital_operations()`) し、run ごとに `HospitalState` を構築。 |
| Order 結果 timing | [`clinosim/modules/order/engine.py`](../order/engine.py) (`calculate_result_time_from_state`、~L795) | lab / imaging / OR 結果の timestamp に `HospitalState.calculate_delay` を使用。`simulator/lab_pipeline.py` + `simulator/unknown_condition.py` から呼び出される。 |
| Order queue-replay test | [`tests/unit/test_order_queue_replay.py`](../../../tests/unit/test_order_queue_replay.py) | `HospitalState` + `load_hospital_operations()` を load し queue add / release 意味論を replay。 |
| Wall-clock sentinel test | [`tests/unit/test_wallclock_sentinel_defaults.py`](../../../tests/unit/test_wallclock_sentinel_defaults.py) | `_UNSET_DATETIME` sentinel default を assert。 |

## テスト

```bash
pytest tests/unit -k "facility or hospital_state or order_queue_replay" -q
```

個別ファイル:

- [`tests/unit/test_facility_ecs_organization.py`](../../../tests/unit/test_facility_ecs_organization.py)
  — JP-CLINS 統一 `hospital-main` Organization
  (JP_Organization + JP_Organization_eCS profile を単一 resource に
  同居、Issue #746)。facility identity を読む FHIR Organization 出力
  を pin。
- [`tests/unit/test_order_queue_replay.py`](../../../tests/unit/test_order_queue_replay.py)
  — queue add / release 不変量。
- [`tests/unit/test_wallclock_sentinel_defaults.py`](../../../tests/unit/test_wallclock_sentinel_defaults.py)
  — `HospitalState.timestamp` の sentinel default 挙動。

**coverage gap**: `calculate_delay` / `update_for_time` に直接 unit
test は無く、DES engine 経由で間接カバー。遅延式 (base × congestion
× staff + reporting、cap、resource 別 capacity dispatch) に対する
focused test の追加は低コスト follow-up。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
