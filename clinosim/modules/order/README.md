# clinosim.modules.order — Order Engine Module

## 目的

**疾患プロトコル (YAML) の抽象的なオーダー記述 → 具体的な `Order` インスタンス** への展開を担当する。 また各オーダーの **結果が利用可能になる時刻** を計算する (検査・画像)。

本モジュールが扱うオーダー種別:

- **Lab orders** — 血液検査、尿検査、培養など
- **Imaging orders** — X線、CT、MRI、エコー
- **Medication orders** — 抗菌薬、対症療法薬、在宅薬継続
- **Supportive orders** — 輸液、DVT 予防、モニタリング等
- **Care plan / therapy orders** — NPO、転倒予防、体位管理等 (非薬物)

結果時刻計算は **2 つのモード** を持つ:

1. **Legacy mode** (`calculate_lab_result_time`, `calculate_imaging_result_time`) — urgency + 時刻 + 曜日 + ランダム混雑 で統計的にモデル化
2. **Hospital-state-aware mode** (`calculate_result_time_from_state`) — 病院リソース状態 (lab / CT / MRI の待ち行列) と `ops_config` から遅延を導出

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **Protocol is the truth** | オーダー内容は disease YAML の `order_protocols.admission_orders` / `.daily_monitoring` / `drugs` から展開 |
| 2 | **Fallback chain** | `order_protocols` が無い疾患は `expected_lab_distributions` / `drugs` からフォールバック |
| 3 | **Country-aware** | JP / US で lab frequency と薬剤選択が切り替わる |
| 4 | **Idempotent enrich** | `enrich_medication_order` は何度呼んでも安全 (既に埋まっているフィールドは上書きしない) |
| 5 | **Decimal RNG 注入** | 全ての stochastic 処理は `rng: numpy.random.Generator` を受け取る (AD-16) |
| 6 | **Queueing integration** | hospital state がある場合は待ち行列モデルで遅延を計算 |
| 7 | **Night / weekend awareness** | 22:00–06:00 の non-stat は翌朝延期。週末は lab/imaging 遅延 |

## ディレクトリ構造

```
clinosim/modules/order/
├── __init__.py
├── engine.py          # order placement + result timing (≈ 460 行)
├── panel_grouping.py  # classify_lab_specs — panel-aware Order generation (PR1)
├── reference_data/
│   └── lab_panel_groups.yaml  # panel → member tests canonical mapping
├── README.md
└── SPEC.md
```

## パネル集約 Order 生成 (PR1, 2026-06-29)

`panel_grouping.py` は lab Order をパネルメンバーか単独オーダーかに分類し、
FHIR `ServiceRequest` 生成 (`_fhir_service_request.py`) と結果タイミング計算の
**シングル編集ポイント** を提供する (AD-61)。

### `Order.panel_key` フィールド

`clinosim/types/encounter.py` の `Order` dataclass に追加された 1 フィールド:

| フィールド | 型 | セマンティクス |
|---|---|---|
| `panel_key` | `str` | 空文字 = 単独オーダー。非空 = パネル識別子 (e.g. `"CBC"`, `"BMP"`) |

同一 encounter-day のパネルメンバーは同じ `panel_key` + `ordered_datetime` を共有する。
これにより `_fhir_service_request.py` が `(encounter_id, panel_key, ordered_datetime)` を
グループキーとして 1 SR に集約できる (AD-61)。

### `classify_lab_specs(specs, rng) -> list[ClassifiedOrder]`

```python
from clinosim.modules.order.panel_grouping import classify_lab_specs

specs = [
    {"test": "CBC", "probability": 1.0, "urgency": "stat"},
    {"test": "CRP", "probability": 0.8, "urgency": "routine"},
]
classified = classify_lab_specs(specs, rng)
# CBC spec → panel_key="CBC", shared ordered_datetime (同一 panel で揃える)
# CRP spec → panel_key=""   (CBC パネルの member ではない)
```

**2-pass アルゴリズム:**

1. **Pass 1 (パネル検出)** — `lab_panel_groups.yaml` でパネルメンバーを確認し、
   マッチしたメンバーに `panel_key` とパネル共有 `ordered_datetime` を割り当てる。
   RNG draw はパネル単位で 1 回 (AD-16)。
2. **Pass 2 (単独オーダー)** — パネルに未参加の spec に `panel_key=""` と
   個別 `ordered_datetime` を割り当てる。

`place_admission_orders` と `place_daily_lab_orders` はいずれも `classify_lab_specs`
を経由する。コールサイトにパネル検出 if/elif をインラインで書かない — `lab_panel_groups.yaml`
に新パネルを追加するだけで全オーダーサイトに自動到達する
(`scenario_flags_from_protocol` / `medication_flags_from_context` と同じ DRY パターン)。

### `lab_panel_groups.yaml` (canonical loader)

`order/reference_data/lab_panel_groups.yaml` がパネル → メンバーテスト名のマスター。
ロードは `panel_grouping.load_panel_groups()` (`@lru_cache(maxsize=1)`) のみ経由。
出力側 `_fhir_service_request.py` も同一 loader を使う (single source of truth)。

```yaml
CBC:
  loinc_panel: "58410-2"
  members: [WBC, Hb, Hct, Plt]
BMP:
  loinc_panel: "24323-8"
  members: [Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]
```

### FHIR ServiceRequest との契約

`_fhir_service_request.py` は `CIFPatientRecord` の全 encounter の orders を走査し:

- `panel_key` が非空のオーダーを `(encounter_id, panel_key, ordered_datetime)` でグループ化
  → 1 SR per group
- `panel_key` が空 (単独) オーダー → 1 SR each

SR の `basedOn[]` は同グループの Observation を参照。
`authoredOn` はグループ共通 `ordered_datetime`。

## 画像オーダー固有フィールド (Tier 1 #2, AD-62)

`Order` dataclass に追加された imaging-specific フィールド群:

| フィールド | 型 | セマンティクス |
|---|---|---|
| `imaging_modality` | `str` | DCM コード (CR / CT / MR / US / NM / ...) |
| `imaging_body_site_code` | `str` | SNOMED CT 身体構造コード (例: 51185008 = 胸部構造) |
| `imaging_views` | `list[str]` | ビューラベル (例: `["PA", "Lateral"]`)。Imaging enricher が ImagingStudy.series に展開する。空のときは `modalities.yaml:default_views_by_body_site` からフォールバック |
| `imaging_spec_meta` | `dict` | 画像オーダー固有のメタデータ (例: `abnormal_rate_by_severity`)。Imaging enricher が DiagnosticReport 所見テンプレート選択に使用 |

### FHIR ServiceRequest との契約 (imaging)

`_fhir_service_request._build_imaging_service_requests` は IMAGING OrderType のオーダーを走査し:

- `imaging_modality` が非空 → 通常の imaging SR を emit
- `imaging_modality` が空 (legacy Chest_Xray / CT 等) → SR は emit されるが ImagingStudy は生成されない (imaging enricher がスキップ)
- 1 Order = 1 SR。マルチシリーズ (PA + Lateral CXR 等) は 1 ImagingStudy の series[] で表現

### `place_imaging_orders(protocol, patient_id, encounter_id, admission_time, rng) -> list[Order]`

Disease YAML の `imaging_orders[]` から imaging-metadata-filled Order を生成する。
各 Order に `imaging_modality` / `imaging_body_site_code` / `imaging_views` / `imaging_spec_meta` を設定するシングル編集ポイント (AD-62)。
コールサイトで imaging_modality を直接セットしない — この関数経由のみ (classify_lab_specs / scenario_flags_from_protocol と同じ DRY パターン)。

## 権威ソース

| データ | ソース |
|---|---|
| **TAT (turnaround time)** 分布 | CAP Q-Probes studies, JSLM 臨床検査 TAT 調査 |
| **投薬頻度トークン** (qid, q6h 等) | 標準医薬品処方用語 (Micromedex, 日本薬局方) |
| **Routing (PO/IV/SC/...)** | 標準投与経路略号 (HL7 ActCode ROUTE) |

## API リファレンス

### `place_admission_orders(protocol, patient_id, encounter_id, admission_time, country, rng, ordered_by="") -> list[Order]`

入院時オーダーセットを展開する (`engine.py:98`)。

**Args**:
- `protocol` — `DiseaseProtocol.model_dump()` の辞書 (または YAML から直接読み込んだ dict)
- `patient_id`, `encounter_id` — ID
- `admission_time` — 入院時刻
- `country` — `"JP"` or `"US"` (薬剤選択に使用)
- `rng` — Generator
- `ordered_by` — 発注者 ID (オプション)

**展開内容**:

1. **Labs** — `order_protocols.admission_orders.labs` (なければ `expected_lab_distributions.admission` からフォールバック)。各 lab は probability フィールドで確率的に発注
2. **Supportive** — デフォルト: `IV_fluid NS 80-125 mL/h` + `DVT_prophylaxis Enoxaparin 2000IU SC daily`
3. **Imaging** — デフォルト: `Chest_Xray stat`
4. **Medications** — `drugs.first_line.<country>` から 1 剤選択 (empiric antibiotic)

**Order ID 規則**: `ORD-<patient>-ADM-L<nn>` (lab) / `ADM-M01` (med) / `ADM-S<nn>` (supportive) / `ADM-I<nn>` (imaging)

**Supportive 分類** (`engine.py:190`): `_MED_TYPES` と `_CARE_PLAN_TYPES` の 2 セットで `OrderType.MEDICATION` と `OrderType.THERAPY` に振り分ける。 例: `IV_fluid`, `DVT_prophylaxis`, `antibiotic` → MEDICATION / `NPO`, `bed_rest`, `fall_precautions` → THERAPY。

```python
from clinosim.modules.order.engine import place_admission_orders
from clinosim.modules.disease.protocol import load_disease_protocol

protocol = load_disease_protocol("bacterial_pneumonia").model_dump()
orders = place_admission_orders(
    protocol=protocol,
    patient_id="P-000001",
    encounter_id="ENC-P-000001-000001",
    admission_time=datetime(2024, 1, 15, 14, 30),
    country="JP",
    rng=np.random.default_rng(42),
    ordered_by="DR-001",
)
# 典型的に 10-15 件: WBC, CRP, 電解質, Cr, 血液ガス, CXR, 抗菌薬, 輸液, DVT予防
```

### `place_daily_lab_orders(protocol, patient_id, encounter_id, day_number, order_time, lab_frequency_multiplier, rng, ordered_by="") -> list[Order]`

日次モニタリング lab を発注する (`engine.py:247`)。

**Args**:
- `day_number` — 入院何日目 (Day 0 = 入院日)
- `order_time` — 発注時刻 (通常は morning_labs: 06:30)
- `lab_frequency_multiplier` — country-specific 修正係数 (例: JP=1.3, US=0.8)

**ロジック** (`engine.py:263`):

- `order_protocols.daily_monitoring.labs` を読む (なければ CRP + WBC + Creatinine をデフォルト)
- `frequency: "every_3_days"` → 3 日に 1 回
- `frequency: "daily"` + `japan_modifier` + `lab_frequency_multiplier` → effective freq が 1.0 未満なら確率的にスキップ
- `probability < 1.0` は physician discretion として確率発注

```python
from clinosim.modules.order.engine import place_daily_lab_orders

orders = place_daily_lab_orders(
    protocol=protocol,
    patient_id="P-000001",
    encounter_id="ENC-P-000001-000001",
    day_number=3,
    order_time=datetime(2024, 1, 18, 6, 30),
    lab_frequency_multiplier=1.3,   # JP
    rng=rng,
)
```

### `parse_dose_string(dose_str) -> dict[str, Any]`

`"500mg PO BID"` のような投薬文字列を構造化フィールドに分解する (`engine.py:59`)。

**戻り値 dict** (全て optional):
- `dose_quantity` (float), `dose_unit` (str)
- `route` (str): `PO` / `IV` / `SC` / `IM` / `SL` / `PR` / `NG` / `INHALED` / `TOPICAL` / `NEBULIZED`
- `frequency` (str): `QD`, `BID`, `TID`, `QID`, `Q6H`, ...
- `frequency_per_day` (int)

```python
from clinosim.modules.order.engine import parse_dose_string

parse_dose_string("500mg PO BID")
# {"dose_quantity": 500.0, "dose_unit": "mg", "route": "PO",
#  "frequency": "BID", "frequency_per_day": 2}

parse_dose_string("1g IV q8h")
# {"dose_quantity": 1.0, "dose_unit": "g", "route": "IV",
#  "frequency": "Q8H", "frequency_per_day": 3}

parse_dose_string("Levofloxacin")
# {}  (parseable components なし)
```

**Frequency tokens** (`engine.py:17`):

```python
_FREQ_PER_DAY = {
    "once": 1, "qd": 1, "daily": 1,
    "bid": 2, "q12h": 2,
    "tid": 3, "q8h": 3,
    "qid": 4, "q6h": 4,
    "q4h": 6, "q3h": 8, "q2h": 12,
    "continuous": 24, "drip": 24,
}
```

### `enrich_medication_order(order, dose_str="") -> Order`

`Order` オブジェクトの薬剤関連フィールドを後付けで充填する (`engine.py:28`)。 idempotent — 既に値があるフィールドは保持。

```python
from clinosim.modules.order.engine import enrich_medication_order

order = Order(
    order_id="ORD-001",
    display_name="Ceftriaxone 1g IV q24h",
    order_type=OrderType.MEDICATION,
    # dose/frequency/route が未設定
    ...
)
enrich_medication_order(order, dose_str="1g IV q24h")
# order.dose_quantity == 1.0
# order.dose_unit == "g"
# order.route == "IV"
# order.frequency == "Q24H" (または Q24H → daily fallback)
# order.frequency_per_day == 1
```

フォールバック戦略:
1. `dose_str` 引数を `parse_dose_string` でパース
2. それでも空なら `order.display_name` をパース
3. 薬剤名から route 推測 (`simulator.helpers._determine_route`)
4. dose_quantity があって frequency が無ければ `DAILY` / 1 をデフォルト

### `calculate_lab_result_time(order, rng) -> datetime`

Lab 結果利用可能時刻を統計モデルで計算 (`engine.py:306`)。

**モデル**:

| 要因 | 効果 |
|---|---|
| **Base (stat)** | N(45, 15) 分 |
| **Base (routine)** | N(120, 30) 分 |
| **夜間 (22:00–06:00), non-stat** | 翌朝 06:30 + N(90, 30) 分に繰越 |
| **週末 (Sat/Sun)** | base ×1.5 (+ routine はさらに ×1.3) |
| **混雑 (15% 確率)** | +Exp(30) 分 |
| **夕方 (17:00–22:00)** | base ×1.2 |
| **Minimum** | 15 分 |

```python
from clinosim.modules.order.engine import calculate_lab_result_time

result_time = calculate_lab_result_time(order, rng)
# stat の場合 ~45 分後、 routine 平日昼 ~2 時間後、夜間 routine は翌朝
```

### `calculate_imaging_result_time(order, rng) -> datetime`

画像検査の結果時刻を計算 (`engine.py:350`)。 scheduling delay + reporting delay の合計。

**Scheduling delay**:

| 検査 | stat | routine |
|---|---|---|
| CT | N(60, 20) 分 | N(240, 120) 分 |
| MRI | N(60, 20) 分 | N(1440, 480) 分 (1–2日) |
| Echo / Ultrasound | — | N(180, 60) 分 |
| X-ray (その他) | N(30, 10) 分 | N(60, 30) 分 |

**Reporting delay**:
- stat: N(30, 10) 分
- routine: N(240, 120) 分 (2–6h)

**週末補正**: ×1.5, さらに MRI non-stat は +24h (月曜繰越)
**夜間 non-stat**: 翌朝 6:00 まで繰延

### `calculate_result_time_from_state(order, hospital_state, ops_config, rng) -> datetime`

病院 state-aware な結果時刻計算 (`engine.py:405`)。待ち行列モデル統合。

**ロジック**:

1. `order.display_name` から resource 種別を判定 (`lab` / `xray` / `ct` / `mri` / `ultrasound`)
2. `hospital_state.update_for_time(ordered, ops_config)` で現時点の稼働状況に更新
3. `hospital_state.calculate_delay(resource, urgency, ops_config)` → 基本遅延
4. ±20% のランダムバリエーション
5. 夜間 non-stat は翌朝繰越
6. `hospital_state.add_to_queue(resource, ops_config)` で待ち行列に追加

`hospital_state is None` の場合は `calculate_lab_result_time` にフォールバック。

これにより **遅延がハードコード値ではなく病院リソース使用率から emerge する** 動的モデルになる。 多数患者を同時シミュレートすると自然に "混雑時間帯で結果が遅れる" 現象が現れる。

## データ構造

主要型 (`clinosim/types/encounter.py` に集約):

| Type | 場所 | Key fields | 用途 |
|---|---|---|---|
| `Order` | `clinosim/types/encounter.py:133` (`@dataclass`) | `order_id`, `patient_id`, `encounter_id`, `order_type` (`OrderType`), `display_name`, `urgency`, `clinical_intent`, `ordered_datetime`, `ordered_by`, `status` (`OrderStatus`), `result` (`OrderResult \| None`), `dose_quantity`, `dose_unit` 等 | lab/medication/imaging/procedure/consultation 等の order 統合型 |
| `OrderResult` | `clinosim/types/encounter.py:92` (`@dataclass`) | `result_datetime`, `performed_by`, `lab_name`, `value` (`float \| str \| None`), `unit`, `reference_range`, `flag` (H/L/critical), `interpretation`, `specimen_note` | lab order 結果 |
| `OrderType` | `clinosim/types/encounter.py:71` (`str Enum`) | LAB / IMAGING / MEDICATION / PROCEDURE / CONSULTATION / DIET / THERAPY / INFECTION_CONTROL | order 種別 |
| `OrderStatus` | `clinosim/types/encounter.py:82` (`str Enum`) | PLACED / ACCEPTED / IN_PROGRESS / RESULTED / CANCELED / SUSPENDED | order 状態 |
| `PrescriptionRecord` | `clinosim/types/encounter.py:121` (`@dataclass`) | 退院処方 items | 退院処方用 |
| `MedicationAdministration` | `clinosim/types/encounter.py:105` (`@dataclass`) | MAR (Medication Administration Record) | 投与記録 |

> `clinosim/types/encounter.py` は **`Order` / `OrderResult` / `OrderType` / `OrderStatus` /
> `Encounter` / `MedicationAdministration` / `VitalSignRecord` / `NursingRiskAssessment` 等を集約**。
> import は `from clinosim.types.encounter import Order, OrderType, OrderStatus`。

## 使用例

### Simulator の admission フロー

```python
from datetime import datetime
import numpy as np
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.order.engine import (
    place_admission_orders, place_daily_lab_orders,
    calculate_result_time_from_state,
)

protocol = load_disease_protocol("bacterial_pneumonia").model_dump()
rng = np.random.default_rng(42)

# Day 0: admission orders
orders = place_admission_orders(
    protocol, "P-001", "ENC-P-001-000001",
    admission_time=datetime(2024, 1, 15, 14, 30),
    country="JP", rng=rng,
)

# 各オーダーの結果時刻を計算 (hospital state があれば動的)
for o in orders:
    if o.order_type.value in ("lab", "imaging"):
        o.result_datetime = calculate_result_time_from_state(
            o, hospital_state, ops_config, rng,
        )

# Day 3: daily monitoring
daily = place_daily_lab_orders(
    protocol, "P-001", "ENC-P-001-000001",
    day_number=3,
    order_time=datetime(2024, 1, 18, 6, 30),
    lab_frequency_multiplier=1.3,  # JP
    rng=rng,
)
```

### 薬剤オーダーの後付け enrichment

```python
from clinosim.modules.order.engine import enrich_medication_order
from clinosim.types.encounter import Order, OrderType, OrderStatus

order = Order(
    order_id="ORD-X",
    encounter_id="E",
    patient_id="P",
    order_type=OrderType.MEDICATION,
    display_name="Amoxicillin 500mg PO TID",
    # dose fields 未設定
    status=OrderStatus.PLACED,
    ordered_datetime=datetime.now(),
)
enrich_medication_order(order)
assert order.dose_quantity == 500.0
assert order.dose_unit == "mg"
assert order.route == "PO"
assert order.frequency_per_day == 3
```

## 拡張方法

### 新しい frequency トークンを追加する

`_FREQ_PER_DAY` に追加:

```python
_FREQ_PER_DAY["q1h"] = 24
_FREQ_PER_DAY["q30min"] = 48
```

### 新しい supportive type を追加する

`place_admission_orders` 内の `_MED_TYPES` または `_CARE_PLAN_TYPES` に追加:

```python
_MED_TYPES.add("new_drug_category")
_CARE_PLAN_TYPES.add("new_care_plan_type")
```

未分類のタイプは `"drug"` 部分文字列ヒューリスティックで判定される。

### 新しい imaging resource を追加する

`calculate_imaging_result_time` と `calculate_result_time_from_state` の両方に match ブロックを追加:

```python
# calculate_result_time_from_state
elif "PET" in name_upper:
    resource = "pet"
```

`ops_config` に `pet` リソースの定義 (`capacity`, `slot_duration_minutes` 等) も合わせて追加する。

### 新しい疾患のデフォルトオーダーを定義する

ベストプラクティスは疾患 YAML の `order_protocols` セクションに明示する (engine 変更なし):

```yaml
order_protocols:
  admission_orders:
    labs:
      - {test: "WBC", probability: 1.0, urgency: "stat", code_loinc: "6690-2"}
      - {test: "CRP", probability: 1.0, urgency: "stat"}
      - {test: "Procalcitonin", probability: 0.6, urgency: "stat"}
    imaging:
      - {test: "Chest_Xray", urgency: "stat"}
    supportive:
      - {type: "IV_fluid", detail: "NS 100 mL/h"}
  daily_monitoring:
    labs:
      - {test: "CRP", frequency: "daily", japan_modifier: 1.0}
      - {test: "Creatinine", frequency: "every_3_days"}
```

## 依存関係

本モジュールが依存するもの:

| 依存先 | 用途 |
|---|---|
| `clinosim.types.encounter` | `Order`, `OrderType`, `OrderStatus` |
| `clinosim.simulator.helpers._determine_route` | 薬剤名からの経路ヒューリスティック (enrich_medication_order 内) |
| `numpy` | RNG |
| `order/reference_data/lab_panel_groups.yaml` | パネル → メンバー canonical mapping (PR1, panel_grouping.py) |

## Consumers

このモジュールに依存するもの:

| Caller | How | Impact |
|---|---|---|
| `simulator/inpatient.py` | admission orders + daily cycle 時にオーダー発行、Pass-1/Pass-2 lab loop でオーダー消費 | core (主 simulation loop) |
| `simulator/emergency.py` | ED visit のオーダー発行 + lab 結果生成 | core |
| `modules/encounter` | Daily cycle event (`morning_labs`) から `place_daily_lab_orders()` を呼ぶ | medium |
| `modules/observation` (README cross-ref) | 結果時刻経過後に観測値生成をトリガ | medium |
| `modules/procedure` (README cross-ref) | 手術・手技オーダーを拡張 | medium |
| `modules/output/_fhir_service_request.py` | `classify_lab_specs` + `load_panel_groups()` を使い FHIR ServiceRequest を生成 (PR1, AD-61) | medium |

## テスト

```bash
# 単体テスト
pytest tests/unit/test_order.py -v

# parse_dose_string の網羅
pytest tests/unit/test_order.py::test_parse_dose_string -v

# 結果時刻モデルのテスト
pytest tests/unit/test_order.py::test_lab_result_time -v
```

テスト観点:

- `parse_dose_string("500mg PO BID")` が期待通りパースされること
- `parse_dose_string("")` が空 dict を返すこと
- `place_admission_orders` が disease YAML から少なくとも 1 つの lab, 1 つの med, 1 つの imaging を生成すること
- `calculate_lab_result_time` の stat オーダーが平均 ~45 分で遅延すること
- 夜間 routine が翌朝に繰越されること
- 週末 ×1.5 が適用されること
- `enrich_medication_order` が idempotent (2 回呼んでも値が変わらない) であること

## 実装状況

- [x] Admission order expansion from protocol YAML
- [x] Daily monitoring lab orders with frequency adjustment (country + protocol)
- [x] Lab result timing model (stat vs routine, night deferral, weekend, congestion)
- [x] Imaging result timing (CT/MRI/Echo/Xray 個別モデル)
- [x] Hospital-state-aware delay calculation (queueing integration)
- [x] Dose string parser (`parse_dose_string`)
- [x] Medication order enrichment (idempotent)
- [ ] Medication order recurring schedule (MAR auto-expansion)
- [ ] Trigger order evaluation (protocol triggers like "stat lactate if febrile")
- [ ] Equipment capacity constraints with priority preemption

## 修正ガイド（追加情報）

### 薬品追加時の関連ファイル

| ファイル | 目的 | 例 |
|---|---|---|
| disease YAML `drugs.first_line` | 入院時の薬剤オーダー | `{drug: "Meropenem", dose: "1g IV q8h"}` |
| `locale/shared/chronic_medications.yaml` | 慢性疾患の常用薬 | `drug_ja` フィールドでJP名 |
| `locale/shared/drug_names_ja.yaml` | FHIR JP 出力用辞書 | `Meropenem: "メロペネム"` |
| `locale/{jp,us}/code_mapping_drug.yaml` | 薬品名 → RxNorm/YJ コード | |

### 薬品名の AD-30 原則

- CIF には **英語薬品名** を格納 (Order.display_name, MAR.drug_name)
- JP FHIR 出力時は `_localize_drug_name()` が `drug_names_ja.yaml` で変換
- **空文字の drug_name はスキップ** される (FHIR adapter 側のフィルタ)
- プロトコル接頭辞 (`DVT_prophylaxis:` 等) は FHIR adapter で `_strip_protocol_prefix()` により分離 (AD-50)
