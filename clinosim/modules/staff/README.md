# clinosim.modules.staff — 医療従事者ロスター生成・割り当て

## 目的

病院の **医療スタッフ名簿 (roster)** を生成し、 臨床イベント (入院、回診、採血、画像読影、投薬等) に適切なスタッフを割り当てる。

CIF / FHIR の各 Resource には `performer` / `attending_physician` / `administering_nurse` 等の担当者参照が必要であり、 staff モジュールはその参照可能な ID とメタデータ (名前・所属・専門科・連絡先) を提供する。

特徴:

- **Department-aware**: hospital config の `available_departments` に合わせて医師数を配分
- **Ward-aware**: 看護師は病棟単位で配置 (1 看護師: 2 床を基準)
- **Locale-aware**: 国別の names.yaml から姓名をサンプル (日本語は姓・名の順、 英語は名・姓)
- **Role-based assignment**: `assign_staff()` がイベント種別と科から適切な role を選出

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **Hospital config ベース** | 部門数・病床・病棟は hospital_config (hospital_small.yaml 等) に従う |
| 2 | **科別 ID prefix** | `DR-IM-001` (内科)、 `DR-CA-003` (循環器)、 `NS-OR-012` (整形外科看護師) |
| 3 | **1 医師 : 5 床** 以上 (department 別) | 内科は 8 床に 1 人等、 dept ごとに heuristic 設定 |
| 4 | **1 看護師 : 2 床** + バッファ | `nurses_per_ward = max(6, beds_per_ward // 2 + 3)` |
| 5 | **性別バイアス** | 医師 M:F = 65:35、 看護師 M:F = 15:85 (統計的現実への一次近似) |
| 6 | **Fallback chain** | `assign_staff()` は dept 一致 → specialty 一致 → 任意の role の順 |

## API リファレンス

### `generate_roster(hospital_scale, country, rng, hospital_config=None) -> StaffRoster`

病院規模と国に応じた完全な staff roster を生成する。

```python
from clinosim.modules.staff.engine import generate_roster
import numpy as np

rng = np.random.default_rng(42)
roster = generate_roster(
    hospital_scale="medium",
    country="JP",
    rng=rng,
    hospital_config=load_hospital_config("hospital_medium.yaml"),
)
print(f"Total staff: {len(roster.members)}")
print(f"Physicians: {len(roster.get_by_role('physician'))}")
```

**生成ロジック**:

1. `hospital_config.available_departments` から対象科を取得 (デフォルト `["internal_medicine"]`)
2. `hospital_config.wards` から病棟マップを取得
3. `hospital_config.resource_capacity.inpatient_beds` から総病床
4. **医師** を科ごとに配分:
   ```python
   doctors_per_dept = {
       "internal_medicine":  max(4, beds_total // 8),
       "cardiology":         2,
       "pulmonology":        2,
       "gastroenterology":   2,
       "nephrology":         1,
       "endocrinology":      1,
       "neurology":          2,
       "general_surgery":    max(3, beds_total // 10),
       "orthopedics":        2,
       "neurosurgery":       2,
       "trauma_surgery":     2,
       "emergency_medicine": max(3, beds_total // 12),
       "primary_care":       2,
   }
   ```
5. **看護師** を病棟 (dept × ward) 毎に配置。 `beds_per_ward ≒ beds_total / n_wards`、 `nurses_per_ward ≒ max(6, beds_per_ward//2 + 3)`
6. **ED / OPD 看護師**: emergency_medicine / primary_care は各 5 名共通配置
7. **共通サービス**: 臨床検査技師 10 名、 放射線科医 4 名、 薬剤師 8 名

### `assign_staff(event_type, department, roster, rng) -> dict[str, str]`

臨床イベントに対し `{role_in_event: staff_id}` 辞書を返す。

```python
from clinosim.modules.staff.engine import assign_staff

assignments = assign_staff("admission", "pulmonology", roster, rng)
# → {"attending_physician": "DR-PU-003", "primary_nurse": "NS-PU-012"}

assignments = assign_staff("lab_collection", "", roster, rng)
# → {"performing_technician": "TECH-LAB-005"}
```

**イベント種別と割り当てロール**:

| event_type | 割り当て role | ソース |
|---|---|---|
| `admission` / `rounds` / `discharge` | `attending_physician`, `primary_nurse` | 科一致 → specialty 一致 → 任意の医師 |
| `lab_collection` / `lab_result` | `performing_technician` | 臨床検査技師 |
| `imaging_interpretation` | `interpreting_radiologist` | 放射線科医 |
| `medication_administration` | `administering_nurse` | 科一致の看護師、 なければ任意 |

## データ構造

### `StaffMember`

```python
@dataclass
class StaffMember:
    staff_id: str           # "DR-IM-001", "NS-OR-012", "TECH-LAB-005"
    name: str               # "山田 太郎" (JP) or "John Smith" (US)
    role: str               # "physician" | "nurse" | "lab_technician" |
                            # "radiologist" | "pharmacist"
    department: str         # "internal_medicine", "cardiology", ...
    specialty: str = ""     # 通常は department と同じ
    qualification_year: int = 2010
    sex: str = ""           # "M" | "F"
    phone: str = ""         # 内線・業務携帯
    email: str = ""         # "dr-im-001@hospital.example.org"
    ward: str = ""          # 看護師の主担当病棟 (例: "3E")
```

### `StaffRoster`

```python
@dataclass
class StaffRoster:
    members: list[StaffMember]

    def get_by_role(self, role: str, department: str = "") -> list[StaffMember]:
        """role 一致 + (dept 指定があれば一致) のメンバー"""

    def get_by_id(self, staff_id: str) -> StaffMember | None:
        """staff_id で 1 件検索 (線形走査)"""
```

### 科コード prefix

Staff ID 可読性のための prefix 対応表 (`_DEPT_PREFIX`):

| department | prefix |
|---|---|
| internal_medicine | IM |
| cardiology | CA |
| pulmonology | PU |
| gastroenterology | GI |
| nephrology | NE |
| endocrinology | EN |
| neurology | NR |
| general_surgery | GS |
| orthopedics | OR |
| neurosurgery | NS |
| trauma_surgery | TS |
| emergency_medicine | EM |
| primary_care | PC |
| obstetrics_gynecology | OB |
| pediatrics | PD |

例: `DR-CA-002` = 循環器科 2 人目の医師、 `NS-OR-015` = 整形外科 15 人目の看護師、 `TECH-LAB-003` = 検査技師 3 人目。

## 使用例: 入院時のスタッフ割り当て

```python
from clinosim.modules.staff.engine import generate_roster, assign_staff
import numpy as np

rng = np.random.default_rng(42)

# 1. Once per hospital setup
hospital_config = {
    "available_departments": ["internal_medicine", "cardiology", "pulmonology",
                              "general_surgery", "orthopedics", "emergency_medicine"],
    "wards": {
        "internal_medicine": ["3W", "4W"],
        "cardiology": ["CCU", "5E"],
        "pulmonology": ["4E"],
        "orthopedics": ["6W"],
        "emergency_medicine": ["ER"],
    },
    "resource_capacity": {"inpatient_beds": 200},
}
roster = generate_roster("medium", "US", rng, hospital_config)

# 2. On admission
encounter_department = "pulmonology"  # 肺炎症例
assignments = assign_staff("admission", encounter_department, roster, rng)
# {"attending_physician": "DR-PU-001", "primary_nurse": "NS-PU-008"}

# 3. Look up details
attending = roster.get_by_id(assignments["attending_physician"])
print(f"{attending.name} ({attending.specialty}), since {attending.qualification_year}")
# → "Michael Johnson (pulmonology), since 1998"

# 4. For each lab order
lab_staff = assign_staff("lab_collection", "", roster, rng)
# {"performing_technician": "TECH-LAB-007"}

# 5. For each imaging order
img_staff = assign_staff("imaging_interpretation", "", roster, rng)
# {"interpreting_radiologist": "DR-RAD-002"}
```

## 依存関係

- `clinosim.locale.loader.load_names` — 国別名前データ
- `numpy` — RNG, weighted choice
- `hospital_config` (dict) — 呼び出し側から注入 (ward マップ、 部門リスト、 病床数)

**他モジュールへの依存なし** (staff は独立したサービス)。

## 拡張方法

### 新しい科を追加する

1. `_DEPT_PREFIX` に科名 → 2 文字 prefix を追加
2. 必要なら `doctors_per_dept` 辞書に heuristic 数を追加 (無ければデフォルト 2 名)
3. hospital_config の `available_departments` と `wards` に追加
4. **コード変更は prefix 登録のみ** — 医師・看護師生成は既存フローが対応

### 新しいイベントタイプを追加する

`assign_staff()` の `match event_type:` に新しい case を追加:

```python
case "physiotherapy":
    pts = roster.get_by_role("physiotherapist")
    if pts:
        assignments["performing_therapist"] = rng.choice(pts).staff_id
```

新しい role を使う場合は `generate_roster()` に生成ロジックも追加。

## テスト

```bash
source .venv/bin/activate && python -m pytest tests/unit/test_staff.py -v
```

カバー範囲: ロスター生成 (scale 別)、 科別配分、 ward 配置、 assign_staff の fallback chain、 国別名前生成。

## 修正ガイド

### スタッフ名とFHIR出力の関係

- CIF `hospital.json` にスタッフロスター (staff_id, name, department) が格納される
- ナラティブ生成時: `document_generator._load_staff_names()` がロスターを読み込み、staff_id を実名に変換
  - JP: `佐伯 紬医師` (family given + 「医師」suffix)
  - US: `Dr. Smith`
- FHIR: `Practitioner.ndjson` にスタッフリソースとして出力

### 関連モジュール

| モジュール | 関係 |
|---|---|
| `locale` | `names.yaml` からスタッフ名を生成 (国別 surname/given) |
| `hospital_config` | `available_departments` でどの科のスタッフを生成するか決定 |
| `output/document_generator` | ナラティブで staff_id → name 変換 |
| `output/fhir_r4_adapter` | Practitioner + PractitionerRole FHIR リソース |
