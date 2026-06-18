# clinosim.locale — Locale-Specific Data Module

## 目的

clinosim において **国・文化・言語依存のデータの単一情報源** を提供する。

国際標準の臨床コード体系 (ICD / LOINC / RxNorm 等) は `clinosim/codes/` が担当し、本モジュールは **文化・地域・言語に依存するデータ** のみを担当する。典型例:

- 人名 (姓・名のプール + 頻度ウェイト + 読み仮名)
- 住所・電話フォーマット (都道府県 / state、ZIP / 郵便番号)
- 日付・時刻・計量単位の表記規則
- 人口統計 (年齢分布、血液型分布、慢性疾患有病率)
- 検査基準範囲 (JCCLS vs Tietz など地域差のあるもの)
- 慢性疾患の外来フォローアップ規則・在宅処方薬

国が増える = `locale/<country>/` フォルダと YAML を 1 セット追加するだけで済む設計。

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **1 国 = 1 フォルダ** | `jp/`, `us/` 等。ファイル名規約に従う限り、コード変更なしで追加可能 |
| 2 | **CIF は言語中立** | 生成時の人名だけが国依存。他は出力時に変換 (AD-25, AD-26) |
| 3 | **英語がマスター** | `terminology_*.yaml` は英語が base。他言語は翻訳 |
| 4 | **LLM 翻訳禁止** | 臨床用語は公式マスターデータのみ。LLM で翻訳しない (AD-27) |
| 5 | **LRU キャッシュ** | ローダーは `@lru_cache` により 1 回だけ YAML を読む |
| 6 | **Fallback chain** | ファイル無 → 組込み fallback → 空 dict (常に落ちない) |
| 7 | **責務分離** | 国際標準コードは `clinosim/codes/`、文化依存のみ本モジュール |

## ディレクトリ構造

```
clinosim/locale/
├── __init__.py
├── loader.py                  # 全データの単一アクセスポイント (LRU cached)
├── text.py                    # 多言語テキスト解決 (resolve_text)
├── README.md
├── jp/                        # 日本
│   ├── names.yaml             # 姓 (500), 男性名 (200), 女性名 (200) + 読み仮名
│   ├── addresses.yaml         # 東京都市圏ベッドタウン + 郵便番号
│   ├── demographics.yaml      # 年齢分布, 血液型, 慢性疾患有病率, 疾患罹患率
│   ├── formatting.yaml        # 日付・時刻・単位フォーマット
│   ├── code_mapping_lab.yaml      # 内部名 → JLAC10
│   ├── code_mapping_diagnosis.yaml # 内部 慢性/既往 base → ICD-10 (identity, WHO)
│   ├── code_mapping_drug.yaml      # 内部名 → YJ コード
│   ├── code_mapping_procedure.yaml # 内部名 → K コード
│   └── reference_range_lab.yaml    # JCCLS 共用基準範囲 2022
├── us/                        # 米国
│   ├── names.yaml             # 姓 (1083), 男性名 (324), 女性名 (377)
│   ├── addresses.yaml         # US state + ZIP
│   ├── demographics.yaml      # US Census / CDC / AHA
│   ├── formatting.yaml
│   ├── code_mapping_lab.yaml      # 内部名 → LOINC
│   ├── code_mapping_diagnosis.yaml # 内部 慢性/既往 base → billable ICD-10-CM
│   ├── code_mapping_drug.yaml      # 内部名 → RxNorm
│   ├── code_mapping_procedure.yaml # 内部名 → CPT
│   └── reference_range_lab.yaml    # Tietz Clinical Guide
└── shared/                    # 国を跨ぐ共通データ
    ├── naming_rules.yaml      # 10 か国の命名規則
    ├── chronic_medications.yaml # 16 慢性疾患の在宅薬 + モニタリング規則
    └── chronic_followup.yaml  # 16 慢性疾患の外来フォロー間隔
```

> **重要**: かつて本ディレクトリに存在した `terminology_lab.yaml` / `terminology_diagnosis.yaml` / `terminology_drug.yaml` / `terminology_procedure.yaml` は、**`clinosim/codes/data/` に移設された**。 現在 locale モジュールは **display 表示テキストを保持しない** — それは codes モジュール経由で lookup する。 `code_mapping_*.yaml` (内部シミュレータ名 → 標準コード) のみが locale 下に残っている。

## 権威ソース

| データ | 日本 (JP) | 米国 (US) |
|---|---|---|
| **人名頻度** | 総務省統計・電話帳 (姓) / 昭和〜令和の出生届データ (名) | US Census Bureau (姓) / SSA baby names (名) |
| **住所・ZIP** | JIS X 0401 都道府県コード / 日本郵便 郵便番号マスター | USPS ZIP / US State abbreviations |
| **人口統計** | 総務省統計局 (年齢分布), 日本赤十字 (血液型), 厚生労働省 患者調査 | US Census Bureau 2020 / CDC NHANES / AHA |
| **検査基準範囲** | [JCCLS 共用基準範囲 2022](https://www.jccls.org/wp-content/uploads/2022/10/kijyunhani20221031.pdf) | Tietz Clinical Guide to Laboratory Tests (Saunders) |
| **慢性薬・FU** | JCS (循環器), 日本糖尿病学会, KDIGO, GOLD | AHA/ACC, ADA, KDIGO, GOLD |

## API リファレンス

全 API は `clinosim.locale.loader` に集約されており、 LRU キャッシュ付きのため何度呼んでも実際の YAML 読み込みは 1 回のみ。

### `load_names(country: str) -> dict[str, Any]`

姓・名リストと頻度ウェイトを返す。

```python
from clinosim.locale.loader import load_names

data = load_names("JP")
# data = {
#   "surnames": [{"kanji": "佐藤", "kana": "サトウ", "weight": 1880}, ...],
#   "given_names_male":   [{"kanji": "...", "kana": "...", "weight": ...}, ...],
#   "given_names_female": [...],
# }

data_us = load_names("US")
# data_us = {"surnames": [{"name": "Smith", "weight": ...}, ...], ...}
```

ファイルが存在しない場合は `_FALLBACK_NAMES` (Test / John / Jane) を返す。

### `load_naming_rules(country: str) -> dict[str, Any]`

`shared/naming_rules.yaml` から国別セクションを取り出す (10 か国対応)。

```python
rules = load_naming_rules("JP")
# {"family_name_first": True, "separator": " ", ...}
```

国が未定義の場合は `"us"` セクションへフォールバック。

### `load_terminology(domain: str, country: str) -> dict[str, str]`

**非推奨 (deprecated)**: 表示テキストは `clinosim/codes/` に移管。このローダーは後方互換のため残っているが、新規コードは `clinosim.codes.lookup()` を使うこと。

```python
# 旧: load_terminology("lab", "JP").get("CRP")  -> "C反応性蛋白"
# 新: lookup("loinc", "1988-5", "ja")          -> "C反応性蛋白"
```

### `load_code_mapping(domain: str, country: str) -> dict[str, str]`

シミュレータ内部の test name (例: `"CRP"`, `"WBC"`) を locale 依存の標準コードに変換するマップを返す。`domain` は `"lab"` / `"diagnosis"` / `"drug"` / `"procedure"` のいずれか。

```python
from clinosim.locale.loader import load_code_mapping

jp_lab = load_code_mapping("lab", "JP")
# {"CRP": "5C070", "WBC": "2A010", "Hb": "2A020", ...}  (JLAC10)

us_lab = load_code_mapping("lab", "US")
# {"CRP": "1988-5", "WBC": "6690-2", ...}               (LOINC)
```

**`"diagnosis"` domain** — 診断コードは慢性/既往の base コード (例 `I50`, `E78`, `I21`) を
locale の請求可能コードへ変換する。FHIR adapter の `_build_conditions` が primary・chronic
両方の Condition コードに適用 (マップに無いコードは passthrough; 疾患 primary は既に具体的)。

```python
us_dx = load_code_mapping("diagnosis", "US")
# {"E78": "E78.5", "I50": "I50.9", "I21": "I25.2"(陳旧性MI), "R05": "R05.9", ...}  billable ICD-10-CM
jp_dx = load_code_mapping("diagnosis", "JP")
# {"E78": "E78", "I50": "I50", ...}  identity (WHO ICD-10 カテゴリコードは有効、出力不変)
```

> 内部 base コードが慢性歴に入る経路は `simulator/helpers.py` (退院 dx を base 切詰め + 慢性
> prefix 一致で追加)。過去の急性イベント (MI=I21, 脳梗塞=I63 等) は US で「既往 (history/old)」
> コードへ (I21→I25.2, I63→Z86.73)。全ターゲットは NLM ICD-10-CM API で照合済 (捏造禁止)。

シミュレータは内部で `"CRP"` のような人間可読名を使い、CIF 出力時に本マップで国別コードに解決する。

### `load_formatting(country: str) -> dict[str, Any]`

日付・時刻・計量単位の表記規則。

```python
fmt = load_formatting("US")
# {"date_format": "MM/dd/yyyy", "time_format": "12h",
#  "temperature_unit": "F", "weight_unit": "lb", "height_unit": "in"}

fmt = load_formatting("JP")
# {"date_format": "yyyy/MM/dd", "time_format": "24h",
#  "temperature_unit": "C", "weight_unit": "kg", "height_unit": "cm"}
```

### `load_demographics(country: str) -> dict[str, Any]`

人口ピラミッド・血液型分布・慢性疾患有病率・疾患罹患率・季節性モディファイア等を返す population モジュールの主要入力。

```python
demo = load_demographics("US")
# demo["age_distribution"]       -> {"0-14": 0.18, ..., "85-99": 0.02}
# demo["blood_type"]             -> {"O": 0.44, "A": 0.42, "B": 0.10, "AB": 0.04}
# demo["chronic_prevalence"]     -> {"I10": {"40-99": 0.33}, ...}  (ICD-10 code)
# demo["disease_incidence"]      -> {"J18.9": ..., ...}
# demo["seasonal_modifiers"]     -> month-based multipliers
```

### `load_addresses(country: str) -> dict[str, Any]`

住所生成に必要な地理データ (都道府県 / state、市区町村 / city、郵便番号 / ZIP + 人口ウェイト)。

```python
addr = load_addresses("JP")
# {"state": "東京都", "country": "JP",
#  "cities": [{"city": "世田谷区", "prefecture": "東京都",
#              "zips": ["154-0001", ...], "weight": 15}, ...]}
```

### `load_reference_ranges(country: str) -> dict[str, Any]`

検査の地域別基準範囲。観察 (observation) モジュールが flag 判定 (H/L/N) で参照する。

```python
rr = load_reference_ranges("JP")
# {
#   "source_url":  "https://www.jccls.org/wp-content/uploads/2022/10/kijyunhani20221031.pdf",
#   "source_name": "JCCLS共用基準範囲2022",
#   "ranges": {
#     "WBC": [{"low": 3300, "high": 8600, "unit": "/uL", "text": "..."}],
#     "Hb":  [{"low": 13.7, "high": 16.8, "unit": "g/dL", "sex": "M", ...},
#             {"low": 11.6, "high": 14.8, "unit": "g/dL", "sex": "F", ...}],
#     ...
#   }
# }
```

性差がある検査 (Hb, Hct, Creatinine 等) はリスト形式で `sex: "M" | "F"` エントリを複数持つ。

### `load_chronic_followup() -> dict[str, Any]`

16 慢性疾患の **外来フォローアップ規則** (国共通)。

```python
fu = load_chronic_followup()
# fu["I10"]["follow_up_interval_months"] = 1
# fu["I10"]["labs_annual"] = ["Creatinine", "K", "Na"]
# fu["E11.9"]["labs_quarterly"] = ["HbA1c", "Creatinine"]
```

### `load_chronic_medications() -> dict[str, Any]`

16 慢性疾患の **在宅薬とモニタリング規則** (国共通)。 入院中も継続される。

```python
med = load_chronic_medications()
# med["I10"]["medications"] = [
#   {"drug": "Amlodipine 5mg", "route": "PO", "frequency": "daily"},
#   {"drug": "Candesartan 8mg", ..., "probability": 0.5},
# ]
# med["I10"]["hold_conditions"] = [
#   {"drug": "Amlodipine 5mg", "condition": "SBP < 90",
#    "field": "systolic_bp", "threshold": 90, "direction": "below"}, ...
# ]
```

### `clinosim.locale.text.resolve_text(value, language="", country="") -> str`

YAML 内に混在する **文字列フィールド** と **多言語 dict フィールド** の両方を扱うヘルパー。

対応フォーマット:

```yaml
# 形式 1: 直接文字列 (後方互換)
chief_complaint: "Chest pain"

# 形式 2: 言語別 dict
chief_complaint:
  en: "Chest pain"
  ja: "胸痛"
```

```python
from clinosim.locale.text import resolve_text

resolve_text("Chest pain", country="JP")
# → "Chest pain" (直接文字列はそのまま)

resolve_text({"en": "Chest pain", "ja": "胸痛"}, country="JP")
# → "胸痛"

resolve_text({"en": "Chest pain"}, country="JP")
# → "Chest pain" (ja が無い → en フォールバック)

resolve_text(None)
# → ""
```

解決順序: 要求 `language` → `country` → `en` → dict 内最初の文字列 → `str(value)`。

## 使用例: patient module での呼び出し

```python
from clinosim.locale.loader import (
    load_names, load_addresses, load_demographics,
    load_chronic_medications, load_reference_ranges,
)

# 名前生成
names = load_names(country)
surname = rng.choice([s for s in names["surnames"]],
                     p=[s["weight"] for s in names["surnames"]])

# 住所生成
addr_data = load_addresses(country)
city = rng.choice(addr_data["cities"], p=weights)
zip_code = rng.choice(city["zips"])

# 慢性疾患の有病率サンプリング
demo = load_demographics(country)
for icd, by_age in demo["chronic_prevalence"].items():
    prev = by_age.get(age_bucket(age), 0.0)
    if rng.random() < prev:
        patient.chronic_conditions.append(icd)

# 在宅薬の付与
chronic_meds = load_chronic_medications()
for icd in patient.chronic_conditions:
    for m in chronic_meds.get(icd, {}).get("medications", []):
        if "probability" not in m or rng.random() < m["probability"]:
            patient.home_medications.append(m)
```

## データ構造

典型的な YAML スキーマ (`names.yaml`, `demographics.yaml` など) は各ファイルの先頭コメントに記載されている。主要なもの:

### `names.yaml` (JP)

```yaml
surnames:
  - {kanji: "佐藤", kana: "サトウ", weight: 1880}
given_names_male:
  - {kanji: "太郎", kana: "タロウ", weight: 120}
given_names_female:
  - {kanji: "花子", kana: "ハナコ", weight: 100}
```

### `demographics.yaml`

```yaml
age_distribution: {"0-14": 0.18, ..., "85-99": 0.02}
blood_type: {O: 0.44, A: 0.42, B: 0.10, AB: 0.04}
chronic_prevalence:
  I10:  {"40-99": 0.33}     # ICD-10 code → age range → probability
disease_incidence: {...}
seasonal_modifiers: {...}
```

### `reference_range_lab.yaml`

```yaml
source_url: "..."
source_name: "JCCLS共用基準範囲2022"
ranges:
  WBC: [{low: 3300, high: 8600, unit: "/uL", text: "..."}]
  Hb:  [{low: 13.7, high: 16.8, unit: "g/dL", sex: "M", ...},
        {low: 11.6, high: 14.8, unit: "g/dL", sex: "F", ...}]
  # ⚠️ キーは canonical 分析物名 (observation engine / code_mapping_lab.yaml と同一)。
  # 例: 心筋トロポニンは "Troponin_I" であって "Troponin" ではない。不一致だと FHIR
  # adapter の referenceRange 解決が失敗し interpretation も付かない。
  Troponin_I: [{low: 0, high: 0.04, unit: "ng/mL", text: "..."}]
  CK_MB:      [{low: 0, high: 5.0,  unit: "ng/mL", text: "..."}]
```

FHIR adapter (`_build_reference_range`) はこの `ranges[<canonical 名>]` を引いて
数値 Observation に `referenceRange` を付け、`interpretation` を値と範囲から再計算する
(AD-47)。キーが分析物名と一致しない検査は範囲も interpretation も欠落する。

## 拡張方法

### 新しい国を追加する

1. `locale/<country>/` フォルダを作る (ISO 3166-1 alpha-2 小文字を推奨)
2. 最低限以下の YAML を追加:
   - `names.yaml` — 姓・名 + 頻度
   - `addresses.yaml` — 地理・ZIP
   - `demographics.yaml` — 年齢分布・血液型・慢性疾患有病率
   - `formatting.yaml` — 日付・時刻・単位
   - `code_mapping_lab.yaml` / `_diagnosis.yaml` / `_drug.yaml` / `_procedure.yaml`
   - `reference_range_lab.yaml` — 公的な基準範囲ソース付き
3. `shared/naming_rules.yaml` に国別セクションを追加
4. `loader.py` の `_COUNTRY_DIR_MAP` に `"<ISO>": "<dirname>"` を追加 (国コードがそのままディレクトリ名ならスキップ可)
5. コード変更はこれで終わり。他モジュールは自動的に新国に対応する

### 新しい基準範囲を追加する

`<country>/reference_range_lab.yaml` の `ranges:` に試験名を追加し、 権威ソース (JCCLS / Tietz 等) の URL を `source_url` に明記する。 性差がある場合はリスト形式で複数エントリを登録する。

### 新しい慢性疾患を追加する

`shared/chronic_medications.yaml` と `shared/chronic_followup.yaml` の両方に ICD-10 コードキーでエントリを追加。 同コードを各 locale の `demographics.yaml > chronic_prevalence` にも追加し、 年齢帯別の有病率を定義する。

## 依存関係

本モジュールは **他のモジュールに依存しない** (ドメインデータの最下層)。逆に多くのモジュールが本モジュールに依存する:

| 依存側モジュール | 使う API | 用途 |
|---|---|---|
| `patient` | `load_names`, `load_addresses`, `load_chronic_medications`, `load_demographics` | Layer 2 活性化 |
| `population` | `load_demographics` | PersonRecord 生成 |
| `observation` | `load_reference_ranges`, `load_code_mapping` | 検査値の flag 判定 + コード解決 |
| `order` | `load_code_mapping` | 処方・検査オーダーのコード変換 |
| `disease` / `encounter` | (indirectly) | 疾患 YAML の多言語フィールドで `resolve_text` を使用 |
| `simulator` | `load_chronic_followup` | 外来フォローアップ駆動 |
| `output/fhir_r4_adapter` | `load_formatting` | 日付フォーマット |

**依存しないもの**: `clinosim.codes` は本モジュールに依存しない (コード体系は locale 非依存)。逆に本モジュールも `clinosim.codes` に依存しない (純データ層同士の並列関係)。 表示テキスト解決が必要な呼び出し側 (FHIR アダプタ等) は両モジュールを **併用** する。

## テスト

```bash
# 単体テスト (ローダー + fallback)
pytest tests/unit/test_locale.py

# patient モジュール経由 (locale を実際に使う)
pytest tests/unit/test_patient.py

# すべてのモジュール単体テスト
make test-unit
```

データ妥当性チェック:

```python
from clinosim.locale.loader import load_demographics

demo = load_demographics("JP")
# age_distribution は合計 1.0 であること
assert abs(sum(demo["age_distribution"].values()) - 1.0) < 0.01
# blood_type も同様
assert abs(sum(demo["blood_type"].values()) - 1.0) < 0.01
```

新しい国を追加したら上記チェックを手動で実行すること。

## Key rules (AD-25, AD-26, AD-27)

- **AD-25**: CIF は言語中立。生成時点で国依存になるのは人名のみ
- **AD-26**: 全ての locale データはここに集約。他モジュールに散在させない
- **AD-27**: 臨床用語は公式マスターデータのみ。LLM 翻訳禁止
