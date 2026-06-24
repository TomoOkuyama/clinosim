# clinosim.modules.facility — Hospital Operational State Module

## 目的

病院の **運用状態 (resource queues, staffing, 時間帯パターン)** を時系列でモデル化し、 検査・画像・手術・処方等のターンアラウンドタイム (TAT) を **創発的に決定** する。

clinosim では「CT は 30 分後に結果が出る」のような固定値ではなく、 「現在の CT 待ち行列利用率」「放射線技師の人数」「夜勤帯か」「土日か」といったオペレーション要素から **キューイング理論 (M/M/1) で TAT を計算する**。 これにより:

- 夜間・週末の遅延が自然に発生
- ED 混雑期に検査が遅れる
- staffing 削減が下流の処置遅延に波及
- 病院規模 (small/large) を config 切替で表現

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **Delays emerge from contention** | TAT は固定値でなく、 utilization × staff × shift から算出 |
| 2 | **Time-aware staffing** | 8–16 day, 16–24 evening, 0–8 night の 3 シフト + 週末 modifier |
| 3 | **YAML-driven** | 病院規模・設備・スタッフ数は `clinosim/config/hospital_*.yaml` に外在化 |
| 4 | **Capped pathology** | キューイング式の発散を防ぐため congestion / staff factor に上限。 さらに stat ≤ 4h, routine ≤ 12h のハードキャップ |
| 5 | **Daily patterns** | 朝の採血ラッシュ・午後の手術混雑等は YAML の `daily_patterns` で時間帯/曜日条件付きデルタとして表現 |

## ディレクトリ構造

```
clinosim/modules/facility/
├── __init__.py
├── README.md            # 本ドキュメント
├── SPEC.md
└── hospital_state.py    # HospitalState dataclass + load/calculate ヘルパ
```

関連 config (`clinosim/config/`):

- `hospital_operations.yaml` — staffing シフト、 base processing time、 daily patterns、 reporting time
- `hospital_small.yaml` — 200 床規模のリソース容量
- `hospital_large.yaml` — 800 床規模のリソース容量

## API リファレンス

### `HospitalState` (dataclass)

```python
@dataclass
class HospitalState:
    timestamp: datetime
    # Resource queue utilization (0.0=idle, 1.0=fully occupied)
    lab_queue: float = 0.1
    ct_queue: float = 0.1
    mri_queue: float = 0.1
    xray_queue: float = 0.05
    ultrasound_queue: float = 0.05
    or_queue: float = 0.1
    # Occupancy
    bed_occupancy: float = 0.7
    ed_crowding: float = 0.3
    # Staff levels (fraction of full capacity)
    lab_staff: float = 1.0
    radiology_staff: float = 1.0
    nursing_staff: float = 1.0
    pharmacy_staff: float = 1.0
    or_staff: float = 1.0
```

シミュレーション時刻ごとに 1 つ存在し、 各オーダー処理時に状態を読む/更新する。

### `update_for_time(dt: datetime, ops_config: dict) -> None`

シミュレーション時刻が進むたびに呼び、 staffing と baseline utilization を更新する。

**シフト判定**:

| 時刻 | シフト |
|---|---|
| 8 ≤ hour < 16 | day |
| 16 ≤ hour < 24 | evening |
| 0 ≤ hour < 8 | night |

各シフトの staff 値は `ops_config["staffing"][shift]` から読む。 週末 (`weekday >= 5`) は `weekend_modifier` (デフォルト 0.6) が lab/radiology/pharmacy/or の staff に乗算される。

**Daily patterns**:

`ops_config["daily_patterns"]` の各エントリは時間帯・曜日条件と `<resource>_queue_delta` を持ち、 マッチ時に該当する queue 値を加減する。 結果は `[0.0, 0.95]` にクランプ。

```yaml
# hospital_operations.yaml の例
daily_patterns:
  morning_lab_rush:
    hours: [6, 9]                # 6時から9時
    lab_queue_delta: 0.20
  surgery_day:
    weekday: 1                   # 火曜
    or_queue_delta: 0.15
```

### `calculate_delay(resource: str, urgency: str, ops_config: dict) -> float`

特定リソースで特定 urgency のオーダーを処理する場合の **想定遅延 (分)** を返す。

**式**:

```python
base = ops_config["base_processing_time"][f"{resource}_{urgency}"]
utilization = getattr(state, f"{resource}_queue")           # [0, 0.95]
congestion_factor = 1.0 / max(0.05, 1.0 - utilization)      # M/M/1 delay factor
staff_factor = 1.0 / max(0.1, <relevant staff>)             # 1/staff
congestion_factor = min(congestion_factor, 5.0)             # cap 5x
staff_factor = min(staff_factor, 4.0)                       # cap 4x
reporting = ops_config["reporting_time"][urgency]           # 画像のみ
reporting *= staff_factor                                   # less staff → slower reads
delay = base * congestion_factor * staff_factor + reporting
return min(delay, 240.0 if urgency == "stat" else 720.0)    # ハードキャップ
```

| Resource | 使用する staff |
|---|---|
| `ct`, `mri`, `xray`, `ultrasound` | `radiology_staff` |
| `lab` | `lab_staff` |
| `or` | `or_staff` |
| その他 | `1.0` |

`stat` オーダーは base processing time が短く (e.g., `lab_stat: 30` vs `lab_routine: 90`)、 reporting time も `stat: 15min` 程度。 stat の最大遅延は 240 分、 routine は 720 分。

```python
state = HospitalState()
state.update_for_time(datetime(2026, 4, 6, 22, 30), ops_config)  # 夜勤
delay = state.calculate_delay("ct", urgency="routine", ops_config=ops_config)
# → 例: 320 分 (utilization 0.4, radiology_staff 0.4 → 大きい staff_factor)
```

### `add_to_queue(resource: str, ops_config: dict) -> None`

オーダー受付時に呼び、 該当 queue の utilization を `1/capacity` だけ増やす (上限 0.95)。

```python
capacity = ops_config["resource_capacity"]["ct_scanners"]   # e.g., 2
state.ct_queue += 1 / capacity                              # +0.5
```

### `release_from_queue(resource: str, ops_config: dict) -> None`

オーダー完了時に呼び、 utilization を `1/capacity` だけ減らす (下限 0.0)。

リソース→capacity キーマッピング:

| Resource | Capacity key |
|---|---|
| `lab` | `lab_analyzers` |
| `ct` | `ct_scanners` |
| `mri` | `mri_scanners` |
| `xray` | `xray_rooms` |
| `ultrasound` | `ultrasound_rooms` |
| `or` | `operating_rooms` |

### `load_hospital_operations() -> dict`

`clinosim/config/hospital_operations.yaml` をロードして dict で返す (存在しなければ空 dict)。

```python
from clinosim.modules.facility.hospital_state import (
    HospitalState, load_hospital_operations,
)

ops = load_hospital_operations()
state = HospitalState()
state.update_for_time(datetime.now(), ops)
```

## データ構造

主要型:

| Type | 場所 | Key fields | 用途 |
|---|---|---|---|
| `HospitalState` | `clinosim/modules/facility/hospital_state.py:18` (`@dataclass`) | hospital 各 ward 別の bed occupancy / queue length / 各 staff 配置 | hospital 状態の runtime snapshot |

> 既知負債 (MOD-4, TYP-2): `HospitalState` は engine 内 `facility/hospital_state.py` に
> 定義 (CLAUDE.md "All types defined in clinosim/types/" 違反)。将来 PR_C 型統一で
> `clinosim/types/facility.py` への移行予定。

## キューイングモデル — 直感的な解説

M/M/1 待ち行列の平均滞在時間は `1 / (μ - λ)` で、 utilization `ρ = λ/μ` を使うと `T = (1/μ) / (1 - ρ)`。 ここから `congestion_factor = 1/(1-ρ)` を抽出している:

| Utilization | Congestion factor | 体感 |
|---|---|---|
| 0.10 | 1.11x | 空いている |
| 0.50 | 2.00x | 通常 |
| 0.80 | 5.00x (cap) | 忙しい |
| 0.95 | 5.00x (cap) | 限界 |

staff factor は同様に `1/staff` で、 「半分の人員 → 倍の時間」「1/4 → 4x」を表現する。 cap で 4x を上限とすることで、 0.1 staff 想定時の極端な遅延を回避する。

## 使用例

### 1 日のシフト遷移をシミュレート

```python
from datetime import datetime, timedelta
from clinosim.modules.facility.hospital_state import (
    HospitalState, load_hospital_operations,
)

ops = load_hospital_operations()
state = HospitalState()

day = datetime(2026, 4, 6, 0, 0)  # 月曜 00:00
for h in range(0, 24, 2):
    t = day + timedelta(hours=h)
    state.update_for_time(t, ops)
    delay = state.calculate_delay("ct", "routine", ops)
    print(f"{t:%H:%M} radiology={state.radiology_staff:.1f} "
          f"ct_routine TAT≈{delay:.0f} min")
```

### オーダーフロー (resource consumption)

```python
def order_ct(state, ops, urgency="routine"):
    delay_min = state.calculate_delay("ct", urgency, ops)
    state.add_to_queue("ct", ops)
    return delay_min

def complete_ct(state, ops):
    state.release_from_queue("ct", ops)

# Encounter engine からの呼び出しイメージ
for order in ct_orders:
    tat = order_ct(state, ops, order.urgency)
    schedule_completion(order, tat, callback=lambda: complete_ct(state, ops))
```

## 設定 YAML スキーマ

```yaml
# hospital_operations.yaml
staffing:
  day:
    lab_staff: 1.0
    radiology_staff: 1.0
    nursing_staff: 1.0
    pharmacy_staff: 1.0
    or_staff: 1.0
  evening:
    lab_staff: 0.6
    radiology_staff: 0.5
    ...
  night:
    lab_staff: 0.3
    radiology_staff: 0.2
    or_staff: 0.1
  weekend_modifier: 0.6

base_processing_time:
  lab_stat: 30
  lab_routine: 90
  ct_stat: 20
  ct_routine: 45
  mri_routine: 90
  ...

reporting_time:
  stat: 15
  routine: 120

resource_capacity:
  lab_analyzers: 4
  ct_scanners: 2
  mri_scanners: 1
  operating_rooms: 6

daily_patterns:
  morning_lab_rush:
    hours: [6, 9]
    lab_queue_delta: 0.20
```

## 依存関係

- 標準ライブラリ `dataclasses`, `datetime`, `pathlib`
- `pyyaml` — config ロード

他の clinosim モジュールには依存しない。 逆に `encounter`, `order`, `procedure` モジュールが本モジュールを呼び出して TAT を取得・queue を更新する。

## 既知の制約

- M/M/1 は単一サーバ近似。 実際は M/M/c (複数機器) だが capacity を簡略化して代替
- 患者個別の優先度 (triage level) は未対応 — urgency は stat/routine の 2 段階のみ
- 季節性 (インフルエンザシーズンの ED 混雑) は未モデル化
- リソース修理・故障イベント未対応
- staffing は連続値 (fraction) であり個別スタッフ ID とは紐付かない (staff モジュールが別途担当)

## 関連モジュール

- `clinosim.modules.staff` — 個別 Practitioner ロスター (本モジュールは集約 staffing level のみ扱う)
- `clinosim.modules.encounter` — オーダー発行と TAT 適用
- `clinosim.modules.order` — オーダー種別と urgency 設定
- `clinosim/config/hospital_operations.yaml` — 病床数・診療科・病棟・リソース容量の定義

## 修正ガイド

### 病院構成を変更する

- `clinosim/config/hospital_operations.yaml` を編集（50床 community hospital）
- `clinosim/config/hospital_small.yaml` を編集（10床 clinic）
- カスタム: `--hospital-config PATH` で独自 YAML を指定

### 新しい診療科を追加する

1. `hospital_operations.yaml` の `available_departments` に追加
2. `department_rollup` に細分化科 → 利用可能科のマッピング追加
3. `wards` + `ward_capacity` に病棟・ベッド数追加
4. `staff` モジュールの `_DEPT_PREFIX` に追加
5. FHIR: `locale/shared/department_display.yaml` に表示名（`en` / `ja`）を追加

### recommended_population の調整

```yaml
recommended_population:
  US: 40000   # 50 beds ÷ 130/100K ≈ 40K → ~80% occupancy
  JP: 10000   # admission throughput basis: 50×365×0.80/14d ≈ 1,043/yr
```

`-p` CLI オプションでも上書き可能。
