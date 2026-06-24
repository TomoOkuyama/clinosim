# clinosim.modules.observation — Observation (Lab Result) Module

## 目的

clinosim の **Layer 3: 測定ノイズ層** を実装する。

physiology モジュールが患者の真の生理学的状態から導いた **true value** を受け取り、 現実の臨床検査で観察される以下の 3 つのゆらぎを加えて観測値を返す:

1. **Biological variation (CVi)** — 同一個体内の時間的変動 (Ricos et al. desirable variation)
2. **Analytical variation (CVa)** — 検査機器の精度限界 (instrument imprecision)
3. **Reporting precision** — 臨床で実際に報告される桁数への丸め

さらに、検査値に応じた **フラグ判定** (H / L / critical) と **UCUM 単位付与** を担当する。

本モジュールは clinosim の **lab result 生成の単一情報源** — 他モジュールが独自にノイズを加えることはない。

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **3-layer noise model** | CVi + CVa を独立に乗せる。生物学的 vs 分析的の区別を保持 |
| 2 | **UCUM 単位必須** | 全検査値は FHIR R4 Observation 互換の UCUM 表記 |
| 3 | **決定論的** | 呼出側が `rng: np.random.Generator` を渡す。グローバル状態なし (AD-16) |
| 4 | **Negative-safe + 生理学クランプ** | 観測値は 0 下限に加え、アナライト別 `PHYSIOLOGIC_LIMITS` (ヒト生存域の縁) で再クランプ。ノイズのテールが生命非両立値 (K 10.5, CRP 663 等) を生むのを防ぐ。真に極端な true 値は通過 |
| 5 | **Qualitative 検査対応** | 尿検査・培養・Strep 迅速など文字列結果も同じ API で扱える |
| 6 | **Sex-aware reference ranges** | Hb, Creatinine 等は性差対応 |
| 7 | **Panic value 独立判定** | H/L とは別に critical flag (K<2.5, Hb<7, pH<7.1 など) を返す |

## ディレクトリ構造

```
clinosim/modules/observation/
├── __init__.py
├── engine.py      # 全ロジック (約 200 行)
├── README.md
└── SPEC.md
```

## 権威ソース

| データ | ソース |
|---|---|
| **Biological CVi** | [Ricos et al. "Biological Variation Database"](https://biologicalvariation.eu/) — desirable within-individual variation |
| **Analytical CVa** | 各機器メーカーの仕様 + EQAS 調査 (CAP, RCPAQAP 等) |
| **Reporting precision** | 日本臨床検査標準協議会 JCCLS / CLSI ガイドライン |
| **UCUM 単位** | [UCUM](https://ucum.org/) — FHIR R4 Observation 必須 |
| **Reference ranges (default)** | [JCCLS 共用基準範囲 2022](https://www.jccls.org/) / Tietz Clinical Guide → 呼出側が `clinosim.locale.load_reference_ranges()` で上書き可 |
| **Panic values** | CAP Critical Values Guidelines, JCI Accreditation Standards |

## API リファレンス

### `generate_lab_result(lab_name, true_value, rng) -> float | str`

フルパイプラインのエントリーポイント (`engine.py:117`)。 生理学モジュールが算出した true value に対して variability を加え、 精度丸めしてから返す。定性検査の場合は文字列カテゴリを返す。

```python
import numpy as np
from clinosim.modules.observation.engine import generate_lab_result

rng = np.random.default_rng(42)

# 定量検査
crp = generate_lab_result("CRP", true_value=38.2, rng=rng)
# → 40.1  (float, 1 decimal)

k = generate_lab_result("K", true_value=4.2, rng=rng)
# → 4.3  (float, 1 decimal)

# 定性検査
ua = generate_lab_result("Urinalysis", true_value=0.0, rng=rng)
# → "1+ leukocytes"  (str)
```

**Args**:
- `lab_name` — 内部 test name (例: `"CRP"`, `"WBC"`, `"Urinalysis"`)
- `true_value` — 生理学層から導出された真値 (単位は `LAB_UNITS[lab_name]`)
- `rng` — 呼出側の decimal RNG

**Returns**: `float` (定量) または `str` (定性検査)。 定性検査は `_QUALITATIVE_TESTS` (現状 `Urinalysis`, `Urine_culture`, `Rapid_Strep`, `Tetanus_status`) のとき。

### `apply_realistic_variability(lab_name, true_value, rng) -> float`

3-layer noise を手動で適用したい場合に使う (`engine.py:89`)。

```python
from clinosim.modules.observation.engine import apply_realistic_variability

observed = apply_realistic_variability("Creatinine", 1.25, rng)
# 1.25 に対して bio (CVi=5.6%) + analytical (CVa=3%) の独立ガウスノイズ
```

**モデル**:

```
observed = true + N(0, true·CVi) + N(0, true·CVa)
observed = max(0, observed)
```

`true_value <= 0` の場合はそのまま 0 を返す。 未登録の lab は CVi=5%, CVa=3% にデフォルト。

### `round_to_precision(lab_name, value) -> float`

臨床で報告される桁数に丸める (`engine.py:108`)。

```python
round_to_precision("CRP", 38.237)        # 38.2  (1 decimal)
round_to_precision("Na",  140.8)         # 141   (0 decimal)
round_to_precision("Troponin", 0.01234)  # 0.012 (3 decimal)
round_to_precision("Unknown", 1.2345)    # 1.2   (default 1 decimal)
```

### `get_lab_unit(lab_name) -> str`

検査名から UCUM 単位を取得 (`engine.py:84`)。

```python
get_lab_unit("Na")         # "mmol/L"
get_lab_unit("Creatinine") # "mg/dL"
get_lab_unit("eGFR")       # "mL/min/{1.73_m2}"  (UCUM annotation)
get_lab_unit("Plt")        # "10*3/uL"           (UCUM)
get_lab_unit("pH")         # "[pH]"
get_lab_unit("PT_INR")     # "{INR}"
get_lab_unit("Urinalysis") # "{qualitative}"
get_lab_unit("Unknown")    # ""
```

### `determine_flag(lab_name, value, sex="F", reference_ranges=None) -> str | None`

検査値に対する臨床フラグを返す (`engine.py:149`)。

```python
determine_flag("K",          5.8, "F")  # "H"
determine_flag("K",          6.8, "F")  # "critical"  (panic > 6.5)
determine_flag("Hb",         6.5, "M")  # "critical"  (panic < 7.0)
determine_flag("Hb",        14.2, "M")  # None
determine_flag("Creatinine", 1.5, "F")  # "H"         (F normal: 0.4–0.8)
determine_flag("Unknown",   99.9)       # None        (unknown → skip)
```

**Args**:
- `lab_name`, `value` — 検査名と観測値
- `sex` — `"M"` | `"F"` (性差のある試験でのみ使用)
- `reference_ranges` — dict を渡すと組込みデフォルトを上書き。 フォーマット: `{"CRP": {"all": (0, 3)}, "Hb": {"M": (13.5, 17.5), "F": (11.5, 15.5)}}`

**Returns**: `"H"` | `"L"` | `"critical"` | `None`

**判定順序**:
1. `panic` 辞書にエントリがあれば critical 境界を先にチェック
2. 次に参照範囲の low/high を見て `"L"` / `"H"` / `None`

組込みの default reference ranges (`engine.py:157`) は成人向け代表値 (CRP, WBC, Hb, Plt, Creatinine, BUN, Na, K, Glucose, Albumin, AST, ALT, Lactate, pH, PCT)。 国依存の基準範囲は `clinosim.locale.load_reference_ranges(country)` から取得して本関数に渡す。

**組込み panic values** (`engine.py:183`):

| Lab | Low (critical) | High (critical) |
|---|---|---|
| K | 2.5 | 6.5 |
| Hb | 7.0 | — |
| Glucose | 40 | 500 |
| Na | 120 | 160 |
| pH | 7.1 | 7.6 |

## データ構造

全てモジュールレベル定数 (`engine.py` 冒頭):

### `BIOLOGICAL_CV: dict[str, float]`

Ricos et al. desirable within-individual variation (30+ analytes)。例:

| Lab | CVi |
|---|---|
| Na | 0.006 |
| K | 0.046 |
| Creatinine | 0.056 |
| Glucose | 0.056 |
| CRP | 0.423 |
| BNP | 0.40 |
| Troponin | 0.14 |
| Lactate | 0.278 |

CRP や BNP のように絶対値のダイナミックレンジが広い炎症・心負荷マーカーは CVi が大きい。

### `ANALYTICAL_CV: dict[str, float]`

Modern analyzer imprecision (30+ analytes)。例:

| Lab | CVa |
|---|---|
| Na | 0.008 |
| K | 0.015 |
| Creatinine | 0.030 |
| CRP | 0.050 |
| Troponin | 0.080 |

### `PRECISION: dict[str, int]`

報告時の小数桁数。例:

| Lab | decimals |
|---|---|
| Na, Cl, Glucose, WBC, Plt, eGFR | 0 |
| K, Ca, Hb, Hct, CRP, Lactate, pH 以外 | 1 |
| pH, PCT | 2 |
| Troponin | 3 |

### `LAB_UNITS: dict[str, str]`

UCUM 単位テーブル (FHIR R4 Observation 互換)。例:

| Lab | UCUM | 備考 |
|---|---|---|
| Na | `mmol/L` |  |
| Creatinine | `mg/dL` |  |
| eGFR | `mL/min/{1.73_m2}` | UCUM annotation for body surface area |
| WBC | `/uL` | cell count per microliter |
| Plt | `10*3/uL` | UCUM (旧 "x10^3/uL") |
| pH | `[pH]` |  |
| pCO2, pO2 | `mm[Hg]` |  |
| PT_INR | `{INR}` | dimensionless annotation |
| TSH | `m[IU]/L` |  |
| Urinalysis, Urine_culture | `{qualitative}` |  |

### `_QUALITATIVE_TESTS: set[str]`

定性検査の判別セット:

```python
_QUALITATIVE_TESTS = {"Urinalysis", "Urine_culture", "Rapid_Strep", "Tetanus_status"}
```

カテゴリ結果は `_generate_qualitative_result()` (`engine.py:129`) が確率分布に従って文字列を返す:

| Test | 結果候補 |
|---|---|
| Urinalysis | Normal (55%), Trace protein, 1+ protein, Trace blood, 1+ leukocytes, Glucose 1+ |
| Urine_culture | No growth (55%), Mixed flora, E. coli >100K, Klebsiella >100K |
| Rapid_Strep | Negative (85%), Positive (15%) |
| Tetanus_status | Up to date (55%), Unknown, Last >10 years ago |

## 使用例

### Simulator 内でのフルパイプライン

```python
from clinosim.modules.observation.engine import (
    generate_lab_result, determine_flag, get_lab_unit,
)
from clinosim.locale.loader import load_reference_ranges
from clinosim.codes import lookup

# 1. 真値を physiology から取得
true_crp = derive_crp_from_inflammation(patient_state)   # e.g. 38.2

# 2. 観測値 + ノイズ
observed = generate_lab_result("CRP", true_crp, rng)

# 3. 国別基準範囲でフラグ判定
rr = load_reference_ranges("JP")  # JCCLS
flag = determine_flag("CRP", observed, sex=patient.sex,
                       reference_ranges=_adapt(rr["ranges"]))

# 4. CIF 出力 (コードと値と単位のみ)
lab_entry = {
    "code": "1988-5",                        # LOINC, from locale code_mapping
    "system": "loinc",
    "value": observed,
    "unit": get_lab_unit("CRP"),             # "mg/L"
    "flag": flag,                             # "H" | None | ...
}

# 5. FHIR 出力時に display を解決
display = lookup("loinc", lab_entry["code"], "ja")  # "C反応性蛋白"
```

### 定性検査

```python
result = generate_lab_result("Urine_culture", 0.0, rng)
# → "E. coli >100,000 CFU/mL"  (str)
unit = get_lab_unit("Urine_culture")     # "{qualitative}"
flag = determine_flag("Urine_culture", 0.0)  # None (unknown → skip)
```

## 拡張方法

### 新しい検査項目を追加する

`engine.py` の 4 つのモジュール辞書すべてに同じキーでエントリを追加:

```python
# 1. CVi (Ricos or equivalent)
BIOLOGICAL_CV["HbA1c"] = 0.018

# 2. CVa (instrument spec)
ANALYTICAL_CV["HbA1c"] = 0.015

# 3. Reporting precision
PRECISION["HbA1c"] = 1

# 4. UCUM unit
LAB_UNITS["HbA1c"] = "%"
```

未登録でも動くが、`CVi=5%`, `CVa=3%`, `decimals=1`, `unit=""` がデフォルト適用されるため 実データでは明示推奨。

### 新しい reference range を追加する

組込みデフォルト (`determine_flag` 内 `defaults` 辞書) に追加する、 または呼出側で `reference_ranges` 引数を渡す (locale モジュール推奨):

```python
# 組込み追加
defaults["HbA1c"] = {"all": (4.0, 6.4)}
defaults["Hb"]    = {"M": (13.5, 17.5), "F": (11.5, 15.5)}  # 性差対応

# パニック値
panic["Glucose"] = (40, 500)
```

### 新しい panic value を追加する

`determine_flag()` 内の `panic` 辞書に `(low, high)` タプルで追加。 どちらか片側のみなら `None` を入れる (例: `Hb` は critical low のみ)。

### 新しい定性検査を追加する

1. `_QUALITATIVE_TESTS` に名前を追加
2. `_generate_qualitative_result()` に if 分岐を追加してカテゴリ分布を定義
3. `LAB_UNITS[name] = "{qualitative}"` を追加

## 依存関係

本モジュールが依存するもの:

| 依存先 | 用途 |
|---|---|
| `numpy` | `Generator` によるノイズサンプリング |

**clinosim の他モジュールには依存しない** (純粋な stateless 計算層)。

本モジュールに依存する側:

| 依存側 | 用途 |
|---|---|
| `clinosim.simulator` | morning lab / ED workup 時に本 API を呼ぶ |
| `clinosim.modules.order` | オーダー処理の結果生成で呼ぶ |
| `clinosim.modules.encounter` | Daily cycle の `morning_labs` から呼ぶ |
| `clinosim.modules.clinical_course` | 日次状態更新後に観測値を生成 |

関連モジュール (併用):

| モジュール | 用途 |
|---|---|
| `clinosim.locale.load_reference_ranges` | 国別の reference range (JCCLS / Tietz) を取得して `determine_flag` に渡す |
| `clinosim.codes.lookup` | 検査名 display の多言語解決 |
| `clinosim.modules.physiology` | 真値 (inflammation → CRP 等) を提供する上流 |

## Consumers

このモジュールに依存するもの:

| Caller | How | Impact |
|---|---|---|
| `simulator/inpatient.py` | Pass-1 lab loop で `generate_lab_result()` + `canonical_lab_name()` + `lab_panel_components()` を呼出 | core (主 simulation loop) |
| `simulator/emergency.py` | ED visit で `generate_lab_result()` 呼出 | core |
| `simulator/outpatient.py` | outpatient followup で同上 | core |
| `simulator/enrichers.py` | nursing_enricher + microbiology 生成で observation を経由 | core (enricher registry) |
| `tests/integration/test_clinical_pipeline.py` | 臨床 pipeline integration test | guard |
| `tests/integration/test_nursing_enricher.py` | nursing flowsheet enricher test | guard |
| `tests/unit/test_observation.py` | engine unit tests | guard |
| `tests/unit/test_lab_panel_registry.py` | panel registry tests | guard |
| `tests/unit/test_blood_markers.py` | 血液 marker tests | guard |
| `tests/unit/test_microbiology.py` | microbiology tests | guard |
| `tests/unit/test_nursing.py` | nursing assessment tests | guard |
| `tests/unit/test_physiology.py` | physiology↔observation 連携 tests | guard |

## テスト

```bash
# 単体テスト (ノイズモデル + フラグ判定)
pytest tests/unit/test_observation.py -v
```

テスト観点:

- `apply_realistic_variability()` は同一 seed で同一値を返すこと (AD-16)
- 多数サンプルで CRP のノイズ分布が理論値 (true × sqrt(CVi² + CVa²)) に近いこと
- `round_to_precision()` が指定桁に正しく丸めること
- `determine_flag()`: K=6.8 → "critical", K=5.5 → "H", K=4.0 → None, K=2.0 → "critical"
- `generate_lab_result("Urinalysis", ...)` が文字列を返すこと
- `get_lab_unit()` 全エントリが UCUM valid (ucum-py で検証推奨)

## 実装状況

- [x] 3-layer variability model (CVi + CVa)
- [x] Reporting precision per analyte
- [x] UCUM units
- [x] H/L/critical flagging (性差対応)
- [x] Panic value detection (K, Hb, Glucose, Na, pH)
- [x] Qualitative tests (Urinalysis, Urine culture, Rapid Strep, Tetanus)
- [ ] Pre-analytical variation (tourniquet, posture, processing delay)
- [ ] Context-dependent missingness (night, refusal, difficult draw)
- [ ] Explainable anomaly patterns (hemolysis, IV contamination)
- [ ] Pregnancy-specific reference ranges

## 修正ガイド

### よくある修正シナリオ

| やりたいこと | 修正場所 | 影響範囲 |
|---|---|---|
| 新しい検査項目を追加 | (1) `BIOLOGICAL_CV`, `ANALYTICAL_CV`, `PRECISION` dict (2) `LAB_UNITS` dict (3) 任意で `PHYSIOLOGIC_LIMITS` dict (生存域上下限) (4) physiology の `derive_lab_values()` | FHIR Observation, narrative enrichment |
| 生理学クランプ範囲を調整 | `PHYSIOLOGIC_LIMITS` dict (`engine.py`) — アナライト別 `(lo, hi)` | 観測値の最大/最小テール |
| 参照範囲を変更 | `clinosim/locale/{jp,us}/reference_range_lab.yaml` | FHIR referenceRange, interpretation (AD-47) |
| フラグ判定ロジック変更 | `determine_flag()` | CIF flag → FHIR interpretation |
| CRP単位変換の調整 | ここでは変更しない — output モジュールの `_JA_CONVERSION` (AD-42) | |

### 関連モジュール・データフロー

```
physiology.derive_lab_values()
  ↓ true value (float)
observation.generate_lab_result(name, true_value, rng)
  ↓ + CVi + CVa + precision rounding
  ↓ observed value (float)
observation.determine_flag(name, value, sex)
  ↓ "H" / "L" / "H*" / "L*" / None
CIF OrderResult {value, unit, flag}
  ↓
fhir_r4_adapter._build_lab_observation()
  ↓ referenceRange (from locale YAML) + interpretation (recomputed from value vs range)
FHIR Observation
```

**重要**: FHIR adapter の interpretation は `OrderResult.flag` ではなく `value vs referenceRange` から再計算される (AD-47)。observation モジュールの flag はヒントとして使われるが、referenceRange との整合性が優先。

## 看護フローシート (AD-55 Base / AD-56 post_records)

### 概要

入院患者ごとに標準化された看護スコアを自動算出し、CIF・FHIR・CSV として出力する。
常時有効 (always-on Base enricher)。スコア計算は純粋関数で、実装はデータ駆動
(`reference_data/nursing_scores.yaml`)。

### 提供スコア

| スコア | 範囲 | 説明 | 権威出典 |
|---|---|---|---|
| **NEWS2** | 0–20 | National Early Warning Score 2。 RR / SpO2 / 体温 / 収縮期 BP / 心拍 / 意識 (AVPU) + 酸素投与の 7 要素 | Royal College of Physicians, 2017 |
| **GCS** | 3–15 | Glasgow Coma Scale total。AVPU → ベース値 + 灌流状態デクリメント + 小 jitter | Teasdale & Jennett, 1974 |
| **Braden** | 6–23 | 褥瘡リスク。感覚知覚・湿潤・活動性・可動性・栄養・摩擦ずれの 6 サブスケール。低スコア = 高リスク | Bergstrom et al., 1987 |
| **Morse Fall Scale** | 0–125 | 転倒リスク。転倒歴・IV ライン・歩行障害・認知状態に基づくスコア + リスクレベル (low/moderate/high) | Morse, 1989 |

### データ駆動設計

スコアのしきい値・バンド・重みはすべて
`clinosim/modules/observation/reference_data/nursing_scores.yaml` に集約されており、
Python コードを変更せずに閾値調整が可能。各スコアのセクション構造:

```yaml
news2:
  respiratory_rate:              # [low, high, points] バンドリスト
    - [null, 8, 3]
    - [12, 20, 0]
    ...
  consciousness:                 # AVPU 辞書 (A=0, V/P/U=3)
    A: 0
    ...
braden:
  barthel_to_subscale:           # Barthel (0-100) → サブスケール (1-4) 変換テーブル
    - [0, 1]
    ...
morse:
  history_of_falling: 25         # 項目別重み (公開済みスコアリング)
  risk_levels:
    - [25, "moderate"]
    ...
```

### Enricher 実行 (AD-56 post_records)

`clinosim/modules/observation/nursing_enricher.py` が Base enricher として
`simulator/enrichers.py` の `register_builtin_enrichers()` に登録されており、
`POST_RECORDS` ステージ (order=20) で実行される。

**決定論的サブシード (AD-16)**:
メインランダムストリームを汚染しないよう、`hashlib.sha256` ベースの専用サブシードを生成する。

```python
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed

rng = np.random.default_rng(
    derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["nursing"], patient_id)
)
```

オフセット定数(`0x4E55` = "NU")は `ENRICHER_SEED_OFFSETS` 中央 registry で管理(PR1 2026-06-24 foundation refactor)。重複は import 時 assert で検出。

患者 ID をキーとして patient ごとに独立した `numpy.random.Generator` を作成するため、
既存の labs/vitals 数値・診断・I/O は変化しない。

### API (nursing.py — 純粋関数)

| 関数 | シグネチャ | 説明 |
|---|---|---|
| `compute_news2` | `(vs: dict) -> int` | バイタルサイン dict から NEWS2 スコアを返す。完全決定論的 (rng 不要) |
| `compute_gcs` | `(consciousness_level: str, perfusion_status: float, rng) -> int` | AVPU + 灌流状態から GCS を返す |
| `compute_braden` | `(adl: dict, consciousness_level: str, volume_status: float, rng) -> dict` | Braden 6 サブスケール + total を dict で返す |
| `compute_morse_fall_risk` | `(age: int, adl: dict, consciousness_level: str, has_iv: bool, rng) -> tuple[int, str]` | Morse スコアとリスクレベルを返す |

### CIF 表現

**VitalSignRecord** (`clinosim/types/encounter.py`):

```python
@dataclass
class VitalSignRecord:
    ...
    news2_score: int | None = None   # NEWS2 集計値 (0-20)
    gcs_score:   int | None = None   # GCS 合計 (3-15)
```

**NursingRiskAssessment** (日次、`clinosim/types/encounter.py`):

```python
@dataclass
class NursingRiskAssessment:
    date:             date
    braden_total:     int   # 6-23; 低スコア = 高リスク
    braden_sensory:   int   # 1-4
    braden_moisture:  int   # 1-4
    braden_activity:  int   # 1-4
    braden_mobility:  int   # 1-4
    braden_nutrition: int   # 1-4
    braden_friction:  int   # 1-3
    morse_total:      int   # 0-125
    fall_risk_level:  str   # "low" | "moderate" | "high"
```

`CIFPatientRecord.nursing_risk_assessments: list[NursingRiskAssessment]` に格納される。

### FHIR 出力

`_build_nursing_observations()` が `_BUNDLE_BUILDERS` に登録されており、
`category=survey` の FHIR `Observation` リソースを生成する。

| 観測値 | LOINC | 備考 |
|---|---|---|
| GCS total | `9269-2` | NLM 照合済み |
| Braden scale total | `38227-5` | NLM 照合済み |
| Morse fall risk | `59460-6` | NLM 照合済み |
| Barthel index | `96761-2` | NLM 照合済み |
| Fluid intake (24 h) | `9108-2` | NLM 照合済み |
| Urine output (24 h) | `9192-6` | NLM 照合済み |
| Fluid output total (24 h) | `9262-7` | NLM 照合済み |
| **NEWS2** | *(なし)* | 権威 LOINC コードなし — `code.text` のみ発行 |

合計 7 コードを NLM ICD-10CM API / LOINC ブラウザで照合・確認済み。

### CSV 出力

| ファイル | 追加カラム / 備考 |
|---|---|
| `vital_signs.csv` | `news2_score`, `gcs_score` 列を追加 |
| `nursing_risk.csv` | 新規ファイル。`patient_id`, `date`, `braden_total`, `morse_total`, `fall_risk_level` |

### 権威出典

| スコア | 出典 |
|---|---|
| NEWS2 | Royal College of Physicians. *National Early Warning Score (NEWS) 2.* London: RCP, 2017. |
| GCS | Teasdale G, Jennett B. "Assessment of coma and impaired consciousness." *Lancet* 1974. |
| Braden | Bergstrom N et al. "The Braden Scale for Predicting Pressure Sore Risk." *Nursing Research* 1987. |
| Morse Fall Scale | Morse JM et al. "Identifying the needs of the elderly in the community." *Canadian Journal on Aging* 1989. |
| LOINC コード | NLM LOINC browser (`loinc.org`) — 全コード公式データベース照合済み |

---

## ラボ名の正規化・パネル展開・微生物 (AD-55 / AD-57)

`reference_data/`(データ駆動、コード変更不要):

- `lab_aliases.yaml` — オーダー名のバリアント → 正準 analyte。`canonical_lab_name(name)` が解決
  (例: `Troponin` / `Troponin_I_stat` / `Troponin_I_serial_6h` → `Troponin_I`、`ABG_repeat_1h` → `ABG`)。
- `lab_panels.yaml` — パネル → 構成要素。`lab_panel_components(name)` が返す
  (例: `ABG` → `[pH, pCO2, pO2, HCO3]`、`BMP` → canonical 8 = `[Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]`、
  `Coag` → `[PT, PT_INR, APTT]`、`LFT` → `[AST, ALT, ALP, T_Bil, Albumin, TP, GGT, LDH]`、
  `Lipid` → `[TC, LDL, HDL, TG]`、`UA` → `[Urine_pH, Urine_specific_gravity, ...]`)。
  simulator がパネルオーダーを構成要素オーダーに展開し、各要素が上記スカラー経路で結果化される。
  panel child の specimen-rejection / hemolysis は per-parent sub-RNG
  (`simulator/seeding.py:panel_specimen_seed`、AD-16/AD-59) で発生し、master stream を汚染しない。
  UA の urine analyte 群は urine physiology が未実装の間 silent-drop される(将来の UA-panel PR で対応)。
  panel order 展開源 (`lab_panels.yaml`) と FHIR DR 集約源 (`output/reference_data/lab_panel_groups.yaml`)
  は責任が違うので別ファイル(前者 = 入力、後者 = 出力)で持つ — 7 panel すべて両側に存在し対称。
- `microbiology.yaml` — 培養/感受性の起因菌・検体・抗菌薬コード + 疾患別分布 (`microbiology.py`)。

**venue 横断の真値源 (AD-57)**: 入院/ED/外来とも `physiology.derive_lab_values(state)` で真値生成し、
基礎疾患が全 venue に反映される。本モジュールは正準化・ノイズ・flag・単位・コード解決を担う。

### テスト

```bash
source .venv/bin/activate && python -m pytest tests/unit/test_observation.py -v
```
