# clinosim.modules.procedure — Procedure Engine Module

## 目的

外科手術 (surgery) と病棟ベッドサイド処置 (bedside procedure)、 およびリハビリセッションを **疾患・重症度ドリブン** で生成する。

clinosim では「肺炎なら気管支鏡 15%」「敗血症なら中心静脈ライン 70%」のような **疾患 → 処置の確率ルール** を本モジュールが管理し、 ProcedureRecord (CIF の一部) を出力する。 整形外科 (hip fracture) では disease YAML の `requires_surgery` フラグから手術記録を生成し、 術後リハビリを連動させる。

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **Disease-driven, not random** | 各処置は disease_id に対するルールマッチで発火。 無関係な患者には生成されない |
| 2 | **Severity scaling** | 重症度 (`severe`/`moderate`/`mild`) で確率が 1.3 / 1.0 / 0.5 倍 |
| 3 | **Code dual-encoding** | CPT (US) と K コード (JP) を両方持ち、 country で出力時に切替 |
| 4 | **State impact returned** | 手術は physiology state への影響 (出血 → 貧血、 組織損傷 → 炎症) を `state_impacts` 辞書で返す |
| 5 | **Deterministic with rng** | 全ての確率判定は引数で渡された `numpy.random.Generator` を使用 (AD-16) |
| 6 | **Rehab is post-op event** | リハビリセッションは手術日付からの相対 day で生成、 phase (early/mid/late) で活動内容を切替 |

## ディレクトリ構造

```
clinosim/modules/procedure/
├── __init__.py
├── README.md       # 本ドキュメント
├── SPEC.md
└── engine.py       # ProcedureRecord, RehabSession, simulate_surgery,
                    # generate_bedside_procedures, generate_rehab_sessions
```

## API リファレンス

### `ProcedureRecord` (dataclass)

```python
@dataclass
class ProcedureRecord:
    procedure_id: str = ""
    patient_id: str = ""
    encounter_id: str = ""
    procedure_type: str = ""        # Internal identifier: "ORIF" | "thoracentesis" | ...
    procedure_code: str = ""        # Primary code: K-code (JP) or CPT (US)
    procedure_code_jp: str = ""     # Always populated (for multilingual coding)
    procedure_code_us: str = ""     # Always populated
    # Per AD-30, display name is NOT stored in CIF — resolved at output time
    # via code_lookup("k-codes"|"cpt", code, lang).

    # Timing
    start_datetime: datetime
    end_datetime: datetime
    duration_minutes: int = 90

    # Team
    primary_surgeon_id: str = ""
    anesthesiologist_id: str = ""
    assistant_ids: list[str] = []

    # Anesthesia
    anesthesia_type: str = "general"  # "general" | "spinal" | "local" | "sedation"
    asa_class: int = 2

    # Findings
    estimated_blood_loss_ml: int = 300
    specimens_sent: list[str] = []
    implants_used: list[str] = []
    intraop_complications: list[str] = []

    # Pre/post
    preop_diagnosis: str = ""
    postop_diagnosis: str = ""

    # FHIR Procedure structural fields (SNOMED CT codes, resolved at output time)
    category_code: str = ""        # 387713003 (surgical) / 103693007 (diagnostic) / 277132007 (therapeutic)
    body_site_code: str = ""       # SNOMED body site (e.g., 71341001 = femur)
    outcome_code: str = ""         # 385669000 (successful) / 385670004 (partial) / 385671000 (unsuccessful)
    complication_codes: list[str] = []  # SNOMED complication codes
    location_id: str = ""          # FHIR Location id (e.g., "loc-or-2")
```

**`category_code` / `body_site_code`** は `_PROCEDURE_METADATA` (procedure_type → ProcedureMeta) から自動決定。 SNOMED CT コードの表示テキストは [`clinosim/codes/data/snomed-ct.yaml`](../../codes/data/snomed-ct.yaml) で解決される (en / ja)。

**`outcome_code`** は `intraop_complications` の有無で自動判定:
- 合併症なし → `385669000` (Successful)
- 合併症あり → `385670004` (Partially successful)

**`complication_codes`** は `intraop_complications` の内部キー ("excessive_bleeding" 等) を SNOMED コードにマップ:

| 内部キー | SNOMED |
|---|---|
| excessive_bleeding | 131148009 (Bleeding) |
| anesthesia_hypotension | 45007003 (Hypotension) |
| surgical_site_infection | 87317003 |
| ards | 67782005 |

**`location_id`** は手術時に `loc-or-1..N` (N = `hospital_config.resource_capacity.operating_rooms`) からランダム割当。 bedside procedure は空 (病棟で実施されるため)。

### `simulate_surgery(...) -> tuple[ProcedureRecord, dict[str, float]]`

```python
def simulate_surgery(
    patient: Any,
    disease_id: str,
    encounter_id: str,
    admission_time: datetime,
    protocol: Any,
    rng: np.random.Generator,
    country: str = "JP",
    surgeon_id: str = "",
    anesthesiologist_id: str = "",
) -> tuple[ProcedureRecord, dict[str, float]]: ...
```

主要疾患 (現状 hip fracture) の手術をシミュレートし、 ProcedureRecord と physiology state への影響を返す。

**Time-to-surgery** (国差):

| Country | 平均 (h) | sd (h) | 最小 (h) |
|---|---|---|---|
| JP | 48 | 24 | 12 |
| US | 24 | 12 | 6 |

US は "hip fracture surgery within 24h" 推奨を反映し早期手術。

**Hip fracture procedure 選択** (`disease_id == "hip_fracture"`):

| 確率 | Type | CPT | K-code | Implant |
|---|---|---|---|---|
| 55% | ORIF | 27236 | K0461 | compression hip screw or intramedullary nail |
| 45% | hemiarthroplasty | 27125 | K0811 | bipolar femoral prosthesis |

**ASA class 推定**: 既往疾患数と年齢から:

```python
asa = 2
if n_chronic_conditions >= 2 or age >= 80: asa = 3
if n_chronic_conditions >= 3 and age >= 85: asa = 4
```

**Intraoperative complications** (rng):

- 3% : `excessive_bleeding` (EBL × 2)
- 1% : `anesthesia_hypotension`

**State impacts** (返り値の 2 つ目):

| Key | 条件 | 値 |
|---|---|---|
| `anemia_level` | EBL > 200 | `EBL / 5000` (例: 500mL → +0.10) |
| `volume_status` | 常時 | +0.10 (術中輸液) |
| `inflammation_level` | 常時 | +0.10 (組織損傷) |
| `perfusion_status` | EBL > 800 | -0.10 |

```python
record, impacts = simulate_surgery(
    patient=patient_obj,
    disease_id="hip_fracture",
    encounter_id="ENC-0001",
    admission_time=datetime(2026, 4, 6, 14, 30),
    protocol=hip_fracture_protocol,
    rng=np.random.default_rng(seed=42),
    country="JP",
    surgeon_id="DR-001",
    anesthesiologist_id="DR-099",
)
# impacts e.g. {"anemia_level": 0.06, "volume_status": 0.10,
#               "inflammation_level": 0.10}
```

### `generate_bedside_procedures(...) -> list[ProcedureRecord]`

```python
def generate_bedside_procedures(
    patient_id: str,
    encounter_id: str,
    disease_id: str,
    admission_time: datetime,
    severity: str,                # "severe" | "moderate" | "mild"
    rng: np.random.Generator,
    country: str = "US",
) -> list[ProcedureRecord]: ...
```

疾患マッチング → 確率 × severity multiplier で複数のベッドサイド処置を生成する。 各処置は入院後 0.5h 〜 (median 6h) のオフセットで配置される。

**Severity multiplier**:

```python
{"severe": 1.3, "moderate": 1.0, "mild": 0.5}
```

複数ルールで同じ procedure_type が triggered されると **最高確率を採用** (重複生成しない)。

### Bedside procedure 一覧 (`_BEDSIDE_PROCEDURES`)

| Type | CPT | K-code | 名称 (en) | 麻酔 |
|---|---|---|---|---|
| `urinary_catheter` | 51702 | D002 | Urinary catheter insertion | none |
| `central_line` | 36556 | G005-2 | Central venous catheter insertion | local |
| `arterial_line` | 36620 | G005-3 | Arterial line insertion | local |
| `lumbar_puncture` | 62270 | D004 | Lumbar puncture | local |
| `thoracentesis` | 32555 | D010 | Thoracentesis | local |
| `paracentesis` | 49083 | D011 | Paracentesis | local |
| `intubation` | 31500 | J044 | Endotracheal intubation | sedation |
| `nasogastric_tube` | 43752 | J034 | Nasogastric tube insertion | none |
| `chest_tube` | 32551 | D012 | Chest tube insertion | local |
| `wound_debridement` | 97597 | K002 | Wound debridement | local |
| `cardioversion` | 92960 | K599 | Electrical cardioversion | sedation |
| `blood_transfusion` | 36430 | K920 | Blood transfusion | none |
| `dialysis_acute` | 90935 | J038 | Acute hemodialysis | none |
| `bronchoscopy` | 31622 | D302 | Bronchoscopy | sedation |
| `echocardiography` | 93306 | D215 | Transthoracic echocardiography | none |

CPT / K-code の正本は [`clinosim/codes/data/cpt.yaml`](../../codes/data/cpt.yaml) と [`clinosim/codes/data/k-codes.yaml`](../../codes/data/k-codes.yaml) を参照。

### Disease → procedure ルール (`_PROCEDURE_RULES`)

| Disease(s) | 生成される処置 (確率) |
|---|---|
| sepsis, acute_mi, heart_failure, stroke 系, severe trauma | urinary_catheter (0.85) |
| copd_exac, gi_bleeding, pancreatitis, DKA, liver cirrhosis, PE, AKI | urinary_catheter (0.50) |
| sepsis | central_line (0.70), arterial_line (0.50), blood_transfusion (0.15) |
| heart_failure_exacerbation | echocardiography (0.80), urinary_catheter (0.60) |
| acute_mi | arterial_line (0.60), central_line (0.40), echo (0.90) |
| cerebral_infarction, hemorrhagic_stroke | NG tube (0.30), echo (0.50) |
| hemorrhagic_stroke, subdural_hematoma | intubation (0.40), central_line (0.50), arterial_line (0.40) |
| gi_bleeding | NG tube (0.50), transfusion (0.60), central_line (0.30) |
| liver_cirrhosis_decompensated | paracentesis (0.70), NG tube (0.25), transfusion (0.30) |
| bacterial_pneumonia, aspiration_pneumonia | bronchoscopy (0.15), intubation (0.10) |
| diabetic_ketoacidosis | central_line (0.35), arterial_line (0.20) |
| pulmonary_embolism | echo (0.70), central_line (0.20) |
| ileus | NG tube (0.80) |
| acute_kidney_injury | dialysis_acute (0.30), central_line (0.40) |
| atrial_fibrillation_rvr | cardioversion (0.25), echo (0.60) |
| acute_pancreatitis | NG tube (0.40), central_line (0.20) |
| traffic_accident_severe | central_line (0.70), arterial_line (0.60), transfusion (0.50), intubation (0.30), chest_tube (0.25) |
| cellulitis | wound_debridement (0.30) |

(severity multiplier 適用前の値)

```python
import numpy as np
from datetime import datetime
from clinosim.modules.procedure.engine import generate_bedside_procedures

procs = generate_bedside_procedures(
    patient_id="PAT-0001",
    encounter_id="ENC-0001",
    disease_id="sepsis",
    admission_time=datetime(2026, 4, 6, 10, 0),
    severity="severe",
    rng=np.random.default_rng(42),
    country="JP",
)
for p in procs:
    print(p.procedure_type, p.procedure_code, p.start_datetime)
# urinary_catheter D002 2026-04-06 14:23:00
# central_line G005-2 2026-04-06 12:08:00
# arterial_line G005-3 2026-04-06 18:41:00
```

### `RehabSession` (dataclass)

```python
@dataclass
class RehabSession:
    session_id: str = ""
    patient_id: str = ""
    encounter_id: str = ""
    therapy_type: str = "PT"        # "PT" | "OT" | "ST"
    session_date: datetime
    duration_minutes: int = 40
    day_post_op: int = 0
    activities: list[str] = []
    patient_participation: str = "good"  # "good" | "fair" | "refused"
    pain_score: int | None = None
    functional_progress: str = "stable"   # "improved" | "stable" | "unable_to_assess"
```

### `generate_rehab_sessions(...) -> list[RehabSession]`

```python
def generate_rehab_sessions(
    patient_id: str,
    encounter_id: str,
    surgery_date: datetime,
    total_days: int,
    rng: np.random.Generator,
    country: str = "JP",
) -> list[RehabSession]: ...
```

POD 1 (post-op day 1) から開始する PT (理学療法) セッションを生成する。 セッション時刻は午前 10 時固定。 約 10% の日はランダムに skip (週末・体調)。

**Phase × activities**:

| Phase | POD range | Activities |
|---|---|---|
| early | 1–3 | bed exercises, sitting up, standing with assist |
| mid | 4–14 | walker ambulation, stair practice, transfer training |
| late | 15+ | independent ambulation, ADL practice, stair climbing |

各セッションで activities のうち最大 3 つをランダム選択。

**Pain score**: `N(4 - day*0.1, 1.5)` を [0, 10] にクランプ (POD が進むほど痛み軽減)。

**Participation**:

- pain > 6 → `fair`
- 5% 確率で `refused` (この場合 progress は `unable_to_assess`)

**Duration**: JP=40 分, US=30 分

```python
rehabs = generate_rehab_sessions(
    patient_id="PAT-0001",
    encounter_id="ENC-0001",
    surgery_date=datetime(2026, 4, 7, 9, 0),
    total_days=14,
    rng=np.random.default_rng(42),
    country="JP",
)
```

## 使用例

### Hip fracture フルパイプライン

```python
import numpy as np
from datetime import datetime
from clinosim.modules.procedure.engine import (
    simulate_surgery,
    generate_bedside_procedures,
    generate_rehab_sessions,
)

rng = np.random.default_rng(seed=42)
admission = datetime(2026, 4, 6, 14, 0)

# 1) Surgery
record, impacts = simulate_surgery(
    patient=patient, disease_id="hip_fracture",
    encounter_id="ENC-0001", admission_time=admission,
    protocol=hip_protocol, rng=rng, country="JP",
    surgeon_id="DR-ORTH-01", anesthesiologist_id="DR-ANES-01",
)

# 2) Bedside procedures (urinary catheter etc.)
bedside = generate_bedside_procedures(
    patient_id=patient.patient_id, encounter_id="ENC-0001",
    disease_id="hip_fracture", admission_time=admission,
    severity="moderate", rng=rng, country="JP",
)

# 3) Post-op rehab
rehabs = generate_rehab_sessions(
    patient_id=patient.patient_id, encounter_id="ENC-0001",
    surgery_date=record.start_datetime, total_days=14,
    rng=rng, country="JP",
)

# 4) Apply state impacts to physiology
for key, delta in impacts.items():
    physio_state[key] += delta
```

## 依存関係

- `numpy` — 確率分布・乱数
- 標準ライブラリ `dataclasses`, `datetime`
- `clinosim.codes` (間接) — CPT/K-code の表示テキスト解決は出力時に行う

本モジュールは clinosim の他モジュールに **依存しない**。 disease protocol オブジェクトはダックタイピングで受ける (`hasattr(protocol, "procedure")`)。

## 関連コード体系

- **CPT** — [`clinosim/codes/data/cpt.yaml`](../../codes/data/cpt.yaml) ([AMA CPT](https://www.ama-assn.org/practice-management/cpt))
- **K コード** — [`clinosim/codes/data/k-codes.yaml`](../../codes/data/k-codes.yaml) ([厚労省 診療報酬点数表](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000188411.html))

## 既知の制約

- 手術は hip fracture 以外の disease では generic な "surgery" record になる (procedure_code 空)
- 術中合併症は 2 種類のみ (出血、 麻酔低血圧)。 神経損傷・感染等は未実装
- リハビリは PT のみ生成 (OT/ST の自動生成は未実装)
- 処置の team assignment は最低限 (assistant_ids 空、 staff モジュールとの統合が課題)
- 退院処方の影響 (抗凝固開始等) との連動は disease engine 側で処理
