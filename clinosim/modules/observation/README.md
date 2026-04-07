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
| 4 | **Negative-safe** | 観測値が負になる場合は 0 にクリップ |
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
